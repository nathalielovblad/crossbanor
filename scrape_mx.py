"""
scrape_mx.py – Hämtar öppettider från Stockholms crossbanor
Fungerar för: Uringe (KlubbenOnline), Nynäshamn (WordPress/MEC),
              Arlanda (WordPress/TEC), Haninge (eget bokningssystem)
Blockerar:    Botkyrka, Täby (robots.txt) → uppdateras manuellt

Kör: python scrape_mx.py
Kräver: pip install requests beautifulsoup4

Resultatet sparas i oppettider.json
"""

import json
import re
from datetime import date, timedelta
import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; MXSthlmBot/1.0; "
        "+https://din-domän.se kontakta@din-domän.se)"
    )
}

NORMALA_TIDER = {
    # weekday (0=mån, 2=ons, 5=lör, 6=sön)
    2: "17:30–20:30",  # Onsdag
    5: "10:00–14:00",  # Lördag
    6: "10:00–14:00",  # Söndag
}


# ──────────────────────────────────────────────
# URINGE  (KlubbenOnline)
# ──────────────────────────────────────────────

def scrape_uringe() -> list[dict]:
    """Hämtar KlubbenOnline-kalendern för innevarande + nästa månad."""
    events = []
    today = date.today()
    months = [today, (today.replace(day=28) + timedelta(days=4)).replace(day=1)]

    for ref in months:
        url = f"https://uringe.se/kalender?date={ref.isoformat()}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Uringe] Fel för {url}: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")

        month_header = soup.find(string=re.compile(
            r"(januari|februari|mars|april|maj|juni|juli|"
            r"augusti|september|oktober|november|december)\s+\d{4}", re.IGNORECASE))

        current_month = ref.month
        current_year  = ref.year
        if month_header:
            parts = month_header.strip().split()
            mnames = {"januari":1,"februari":2,"mars":3,"april":4,"maj":5,"juni":6,
                      "juli":7,"augusti":8,"september":9,"oktober":10,"november":11,"december":12}
            current_month = mnames.get(parts[0].lower(), ref.month)
            if len(parts) > 1:
                current_year = int(parts[1])

        cells = soup.find_all("td")
        for i, cell in enumerate(cells):
            text = cell.get_text(" ", strip=True)
            day_match = re.match(r"^(\d{1,2})$", text)
            if not day_match:
                continue
            day_num = int(day_match.group(1))
            lookahead = " ".join(
                cells[j].get_text(" ", strip=True)
                for j in range(i+1, min(i+4, len(cells)))
            )
            time_match = re.search(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})", lookahead)
            is_open   = "Öppet"  in lookahead
            is_closed = "Stängt" in lookahead
            if time_match and (is_open or is_closed):
                try:
                    ev_date = date(current_year, current_month, day_num)
                    events.append({
                        "date":  ev_date.isoformat(),
                        "start": time_match.group(1),
                        "end":   time_match.group(2),
                        "open":  is_open,
                        "source": "uringe.se"
                    })
                except ValueError:
                    pass

    seen, unique = set(), []
    for e in events:
        if e["date"] not in seen:
            seen.add(e["date"])
            unique.append(e)

    print(f"  [Uringe] {len(unique)} händelser")
    return unique


# ──────────────────────────────────────────────
# NYNÄSHAMN  (WordPress + MEC)
# ──────────────────────────────────────────────

def scrape_nynashamn() -> list[dict]:
    """WordPress med Modern Events Calendar – hämtar från /kalender/."""
    url = "https://nynashamnsmck.se/kalender/"
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Nynäshamn] Fel: {e}")
        return events

    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text("\n")
    blocks = re.split(r"\n{2,}", text)

    date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")
    time_re = re.compile(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})")

    current_date = None
    for block in blocks:
        dm = date_re.search(block)
        if dm:
            current_date = dm.group(1)
        tm = time_re.search(block)
        if tm and current_date:
            title = block.strip().split("\n")[0].strip()
            is_open = not re.search(r"stäng|reserverad|uthyrd", title, re.IGNORECASE)
            events.append({
                "date":  current_date,
                "start": tm.group(1),
                "end":   tm.group(2),
                "open":  is_open,
                "title": title[:80],
                "source": "nynashamnsmck.se"
            })
            current_date = None

    seen, unique = set(), []
    for e in events:
        key = (e["date"], e["start"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    print(f"  [Nynäshamn] {len(unique)} händelser")
    return unique


# ──────────────────────────────────────────────
# ARLANDA  (WordPress + The Events Calendar)
# ──────────────────────────────────────────────

def scrape_arlanda() -> list[dict]:
    """WordPress med The Events Calendar – hämtar från /traningstider/."""
    url = "https://www.arlandamc.se/traningstider/"
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Arlanda] Fel: {e}")
        return events

    soup = BeautifulSoup(r.text, "html.parser")
    lines = soup.get_text("\n").splitlines()
    date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")
    time_re = re.compile(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})")

    current_date = None
    for line in lines:
        line = line.strip()
        dm = date_re.match(line)
        if dm:
            current_date = dm.group(1)
            continue
        tm = time_re.search(line)
        if tm and current_date and line:
            is_open = not re.search(r"stäng|reserverad|uthyrd", line, re.IGNORECASE)
            events.append({
                "date":  current_date,
                "start": tm.group(1),
                "end":   tm.group(2),
                "open":  is_open,
                "title": line[:80],
                "source": "arlandamc.se"
            })

    seen, unique = set(), []
    for e in events:
        key = (e["date"], e["start"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    print(f"  [Arlanda] {len(unique)} händelser")
    return unique


# ──────────────────────────────────────────────
# HANINGE  (Eget bokningssystem)
# ──────────────────────────────────────────────

def scrape_haninge() -> list[dict]:
    """
    Haninge har ett eget bokningssystem (oppnBokn.php).
    Tabellen visar datum + vem som har bokat (= öppet) eller tomt (= ej planerat).
    OBS: För tillfället är crossbanan stängd, endurobanan öppen normala tider.
    """
    url = "https://anm.haningemotorklubb.se/anm/oppnBokn.php"
    events = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"  [Haninge] Fel: {e}")
        return events

    soup = BeautifulSoup(r.text, "html.parser")

    # Kolla om crossbanan är stängd
    page_text = soup.get_text()
    cross_closed = bool(re.search(r"crossbanan.*(inte|ej|stängd)", page_text, re.IGNORECASE))

    # Hitta tabellen med datum och bokningar
    tables = soup.find_all("table")
    date_re = re.compile(r"(\d{4}-\d{2}-\d{2})")

    for table in tables:
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_text = cells[0].get_text(strip=True)
            dm = date_re.search(date_text)
            if not dm:
                continue

            ev_date_str = dm.group(1)
            ev_date = date.fromisoformat(ev_date_str)
            responsible = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            is_stängt   = "Stängt" in responsible or "stängt" in responsible

            # Har datum en ansvarig person → öppet
            is_open = bool(responsible) and not is_stängt

            if not is_open:
                continue  # hoppa över ej bokade datum

            # Normala tider baserat på veckodag
            weekday = ev_date.weekday()  # 0=mån, 2=ons, 5=lör, 6=sön
            tider = NORMALA_TIDER.get(weekday, "10:00–14:00")
            start, end = tider.split("–")

            events.append({
                "date":       ev_date_str,
                "start":      start,
                "end":        end,
                "open":       True,
                "enduro_only": cross_closed,
                "responsible": responsible,
                "source":     "haningemotorklubb.se"
            })

    cross_status = "STÄNGD (byggs om), endurobanan öppen" if cross_closed else "Öppen"
    print(f"  [Haninge] {len(events)} öppna tillfällen. Crossbanan: {cross_status}")
    return events


# ──────────────────────────────────────────────
# HUVUDPROGRAM
# ──────────────────────────────────────────────

def main():
    print("=== Hämtar crossbanornas öppettider ===\n")

    result = {
        "updated": date.today().isoformat(),
        "banor": [
            {
                "id":     "uringe",
                "name":   "Uringe MX",
                "url":    "https://uringe.se/kalender",
                "events": scrape_uringe()
            },
            {
                "id":     "nynashamn",
                "name":   "Nynäshamn MCK",
                "url":    "https://nynashamnsmck.se/kalender/",
                "events": scrape_nynashamn()
            },
            {
                "id":     "arlanda",
                "name":   "Arlanda MC",
                "url":    "https://www.arlandamc.se/traningstider/",
                "events": scrape_arlanda()
            },
            {
                "id":     "varmdo",
                "name":   "Värmdö MK",
                "url":    "https://varmdomx.se/kalender",
                "events": scrape_varmdo()
            },
            {
                "id":     "uvmk",
                "name":   "Upplands Väsby MK",
                "url":    "https://uvmk.nu/kalender/",
                "note":   "Använder Google Kalender – uppdateras manuellt tills ICS-länk finns.",
                "manual": True,
                "events": scrape_uvmk()
            },
            {
                "id":     "haninge",
                "name":   "Haninge MK",
                "url":    "https://anm.haningemotorklubb.se/anm/oppnBokn.php",
                "note":   "Crossbanan stängd tills vidare – byggs om. Endurobanan öppen normala tider.",
                "events": scrape_haninge()
            },
            {
                "id":     "botkyrka",
                "name":   "Botkyrka MK",
                "url":    "https://www.botkyrkamk.se/kalender",
                "note":   "Blockerar automatisk hämtning. Uppdateras manuellt.",
                "manual": True,
                "events": []  # ← fyll i manuellt
            },
            {
                "id":     "taby",
                "name":   "Täby MK",
                "url":    "https://www.tabymk.se/",
                "note":   "Blockerar automatisk hämtning. Uppdateras manuellt.",
                "manual": True,
                "events": []  # ← fyll i manuellt
            },
        ]
    }

    output = "oppettider.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    total = sum(len(b["events"]) for b in result["banor"])
    print(f"\n✓ {total} händelser sparade i {output}")
    print("\nKör dagligen med cron:")
    print("  0 6 * * * /usr/bin/python3 /path/to/scrape_mx.py")


if __name__ == "__main__":
    main()


# ──────────────────────────────────────────────
# VÄRMDÖ  (KlubbenOnline – samma system som Uringe)
# ──────────────────────────────────────────────

def scrape_varmdo() -> list[dict]:
    """Värmdö använder KlubbenOnline, identisk struktur som Uringe."""
    events = []
    today = date.today()
    months = [today, (today.replace(day=28) + timedelta(days=4)).replace(day=1)]

    for ref in months:
        url = f"https://varmdomx.se/kalender?date={ref.isoformat()}"
        try:
            r = requests.get(url, headers=HEADERS, timeout=10)
            r.raise_for_status()
        except requests.RequestException as e:
            print(f"  [Värmdö] Fel för {url}: {e}")
            continue

        soup = BeautifulSoup(r.text, "html.parser")
        month_header = soup.find(string=re.compile(
            r"(januari|februari|mars|april|maj|juni|juli|"
            r"augusti|september|oktober|november|december)\s+\d{4}", re.IGNORECASE))

        current_month, current_year = ref.month, ref.year
        if month_header:
            parts = month_header.strip().split()
            mnames = {"januari":1,"februari":2,"mars":3,"april":4,"maj":5,"juni":6,
                      "juli":7,"augusti":8,"september":9,"oktober":10,"november":11,"december":12}
            current_month = mnames.get(parts[0].lower(), ref.month)
            if len(parts) > 1:
                current_year = int(parts[1])

        cells = soup.find_all("td")
        for i, cell in enumerate(cells):
            text = cell.get_text(" ", strip=True)
            day_match = re.match(r"^(\d{1,2})$", text)
            if not day_match:
                continue
            day_num = int(day_match.group(1))
            # Hämta nästa 6 celler för att fånga tid + titel
            lookahead_cells = [cells[j].get_text(" ", strip=True) for j in range(i+1, min(i+7, len(cells)))]
            lookahead = " ".join(lookahead_cells)

            time_match = re.search(r"(\d{2}:\d{2})\s*[-–]\s*(\d{2}:\d{2})", lookahead)
            heldag = "Heldag" in lookahead
            stängt = re.search(r"stäng|arbetsdag", lookahead, re.IGNORECASE)

            if not (time_match or heldag):
                continue

            # Hämta händelsetitel (ofta i cell efter tider)
            title = ""
            for lc in lookahead_cells:
                if lc and not re.match(r"\d{2}:\d{2}", lc) and "Värmdö" not in lc and lc != "Heldag":
                    title = lc[:60]
                    break

            is_open = not bool(stängt)
            try:
                ev_date = date(current_year, current_month, day_num)
                events.append({
                    "date":  ev_date.isoformat(),
                    "start": time_match.group(1) if time_match else "Heldag",
                    "end":   time_match.group(2) if time_match else "",
                    "open":  is_open,
                    "title": title,
                    "source": "varmdomx.se"
                })
            except ValueError:
                pass

    seen, unique = set(), []
    for e in events:
        key = (e["date"], e["start"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    print(f"  [Värmdö] {len(unique)} händelser")
    return unique


# ──────────────────────────────────────────────
# UPPLANDS VÄSBY  (Google Kalender – kan ej scrapa direkt)
# Alternativ: hämta senaste nyheter för att plocka ut öppettider
# ──────────────────────────────────────────────

def scrape_uvmk() -> list[dict]:
    """
    UVMK använder Google Kalender inbäddad på sin sida – kan inte hämtas
    automatiskt utan Google Calendar API-nyckel.

    Alternativt: hämta deras senaste nyhetsinlägg som ibland innehåller tider.
    Returnerar [] tills vidare – uppdateras manuellt i oppettider.json.

    TIP: Kontakta UVMK och be dem exportera sin Google Kalender som ICS-länk.
    Lägg sedan till scraping av ICS-flödet här:
        from icalendar import Calendar
        r = requests.get(ICS_URL, ...)
        cal = Calendar.from_ical(r.content)
        for component in cal.walk():
            if component.name == "VEVENT": ...
    """
    print("  [UVMK] Använder Google Kalender – hämtas ej automatiskt (uppdatera manuellt)")
    return []
