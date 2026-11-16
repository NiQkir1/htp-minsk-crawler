package main

import (
	"bytes"
	"context"
	"crypto/tls"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"flag"
	"fmt"
	"html"
	"io"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// Resident represents a company in HTP (ПВТ) and its crawled recruitment contacts.
type Resident struct {
	ParkURL        string   `json:"park_url"`
	Name           string   `json:"name"`
	FullName       string   `json:"full_name"`
	UNP            string   `json:"unp"`
	City           string   `json:"city"`
	Address        string   `json:"address"`
	StaffCount     string   `json:"staff_count"`
	FoundedYear    string   `json:"founded_year"`
	Phone          string   `json:"phone"`
	ParkEmail      string   `json:"park_email"`
	Website        string   `json:"website"`
	Directions     []string `json:"directions"`
	Industries     []string `json:"industries"`
	Description    string   `json:"description"`
	IsMinsk        bool     `json:"is_minsk"`
	IsITTarget     bool     `json:"is_it_target"`
	HREmails       []string `json:"hr_emails"`
	OtherEmails    []string `json:"other_emails"`
	Telegrams      []string `json:"telegrams"`
	LinkedIns      []string `json:"linkedins"`
	CareerPages    []string `json:"career_pages"`
	JobBoardLinks  []string `json:"job_board_links"`
	MatchedRoles   []string `json:"matched_roles"`
	RelevanceScore int      `json:"relevance_score"`
	CrawlStatus    string   `json:"crawl_status"`
}

const userAgent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

var (
	reLoc         = regexp.MustCompile(`<loc>(https?://[^<]+)</loc>`)
	reH1Title     = regexp.MustCompile(`(?s)<h1[^>]*class=["'][^"']*title[^"']*["'][^>]*>(.*?)</h1>`)
	reFullName    = regexp.MustCompile(`(?s)<div[^>]*class=["'][^"']*full-name[^"']*["'][^>]*>(.*?)</div>`)
	rePreviewText = regexp.MustCompile(`(?s)<div[^>]*class=["'][^"']*preview-text[^"']*["'][^>]*>(.*?)</div>`)
	reInfoItem    = regexp.MustCompile(`(?s)<div\s+class=["']info-item["']>\s*<div\s+class=["']info-title["']>(.*?)</div>\s*<div\s+class=["']info-value["']>(.*?)</div>\s*</div>`)
	reLi          = regexp.MustCompile(`(?s)<li[^>]*>(.*?)</li>`)
	reHref        = regexp.MustCompile(`(?i)href\s*=\s*["']([^"']+)["']`)
	reAnchor      = regexp.MustCompile(`(?is)<a\s+[^>]*href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>`)
	reTags        = regexp.MustCompile(`<[^>]+>`)
	reSpaces      = regexp.MustCompile(`\s+`)

	// Contact extractors
	reMailto  = regexp.MustCompile(`(?i)mailto:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,24})`)
	reEmail   = regexp.MustCompile(`(?i)\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,24})\b`)
	reObfMail = regexp.MustCompile(`(?i)\b([a-zA-Z0-9._%+\-]+)\s*(?:\[at\]|\(at\)|\s+at\s+)\s*([a-zA-Z0-9.\-]+)\s*(?:\[dot\]|\(dot\)|\.)\s*([a-zA-Z]{2,12})\b`)
	reCfEmail = regexp.MustCompile(`data-cfemail=["']([0-9a-fA-F]+)["']`)

	// Telegram links: t.me/username, telegram.me/username, tg://resolve?domain=username
	reTgLink   = regexp.MustCompile(`(?i)(?:https?://)?(?:www\.)?(?:t\.me|telegram\.me|telegram\.dog)/(?:s/)?([a-zA-Z0-9_]{4,64}|\+[a-zA-Z0-9_\-]+|joinchat/[a-zA-Z0-9_\-]+)`)
	reTgDomain = regexp.MustCompile(`(?i)tg://resolve\?domain=([a-zA-Z0-9_]{4,64})`)
	reTgText   = regexp.MustCompile(`(?i)(?:telegram|телеграм|телеграмм|тг|tg)\s*[:\-–—]?\s*@([a-zA-Z0-9_]{4,32})\b`)

	// LinkedIn & Job boards
	reLinkedIn = regexp.MustCompile(`(?i)https?://(?:[a-z]{2,3}\.)?linkedin\.com/(?:company|in)/[a-zA-Z0-9_\-%]+`)
	reJobBoard = regexp.MustCompile(`(?i)https?://(?:[a-z0-9.]*\.)?(?:rabota\.by|hh\.ru|devby\.io|dev\.by|career\.habr\.com|praca\.by)/(?:employer|companies|company)/[a-zA-Z0-9_\-]+`)

	// Tech stack regexes
	reCSharp = regexp.MustCompile(`(?i)(?:\bc#|c-sharp|\.net\b|dotnet|asp\.net)`)
	reGolang = regexp.MustCompile(`(?i)(?:\bgolang\b|\bgo\s+developer|\bgo\s+engineer|\bgo\s+backend|разработчик\s+go\b|go-разработчик|\bgo/c#|\bc#/go\b)`)
	reSysAna = regexp.MustCompile(`(?i)(?:системн[а-я]+\s+аналит|бизнес[\-\s]+аналит|system[s]?\s+analyst|business\s+analyst|\bsystem\s+analysis\b|\bba/sa\b)`)
	reJunMid = regexp.MustCompile(`(?i)(?:\bjunior\b|\bmiddle\b|джуниор|мидл|миддл|стажировк|стажер|\bintern\b|\binternship\b|\btrainee\b)`)
)

func main() {
	workersPark := flag.Int("park-workers", 25, "Concurrent workers for park.by")
	workersSite := flag.Int("site-workers", 35, "Concurrent workers for external company websites")
	refreshPark := flag.Bool("refresh-park", false, "Force re-crawling park.by even if cache exists")
	maxPagesPerSite := flag.Int("max-pages", 6, "Max internal career/contact pages to crawl per company website")
	flag.Parse()

	start := time.Now()
	fmt.Println("=== HTP Minsk (ПВТ) Recruiter Email & Telegram Crawler ===")

	clientPark := newHTTPClient(15 * time.Second)
	clientSite := newHTTPClient(9 * time.Second)

	cacheFile := "residents_park_raw.json"
	var residents []*Resident

	if !*refreshPark {
		if data, err := os.ReadFile(cacheFile); err == nil && len(data) > 100 {
			if err := json.Unmarshal(data, &residents); err == nil && len(residents) > 0 {
				fmt.Printf("[Stage 1] Loaded %d residents from cache (%s)\n", len(residents), cacheFile)
			}
		}
	}

	if len(residents) == 0 {
		fmt.Println("[Stage 1] Discovering resident URLs from https://park.by/sitemap-iblock-170.xml ...")
		urls, err := fetchParkResidentURLs(clientPark)
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error fetching resident URLs: %v\n", err)
			os.Exit(1)
		}
		fmt.Printf("[Stage 1] Found %d resident pages on park.by. Crawling details with %d workers...\n", len(urls), *workersPark)
		residents = crawlParkDetails(clientPark, urls, *workersPark)

		if rawBytes, err := json.MarshalIndent(residents, "", "  "); err == nil {
			_ = os.WriteFile(cacheFile, rawBytes, 0644)
			fmt.Printf("[Stage 1] Saved %d residents to %s\n", len(residents), cacheFile)
		}
	}

	// Count stats from Stage 1
	minskCount := 0
	withWebsite := 0
	for _, r := range residents {
		if r.IsMinsk {
			minskCount++
		}
		if r.Website != "" {
			withWebsite++
		}
	}
	fmt.Printf("[Stage 1 Summary] Total residents: %d | Minsk: %d | With website: %d\n", len(residents), minskCount, withWebsite)

	// Stage 2: Crawl company websites + career/contacts pages
	fmt.Printf("[Stage 2] Crawling company websites and /career, /vacancies, /contacts pages (%d workers, max %d pages/site)...\n", *workersSite, *maxPagesPerSite)
	crawlCompanyWebsites(clientSite, residents, *workersSite, *maxPagesPerSite)

	// Compute relevance score and sort
	for _, r := range residents {
		computeRelevance(r)
	}

	sort.Slice(residents, func(i, j int) bool {
		if residents[i].RelevanceScore != residents[j].RelevanceScore {
			return residents[i].RelevanceScore > residents[j].RelevanceScore
		}
		return residents[i].Name < residents[j].Name
	})

	// Save outputs
	if err := saveOutputs(residents); err != nil {
		fmt.Fprintf(os.Stderr, "Error saving outputs: %v\n", err)
		os.Exit(1)
	}

	fmt.Printf("\nDone in %s!\n", time.Since(start).Round(time.Second))
}

func newHTTPClient(timeout time.Duration) *http.Client {
	tr := &http.Transport{
		TLSClientConfig:     &tls.Config{InsecureSkipVerify: true},
		MaxIdleConns:        200,
		MaxIdleConnsPerHost: 10,
		IdleConnTimeout:     30 * time.Second,
		DisableKeepAlives:   false,
	}
	return &http.Client{
		Transport: tr,
		Timeout:   timeout,
		CheckRedirect: func(req *http.Request, via []*http.Request) error {
			if len(via) >= 7 {
				return fmt.Errorf("too many redirects")
			}
			return nil
		},
	}
}

func fetchHTML(ctx context.Context, client *http.Client, targetURL string) (string, string, error) {
	req, err := http.NewRequestWithContext(ctx, "GET", targetURL, nil)
	if err != nil {
		return "", "", err
	}
	req.Header.Set("User-Agent", userAgent)
	req.Header.Set("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
	req.Header.Set("Accept-Language", "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7")

	resp, err := client.Do(req)
	if err != nil {
		return "", "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode >= 400 {
		return "", "", fmt.Errorf("HTTP %d", resp.StatusCode)
	}

	// Read up to 2.5 MB
	bodyBytes, err := io.ReadAll(io.LimitReader(resp.Body, 2500000))
	if err != nil {
		return "", "", err
	}

	contentType := strings.ToLower(resp.Header.Get("Content-Type"))
	text := decodeBytes(bodyBytes, contentType)
	finalURL := resp.Request.URL.String()
	return text, finalURL, nil
}

// decodeBytes handles UTF-8 and Windows-1251 fallback for older .by sites.
func decodeBytes(b []byte, contentType string) string {
	lowerHead := strings.ToLower(string(b[:min(len(b), 2048)]))
	if strings.Contains(contentType, "windows-1251") || strings.Contains(contentType, "cp1251") ||
		strings.Contains(lowerHead, "windows-1251") || strings.Contains(lowerHead, "cp1251") {
		return decodeCP1251(b)
	}
	return string(b)
}

func decodeCP1251(b []byte) string {
	var buf bytes.Buffer
	buf.Grow(len(b) * 2)
	for _, c := range b {
		if c < 0x80 {
			buf.WriteByte(c)
		} else if c >= 0xC0 {
			buf.WriteRune(rune(0x0410 + int(c) - 0xC0))
		} else if c == 0xA8 {
			buf.WriteRune('Ё')
		} else if c == 0xB8 {
			buf.WriteRune('ё')
		} else {
			buf.WriteRune(' ')
		}
	}
	return buf.String()
}

func fetchParkResidentURLs(client *http.Client) ([]string, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()

	xmlText, _, err := fetchHTML(ctx, client, "https://park.by/sitemap-iblock-170.xml")
	if err != nil {
		return nil, err
	}

	matches := reLoc.FindAllStringSubmatch(xmlText, -1)
	seen := make(map[string]bool)
	var urls []string
	for _, m := range matches {
		u := strings.TrimSpace(m[1])
		if u == "https://park.by/residents/" || u == "https://www.park.by/residents/" || !strings.Contains(u, "/residents/") {
			continue
		}
		if !seen[u] {
			seen[u] = true
			urls = append(urls, u)
		}
	}
	return urls, nil
}

func crawlParkDetails(client *http.Client, urls []string, workers int) []*Resident {
	type job struct {
		idx int
		url string
	}
	jobs := make(chan job, len(urls))
	results := make([]*Resident, len(urls))

	var doneCount int64
	var wg sync.WaitGroup

	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range jobs {
				ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
				body, _, err := fetchHTML(ctx, client, j.url)
				cancel()

				if err != nil {
					// Retry once
					time.Sleep(400 * time.Millisecond)
					ctx2, cancel2 := context.WithTimeout(context.Background(), 15*time.Second)
					body, _, err = fetchHTML(ctx2, client, j.url)
					cancel2()
				}

				if err == nil && body != "" {
					results[j.idx] = parseParkResidentPage(j.url, body)
				} else {
					results[j.idx] = &Resident{
						ParkURL:     j.url,
						CrawlStatus: "park_error: " + fmt.Sprint(err),
					}
				}

				cur := atomic.AddInt64(&doneCount, 1)
				if cur%100 == 0 || int(cur) == len(urls) {
					fmt.Printf("  [Stage 1] Crawled %d / %d park.by pages\n", cur, len(urls))
				}
			}
		}()
	}

	for i, u := range urls {
		jobs <- job{idx: i, url: u}
	}
	close(jobs)
	wg.Wait()

	var clean []*Resident
	for _, r := range results {
		if r != nil && r.Name != "" {
			clean = append(clean, r)
		}
	}
	return clean
}

func cleanText(s string) string {
	s = reTags.ReplaceAllString(s, " ")
	s = html.UnescapeString(s)
	s = strings.ReplaceAll(s, "\u00a0", " ")
	s = reSpaces.ReplaceAllString(s, " ")
	return strings.TrimSpace(s)
}

func parseParkResidentPage(pageURL, body string) *Resident {
	r := &Resident{
		ParkURL: pageURL,
	}

	if m := reH1Title.FindStringSubmatch(body); len(m) > 1 {
		r.Name = cleanText(m[1])
	}
	if m := reFullName.FindStringSubmatch(body); len(m) > 1 {
		r.FullName = cleanText(m[1])
	}
	if m := rePreviewText.FindStringSubmatch(body); len(m) > 1 {
		r.Description = cleanText(m[1])
	}

	items := reInfoItem.FindAllStringSubmatch(body, -1)
	for _, it := range items {
		title := cleanText(it[1])
		valHTML := it[2]
		valText := cleanText(valHTML)

		switch title {
		case "УНП":
			r.UNP = valText
		case "Количество сотрудников":
			r.StaffCount = valText
		case "Город":
			r.City = valText
		case "Юридический адрес":
			r.Address = valText
		case "Контактный телефон":
			r.Phone = valText
		case "Адрес электронной почты":
			r.ParkEmail = valText
		case "Веб-сайт":
			if hm := reHref.FindStringSubmatch(valHTML); len(hm) > 1 {
				r.Website = normalizeWebsiteURL(hm[1])
			} else {
				r.Website = normalizeWebsiteURL(valText)
			}
		case "Год основания":
			r.FoundedYear = valText
		case "Направления деятельности":
			lis := reLi.FindAllStringSubmatch(valHTML, -1)
			for _, li := range lis {
				if t := cleanText(li[1]); t != "" {
					r.Directions = append(r.Directions, t)
				}
			}
		case "Отрасль применения":
			lis := reLi.FindAllStringSubmatch(valHTML, -1)
			for _, li := range lis {
				if t := cleanText(li[1]); t != "" {
					r.Industries = append(r.Industries, t)
				}
			}
		}
	}

	// Determine if Minsk
	cityLower := strings.ToLower(r.City)
	addrLower := strings.ToLower(r.Address)
	if strings.Contains(cityLower, "минск") || strings.Contains(addrLower, "минск") || r.City == "" {
		r.IsMinsk = true
	}

	// Extract any emails/telegrams already present in ParkEmail or Description
	emailSet := make(map[string]bool)
	tgSet := make(map[string]bool)
	liSet := make(map[string]bool)
	jbSet := make(map[string]bool)

	if r.ParkEmail != "" {
		extractContactsFromText(r.ParkEmail, emailSet, tgSet, liSet, jbSet)
	}
	if m := rePreviewText.FindStringSubmatch(body); len(m) > 1 {
		extractContactsFromText(m[1], emailSet, tgSet, liSet, jbSet)
	}

	classifyEmails(emailSet, r)
	r.Telegrams = mapKeysSorted(tgSet)
	r.LinkedIns = mapKeysSorted(liSet)
	r.JobBoardLinks = mapKeysSorted(jbSet)

	return r
}

func normalizeWebsiteURL(raw string) string {
	raw = strings.TrimSpace(html.UnescapeString(raw))
	if raw == "" {
		return ""
	}
	// If multiple URLs separated by comma or space, take first
	fields := strings.FieldsFunc(raw, func(r rune) bool {
		return r == ',' || r == ';' || r == ' ' || r == '\n' || r == '\t'
	})
	if len(fields) == 0 {
		return ""
	}
	u := strings.TrimSpace(fields[0])
	u = strings.TrimRight(u, ".,;/")
	if !strings.HasPrefix(strings.ToLower(u), "http://") && !strings.HasPrefix(strings.ToLower(u), "https://") {
		u = "https://" + u
	}
	parsed, err := url.Parse(u)
	if err != nil || parsed.Host == "" {
		return ""
	}
	return parsed.String()
}

func crawlCompanyWebsites(client *http.Client, residents []*Resident, workers int, maxPages int) {
	jobs := make(chan *Resident, len(residents))
	var doneCount int64
	var totalWithSites int64
	for _, r := range residents {
		if r.Website != "" {
			totalWithSites++
		} else {
			r.CrawlStatus = "no_website"
		}
	}

	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for r := range jobs {
				crawlSingleCompany(client, r, maxPages)
				cur := atomic.AddInt64(&doneCount, 1)
				if cur%50 == 0 || cur == totalWithSites {
					fmt.Printf("  [Stage 2] Crawled %d / %d company websites\n", cur, totalWithSites)
				}
			}
		}()
	}

	for _, r := range residents {
		if r.Website != "" {
			jobs <- r
		}
	}
	close(jobs)
	wg.Wait()
}

type scoredLink struct {
	url   string
	score int
}

func crawlSingleCompany(client *http.Client, r *Resident, maxPages int) {
	siteCtx, siteCancel := context.WithTimeout(context.Background(), 22*time.Second)
	defer siteCancel()

	emailSet := make(map[string]bool)
	for _, e := range r.HREmails {
		emailSet[e] = true
	}
	for _, e := range r.OtherEmails {
		emailSet[e] = true
	}
	tgSet := make(map[string]bool)
	for _, t := range r.Telegrams {
		tgSet[t] = true
	}
	liSet := make(map[string]bool)
	for _, l := range r.LinkedIns {
		liSet[l] = true
	}
	jbSet := make(map[string]bool)
	for _, j := range r.JobBoardLinks {
		jbSet[j] = true
	}
	careerPagesSet := make(map[string]bool)

	var combinedTextBuilder strings.Builder
	combinedTextBuilder.WriteString(r.Description)
	combinedTextBuilder.WriteString(" ")
	combinedTextBuilder.WriteString(strings.Join(r.Directions, " "))

	// Try HTTPS first; if it fails and was HTTPS, try HTTP
	homeURL := r.Website
	reqCtx, cancel := context.WithTimeout(siteCtx, 8*time.Second)
	homeHTML, finalHomeURL, err := fetchHTML(reqCtx, client, homeURL)
	cancel()

	if err != nil && strings.HasPrefix(homeURL, "https://") {
		altURL := "http://" + strings.TrimPrefix(homeURL, "https://")
		reqCtx2, cancel2 := context.WithTimeout(siteCtx, 7*time.Second)
		homeHTML, finalHomeURL, err = fetchHTML(reqCtx2, client, altURL)
		cancel2()
	}

	if err != nil || homeHTML == "" {
		r.CrawlStatus = "site_unreachable"
		detectTechAndRoles(combinedTextBuilder.String(), r)
		return
	}

	r.CrawlStatus = "ok"
	if finalHomeURL != "" {
		homeURL = finalHomeURL
	}

	extractContactsFromText(homeHTML, emailSet, tgSet, liSet, jbSet)
	combinedTextBuilder.WriteString(" ")
	combinedTextBuilder.WriteString(cleanText(homeHTML))

	// Discover candidate internal links from homepage
	candidates := discoverCandidateLinks(homeURL, homeHTML)

	visited := make(map[string]bool)
	visited[normalizeForDedup(homeURL)] = true

	pagesCrawled := 0
	for _, cand := range candidates {
		if pagesCrawled >= maxPages {
			break
		}
		if siteCtx.Err() != nil {
			break
		}
		norm := normalizeForDedup(cand.url)
		if visited[norm] {
			continue
		}
		visited[norm] = true

		pCtx, pCancel := context.WithTimeout(siteCtx, 6*time.Second)
		pageHTML, finalPageURL, pErr := fetchHTML(pCtx, client, cand.url)
		pCancel()
		if pErr != nil || pageHTML == "" {
			continue
		}
		pagesCrawled++

		if cand.score >= 80 {
			if finalPageURL != "" {
				careerPagesSet[finalPageURL] = true
			} else {
				careerPagesSet[cand.url] = true
			}
		}

		extractContactsFromText(pageHTML, emailSet, tgSet, liSet, jbSet)
		combinedTextBuilder.WriteString(" ")
		combinedTextBuilder.WriteString(cleanText(pageHTML))

		// Also check if career page links to nested vacancy/contact pages
		if cand.score >= 80 && pagesCrawled < maxPages {
			subLinks := discoverCandidateLinks(cand.url, pageHTML)
			for _, sub := range subLinks {
				if sub.score >= 80 && !visited[normalizeForDedup(sub.url)] && pagesCrawled < maxPages {
					visited[normalizeForDedup(sub.url)] = true
					sCtx, sCancel := context.WithTimeout(siteCtx, 5*time.Second)
					sHTML, _, sErr := fetchHTML(sCtx, client, sub.url)
					sCancel()
					if sErr == nil && sHTML != "" {
						pagesCrawled++
						extractContactsFromText(sHTML, emailSet, tgSet, liSet, jbSet)
						combinedTextBuilder.WriteString(" ")
						combinedTextBuilder.WriteString(cleanText(sHTML))
					}
				}
			}
		}
	}

	r.HREmails = nil
	r.OtherEmails = nil
	classifyEmails(emailSet, r)
	r.Telegrams = mapKeysSorted(tgSet)
	r.LinkedIns = mapKeysSorted(liSet)
	r.JobBoardLinks = mapKeysSorted(jbSet)
	r.CareerPages = mapKeysSorted(careerPagesSet)

	detectTechAndRoles(combinedTextBuilder.String(), r)
}

func discoverCandidateLinks(baseURLStr, htmlStr string) []scoredLink {
	baseURL, err := url.Parse(baseURLStr)
	if err != nil {
		return nil
	}
	baseHost := strings.TrimPrefix(strings.ToLower(baseURL.Hostname()), "www.")

	bestScore := make(map[string]int)

	anchors := reAnchor.FindAllStringSubmatch(htmlStr, -1)
	for _, a := range anchors {
		rawHref := strings.TrimSpace(html.UnescapeString(a[1]))
		anchorText := strings.ToLower(cleanText(a[2]))

		if rawHref == "" || strings.HasPrefix(rawHref, "#") || strings.HasPrefix(strings.ToLower(rawHref), "javascript:") ||
			strings.HasPrefix(strings.ToLower(rawHref), "mailto:") || strings.HasPrefix(strings.ToLower(rawHref), "tel:") {
			continue
		}

		resolved, err := baseURL.Parse(rawHref)
		if err != nil || (resolved.Scheme != "http" && resolved.Scheme != "https") {
			continue
		}
		resolved.Fragment = ""

		linkHost := strings.TrimPrefix(strings.ToLower(resolved.Hostname()), "www.")
		// Allow same domain or subdomain (e.g. career.company.com or jobs.company.by)
		if linkHost != baseHost && !strings.HasSuffix(linkHost, "."+baseHost) {
			continue
		}

		pathLower := strings.ToLower(resolved.Path + "?" + resolved.RawQuery)
		// Skip static assets / docs
		if strings.HasSuffix(pathLower, ".pdf?") || strings.HasSuffix(strings.ToLower(resolved.Path), ".pdf") ||
			strings.HasSuffix(strings.ToLower(resolved.Path), ".jpg") || strings.HasSuffix(strings.ToLower(resolved.Path), ".png") ||
			strings.HasSuffix(strings.ToLower(resolved.Path), ".zip") {
			continue
		}

		score := scoreCandidateLink(strings.ToLower(resolved.Hostname()+resolved.Path), anchorText)
		if score > 0 {
			uStr := resolved.String()
			if score > bestScore[uStr] {
				bestScore[uStr] = score
			}
		}
	}

	// If no career links found on homepage, add standard fallback paths with score 50
	hasCareer := false
	for _, sc := range bestScore {
		if sc >= 80 {
			hasCareer = true
			break
		}
	}
	if !hasCareer {
		root := &url.URL{Scheme: baseURL.Scheme, Host: baseURL.Host}
		for _, p := range []string{"/career", "/careers", "/vacancies", "/jobs", "/contacts", "/contact"} {
			uStr := root.String() + p
			if bestScore[uStr] == 0 {
				bestScore[uStr] = 50
			}
		}
	}

	var list []scoredLink
	for u, sc := range bestScore {
		list = append(list, scoredLink{url: u, score: sc})
	}
	sort.Slice(list, func(i, j int) bool {
		if list[i].score != list[j].score {
			return list[i].score > list[j].score
		}
		return len(list[i].url) < len(list[j].url)
	})
	return list
}

func scoreCandidateLink(urlPathLower, anchorLower string) int {
	combined := urlPathLower + " " + anchorLower

	// High priority: Career / Jobs / Vacancies / HR
	careerKeywords := []string{
		"career", "careers", "vacanc", "job", "jobs", "join-us", "join_us", "work-with-us",
		"talent", "recruiting", "hiring", "intern", "trainee",
		"ваканс", "карьер", "работ", "стажиров", "vakans", "karer", "rabot",
	}
	for _, kw := range careerKeywords {
		if strings.Contains(combined, kw) {
			return 100
		}
	}

	// Medium priority: Contacts / About / Team / People
	contactKeywords := []string{
		"contact", "contacts", "контакт", "kontakt", "связаться", "обратная связь",
		"about", "о-нас", "о нас", "компани", "team", "команд", "people",
	}
	for _, kw := range contactKeywords {
		if strings.Contains(combined, kw) {
			return 70
		}
	}

	return 0
}

func normalizeForDedup(u string) string {
	u = strings.ToLower(strings.TrimSpace(u))
	u = strings.TrimPrefix(u, "https://")
	u = strings.TrimPrefix(u, "http://")
	u = strings.TrimPrefix(u, "www.")
	u = strings.TrimRight(u, "/")
	return u
}

func cfDecodeEmail(encoded string) string {
	b, err := hex.DecodeString(encoded)
	if err != nil || len(b) < 2 {
		return ""
	}
	key := b[0]
	var out []byte
	for i := 1; i < len(b); i++ {
		out = append(out, b[i]^key)
	}
	return string(out)
}

func extractContactsFromText(rawHTML string, emailSet, tgSet, liSet, jbSet map[string]bool) {
	// 1. Decode Cloudflare data-cfemail if any
	for _, m := range reCfEmail.FindAllStringSubmatch(rawHTML, -1) {
		if dec := cfDecodeEmail(m[1]); dec != "" {
			if cleanE := validateAndCleanEmail(dec); cleanE != "" {
				emailSet[cleanE] = true
			}
		}
	}

	// 2. Unescape HTML entities so &#64; or &commat; becomes @
	unescaped := html.UnescapeString(rawHTML)

	// 3. Extract mailto: links
	for _, m := range reMailto.FindAllStringSubmatch(unescaped, -1) {
		if cleanE := validateAndCleanEmail(m[1]); cleanE != "" {
			emailSet[cleanE] = true
		}
	}

	// 4. Extract standard emails
	for _, m := range reEmail.FindAllStringSubmatch(unescaped, -1) {
		if cleanE := validateAndCleanEmail(m[1]); cleanE != "" {
			emailSet[cleanE] = true
		}
	}

	// 5. Extract obfuscated emails like hr [at] company [dot] by
	for _, m := range reObfMail.FindAllStringSubmatch(unescaped, -1) {
		candidate := m[1] + "@" + m[2] + "." + m[3]
		if cleanE := validateAndCleanEmail(candidate); cleanE != "" {
			emailSet[cleanE] = true
		}
	}

	// 6. Extract Telegram links
	for _, m := range reTgLink.FindAllStringSubmatch(unescaped, -1) {
		if tg := cleanTelegramHandle(m[1]); tg != "" {
			tgSet[tg] = true
		}
	}
	for _, m := range reTgDomain.FindAllStringSubmatch(unescaped, -1) {
		if tg := cleanTelegramHandle(m[1]); tg != "" {
			tgSet[tg] = true
		}
	}
	for _, m := range reTgText.FindAllStringSubmatch(unescaped, -1) {
		if tg := cleanTelegramHandle(m[1]); tg != "" {
			tgSet[tg] = true
		}
	}

	// 7. LinkedIn & Job Boards
	for _, m := range reLinkedIn.FindAllString(unescaped, -1) {
		liSet[strings.TrimRight(m, "/")] = true
	}
	for _, m := range reJobBoard.FindAllString(unescaped, -1) {
		jbSet[strings.TrimRight(m, "/")] = true
	}
}

func validateAndCleanEmail(raw string) string {
	e := strings.ToLower(strings.TrimSpace(raw))
	e = strings.Trim(e, ".,;:\"'()[]<>\\/")
	// Strip leading hex escape artifacts like u003e or 20
	for _, pref := range []string{"u003e", "u002f", "u003a", "3a", "20"} {
		if strings.HasPrefix(e, pref) && len(e) > len(pref)+5 {
			// Only strip if the next char is a letter
			e = strings.TrimPrefix(e, pref)
		}
	}

	parts := strings.Split(e, "@")
	if len(parts) != 2 {
		return ""
	}
	local, domain := parts[0], parts[1]
	if len(local) < 1 || len(local) > 64 || len(domain) < 4 || !strings.Contains(domain, ".") {
		return ""
	}

	// Filter out false-positive file extensions
	badSuffixes := []string{
		".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp",
		".css", ".js", ".ts", ".map", ".woff", ".woff2", ".ttf", ".eot",
		".mp4", ".mp3", ".pdf", ".doc", ".docx", ".zip", ".rar", ".php", ".html", ".htm",
	}
	for _, suf := range badSuffixes {
		if strings.HasSuffix(domain, suf) {
			return ""
		}
	}

	// Filter out placeholder/system domains & HTP admin emails
	badDomains := []string{
		"park.by", "example.com", "example.org", "domain.com", "yoursite.com",
		"email.com", "mysite.com", "test.com", "company.com", "website.com",
		"sentry.io", "sentry-next.wixpress.com", "wixpress.com", "wix.com",
		"tilda.ws", "bitrix24.ru", "bitrix24.by", "1c-bitrix.ru",
	}
	for _, bd := range badDomains {
		if domain == bd || strings.HasSuffix(domain, "."+bd) {
			return ""
		}
	}

	badLocals := []string{
		"noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster",
		"webmaster", "abuse", "privacy", "gdpr", "dpo", "security", "legal",
		"example", "username", "name", "yourname", "user", "firstname",
	}
	for _, bl := range badLocals {
		if local == bl {
			return ""
		}
	}

	// Validate TLD has only letters and length 2..12
	domParts := strings.Split(domain, ".")
	tld := domParts[len(domParts)-1]
	if len(tld) < 2 || len(tld) > 12 {
		return ""
	}
	for _, ch := range tld {
		if ch < 'a' || ch > 'z' {
			return ""
		}
	}

	return e
}

func cleanTelegramHandle(raw string) string {
	h := strings.TrimSpace(raw)
	h = strings.Trim(h, "/.,;:\"'()[]<>")
	hLower := strings.ToLower(h)

	ignore := map[string]bool{
		"share": true, "iv": true, "joinchat": true, "addstickers": true,
		"proxy": true, "socks": true, "htp_belarus": true, "telegram": true,
		"dl": true, "msg": true, "msg_url": true, "confirmphone": true,
		"setlanguage": true, "login": true, "contact": true,
	}
	if ignore[hLower] || len(h) < 4 {
		return ""
	}
	return "https://t.me/" + h
}

func classifyEmails(emailSet map[string]bool, r *Resident) {
	hrKeywords := []string{
		"hr", "job", "jobs", "career", "careers", "cv", "resume",
		"recruit", "recruiting", "recruitment", "recruiter",
		"talent", "talents", "people", "work", "join", "hiring",
		"staff", "personal", "kadry", "rabota", "vacancy", "vacancies",
		"intern", "internship", "trainee", "academy", "team",
	}

	var hrList, otherList []string
	for e := range emailSet {
		local := strings.Split(e, "@")[0]
		isHR := false
		for _, kw := range hrKeywords {
			if local == kw || strings.HasPrefix(local, kw+".") || strings.HasPrefix(local, kw+"_") ||
				strings.HasPrefix(local, kw+"-") || strings.HasSuffix(local, "."+kw) ||
				strings.HasSuffix(local, "_"+kw) || strings.HasSuffix(local, "-"+kw) ||
				strings.Contains(local, "hr") || strings.Contains(local, "job") ||
				strings.Contains(local, "career") || strings.Contains(local, "recruit") ||
				strings.Contains(local, "rabota") || strings.Contains(local, "cv") ||
				strings.Contains(local, "talent") {
				isHR = true
				break
			}
		}
		if isHR {
			hrList = append(hrList, e)
		} else {
			otherList = append(otherList, e)
		}
	}
	sort.Strings(hrList)
	sort.Strings(otherList)
	r.HREmails = hrList
	r.OtherEmails = otherList
}

func detectTechAndRoles(text string, r *Resident) {
	roleSet := make(map[string]bool)

	if reCSharp.MatchString(text) {
		roleSet["C# / .NET"] = true
	}
	if reGolang.MatchString(text) {
		roleSet["Go (Golang)"] = true
	}
	if reSysAna.MatchString(text) {
		roleSet["System / Business Analyst"] = true
	}
	for _, d := range r.Directions {
		dl := strings.ToLower(d)
		if strings.Contains(dl, "системный анализ") || strings.Contains(dl, "бизнес-анализ") {
			roleSet["System / Business Analyst"] = true
		}
		if strings.Contains(dl, "разработка программного обеспечения") || strings.Contains(dl, "разработка по") {
			r.IsITTarget = true
		}
	}
	if reJunMid.MatchString(text) {
		roleSet["Junior / Middle / Intern Mentioned"] = true
	}

	r.MatchedRoles = mapKeysSorted(roleSet)
}

func computeRelevance(r *Resident) {
	score := 0
	if r.IsMinsk {
		score += 20
	}
	if r.IsITTarget {
		score += 15
	}
	if len(r.HREmails) > 0 {
		score += 40
	} else if len(r.OtherEmails) > 0 {
		score += 15
	}
	if len(r.Telegrams) > 0 {
		score += 25
	}
	if len(r.CareerPages) > 0 {
		score += 15
	}
	for _, role := range r.MatchedRoles {
		switch role {
		case "C# / .NET", "Go (Golang)":
			score += 35
		case "System / Business Analyst":
			score += 30
		case "Junior / Middle / Intern Mentioned":
			score += 20
		}
	}
	// Companies with 11-50, 51-100, 101-500, 501-1000, >1000 employees are much more likely to hire Junior/Middle than <10
	switch r.StaffCount {
	case "11-50", "51-100":
		score += 10
	case "101-500", "501-1000", ">1000":
		score += 15
	}
	r.RelevanceScore = score
}

func mapKeysSorted(m map[string]bool) []string {
	if len(m) == 0 {
		return nil
	}
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

func saveOutputs(residents []*Resident) error {
	// 1. Save full JSON
	jsonBytes, err := json.MarshalIndent(residents, "", "  ")
	if err != nil {
		return err
	}
	if err := os.WriteFile("htp_companies_contacts.json", jsonBytes, 0644); err != nil {
		return err
	}

	// 2. Save UTF-8 BOM CSV (so Excel on Windows opens Russian characters properly!)
	if err := writeCSV("htp_minsk_all_contacts.csv", residents, false); err != nil {
		return err
	}
	if err := writeCSV("htp_minsk_priority_hr_contacts.csv", residents, true); err != nil {
		return err
	}

	return nil
}

func writeCSV(filename string, residents []*Resident, priorityOnly bool) error {
	f, err := os.Create(filename)
	if err != nil {
		return err
	}
	defer f.Close()

	// Write UTF-8 BOM for Microsoft Excel compatibility
	_, _ = f.Write([]byte{0xEF, 0xBB, 0xBF})

	w := csv.NewWriter(f)
	w.Comma = ';' // Semicolon is standard for Russian Excel locale

	header := []string{
		"Score",
		"Company Name",
		"City",
		"Staff Size",
		"Matched Roles / Stack",
		"HR / Career Emails",
		"Telegram Contacts",
		"General Emails",
		"Career Page URLs",
		"Website",
		"LinkedIn / Job Boards",
		"Phone",
		"Directions (HTP)",
		"Park.by URL",
	}
	if err := w.Write(header); err != nil {
		return err
	}

	count := 0
	for _, r := range residents {
		if priorityOnly {
			if !r.IsMinsk {
				continue
			}
			if len(r.HREmails) == 0 && len(r.Telegrams) == 0 && len(r.OtherEmails) == 0 {
				continue
			}
		}

		links := append([]string{}, r.LinkedIns...)
		links = append(links, r.JobBoardLinks...)

		row := []string{
			fmt.Sprintf("%d", r.RelevanceScore),
			r.Name,
			r.City,
			r.StaffCount,
			strings.Join(r.MatchedRoles, ", "),
			strings.Join(r.HREmails, ", "),
			strings.Join(r.Telegrams, ", "),
			strings.Join(r.OtherEmails, ", "),
			strings.Join(r.CareerPages, ", "),
			r.Website,
			strings.Join(links, ", "),
			r.Phone,
			strings.Join(r.Directions, "; "),
			r.ParkURL,
		}
		if err := w.Write(row); err != nil {
			return err
		}
		count++
	}
	w.Flush()
	fmt.Printf("Saved %d rows to %s\n", count, filename)
	return w.Error()
}

