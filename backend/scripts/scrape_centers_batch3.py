"""
Batch 3 center scraper: CEAH, Catt Center, CFSPH.

Scrapes three ISU research centers and writes JSON files to backend/data/centers/.

Centers:
  1. CEAH  - Center for Excellence in Arts & Humanities (Drupal, isu-horizontal-card)
  2. Catt  - Carrie Chapman Catt Center for Women and Politics (WordPress LAS)
  3. CFSPH - Center for Food Security and Public Health (WordPress, h5 cards)

Run:
    python scripts/scrape_centers_batch3.py
"""
from __future__ import annotations

import gzip
import json
import re
import ssl
import sys
import os
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parent.parent
DATA_DIR = BASE / "data" / "centers"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Accept-Language": "en-US,en;q=0.9",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# Allow self-signed / outdated certs on ISU sub-sites
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def fetch(url: str) -> str:
    """Fetch a URL with urllib.request, handling gzip and redirects."""
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=20, context=_CTX) as resp:
        data = resp.read()
        # Handle gzip-encoded responses
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        elif data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.decode("utf-8", errors="replace")


def normalize_name(name: str) -> str:
    """Collapse multiple whitespace and strip a name."""
    return re.sub(r"\s+", " ", name).strip()


def slugify(name: str) -> str:
    """Generate a slug ID from a person's name."""
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def extract_email(tag) -> str:
    """Find an email address in a tag's subtree."""
    for a in tag.find_all("a", href=True):
        href = a["href"]
        if "mailto:" in href:
            email = href.replace("mailto:", "").strip().split("?")[0]
            if "@" in email:
                return email.lower()
    # Fallback: regex on text content
    text = tag.get_text(" ", strip=True)
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    return m.group(0).lower() if m else ""


def is_junk_name(name: str) -> bool:
    """Filter obviously bad names."""
    n = name.strip().lower()
    if not n or len(n) < 3:
        return True
    junk = {
        "apply", "visit", "contact", "directory", "people", "staff",
        "team", "home", "about", "menu", "search", "back to top",
        "read more", "view profile", "learn more", "view all",
        "loading", "no results", "meet our team", "our team",
        "profiles", "profile", "previous", "next",
        "quick links", "related links", "footer", "header",
        "main navigation", "site navigation", "skip to content",
    }
    if n in junk:
        return True
    if re.match(r"^[\d\W]+$", n):
        return True
    return False


def make_record(name: str, email: str, center_name: str, source_url: str) -> dict:
    """Build a standard faculty record for batch-3 centers."""
    clean_name = normalize_name(name)
    return {
        "id": slugify(clean_name),
        "name": clean_name,
        "email": email.strip().lower() if email else "",
        "department": center_name,
        "center_affiliation": center_name,
        "source_url": source_url,
    }


# ---------------------------------------------------------------------------
# 1. CEAH  --  Drupal iastate22 with isu-horizontal-card layout
# ---------------------------------------------------------------------------

def scrape_ceah() -> list[dict]:
    """Scrape Center for Excellence in the Arts and Humanities."""
    url = "https://ceah.iastate.edu/people"
    center_name = "Center for Excellence in the Arts and Humanities"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen = set()

    # Pattern: h3 > a with person name, mailto links nearby
    for h3 in soup.find_all("h3"):
        a = h3.find("a", href=True)
        if not a:
            continue
        name = a.get_text(" ", strip=True)
        if is_junk_name(name):
            continue
        key = slugify(name)
        if key in seen:
            continue
        seen.add(key)

        # Walk up to find the containing card (1-3 levels)
        card = h3.parent
        for _ in range(3):
            if card and card.parent and card.parent.name not in ("body", "html", "[document]"):
                if len(list(card.parent.children)) < 30:
                    card = card.parent
                else:
                    break
            else:
                break

        email = extract_email(card) if card else ""

        records.append(make_record(name, email, center_name, url))

    return records


# ---------------------------------------------------------------------------
# 2. Catt Center  --  WordPress LAS site with profile cards
# ---------------------------------------------------------------------------

def scrape_cattcenter() -> list[dict]:
    """Scrape Carrie Chapman Catt Center for Women and Politics."""
    # Original URL redirects: wp.las.iastate.edu -> cattcenter.iastate.edu
    url = "https://cattcenter.iastate.edu/profiles/"
    center_name = "Carrie Chapman Catt Center for Women and Politics"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen = set()

    # Structure: div.faculty-staff-card contains
    #   div.faculty-staff-card__content which has:
    #     h3.faculty-staff-card__content-name  (person name)
    #     ul.faculty-staff-card__content-contact  (mailto links)
    for card in soup.find_all("div", class_="faculty-staff-card__content"):
        h3 = card.find("h3")
        if not h3:
            continue
        name = h3.get_text(" ", strip=True)
        if is_junk_name(name):
            continue
        # Must look like a person name: 2+ words, no digits
        words = name.split()
        if len(words) < 2 or len(words) > 6:
            continue
        if re.search(r"\d", name):
            continue

        key = slugify(normalize_name(name))
        if key in seen:
            continue
        seen.add(key)

        # Extract email from this specific card's contact list
        email = extract_email(card)

        records.append(make_record(name, email, center_name, url))

    # Fallback: if the CSS-class approach found nothing, try generic heading scan
    if not records:
        for heading in soup.find_all(["h2", "h3", "h4"]):
            name = heading.get_text(" ", strip=True)
            if is_junk_name(name):
                continue
            words = name.split()
            if len(words) < 2 or len(words) > 6:
                continue
            if re.search(r"\d", name):
                continue
            cap_count = sum(1 for w in words if w[0].isupper())
            if cap_count < len(words) * 0.5:
                continue

            key = slugify(normalize_name(name))
            if key in seen:
                continue
            seen.add(key)

            # Use immediate parent only to avoid cross-contamination
            card = heading.parent
            email = extract_email(card) if card else ""
            records.append(make_record(name, email, center_name, url))

    return records


# ---------------------------------------------------------------------------
# 3. CFSPH  --  WordPress with h5 person cards
# ---------------------------------------------------------------------------

def scrape_cfsph() -> list[dict]:
    """Scrape Center for Food Security and Public Health."""
    url = "https://www.cfsph.iastate.edu/about/our-team/"
    center_name = "Center for Food Security and Public Health"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen = set()

    # Pattern: h5 > a with person name linking to /team/slug/
    for h5 in soup.find_all("h5"):
        a = h5.find("a", href=True)
        if a:
            name = a.get_text(" ", strip=True)
        else:
            name = h5.get_text(" ", strip=True)

        if is_junk_name(name):
            continue

        # Must look like a person name
        words = name.split()
        if len(words) < 2 or len(words) > 6:
            continue
        if re.search(r"\d", name):
            continue

        key = slugify(name)
        if key in seen:
            continue
        seen.add(key)

        # Walk up to find card container
        card = h5.parent
        for _ in range(3):
            if card and card.parent and card.parent.name not in ("body", "html", "[document]"):
                if len(list(card.parent.children)) < 30:
                    card = card.parent
                else:
                    break
            else:
                break

        email = extract_email(card) if card else ""

        records.append(make_record(name, email, center_name, url))

    # If h5 approach found nothing, try h3/h4 as fallback
    if not records:
        for heading in soup.find_all(["h3", "h4"]):
            name = heading.get_text(" ", strip=True)
            if is_junk_name(name):
                continue
            words = name.split()
            if len(words) < 2 or len(words) > 6:
                continue
            if re.search(r"\d", name):
                continue
            cap_count = sum(1 for w in words if w[0].isupper())
            if cap_count < len(words) * 0.5:
                continue

            key = slugify(name)
            if key in seen:
                continue
            seen.add(key)

            card = heading.parent
            for _ in range(3):
                if card and card.parent and card.parent.name not in ("body", "html", "[document]"):
                    if len(list(card.parent.children)) < 30:
                        card = card.parent
                    else:
                        break
                else:
                    break

            email = extract_email(card) if card else ""
            records.append(make_record(name, email, center_name, url))

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_json(records: list[dict], filename: str) -> None:
    """Write records to a JSON file in the centers data directory."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    print(f"  Wrote {path} ({len(records)} records)")


def main() -> int:
    # Fix Windows console encoding for Unicode names
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    print("=" * 60)
    print("Batch 3 Center Scraper: CEAH, Catt Center, CFSPH")
    print("=" * 60)

    total = 0

    # 1. CEAH
    print("\n[1/3] CEAH - Center for Excellence in the Arts and Humanities")
    print("  URL: https://ceah.iastate.edu/people")
    try:
        ceah = scrape_ceah()
        write_json(ceah, "ceah_faculty.json")
        print(f"  Found {len(ceah)} people")
        for r in ceah:
            print(f"    - {r['name']} ({r['email'] or 'no email'})")
        total += len(ceah)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)

    # 2. Catt Center
    print("\n[2/3] Catt Center - Carrie Chapman Catt Center for Women and Politics")
    print("  URL: https://cattcenter.iastate.edu/profiles/")
    try:
        catt = scrape_cattcenter()
        write_json(catt, "cattcenter_faculty.json")
        print(f"  Found {len(catt)} people")
        for r in catt:
            print(f"    - {r['name']} ({r['email'] or 'no email'})")
        total += len(catt)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)

    # 3. CFSPH
    print("\n[3/3] CFSPH - Center for Food Security and Public Health")
    print("  URL: https://www.cfsph.iastate.edu/about/our-team/")
    try:
        cfsph = scrape_cfsph()
        write_json(cfsph, "cfsph_faculty.json")
        print(f"  Found {len(cfsph)} people")
        for r in cfsph:
            print(f"    - {r['name']} ({r['email'] or 'no email'})")
        total += len(cfsph)
    except Exception as e:
        print(f"  ERROR: {e}", file=sys.stderr)

    print(f"\n{'=' * 60}")
    print(f"Total: {total} people across 3 centers")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
