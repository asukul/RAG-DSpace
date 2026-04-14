"""
Scrape ISU Library faculty (librarians, archivists, curators) from
https://www.lib.iastate.edu/about-us/staff-directory.

Strategy
--------
The directory is a single static Drupal page that lists ~180 staff. Each
person has a card with a profile link `/people/{slug}`, a title line
("Social Sciences and Humanities Librarian", "University Archivist", ...),
an email, an optional phone, and a photo.

ISU librarians are tenure-track *faculty*. We keep records whose title
contains any of: Librarian, Archivist, Curator, Professor, Dean. Everyone
else (Library Assistant, Coordinator, Specialist) is filtered out as staff.

Per profile we then GET `/people/{slug}` to enrich with subject area / bio
text. Optional but useful for embeddings.

Output
------
Writes `backend/data/library_faculty.json` in the standard schema:
  { id, name, title, department, college, email, profile_url, photo_url,
    research_interests, courses_taught, is_teaching_faculty, source_url }
"""
from __future__ import annotations

import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from curl_cffi import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
OUT_PATH = BASE / "data" / "library_faculty.json"
REPORT_PATH = BASE.parent / "tests" / "results" / "LIBRARY_SCRAPE_REPORT.md"

DIR_URL = "https://www.lib.iastate.edu/about-us/staff-directory"
SITE = "https://www.lib.iastate.edu"

POLITE_DELAY = 0.5  # 2/sec — single host, ~180 fetches
COLLEGE = "University Library"  # Library is a unit, not a "college"; treat as its own bucket
DEPT_DEFAULT = "University Library"

# Faculty title regex per agent's research
FACULTY_TITLE_RE = re.compile(
    r"\b(Librarian|Archivist|Curator|Professor|Dean)\b",
    re.I,
)
TEACHING_TRACK_RE = re.compile(
    r"\b(Teaching|Lecturer|Instructor)\b",
    re.I,
)

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def looks_like_faculty(title: str) -> bool:
    return bool(FACULTY_TITLE_RE.search(title or ""))


def is_teaching(title: str) -> bool:
    return bool(TEACHING_TRACK_RE.search(title or ""))


def normalize_url(href: str) -> str:
    if not href:
        return ""
    if href.startswith("http"):
        return href
    if href.startswith("/"):
        return f"{SITE}{href}"
    return f"{SITE}/{href}"


def parse_directory(html: str) -> list[dict[str, Any]]:
    """
    Walk the directory page and pull each profile card.

    Selectors discovered by inspecting the live HTML:
      - Card container: div.faculty-staff-card__content
      - Name link:      p.faculty-staff-card__content-title > a
      - Title/dept:     p.faculty-staff-card__content-body
                        Format: "Title, Department" — split on first comma.
      - Contact:        ul.faculty-staff-card__content-contact > li
    """
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    for card in soup.select("div.faculty-staff-card__content"):
        # Name and slug
        link = card.select_one("p.faculty-staff-card__content-title a")
        if not link:
            continue
        href = link.get("href") or ""
        slug = href.rstrip("/").split("/")[-1]
        if not slug or slug in seen_slugs:
            continue
        # Drop the trailing arrow span text — get_text already collapses it
        name_text = re.sub(r"\s+", " ", link.get_text(strip=True)).strip()
        if not name_text:
            continue
        seen_slugs.add(slug)

        # Title and department (split first comma)
        body = card.select_one("p.faculty-staff-card__content-body")
        title = ""
        dept = ""
        if body:
            txt = re.sub(r"\s+", " ", body.get_text(" ", strip=True)).strip()
            if "," in txt:
                title, dept = txt.split(",", 1)
                title = title.strip()
                dept = dept.strip()
            else:
                title = txt

        # Email
        email = ""
        mail = card.select_one('a[href^="mailto:"]')
        if mail:
            email = mail.get("href", "").replace("mailto:", "").strip().lower()

        # Photo lives outside the content div but within the same card —
        # walk up to the card root.
        photo_url = ""
        card_root = card.parent  # the outer faculty-staff-card div
        if card_root:
            img = card_root.select_one("img")
            if img:
                src = img.get("src", "") or img.get("data-src", "")
                photo_url = normalize_url(src)

        rows.append({
            "slug": slug,
            "name": name_text,
            "title": title,
            "department": dept or DEPT_DEFAULT,
            "email": email,
            "photo_url": photo_url,
            "profile_url": normalize_url(href),
        })

    return rows


def fetch_profile_extras(session: requests.Session, profile_url: str) -> dict[str, Any]:
    """Fetch the individual profile page to extract bio / subject areas."""
    extras: dict[str, Any] = {"bio": "", "research_interests": []}
    try:
        r = session.get(profile_url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return extras
        soup = BeautifulSoup(r.text, "html.parser")
        # Bio is usually in the body of the page after the photo and contact info
        main = soup.select_one("main") or soup.select_one("#main-content") or soup.body
        if not main:
            return extras
        # Grab all <p> text from main, excluding contact info lines
        paras = []
        for p in main.find_all("p"):
            txt = p.get_text(" ", strip=True)
            if not txt or len(txt) < 40:
                continue
            if "@" in txt or re.match(r"^\d{3}-\d{3}", txt):
                continue
            paras.append(txt)
        extras["bio"] = " ".join(paras)[:2000]
        # Subject areas: look for headings like "Subject Areas", "Research Interests"
        for heading in main.find_all(re.compile(r"^h[1-6]$")):
            ht = heading.get_text(" ", strip=True).lower()
            if "subject" in ht or "research interest" in ht or "expertise" in ht:
                # Next sibling list/paragraph
                sib = heading.find_next_sibling()
                if sib:
                    items = sib.find_all("li") if sib.name in ("ul", "ol") else []
                    if items:
                        extras["research_interests"] = [
                            li.get_text(" ", strip=True) for li in items
                            if li.get_text(strip=True)
                        ][:25]
                    else:
                        text = sib.get_text(" ", strip=True)
                        if text:
                            extras["research_interests"] = [
                                t.strip() for t in re.split(r"[;\n,]", text) if t.strip()
                            ][:25]
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
        "department": row.get("department") or DEPT_DEFAULT,
        "college": COLLEGE,
        "email": row.get("email") or None,
        "profile_url": row["profile_url"],
        "photo_url": row.get("photo_url") or None,
        "research_interests": extras.get("research_interests") or [],
        "courses_taught": [],
        "is_teaching_faculty": is_teaching(title),
        "source_url": row["profile_url"],
        "bio": (extras.get("bio") or "")[:2000],
    }


def main() -> int:
    session = requests.Session(impersonate="chrome124")
    started = datetime.now(timezone.utc).isoformat()

    print(f"== ISU Library scrape == {started}")
    print(f"Fetching {DIR_URL}")
    r = session.get(DIR_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    print(f"Got {len(r.text)} bytes")

    raw_people = parse_directory(r.text)
    print(f"Parsed {len(raw_people)} directory entries")

    if not raw_people:
        print("ERROR: no entries parsed — selectors may be wrong", file=sys.stderr)
        return 2

    faculty_rows = [p for p in raw_people if looks_like_faculty(p.get("title", ""))]
    skipped = [p for p in raw_people if not looks_like_faculty(p.get("title", ""))]
    print(f"Faculty candidates: {len(faculty_rows)} (skipped {len(skipped)} non-faculty)")

    print("\nFetching individual profiles for enrichment...")
    enriched: list[dict[str, Any]] = []
    enrich_ok = 0
    enrich_fail = 0
    for i, p in enumerate(faculty_rows, 1):
        extras = fetch_profile_extras(session, p["profile_url"])
        if extras.get("bio") or extras.get("research_interests"):
            enrich_ok += 1
        else:
            enrich_fail += 1
        rec = normalize_record(p, extras)
        enriched.append(rec)
        if i % 10 == 0 or i == len(faculty_rows):
            print(f"  [{i}/{len(faculty_rows)}] {p['name']}")
        time.sleep(POLITE_DELAY)

    # Sort by name
    enriched.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(enriched)} library faculty -> {OUT_PATH}")

    # Report
    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    title_counts: dict[str, int] = {}
    for r in enriched:
        title_counts[r["title"]] = title_counts.get(r["title"], 0) + 1

    lines = [
        "# ISU Library Faculty Scrape Report",
        "",
        f"Started:  {started}",
        f"Finished: {finished}",
        "",
        "## Source",
        "",
        f"- Directory: {DIR_URL}",
        f"- Each profile fetched at: {SITE}/people/{{slug}}",
        "- Static Drupal HTML; uses curl_cffi for Cloudflare bypass.",
        "",
        "## Counts",
        "",
        f"- Raw directory entries:  {len(raw_people)}",
        f"- Faculty (kept):         {len(enriched)}",
        f"- Non-faculty (skipped):  {len(skipped)}",
        f"- Profile enriched (ok):  {enrich_ok}",
        f"- Profile enrich failed:  {enrich_fail}",
        "",
        "## Faculty filter rule",
        "",
        "Title must match one of: Librarian, Archivist, Curator, Professor, Dean.",
        "ISU librarians are tenure-track faculty.",
        "",
        "## Top titles",
        "",
        "| Title | Count |",
        "|---|---:|",
    ]
    for t, n in sorted(title_counts.items(), key=lambda x: -x[1])[:25]:
        safe = (t or "").replace("|", "/")
        lines.append(f"| {safe} | {n} |")
    lines += [
        "",
        "## Output",
        "",
        f"- `{OUT_PATH.relative_to(BASE.parent) if OUT_PATH.is_relative_to(BASE.parent) else OUT_PATH}`",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Report -> {REPORT_PATH}")

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("Interrupted")
        sys.exit(130)
