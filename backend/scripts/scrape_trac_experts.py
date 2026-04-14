"""
Scrape TrAC faculty experts from https://trac-ai.iastate.edu/about/faculty-experts/
Uses BeautifulSoup for robust HTML parsing.
"""
import gzip
import json
import re
import sys
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
OUT = BACKEND / "data" / "centers" / "trac_experts_faculty.json"

URL = "https://trac-ai.iastate.edu/about/faculty-experts/"


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "ISU-Research-Bot/1.0",
        "Accept-Encoding": "gzip",
    })
    resp = urllib.request.urlopen(req, timeout=30)
    raw = resp.read()
    if raw[:2] == b'\x1f\x8b':
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", errors="replace")


def main():
    print(f"Fetching {URL}")
    html = fetch(URL)
    soup = BeautifulSoup(html, "html.parser")

    # Find all mailto links
    mailto_links = soup.find_all("a", href=re.compile(r"^mailto:"))
    print(f"  Found {len(mailto_links)} mailto links")

    faculty = []
    seen = set()

    for link in mailto_links:
        email = link["href"].replace("mailto:", "").strip().lower()
        if not email or email in seen:
            continue

        # Walk up to find the parent container that holds both name and email
        # Usually the name is in a preceding sibling, parent text, or heading
        name = None

        # Strategy 1: Look at parent and preceding siblings
        parent = link.parent
        if parent:
            # Get all text in parent before the mailto link
            for child in parent.children:
                if child == link:
                    break
                text = child.string or (child.get_text() if hasattr(child, 'get_text') else str(child))
                text = text.strip()
                if text and 2 <= len(text.split()) <= 6 and "@" not in text:
                    name = text

        # Strategy 2: Look at previous siblings of parent
        if not name and parent:
            for sib in parent.previous_siblings:
                if hasattr(sib, 'get_text'):
                    text = sib.get_text().strip()
                elif isinstance(sib, str):
                    text = sib.strip()
                else:
                    continue
                if text and 2 <= len(text.split()) <= 6 and "@" not in text and len(text) < 60:
                    name = text
                    break

        # Strategy 3: Look at grandparent's headings or strong tags
        if not name and parent and parent.parent:
            gp = parent.parent
            for tag in gp.find_all(["h2", "h3", "h4", "strong", "b"]):
                text = tag.get_text().strip()
                if text and 2 <= len(text.split()) <= 6 and "@" not in text:
                    name = text
                    break

        # Strategy 4: Look at the container — many WordPress themes use
        # card/profile divs with the name in a heading
        if not name:
            container = link.find_parent(["div", "li", "article", "td"])
            if container:
                # Find first heading or strong in this container
                heading = container.find(["h2", "h3", "h4", "h5", "strong", "b", "p"])
                if heading:
                    text = heading.get_text().strip()
                    if 2 <= len(text.split()) <= 6 and "@" not in text:
                        name = text

        if name:
            name = re.sub(r'\s+', ' ', name).strip()
            seen.add(email)
            faculty.append({
                "id": slug(name),
                "name": name,
                "email": email,
                "department": "Translational AI Research and Education Center",
                "center_affiliation": "Translational AI Research and Education Center",
                "source_url": URL,
            })

    # If we got very few, try a different approach: extract all text blocks
    # and pair names with emails by proximity
    if len(faculty) < 20:
        print(f"  Only {len(faculty)} from mailto parsing, trying text proximity...")
        # Strip HTML, split into lines
        text = soup.get_text(separator="\n")
        lines = [l.strip() for l in text.split("\n") if l.strip()]

        seen2 = set(seen)
        for i, line in enumerate(lines):
            if "@iastate.edu" in line.lower() and line.lower().strip() not in seen2:
                email = line.strip().lower()
                # Clean email - might have extra text
                em_match = re.search(r'[a-z0-9._%+-]+@iastate\.edu', email)
                if not em_match:
                    continue
                email = em_match.group(0)
                if email in seen2:
                    continue

                # Look backwards for name
                name = None
                for j in range(max(0, i - 5), i):
                    candidate = lines[j]
                    words = candidate.split()
                    if (2 <= len(words) <= 6
                            and "@" not in candidate
                            and len(candidate) < 60
                            and not candidate.startswith("http")
                            and not any(c in candidate.lower() for c in ["©", "iowa state", "menu", "search", "skip"])
                            and any(w[0].isupper() for w in words if w)):
                        name = candidate
                if name:
                    seen2.add(email)
                    name = re.sub(r'\s+', ' ', name).strip()
                    faculty.append({
                        "id": slug(name),
                        "name": name,
                        "email": email,
                        "department": "Translational AI Research and Education Center",
                        "center_affiliation": "Translational AI Research and Education Center",
                        "source_url": URL,
                    })

    # Deduplicate by email
    by_email = {}
    for f in faculty:
        by_email[f["email"]] = f
    faculty = list(by_email.values())

    print(f"  Total unique faculty: {len(faculty)}")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(faculty, f, indent=2, ensure_ascii=False)
    print(f"  Written to {OUT}")

    for fac in faculty[:15]:
        print(f"    {fac['name']:40s} {fac['email']}")
    if len(faculty) > 15:
        print(f"    ... and {len(faculty) - 15} more")

    return 0


if __name__ == "__main__":
    sys.exit(main())
