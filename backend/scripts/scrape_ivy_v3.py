"""
Scrape Ivy College of Business directory in one shot.

The earlier ivy_v2 scrape grabbed 192 people but left 132 with Department='Unknown
Department' because the directory listing page didn't include department info on
the surface (we'd need each individual profile). Worse, many of those "unknowns"
turned out to be staff (Asst Director, Coordinator, Office Manager) — not
faculty.

Discovery: the master URL https://www.ivybusiness.iastate.edu/directory/ is a
single 549k HTML page that contains all ~330 Ivy people with full structured
fields:

  <a class="iastate22-link-secondary">Lastname, First</a>
  <div><strong>Title: </strong>Professor</div>
  <div><strong>Department: </strong>Marketing</div>
  <div><strong>Office: </strong>1234 Gerdin</div>
  <ul.faculty-staff-card__content-contact>
      <li>email</li>
      <li>phone</li>
  </ul>

No JavaScript rendering required. We extract everything in one request and
filter to faculty (Professor / Lecturer / Instructor / Chair / Dean / Faculty).

Output
------
Writes `backend/data/ivy_v3_faculty.json` to be picked up by merge_faculty_sources.
Sits ABOVE ivy_v2_faculty.json in the SOURCES list, so v3 wins on conflicts.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
OUT_PATH = BASE / "data" / "ivy_v3_faculty.json"
REPORT_PATH = BASE.parent / "tests" / "results" / "IVY_V3_SCRAPE_REPORT.md"

DIR_URL = "https://www.ivybusiness.iastate.edu/directory/"
SITE = "https://www.ivybusiness.iastate.edu"
COLLEGE = "Ivy College of Business"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

FACULTY_TITLE_RE = re.compile(
    r"\b(Professor|Lecturer|Instructor|Faculty|Chair|Dean|Scholar|Endowed)\b",
    re.I,
)
TEACHING_TRACK_RE = re.compile(
    r"\b(Teaching Professor|Lecturer|Instructor|Professor of Practice)\b",
    re.I,
)


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def normalize_url(href: str) -> str:
    if not href:
        return ""
    return urljoin(SITE + "/", href)


def normalize_name(name: str) -> str:
    """'Lastname, First Middle' -> 'First Middle Lastname'."""
    if "," not in name:
        return name.strip()
    last, first = [p.strip() for p in name.split(",", 1)]
    return f"{first} {last}".strip()


def parse_field_div(div: Any, label: str) -> str:
    """Given a <div><strong>Label: </strong>value</div>, return value."""
    strong = div.find("strong")
    if not strong:
        return ""
    if label.lower() not in strong.get_text(strip=True).lower():
        return ""
    # Strip the strong from the text
    text = div.get_text(" ", strip=True)
    return text.split(":", 1)[1].strip() if ":" in text else ""


def parse_directory(html: str) -> list[dict[str, Any]]:
    """Parse all faculty/staff cards from the master directory HTML."""
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    seen_slugs: set[str] = set()

    # Each card has a profile link `iastate22-link-secondary` whose href is the
    # bare netid slug (e.g., "lola7"), to be combined with /directory/.
    for link in soup.find_all("a", class_="iastate22-link-secondary"):
        href = (link.get("href", "") or "").strip()
        if not href:
            continue
        # Skip absolute nav links
        if href.startswith("http") or href.startswith("/"):
            continue
        # Strip trailing slash and accept anything that looks like a netid
        slug = href.rstrip("/")
        if not re.match(r"^[a-z][a-z0-9_-]*$", slug):
            continue
        if slug in seen_slugs:
            continue
        name_text = link.get_text(" ", strip=True)
        if not name_text or "," not in name_text:
            # Real names are "Lastname, First" — skip nav links
            continue
        seen_slugs.add(slug)

        # Walk up to the card container — usually a div containing both the
        # link and the strong-tag fields
        container = link
        for _ in range(6):
            container = container.parent
            if container is None:
                break
            # The card has the Title strong somewhere inside
            if container.find("strong", string=re.compile(r"Title:")):
                break
        if container is None:
            container = link.parent

        # Extract field divs
        title = ""
        department = ""
        office = ""
        for d in container.find_all("div"):
            strong = d.find("strong")
            if not strong:
                continue
            label_text = strong.get_text(strip=True).rstrip(":").strip().lower()
            if label_text == "title":
                title = parse_field_div(d, "Title")
            elif label_text == "department":
                department = parse_field_div(d, "Department")
            elif label_text == "office":
                office = parse_field_div(d, "Office")

        # Email and phone from the contact list
        email = ""
        phone = ""
        contact_list = container.find("ul", class_="faculty-staff-card__content-contact")
        if contact_list:
            mail = contact_list.find("a", href=lambda x: bool(x) and "mailto:" in x)
            if mail:
                email = mail.get("href", "").replace("mailto:", "").strip().lower()
            for li in contact_list.find_all("li"):
                txt = li.get_text(" ", strip=True)
                if re.search(r"\d{3}.*\d{4}", txt) and "@" not in txt:
                    phone = txt
                    break

        # Photo
        photo_url = ""
        img = container.find("img", src=True)
        if img:
            photo_url = normalize_url(img.get("src", ""))

        rows.append({
            "slug": slug,
            "name": normalize_name(name_text),
            "title": title,
            "department": department,
            "office": office,
            "email": email,
            "phone": phone,
            "photo_url": photo_url,
            "profile_url": f"{SITE}/directory/{slug}",
        })

    return rows


def looks_like_faculty(title: str) -> bool:
    return bool(FACULTY_TITLE_RE.search(title or ""))


def is_teaching(title: str) -> bool:
    return bool(TEACHING_TRACK_RE.search(title or ""))


def normalize_record(row: dict[str, Any]) -> dict[str, Any]:
    name = row["name"]
    title = row["title"]
    return {
        "id": slugify(name),
        "name": name,
        "title": title,
        "department": row.get("department") or "Unknown Department",
        "college": COLLEGE,
        "email": row.get("email") or None,
        "profile_url": row["profile_url"],
        "photo_url": row.get("photo_url") or None,
        "research_interests": [],
        "courses_taught": [],
        "is_teaching_faculty": is_teaching(title),
        "source_url": row["profile_url"],
    }


def main() -> int:
    session = requests.Session(impersonate="chrome124")
    started = datetime.now(timezone.utc).isoformat()

    print(f"== Ivy v3 scrape == {started}")
    print(f"Fetching {DIR_URL}")
    r = session.get(DIR_URL, headers=HEADERS, timeout=60)
    r.raise_for_status()
    print(f"Got {len(r.text)} bytes")

    raw_people = parse_directory(r.text)
    print(f"Parsed {len(raw_people)} cards")

    if not raw_people:
        print("ERROR: no cards parsed", file=sys.stderr)
        return 2

    faculty_rows = [p for p in raw_people if looks_like_faculty(p["title"])]
    skipped = len(raw_people) - len(faculty_rows)
    print(f"Faculty (kept): {len(faculty_rows)} (skipped {skipped} non-faculty)")

    # Stats by title and dept
    from collections import Counter
    print("\nTop kept titles:")
    for t, n in Counter(p["title"] for p in faculty_rows).most_common(10):
        print(f"  {n:3d}  {t[:60]}")
    print("\nBy department:")
    for d, n in Counter(p["department"] for p in faculty_rows).most_common(15):
        print(f"  {n:3d}  {d[:50]}")
    print("\nSkipped (non-faculty) sample titles:")
    for t, n in Counter(p["title"] for p in raw_people if not looks_like_faculty(p["title"])).most_common(10):
        print(f"  {n:3d}  {t[:60]}")

    enriched = [normalize_record(r) for r in faculty_rows]
    enriched.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(enriched)} Ivy faculty -> {OUT_PATH}")

    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    title_counts = Counter(r["title"] for r in enriched)
    dept_counts = Counter(r["department"] for r in enriched)
    lines = [
        "# Ivy College of Business Scrape v3 Report",
        "",
        f"Started: {started}",
        f"Finished: {finished}",
        "",
        "## Source",
        f"- {DIR_URL} (single static HTML page, ~330 people)",
        "",
        "## Counts",
        f"- Cards parsed:   {len(raw_people)}",
        f"- Faculty kept:   {len(enriched)}",
        f"- Non-faculty:    {skipped}",
        "",
        "## Faculty filter",
        "",
        "Title contains: Professor, Lecturer, Instructor, Faculty, Chair, Dean, Scholar, Endowed.",
        "Excludes admin/staff (Director, Coordinator, Manager, Bookkeeper, etc.) which the",
        "earlier ivy_v2 scrape misclassified as 'Unknown Department' faculty.",
        "",
        "## By department",
        "",
        "| Department | Count |",
        "|---|---:|",
    ]
    for d, n in sorted(dept_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {d.replace('|', '/')} | {n} |")
    lines += ["", "## Top titles", "", "| Title | Count |", "|---|---:|"]
    for t, n in title_counts.most_common(20):
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
