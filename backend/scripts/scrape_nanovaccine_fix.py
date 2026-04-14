"""
Re-scrape Nanovaccine Institute people directory using the WordPress REST API.

The public /members/ page is JS-rendered and only yields ~20 people via
normal scraping. The WP REST API at /wp-json/wp/v2/people returns all
entries with proper pagination.

Run:
    python scripts/scrape_nanovaccine_fix.py
"""
from __future__ import annotations

import json
import re
import time
from html import unescape
from pathlib import Path

import requests

BASE = Path(__file__).resolve().parent.parent
OUT_FILE = BASE / "data" / "centers" / "nanovaccine_faculty.json"

API_URL = "https://nanovaccine.iastate.edu/wp-json/wp/v2/people"
PER_PAGE = 100
SOURCE_URL = "https://nanovaccine.iastate.edu/members/"

HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
}

# Regex to strip HTML tags
TAG_RE = re.compile(r"<[^>]+>")
# Regex to find email addresses
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")


def strip_html(html: str) -> str:
    """Remove HTML tags, decode entities, normalise whitespace."""
    text = unescape(TAG_RE.sub("", html)).strip()
    # Replace non-breaking spaces and other Unicode spaces with regular space
    text = re.sub(r"[\xa0\u00a0\u2011\u202f\u2009]", " ", text)
    # Collapse multiple spaces
    text = re.sub(r"  +", " ", text)
    return text


def make_slug(name: str) -> str:
    """Turn a name into a kebab-case slug."""
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", name.lower())
    s = re.sub(r"\s+", "-", s.strip())
    return s


def extract_email(content_html: str) -> str:
    """Try to find an email address in the rendered content HTML."""
    if not content_html:
        return ""
    # Look in mailto links first
    mailto = re.search(r'href="mailto:([^"]+)"', content_html)
    if mailto:
        return mailto.group(1).strip()
    # Fall back to regex on plain text
    plain = strip_html(content_html)
    match = EMAIL_RE.search(plain)
    return match.group(0) if match else ""


def extract_department(content_html: str) -> str:
    """Try to extract a department from the bio content."""
    if not content_html:
        return "Nanovaccine Institute"
    plain = strip_html(content_html)
    # Common patterns: "Department of X" or "Dept. of X"
    dept_match = re.search(r"(?:Department|Dept\.?)\s+of\s+([A-Z][A-Za-z\s&,]+)", plain)
    if dept_match:
        return dept_match.group(0).strip().rstrip(",.")
    return "Nanovaccine Institute"


def extract_profile_url(entry: dict) -> str:
    """Get the profile URL from the WP API entry."""
    return entry.get("link", "")


def fetch_all_people() -> list[dict]:
    """Fetch all people from the WP REST API with pagination."""
    all_entries = []
    page = 1

    while True:
        params = {"per_page": PER_PAGE, "page": page}
        print(f"  Fetching page {page} ...")
        resp = requests.get(API_URL, headers=HEADERS, params=params, timeout=20)

        if resp.status_code == 400:
            # WP returns 400 when page exceeds total pages
            break
        resp.raise_for_status()

        entries = resp.json()
        if not entries:
            break

        all_entries.extend(entries)
        print(f"    Got {len(entries)} entries (total so far: {len(all_entries)})")

        # Check total pages from response headers
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        if page >= total_pages:
            break

        page += 1
        time.sleep(0.5)  # polite delay

    return all_entries


def process_entry(entry: dict) -> dict:
    """Convert a WP REST API people entry to our standard schema."""
    # Name from title.rendered (strip HTML tags like <span>, etc.)
    raw_name = strip_html(entry.get("title", {}).get("rendered", ""))

    # Content for email/department extraction
    content_html = entry.get("content", {}).get("rendered", "")

    email = extract_email(content_html)
    department = extract_department(content_html)
    profile_url = extract_profile_url(entry)

    # Check ACF fields if present
    acf = entry.get("acf", {})
    if acf and isinstance(acf, dict):
        if not email and acf.get("email"):
            email = acf["email"]
        if acf.get("department"):
            department = acf["department"]

    slug = entry.get("slug", make_slug(raw_name))

    return {
        "id": slug,
        "name": raw_name,
        "title": "",
        "department": department,
        "college": "Nanovaccine Institute",
        "email": email,
        "profile_url": profile_url,
        "photo_url": "",
        "research_interests": [],
        "courses_taught": [],
        "is_teaching_faculty": False,
        "source_url": SOURCE_URL,
        "center_affiliation": "Nanovaccine Institute",
    }


def main():
    print("Scraping Nanovaccine Institute via WP REST API ...")
    raw_entries = fetch_all_people()
    print(f"\nFetched {len(raw_entries)} raw entries from API.")

    people = []
    seen_ids = set()
    for entry in raw_entries:
        person = process_entry(entry)
        # Deduplicate by slug
        if person["id"] in seen_ids:
            continue
        seen_ids.add(person["id"])
        people.append(person)

    # Sort by name
    people.sort(key=lambda p: p["name"].lower())

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(people, f, indent=2, ensure_ascii=False)

    emails_found = sum(1 for p in people if p["email"])
    print(f"\nWrote {len(people)} people to {OUT_FILE}")
    print(f"  Emails found: {emails_found}")
    print(f"  Sample names: {[p['name'] for p in people[:5]]}")


if __name__ == "__main__":
    main()
