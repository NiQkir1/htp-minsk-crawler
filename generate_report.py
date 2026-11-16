import json
import os
import re
from html import escape

# Regex to check park description
RE_CS_PARK = re.compile(r'(?i)(?:\bC#(?=[,\s\.\/\)\(]|$)|c-sharp|\b\.NET(?=[,\s\.\/\)\(]|$)|\bdotnet\b|\basp\.net\b)')
RE_GO_PARK = re.compile(r'(?i)(?:\bgolang\b|\bgo\s*(?:язык|разработ|developer|engineer|backend|дев)|\bgo\b(?:\s*\/|\/go))')

# Known False Positives (job boards, courses, 1C accounting resellers, domain .net hits)
FALSE_POSITIVES_SET = {
    'ПРАЦА БАЙ', 'Байскилз', 'ЮКОЛА-ИНФО-Брест', 'Твоя столицааналитикс', 
    'Майфин', 'Онлайн Медиа', 'Агентство цифровой трансформации', 
    'ВК Решения', 'ДПО', 'Пиксель Интернет', 'Фермент', 'Ресинк', 
    'Бонусторг', 'ИнКата Продакт Девелопмент', 'ФОТЭК', 'ЕСД Солюшнс', 'Вайден'
}

# Known Major Dev Companies with verified .NET / Go engineering departments
KNOWN_MAJOR_DEV = {
    'ФордэКонсалтинг': 'Forte Group (.NET, C#, Cloud Enterprise)',
    'СОФТКЛУБ': 'SoftClub (Банковский софт, .NET, Java, Oracle)',
    'СОФТКЛУБ – Центр разработки': 'SoftClub (Финтех / .NET, Java)',
    'Спесифик-Груп Софтвэ Девелопмент Дивижн': 'Specific-Group (.NET enterprise)',
    'Белитсофт Интернешнл': 'Belitsoft (.NET, C#, Azure development)',
    'Техартгруп': 'iTechArt (.NET, C#, Cloud/Web)',
    'ИксБи Софтваре': 'XB Software (.NET, Web fullstack)',
    'СЕНЛА ГРУП': 'SENLA (.NET enterprise, FinTech)',
    'HQSoftware': 'HQSoftware (.NET, IoT, Web)',
    'Эйч Кью Системз': 'HQSoftware (.NET, IoT, Web)',
    'Интач Софт': 'Intouch Soft (.NET development)',
    'Финмаркет Софт': 'Finmarket Soft (.NET, ASP.NET)',
    'Финстек Бел': 'Finstek (.NET fintech)',
    'Прикладные системы': 'Applied Systems (Industrial .NET / C#)',
    'Электронное ДЕЛО': 'Электронное ДЕЛО (.NET, ASP.NET)',
    'ПикселПлекс Лабс': 'PixelPlex (Blockchain, Web, .NET/C#)',
    'ДЗЭНСОФТ СОЛЮШЕН': 'Dzensoft (.NET enterprise)',
    'ИнДев Солюшенс': 'InDev Solutions (Гос. и enterprise софт)',
    'Девелопмент Фэмили': 'Dev.family (Web/mobile/Go)',
    'Бизнес Солюшинс Лаб Бел': 'BSL (Go, Mobile, Web)',
    'ИТМ-БЕЛ': 'MTS Web Services (Go, Cloud, Telecom)',
    'УайтСнейк': 'WhiteSnake (GameDev / C# / Go)',
    'Фаундэвс': 'Foundevs (Go / Web dev)',
    'АкссонСофт': 'AxxonSoft (Системы безопасности, C#, Go, C++)',
    'ОКСАДЖАЙЛ': 'Oxagile (.NET, Web, Video streaming)',
    'ИБА ИТ Парк': 'IBA Group (.NET, Enterprise)',
    'ЭПАМ Системз': 'EPAM (.NET, Cloud, Enterprise)',
}

def enrich_and_verify(resident):
    name = resident.get('name', '')
    desc = resident.get('description') or ''
    clean_desc = re.sub(r'https?://\S+', ' ', desc)
    clean_desc = re.sub(r'[\w.-]+@[\w.-]+', ' ', clean_desc)
    
    cs_park = bool(RE_CS_PARK.search(clean_desc))
    go_park = bool(RE_GO_PARK.search(clean_desc))
    
    matched_roles = list(resident.get('matched_roles') or [])
    dirs = resident.get('directions') or []
    is_dev_direction = any('разработка' in d.lower() for d in dirs) or resident.get('is_it_target')
    
    if name in FALSE_POSITIVES_SET:
        resident['verification_level'] = 'false_positive'
        resident['verification_label'] = '⚠️ Ложное (портал / курсы / не разработка)'
        resident['verification_note'] = 'Ложное срабатывание краулера (агрегатор вакансий, онлайн-курсы, 1С франчайзинг или домен .net)'
        resident['matched_roles'] = [r for r in matched_roles if r not in ('C# / .NET', 'Go (Golang)')]
        return resident
        
    if cs_park or go_park:
        tags = []
        if cs_park and 'C# / .NET' not in matched_roles:
            matched_roles.append('C# / .NET')
        if go_park and 'Go (Golang)' not in matched_roles:
            matched_roles.append('Go (Golang)')
        if cs_park: tags.append('.NET / C#')
        if go_park: tags.append('Go')
        resident['verification_level'] = 'verified'
        resident['verification_label'] = f"🟢 Подтвержден в ПВТ ({', '.join(tags)})"
        resident['verification_note'] = f"Стек официально подтвержден в описании карточки резидента ПВТ ({', '.join(tags)})"
        resident['matched_roles'] = matched_roles
        return resident
        
    if name in KNOWN_MAJOR_DEV:
        note = KNOWN_MAJOR_DEV[name]
        if 'C#' in note or '.NET' in note:
            if 'C# / .NET' not in matched_roles:
                matched_roles.append('C# / .NET')
        if 'Go' in note:
            if 'Go (Golang)' not in matched_roles:
                matched_roles.append('Go (Golang)')
        resident['verification_level'] = 'verified'
        resident['verification_label'] = '🟢 Подтвержден (крупный IT-разработчик)'
        resident['verification_note'] = f"Подтвержденный IT-вендор с экспертизой в стеке: {note}"
        resident['matched_roles'] = matched_roles
        return resident
        
    has_cs = 'C# / .NET' in matched_roles
    has_go = 'Go (Golang)' in matched_roles
    
    if has_cs or has_go:
        if is_dev_direction:
            resident['verification_level'] = 'dev_unverified'
            resident['verification_label'] = '🟡 Разработчик ПО (стек с сайта/вакансий)'
            resident['verification_note'] = 'ИТ-компания разработчик ПО. Стек обнаружен краулером на сайте компании или странице карьеры.'
            resident['matched_roles'] = matched_roles
            return resident
        else:
            resident['verification_level'] = 'false_positive'
            resident['verification_label'] = '⚠️ Ложное (не разработка ПО)'
            resident['verification_note'] = 'Направление деятельности не связано с разработкой ПО (совпадение по домену или сторонней ссылке)'
            resident['matched_roles'] = [r for r in matched_roles if r not in ('C# / .NET', 'Go (Golang)')]
            return resident
            
    resident['verification_level'] = 'general_dev'
    resident['verification_label'] = '⚪ Разработка ПО (общий стек)'
    resident['verification_note'] = 'Резидент ПВТ в сфере разработки ПО. Специфический стек C#/.NET или Go не был явно заявлен.'
    resident['matched_roles'] = matched_roles
    return resident

def main():
    json_path = "htp_companies_contacts.json"
    if not os.path.exists(json_path):
        print(f"{json_path} not found yet.")
        return

    with open(json_path, "r", encoding="utf-8") as f:
        residents = json.load(f)

    # Enrich and verify all residents
    enriched = [enrich_and_verify(r) for r in residents]

    minsk = [r for r in enriched if r.get("is_minsk")]
    with_hr_email = [r for r in minsk if r.get("hr_emails")]
    with_tg = [r for r in minsk if r.get("telegrams")]
    with_any_contact = [r for r in minsk if r.get("hr_emails") or r.get("telegrams") or r.get("other_emails")]

    verified_cs_go = [r for r in minsk if r.get("verification_level") == "verified"]
    unverified_dev = [r for r in minsk if r.get("verification_level") == "dev_unverified"]
    false_positives = [r for r in minsk if r.get("verification_level") == "false_positive"]

    print(f"Total residents: {len(residents)}")
    print(f"Minsk residents: {len(minsk)}")
    print(f"Verified .NET / Go: {len(verified_cs_go)}")
    print(f"Unverified dev: {len(unverified_dev)}")
    print(f"Filtered false positives: {len(false_positives)}")

    # Update TOP_COMPANIES_REPORT.md
    md_lines = [
        "# База контактов рекрутеров ПВТ (Минск) — C# / .NET, Go, Системный аналитик",
        "",
        "## Сводная статистика краулинга и верификации",
        f"- **Всего резидентов ПВТ:** {len(residents)}",
        f"- **Компаний в Минске:** {len(minsk)}",
        f"- **Компаний с найденными контактами (Email / Telegram):** {len(with_any_contact)}",
        f"- **Компаний с выделенными HR-почтами:** {len(with_hr_email)}",
        f"- **Компаний с Telegram-контактами:** {len(with_tg)}",
        f"- **🟢 Подтвержденный стек C# / .NET и Go (карточка ПВТ / ключевые IT-вендоры):** {len(verified_cs_go)} компаний",
        f"- **🟡 Разработчики ПО со стеком с сайта / вакансий:** {len(unverified_dev)} компаний",
        f"- **⚠️ Отфильтрованные ложные срабатывания (агрегаторы, курсы, 1С, домены .net):** {len(false_positives)} компаний",
        "",
        "---",
        "",
        "## Топ компаний ПВТ (Минск) — Верифицированный стек и контакты HR",
        "",
        "| Компания | Верификация стека | Штат | Роли / Стек | HR / Career Почты | Telegram | Сайт / Ссылки |",
        "|---|---|---|---|---|---|---|",
    ]

    # Prioritize verified companies first
    sorted_minsk = sorted(minsk, key=lambda r: (
        0 if r.get("verification_level") == "verified" else (
            1 if r.get("verification_level") == "dev_unverified" else (
                2 if r.get("verification_level") == "general_dev" else 3
            )
        ),
        0 if (r.get("hr_emails") or r.get("telegrams")) else 1,
        -r.get("relevance_score", 0)
    ))

    top_rows = 0
    for r in sorted_minsk:
        hr_emails = r.get("hr_emails") or []
        tgs = r.get("telegrams") or []
        other_emails = r.get("other_emails") or []
        roles = r.get("matched_roles") or []
        if not hr_emails and not tgs and not other_emails:
            continue
        if r.get("verification_level") == "false_positive":
            continue
            
        name = r.get("name", "").replace("|", "/")
        staff = r.get("staff_count") or "—"
        ver_lbl = r.get("verification_label", "")
        roles_str = ", ".join(roles) if roles else ("Разработка ПО" if r.get("is_it_target") else "ИТ")
        hr_str = "<br>".join(hr_emails[:4]) if hr_emails else "—"
        tg_str = "<br>".join(tgs[:3]) if tgs else "—"
        site = (r.get("career_pages") or [r.get("website") or r.get("park_url")])[0]
        md_lines.append(f"| **{name}** | {ver_lbl} | {staff} | {roles_str} | {hr_str} | {tg_str} | {site} |")
        top_rows += 1
        if top_rows >= 250:
            break

    with open("TOP_COMPANIES_REPORT.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))
    print(f"Saved TOP_COMPANIES_REPORT.md ({top_rows} companies listed)")

    # Generate HTML Dashboard
    generate_html_dashboard(sorted_minsk)

def generate_html_dashboard(residents):
    data_json = json.dumps(residents, ensure_ascii=False)
    html_content = f"""<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ПВТ Минск — База контактов и шаблоны откликов (Разработчик)</title>
<style>
  :root {{
    --bg: #090d16;
    --card: #131c2e;
    --card-hover: #1e293b;
    --border: #24344d;
    --border-subtle: #1e2c42;
    --text: #f1f5f9;
    --muted: #94a3b8;
    --accent: #38bdf8;
    --accent-hover: #0284c7;
    --accent-glow: rgba(56, 189, 248, 0.15);
    --hr: #4ade80;
    --hr-bg: rgba(74, 222, 128, 0.1);
    --tg: #38bdf8;
    --tg-bg: rgba(56, 189, 248, 0.1);
    --warn: #fbbf24;
    --warn-bg: rgba(251, 191, 36, 0.1);
    --danger: #f87171;
    --danger-bg: rgba(248, 113, 113, 0.1);
    --purple: #c084fc;
    --purple-bg: rgba(192, 132, 252, 0.1);
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 24px;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
    background: var(--bg); color: var(--text);
    line-height: 1.5;
  }}
  h1 {{
    margin: 0 0 6px 0; font-size: 26px; font-weight: 700;
    background: linear-gradient(90deg, #38bdf8, #818cf8, #c084fc);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
  }}
  .subtitle {{ color: var(--muted); font-size: 14px; margin-bottom: 20px; }}

  /* APPLICANT PROFILE PANEL */
  .profile-panel {{
    background: linear-gradient(135deg, rgba(30, 41, 59, 0.7), rgba(15, 23, 42, 0.9));
    border: 1px solid #3b82f640;
    border-radius: 14px;
    padding: 16px 20px;
    margin-bottom: 20px;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.3);
  }}
  .profile-header {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 12px;
  }}
  .profile-title {{
    font-size: 15px; font-weight: 600; color: #93c5fd; display: flex; align-items: center; gap: 8px;
  }}
  .profile-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 12px;
  }}
  .form-group {{
    display: flex; flex-direction: column; gap: 4px;
  }}
  .form-group label {{
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px;
    color: var(--muted); font-weight: 600;
  }}
  .form-group input, .form-group select {{
    background: #0b1120; color: var(--text);
    border: 1px solid var(--border);
    padding: 7px 10px; border-radius: 8px; font-size: 13px;
    transition: border-color 0.15s;
  }}
  .form-group input:focus, .form-group select:focus {{
    outline: none; border-color: var(--accent); box-shadow: 0 0 0 2px var(--accent-glow);
  }}

  /* CONTROLS */
  .controls {{
    display: flex; flex-wrap: wrap; gap: 10px;
    background: var(--card); padding: 14px 18px; border-radius: 12px;
    border: 1px solid var(--border); margin-bottom: 16px; align-items: center;
  }}
  input[type="text"], select {{
    background: #090d16; color: var(--text); border: 1px solid var(--border);
    padding: 8px 12px; border-radius: 8px; font-size: 13px;
  }}
  #q {{ min-width: 280px; flex: 2; }}
  .btn {{
    display: inline-flex; align-items: center; justify-content: center; gap: 6px;
    padding: 7px 13px; border-radius: 8px; font-size: 13px; font-weight: 500;
    cursor: pointer; border: 1px solid transparent; transition: all 0.15s ease;
    text-decoration: none; white-space: nowrap;
  }}
  .btn-primary {{
    background: #0284c7; color: #fff;
  }}
  .btn-primary:hover {{ background: #0369a1; }}
  .btn-secondary {{
    background: #1e293b; color: var(--text); border-color: var(--border);
  }}
  .btn-secondary:hover {{ background: #334155; }}
  .btn-success {{
    background: rgba(34, 197, 94, 0.15); color: #86efac; border-color: #22c55e40;
  }}
  .btn-success:hover {{ background: rgba(34, 197, 94, 0.25); }}
  .btn-sm {{ padding: 4px 8px; font-size: 11px; border-radius: 6px; }}

  /* STATS BAR */
  .stats-bar {{
    display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center;
    gap: 12px; margin-bottom: 12px; font-size: 13px; color: var(--muted);
  }}
  .stat-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    background: #131c2e; border: 1px solid var(--border-subtle);
    padding: 3px 10px; border-radius: 20px; font-size: 12px;
  }}
  .stat-pill b {{ color: var(--text); }}

  /* TABLE */
  .table-container {{
    overflow-x: auto; background: var(--card); border-radius: 12px;
    border: 1px solid var(--border); box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  th, td {{
    padding: 11px 12px; text-align: left; border-bottom: 1px solid var(--border);
    font-size: 13px; vertical-align: top;
  }}
  th {{
    background: #0b1120; color: #94a3b8; font-weight: 600; font-size: 12px;
    text-transform: uppercase; letter-spacing: 0.5px; position: sticky; top: 0; z-index: 10;
  }}
  tr:hover {{ background: rgba(255,255,255,0.02); }}
  tr.status-applied {{ opacity: 0.65; background: rgba(34, 197, 94, 0.04); }}

  /* BADGES */
  .badge {{
    display: inline-block; padding: 2px 7px; border-radius: 999px; font-size: 11px;
    margin: 2px 3px 2px 0; background: #1e293b; color: #cbd5e1; border: 1px solid var(--border);
    font-weight: 500;
  }}
  .badge.csharp {{ background: #3b0764; color: #f3e8ff; border-color: #581c87; }}
  .badge.go {{ background: #083344; color: #cffafe; border-color: #155e75; }}
  .badge.sa {{ background: #422006; color: #fef08a; border-color: #713f12; }}
  .badge.jun {{ background: #064e3b; color: #a7f3d0; border-color: #065f46; }}

  .ver-badge {{
    display: inline-flex; align-items: center; gap: 4px;
    padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;
    margin-bottom: 4px;
  }}
  .ver-badge.verified {{
    background: rgba(34, 197, 94, 0.15); color: #86efac; border: 1px solid rgba(34, 197, 94, 0.3);
  }}
  .ver-badge.dev_unverified {{
    background: rgba(234, 179, 8, 0.15); color: #fde047; border: 1px solid rgba(234, 179, 8, 0.3);
  }}
  .ver-badge.false_positive {{
    background: rgba(239, 68, 68, 0.15); color: #fca5a5; border: 1px solid rgba(239, 68, 68, 0.3);
  }}
  .ver-badge.general_dev {{
    background: rgba(148, 163, 184, 0.1); color: #94a3b8; border: 1px solid rgba(148, 163, 184, 0.2);
  }}

  a {{ color: var(--accent); text-decoration: none; word-break: break-all; }}
  a:hover {{ text-decoration: underline; }}
  .hr-mail {{ color: var(--hr); font-weight: 600; display: block; margin-bottom: 2px; }}
  .tg-link {{ color: #60a5fa; font-weight: 500; display: block; margin-bottom: 2px; }}
  .other-mail {{ color: var(--muted); display: block; margin-bottom: 1px; font-size: 12px; }}

  .action-buttons {{
    display: flex; flex-direction: column; gap: 6px; min-width: 130px;
  }}

  /* APPLIED CHECKBOX */
  .applied-label {{
    display: inline-flex; align-items: center; gap: 6px; font-size: 11px;
    color: var(--muted); cursor: pointer; user-select: none; margin-top: 4px;
  }}
  .applied-label input {{ cursor: pointer; }}

  /* MODAL */
  .modal-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0, 0, 0, 0.75);
    backdrop-filter: blur(4px); z-index: 100;
    align-items: center; justify-content: center; padding: 16px;
  }}
  .modal-overlay.open {{ display: flex; }}
  .modal {{
    background: #111827; border: 1px solid #374151; border-radius: 16px;
    width: 100%; max-width: 760px; max-height: 90vh; display: flex; flex-direction: column;
    box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
    overflow: hidden;
  }}
  .modal-header {{
    padding: 16px 20px; border-bottom: 1px solid #1f2937;
    display: flex; justify-content: space-between; align-items: flex-start;
  }}
  .modal-header h2 {{ margin: 0; font-size: 18px; color: #fff; }}
  .modal-close {{
    background: none; border: none; color: #9ca3af; font-size: 22px; cursor: pointer;
    padding: 0; line-height: 1;
  }}
  .modal-close:hover {{ color: #fff; }}
  .modal-body {{
    padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 16px;
  }}
  .modal-tabs {{
    display: flex; gap: 8px; border-bottom: 1px solid #1f2937; padding-bottom: 8px;
  }}
  .modal-tab {{
    background: none; border: none; color: #9ca3af; padding: 6px 14px;
    border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500;
  }}
  .modal-tab.active {{
    background: #1f2937; color: #38bdf8;
  }}
  .msg-preview {{
    background: #030712; border: 1px solid #1f2937; border-radius: 8px;
    padding: 14px; font-family: monospace; font-size: 12.5px;
    white-space: pre-wrap; word-break: break-word; color: #e5e7eb;
    max-height: 280px; overflow-y: auto;
  }}
  .modal-footer {{
    padding: 14px 20px; border-top: 1px solid #1f2937; background: #0b1120;
    display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 10px;
  }}
  .toast {{
    position: fixed; bottom: 24px; right: 24px; background: #10b981; color: #fff;
    padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 500;
    box-shadow: 0 10px 25px rgba(0,0,0,0.4); z-index: 200;
    display: none; animation: fadeIn 0.2s ease-out;
  }}
  @keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}
</style>
</head>
<body>
  <h1>ПВТ Минск — База контактов и умные шаблоны откликов</h1>
  <div class="subtitle">
    Автоматизированная подготовка сопроводительных писем под каждую компанию на основе резюме разработчика.
  </div>

  <!-- APPLICANT PROFILE PANEL -->
  <div class="profile-panel">
    <div class="profile-header">
      <div class="profile-title">
        <span>👤</span> <strong>Мой профиль соискателя</strong> (автоматически подставляется во все шаблоны)
      </div>
      <div style="font-size:12px; color: #94a3b8;">Данные сохраняются локально в браузере</div>
    </div>
    <div class="profile-grid">
      <div class="form-group">
        <label>Мое имя / Фамилия</label>
        <input type="text" id="pref_name" value="Кирилл Чечулин" placeholder="Кирилл Чечулин">
      </div>
      <div class="form-group">
        <label>Целевая роль</label>
        <input type="text" id="pref_role" value="Разработчик" placeholder="Разработчик">
      </div>
      <div class="form-group">
        <label>Мой Telegram</label>
        <input type="text" id="pref_tg" value="@rustyspy" placeholder="@rustyspy">
      </div>
      <div class="form-group">
        <label>Телефон / Связь</label>
        <input type="text" id="pref_phone" value="+375 (29) 856-73-61" placeholder="+375 (29) 856-73-61">
      </div>
      <div class="form-group">
        <label>Ссылка на Резюме / GitHub</label>
        <input type="text" id="pref_cv" value="https://github.com/NiQkir1" placeholder="https://github.com/NiQkir1">
      </div>
      <div class="form-group">
        <label>Email соискателя</label>
        <input type="text" id="pref_email" value="jotrykastik@gmail.com" placeholder="jotrykastik@gmail.com">
      </div>
    </div>
  </div>

  <!-- CONTROLS & FILTERS -->
  <div class="controls">
    <input type="text" id="q" placeholder="Поиск по названию, стеку, описанию, почте, Telegram...">
    
    <select id="verFilter">
      <option value="hide_false">Только реальные разработчики (скрыть порталы)</option>
      <option value="verified_only">🟢 Только проверенный стек (.NET / Go)</option>
      <option value="dev_all">🟢+🟡 Все IT-разработчики (проверенные + кандидаты)</option>
      <option value="false_positive">⚠️ Только ложные срабатывания (порталы, курсы, 1С)</option>
      <option value="all">Показать вообще все компании ({len(residents)})</option>
    </select>

    <select id="roleFilter">
      <option value="">Все направления</option>
      <option value="C# / .NET">C# / .NET</option>
      <option value="Go (Golang)">Go (Golang)</option>
      <option value="System / Business Analyst">Системный / Бизнес-аналитик</option>
      <option value="Junior / Middle / Intern Mentioned">Junior / Middle / Стажировки</option>
    </select>

    <select id="contactFilter">
      <option value="any">С любыми контактами (Email или ТГ)</option>
      <option value="hr_or_tg">Только HR-почта или Telegram</option>
      <option value="hr">Только с HR / Career почтой</option>
      <option value="tg">Только с Telegram</option>
      <option value="all">С контактами и без</option>
    </select>

    <select id="staffFilter">
      <option value="">Любой размер штата</option>
      <option value="10plus">От 11+ сотрудников (без микро)</option>
      <option value="50plus">От 51+ сотрудников</option>
    </select>

    <button class="btn btn-primary" onclick="copyFilteredHREmails()">📋 Скопировать HR-почты выборки</button>
  </div>

  <!-- STATS -->
  <div class="stats-bar">
    <div id="statsText">Загрузка данных...</div>
    <div style="display:flex; gap:8px; flex-wrap:wrap;">
      <span class="stat-pill">🟢 Проверен в ПВТ/Вендор: <b id="statVerified">0</b></span>
      <span class="stat-pill">🟡 Разработка ПО (сайт): <b id="statUnverified">0</b></span>
      <span class="stat-pill">⚠️ Отфильтровано нерелевантных: <b id="statFalse">0</b></span>
      <span class="stat-pill">✅ Откликов отправлено: <b id="statApplied">0</b></span>
    </div>
  </div>

  <!-- TABLE -->
  <div class="table-container">
    <table>
      <thead>
        <tr>
          <th style="width:20%">Компания & Верификация</th>
          <th style="width:7%">Штат</th>
          <th style="width:16%">Стек / Роли</th>
          <th style="width:18%">HR / Career Почты</th>
          <th style="width:12%">Telegram HR</th>
          <th style="width:12%">Общие контакты</th>
          <th style="width:15%">Отклик & Шаблоны</th>
        </tr>
      </thead>
      <tbody id="tbody"></tbody>
    </table>
  </div>

  <!-- MODAL FOR TEMPLATE -->
  <div class="modal-overlay" id="modalOverlay" onclick="closeModalOnBg(event)">
    <div class="modal" id="modalWindow">
      <div class="modal-header">
        <div>
          <h2 id="mCompanyName">Название компании</h2>
          <div id="mCompanySub" style="font-size:12px; color:var(--muted); margin-top:2px;"></div>
        </div>
        <button class="modal-close" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div style="display:flex; gap:16px; align-items:center; flex-wrap:wrap; background:#0b1120; padding:10px 14px; border-radius:8px; border:1px solid #1e293b;">
          <div style="font-size:12px;"><strong>HR Почты:</strong> <span id="mHREmails">—</span></div>
          <div style="font-size:12px;"><strong>Telegram:</strong> <span id="mTelegrams">—</span></div>
          <div style="font-size:12px;"><strong>Сайт:</strong> <span id="mWebsite">—</span></div>
        </div>

        <div class="modal-tabs">
          <button class="modal-tab active" id="tabEmailBtn" onclick="switchTab('email')">✉️ Письмо для HR (Email)</button>
          <button class="modal-tab" id="tabTgBtn" onclick="switchTab('tg')">💬 Краткое для Telegram</button>
        </div>

        <div id="emailTabContent">
          <div style="font-size:11px; text-transform:uppercase; color:var(--muted); font-weight:600; margin-bottom:4px;">Тема письма:</div>
          <div class="msg-preview" id="mEmailSubject" style="margin-bottom:12px; font-weight:600; color:#38bdf8; max-height:45px;"></div>

          <div style="font-size:11px; text-transform:uppercase; color:var(--muted); font-weight:600; margin-bottom:4px;">Текст сопроводительного письма:</div>
          <div class="msg-preview" id="mEmailBody"></div>
        </div>

        <div id="tgTabContent" style="display:none;">
          <div style="font-size:11px; text-transform:uppercase; color:var(--muted); font-weight:600; margin-bottom:4px;">Текст первого сообщения в Telegram:</div>
          <div class="msg-preview" id="mTgBody"></div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center;">
          <label class="applied-label" style="font-size:13px; color:#cbd5e1;">
            <input type="checkbox" id="mAppliedCheckbox" onchange="toggleAppliedFromModal()">
            Отметить: резюме в эту компанию уже отправлено
          </label>
        </div>
      </div>

      <div class="modal-footer">
        <button class="btn btn-secondary" onclick="closeModal()">Закрыть</button>
        <div style="display:flex; gap:8px;">
          <button class="btn btn-secondary" id="mCopySubjectBtn" onclick="copySubject()">📋 Скопировать только тему</button>
          <button class="btn btn-secondary" onclick="copyActiveMessage()">📋 Скопировать текст</button>
          <button class="btn btn-primary" id="mMailtoBtn">🚀 Открыть в почтовой программе</button>
        </div>
      </div>
    </div>
  </div>

  <div class="toast" id="toast">Скопировано в буфер обмена!</div>

<script>
const DATA = {data_json};

let CURRENT_MODAL_COMPANY = null;
let ACTIVE_TAB = 'email';
let APPLIED_SET = new Set(JSON.parse(localStorage.getItem('htp_applied_companies') || '[]'));

// Load applicant preferences
function loadPreferences() {{
  const prefs = JSON.parse(localStorage.getItem('htp_applicant_prefs') || '{{}}');
  if (prefs.name) document.getElementById('pref_name').value = prefs.name;
  if (prefs.role && !prefs.role.includes('.NET') && !prefs.role.includes('Go') && !prefs.role.includes('Junior') && !prefs.role.includes('Middle')) {{
    document.getElementById('pref_role').value = prefs.role;
  }} else {{
    document.getElementById('pref_role').value = 'Разработчик';
  }}
  if (prefs.tg) document.getElementById('pref_tg').value = prefs.tg;
  if (prefs.phone) document.getElementById('pref_phone').value = prefs.phone;
  if (prefs.cv) document.getElementById('pref_cv').value = prefs.cv;
  if (prefs.email && document.getElementById('pref_email')) document.getElementById('pref_email').value = prefs.email;
}}

function savePreferences() {{
  const prefs = {{
    name: document.getElementById('pref_name').value.trim() || 'Кирилл Чечулин',
    role: document.getElementById('pref_role').value.trim() || 'Разработчик',
    tg: document.getElementById('pref_tg').value.trim() || '@rustyspy',
    phone: document.getElementById('pref_phone').value.trim() || '+375 (29) 856-73-61',
    cv: document.getElementById('pref_cv').value.trim() || 'https://github.com/NiQkir1',
    email: document.getElementById('pref_email') ? document.getElementById('pref_email').value.trim() : 'jotrykastik@gmail.com',
  }};
  localStorage.setItem('htp_applicant_prefs', JSON.stringify(prefs));
  if (CURRENT_MODAL_COMPANY) updateModalContent(CURRENT_MODAL_COMPANY);
}}

['pref_name', 'pref_role', 'pref_tg', 'pref_phone', 'pref_cv', 'pref_email'].forEach(id => {{
  const el = document.getElementById(id);
  if (el) {{
    el.addEventListener('input', savePreferences);
    el.addEventListener('change', savePreferences);
  }}
}});

function getPrefs() {{
  return {{
    name: (document.getElementById('pref_name')?.value || '').trim() || 'Кирилл Чечулин',
    role: (document.getElementById('pref_role')?.value || '').trim() || 'Разработчик',
    tg: (document.getElementById('pref_tg')?.value || '').trim() || '@rustyspy',
    phone: (document.getElementById('pref_phone')?.value || '').trim() || '+375 (29) 856-73-61',
    cv: (document.getElementById('pref_cv')?.value || '').trim() || 'https://github.com/NiQkir1',
    email: (document.getElementById('pref_email')?.value || '').trim() || 'jotrykastik@gmail.com',
  }};
}}

// Build customized template messages for a company
function generateMessages(company) {{
  const p = getPrefs();
  const cName = company.name || 'компания';
  const roleName = p.role || 'Разработчик';

  const emailSubject = `Отклик на позицию разработчика — ${{p.name}}`;

  const emailBody = `Добрый день, команда ${{cName}}!

Меня зовут ${{p.name}}. Нашел контакты вашей компании в каталоге резидентов ПВТ (Минск).

Я — ${{roleName}} с практическим опытом работы в FinTech (Т-Банк), проектирования масштабируемых сервисов (Clean Architecture, CQRS) и интеграции AI/LLM решений (RAG, n8n).

Ключевой опыт из резюме:
• Бэкенд и микросервисы: разработка и модернизация сервисов, безопасность и аутентификация, оптимизация кодовой базы и снижение техдолга.
• Автоматизация поддержки (Service Desk): разработал сервис интеграции Portal ↔ Service Desk с кэшированием справочников и контекстом безопасности, снизив поток повторных обращений на 30–70% (экономия >1 млн руб/год).
• AI & автоматизация: создание корпоративных AI-ассистентов для автоматизации FAQ, RAG-пайплайны и механизм Context Switching на базе LLM для бесшовной смены темы диалога.
• Надежность и процессы: внедрение мониторинга и алертинга RAG-компонентов, автоэскалация инцидентов (снижение MTTR), подготовка ADR/RFC и покрытие unit-тестами.
• Хакатоны: 4-е место и финалист всероссийского хакатона T1 SmartSupport (AI-система поддержки на RAG), T1 Vibecode Interview.
• Образование: БГУИР, Факультет информационных технологий и управления (2024–2028).

Буду рад применить свои навыки для решения задач компании ${{cName}}. Рассматриваю открытые вакансии или варианты сотрудничества в Минске / удаленно.

Контакты:
• Резюме / GitHub: ${{p.cv || 'https://github.com/NiQkir1'}}
• Telegram: ${{p.tg || '@rustyspy'}}
• Телефон: ${{p.phone || '+375 (29) 856-73-61'}}
• Email: ${{p.email || 'jotrykastik@gmail.com'}}

Подробное резюме во вложении. Готов оперативно выйти на связь и выполнить тестовое задание.

С уважением,
${{p.name}}`;

  const tgBody = `Добрый день! Нашел контакт вашей компании (${{cName}}) в реестре ПВТ.

Меня зовут ${{p.name}}, я — разработчик. Имею коммерческий опыт в FinTech (Т-Банк: бэкенд, сервисные интеграции Portal ↔ Service Desk, AI/LLM-ассистенты, RAG, PostgreSQL, Redis, брокеры сообщений). Студент БГУИР (ФИТУ), финалист хакатона T1 SmartSupport.

Ищу открытые вакансии или варианты сотрудничества разработчиком в Минске / удаленно. Подскажите, пожалуйста, актуален ли сейчас найм в вашей команде?

Мой GitHub и проекты: ${{p.cv || 'https://github.com/NiQkir1'}}
Telegram: ${{p.tg || '@rustyspy'}} | Телефон: ${{p.phone || '+375 (29) 856-73-61'}}
Буду признателен за обратную связь! Спасибо.`;

  return {{ emailSubject, emailBody, tgBody }};
}}

function render() {{
  const q = document.getElementById('q').value.toLowerCase().trim();
  const ver = document.getElementById('verFilter').value;
  const role = document.getElementById('roleFilter').value;
  const contact = document.getElementById('contactFilter').value;
  const staff = document.getElementById('staffFilter').value;

  let totalVer = 0, totalUnver = 0, totalFalse = 0;
  DATA.forEach(r => {{
    if (r.verification_level === 'verified') totalVer++;
    else if (r.verification_level === 'dev_unverified') totalUnver++;
    else if (r.verification_level === 'false_positive') totalFalse++;
  }});
  document.getElementById('statVerified').textContent = totalVer;
  document.getElementById('statUnverified').textContent = totalUnver;
  document.getElementById('statFalse').textContent = totalFalse;
  document.getElementById('statApplied').textContent = APPLIED_SET.size;

  const filtered = DATA.filter(r => {{
    const hr = r.hr_emails || [];
    const tg = r.telegrams || [];
    const other = r.other_emails || [];
    const roles = r.matched_roles || [];
    const vLevel = r.verification_level || 'general_dev';

    // Verification filter
    if (ver === 'hide_false' && vLevel === 'false_positive') return false;
    if (ver === 'verified_only' && vLevel !== 'verified') return false;
    if (ver === 'dev_all' && (vLevel === 'false_positive')) return false;
    if (ver === 'false_positive' && vLevel !== 'false_positive') return false;

    // Contact filter
    if (contact === 'any' && hr.length === 0 && tg.length === 0 && other.length === 0) return false;
    if (contact === 'hr_or_tg' && hr.length === 0 && tg.length === 0) return false;
    if (contact === 'hr' && hr.length === 0) return false;
    if (contact === 'tg' && tg.length === 0) return false;

    // Role filter
    if (role && !roles.includes(role)) return false;

    // Staff filter
    if (staff === '10plus' && (r.staff_count === '<10')) return false;
    if (staff === '50plus' && !['51-100', '101-500', '501-1000', '>1000'].includes(r.staff_count)) return false;

    if (q) {{
      const hay = [
        r.name, r.full_name, r.description, r.verification_note,
        ...(r.directions || []), ...roles, ...hr, ...tg, ...other, r.website
      ].join(' ').toLowerCase();
      if (!hay.includes(q)) return false;
    }}
    return true;
  }});

  document.getElementById('statsText').innerHTML = `Найдено компаний: <strong>${{filtered.length}}</strong> (из ${{DATA.length}} в Минске)`;

  const rowsHTML = filtered.map(r => {{
    const isApplied = APPLIED_SET.has(r.name);
    
    // Verification label & badge
    let verClass = r.verification_level || 'general_dev';
    let verLabel = r.verification_label || '⚪ Разработка ПО';
    const verBadgeHTML = `<div class="ver-badge ${{verClass}}" title="${{escapeHTML(r.verification_note || '')}}">${{verLabel}}</div>`;

    const rolesHTML = (r.matched_roles || []).map(m => {{
      let cls = '';
      if (m.includes('C#')) cls = 'csharp';
      else if (m.includes('Go')) cls = 'go';
      else if (m.includes('Analyst')) cls = 'sa';
      else if (m.includes('Junior')) cls = 'jun';
      return `<span class="badge ${{cls}}">${{m}}</span>`;
    }}).join('') || '<span class="badge">Разработка ПО</span>';

    const hrHTML = (r.hr_emails || []).map(e => `<a class="hr-mail" href="mailto:${{e}}">${{e}}</a>`).join('') || '—';
    const tgHTML = (r.telegrams || []).map(t => `<a class="tg-link" target="_blank" href="${{t}}">${{t.replace('https://t.me/', '@')}}</a>`).join('') || '—';
    const otherHTML = (r.other_emails || []).slice(0, 3).map(e => `<a class="other-mail" href="mailto:${{e}}">${{e}}</a>`).join('') || '—';

    let links = [];
    if (r.website) links.push(`<a target="_blank" href="${{r.website}}">Сайт</a>`);
    if (r.career_pages && r.career_pages.length > 0) links.push(`<a target="_blank" href="${{r.career_pages[0]}}">Карьера</a>`);
    if (r.park_url) links.push(`<a target="_blank" href="${{r.park_url}}">ПВТ</a>`);

    const rIdx = DATA.indexOf(r);

    return `<tr class="${{isApplied ? 'status-applied' : ''}}" id="row_${{rIdx}}">
      <td>
        ${{verBadgeHTML}}
        <div style="font-weight:700; font-size:14px; margin-top:2px;">${{r.name}}</div>
        <div style="color:var(--muted); font-size:11px; margin-top:2px;">${{(r.directions || []).slice(0, 2).join(', ')}}</div>
        <div style="margin-top:4px; font-size:12px;">${{links.join(' · ')}}</div>
      </td>
      <td>${{r.staff_count || '—'}}</td>
      <td>${{rolesHTML}}</td>
      <td>${{hrHTML}}</td>
      <td>${{tgHTML}}</td>
      <td>${{otherHTML}}</td>
      <td>
        <div class="action-buttons">
          <button class="btn btn-primary btn-sm" onclick="openTemplateModal(${{rIdx}})">
            ✉️ Шаблон отклика
          </button>
          <button class="btn btn-secondary btn-sm" onclick="quickCopyMessage(${{rIdx}})" title="Быстро скопировать готовый текст письма в буфер">
            📋 Скопировать письмо
          </button>
          <label class="applied-label">
            <input type="checkbox" ${{isApplied ? 'checked' : ''}} onchange="toggleApplied('${{escapeQuotes(r.name)}}', this.checked, ${{rIdx}})">
            ${{isApplied ? '✅ Отправлено' : 'Отметить отклик'}}
          </label>
        </div>
      </td>
    </tr>`;
  }}).join('');

  document.getElementById('tbody').innerHTML = rowsHTML;
  window.CURRENT_FILTERED = filtered;
}}

function escapeHTML(str) {{
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}}

function escapeQuotes(str) {{
  return str.replace(/'/g, "\\'");
}}

function showToast(msg) {{
  const toast = document.getElementById('toast');
  toast.textContent = msg;
  toast.style.display = 'block';
  setTimeout(() => {{ toast.style.display = 'none'; }}, 2500);
}}

function openTemplateModal(index) {{
  const company = DATA[index];
  if (!company) return;
  CURRENT_MODAL_COMPANY = company;
  updateModalContent(company);
  document.getElementById('modalOverlay').classList.add('open');
}}

function updateModalContent(company) {{
  const {{ emailSubject, emailBody, tgBody }} = generateMessages(company);

  document.getElementById('mCompanyName').textContent = company.name;
  document.getElementById('mCompanySub').textContent = `${{company.verification_label || ''}} · Штат: ${{company.staff_count || '—'}} · ${{company.city || 'Минск'}}`;

  // Contacts
  const hrList = company.hr_emails || [];
  document.getElementById('mHREmails').innerHTML = hrList.length > 0 
    ? hrList.map(e => `<a href="mailto:${{e}}" style="color:var(--hr); font-weight:600;">${{e}}</a>`).join(', ')
    : '<span style="color:var(--muted)">не найден (используйте общую почту)</span>';

  const tgList = company.telegrams || [];
  document.getElementById('mTelegrams').innerHTML = tgList.length > 0 
    ? tgList.map(t => `<a href="${{t}}" target="_blank" style="color:#60a5fa; font-weight:500;">${{t.replace('https://t.me/', '@')}}</a>`).join(', ')
    : '<span style="color:var(--muted)">—</span>';

  document.getElementById('mWebsite').innerHTML = company.website 
    ? `<a href="${{company.website}}" target="_blank">${{company.website}}</a>`
    : '—';

  document.getElementById('mEmailSubject').textContent = emailSubject;
  document.getElementById('mEmailBody').textContent = emailBody;
  document.getElementById('mTgBody').textContent = tgBody;

  // Checkbox state
  document.getElementById('mAppliedCheckbox').checked = APPLIED_SET.has(company.name);

  // Setup mailto button
  const toEmail = (company.hr_emails && company.hr_emails[0]) || (company.other_emails && company.other_emails[0]) || '';
  const mailtoBtn = document.getElementById('mMailtoBtn');
  if (toEmail) {{
    const mailtoURL = `mailto:${{encodeURIComponent(toEmail)}}?subject=${{encodeURIComponent(emailSubject)}}&body=${{encodeURIComponent(emailBody)}}`;
    mailtoBtn.onclick = () => {{ window.location.href = mailtoURL; }};
    mailtoBtn.style.display = 'inline-flex';
    mailtoBtn.textContent = `🚀 Открыть в почте (${{toEmail}})`;
  }} else {{
    mailtoBtn.style.display = 'none';
  }}
}}

function closeModal() {{
  document.getElementById('modalOverlay').classList.remove('open');
  CURRENT_MODAL_COMPANY = null;
}}

function closeModalOnBg(e) {{
  if (e.target.id === 'modalOverlay') closeModal();
}}

function switchTab(tab) {{
  ACTIVE_TAB = tab;
  if (tab === 'email') {{
    document.getElementById('tabEmailBtn').classList.add('active');
    document.getElementById('tabTgBtn').classList.remove('active');
    document.getElementById('emailTabContent').style.display = 'block';
    document.getElementById('tgTabContent').style.display = 'none';
    document.getElementById('mCopySubjectBtn').style.display = 'inline-flex';
  }} else {{
    document.getElementById('tabEmailBtn').classList.remove('active');
    document.getElementById('tabTgBtn').classList.add('active');
    document.getElementById('emailTabContent').style.display = 'none';
    document.getElementById('tgTabContent').style.display = 'block';
    document.getElementById('mCopySubjectBtn').style.display = 'none';
  }}
}}

function copySubject() {{
  if (!CURRENT_MODAL_COMPANY) return;
  const {{ emailSubject }} = generateMessages(CURRENT_MODAL_COMPANY);
  navigator.clipboard.writeText(emailSubject).then(() => {{
    showToast('Тема письма скопирована в буфер!');
  }});
}}

function copyActiveMessage() {{
  if (!CURRENT_MODAL_COMPANY) return;
  const {{ emailBody, tgBody }} = generateMessages(CURRENT_MODAL_COMPANY);
  const text = (ACTIVE_TAB === 'email') ? emailBody : tgBody;
  navigator.clipboard.writeText(text).then(() => {{
    showToast((ACTIVE_TAB === 'email') ? 'Текст письма скопирован!' : 'Сообщение для Telegram скопировано!');
  }});
}}

function quickCopyMessage(index) {{
  const company = DATA[index];
  if (!company) return;
  const {{ emailBody }} = generateMessages(company);
  navigator.clipboard.writeText(emailBody).then(() => {{
    showToast(`Текст письма для "${{company.name}}" скопирован!`);
  }});
}}

function toggleApplied(name, isChecked, rowIdx) {{
  if (isChecked) {{
    APPLIED_SET.add(name);
  }} else {{
    APPLIED_SET.delete(name);
  }}
  localStorage.setItem('htp_applied_companies', JSON.stringify(Array.from(APPLIED_SET)));
  document.getElementById('statApplied').textContent = APPLIED_SET.size;
  const row = document.getElementById(`row_${{rowIdx}}`);
  if (row) {{
    if (isChecked) row.classList.add('status-applied');
    else row.classList.remove('status-applied');
  }}
}}

function toggleAppliedFromModal() {{
  if (!CURRENT_MODAL_COMPANY) return;
  const checked = document.getElementById('mAppliedCheckbox').checked;
  const idx = DATA.indexOf(CURRENT_MODAL_COMPANY);
  toggleApplied(CURRENT_MODAL_COMPANY.name, checked, idx);
  render();
}}

function copyFilteredHREmails() {{
  const emails = new Set();
  (window.CURRENT_FILTERED || []).forEach(r => {{
    // Don't copy emails of false positives
    if (r.verification_level === 'false_positive') return;
    (r.hr_emails || []).forEach(e => emails.add(e));
    if (!r.hr_emails || r.hr_emails.length === 0) {{
      (r.other_emails || []).slice(0, 1).forEach(e => emails.add(e));
    }}
  }});
  const list = Array.from(emails).join(', ');
  navigator.clipboard.writeText(list).then(() => {{
    alert(`Скопировано ${{emails.size}} проверенных email-адресов в буфер обмена!`);
  }});
}}

// Listeners
['q', 'verFilter', 'roleFilter', 'contactFilter', 'staffFilter'].forEach(id => {{
  document.getElementById(id).addEventListener('input', render);
  document.getElementById(id).addEventListener('change', render);
}});

loadPreferences();
render();
</script>
</body>
</html>"""
    with open("htp_minsk_dashboard.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("Saved htp_minsk_dashboard.html")

if __name__ == "__main__":
    main()
