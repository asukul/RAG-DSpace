"""
Scrape ISU Extension and Outreach staff directory.

ISU Extension and Outreach is the university's outreach arm. It has ~880
employees ranging from clerical office staff (Office Assistant, Bookkeeper)
to subject-matter experts (Extension Field Agronomist, Field Specialist,
Educator, Specialist, Research Scientist, Associate Professor). The
subject-matter experts ARE faculty in the academic sense — many hold joint
ISU appointments — and almost none of them appear in the college directories.

Strategy
--------
1. Iterate `https://www.extension.iastate.edu/search_staff?term_node_tid_depth=All&page=N`
   until pages return zero rows. ~36 pages, 25 staff each.
2. Parse each `tr.staff-directory-results` table row to extract name slug,
   title, email, phone.
3. Filter to subject-matter staff via title regex.
4. Optionally fetch each kept profile for Program Areas (research interests),
   Base County, and a photo URL. Per-profile fetch is enabled by default.

Output
------
`backend/data/extension_faculty.json` in the standard schema with
college="ISU Extension and Outreach" and department=program area or
"ISU Extension and Outreach" fallback.
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
OUT_PATH = BASE / "data" / "extension_faculty.json"
REPORT_PATH = BASE.parent / "tests" / "results" / "EXTENSION_SCRAPE_REPORT.md"

DIR_BASE = "https://www.extension.iastate.edu"
DIR_URL = f"{DIR_BASE}/search_staff?term_node_tid_depth=All"
COLLEGE = "ISU Extension and Outreach"
DEPT_DEFAULT = "ISU Extension and Outreach"

POLITE_DELAY = 0.3
ENRICH_PROFILES = True
MAX_PAGES = 60   # safety stop
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

# Keep titles that suggest research/teaching/expertise
KEEP_TITLE_RE = re.compile(
    r"\b("
    r"Specialist|Educator|Agronomist|Scientist|Professor|Lecturer|Instructor|"
    r"Director|Coordinator|Researcher|Engineer|Veterinarian|Analyst|Curator|"
    r"Field|Advisor|Educator|Consultant|Faculty|Outreach"
    r")\b",
    re.I,
)
# Drop pure clerical/admin
SKIP_TITLE_RE = re.compile(
    r"^("
    r"Office Assistant|Office Manager|External Bookkeeper|Bookkeeper|"
    r"Receptionist|Custodian|Janitor|Event Planner|Cashier|"
    r"Office Program Assistant|Office Coordinator|Administrative Assistant|"
    r"Secretary|Office Specialist"
    r")$",
    re.I,
)


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def normalize_url(href: str) -> str:
    if not href:
        return ""
    return urljoin(DIR_BASE + "/", href)


def parse_row(row: Any) -> dict[str, Any] | None:
    """Parse one tr.staff-directory-results into a dict."""
    cells = row.find_all("td")
    if len(cells) < 2:
        return None
    # First cell: <h2><a href="/staff/{slug}">Name</a></h2>
    link = cells[0].find("a", href=True)
    if not link:
        return None
    href = link["href"]
    m = re.match(r"/staff/([\w-]+)$", href)
    if not m:
        return None
    netid = m.group(1)
    name = link.get_text(" ", strip=True)
    if not name:
        return None
    # Second cell contains: title, email, phone separated by <br>
    cell = cells[1]
    # Walk children, separating into lines
    lines: list[str] = []
    for child in cell.children:
        if hasattr(child, "name"):
            if child.name == "br":
                continue
            txt = child.get_text(" ", strip=True) if hasattr(child, "get_text") else ""
        else:
            txt = str(child).strip()
        if txt:
            lines.append(txt)
    # The cell text is structured as: title \n email \n phone
    title = ""
    email = ""
    phone = ""
    for line in lines:
        if "@iastate.edu" in line.lower():
            email = line.lower()
        elif re.search(r"\d{3}.*\d{4}", line):
            phone = line
        elif not title:
            title = line
    return {
        "netid": netid,
        "name": name,
        "title": title,
        "email": email,
        "phone": phone,
        "profile_url": normalize_url(href),
    }


def keep_title(title: str) -> bool:
    if not title:
        return False
    if SKIP_TITLE_RE.match(title.strip()):
        return False
    return bool(KEEP_TITLE_RE.search(title))


def fetch_directory_page(session: requests.Session, page: int) -> list[dict[str, Any]]:
    url = f"{DIR_URL}&page={page}"
    r = session.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"directory page {page} HTTP {r.status_code}")
    soup = BeautifulSoup(r.text, "html.parser")
    rows: list[dict[str, Any]] = []
    for tr in soup.select("tr.staff-directory-results"):
        rec = parse_row(tr)
        if rec:
            rows.append(rec)
    return rows


def fetch_profile_extras(session: requests.Session, profile_url: str) -> dict[str, Any]:
    """Fetch a staff profile to enrich with program areas, base county, photo."""
    extras: dict[str, Any] = {
        "research_interests": [],
        "base_county": "",
        "photo_url": "",
    }
    try:
        r = session.get(profile_url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return extras
        soup = BeautifulSoup(r.text, "html.parser")
        # Photo
        main = soup.select_one("#block-isuextension-content") or soup.select_one("main") or soup.body
        if main:
            for img in main.find_all("img", src=True):
                src = img.get("src")
                if not src:
                    continue
                if "smugmug" in src or "person" in src.lower() or "/sites/" in src:
                    extras["photo_url"] = src
                    break
        # Walk for "Program Areas:" / "Base County:" / "Counties Served:"
        text = main.get_text("\n", strip=True) if main else ""
        # Look for "Program Areas:\nLine1\nLine2..." until next "X:" key
        m = re.search(r"Program Areas:\s*\n(.*?)(?=\n\w[^\n]*:|$)", text, re.S)
        if m:
            interests = [
                line.strip() for line in m.group(1).split("\n")
                if line.strip() and ":" not in line
            ]
            extras["research_interests"] = interests[:25]
        m2 = re.search(r"Base County:\s*([^\n]+)", text)
        if m2:
            extras["base_county"] = m2.group(1).strip()[:80]
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
        "department": DEPT_DEFAULT,
        "college": COLLEGE,
        "email": row.get("email") or None,
        "profile_url": row["profile_url"],
        "photo_url": extras.get("photo_url") or None,
        "research_interests": extras.get("research_interests") or [],
        "courses_taught": [],
        "is_teaching_faculty": False,
        "source_url": row["profile_url"],
        "base_county": extras.get("base_county") or "",
    }


def main() -> int:
    session = requests.Session(impersonate="chrome124")
    started = datetime.now(timezone.utc).isoformat()
    print(f"== Extension scrape == {started}")
    print(f"Directory: {DIR_URL}")

    # Step 1: walk all pages of the directory
    all_raw: list[dict[str, Any]] = []
    seen_netids: set[str] = set()
    for page in range(0, MAX_PAGES):
        try:
            rows = fetch_directory_page(session, page)
        except Exception as e:
            print(f"  page {page} failed: {e}")
            break
        if not rows:
            print(f"  page {page} empty — done")
            break
        new_rows = [r for r in rows if r["netid"] not in seen_netids]
        for r in new_rows:
            seen_netids.add(r["netid"])
        all_raw.extend(new_rows)
        print(f"  page {page}: {len(rows)} rows ({len(new_rows)} new) — total {len(all_raw)}")
        time.sleep(POLITE_DELAY)

    print(f"\nTotal directory entries: {len(all_raw)}")

    # Step 2: filter
    kept = [r for r in all_raw if keep_title(r["title"])]
    skipped = len(all_raw) - len(kept)
    print(f"Kept (subject-matter titles): {len(kept)} (skipped {skipped} clerical/admin)")

    # Step 3: enrich
    enriched: list[dict[str, Any]] = []
    enrich_ok = 0
    enrich_fail = 0
    if ENRICH_PROFILES:
        print("\nFetching individual profiles for enrichment...")
        for i, row in enumerate(kept, 1):
            extras = fetch_profile_extras(session, row["profile_url"])
            if extras.get("research_interests") or extras.get("photo_url"):
                enrich_ok += 1
            else:
                enrich_fail += 1
            rec = normalize_record(row, extras)
            enriched.append(rec)
            if i % 25 == 0 or i == len(kept):
                print(f"  [{i}/{len(kept)}] {row['name']} (enriched {enrich_ok}, fail {enrich_fail})")
            time.sleep(POLITE_DELAY)
    else:
        for row in kept:
            enriched.append(normalize_record(row, {}))

    enriched.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(enriched)} Extension staff -> {OUT_PATH}")

    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    title_counts: dict[str, int] = {}
    for r in enriched:
        title_counts[r["title"]] = title_counts.get(r["title"], 0) + 1
    lines = [
        "# ISU Extension and Outreach Scrape Report",
        "",
        f"Started: {started}",
        f"Finished: {finished}",
        "",
        "## Source",
        f"- Directory: {DIR_URL}",
        f"- Per-profile pages: {DIR_BASE}/staff/{{netid}}",
        "",
        "## Counts",
        f"- Directory entries:        {len(all_raw)}",
        f"- Kept (subject-matter):    {len(kept)}",
        f"- Skipped (clerical):       {skipped}",
        f"- Profile enriched (ok):    {enrich_ok}",
        f"- Profile enrich failed:    {enrich_fail}",
        "",
        "## Top titles",
        "",
        "| Title | Count |",
        "|---|---:|",
    ]
    for t, n in sorted(title_counts.items(), key=lambda x: -x[1])[:30]:
        lines.append(f"| {(t or '').replace('|', '/')} | {n} |")
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report -> {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
