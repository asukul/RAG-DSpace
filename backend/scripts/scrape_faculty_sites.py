#!/usr/bin/env python3
"""
Scrape the ISU Faculty Sites Directory at https://faculty.sites.iastate.edu/
Extract all faculty names and their personal site URLs.
Save results to data/faculty_sites_directory.json
"""

import json
import gzip
import urllib.request
from pathlib import Path
from bs4 import BeautifulSoup

URL = "https://faculty.sites.iastate.edu/"
OUT = Path(__file__).resolve().parent.parent / "data" / "faculty_sites_directory.json"


def fetch_page(url: str) -> str:
    """Fetch a URL, handling gzip responses."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ISU-Research-Search/1.0",
        "Accept-Encoding": "gzip",
    })
    resp = urllib.request.urlopen(req, timeout=30)
    data = resp.read()
    if resp.headers.get("Content-Encoding") == "gzip":
        data = gzip.decompress(data)
    return data.decode("utf-8")


def scrape_faculty_sites() -> list[dict]:
    """Parse the faculty sites directory and return a list of {name, faculty_site_url}."""
    html = fetch_page(URL)
    soup = BeautifulSoup(html, "html.parser")

    entries = []
    # Each faculty entry is inside <span class="field-content"><a href="...">Name</a></span>
    for span in soup.select("span.field-content"):
        a = span.find("a")
        if a and a.get("href", "").startswith("https://faculty.sites.iastate.edu/"):
            name = a.get_text(strip=True)
            url = a["href"]
            if name:
                entries.append({
                    "name": name,
                    "faculty_site_url": url,
                })

    return entries


def main():
    print(f"Fetching {URL} ...")
    entries = scrape_faculty_sites()
    print(f"Found {len(entries)} faculty site entries.")

    # Show a few samples
    for e in entries[:5]:
        print(f"  {e['name']:40s}  {e['faculty_site_url']}")
    if len(entries) > 5:
        print(f"  ... and {len(entries) - 5} more")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2, ensure_ascii=False)
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    main()
