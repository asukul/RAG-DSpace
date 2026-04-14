"""
Scrape Institute for Transportation (InTrans) staff at intrans.iastate.edu/people/.

InTrans is a research institute that hosts CTRE (Center for Transportation
Research and Education), Iowa LTAP (Local Technical Assistance Program),
the Bridge Engineering Center, MTC, and several other transportation-related
centers. Many of its 60-100 people are NOT regular faculty — they're
Research Engineers / Research Scientists / Technical Coordinators who work
across these centers but aren't in the COE faculty list.

Strategy
--------
Single static HTML page. Each `div.people__single` card has:
  - <a href="/people/{slug}/"> with photo <img>
  - <h3>Lastname, First</h3>
  - <span class="text-uppercase">Title, Center</span>

We optionally fetch each individual `/people/{slug}/` page for bio /
research interests, but the directory has enough for a baseline record.

Output
------
Writes `backend/data/intrans_faculty.json`.
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
OUT_PATH = BASE / "data" / "intrans_faculty.json"
REPORT_PATH = BASE.parent / "tests" / "results" / "INTRANS_SCRAPE_REPORT.md"

DIR_URL = "https://intrans.iastate.edu/people/"
SITE = "https://www.intrans.iastate.edu"
COLLEGE = "Institute for Transportation"

POLITE_DELAY = 0.5
ENRICH_PROFILES = True

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Title regex — keep researchers and engineers and faculty, skip pure admin
KEEP_TITLE_RE = re.compile(
    r"\b(Research|Engineer|Scientist|Specialist|Director|Coordinator|"
    r"Manager|Faculty|Professor|Lecturer|Instructor|Analyst)\b",
    re.I,
)
SKIP_TITLE_RE = re.compile(
    r"\b(Office Coordinator|Administrative|Receptionist|Intern)\b",
    re.I,
)


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def normalize_name(name: str) -> str:
    """Convert 'Lastname, First' or 'Lastname, First Middle' to 'First Middle Lastname'."""
    if "," not in name:
        return name.strip()
    last, first = [p.strip() for p in name.split(",", 1)]
    return f"{first} {last}".strip()


def keep_title(title: str) -> bool:
    if not title:
        return False
    if SKIP_TITLE_RE.search(title):
        return False
    return bool(KEEP_TITLE_RE.search(title))


def parse_directory(html: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()
    for card in soup.select("div.people__single"):
        link = card.find("a", href=True)
        if not link:
            continue
        href = link["href"]
        m = re.search(r"/people/([a-z0-9-]+)/?$", href)
        if not m:
            continue
        slug = m.group(1)
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        h3 = card.find("h3")
        raw_name = h3.get_text(" ", strip=True) if h3 else ""
        if not raw_name:
            continue
        name = normalize_name(raw_name)

        title_span = card.find("span", class_="text-uppercase")
        title_dept = title_span.get_text(" ", strip=True) if title_span else ""
        # Split "Title, Center" — first comma
        title, dept = title_dept, ""
        if "," in title_dept:
            title, dept = title_dept.split(",", 1)
            title = title.strip()
            dept = dept.strip()

        img = card.find("img")
        photo_url = img.get("src", "") if img else ""

        rows.append({
            "slug": slug,
            "name": name,
            "title": title,
            "department": dept or "Institute for Transportation",
            "photo_url": photo_url,
            "profile_url": href,
        })
    return rows


def fetch_profile_extras(session: requests.Session, profile_url: str) -> dict[str, Any]:
    """Get email, bio, research interests from individual profile."""
    extras: dict[str, Any] = {"email": "", "bio": "", "research_interests": []}
    try:
        r = session.get(profile_url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return extras
        soup = BeautifulSoup(r.text, "html.parser")
        # Email
        mail = soup.select_one('a[href^="mailto:"]')
        if mail:
            extras["email"] = mail.get("href", "").replace("mailto:", "").strip().lower()
        # Bio paragraphs from main content area
        main = soup.select_one("main") or soup.select_one("article") or soup.body
        if main:
            paras = []
            for p in main.find_all("p"):
                txt = p.get_text(" ", strip=True)
                if not txt or len(txt) < 40 or "@" in txt:
                    continue
                paras.append(txt)
            extras["bio"] = " ".join(paras)[:2000]
        # Research interests via headings
        for heading in soup.find_all(re.compile(r"^h[1-6]$")):
            ht = heading.get_text(" ", strip=True).lower()
            if "research" in ht or "expertise" in ht or "interest" in ht:
                sib = heading.find_next_sibling()
                if sib:
                    items = sib.find_all("li") if sib.name in ("ul", "ol") else []
                    if items:
                        extras["research_interests"] = [
                            li.get_text(" ", strip=True) for li in items
                            if li.get_text(strip=True)
                        ][:25]
                        break
    except Exception:
        pass
    return extras


def normalize_record(row: dict[str, Any], extras: dict[str, Any]) -> dict[str, Any]:
    name = row["name"]
    title = row["title"]
    return {
        "id": slugify(name),
        "name": name,
        "title": title,
        "department": row.get("department") or "Institute for Transportation",
        "college": COLLEGE,
        "email": extras.get("email") or None,
        "profile_url": row["profile_url"],
        "photo_url": row.get("photo_url") or None,
        "research_interests": extras.get("research_interests") or [],
        "courses_taught": [],
        "is_teaching_faculty": False,
        "source_url": row["profile_url"],
        "bio": (extras.get("bio") or "")[:2000],
    }


def main() -> int:
    session = requests.Session(impersonate="chrome124")
    started = datetime.now(timezone.utc).isoformat()

    print(f"== InTrans scrape == {started}")
    print(f"Fetching {DIR_URL}")
    r = session.get(DIR_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    raw_people = parse_directory(r.text)
    print(f"Parsed {len(raw_people)} cards")

    if not raw_people:
        print("ERROR: no cards parsed", file=sys.stderr)
        return 2

    kept_rows = [p for p in raw_people if keep_title(p["title"])]
    skipped = len(raw_people) - len(kept_rows)
    print(f"Kept {len(kept_rows)} researcher-style entries (skipped {skipped})")

    enriched: list[dict[str, Any]] = []
    enrich_ok = 0
    enrich_fail = 0
    for i, row in enumerate(kept_rows, 1):
        extras = {"email": "", "bio": "", "research_interests": []}
        if ENRICH_PROFILES:
            extras = fetch_profile_extras(session, row["profile_url"])
            if extras.get("bio") or extras.get("email"):
                enrich_ok += 1
            else:
                enrich_fail += 1
        rec = normalize_record(row, extras)
        enriched.append(rec)
        if i % 10 == 0 or i == len(kept_rows):
            print(f"  [{i}/{len(kept_rows)}] {row['name']}")
        time.sleep(POLITE_DELAY)

    enriched.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(enriched)} InTrans staff -> {OUT_PATH}")

    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    title_counts: dict[str, int] = {}
    dept_counts: dict[str, int] = {}
    for r in enriched:
        title_counts[r["title"]] = title_counts.get(r["title"], 0) + 1
        dept_counts[r["department"]] = dept_counts.get(r["department"], 0) + 1
    lines = [
        "# InTrans Scrape Report",
        "",
        f"Started: {started}",
        f"Finished: {finished}",
        "",
        "## Source",
        f"- Directory: {DIR_URL}",
        "",
        "## Counts",
        f"- Cards parsed: {len(raw_people)}",
        f"- Kept (researcher/engineer titles): {len(enriched)}",
        f"- Skipped (admin titles): {skipped}",
        f"- Enriched OK: {enrich_ok}",
        f"- Enrich failed: {enrich_fail}",
        "",
        "## Departments / centers",
        "",
        "| Dept | Count |",
        "|---|---:|",
    ]
    for d, n in sorted(dept_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {d.replace('|', '/')} | {n} |")
    lines += ["", "## Top titles", "", "| Title | Count |", "|---|---:|"]
    for t, n in sorted(title_counts.items(), key=lambda x: -x[1])[:20]:
        lines.append(f"| {t.replace('|', '/')} | {n} |")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
