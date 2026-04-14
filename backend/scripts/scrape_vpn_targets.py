"""
VPN-only ISU faculty scrape.

These 9 subdomains pin to ISU datacenter IPs that are unreachable from the
local Windows network without the campus VPN. Run from inside the VPN tunnel.

Two layouts to handle:
  1. Drupal `node--type-people` cards (8 of 9 sites)
  2. HORT custom `directory-list-info` (paginated)

Output: backend/data/vpn_scraped_faculty.json
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"}
TIMEOUT = 25

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
OUT_FILE = os.path.join(DATA_DIR, "vpn_scraped_faculty.json")


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", (name or "").lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


@dataclass
class FacultyRow:
    id: str
    name: str
    title: str = ""
    department: str = ""
    college: str = "College of Liberal Arts and Sciences"
    email: str = ""
    profile_url: str = ""
    photo_url: str = ""
    research_interests: List[str] = field(default_factory=list)
    courses_taught: List[str] = field(default_factory=list)
    is_teaching_faculty: bool = False
    source_url: str = ""


def fetch(url: str, retries: int = 3) -> Optional[str]:
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code in (403, 503):
                time.sleep(1 + attempt)
                continue
            print(f"  fetch {url} -> {r.status_code}", file=sys.stderr)
            return None
        except Exception as e:
            print(f"  fetch err {url}: {e}", file=sys.stderr)
            time.sleep(1 + attempt)
    return None


def absolute(base: str, href: str) -> str:
    return urllib.parse.urljoin(base, href)


# ---------------------------------------------------------------------------
# Parser 1: Drupal node--type-people cards
# ---------------------------------------------------------------------------

def parse_drupal_people(
    html: str,
    base_url: str,
    department: str,
    college: str,
    source_url: str,
) -> List[FacultyRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[FacultyRow] = []
    seen = set()

    for art in soup.select("article.node--type-people"):
        # Name + profile URL
        name_el = art.select_one("h3.people-teaser-name a, h2.people-teaser-name a, .people-teaser-name a")
        if not name_el:
            continue
        name = name_el.get_text(" ", strip=True)
        if not name or len(name) < 3 or name.lower() in seen:
            continue
        seen.add(name.lower())

        prof_url = absolute(base_url, name_el.get("href", ""))

        # Title (positions are a list)
        positions = []
        for li in art.select("ul.isu-people_position-list li, .isu-people_position-list li"):
            t = li.get_text(" ", strip=True)
            if t:
                positions.append(t)
        title = " / ".join(positions) if positions else "Faculty"

        # Email
        email = ""
        em = art.select_one(".isu-people_email a, a[href^='mailto:']")
        if em and em.get("href", "").startswith("mailto:"):
            email = em["href"].replace("mailto:", "").strip()

        # Photo
        img = art.select_one(".isu-people_pic, img")
        photo = absolute(base_url, img["src"]) if img and img.get("src") else ""

        # Filter to faculty (drop if title is clearly admin/staff/student)
        title_lower = title.lower()
        if any(k in title_lower for k in (
            "graduate student", "phd student", "phd candidate",
            "academic adviser", "academic advisor",
            "administrative", "office assistant",
            "secretary", "receptionist",
        )):
            continue

        out.append(FacultyRow(
            id=slugify(name),
            name=name,
            title=title,
            department=department,
            college=college,
            email=email,
            profile_url=prof_url,
            photo_url=photo,
            source_url=source_url,
        ))

    return out


# ---------------------------------------------------------------------------
# Parser 2: HORT custom directory-list-info
# ---------------------------------------------------------------------------

def parse_hort_directory_page(
    html: str,
    base_url: str,
    department: str,
    college: str,
    source_url: str,
) -> List[FacultyRow]:
    soup = BeautifulSoup(html, "html.parser")
    out: List[FacultyRow] = []
    for li in soup.select("li.directory-list-left-column"):
        name_a = li.select_one("h3 a")
        if not name_a:
            continue
        name = name_a.get_text(" ", strip=True)
        if not name or len(name) < 3:
            continue
        prof_url = absolute(base_url, name_a.get("href", ""))

        email = ""
        em = li.select_one("a[href^='mailto:']")
        if em:
            email = em["href"].replace("mailto:", "").strip()

        out.append(FacultyRow(
            id=slugify(name),
            name=name,
            title="Faculty",  # HORT directory listing doesn't expose titles inline
            department=department,
            college=college,
            email=email,
            profile_url=prof_url,
            source_url=source_url,
        ))
    return out


def scrape_hort() -> List[FacultyRow]:
    base = "https://www.hort.iastate.edu/directory-section/faculty/"
    rows: List[FacultyRow] = []
    seen = set()
    for page in range(1, 8):
        url = base if page == 1 else f"{base}page/{page}/"
        html = fetch(url)
        if not html:
            break
        page_rows = parse_hort_directory_page(
            html, url,
            department="Horticulture",
            college="College of Agriculture and Life Sciences",
            source_url=base,
        )
        if not page_rows:
            break
        added = 0
        for r in page_rows:
            if r.name.lower() in seen:
                continue
            seen.add(r.name.lower())
            rows.append(r)
            added += 1
        if added == 0:
            break
        time.sleep(0.3)
    return rows


# ---------------------------------------------------------------------------
# Per-target scrapers (Drupal-pattern sites)
# ---------------------------------------------------------------------------

DRUPAL_TARGETS = [
    {
        "label": "ageds",
        "url": "https://www.ageds.iastate.edu/people/faculty",
        "fallback_url": "https://www.ageds.iastate.edu/people",
        "department": "Agricultural Education and Studies",
        "college": "College of Agriculture and Life Sciences",
    },
    {
        "label": "ans",
        "url": "https://www.ans.iastate.edu/people/faculty",
        "department": "Animal Science",
        "college": "College of Agriculture and Life Sciences",
    },
    {
        "label": "nrem",
        "url": "https://www.nrem.iastate.edu/people/faculty",
        "department": "Natural Resource Ecology and Management",
        "college": "College of Agriculture and Life Sciences",
    },
    {
        "label": "ppem",
        "url": "https://www.ppem.iastate.edu/people/faculty",
        "fallback_url": "https://www.ppem.iastate.edu/people",
        "department": "Plant Pathology, Entomology and Microbiology",
        "college": "College of Agriculture and Life Sciences",
    },
    {
        "label": "bcbio",
        "url": "https://bcbio.las.iastate.edu/people",
        "department": "Bioinformatics and Computational Biology",
        "college": "College of Liberal Arts and Sciences",
    },
    {
        "label": "ensci",
        "url": "https://ensci.iastate.edu/people",
        "department": "Environmental Science",
        "college": "College of Liberal Arts and Sciences",
    },
    {
        "label": "datascience",
        "url": "https://datascience.iastate.edu/people",
        "department": "Data Science",
        "college": "College of Liberal Arts and Sciences",
    },
    {
        "label": "ihs",
        "url": "https://integratedhealthsciences.iastate.edu/people",
        "department": "Integrated Health Sciences",
        "college": "College of Liberal Arts and Sciences",
    },
]


def scrape_drupal(target: Dict) -> List[FacultyRow]:
    url = target["url"]
    html = fetch(url)
    if not html:
        url = target.get("fallback_url") or url
        html = fetch(url)
    if not html:
        return []
    return parse_drupal_people(
        html, url,
        department=target["department"],
        college=target["college"],
        source_url=url,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    all_rows: List[FacultyRow] = []
    counts: Dict[str, int] = {}

    for target in DRUPAL_TARGETS:
        label = target["label"]
        print(f"[{label}] scraping...", flush=True)
        try:
            rows = scrape_drupal(target)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr)
            counts[label] = 0
            continue
        counts[label] = len(rows)
        print(f"  -> {len(rows)} rows")
        all_rows.extend(rows)
        time.sleep(0.4)

    print("[hort] scraping...", flush=True)
    try:
        hort_rows = scrape_hort()
    except Exception as e:
        print(f"  FAILED: {e}", file=sys.stderr)
        hort_rows = []
    counts["hort"] = len(hort_rows)
    print(f"  -> {len(hort_rows)} rows")
    all_rows.extend(hort_rows)

    # Dedupe across by (name, dept)
    seen = set()
    deduped: List[FacultyRow] = []
    for r in all_rows:
        key = (r.name.lower(), r.department.lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)

    print()
    print("=" * 60)
    print("SUMMARY")
    print("-" * 60)
    for label, n in counts.items():
        print(f"  {label:15s}  {n}")
    print("-" * 60)
    print(f"  Total raw      {sum(counts.values())}")
    print(f"  After dedupe   {len(deduped)}")

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in deduped], f, indent=2, ensure_ascii=False)
    print(f"\nWrote: {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
