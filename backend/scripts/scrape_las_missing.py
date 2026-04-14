"""Scrape ISU LAS faculty directories for departments that are missing / sparse
in the current `backend/data/las_faculty.json` dataset.

Reads the audit worklist in `tests/results/LAS_AUDIT.md` (as context) and walks
each departmental faculty directory, emitting one JSON row per faculty member
in the same shape as `las_faculty.json`.

Output:
  * backend/data/las_missing_faculty.json   — new faculty rows
  * tests/results/LAS_SCRAPE_REPORT.md      — per-department counts + errors

This script is idempotent — it can be re-run to refresh the file.

URL families handled:
  1.  <dept>.iastate.edu/profiles/?post_type=profiles&department=faculty
      ^ WP CMS used by engl, math, history, greenlee, language, psychology,
        pols, soc-cj, comst, intst, philrs (all route through wp.las.iastate.edu
        but expose themselves on their own subdomain). Cards use the
        `faculty-staff-card` CSS class. Pagination via `/profiles/page/N/`.
  2.  earth-atmosphere-climate.iastate.edu — same WP CMS, same selectors,
        but uses its own host.
  3.  wp.las.iastate.edu/<slug>/profiles/?department=faculty
        Same HTML, just uses the shared multisite host directly (used for
        philrs24, womensstudies23, comst-v2, etc.).
  4.  <dept>.iastate.edu/people/ (Drupal) — bcbio, ensci, datascience, ihs
        — one big page of `article.node--type-people` elements.
  5.  afam/amin/asam/scientificillustration/<misc>.iastate.edu/profiles/
        — same WP cards as family 1.
"""
from __future__ import annotations

import json
import os
import re
import socket
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

# -------------------------------------------------------------------------
# Paths
# -------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(SCRIPT_DIR)
REPO_ROOT = os.path.dirname(BACKEND_DIR)
OUT_JSON = os.path.join(BACKEND_DIR, "data", "las_missing_faculty.json")
REPORT_MD = os.path.join(REPO_ROOT, "tests", "results", "LAS_SCRAPE_REPORT.md")

# -------------------------------------------------------------------------
# HTTP configuration
# -------------------------------------------------------------------------
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "Connection": "keep-alive",
}
TIMEOUT = 15
MAX_WORKERS = 8
SLEEP_BETWEEN = 0.25  # seconds between profile fetches inside a worker
LIST_PAGE_RETRIES = 3

# Force IPv4 — some ISU hosts route to an IP that blocks inbound from this
# workstation over IPv6 and requests/urllib3 prefers IPv6 by default.
# This is the classic "happy eyeballs" mitigation.
_orig_getaddrinfo = socket.getaddrinfo


def _getaddrinfo_ipv4_only(host, port, family=0, type=0, proto=0, flags=0):
    return _orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)


socket.getaddrinfo = _getaddrinfo_ipv4_only


# -------------------------------------------------------------------------
# Department worklist — one entry per source to scrape.
#
# Every entry has:
#   * department    — canonical department name we want to store
#   * list_url      — first directory page URL
#   * style         — "wp_card" (faculty-staff-card) or "drupal_node" (article.node--type-people)
#   * source_url    — what we write into the `source_url` field for each row
#
# The order is the "high priority" sections first. Low-priority ROTC units
# are intentionally skipped per the audit.
# -------------------------------------------------------------------------
COLLEGE = "College of Liberal Arts and Sciences"

WORKLIST = [
    # ------- High priority: large LAS departments -------
    {
        "department": "Mathematics",
        "list_url": "https://math.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "English",
        "list_url": "https://engl.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "History",
        "list_url": "https://history.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Political Science",
        "list_url": "https://pols.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Sociology and Criminal Justice",
        "list_url": "https://soc-cj.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Psychology",
        "list_url": "https://psychology.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "World Languages and Cultures",
        "list_url": "https://language.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Philosophy and Religious Studies",
        # No faculty-only filter available; pulls everything (~27 total)
        "list_url": "https://philrs.iastate.edu/profiles/?post_type=profiles",
        "style": "wp_card",
    },
    {
        "department": "Greenlee School of Journalism and Communication",
        "list_url": "https://greenlee.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Earth, Atmosphere, and Climate",
        "list_url": "https://earth-atmosphere-climate.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    # ------- Medium priority: interdepartmental programs -------
    {
        "department": "Communication Studies",
        "list_url": "https://comst.las.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "International Studies",
        "list_url": "https://intst.las.iastate.edu/profiles/?post_type=profiles&search_letter=&s=&department=faculty",
        "style": "wp_card",
    },
    {
        "department": "Women's and Gender Studies",
        # No faculty-only filter available; includes core + affiliates
        "list_url": "https://womensstudies.las.iastate.edu/profiles/?post_type=profiles",
        "style": "wp_card",
    },
    {
        "department": "Bioinformatics and Computational Biology",
        "list_url": "https://bcbio.las.iastate.edu/people/",
        "style": "drupal_node",
    },
    {
        "department": "Environmental Science (ENSCI)",
        "list_url": "https://ensci.iastate.edu/people/",
        "style": "drupal_node",
    },
    {
        "department": "Data Science",
        "list_url": "https://datascience.iastate.edu/people/",
        "style": "drupal_node",
    },
    # Note on Linguistics: ling.las.iastate.edu/people/ has no real people list —
    # the department site now redirects users to the English directory. Its
    # faculty are already scraped via the English entry above, so we skip it
    # here to avoid duplicates.
]


# -------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------
def make_session() -> requests.Session:
    s = requests.Session()
    adapter = HTTPAdapter(pool_connections=MAX_WORKERS, pool_maxsize=MAX_WORKERS)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    s.headers.update(HEADERS)
    return s


def slugify(text: str) -> str:
    text = (text or "").strip().lower()
    text = re.sub(r"['\u2018\u2019]", "", text)  # drop apostrophes
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "unknown"


def clean_text(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"\s+", " ", s).strip()


def get(session: requests.Session, url: str, tries: int = LIST_PAGE_RETRIES) -> Optional[requests.Response]:
    last_err = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=TIMEOUT, allow_redirects=True)
            if r.status_code == 200:
                return r
            last_err = f"HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last_err = str(e)[:120]
        time.sleep(1 + i)
    print(f"    FAILED {url} ({last_err})", file=sys.stderr)
    return None


# -------------------------------------------------------------------------
# Directory listing parsers
# -------------------------------------------------------------------------
@dataclass
class RawCard:
    name: str = ""
    title: str = ""
    email: str = ""
    photo_url: str = ""
    profile_url: str = ""


def parse_wp_cards(html: str) -> list[RawCard]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawCard] = []
    for card in soup.find_all(class_="faculty-staff-card"):
        name_el = card.find(class_="faculty-staff-card__content-name")
        name = clean_text(name_el.get_text(" ", strip=True)) if name_el else ""
        if not name:
            continue

        title_el = card.find(class_="faculty-staff-feed-item__content-body")
        title = clean_text(title_el.get_text(" ", strip=True)) if title_el else ""

        profile_a = card.find("a", class_="iastate22-link-secondary")
        profile_url = profile_a.get("href", "").strip() if profile_a else ""

        email_a = card.find("a", href=lambda x: isinstance(x, str) and x.startswith("mailto:"))
        email = ""
        if email_a:
            email = email_a.get("href", "").replace("mailto:", "").strip()

        img = card.find("img", class_="faculty-staff-card__media-image") or card.find("img")
        photo_url = ""
        if img:
            photo_url = (img.get("src") or img.get("data-src") or "").strip()

        out.append(RawCard(name=name, title=title, email=email,
                           photo_url=photo_url, profile_url=profile_url))
    return out


def parse_drupal_nodes(html: str) -> list[RawCard]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[RawCard] = []
    articles = soup.find_all("article", class_="node--type-people")
    for a in articles:
        name_el = a.find(class_="people-teaser-name")
        name = clean_text(name_el.get_text(" ", strip=True)) if name_el else ""
        if not name:
            continue

        # Position list is an <ul>; join items with " | "
        pos_el = a.find(class_="isu-people_position-list")
        title = ""
        if pos_el:
            items = [clean_text(li.get_text(" ", strip=True)) for li in pos_el.find_all("li")]
            items = [t for t in items if t]
            title = " | ".join(items) if items else clean_text(pos_el.get_text(" ", strip=True))

        email = ""
        em_el = a.find(class_="isu-people_email")
        if em_el:
            em_a = em_el.find("a")
            if em_a:
                email = em_a.get("href", "").replace("mailto:", "").strip()
            else:
                email = clean_text(em_el.get_text(" ", strip=True))

        img = a.find("img")
        photo_url = ""
        if img:
            photo_url = (img.get("src") or "").strip()
            # Drupal sometimes emits relative URLs
            if photo_url and photo_url.startswith("/"):
                # We don't know the base host until the caller supplies it
                pass

        profile_url = ""
        if name_el:
            link = name_el.find("a")
            if link:
                profile_url = link.get("href", "").strip()
        if not profile_url:
            link = a.find("a", href=True)
            if link:
                profile_url = link.get("href", "").strip()

        out.append(RawCard(name=name, title=title, email=email,
                           photo_url=photo_url, profile_url=profile_url))
    return out


def detect_total_and_max_page(html: str) -> tuple[Optional[int], int]:
    """Return (total_results, max_page_number) from the listing HTML."""
    tot = None
    m = re.search(r"About (\d+)", html)
    if m:
        tot = int(m.group(1))
    pages = re.findall(r"/page/(\d+)/", html)
    max_page = max(int(x) for x in pages) if pages else 1
    return tot, max_page


def build_page_urls(list_url: str, max_page: int) -> list[str]:
    """Expand a directory list_url into one URL per page (1..max_page)."""
    if max_page <= 1:
        return [list_url]

    parsed = urlparse(list_url)
    # directory path is like /profiles/ — insert /page/N/ before the ?query.
    path = parsed.path
    if not path.endswith("/"):
        path += "/"
    query = f"?{parsed.query}" if parsed.query else ""
    urls = [list_url]
    for p in range(2, max_page + 1):
        page_path = f"{path}page/{p}/"
        urls.append(f"{parsed.scheme}://{parsed.netloc}{page_path}{query}")
    return urls


# -------------------------------------------------------------------------
# Profile page enrichment
# -------------------------------------------------------------------------
def extract_profile_detail(html: str) -> dict:
    """Pull research interests / bio out of a profile page.

    Works for both the WP profile template (headers like 'Research areas',
    'Research Interests', 'Bio') and the Drupal isu-people template
    (`isu-people_research-list` etc.).
    """
    soup = BeautifulSoup(html, "html.parser")
    interests: list[str] = []
    bio = ""

    # --- WP template: look for <h2>/<h3> labels ---
    labels = {
        "research areas": "research",
        "research interests": "research",
        "areas of expertise": "research",
        "interests": "research",
        "expertise": "research",
        "research and expertise": "research",
        "bio": "bio",
        "biography": "bio",
        "about": "bio",
    }
    for h in soup.find_all(["h2", "h3"]):
        label = clean_text(h.get_text(" ", strip=True)).lower()
        if label not in labels:
            continue
        kind = labels[label]
        # Collect sibling content until the next header
        parts: list[str] = []
        list_items: list[str] = []
        for sib in h.find_next_siblings():
            if sib.name in ("h2", "h3"):
                break
            if sib.name in ("ul", "ol"):
                for li in sib.find_all("li"):
                    t = clean_text(li.get_text(" ", strip=True))
                    if t:
                        list_items.append(t)
            else:
                t = clean_text(sib.get_text(" ", strip=True))
                if t:
                    parts.append(t)
        if kind == "research":
            if list_items:
                interests.extend(list_items)
            elif parts:
                # Split a prose blob by commas / semicolons / periods
                blob = " ".join(parts)
                pieces = re.split(r"[;•·]|\s*,\s*|\s*\n+\s*", blob)
                interests.extend([p.strip(" .") for p in pieces if len(p.strip()) > 2])
        elif kind == "bio" and not bio:
            if parts:
                bio = " ".join(parts)
            elif list_items:
                bio = " | ".join(list_items)

    # --- Drupal template: isu-people_research-list / expertise-list ---
    for cls in ("isu-people_research-list", "isu-people_expertise-list"):
        el = soup.find(class_=cls)
        if el:
            lis = el.find_all("li")
            if lis:
                for li in lis:
                    t = clean_text(li.get_text(" ", strip=True))
                    if t and t not in interests:
                        interests.append(t)
            else:
                t = clean_text(el.get_text(" ", strip=True))
                if t and t not in interests:
                    interests.append(t)

    # Drupal bio sketch
    if not bio:
        bio_el = soup.find(class_="isu-people_bio-sketch")
        if bio_el:
            bio = clean_text(bio_el.get_text(" ", strip=True))

    # Deduplicate while preserving order
    seen = set()
    deduped: list[str] = []
    for it in interests:
        key = it.lower()
        if key and key not in seen and len(it) < 300:
            seen.add(key)
            deduped.append(it)
    return {"research_interests": deduped, "bio": bio}


# -------------------------------------------------------------------------
# Main scrape loop
# -------------------------------------------------------------------------
@dataclass
class FetchResult:
    department: str
    source_url: str
    rows: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    total_reported: Optional[int] = None
    pages_scanned: int = 0


def scrape_department(entry: dict, session: requests.Session, global_slug_counts: dict) -> FetchResult:
    department = entry["department"]
    list_url = entry["list_url"]
    style = entry["style"]
    print(f"\n=== {department} ===")
    print(f"list: {list_url}")
    result = FetchResult(department=department, source_url=list_url)

    # 1. Fetch the first directory page to determine total + max_page
    r = get(session, list_url)
    if r is None:
        result.errors.append(f"Failed to GET first page: {list_url}")
        return result

    html = r.text
    total, max_page = detect_total_and_max_page(html)
    result.total_reported = total
    print(f"reported total: {total}, pagination: {max_page} page(s)")

    # 2. For WP-style pagination, walk each page. For drupal_node, single-page.
    cards: list[RawCard] = []
    if style == "wp_card":
        page_urls = build_page_urls(list_url, max_page)
        for i, url in enumerate(page_urls, start=1):
            if i == 1:
                page_html = html  # reuse fetched page
            else:
                pr = get(session, url)
                if pr is None:
                    result.errors.append(f"Failed page {i}: {url}")
                    continue
                page_html = pr.text
            page_cards = parse_wp_cards(page_html)
            cards.extend(page_cards)
            result.pages_scanned += 1
            print(f"  page {i}: {len(page_cards)} cards (running total {len(cards)})")
            time.sleep(0.15)
    elif style == "drupal_node":
        cards = parse_drupal_nodes(html)
        result.pages_scanned = 1
        print(f"  single page: {len(cards)} cards")
    else:
        result.errors.append(f"Unknown style: {style}")
        return result

    if not cards:
        result.errors.append("No cards parsed from listing")
        return result

    # 3. Fan out profile-page fetches for enrichment
    def enrich(card: RawCard) -> dict:
        detail = {}
        if card.profile_url:
            try:
                pr = session.get(card.profile_url, timeout=TIMEOUT, allow_redirects=True)
                if pr.status_code == 200:
                    detail = extract_profile_detail(pr.text)
            except Exception as e:  # noqa: BLE001
                detail = {"_error": str(e)[:120]}
            time.sleep(SLEEP_BETWEEN)
        return detail

    enriched: list[tuple[RawCard, dict]] = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        future_map = {pool.submit(enrich, c): c for c in cards}
        for fut in as_completed(future_map):
            c = future_map[fut]
            try:
                detail = fut.result()
            except Exception as e:  # noqa: BLE001
                detail = {"_error": str(e)[:120]}
            enriched.append((c, detail))

    # 4. Build output rows (stable IDs, dedupe on slug collisions across all
    # departments — cross-appointments still get a unique row with a -2 suffix)
    for card, detail in enriched:
        base = slugify(card.name)
        global_slug_counts[base] = global_slug_counts.get(base, 0) + 1
        row_id = base if global_slug_counts[base] == 1 else f"{base}-{global_slug_counts[base]}"

        photo_url = card.photo_url
        # Drupal absolute-ify
        if photo_url and photo_url.startswith("/"):
            host = urlparse(list_url)
            photo_url = f"{host.scheme}://{host.netloc}{photo_url}"

        row = {
            "id": row_id,
            "name": card.name,
            "title": card.title,
            "department": department,
            "college": COLLEGE,
            "email": card.email,
            "profile_url": card.profile_url,
            "photo_url": photo_url,
            "research_interests": detail.get("research_interests", []) or [],
            "courses_taught": [],
            "is_teaching_faculty": bool(re.search(r"teach", card.title or "", re.IGNORECASE)),
            "source_url": list_url,
        }
        # Tack on bio when present (non-schema extension; downstream ingestion
        # already tolerates extra keys in the other faculty files).
        bio = detail.get("bio", "")
        if bio:
            row["bio"] = bio
        if detail.get("_error"):
            row["_profile_error"] = detail["_error"]

        result.rows.append(row)

    print(f"extracted {len(result.rows)} rows")
    return result


def main() -> int:
    session = make_session()
    all_rows: list[dict] = []
    reports: list[FetchResult] = []
    global_slug_counts: dict[str, int] = {}

    for entry in WORKLIST:
        try:
            r = scrape_department(entry, session, global_slug_counts)
        except Exception as e:  # noqa: BLE001
            tb = traceback.format_exc().splitlines()[-1]
            r = FetchResult(
                department=entry["department"],
                source_url=entry["list_url"],
                errors=[f"Exception: {tb}"],
            )
            print(f"EXC: {e}", file=sys.stderr)
        reports.append(r)
        all_rows.extend(r.rows)

        # Persist after each department so interruptions don't lose work
        os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
        with open(OUT_JSON, "w", encoding="utf-8") as fp:
            json.dump(all_rows, fp, ensure_ascii=False, indent=2)

    # Compute enrichment stats
    with_interests = sum(1 for r in all_rows if r.get("research_interests"))
    with_bio = sum(1 for r in all_rows if r.get("bio"))

    # Write summary report
    os.makedirs(os.path.dirname(REPORT_MD), exist_ok=True)
    with open(REPORT_MD, "w", encoding="utf-8") as fp:
        fp.write("# LAS Missing Faculty — Scrape Report\n\n")
        fp.write(f"- Output: `backend/data/las_missing_faculty.json`\n")
        fp.write(f"- Script: `backend/scripts/scrape_las_missing.py`\n")
        fp.write(f"- Total rows scraped: **{len(all_rows)}**\n")
        fp.write(f"- Rows with research interests: **{with_interests}**\n")
        fp.write(f"- Rows with bio text: **{with_bio}**\n\n")

        fp.write("## Per-department results\n\n")
        fp.write("| Department | Reported total | Scraped | Pages | Errors |\n")
        fp.write("|---|---:|---:|---:|---|\n")
        for r in reports:
            err_txt = "; ".join(r.errors) if r.errors else ""
            err_txt = err_txt.replace("|", "\\|")[:180]
            tot = "?" if r.total_reported is None else str(r.total_reported)
            fp.write(f"| {r.department} | {tot} | {len(r.rows)} | {r.pages_scanned} | {err_txt} |\n")

        fp.write("\n## Source URLs\n\n")
        for r in reports:
            fp.write(f"- **{r.department}** — {r.source_url}\n")

        fp.write("\n## Notes\n\n")
        fp.write(
            "- Cross-appointments (same faculty listed under two programs, e.g. "
            "English + Women's and Gender Studies) are preserved as separate "
            "rows with distinct `id` values (`-2`, `-3` suffix) so both "
            "departments retain the entry. Names/profile URLs will match.\n"
        )
        fp.write(
            "- Research interests are pulled from explicit `Research`, "
            "`Expertise`, or `Interests` sections on the profile page when "
            "present. Many departments (History, Sociology, Political Science, "
            "Greenlee) embed that information inside the `Bio` block, so those "
            "rows will have a `bio` field instead.\n"
        )
        fp.write(
            "- Some ISU LAS hosts resolve to the IP `129.186.90.87` (shared "
            "site infrastructure) which may be blocked by local firewall "
            "routing — specifically bcbio, ensci, datascience, integratedhealthsciences. "
            "Re-run this script from a different network to pick up those "
            "departments when that IP becomes reachable.\n"
        )
        fp.write(
            "- Linguistics (ling.las.iastate.edu) redirects its 'faculty' link "
            "to the English directory — its faculty are already covered under "
            "the English entry, so we do not scrape it separately.\n"
        )
        fp.write(
            "- ROTC units (Air Force / Army / Navy) were intentionally skipped "
            "per the audit — they have ≤6 cadre staff each and no structured "
            "directory HTML, so they are handled manually.\n"
        )

    print("\n" + "=" * 60)
    print(f"TOTAL: {len(all_rows)} faculty rows written to {OUT_JSON}")
    print(f"Report: {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
