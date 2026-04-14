"""Scrape the ISU College of Health and Human Sciences faculty directory.

Strategy
--------
Every CHHS department directory page (e.g. https://aeshm.hs.iastate.edu/directory/)
renders via a React widget backed by a WordPress plugin called "hs-directory".
The plugin exposes a JSON REST namespace at `/wp-json/fhsd/directory/` with:

  - check-multisite : returns the blog_id for the current subdomain
  - get-directory   : paginated list of staff; filter by `site=<blog_id>`
  - get-staff-member: per-person details (research interests, bio, etc.)

The mainsite endpoint `https://hs.iastate.edu/wp-json/fhsd/directory/get-directory/`
returns a cumulative `staff` array across pages (page 2 contains all of page 1
plus the next 12, etc). `nextpage=false` signals the final page. The final
page therefore holds the complete list; we simply keep requesting until
`nextpage` is false and take the last `staff` array.

Known blog_id mapping (from `check-multisite`):
  AESHM  -> 5
  FSHN   -> 6
  HDFS   -> 7
  KIN    -> 3
  EDU    -> 4

Because each department's directory is a standalone React app on its own
subdomain we iterate the five subdomains and query the mainsite API with
`site=<blog_id>`. We then optionally enrich each faculty record via
`get-staff-member/?slug=<slug>` to pull research_interests and bio.

Cloudflare protects these endpoints so we use `curl_cffi` to impersonate a
real Chrome browser. Polite: 250ms between requests, single-threaded.

Output
------
Writes `backend/data/chhs_faculty.json` as a list of dicts matching the
coe_faculty.json schema extended with research_interests, courses_taught,
is_teaching_faculty and source_url.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from curl_cffi import requests

BASE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
OUT_PATH = BASE / "data" / "chhs_faculty.json"
REPORT_PATH = Path("D:/Dropbox/RAG-DSpace/isu-research-search/tests/results/CHHS_SCRAPE_REPORT.md")

MAINSITE = "https://hs.iastate.edu"
API_GET_DIRECTORY = f"{MAINSITE}/wp-json/fhsd/directory/get-directory/"
API_GET_STAFF = f"{MAINSITE}/wp-json/fhsd/directory/get-staff-member/"

# blog_id per department subdomain, plus canonical department label we want
# to store on each record, plus the subdomain that owns the directory page.
DEPARTMENTS: list[tuple[str, int, str, str]] = [
    # (short_code, blog_id, canonical_dept_name, subdomain_url)
    ("AESHM", 5, "Apparel, Events, and Hospitality Management", "https://aeshm.hs.iastate.edu"),
    ("FSHN", 6, "Food Science and Human Nutrition", "https://fshn.hs.iastate.edu"),
    ("HDFS", 7, "Human Development and Family Studies", "https://hdfs.hs.iastate.edu"),
    ("KIN", 3, "Kinesiology and Health", "https://kin.hs.iastate.edu"),
    ("EDU", 4, "School of Education", "https://education.iastate.edu"),
]

# Titles that we consider faculty (scholarly / teaching).  Keep inclusive:
# Emeritus, Clinical, Research, Adjunct, Affiliate, Assistant, Associate,
# Teaching Professor, Professor of Practice, Lecturer, Instructor.  Also
# accept leadership-who-are-faculty (Department Chair, Director of School,
# Associate Dean) and the literal suffix "Graduate Faculty".
FACULTY_TITLE_RE = re.compile(
    r"\b("
    r"Professor"            # any flavor of professor, emeritus, teaching
    r"|Lecturer"
    r"|Instructor"
    r"|Scholar"
    r"|Graduate Faculty"    # suffix indicating grad-faculty status
    r"|Department Chair"
    r"|Director of the School"
    r"|Director.*School of Education"
    r"|Associate Dean"
    r"|Dean,"              # "Dean, ..."
    r")\b",
    re.I,
)

# Heuristic: recognize teaching-track faculty so we can tag is_teaching_faculty.
TEACHING_TRACK_RE = re.compile(
    r"\b(Teaching Professor|Lecturer|Instructor|Academic Specialist|Clinical (Assistant|Associate )?Professor)\b",
    re.I,
)

POLITE_DELAY = 0.25  # seconds between requests

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
}


@dataclass
class Stats:
    department: str
    total_records: int = 0
    faculty_kept: int = 0
    enriched_ok: int = 0
    enrich_failed: int = 0
    errors: list[str] = field(default_factory=list)


def slugify(name: str) -> str:
    """Convert 'Last, First Middle' -> 'first-middle-last' slug."""
    name = (name or "").strip()
    # The API gives us Last, First (Middle) often. Normalize.
    if "," in name:
        last, first = [p.strip() for p in name.split(",", 1)]
        name = f"{first} {last}"
    # Drop punctuation
    s = re.sub(r"[^\w\s-]", "", name, flags=re.UNICODE).strip().lower()
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s or "unknown"


def strip_html(s: str) -> str:
    """Minimal HTML -> text. The API returns <ul><li>… for research interests."""
    if not s:
        return ""
    s = re.sub(r"</li\s*>\s*<li\s*>", "|", s, flags=re.I)
    s = re.sub(r"<br\s*/?>", "|", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = s.replace("&#8211;", "-").replace("&#8217;", "'").replace("&amp;", "&")
    s = s.replace("&#038;", "&").replace("&nbsp;", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_research_interests(raw_html: str) -> list[str]:
    """The fhsd_staff_research_interests field is a WP-rendered HTML blob.
    It's usually a <ul><li>… list. Extract each bullet as a string."""
    if not raw_html:
        return []
    # Extract <li>… text
    items = re.findall(r"<li[^>]*>(.*?)</li>", raw_html, flags=re.I | re.S)
    if not items:
        # Fallback: split on line breaks / paragraphs
        text = strip_html(raw_html)
        if not text:
            return []
        parts = [p.strip() for p in re.split(r"[|\n]+", text) if p.strip()]
        return parts[:25]
    out = []
    for it in items:
        txt = strip_html(it)
        if txt and len(txt) < 300:
            out.append(txt)
    return out[:25]


def looks_like_faculty(title: str) -> bool:
    if not title:
        return False
    return bool(FACULTY_TITLE_RE.search(title))


def is_teaching(title: str) -> bool:
    return bool(TEACHING_TRACK_RE.search(title or ""))


def fetch_directory_for_site(session: requests.Session, site: int, dept_url: str) -> list[dict[str, Any]]:
    """Query get-directory for a given blog_id/site until nextpage=False.
    Return the final cumulative staff array."""
    final_staff: list[dict[str, Any]] = []
    page = 1
    referer = f"{dept_url.rstrip('/')}/directory/"
    while True:
        params = {
            "department": "",
            "searchName": "",
            "keyword": "",
            "page": str(page),
            "site": str(site),
        }
        r = session.get(
            API_GET_DIRECTORY,
            params=params,
            headers={**HEADERS, "Referer": referer},
            timeout=30,
        )
        if r.status_code != 200:
            raise RuntimeError(f"get-directory site={site} page={page} -> HTTP {r.status_code}")
        data = r.json()
        staff = data.get("staff", []) or []
        if staff:
            final_staff = staff  # cumulative; always take latest
        if not data.get("nextpage") or not staff:
            break
        page += 1
        if page > 60:  # hard safety stop
            break
        time.sleep(POLITE_DELAY)
    return final_staff


def fetch_staff_detail(session: requests.Session, slug: str, referer: str) -> dict[str, Any] | None:
    try:
        r = session.get(
            API_GET_STAFF,
            params={"slug": slug},
            headers={**HEADERS, "Referer": referer},
            timeout=30,
        )
        if r.status_code != 200:
            return None
        data = r.json()
        if not isinstance(data, dict):
            return None
        return data
    except Exception:
        return None


def build_full_name(rec: dict[str, Any]) -> str:
    fname = (rec.get("fname") or "").strip()
    mname = (rec.get("mname") or "").strip()
    lname = (rec.get("lname") or "").strip()
    parts = [p for p in (lname, ", ".join([x for x in [fname, mname] if x])) if p]
    # Produce "Last, First Middle"
    fm = " ".join([x for x in [fname, mname] if x])
    if lname and fm:
        return f"{lname}, {fm}".strip()
    return lname or fm or "Unknown"


def build_profile_url(slug: str, dept_url: str) -> str:
    return f"{dept_url.rstrip('/')}/directory/{slug}/"


def normalize_record(
    rec: dict[str, Any],
    canonical_dept: str,
    dept_url: str,
    detail: dict[str, Any] | None,
) -> dict[str, Any]:
    full_name = build_full_name(rec)
    slug = (rec.get("slug") or "").strip() or slugify(full_name)
    title = (rec.get("title") or "").strip()
    email = (rec.get("email") or "").strip().lower() or None
    img = rec.get("img") or None
    profile_url = build_profile_url(slug, dept_url)

    research_interests: list[str] = []
    if detail:
        ri_raw = detail.get("fhsd_staff_research_interests") or ""
        if isinstance(ri_raw, str):
            research_interests = parse_research_interests(ri_raw)

    return {
        "id": slugify(full_name),
        "name": full_name,
        "title": title,
        "department": canonical_dept,
        "college": "College of Health and Human Sciences",
        "email": email,
        "profile_url": profile_url,
        "photo_url": img,
        "research_interests": research_interests,
        "courses_taught": [],
        "is_teaching_faculty": is_teaching(title),
        "source_url": profile_url,
    }


def main() -> None:
    session = requests.Session(impersonate="chrome124")

    all_records: dict[str, dict[str, Any]] = {}
    stats_by_dept: list[Stats] = []
    started = datetime.now(timezone.utc).isoformat()

    print("== CHHS scrape ==", started)
    print()

    for code, site, canonical, dept_url in DEPARTMENTS:
        print(f"[{code}] fetching directory site={site} ({canonical})")
        stats = Stats(department=canonical)
        try:
            staff = fetch_directory_for_site(session, site, dept_url)
        except Exception as e:  # noqa: BLE001
            msg = f"{type(e).__name__}: {e}"
            print(f"  ERROR: {msg}")
            stats.errors.append(msg)
            stats_by_dept.append(stats)
            continue

        stats.total_records = len(staff)
        print(f"  got {len(staff)} raw records")

        # Filter to records whose primary department matches this subdomain,
        # so joint-appointed people get attributed to their home unit.
        # The API's department.name varies slightly (trailing-Oxford-comma
        # inconsistency); use the blog_id (site) for identity.
        primary_records = []
        for rec in staff:
            d = rec.get("department") or {}
            site_id = d.get("site")
            if site_id == site:
                primary_records.append(rec)
            elif site_id is None:
                # Missing -- attribute to this directory (shouldn't happen)
                primary_records.append(rec)

        print(f"  {len(primary_records)} primary-site records")

        # Now classify as faculty vs admin and enrich the faculty.
        kept = 0
        for rec in primary_records:
            title = rec.get("title") or ""
            if not looks_like_faculty(title):
                continue
            full_name = build_full_name(rec)
            dedup_key = (rec.get("email") or "").strip().lower() or slugify(full_name)
            if dedup_key in all_records:
                # Already seen (cross-dept duplicate). Skip.
                continue

            slug = (rec.get("slug") or "").strip()
            detail = None
            if slug:
                detail = fetch_staff_detail(session, slug, f"{dept_url.rstrip('/')}/directory/")
                if detail:
                    stats.enriched_ok += 1
                else:
                    stats.enrich_failed += 1
                time.sleep(POLITE_DELAY)

            normalized = normalize_record(rec, canonical, dept_url, detail)
            all_records[dedup_key] = normalized
            kept += 1

        stats.faculty_kept = kept
        print(f"  kept {kept} faculty (enriched {stats.enriched_ok}, enrich-fail {stats.enrich_failed})")
        stats_by_dept.append(stats)

    # Write output
    records = list(all_records.values())
    # Sort by department then name
    records.sort(key=lambda r: (r["department"], r["name"].lower()))

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"Wrote {len(records)} faculty -> {OUT_PATH}")

    # Write report
    finished = datetime.now(timezone.utc).isoformat()
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# CHHS Faculty Scrape Report",
        "",
        f"Started: {started}",
        f"Finished: {finished}",
        "",
        "## Strategy",
        "",
        "All five CHHS department directory pages use the `hs-directory`",
        "WordPress plugin which exposes JSON at",
        "`https://hs.iastate.edu/wp-json/fhsd/directory/get-directory/` and",
        "`.../get-staff-member/`. The React widget queries the mainsite API with a",
        "`site=<blog_id>` parameter where blog_id comes from the subdomain's",
        "`check-multisite` endpoint. I hit these endpoints directly via",
        "`curl_cffi` (Cloudflare requires browser TLS fingerprints).",
        "",
        "blog_id map (from `check-multisite`):",
        "",
        "| Code | Department | blog_id |",
        "|---|---|---|",
    ]
    for code, site, canonical, _url in DEPARTMENTS:
        lines.append(f"| {code} | {canonical} | {site} |")
    lines += [
        "",
        "## Per-department results",
        "",
        "| Department | Raw records | Faculty kept | Enriched OK | Enrich failed | Errors |",
        "|---|---:|---:|---:|---:|---|",
    ]
    total_raw = 0
    total_kept = 0
    total_enriched = 0
    for st in stats_by_dept:
        total_raw += st.total_records
        total_kept += st.faculty_kept
        total_enriched += st.enriched_ok
        err_note = "; ".join(st.errors) or "-"
        lines.append(
            f"| {st.department} | {st.total_records} | {st.faculty_kept} |"
            f" {st.enriched_ok} | {st.enrich_failed} | {err_note} |"
        )
    lines += [
        f"| **TOTAL** | **{total_raw}** | **{total_kept}** | **{total_enriched}** | | |",
        "",
        "## Faculty filter rule",
        "",
        "A record was retained as faculty if its `title` field matched any of:",
        "Professor (any), Lecturer, Instructor, Scholar, Graduate Faculty,",
        "Department Chair, Director of the School, Associate Dean, Dean,.",
        "Everyone else (program specialists, academic advisors, administrative",
        "assistants, research scientists, AmeriCorps, instructional designers,",
        "etc.) was skipped.",
        "",
        "## Output",
        "",
        f"- `{OUT_PATH}` - {len(records)} unique faculty records",
        f"- Schema: id, name, title, department, college, email, profile_url,"
        f" photo_url, research_interests, courses_taught, is_teaching_faculty,"
        f" source_url",
        "",
        "## Notes / caveats",
        "",
        "- The `get-directory` endpoint returns a *cumulative* staff array per",
        "  page (page N has the first N*12 results), so we just keep requesting",
        "  until `nextpage=false` and take the final array.",
        "- Dedup key is email (primary) -> slugified name (fallback). Faculty",
        "  with joint appointments are attributed to whichever subdomain we",
        "  scraped first in the DEPARTMENTS list.",
        "- `courses_taught` is left empty; the API doesn't expose course",
        "  assignments.",
        "- Research interests come from `fhsd_staff_research_interests`, which",
        "  the editor types as free-form HTML (<ul><li>...</li></ul> usually).",
        "  We parse each <li> as a separate interest.",
        "- Cloudflare blocks plain httpx; requires curl_cffi with Chrome TLS",
        "  impersonation (`impersonate='chrome124'`).",
    ]
    REPORT_PATH.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote report -> {REPORT_PATH}")
    print()
    print("===== SUMMARY =====")
    for st in stats_by_dept:
        print(f"  {st.department:50s} raw={st.total_records:4d} kept={st.faculty_kept:4d}")
    print(f"  {'TOTAL':50s} kept={len(records)}")


if __name__ == "__main__":
    main()
