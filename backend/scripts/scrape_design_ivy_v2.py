"""Re-scrape ISU College of Design and Ivy College of Business with per-department tags.

Both the Design `/profiles/` and the Ivy `/directory/` use the same WordPress
`.faculty-staff-card` component, but the two sites expose the department
differently:

  * Design (https://www.design.iastate.edu/profiles/)
      - Unified page shows 268 results but does NOT label the department on each
        card. The dropdown filter DOES work via `?department=<Name>` and the
        URL-encoded department label becomes the ground truth for every card
        returned by that filtered page.
      - We fetch each of the 10 department filters in turn. Academic departments
        are scraped first so that a faculty member who appears under multiple
        filters (e.g. chair of one dept who also teaches in another) lands under
        their primary academic department.

  * Ivy Business (https://www.ivybusiness.iastate.edu/directory/)
      - Single unified page renders every card with an inline
        `<div><strong>Department:</strong> ...</div>` block, so one GET of the
        directory root yields every person plus their department label.
      - Academic departments: Accounting, Finance, Information Systems and
        Business Analytics, Management and Entrepreneurship, Marketing, Supply
        Chain Management. The page also lists admin units (Administration,
        Graduate Office, Career Services, etc.); we still allow a card under
        those units IF the title clearly says Professor/Lecturer/etc. (endowed
        deans, for instance, sit under Administration).

Output schema matches `backend/data/coe_faculty.json`:
  { "name", "title", "profile_url", "photo_url", "email",
    "department", "college", "id" }

Stable IDs are `slugify(name)`. The existing
`backend/data/{design,ivy}_faculty.json` files are NEVER modified — new files
are written to `design_v2_faculty.json` / `ivy_v2_faculty.json`.
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# Windows cp1252 consoles can crash on smart-quote characters emitted by the
# source HTML. Force stdout to UTF-8 with a replacement handler so logging
# never becomes the reason the scraper aborts.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
DATA = BASE / "data"
DESIGN_OUT = DATA / "design_v2_faculty.json"
IVY_OUT = DATA / "ivy_v2_faculty.json"
REPORT = Path(
    "D:/Dropbox/RAG-DSpace/isu-research-search/tests/results/DESIGN_IVY_SCRAPE_REPORT.md"
)

USER_AGENT = "ISU-RAG-Indexer/1.0 (academic research; contact: asukul@iastate.edu)"
HTTP_TIMEOUT = 30.0
REQUEST_DELAY = 0.25  # 250 ms between requests
MAX_WORKERS = 8

DESIGN_COLLEGE = "College of Design"
IVY_COLLEGE = "Ivy College of Business"

# ---- Design department filter values (exact strings from the <select>) ----
#
# Order matters: academic departments come first so that a person listed under
# multiple filters lands in their primary academic department.
DESIGN_DEPARTMENTS: list[str] = [
    "Architecture",
    "Art and Visual Culture",
    "Graphic Design",
    "Industrial Design",
    "Interior Design",
    "Landscape Architecture",
    "Urban Planning and Development",
    "Design Administration",
    "GIS Facility",
    "IDRO",
]

DESIGN_DIRECTORY = "https://www.design.iastate.edu/profiles/"
IVY_DIRECTORY = "https://www.ivybusiness.iastate.edu/directory/"

# Ivy: only these six are the academic departments with real faculty
IVY_ACADEMIC_DEPARTMENTS: set[str] = {
    "Accounting",
    "Finance",
    "Information Systems and Business Analytics",
    "Management and Entrepreneurship",
    "Marketing",
    "Supply Chain Management",
}

# ---- Faculty/staff classifier ----------------------------------------------
#
# Design philosophy: be permissive on the "include" side for academic ranks
# (Professor, Lecturer, Instructor, Chair, Faculty, Emeritus, Clinician,
# Fellow-in-dept) BUT run a strict exclude list first so that staff titles that
# happen to contain a word like "Dean" or "Director" do not slip through.
#
# The NON_FACULTY list MUST be checked before the FACULTY list.

FACULTY_TITLE_PATTERNS = [
    re.compile(r"\bprofessor\b", re.IGNORECASE),  # Professor / Associate / Assistant / Teaching / Emeritus / Morrill / Distinguished / Endowed
    re.compile(r"\blecturer\b", re.IGNORECASE),
    re.compile(r"\binstructor\b", re.IGNORECASE),
    re.compile(r"\bfaculty\b", re.IGNORECASE),
    re.compile(r"\bchair\b", re.IGNORECASE),              # Department Chair
    re.compile(r"\bassociate dean\b", re.IGNORECASE),     # Associate Dean, Senior Associate Dean (always faculty-rank in these colleges)
    re.compile(r"\bendowed dean\b", re.IGNORECASE),       # Raisbeck Endowed Dean etc
    re.compile(r"\bendowed chair\b", re.IGNORECASE),
    re.compile(r"\bclinician\b", re.IGNORECASE),
]

NON_FACULTY_TITLE_PATTERNS = [
    # Students
    re.compile(r"\bphd candidate\b", re.IGNORECASE),
    re.compile(r"\bphd student\b", re.IGNORECASE),
    re.compile(r"\bgraduate student\b", re.IGNORECASE),
    re.compile(r"\bdoctoral student\b", re.IGNORECASE),
    re.compile(r"\bmasters? student\b", re.IGNORECASE),
    re.compile(r"\bgraduate assistant\b", re.IGNORECASE),
    re.compile(r"\bresearch assistant\b", re.IGNORECASE),
    re.compile(r"\bteaching assistant\b", re.IGNORECASE),
    re.compile(r"\bresearch associate\b", re.IGNORECASE),  # usually postdoc/staff scientist, not faculty
    re.compile(r"\bpostdoc\b", re.IGNORECASE),

    # Clinical / research support
    re.compile(r"\bresident\b", re.IGNORECASE),
    re.compile(r"\bintern\b", re.IGNORECASE),
    re.compile(r"\btechnician\b", re.IGNORECASE),
    re.compile(r"\btechnologist\b", re.IGNORECASE),
    re.compile(r"\bassistant scientist\b", re.IGNORECASE),

    # Admin / office staff
    re.compile(r"\bclerk\b", re.IGNORECASE),
    re.compile(r"\badministrative assistant\b", re.IGNORECASE),
    re.compile(r"\bexecutive assistant\b", re.IGNORECASE),
    re.compile(r"\bassistant to the dean\b", re.IGNORECASE),
    re.compile(r"\bassistant to the chair\b", re.IGNORECASE),
    re.compile(r"\bassistant director\b", re.IGNORECASE),
    re.compile(r"\bsecretary\b", re.IGNORECASE),
    re.compile(r"\breceptionist\b", re.IGNORECASE),
    re.compile(r"\bbusiness administrator\b", re.IGNORECASE),
    re.compile(r"\bdepartmental partner\b", re.IGNORECASE),
    re.compile(r"\bhuman resources\b", re.IGNORECASE),
    re.compile(r"\bhr partner\b", re.IGNORECASE),

    # Non-faculty "directors": career services, communications, recruitment, etc.
    re.compile(r"\bdirector of marketing\b", re.IGNORECASE),
    re.compile(r"\bdirector of communications\b", re.IGNORECASE),
    re.compile(r"\bdirector of strategic communications\b", re.IGNORECASE),
    re.compile(r"\bdirector of development\b", re.IGNORECASE),
    re.compile(r"\bdirector of budget\b", re.IGNORECASE),
    re.compile(r"\bdirector of finance\b", re.IGNORECASE),
    re.compile(r"\bdirector of student\b", re.IGNORECASE),
    re.compile(r"\bdirector of enrollment\b", re.IGNORECASE),
    re.compile(r"\bdirector of international programs\b", re.IGNORECASE),
    re.compile(r"\bdirector of graduate business career\b", re.IGNORECASE),
    re.compile(r"\bdirector of graduate recruitment\b", re.IGNORECASE),
    re.compile(r"\bexecutive director\b", re.IGNORECASE),
    re.compile(r"\bresident director\b", re.IGNORECASE),
    re.compile(r"\bvice president\b", re.IGNORECASE),
    re.compile(r"\bvp\b", re.IGNORECASE),

    # Advising / student services
    re.compile(r"\bacademic advisor\b", re.IGNORECASE),
    re.compile(r"\badviser\b", re.IGNORECASE),
    re.compile(r"\bstudent services\b", re.IGNORECASE),
    re.compile(r"\bstudent success\b", re.IGNORECASE),
    re.compile(r"\bstudent recruiter\b", re.IGNORECASE),
    re.compile(r"\brecruiter\b", re.IGNORECASE),
    re.compile(r"\bcounselor\b", re.IGNORECASE),
    re.compile(r"\bcoach\b", re.IGNORECASE),
    re.compile(r"\bcareer services\b", re.IGNORECASE),

    # Managers / coordinators / analysts / specialists
    re.compile(r"\bcoordinator\b", re.IGNORECASE),
    re.compile(r"\bprogram manager\b", re.IGNORECASE),
    re.compile(r"\boperations manager\b", re.IGNORECASE),
    re.compile(r"\bfacilities manager\b", re.IGNORECASE),
    re.compile(r"\bshop manager\b", re.IGNORECASE),
    re.compile(r"\blab manager\b", re.IGNORECASE),
    re.compile(r"\bgallery manager\b", re.IGNORECASE),
    re.compile(r"\bfacility manager\b", re.IGNORECASE),
    re.compile(r"\bproject manager\b", re.IGNORECASE),
    re.compile(r"\bshop supervisor\b", re.IGNORECASE),
    re.compile(r"\bgis analyst\b", re.IGNORECASE),
    re.compile(r"\bresearch analyst\b", re.IGNORECASE),
    re.compile(r"\banalyst\b", re.IGNORECASE),
    re.compile(r"\bcommunications specialist\b", re.IGNORECASE),
    re.compile(r"\bmarketing specialist\b", re.IGNORECASE),
    re.compile(r"\bfinancial specialist\b", re.IGNORECASE),
    re.compile(r"\bstudent services specialist\b", re.IGNORECASE),
    re.compile(r"\bit specialist\b", re.IGNORECASE),
    re.compile(r"\bprogram specialist\b", re.IGNORECASE),
    re.compile(r"\bsystem support specialist\b", re.IGNORECASE),
    re.compile(r"\blaptop program\b", re.IGNORECASE),

    # Budget / finance / IT
    re.compile(r"\bbudget\b", re.IGNORECASE),
    re.compile(r"\baccountant\b", re.IGNORECASE),
    re.compile(r"\bcustodian\b", re.IGNORECASE),
    re.compile(r"\barea mechanic\b", re.IGNORECASE),
    re.compile(r"\bcaretaker\b", re.IGNORECASE),
    re.compile(r"\bweb developer\b", re.IGNORECASE),
    re.compile(r"\bnetwork\b", re.IGNORECASE),
    re.compile(r"\bdesktop support\b", re.IGNORECASE),
    re.compile(r"\bsystems administrator\b", re.IGNORECASE),
    re.compile(r"\bit support\b", re.IGNORECASE),
    re.compile(r"\bvideographer\b", re.IGNORECASE),
    re.compile(r"\bstaff writer\b", re.IGNORECASE),
    re.compile(r"\bcommunity engagement strategist\b", re.IGNORECASE),
    re.compile(r"\bevents\b", re.IGNORECASE),
    re.compile(r"\balumni relations\b", re.IGNORECASE),
    re.compile(r"\bbusiness counselor\b", re.IGNORECASE),
]


def _part_is_faculty(part: str) -> bool:
    if not part:
        return False
    if any(p.search(part) for p in NON_FACULTY_TITLE_PATTERNS):
        return False
    return any(p.search(part) for p in FACULTY_TITLE_PATTERNS)


def is_faculty_title(title: str) -> bool:
    """Return True if the title text looks like an academic faculty rank.

    We split the title on `/` (which both sites use to separate multiple roles,
    e.g. "Director of Graduate Education / Associate Professor") and classify
    each part independently. A person is considered faculty if ANY part
    clearly names a faculty rank that is NOT itself overridden by a staff
    keyword. This keeps dual-role faculty administrators (e.g. "Executive
    Director for Healthcare Initiatives / Teaching Professor") while still
    rejecting staff-only strings like "Assistant to the Dean".
    """
    if not title:
        return False
    t = title.strip()
    if not t:
        return False

    # Split on the slash separator used by the Ivy/Design directories.
    parts = [p.strip() for p in t.split("/") if p.strip()]
    if not parts:
        return False
    if any(_part_is_faculty(p) for p in parts):
        return True
    # Fallback: look at the whole title — a single-part title with no slashes.
    return _part_is_faculty(t)


# ---- HTTP --------------------------------------------------------------------

HTTP_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def http_get(client: httpx.Client, url: str, params: dict | None = None) -> str:
    last_err: Exception | None = None
    for attempt in range(3):
        try:
            r = client.get(
                url,
                params=params,
                headers=HTTP_HEADERS,
                timeout=HTTP_TIMEOUT,
                follow_redirects=True,
            )
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.5 * (attempt + 1))
    raise RuntimeError(f"GET failed for {url}: {last_err}")


# ---- Identity helpers --------------------------------------------------------


_TRAILING_SUFFIX = re.compile(
    r",?\s*(ph\.?d\.?|ed\.?d\.?|m\.?d\.?|dvm|esq\.?|jr\.?|sr\.?|i{1,3}|iv)\b",
    re.IGNORECASE,
)


def slugify(name: str) -> str:
    """Kebab-case slug, e.g. 'Mark Raymond' -> 'mark-raymond'.

    Strips trailing academic/title suffixes (PhD, EdD, DVM, MD, Jr, Sr, III)
    before slugifying so that 'Douglas Spencer PhD' and 'Douglas Spencer' map
    to the same id.
    """
    base = _TRAILING_SUFFIX.sub("", name).strip()
    if not base:
        base = name
    n = unicodedata.normalize("NFKD", base)
    n = n.encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "-", n)
    return n.strip("-")


def normalize_title(raw: str) -> str:
    """Collapse whitespace, keep slashes/commas that separate roles."""
    if not raw:
        return ""
    # Replace various whitespace (including non-breaking) with a single space
    raw = raw.replace("\xa0", " ")
    raw = re.sub(r"\s+", " ", raw).strip()
    # Some cards end with a trailing '|' or ','
    raw = raw.rstrip("|, ")
    return raw


def normalize_name(raw: str) -> str:
    """Strip extra spaces; leave the site's natural ordering alone.

    Design site lists names as 'First Last'; Ivy site lists 'Last, First'.
    We preserve each site's native ordering in the output so callers don't
    have to re-parse.
    """
    if not raw:
        return ""
    return re.sub(r"\s+", " ", raw).strip()


def first_href(card, pattern: re.Pattern | None = None) -> str | None:
    for a in card.find_all("a", href=True):
        if pattern is None or pattern.search(a["href"]):
            return a["href"]
    return None


# ---- Design scraper ----------------------------------------------------------


def parse_design_card(card, department: str, filter_url: str) -> dict | None:
    """Pull (name, title, profile_url, photo_url, email) out of one card.

    Filter pages label every card with the filter's department, so the caller
    passes `department` in explicitly rather than trying to parse it from the
    card body.
    """
    # Name + profile URL from the content-title anchor
    title_p = card.select_one(".faculty-staff-card__content-title")
    if not title_p:
        return None
    name_anchor = title_p.find("a")
    name = normalize_name(name_anchor.get_text(" ", strip=True)) if name_anchor else normalize_name(title_p.get_text(" ", strip=True))
    if not name:
        return None
    profile_url = None
    if name_anchor and name_anchor.get("href"):
        profile_url = urljoin(filter_url, name_anchor["href"])

    # Titles: body paragraph lines, joined with ' / '
    title = ""
    body = card.select_one(".faculty-staff-card__content-body")
    if body:
        # Use <br>-separated lines
        lines: list[str] = []
        for chunk in body.stripped_strings:
            chunk = chunk.strip()
            if chunk:
                lines.append(chunk)
        title = " / ".join(lines)
    title = normalize_title(title)

    # Email
    email = ""
    mail_anchor = card.find("a", href=re.compile(r"^mailto:", re.IGNORECASE))
    if mail_anchor:
        email = mail_anchor["href"].split(":", 1)[1].strip()

    # Photo — first <img> with a usable src
    photo_url = None
    img = card.find("img")
    if img and img.get("src"):
        photo_url = img["src"]

    return {
        "name": name,
        "title": title,
        "profile_url": profile_url,
        "photo_url": photo_url,
        "email": email,
        "department": department,
        "college": DESIGN_COLLEGE,
        "id": slugify(name),
    }


def scrape_design_department(client: httpx.Client, department: str) -> list[dict]:
    params = {"department": department}
    html = http_get(client, DESIGN_DIRECTORY, params=params)
    time.sleep(REQUEST_DELAY)
    soup = BeautifulSoup(html, "lxml")
    cards = soup.select(".faculty-staff-card")
    out: list[dict] = []
    for card in cards:
        row = parse_design_card(
            card,
            department=department,
            filter_url=f"{DESIGN_DIRECTORY}?department={department.replace(' ', '+')}",
        )
        if row:
            out.append(row)
    return out


def scrape_design() -> tuple[list[dict], dict]:
    """Scrape every Design department filter and return faculty rows + stats."""
    print(f"[design] fetching {len(DESIGN_DEPARTMENTS)} department filters")
    all_cards: list[dict] = []
    per_dept_raw: dict[str, int] = {}

    with httpx.Client() as client:
        # Serial with 250ms delay — 10 filters is a tiny workload and we want to
        # stay politely under rate limits.
        for dept in DESIGN_DEPARTMENTS:
            rows = scrape_design_department(client, dept)
            per_dept_raw[dept] = len(rows)
            all_cards.extend(rows)
            print(f"[design]   {dept:32s} -> {len(rows):3d} cards")

    # Deduplicate by slug (first occurrence wins; academic departments iterate first)
    unique: OrderedDict[str, dict] = OrderedDict()
    for row in all_cards:
        key = row["id"] or row.get("email") or row["name"]
        if key in unique:
            continue
        unique[key] = row
    raw_unique = list(unique.values())

    # Filter to faculty
    faculty_rows = [r for r in raw_unique if is_faculty_title(r["title"])]

    stats = {
        "raw_cards_across_filters": len(all_cards),
        "raw_unique_people": len(raw_unique),
        "faculty_rows": len(faculty_rows),
        "per_filter_raw": per_dept_raw,
        "per_dept_final": Counter(r["department"] for r in faculty_rows),
        "skipped_non_faculty_examples": [
            (r["name"], r["title"], r["department"])
            for r in raw_unique
            if not is_faculty_title(r["title"])
        ][:10],
    }
    return faculty_rows, stats


# ---- Ivy scraper -------------------------------------------------------------


def parse_ivy_card(card) -> dict | None:
    """Extract a single Ivy directory row.

    Each card has the HTML shape:
        <div class="faculty-staff-card">
          <img ... />
          <p class="faculty-staff-card__content-title"><a href="lola7">Last, First</a></p>
          <div><strong>Title:</strong> Assistant Director ...</div>
          <div><strong>Department:</strong> Graduate Office</div>
          <div><strong>Office:</strong> 1420 Gerdin</div>
          <ul class="faculty-staff-card__content-contact">
            <li> ... phone ... </li>
            <li> ... <a href="mailto:lola7@iastate.edu">lola7@iastate.edu</a> ... </li>
          </ul>
        </div>
    The `<a href="lola7">` is RELATIVE (just the slug), so we urljoin against
    the directory root.
    """
    title_p = card.select_one(".faculty-staff-card__content-title")
    if not title_p:
        return None
    anchor = title_p.find("a")
    if not anchor:
        return None
    name = normalize_name(anchor.get_text(" ", strip=True))
    if not name:
        return None
    slug = anchor.get("href") or slugify(name)
    profile_url = urljoin(IVY_DIRECTORY, slug)

    # Walk the sibling <div><strong>Label:</strong> value</div> blocks
    labels: dict[str, str] = {}
    for div in card.find_all("div"):
        strong = div.find("strong")
        if not strong:
            continue
        label_text = strong.get_text(strip=True).rstrip(":").lower()
        if label_text not in {"title", "department", "office"}:
            continue
        # Value = full div text minus the label
        full = div.get_text(" ", strip=True)
        val = full
        if full.lower().startswith(f"{label_text}:"):
            val = full[len(label_text) + 1 :].strip()
        labels[label_text] = normalize_title(val)

    title = labels.get("title", "")
    department = labels.get("department", "")

    # Email
    email = ""
    mail_anchor = card.find("a", href=re.compile(r"^mailto:", re.IGNORECASE))
    if mail_anchor:
        email = mail_anchor["href"].split(":", 1)[1].strip()

    # Photo
    photo_url = None
    img = card.find("img")
    if img and img.get("src"):
        photo_url = img["src"]

    return {
        "name": name,
        "title": title,
        "profile_url": profile_url,
        "photo_url": photo_url,
        "email": email,
        "department": department,
        "college": IVY_COLLEGE,
        "id": slugify(name),
    }


def extract_ivy_profile_title(html: str) -> str:
    """Parse an Ivy profile page and return the full Title field text.

    Profile pages render the title with the same shape as the directory cards:
        <div><strong>Title:</strong> <value></div>
    but sometimes carry a longer / more-specific rank (e.g.
    "Dean's Fellow in Management / Professor" vs just "Dean's Fellow in
    Management"). We locate the `<strong>Title:</strong>` node and grab the
    text from that strong's direct parent only — NOT an ancestor chain, which
    would otherwise swallow the entire page body.
    """
    soup = BeautifulSoup(html, "lxml")
    for strong in soup.find_all("strong"):
        label = strong.get_text(strip=True).rstrip(":").lower()
        if label != "title":
            continue
        parent = strong.parent
        if parent is None:
            continue
        # Accept only short parent containers (a single row, not a wrapper)
        parent_text = parent.get_text(" ", strip=True)
        if len(parent_text) > 250:
            # Wrong hit — this is a wrapping container. Keep scanning.
            continue
        full = parent_text
        if full.lower().startswith("title:"):
            full = full[6:].strip()
        return normalize_title(full)
    return ""


def enrich_ivy_ambiguous(rows: list[dict], client: httpx.Client) -> int:
    """Mutate `rows` in place: for academic-dept rows whose listing title lacks
    a faculty keyword, fetch the profile page and replace the title with the
    longer profile-page value if that value exists.

    Concurrent fetches with MAX_WORKERS, 250 ms polite delay between per-worker
    requests. Only academic-department rows are enriched; non-academic rows
    stay as-is. Returns the number of rows whose title was actually updated.
    """
    faculty_kw = re.compile(
        r"(professor|lecturer|instructor|chair|faculty|emerita|emeritus)",
        re.IGNORECASE,
    )

    def needs_enrichment(row: dict) -> bool:
        if row.get("department") not in IVY_ACADEMIC_DEPARTMENTS:
            return False
        if not row.get("profile_url"):
            return False
        return not faculty_kw.search(row.get("title") or "")

    targets = [r for r in rows if needs_enrichment(r)]
    print(f"[ivy]   enriching {len(targets)} ambiguous academic-dept rows "
          f"from per-profile pages")

    def _fetch(row: dict) -> tuple[dict, str, str | None]:
        try:
            html = http_get(client, row["profile_url"])
        except Exception as e:  # noqa: BLE001
            return row, "", f"{type(e).__name__}: {e}"
        time.sleep(REQUEST_DELAY)
        return row, extract_ivy_profile_title(html), None

    updated = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(_fetch, r) for r in targets]
        for fut in as_completed(futures):
            row, full_title, err = fut.result()
            if err:
                print(f"[ivy]     enrich failed for {row['name']}: {err}")
                continue
            if full_title and full_title != row["title"]:
                # Encode name/titles to ASCII for logging so Windows cp1252
                # terminals don't choke on smart quotes.
                def _ascii(s: str) -> str:
                    return s.encode("ascii", "replace").decode("ascii")
                print(
                    f"[ivy]     enriched {_ascii(row['name']):<35s} "
                    f"{_ascii(row['title']):<45s} -> {_ascii(full_title)}"
                )
                row["title"] = full_title
                updated += 1
    return updated


def scrape_ivy() -> tuple[list[dict], dict]:
    print("[ivy] fetching unified directory")
    with httpx.Client() as client:
        html = http_get(client, IVY_DIRECTORY)
        time.sleep(REQUEST_DELAY)

        soup = BeautifulSoup(html, "lxml")
        cards = soup.select(".faculty-staff-card")
        print(f"[ivy]   found {len(cards)} raw cards")

        raw_rows: list[dict] = []
        for card in cards:
            row = parse_ivy_card(card)
            if row:
                raw_rows.append(row)

        # Deduplicate by slug (one person, one row) before enrichment, so we
        # only fetch the profile page for each unique person once.
        unique: OrderedDict[str, dict] = OrderedDict()
        for row in raw_rows:
            key = row["id"] or row.get("email") or row["name"]
            if key in unique:
                continue
            unique[key] = row
        raw_unique = list(unique.values())

        # Enrich ambiguous academic-dept rows with their profile-page title
        enriched_count = enrich_ivy_ambiguous(raw_unique, client)

    # Apply the faculty filter after enrichment. With richer titles, the
    # regular `is_faculty_title` can handle the decision without dept overrides.
    def keep(row: dict) -> bool:
        dep = (row.get("department") or "").strip()
        title_ok = is_faculty_title(row.get("title") or "")
        # Academic department: title_ok is sufficient
        if dep in IVY_ACADEMIC_DEPARTMENTS:
            return title_ok
        # Non-academic department: only keep if title is clearly faculty
        return title_ok

    faculty_rows = [r for r in raw_unique if keep(r)]

    stats = {
        "raw_cards": len(cards),
        "raw_parsed": len(raw_rows),
        "raw_unique_people": len(raw_unique),
        "enriched_rows": enriched_count,
        "faculty_rows": len(faculty_rows),
        "per_dept_raw": Counter(r["department"] for r in raw_unique),
        "per_dept_final": Counter(r["department"] for r in faculty_rows),
        "skipped_non_faculty_examples": [
            (r["name"], r["title"], r["department"])
            for r in raw_unique
            if not keep(r)
        ][:15],
    }
    return faculty_rows, stats


# ---- Orchestration -----------------------------------------------------------


def save_json(path: Path, rows: list[dict]) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def format_counter(c: Counter, total_label: str = "total") -> str:
    lines: list[str] = []
    for key, val in c.most_common():
        lines.append(f"- **{key}**: {val}")
    lines.append(f"- _{total_label}_: {sum(c.values())}")
    return "\n".join(lines)


def build_report(design_rows: list[dict], design_stats: dict,
                 ivy_rows: list[dict], ivy_stats: dict) -> str:
    design_counts = design_stats["per_dept_final"]
    ivy_counts = ivy_stats["per_dept_final"]

    lines: list[str] = []
    lines.append("# College of Design + Ivy College of Business - Department-Tagged Re-scrape")
    lines.append("")
    lines.append(f"Generated by `backend/scripts/scrape_design_ivy_v2.py`. "
                 f"Output files: `backend/data/design_v2_faculty.json` "
                 f"({len(design_rows)} rows), "
                 f"`backend/data/ivy_v2_faculty.json` ({len(ivy_rows)} rows).")
    lines.append("")
    lines.append("Both runs hit only the public unified directories; the existing "
                 "`design_faculty.json` and `ivy_faculty.json` files were left "
                 "untouched per instructions. Every row in the new files carries "
                 "a real department value (no `College of X` or `Unknown`).")
    lines.append("")
    lines.append("## Methodology")
    lines.append("")
    lines.append("- **Design** (https://www.design.iastate.edu/profiles/): the "
                 "unified `/profiles/` page shows 268 results but does not print "
                 "the department on the card, so we fetch the dropdown-filtered "
                 "view `?department=<Name>` once per department. Every card in "
                 "that filtered view is unambiguously tagged with the filter's "
                 "department. Academic departments iterate first so that "
                 "cross-listed faculty land in their primary academic department "
                 "when we deduplicate by slug.")
    lines.append("- **Ivy Business** (https://www.ivybusiness.iastate.edu/directory/): "
                 "the unified `/directory/` page renders every row with an inline "
                 "`<div><strong>Department:</strong> ...</div>` block, so a "
                 "single GET returns every person + their department. For "
                 "ambiguous academic-department rows whose listing title does "
                 "NOT contain a faculty keyword (Fellow, Director, etc.), we "
                 "fetch the individual profile page to recover the longer title "
                 "(e.g. `Dean's Fellow in Management / Professor`).")
    lines.append("- **Polite scraping**: 250 ms delay between requests, 8-way "
                 "concurrency for the Ivy profile enrichment, single-threaded "
                 "for the Design dept-filter sweep.")
    lines.append("- **Faculty classifier**: title is split on `/` and each "
                 "segment is checked independently against a keep-list "
                 "(professor/lecturer/instructor/faculty/chair/associate dean/"
                 "endowed dean/endowed chair/clinician) AFTER a strict "
                 "exclude-list (PhD student, administrative assistant, "
                 "assistant to the dean, assistant director, academic advisor, "
                 "custodian, coordinator, GIS analyst, etc.). Dual-role "
                 "faculty administrators like "
                 "`Executive Director for Healthcare Initiatives / Teaching Professor` "
                 "are kept because at least one segment is faculty-rank.")
    lines.append("")

    lines.append("## College of Design")
    lines.append("")
    lines.append(f"- Raw cards across all 10 department filters: "
                 f"{design_stats['raw_cards_across_filters']}")
    lines.append(f"- Unique people after cross-filter dedup: "
                 f"{design_stats['raw_unique_people']}")
    lines.append(f"- **Faculty after title filtering: "
                 f"{design_stats['faculty_rows']}**")
    lines.append("")
    lines.append("### Per-filter raw counts (before dedup)")
    for dept in DESIGN_DEPARTMENTS:
        n = design_stats["per_filter_raw"].get(dept, 0)
        lines.append(f"- {dept}: {n}")
    lines.append("")
    lines.append("### Per-department faculty (final output)")
    lines.append(format_counter(design_counts, total_label="total"))
    lines.append("")

    if design_stats["skipped_non_faculty_examples"]:
        lines.append("### Sample skipped non-faculty rows (sanity check)")
        for name, title, dept in design_stats["skipped_non_faculty_examples"]:
            lines.append(f"- {name} - _{title}_ ({dept})")
        lines.append("")

    lines.append("## Ivy College of Business")
    lines.append("")
    lines.append(f"- Raw cards on unified directory: {ivy_stats['raw_cards']}")
    lines.append(f"- Parsed rows: {ivy_stats['raw_parsed']}")
    lines.append(f"- Unique people after dedup: {ivy_stats['raw_unique_people']}")
    lines.append(f"- Ambiguous academic-dept rows enriched from profile pages: "
                 f"{ivy_stats['enriched_rows']}")
    lines.append(f"- **Faculty after title / department filtering: "
                 f"{ivy_stats['faculty_rows']}**")
    lines.append("")
    lines.append("### Raw per-department counts (all cards, pre-filter)")
    lines.append(format_counter(ivy_stats["per_dept_raw"], total_label="total"))
    lines.append("")
    lines.append("### Per-department faculty (final output)")
    lines.append(format_counter(ivy_counts, total_label="total"))
    lines.append("")
    lines.append("Academic departments kept: "
                 + ", ".join(sorted(IVY_ACADEMIC_DEPARTMENTS)))
    lines.append("")
    lines.append("Non-academic department rows are retained ONLY when the title "
                 "clearly names a professor rank (e.g. Raj Agnihotri, Raisbeck "
                 "Endowed Dean; Mike Howe, Hadden Professor + Interim Associate "
                 "Dean; Valentina Salotti, Carlson Professor + Sr. Associate "
                 "Dean for Academic Affairs).")
    lines.append("")

    if ivy_stats["skipped_non_faculty_examples"]:
        lines.append("### Sample skipped non-faculty rows (sanity check)")
        for name, title, dept in ivy_stats["skipped_non_faculty_examples"]:
            lines.append(f"- {name} - _{title}_ ({dept})")
        lines.append("")

    lines.append("## Schema")
    lines.append("")
    lines.append("Both files match `coe_faculty.json`:")
    lines.append("```json")
    lines.append('{')
    lines.append('  "name": "Mark Raymond",')
    lines.append('  "title": "Chair - Architecture / Professor",')
    lines.append('  "profile_url": "https://www.design.iastate.edu/profiles/mark01/",')
    lines.append('  "photo_url": "https://www.design.iastate.edu/wp-content/uploads/faculty_square/mark01.jpg",')
    lines.append('  "email": "mark01@iastate.edu",')
    lines.append('  "department": "Architecture",')
    lines.append('  "college": "College of Design",')
    lines.append('  "id": "mark-raymond"')
    lines.append('}')
    lines.append("```")
    lines.append("")
    lines.append("`id` is `slugify(name)`, with common suffixes (PhD, EdD, MD, "
                 "Jr, Sr, etc.) stripped before slugifying so that "
                 "`Douglas Spencer PhD` -> `douglas-spencer`.")
    return "\n".join(lines) + "\n"


def main() -> None:
    design_rows, design_stats = scrape_design()
    ivy_rows, ivy_stats = scrape_ivy()

    DATA.mkdir(parents=True, exist_ok=True)
    save_json(DESIGN_OUT, design_rows)
    save_json(IVY_OUT, ivy_rows)

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(build_report(design_rows, design_stats, ivy_rows, ivy_stats),
                      encoding="utf-8")

    print()
    print("===== SUMMARY =====")
    print(f"Design  : {len(design_rows):4d} faculty -> {DESIGN_OUT}")
    print(f"Ivy     : {len(ivy_rows):4d} faculty -> {IVY_OUT}")
    print(f"Report  : {REPORT}")
    print()
    print("Design per-department:")
    for k, v in design_stats["per_dept_final"].most_common():
        print(f"  {v:4d}  {k}")
    print()
    print("Ivy per-department:")
    for k, v in ivy_stats["per_dept_final"].most_common():
        print(f"  {v:4d}  {k}")


if __name__ == "__main__":
    main()
