"""
Generic scraper for ISU Centers & Institutes people directories.

Strategy
--------
Each center is configured with its people directory URL and a template type.
The scraper fetches the directory page, extracts people using template-specific
parsers, and writes a JSON file per center.

Template families:
  - "drupal"    : ISU iastate22 Drupal theme — /people pages with profile_picture_thumbnail
  - "wordpress" : ISU WordPress themes — varied HTML, profile cards with h3 names
  - "custom"    : One-off patterns needing per-site selectors

Already scraped by dedicated scripts (SKIP these):
  - CIRAS  → scrape_ciras.py  → ciras_faculty.json
  - InTrans → scrape_intrans.py → intrans_faculty.json
  - Library → scrape_library.py → library_faculty.json
  - Extension → scrape_extension.py → extension_faculty.json

Output
------
Writes backend/data/centers/<center_slug>_faculty.json in the standard schema.
Also writes a merged backend/data/centers_faculty.json that combines all centers.

Run:
    python scripts/scrape_centers.py                 # scrape all
    python scripts/scrape_centers.py --center card   # scrape one center
    python scripts/scrape_centers.py --dry-run       # just list centers
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin

from curl_cffi import requests
from bs4 import BeautifulSoup, Tag

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data" / "centers"
MERGED_OUT = BASE / "data" / "centers_faculty.json"

POLITE_DELAY = 0.5  # seconds between requests
TIMEOUT = 15

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}


# ---------------------------------------------------------------------------
# Center configuration
# ---------------------------------------------------------------------------

@dataclass
class CenterConfig:
    slug: str                    # Short identifier
    name: str                    # Full center name
    abbreviation: str            # Abbreviation (e.g., "CARD")
    people_url: str              # URL to the people directory page
    site_base: str               # Site root for resolving relative URLs
    template: str = "drupal"     # "drupal", "wordpress", or "custom"
    college: str = ""            # If people map to a specific college
    department: str = ""         # Default department
    extra_urls: list[str] = field(default_factory=list)  # Additional pages to scrape
    # CSS selectors for custom parsing
    card_selector: str = ""      # Container for each person card
    name_selector: str = ""      # Name element within card
    title_selector: str = ""     # Title/position element
    # Filter: only keep people whose title matches this regex (if set)
    title_filter: str = ""


# Centers from the mapping report.
# Already-scraped centers (CIRAS, InTrans, Library, Extension) are excluded.
CENTERS: list[CenterConfig] = [
    # === GROUP 1: Drupal iastate22 (/people pattern) ===
    CenterConfig(
        slug="bfc", name="Beginning Farmer Center", abbreviation="BFC",
        people_url="https://beginningfarmer.iastate.edu/people",
        site_base="https://beginningfarmer.iastate.edu",
    ),
    CenterConfig(
        slug="bei", name="Bioeconomy Institute", abbreviation="BEI",
        people_url="https://www.biorenew.iastate.edu/people",
        site_base="https://www.biorenew.iastate.edu",
    ),
    CenterConfig(
        slug="calt", name="Center for Agricultural Law and Taxation", abbreviation="CALT",
        people_url="https://www.calt.iastate.edu/people",
        site_base="https://www.calt.iastate.edu",
    ),
    CenterConfig(
        slug="card", name="Center for Agricultural and Rural Development", abbreviation="CARD",
        people_url="https://www.card.iastate.edu/people/",
        site_base="https://www.card.iastate.edu",
    ),
    CenterConfig(
        slug="cssm", name="Center for Survey Statistics and Methodology", abbreviation="CSSM",
        people_url="https://www.cssm.iastate.edu/people",
        site_base="https://www.cssm.iastate.edu",
    ),
    CenterConfig(
        slug="csrl", name="Center for Sustainable Rural Livelihoods", abbreviation="CSRL",
        people_url="https://www.csrl.cals.iastate.edu/people",
        site_base="https://www.csrl.cals.iastate.edu",
    ),
    CenterConfig(
        slug="cbc", name="Crop Bioengineering Center", abbreviation="CBC",
        people_url="https://www.cropbioengineering.iastate.edu/members",
        site_base="https://www.cropbioengineering.iastate.edu",
    ),
    CenterConfig(
        slug="cbbs", name="Laurence H. Baker Center for Bioinformatics and Biological Statistics",
        abbreviation="CBBS",
        people_url="https://www.bioinformatics.iastate.edu/people",
        site_base="https://www.bioinformatics.iastate.edu",
    ),
    CenterConfig(
        slug="lcsa", name="Leopold Center for Sustainable Agriculture", abbreviation="LCSA",
        people_url="https://www.leopold.iastate.edu/people",
        site_base="https://www.leopold.iastate.edu",
    ),
    CenterConfig(
        slug="ppsi", name="Partnerships in Prevention Science Institute", abbreviation="PPSI",
        people_url="https://www.ppsi.iastate.edu/directory",
        site_base="https://www.ppsi.iastate.edu",
    ),
    CenterConfig(
        slug="plantbreeding", name="Raymond F. Baker Center for Plant Breeding",
        abbreviation="RFBCPB",
        people_url="https://www.plantbreeding.iastate.edu/people",
        site_base="https://www.plantbreeding.iastate.edu",
    ),
    CenterConfig(
        slug="ssc", name="Seed Science Center", abbreviation="SSC",
        people_url="https://www.seeds.iastate.edu/people",
        site_base="https://www.seeds.iastate.edu",
    ),
    # === GROUP 2: WordPress ISU-themed ===
    CenterConfig(
        slug="bec", name="Bridge Engineering Center", abbreviation="BEC",
        people_url="https://bec.iastate.edu/people/",
        site_base="https://bec.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="cber", name="Center for Building Energy Research", abbreviation="CBER",
        people_url="https://www.cber.iastate.edu/people/",
        site_base="https://www.cber.iastate.edu",
        template="wordpress",
        extra_urls=[
            "https://www.cber.iastate.edu/people/director/",
            "https://www.cber.iastate.edu/people/affiliates/",
            "https://www.cber.iastate.edu/people/key-figures/",
        ],
    ),
    CenterConfig(
        slug="ccur", name="Center for Crops Utilization Research", abbreviation="CCUR",
        people_url="https://www.ccur.iastate.edu/our-staff/",
        site_base="https://www.ccur.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="cyio", name="Center for Cybersecurity Innovation & Outreach", abbreviation="CyIO",
        people_url="https://www.cyio.iastate.edu/faculty-staff-directory/",
        site_base="https://www.cyio.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="celt", name="Center for Excellence in Learning and Teaching", abbreviation="CELT",
        people_url="https://www.celt.iastate.edu/about/staff-directory/",
        site_base="https://www.celt.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="cfsph", name="Center for Food Security and Public Health", abbreviation="CFSPH",
        people_url="https://www.cfsph.iastate.edu/about/our-team/",
        site_base="https://www.cfsph.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="comfre", name="Center for Multiphase Flow Research and Education",
        abbreviation="CoMFRE",
        people_url="https://comfre.iastate.edu/faculty-2-2/",
        site_base="https://comfre.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="cnde", name="Center for Nondestructive Evaluation", abbreviation="CNDE",
        people_url="https://www.cnde.iastate.edu/cnde-directory/",
        site_base="https://www.cnde.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="ctlt", name="Center for Technology in Learning and Teaching", abbreviation="CTLT",
        people_url="https://www.ctlt.iastate.edu/faculty-and-staff/",
        site_base="https://www.ctlt.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="ctre", name="Center for Transportation Research and Education",
        abbreviation="CTRE",
        people_url="https://ctre.iastate.edu/people/",
        site_base="https://ctre.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="wici", name="Center for Wireless Communities and Innovation", abbreviation="WiCI",
        people_url="https://wici.iastate.edu/team/",
        site_base="https://wici.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="eprc", name="Electric Power Research Center", abbreviation="EPRC",
        people_url="https://www.ece.iastate.edu/eprc/people/",
        site_base="https://www.ece.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="mrc", name="Microelectronics Research Center", abbreviation="MRC",
        people_url="https://www.mrc.iastate.edu/directory-2/",
        site_base="https://www.mrc.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="cptech", name="National Concrete Pavement Technology Center",
        abbreviation="CP Tech Center",
        people_url="https://cptechcenter.org/people/",
        site_base="https://cptechcenter.org",
        template="wordpress",
    ),
    CenterConfig(
        slug="rise", name="Research Institute for Studies in Education", abbreviation="RISE",
        people_url="https://www.rise.hs.iastate.edu/team/",
        site_base="https://www.rise.hs.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="smec", name="Swine Medicine Education Center", abbreviation="SMEC",
        people_url="https://www.smec.iastate.edu/smec/faculty-and-staff/",
        site_base="https://www.smec.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="trac", name="Translational AI Research and Education Center", abbreviation="TrAC",
        people_url="https://trac-ai.iastate.edu/profiles/",
        site_base="https://trac-ai.iastate.edu",
        template="wordpress",
    ),
    # === GROUP 3: WordPress non-ISU theme ===
    CenterConfig(
        slug="cbirc", name="Center for Biorenewable Chemicals", abbreviation="CBiRC",
        people_url="https://www.cbirc.iastate.edu/about/team/",
        site_base="https://www.cbirc.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="nanovaccine", name="Nanovaccine Institute", abbreviation="NI",
        people_url="https://nanovaccine.iastate.edu/members/",
        site_base="https://nanovaccine.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="niamrre", name="National Institute of Antimicrobial Resistance Research & Education",
        abbreviation="NIAMRRE",
        people_url="https://www.niamrre.org/staff/",
        site_base="https://www.niamrre.org",
        template="wordpress",
    ),
    CenterConfig(
        slug="vrac", name="Virtual Reality Applications Center", abbreviation="VRAC",
        people_url="http://www.vrac.iastate.edu/directory",
        site_base="http://www.vrac.iastate.edu",
        template="wordpress",
    ),
    CenterConfig(
        slug="boec", name="Biotechnology Outreach Education Center", abbreviation="BOEC",
        people_url="https://boec.biotech.iastate.edu/our-people/",
        site_base="https://boec.biotech.iastate.edu",
        template="wordpress",
    ),
    # === GROUP 4: Custom ===
    CenterConfig(
        slug="cb2", name="Center for Bioplastics and Biocomposites", abbreviation="CB2",
        people_url="https://cb2center.org/about/iowa-state-faculty-and-staff",
        site_base="https://cb2center.org",
        template="custom",
    ),
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def fetch(url: str) -> Optional[str]:
    """Fetch a URL, return HTML or None on failure."""
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, impersonate="chrome")
        r.raise_for_status()
        return r.text
    except Exception as e:
        log(f"  WARN: failed to fetch {url}: {e}")
        return None


def extract_email(tag: Tag) -> str:
    """Find email in a tag's subtree."""
    for a in tag.find_all("a", href=True):
        href = a["href"]
        if "mailto:" in href:
            email = href.replace("mailto:", "").strip().split("?")[0]
            if "@" in email:
                return email.lower()
    # Check text content for email patterns
    text = tag.get_text(" ", strip=True)
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    return m.group(0).lower() if m else ""


def extract_photo(tag: Tag, site_base: str) -> str:
    """Find photo URL in a tag's subtree."""
    for img in tag.find_all("img"):
        src = img.get("src", "")
        # Skip tiny icons, spacers, logos
        if not src or "logo" in src.lower() or "icon" in src.lower():
            continue
        if "gravatar.com/avatar" in src and "d=blank" in src:
            continue
        return urljoin(site_base + "/", src)
    return ""


def extract_profile_link(tag: Tag, site_base: str) -> str:
    """Find a profile link (a link to an individual person page)."""
    for a in tag.find_all("a", href=True):
        href = a["href"]
        if "mailto:" in href or "tel:" in href:
            continue
        # Skip external links, social media, etc.
        if any(x in href for x in ["facebook", "twitter", "linkedin", "youtube"]):
            continue
        full = urljoin(site_base + "/", href)
        # Likely a profile link if it points back to the same site
        if site_base.replace("http://", "https://").rstrip("/") in full.replace("http://", "https://"):
            return full
    return ""


def is_junk_name(name: str) -> bool:
    """Filter obviously bad names."""
    n = name.strip().lower()
    if not n or len(n) < 3:
        return True
    junk = {"apply", "visit", "contact", "directory", "people", "staff",
            "team", "home", "about", "menu", "search", "back to top",
            "read more", "view profile", "learn more", "view all",
            "loading", "no results"}
    if n in junk:
        return True
    # Names that are just numbers or punctuation
    if re.match(r"^[\d\W]+$", n):
        return True
    return False


def make_record(
    name: str,
    title: str = "",
    email: str = "",
    photo_url: str = "",
    profile_url: str = "",
    center: CenterConfig = None,
) -> dict[str, Any]:
    """Build a standard faculty record."""
    return {
        "id": slugify(name),
        "name": name.strip(),
        "title": title.strip(),
        "department": center.name if center else "",
        "college": center.college or center.name,
        "email": email.strip().lower(),
        "profile_url": profile_url,
        "photo_url": photo_url,
        "research_interests": [],
        "courses_taught": [],
        "is_teaching_faculty": False,
        "source_url": center.people_url if center else "",
        "center_affiliation": center.name if center else "",
    }


# ---------------------------------------------------------------------------
# Template-specific parsers
# ---------------------------------------------------------------------------

def parse_drupal(html: str, center: CenterConfig) -> list[dict]:
    """
    Parse ISU Drupal iastate22 /people pages.
    Pattern: h3 > a (name + link), img.profile_picture_thumbnail, mailto links.
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    seen_names: set[str] = set()

    # Strategy 1: Find all h3 tags that contain links (name + profile)
    for h3 in soup.find_all("h3"):
        a = h3.find("a", href=True)
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        if is_junk_name(name):
            continue
        nkey = slugify(name)
        if nkey in seen_names:
            continue
        seen_names.add(nkey)

        profile_url = urljoin(center.site_base + "/", a["href"])

        # Walk up to find the containing card
        card = h3.parent
        # Try to find a broader container (go up 1-2 levels)
        for _ in range(3):
            if card and card.parent and card.parent.name not in ("body", "html", "[document]"):
                if len(list(card.parent.children)) < 20:
                    card = card.parent
                else:
                    break
            else:
                break

        title = ""
        email = ""
        photo_url = ""

        if card:
            # Title: often in <ul><li> or <p> near the h3
            for li in card.find_all("li"):
                t = li.get_text(" ", strip=True)
                if t and "@" not in t and len(t) < 120:
                    title = t
                    break
            if not title:
                for p in card.find_all("p"):
                    t = p.get_text(" ", strip=True)
                    if t and "@" not in t and len(t) < 120 and not is_junk_name(t):
                        title = t
                        break

            email = extract_email(card)
            photo_url = extract_photo(card, center.site_base)

        records.append(make_record(
            name=name, title=title, email=email,
            photo_url=photo_url, profile_url=profile_url,
            center=center,
        ))

    return records


def _looks_like_person_name(text: str) -> bool:
    """Heuristic: does this text look like a person's name?"""
    text = text.strip()
    if not text or len(text) < 4 or len(text) > 60:
        return False
    # Should have at least 2 words
    words = text.split()
    if len(words) < 2 or len(words) > 6:
        return False
    # Most words should be capitalized (names)
    cap = sum(1 for w in words if w[0].isupper() or w in ("de", "van", "von", "al", "el"))
    if cap < len(words) * 0.5:
        return False
    # Should not contain digits
    if re.search(r"\d", text):
        return False
    # Should not contain "our", "meet", "the" as organizational phrases
    if re.match(r"^(meet|our|the|view|all|see|more)\b", text, re.I):
        return False
    # Should not be all-caps abbreviation (e.g., "BEC", "CARD")
    if text.isupper() and len(text) < 10:
        return False
    return True


# Common section headers to skip when parsing WordPress people pages
_SECTION_HEADERS = {
    "faculty", "staff", "students", "affiliates", "researchers", "directors",
    "leadership", "advisory board", "emeritus", "graduate students",
    "postdoctoral", "administration", "collaborators", "faculty affiliates",
    "faculty fellows", "postdoctoral associates", "card collaborators",
    "our team", "team members", "research team", "student research team",
    "key figures", "director", "associate director", "executive committee",
    "external advisory board", "internal advisory board", "personnel",
}


def parse_wordpress(html: str, center: CenterConfig) -> list[dict]:
    """
    Parse WordPress people pages. More varied HTML structures.
    Common patterns: h3/h4 with name, nearby img, sometimes email.
    """
    soup = BeautifulSoup(html, "html.parser")
    records = []
    seen_names: set[str] = set()

    # Strategy: Find profile cards by looking for heading tags with person names
    for heading in soup.find_all(["h2", "h3", "h4"]):
        raw_name = heading.get_text(" ", strip=True)

        # Skip known section headers
        if raw_name.lower().strip() in _SECTION_HEADERS:
            continue

        # Clean up "Last, First" format
        name = raw_name
        if "," in name and len(name.split(",")) == 2:
            parts = name.split(",")
            first = parts[1].strip()
            last = parts[0].strip()
            # Only flip if both parts look like name fragments (no extra text)
            if len(first.split()) <= 2 and len(last.split()) <= 2:
                name = f"{first} {last}"

        if is_junk_name(name):
            continue
        if not _looks_like_person_name(name):
            continue
        # Skip center abbreviation or center name itself
        if name.upper() == center.abbreviation.upper():
            continue
        if slugify(name) == slugify(center.name):
            continue
        # Skip if name contains "center", "institute", "laboratory" (org, not person)
        if re.search(r"\b(center|centre|institute|laboratory|program|office)\b", name, re.I):
            continue

        nkey = slugify(name)
        if nkey in seen_names:
            continue
        seen_names.add(nkey)

        # Find the nearest containing card — stay tight (1-2 levels up)
        card = heading.parent
        if card and card.parent:
            parent = card.parent
            if parent.name not in ("body", "html", "[document]"):
                direct = [c for c in parent.children if isinstance(c, Tag)]
                if len(direct) < 20:
                    card = parent

        # Check for a link in the heading
        a = heading.find("a", href=True)
        profile_url = ""
        if a:
            href = a["href"]
            if "mailto:" not in href and "tel:" not in href:
                profile_url = urljoin(center.site_base + "/", href)

        title = ""
        email = ""
        photo_url = ""

        if card:
            email = extract_email(card)
            photo_url = extract_photo(card, center.site_base)

            # Title: look for text near the heading that's not the name
            # Only search immediate children / siblings, not the whole subtree
            title_candidates = []
            for el in card.find_all(["p", "span"], recursive=True):
                # Skip if this element is inside another person's heading
                if el.find_parent(["h2", "h3", "h4"]) and el.find_parent(["h2", "h3", "h4"]) != heading:
                    continue
                t = el.get_text(" ", strip=True)
                if not t or len(t) > 120 or len(t) < 3:
                    continue
                if t.lower() == name.lower() or t.lower() == raw_name.lower():
                    continue
                if "@" in t:
                    continue
                if is_junk_name(t):
                    continue
                if re.match(r"^[\d\s\-().+]+$", t):
                    continue
                # Skip if it looks like another person's name
                if _looks_like_person_name(t) and slugify(t) != nkey:
                    continue
                title_candidates.append(t)

            if title_candidates:
                # Pick the shortest reasonable candidate (likely the actual title)
                title = min(title_candidates, key=len)

            if not profile_url:
                profile_url = extract_profile_link(card, center.site_base)

        records.append(make_record(
            name=name, title=title, email=email,
            photo_url=photo_url, profile_url=profile_url,
            center=center,
        ))

    return records


def parse_custom(html: str, center: CenterConfig) -> list[dict]:
    """Fallback parser that tries both Drupal and WordPress strategies."""
    results = parse_drupal(html, center)
    if not results:
        results = parse_wordpress(html, center)
    return results


PARSERS = {
    "drupal": parse_drupal,
    "wordpress": parse_wordpress,
    "custom": parse_custom,
}


# ---------------------------------------------------------------------------
# Main scraping logic
# ---------------------------------------------------------------------------

def scrape_center(center: CenterConfig) -> list[dict]:
    """Scrape a single center's people directory."""
    log(f"Scraping {center.abbreviation} ({center.name})")
    log(f"  URL: {center.people_url}")

    urls = [center.people_url] + center.extra_urls
    all_records: list[dict] = []
    seen_names: set[str] = set()

    parser = PARSERS.get(center.template, parse_custom)

    for url in urls:
        html = fetch(url)
        if not html:
            continue

        records = parser(html, center)
        for r in records:
            nk = slugify(r["name"])
            if nk not in seen_names:
                seen_names.add(nk)
                all_records.append(r)

        time.sleep(POLITE_DELAY)

    # Apply title filter if set
    if center.title_filter:
        pat = re.compile(center.title_filter, re.I)
        before = len(all_records)
        all_records = [r for r in all_records if pat.search(r.get("title", ""))]
        if before != len(all_records):
            log(f"  Title filter: {before} -> {len(all_records)}")

    log(f"  Found {len(all_records)} people")
    return all_records


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape ISU centers/institutes people directories")
    parser.add_argument("--center", help="Scrape only this center (by slug)")
    parser.add_argument("--dry-run", action="store_true", help="List centers without scraping")
    parser.add_argument("--list", action="store_true", help="List all center slugs")
    args = parser.parse_args()

    if args.list or args.dry_run:
        print(f"{'Slug':<20} {'Abbr':<10} {'Template':<12} {'Name'}")
        print("-" * 80)
        for c in CENTERS:
            print(f"{c.slug:<20} {c.abbreviation:<10} {c.template:<12} {c.name}")
        print(f"\nTotal: {len(CENTERS)} centers")
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    targets = CENTERS
    if args.center:
        targets = [c for c in CENTERS if c.slug == args.center]
        if not targets:
            print(f"ERROR: unknown center slug '{args.center}'", file=sys.stderr)
            print("Available:", ", ".join(c.slug for c in CENTERS))
            return 1

    all_merged: list[dict] = []
    stats: list[dict] = []

    for center in targets:
        records = scrape_center(center)

        # Write per-center file
        out_path = DATA_DIR / f"{center.slug}_faculty.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        log(f"  Wrote {out_path.name} ({len(records)} records)")

        all_merged.extend(records)
        stats.append({
            "center": center.slug,
            "name": center.name,
            "abbreviation": center.abbreviation,
            "count": len(records),
            "template": center.template,
        })

    # Write merged output
    with open(MERGED_OUT, "w", encoding="utf-8") as f:
        json.dump(all_merged, f, indent=2, ensure_ascii=False)
    log(f"\nMerged: {MERGED_OUT.name} ({len(all_merged)} total records)")

    # Summary
    print(f"\n{'='*60}")
    print(f"{'Center':<10} {'Count':>6}  {'Name'}")
    print(f"{'-'*60}")
    for s in sorted(stats, key=lambda x: -x["count"]):
        print(f"{s['center']:<10} {s['count']:>6}  {s['name']}")
    print(f"{'-'*60}")
    print(f"{'TOTAL':<10} {len(all_merged):>6}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
