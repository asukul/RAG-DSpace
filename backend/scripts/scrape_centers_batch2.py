"""
Batch 2 center scraper: Iowa Beef Center, Iowa Pork Industry Center, Plant Sciences Institute.

Each center has a different HTML structure:
  - IBC: static HTML tables with <td> cells containing name/email
  - IPIC: Drupal site with div.isu-horizontal-card and div.people-teaser-name
  - PSI: Custom Bootstrap with <blockquote> scholar entries and <h3> names

Output: backend/data/centers/{slug}_faculty.json

Run:
    python scripts/scrape_centers_batch2.py
"""
from __future__ import annotations

import gzip
import json
import re
import ssl
import sys
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup, Tag

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

TIMEOUT = 15


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def slugify(name: str) -> str:
    """Turn a name into a URL-safe slug id."""
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def fetch(url: str) -> str:
    """Fetch a URL, handling gzip. Returns HTML string or raises."""
    req = Request(url, headers=HEADERS)
    # Allow HTTPS without strict cert check for older sites
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
        data = resp.read()
        if resp.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return data.decode("utf-8", errors="replace")


def extract_email_from_tag(tag: Tag) -> str:
    """Find email in a tag's subtree via mailto: links or text patterns."""
    for a in tag.find_all("a", href=True):
        href = a["href"]
        if "mailto:" in href:
            email = href.replace("mailto:", "").strip().split("?")[0]
            if "@" in email:
                return email.lower()
    text = tag.get_text(" ", strip=True)
    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    return m.group(0).lower() if m else ""


def clean_name(raw: str) -> str:
    """Clean up a raw name string."""
    name = raw.strip()
    # Remove trailing degree suffixes
    name = re.sub(r",?\s*(Ph\.?D\.?|DVM|M\.?S\.?|D\.?V\.?M\.?)\.?\s*$", "", name, flags=re.I).strip()
    # Collapse internal whitespace
    name = re.sub(r"\s+", " ", name)
    return name


def make_record(
    name: str,
    email: str,
    center_name: str,
    source_url: str,
) -> dict:
    """Build a standard faculty record in the required schema."""
    return {
        "id": slugify(name),
        "name": name.strip(),
        "email": email.strip().lower() if email else "",
        "department": center_name,
        "center_affiliation": center_name,
        "source_url": source_url,
    }


# ---------------------------------------------------------------------------
# 1. Iowa Beef Center
# ---------------------------------------------------------------------------

def scrape_ibc() -> list[dict]:
    """
    Iowa Beef Center: static HTML tables.
    Each <td> holds one person: name (plain text or <a>), optional title lines,
    and a mailto: link.
    """
    url = "https://www.iowabeefcenter.org/whoweare.html"
    center = "Iowa Beef Center"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen: set[str] = set()

    for table in soup.find_all("table"):
        for td in table.find_all("td"):
            text = td.get_text(" ", strip=True)
            if not text or len(text) < 4:
                continue

            # Skip section header rows (long text about specialties)
            if re.search(r"\bSpecialist[s]?\b", text) and len(text) > 50:
                continue

            # Extract email first -- cells without email are not people
            email = extract_email_from_tag(td)
            if not email:
                continue

            # Extract name: prefer the first <a> with a profile link (non-mailto)
            name = ""
            profile_links = [
                a for a in td.find_all("a", href=True)
                if "mailto:" not in a["href"] and "tel:" not in a.get("href", "")
            ]
            if profile_links:
                name = profile_links[0].get_text(" ", strip=True)

            if not name:
                # Fallback: first line of text (before <br> or email)
                # Walk direct children to get the first text node
                for child in td.children:
                    if isinstance(child, str):
                        t = child.strip()
                        if t and "@" not in t and len(t) > 2:
                            name = t
                            break
                    elif hasattr(child, "name"):
                        if child.name == "a" and "mailto:" in child.get("href", ""):
                            continue
                        if child.name == "br":
                            continue
                        if child.name == "p":
                            # Name is inside <p>: get first text node
                            for pc in child.children:
                                if isinstance(pc, str):
                                    t = pc.strip()
                                    if t and "@" not in t and len(t) > 2:
                                        name = t
                                        break
                                elif hasattr(pc, "name") and pc.name == "a" and "mailto:" not in pc.get("href", ""):
                                    name = pc.get_text(" ", strip=True)
                                    break
                            if name:
                                break
                        else:
                            t = child.get_text(" ", strip=True)
                            if t and "@" not in t and len(t) > 2:
                                name = t
                                break

            if not name:
                continue

            name = clean_name(name)
            # Remove email residue from name
            name = re.sub(r"\s*[\w.+-]+@[\w.-]+\.\w+\s*", "", name).strip()
            # Remove trailing department text that slipped in
            name = re.sub(r"\s*Department of .*$", "", name).strip()

            if not name or len(name) < 3:
                continue

            slug = slugify(name)
            if slug in seen:
                continue
            seen.add(slug)

            records.append(make_record(name, email, center, url))

    return records


# ---------------------------------------------------------------------------
# 2. Iowa Pork Industry Center (IPIC)
# ---------------------------------------------------------------------------

def scrape_ipic() -> list[dict]:
    """
    IPIC Drupal site: div.isu-horizontal-card cards with
    div.people-teaser-name > h2 > a (name + link), mailto: links, position <li>.
    """
    url = "https://www.ipic.iastate.edu/people"
    center = "Iowa Pork Industry Center"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen: set[str] = set()

    cards = soup.find_all("div", class_="isu-horizontal-card")
    for card in cards:
        # Name from people-teaser-name div
        name_div = card.find("div", class_="people-teaser-name")
        if not name_div:
            continue
        heading = name_div.find(["h2", "h3", "h4"])
        if not heading:
            continue
        name = clean_name(heading.get_text(" ", strip=True))
        if not name or len(name) < 3:
            continue

        email = extract_email_from_tag(card)

        slug = slugify(name)
        if slug in seen:
            continue
        seen.add(slug)

        records.append(make_record(name, email, center, url))

    return records


# ---------------------------------------------------------------------------
# 3. Plant Sciences Institute (PSI)
# ---------------------------------------------------------------------------

def scrape_psi() -> list[dict]:
    """
    PSI custom Bootstrap theme: each scholar is in a <blockquote> with
    <h3> containing a link to their profile. Name has ", Ph.D." suffix.
    No mailto: links on this page.
    """
    url = "https://www.psi.iastate.edu/faculty-scholars/"
    center = "Plant Sciences Institute"
    html = fetch(url)
    soup = BeautifulSoup(html, "html.parser")

    records = []
    seen: set[str] = set()

    for bq in soup.find_all("blockquote"):
        h3 = bq.find("h3")
        if not h3:
            continue

        # Get name text from the h3 (skip the back-to-top arrow link)
        name_parts = []
        for a in h3.find_all("a", href=True):
            href = a["href"]
            if href == "#top" or href.startswith("#"):
                continue
            name_parts.append(a.get_text(" ", strip=True))
        if not name_parts:
            # Fallback to full h3 text
            name_parts = [h3.get_text(" ", strip=True)]

        raw_name = name_parts[0] if name_parts else ""
        name = clean_name(raw_name)
        if not name or len(name) < 3:
            continue

        # Email: check the whole blockquote for mailto: (unlikely but be safe)
        email = extract_email_from_tag(bq)

        slug = slugify(name)
        if slug in seen:
            continue
        seen.add(slug)

        records.append(make_record(name, email, center, url))

    return records


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def write_json(records: list[dict], filename: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out = DATA_DIR / filename
    with open(out, "w", encoding="utf-8") as f:
        json.dump(records, f, indent=2, ensure_ascii=False)
    return out


def main() -> int:
    scrapers = [
        ("Iowa Beef Center", "ibc_faculty.json", scrape_ibc),
        ("Iowa Pork Industry Center", "ipic_faculty.json", scrape_ipic),
        ("Plant Sciences Institute", "psi_faculty.json", scrape_psi),
    ]

    total = 0
    for label, filename, fn in scrapers:
        print(f"Scraping {label}...", flush=True)
        try:
            records = fn()
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
            continue
        out = write_json(records, filename)
        count = len(records)
        total += count
        print(f"  Found {count} people -> {out.name}")
        for r in records:
            print(f"    {r['name']:40s} {r['email']}")

    print(f"\nTotal: {total} people across 3 centers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
