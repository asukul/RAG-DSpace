"""
Scrape CIRAS (Center for Industrial Research and Service) staff directory.

CIRAS provides applied research, education and technical assistance to Iowa
industry. Their specialists are typically NOT in the College of Engineering
faculty list because they're staff/researchers of a center, not professors.

Strategy
--------
1. GET the directory page https://www.ciras.iastate.edu/staff-directory/
2. Extract all `/staff-directory/person/?id=<netid>` links (~90 entries)
3. For each profile, GET the page and pull from .Rtable-cell--foot:
     h1   = name
     p    = title (e.g., "Strategic Advisor", "Project Manager")
     span = phone, email, address (line 1), city/state/zip
4. Also extract Education / Experience / bio paragraphs from the h4 sections.
5. Photo URL is at /wp-content/themes/iastate-theme-child-ciras/img/staff/{netid}.jpg

Output
------
Writes `backend/data/ciras_faculty.json` in the standard schema with
department="Center for Industrial Research and Service" and
college="Center for Industrial Research and Service".
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
OUT_PATH = BASE / "data" / "ciras_faculty.json"
REPORT_PATH = BASE.parent / "tests" / "results" / "CIRAS_SCRAPE_REPORT.md"

DIR_URL = "https://www.ciras.iastate.edu/staff-directory/"
SITE = "https://www.ciras.iastate.edu"
COLLEGE = "Center for Industrial Research and Service"
DEPT_DEFAULT = "Center for Industrial Research and Service"

POLITE_DELAY = 0.5

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^\w\s-]", "", (name or "").lower(), flags=re.UNICODE)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s or "unknown"


def normalize_url(href: str) -> str:
    if not href:
        return ""
    return urljoin(SITE + "/", href)


def collect_profile_links(html: str) -> list[tuple[str, str]]:
    """Returns [(netid, name)] for every staff profile link on the page."""
    soup = BeautifulSoup(html, "html.parser")
    seen: dict[str, str] = {}
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.search(r"/staff-directory/person/\?id=([^&\s]+)", href)
        if not m:
            continue
        netid = m.group(1).strip()
        name = a.get_text(" ", strip=True)
        if not netid or netid in seen:
            continue
        if not name:
            continue
        seen[netid] = name
    return list(seen.items())


def parse_profile(html: str, netid: str) -> dict[str, Any]:
    """Pull the structured fields out of an individual CIRAS person page."""
    soup = BeautifulSoup(html, "html.parser")

    # The contact card lives in a div.Rtable-cell.Rtable-cell--foot
    foot = soup.select_one(".Rtable-cell--foot")
    if not foot:
        return {}

    h1 = foot.find("h1")
    name = h1.get_text(" ", strip=True) if h1 else ""

    # Title: first <p> in foot
    title_el = foot.find("p")
    title = title_el.get_text(" ", strip=True) if title_el else ""

    # Spans contain phone / email / address line / city-state-zip
    spans = foot.find_all("span")
    phone = ""
    email = ""
    address_lines: list[str] = []
    for sp in spans:
        text = sp.get_text(" ", strip=True)
        if not text:
            continue
        # Phone like 515-419-2163
        if re.match(r"^\d{3}-\d{3}-\d{4}$", text):
            phone = text
        elif "@" in text and "iastate.edu" in text.lower():
            email = text.lower()
        else:
            address_lines.append(text)

    # Education + Experience sections
    education = ""
    experience = ""
    for h4 in soup.find_all("h4"):
        label = h4.get_text(strip=True).lower()
        # Walk siblings until we hit another h4 or h2/h3
        chunks: list[str] = []
        sib = h4.find_next_sibling()
        while sib and sib.name not in ("h4", "h3", "h2"):
            text = sib.get_text(" ", strip=True)
            if text:
                chunks.append(text)
            sib = sib.find_next_sibling()
        joined = " ".join(chunks)
        if label.startswith("educ"):
            education = joined[:1000]
        elif label.startswith("exper"):
            experience = joined[:2000]

    # Photo
    photo_url = ""
    img = soup.find("img", src=lambda s: bool(s) and "staff" in s.lower())
    if img:
        photo_url = normalize_url(img.get("src", ""))

    return {
        "name": name,
        "title": title,
        "email": email,
        "phone": phone,
        "address": " ".join(address_lines)[:200],
        "photo_url": photo_url,
        "education": education,
        "experience": experience,
    }


def title_is_excluded(title: str) -> bool:
    """CIRAS staff with admin-only titles we don't want to keep as faculty/researcher."""
    t = (title or "").lower()
    if not t:
        return True
    # Keep specialists, advisors, managers, engineers, scientists, directors
    # Skip pure administrative/intern roles
    skip = (
        "intern", "administrative assistant", "office manager",
        "receptionist",
    )
    return any(s in t for s in skip)


def normalize_record(netid: str, profile: dict[str, Any]) -> dict[str, Any] | None:
    name = profile.get("name") or ""
    title = profile.get("title") or ""
    if not name or title_is_excluded(title):
        return None

    profile_url = f"{SITE}/staff-directory/person/?id={netid}"
    bio_chunks = [profile.get("experience") or "", profile.get("education") or ""]
    bio = " | ".join(c for c in bio_chunks if c).strip()
    return {
        "id": slugify(name),
        "name": name,
        "title": title,
        "department": DEPT_DEFAULT,
        "college": COLLEGE,
        "email": profile.get("email") or None,
        "profile_url": profile_url,
        "photo_url": profile.get("photo_url") or None,
        "research_interests": [],  # CIRAS profiles don't list research interests
        "courses_taught": [],
        "is_teaching_faculty": False,
        "source_url": profile_url,
        "bio": bio[:2000],
    }


def main() -> int:
    session = requests.Session(impersonate="chrome124")
    started = datetime.now(timezone.utc).isoformat()

    print(f"== CIRAS scrape == {started}")
    print(f"Fetching {DIR_URL}")
    r = session.get(DIR_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()

    profile_links = collect_profile_links(r.text)
    print(f"Found {len(profile_links)} unique profile links")

    if not profile_links:
        print("ERROR: no profile links found", file=sys.stderr)
        return 2

    enriched: list[dict[str, Any]] = []
    skipped = 0
    fetch_errors = 0
    for i, (netid, list_name) in enumerate(profile_links, 1):
        url = f"{SITE}/staff-directory/person/?id={netid}"
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            if r.status_code != 200:
                print(f"  [{i}/{len(profile_links)}] {list_name} HTTP {r.status_code}")
                fetch_errors += 1
                time.sleep(POLITE_DELAY)
                continue
        except Exception as e:
            print(f"  [{i}/{len(profile_links)}] {list_name} ERROR: {e}")
            fetch_errors += 1
            time.sleep(POLITE_DELAY)
            continue

        profile = parse_profile(r.text, netid)
        rec = normalize_record(netid, profile)
        if rec is None:
            skipped += 1
        else:
            enriched.append(rec)
        if i % 10 == 0 or i == len(profile_links):
            print(f"  [{i}/{len(profile_links)}] kept={len(enriched)} skipped={skipped} errs={fetch_errors}")
        time.sleep(POLITE_DELAY)

    enriched.sort(key=lambda r: r["name"].lower())

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(enriched, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nWrote {len(enriched)} CIRAS staff -> {OUT_PATH}")

    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    title_counts: dict[str, int] = {}
    for r in enriched:
        title_counts[r["title"]] = title_counts.get(r["title"], 0) + 1
    lines = [
        "# CIRAS Scrape Report",
        "",
        f"Started:  {started}",
        f"Finished: {finished}",
        "",
        "## Source",
        "",
        f"- Directory: {DIR_URL}",
        f"- Per-profile: {SITE}/staff-directory/person/?id={{netid}}",
        "",
        "## Counts",
        "",
        f"- Profile links discovered: {len(profile_links)}",
        f"- Kept (faculty/researcher): {len(enriched)}",
        f"- Skipped (admin/intern):    {skipped}",
        f"- Fetch errors:              {fetch_errors}",
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
        f"## Output",
        "",
        f"- `{OUT_PATH}`",
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
