"""Scrape ISU CALS per-department faculty and the 3 COE-missing departments.

Produces two new files under backend/data/:
  * cals_v2_faculty.json        (replacement for sparse cals_faculty.json)
  * coe_missing_faculty.json    (ABE / CBE / CCEE only)

Existing files are never modified.

Data sources per department
---------------------------
AGRON        : https://www.agron.iastate.edu/wp-json/wp/v2/people (WP REST)
                + per-profile HTML enrichment for title / email / photo
HORT         : https://www.hort.iastate.edu/directory-section/faculty/page/N/
                Fetched via an out-of-process helper (WebFetch-injected snapshot
                JSON produced beforehand, see HORT_SNAPSHOT_JSON); a fallback
                parses catalog.iastate.edu Horticulture entries.
ABE/CBE/CCEE : https://www.engineering.iastate.edu/people/wp-json/wp/v2/profile
                (same REST that backs coe_faculty.json)
AGEDS / ANS / NREM / PPEM
              : https://catalog.iastate.edu/faculty/ (canonical alphabetical
                master list; every person has title + department in a <p>
                following a name <h4>).

Why catalog for AGEDS/ANS/NREM/PPEM: those four department subdomains are
pinned to the ISU datacenter IP 129.186.90.87, which is unreachable from this
runner (socket errors). The catalog is served from a different edge, is the
university's own authoritative faculty list, and already carries canonical
department labels.

Output schema (matches backend/data/coe_faculty.json shape)
---------------------------------------------------------
    id                 slug(name)  lowercased, hyphenated, ascii
    name               "First Last"
    title              raw title string (e.g. "Associate Professor")
    department         canonical dept name
    college            "College of Agriculture and Life Sciences" or
                       "College of Engineering"
    email              iastate.edu email if discovered, else ""
    profile_url        department or engineering profile page URL if any
    photo_url          headshot URL if any, else ""
    research_interests []
    courses_taught     []
    is_teaching_faculty bool derived from the title string
    source_url         the origin URL the record came from
"""
from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import httpx
from bs4 import BeautifulSoup

# -----------------------------------------------------------------------------
# Paths and constants
# -----------------------------------------------------------------------------

BASE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
DATA = BASE / "data"
RESULTS = BASE.parent / "tests" / "results"
CALS_OUT = DATA / "cals_v2_faculty.json"
COE_OUT = DATA / "coe_missing_faculty.json"
REPORT = RESULTS / "CALS_COE_SCRAPE_REPORT.md"
HORT_SNAPSHOT_JSON = BASE / "scripts" / "_hort_webfetch_snapshot.json"

CALS = "College of Agriculture and Life Sciences"
COE = "College of Engineering"

HEADERS = {
    "User-Agent": "ISU-RAG-Indexer/1.0 (academic research; contact asukul@iastate.edu)",
    "Accept": "text/html,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

POLITE_DELAY_SEC = 0.25
TIMEOUT = 30.0


# -----------------------------------------------------------------------------
# Data model
# -----------------------------------------------------------------------------


@dataclass
class Faculty:
    id: str
    name: str
    title: str
    department: str
    college: str
    email: str = ""
    profile_url: str = ""
    photo_url: str = ""
    research_interests: list[str] = field(default_factory=list)
    courses_taught: list[str] = field(default_factory=list)
    is_teaching_faculty: bool = False
    source_url: str = ""


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def slugify(text: str) -> str:
    """Stable id slug: NFKD-normalised, lowercased, hyphen-separated ascii."""
    norm = unicodedata.normalize("NFKD", text)
    ascii_ = norm.encode("ascii", "ignore").decode("ascii")
    ascii_ = ascii_.lower()
    ascii_ = re.sub(r"[^a-z0-9]+", "-", ascii_)
    return ascii_.strip("-")


def looks_like_teaching_faculty(title: str) -> bool:
    t = title.lower()
    return any(
        kw in t
        for kw in (
            "teaching professor",
            "lecturer",
            "instructor",
            "professor of practice",
            "of practice",
        )
    )


_NONFACULTY_TITLE_KEYWORDS = (
    "graduate student",
    "grad student",
    "undergraduate",
    "phd candidate",
    "doctoral student",
    "student worker",
    "intern",
    # admin / staff roles with no faculty designation
    "manager research",
    "senior manager",
    "manager of",
    "information technology",
    "it support",
    "data analyst",
    "program coordinator",
    "administrative assistant",
    "financial specialist",
    "accountant",
    "communications specialist",
    "outreach coordinator",
    "department assistant",
    "office assistant",
    "facilities manager",
    "lab manager",
    "human resources",
    "hr specialist",
)


def is_faculty_title(title: str, allow_emeritus: bool = True) -> bool:
    """Return True iff the title string suggests a faculty (not pure staff/student) role."""
    if not title:
        return False
    t = title.lower()
    if any(kw in t for kw in _NONFACULTY_TITLE_KEYWORDS):
        return False
    faculty_markers = (
        "professor",
        "lecturer",
        "instructor",
        "scholar",
        "chair",
        "dean",
        "director of ",
    )
    if not allow_emeritus and "emeritus" in t or "emerita" in t:
        return False
    return any(m in t for m in faculty_markers)


def format_catalog_name(raw: str) -> str:
    """ABARCA, SAUL -> Saul Abarca; SCHWAB, ELIZABETH -> Elizabeth Schwab.

    Handles middle initials and 'JR.'/'III' suffixes; strips periods and
    preserves compound last names by rejoining the 'last' part with spaces.
    """
    raw = raw.strip().rstrip(".")
    if "," not in raw:
        return raw.title()
    last, rest = raw.split(",", 1)
    rest = rest.strip()
    last = last.strip()
    # Title-case but keep 'McSomething' / 'O'Neill' style where possible;
    # for the catalog, all input is UPPERCASE, so .title() is safe enough.
    last_formatted = last.title()
    # Rest may be "JANE ELIZABETH" or "JANE E." or "J. MICHAEL"
    parts = [p.title() for p in rest.split() if p]
    first_formatted = " ".join(parts)
    return f"{first_formatted} {last_formatted}".strip()


def split_title_chunk(title_chunk: str) -> tuple[str, str]:
    """Given the first chunk of a catalog body (before the period ending the
    last appointment), separate the rank phrase from the department string.

    Handles all observed patterns:
        "Professor of Horticulture"
        "Emeritus Professor of Agronomy"
        "Affiliate Assistant Professor of Horticulture"
        "Professor of Horticulture and Chair of the Department"
        "Professor of Practice in Agricultural and Biosystems Engineering"
        "Professor of Practice, Animal Science"
        "Professor of Horticulture and Interim Chair of Agricultural Education and Studies"
    """
    s = title_chunk.strip()
    # Pattern A: "<rank> of <dept>" with optional "and Chair of..."
    m = re.match(
        r"^(?P<rank>.+?)\s+of\s+(?P<dept>.+?)(?:\s+and\s+(?:Interim\s+)?Chair\s+of.*)?$",
        s,
    )
    if m:
        return m.group("rank").strip(), m.group("dept").strip()
    # Pattern B: "Professor of Practice, <dept>"  (or "in Dept")
    m = re.match(r"^(?P<rank>Professor of Practice)(?:\s+in|,)\s+(?P<dept>.+)$", s)
    if m:
        return m.group("rank").strip(), m.group("dept").strip()
    # Pattern C: "Practice, <dept>"
    m = re.match(r"^Practice(?:\s+in)?,?\s+(?P<dept>.+)$", s)
    if m:
        return "Professor of Practice", m.group("dept").strip()
    return s, ""


def canonicalise_dept(raw: str) -> str:
    """Normalise variants used in the catalog back to our canonical names."""
    r = raw.strip()
    # Replace stray non-breaking space / weird unicode
    r = r.replace("\xa0", " ").replace("\u2009", " ")
    r = re.sub(r"\s+", " ", r)
    fixes = {
        "Agricultural and Biosystems Engineering": "Agricultural and Biosystems Engineering",
        "Civil, Construction, and Environmental Engineering": "Civil, Construction and Environmental Engineering",
        "Civil, Construction and Environmental Engineering": "Civil, Construction and Environmental Engineering",
        "Chemical and Biological Engineering": "Chemical and Biological Engineering",
        "Agricultural Education and Studies": "Agricultural Education and Studies",
        "Agronomy": "Agronomy",
        "Animal Science": "Animal Science",
        "Horticulture": "Horticulture",
        "Natural Resource Ecology and Management": "Natural Resource Ecology and Management",
        "Natural Resource and Ecology Management": "Natural Resource Ecology and Management",
        "Plant Pathology, Entomology, and Microbiology": "Plant Pathology, Entomology and Microbiology",
        "Plant Pathology, Entomology and Microbiology": "Plant Pathology, Entomology and Microbiology",
    }
    return fixes.get(r, r)


# -----------------------------------------------------------------------------
# Catalog-based parser (used for AGEDS / ANS / NREM / PPEM)
# -----------------------------------------------------------------------------


TARGET_CATALOG_DEPTS = {
    "Agricultural Education and Studies",
    "Animal Science",
    "Natural Resource Ecology and Management",
    "Plant Pathology, Entomology and Microbiology",
}
# Map canonical dept -> (college, source_base_url) used in the Faculty rows
CATALOG_DEPT_META: dict[str, tuple[str, str]] = {
    "Agricultural Education and Studies": (CALS, "https://www.ageds.iastate.edu/people"),
    "Animal Science": (CALS, "https://www.ans.iastate.edu/people/faculty"),
    "Natural Resource Ecology and Management": (CALS, "https://www.nrem.iastate.edu/people/faculty"),
    "Plant Pathology, Entomology and Microbiology": (CALS, "https://www.ppem.iastate.edu/people"),
}


def fetch_catalog_html(client: httpx.Client) -> str:
    print("[catalog] fetching https://catalog.iastate.edu/faculty/", flush=True)
    r = client.get("https://catalog.iastate.edu/faculty/")
    r.raise_for_status()
    return r.text


def parse_catalog(html: str, want_depts: set[str]) -> list[Faculty]:
    """Walk every <h4> name in the catalog, pair it with the next <p>,
    extract the primary department from the first "rank of <dept>" chunk,
    and emit a Faculty row if that dept is in want_depts."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("div", id="textcontainer") or soup.find("main") or soup
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    for h in main.find_all("h4"):
        raw_name = h.get_text(" ", strip=True)
        if not re.match(r"^[A-Z][A-Z \-']+,\s*[A-Z]", raw_name):
            continue
        nxt = h.find_next_sibling()
        if nxt is None or nxt.name != "p":
            continue
        body = nxt.get_text(" ", strip=True)
        # split on '.', take the first sentence as the appointment chunk
        # (but be robust: '.' appears inside degrees too). Use a pragmatic cut:
        # first chunk that ends with '. ' followed by an uppercase letter marking
        # the start of degrees ("B.S.", "B.A.", "M.S.", "Ph.D.", "Bachelor's").
        chunk_match = re.match(
            r"^(?P<chunk>.+?)\.\s+(?=B\.|M\.|Ph\.|Bachelor|Master|Doctor|D\.|J\.|Sc\.|Dr\.)",
            body,
        )
        if chunk_match:
            chunk = chunk_match.group("chunk")
        else:
            # fall back: first period-terminated phrase
            chunk = body.split(". ", 1)[0]
        # Split on ';' to handle joint appointments. First segment is primary.
        segments = [seg.strip() for seg in chunk.split(";") if seg.strip()]
        if not segments:
            continue
        primary = segments[0]
        rank, dept_raw = split_title_chunk(primary)
        if not dept_raw:
            continue
        # Strip any trailing ", University Professor" / ", Morrill Professor" kludges
        dept_raw = re.sub(
            r";?\s*(Charles F.*|Anson.*|Mary B.*|Morrill Professor|University Professor.*|Clarence.*)$",
            "",
            dept_raw,
        ).strip()
        dept = canonicalise_dept(dept_raw)
        if dept not in want_depts:
            continue
        # Build the full title: rank + any secondary appointments summary
        title_parts = [rank]
        for seg in segments[1:]:
            title_parts.append(seg)
        full_title = "; ".join(title_parts)[:400]
        name = format_catalog_name(raw_name)
        # Skip pure student/grad titles
        if not is_faculty_title(full_title, allow_emeritus=True):
            continue
        college, source_url = CATALOG_DEPT_META[dept]
        rec = Faculty(
            id=slugify(name),
            name=name,
            title=full_title,
            department=dept,
            college=college,
            is_teaching_faculty=looks_like_teaching_faculty(full_title),
            source_url=source_url,
        )
        if rec.id in seen_ids:
            continue
        seen_ids.add(rec.id)
        out.append(rec)
    return out


# -----------------------------------------------------------------------------
# Agronomy: WP REST + profile HTML enrichment
# -----------------------------------------------------------------------------


AGRON_REST = "https://www.agron.iastate.edu/wp-json/wp/v2"
# People-category IDs discovered live
AGRON_FACULTY_CAT = 227       # count 53
AGRON_EMERITUS_CAT = 250      # count 32
AGRON_EXTENSION_CAT = 289     # count 7 — extension specialists, many faculty rank


def scrape_agron(client: httpx.Client) -> list[Faculty]:
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    for cat_id, cat_label in (
        (AGRON_FACULTY_CAT, "faculty"),
        (AGRON_EMERITUS_CAT, "emeritus"),
        (AGRON_EXTENSION_CAT, "extension"),
    ):
        page = 1
        while True:
            params = {
                "people-category": cat_id,
                "per_page": 100,
                "page": page,
                "_embed": 1,
            }
            r = client.get(f"{AGRON_REST}/people", params=params)
            if r.status_code == 400:
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for p in batch:
                rec = _agron_person_to_faculty(p)
                if rec is None:
                    continue
                # enrich title+email+photo from the profile HTML
                _agron_enrich_from_profile(client, rec)
                if rec.id not in seen_ids:
                    seen_ids.add(rec.id)
                    out.append(rec)
            total_pages = int(r.headers.get("X-WP-TotalPages") or 1)
            print(
                f"[agron] {cat_label} page {page}/{total_pages} "
                f"got {len(batch)} cumulative {len(out)}",
                flush=True,
            )
            if page >= total_pages:
                break
            page += 1
            time.sleep(POLITE_DELAY_SEC)
    return out


def _agron_person_to_faculty(p: dict[str, Any]) -> Faculty | None:
    title_html = p.get("title", {}).get("rendered", "") or ""
    name = _clean_name_from_title(title_html)
    if not name:
        return None
    link = p.get("link", "") or ""
    # featured_media embed
    photo_url = ""
    media = p.get("_embedded", {}).get("wp:featuredmedia", [])
    if media and isinstance(media, list):
        photo_url = media[0].get("source_url", "") or ""
    return Faculty(
        id=slugify(name),
        name=name,
        title="",
        department="Agronomy",
        college=CALS,
        email="",
        profile_url=link,
        photo_url=photo_url,
        source_url="https://www.agron.iastate.edu/directory/",
    )


def _clean_name_from_title(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html).strip()
    text = html_unescape(text)
    # Strip leading honorifics
    text = re.sub(r"^(Dr\.?|Mr\.?|Mrs\.?|Ms\.?|Prof\.?)\s+", "", text)
    # "Archontoulis, Sotirios" -> "Sotirios Archontoulis"; also handle trailing periods
    # like "Scott, Paul M." and "Jr." suffixes.
    if "," in text:
        bits = [b.strip() for b in text.split(",", 1)]
        if len(bits) == 2 and bits[0] and bits[1]:
            # avoid re-ordering if the second segment looks like a role (e.g. "Ph.D.")
            if not re.match(r"^(Ph\.|M\.|B\.|Sc\.|Dr\.|Jr\.|Sr\.|II|III|IV)$", bits[1].rstrip(".")):
                text = f"{bits[1]} {bits[0]}"
    # Collapse whitespace, drop trailing punctuation
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    return text


def html_unescape(s: str) -> str:
    import html as _html
    return _html.unescape(s)


def _agron_enrich_from_profile(client: httpx.Client, rec: Faculty) -> None:
    if not rec.profile_url:
        return
    try:
        r = client.get(rec.profile_url)
        if r.status_code != 200:
            return
        soup = BeautifulSoup(r.text, "lxml")
        main = soup.find("main") or soup
        text = main.get_text("\n", strip=True)
        # Email
        m = re.search(r"Email:\s*([A-Za-z0-9_.+-]+@iastate\.edu)", text)
        if m:
            rec.email = m.group(1)
        else:
            m2 = re.search(r"([A-Za-z0-9_.+-]+@iastate\.edu)", text)
            if m2:
                rec.email = m2.group(1)
        # Title extraction strategy:
        # The Agron profile layout emits the person's title(s) first, then a
        # short name block in this order: "Dr." -> first-name -> (optional
        # middle initial) -> last-name -> "Office:". We collect lines until we
        # hit a line that matches the last name, stopping the loop there.
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

        def _norm_name_for_cmp(s: str) -> str:
            # Flatten curly quotes, unicode spaces, hyphens to plain ASCII, lower.
            s = s.replace("\u2019", "'").replace("\u2018", "'")
            s = s.replace("\u2013", "-").replace("\u2014", "-")
            s = re.sub(r"[^A-Za-z]+", " ", s).strip().lower()
            return s

        name_tokens = {
            t
            for t in _norm_name_for_cmp(rec.name or "").split()
            if t
        }
        last_name = ""
        if rec.name:
            parts = rec.name.split()
            if parts:
                last_name = _norm_name_for_cmp(parts[-1])
        title_lines: list[str] = []
        for ln in lines[:25]:
            s = ln.strip()
            if not s:
                continue
            ls = s.lower()
            if s.startswith(("Office", "Phone", "Email", "Fax", "Skills", "Address", "About")):
                break
            # Last-name line ends the title block (use normalised compare).
            norm_s = _norm_name_for_cmp(s)
            if last_name and norm_s == last_name:
                break
            if s in ("Dr.", "Dr", "Mr.", "Ms.", "Mrs.", "Prof."):
                continue
            # Skip single-letter middle-initial lines like "G", "M", "G.", "M."
            if re.fullmatch(r"[A-Z]\.?", s):
                continue
            # Skip lines that are just chunks of the person's name (first name,
            # "C. Lee", "A. Susana", "DeVries Gelder", "O'Rourke", etc.)
            plain_tokens = set(norm_s.split()) if norm_s else set()
            if plain_tokens and plain_tokens.issubset(name_tokens):
                continue
            # Avoid degrees / nav / social-bar text
            if re.match(r"^(B\.|M\.|Ph\.|Bachelor|Master|Doctor)", s):
                break
            if s.lower() in {"twitter", "facebook", "linkedin", "instagram", "youtube", "people", "publications", "selected publications"}:
                continue
            title_lines.append(s)
            if len(title_lines) >= 4:
                break
        cleaned_title = " / ".join(title_lines)[:400]
        rec.title = cleaned_title or "Faculty"
        rec.is_teaching_faculty = looks_like_teaching_faculty(rec.title)
        if not rec.photo_url:
            img = main.find("img", src=re.compile(r"/files/.*\.(jpe?g|png)", re.I))
            if img:
                rec.photo_url = img.get("src", "")
    except Exception as e:  # noqa: BLE001
        print(f"[agron] profile enrich fail {rec.profile_url}: {e}", file=sys.stderr)
    finally:
        time.sleep(POLITE_DELAY_SEC)


# -----------------------------------------------------------------------------
# ABE / CBE / CCEE: engineering.iastate.edu REST
# -----------------------------------------------------------------------------

ENG_REST = "https://www.engineering.iastate.edu/people/wp-json/wp/v2"

# department taxonomy ids (verified live)
ENG_DEPT_IDS = {
    "Agricultural and Biosystems Engineering": 10,
    "Chemical and Biological Engineering": 5,
    "Civil, Construction and Environmental Engineering": 8,
}
# Sub-group taxonomy ids for strict-faculty inclusion (emeritus + regular).
# Values are sets of ids that qualify the person as a faculty member.
ENG_FACULTY_SUBGROUPS = {
    10: {1072, 1915, 1073},  # ABE Faculty, ABE Emeritus, ABE Adjunct/Courtesy
    5: {1075, 1074, 1216, 1076},  # CBE Professors, CBE Chair, CBE Emeritus, CBE Courtesy
    8: {1081, 1080, 1217, 1082, 1083},  # CCEE Faculty, Chair, Emeritus, Adjunct, Affiliate
}


def scrape_eng_missing(client: httpx.Client) -> list[Faculty]:
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    for dept_name, dept_id in ENG_DEPT_IDS.items():
        faculty_sub_ids = ENG_FACULTY_SUBGROUPS[dept_id]
        page = 1
        while True:
            params = {
                "department": dept_id,
                "per_page": 100,
                "page": page,
                "_fields": "id,slug,title,link,department,email,isu_title,user_image,firstname,lastname,isu_office,phone_number,info,interest,key_research_area,nickname,middle_name",
            }
            r = client.get(f"{ENG_REST}/profile", params=params)
            if r.status_code == 400:
                break
            r.raise_for_status()
            batch = r.json()
            if not batch:
                break
            for p in batch:
                # filter: only keep if this person has at least one of the faculty-subgroup IDs
                dept_terms = set(p.get("department", []) or [])
                if not (dept_terms & faculty_sub_ids):
                    continue
                rec = _eng_person_to_faculty(p, dept_name)
                if rec is None:
                    continue
                # Additional filter: drop obvious staff titles that are
                # incorrectly tagged into the "Adjunct/Courtesy Faculty"
                # subgroup by the engineering CMS.
                if rec.title and not is_faculty_title(rec.title):
                    continue
                if rec.id in seen_ids:
                    continue
                seen_ids.add(rec.id)
                out.append(rec)
            total_pages = int(r.headers.get("X-WP-TotalPages") or 1)
            total_rec = int(r.headers.get("X-WP-Total") or len(batch))
            print(
                f"[engineering] {dept_name} page {page}/{total_pages} "
                f"got {len(batch)} (cumulative faculty kept {len(out)}/{total_rec} dept-records)",
                flush=True,
            )
            if page >= total_pages:
                break
            page += 1
            time.sleep(POLITE_DELAY_SEC)
    return out


def _eng_person_to_faculty(p: dict[str, Any], dept_name: str) -> Faculty | None:
    first = (p.get("firstname") or "").strip()
    last = (p.get("lastname") or "").strip()
    middle = (p.get("middle_name") or "").strip()
    if first and last:
        name = " ".join(x for x in (first, middle, last) if x)
    else:
        # fallback to rendered title but strip any "[TOKEN]" suffix
        raw_title = p.get("title", {}).get("rendered", "") or ""
        raw_title = re.sub(r"\s*\[[A-Z &]+\]\s*", " ",raw_title).strip()
        name = _clean_name_from_title(raw_title)
    if not name:
        return None
    # isu_title occasionally carries a "[A&BE]" style department token; strip it
    isu_title_raw = (p.get("isu_title") or "").strip()
    isu_title = re.sub(r"\s*\[[A-Z &]+\]\s*", " ",isu_title_raw).strip()
    email = (p.get("email") or "").strip()
    link = (p.get("link") or "").strip()
    # user_image is a WP attachment dict, the direct URL lives in guid
    photo = ""
    ui = p.get("user_image")
    if isinstance(ui, dict):
        photo = (ui.get("guid") or ui.get("url") or ui.get("source_url") or "").strip()
    elif isinstance(ui, str):
        photo = ui.strip()
    return Faculty(
        id=slugify(name),
        name=name,
        title=isu_title or "Faculty",
        department=dept_name,
        college=COE,  # ABE appears in both; per task spec, tag as Engineering
        email=email,
        profile_url=link,
        photo_url=photo,
        research_interests=[],
        courses_taught=[],
        is_teaching_faculty=looks_like_teaching_faculty(isu_title),
        source_url=link or "https://www.engineering.iastate.edu/people/",
    )


# -----------------------------------------------------------------------------
# Horticulture: WebFetch-produced snapshot, fallback to catalog
# -----------------------------------------------------------------------------


def load_hort_snapshot() -> list[Faculty]:
    """Load the hand-fed Horticulture snapshot JSON produced via WebFetch.

    The snapshot file, if present, is a JSON list with objects
    {name, title, email, profile_url, photo_url}. All rows become
    Horticulture / CALS faculty.
    """
    if not HORT_SNAPSHOT_JSON.exists():
        print("[hort] snapshot not found; will fall back to catalog", flush=True)
        return []
    data = json.loads(HORT_SNAPSHOT_JSON.read_text(encoding="utf-8"))
    out: list[Faculty] = []
    seen_ids: set[str] = set()
    for row in data:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        title = (row.get("title") or "Faculty").strip()
        rec = Faculty(
            id=slugify(name),
            name=name,
            title=title,
            department="Horticulture",
            college=CALS,
            email=(row.get("email") or "").strip(),
            profile_url=(row.get("profile_url") or "").strip(),
            photo_url=(row.get("photo_url") or "").strip(),
            is_teaching_faculty=looks_like_teaching_faculty(title),
            source_url="https://www.hort.iastate.edu/directory-section/faculty/",
        )
        if rec.id in seen_ids:
            continue
        seen_ids.add(rec.id)
        out.append(rec)
    print(f"[hort] loaded {len(out)} from snapshot", flush=True)
    return out


def scrape_hort_from_catalog(catalog_html: str) -> list[Faculty]:
    """Fallback: parse Horticulture entries directly from the catalog HTML."""
    temp = parse_catalog(catalog_html, {"Horticulture"})
    # rewire college / source for these
    for r in temp:
        r.college = CALS
        r.source_url = "https://www.hort.iastate.edu/directory-section/faculty/"
    return temp


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------


def dedupe_by_id(rows: Iterable[Faculty]) -> list[Faculty]:
    """Collapse duplicates that share the same slug id.

    When two records collide, prefer the one whose department matches the
    department where the record was sourced from a dedicated department site
    (Horticulture snapshot, Agronomy REST, engineering REST) over a catalog
    row. Catalog rows are fallbacks and should lose to live dept data.
    Ties fall back to "richness" (more populated fields wins).
    """
    seen: dict[str, Faculty] = {}
    order: list[str] = []
    for r in rows:
        if r.id in seen:
            existing = seen[r.id]
            if _preference_rank(r) > _preference_rank(existing):
                # new record wins; backfill any missing fields from the existing one
                for fld in ("email", "title", "photo_url", "profile_url"):
                    if not getattr(r, fld) and getattr(existing, fld):
                        setattr(r, fld, getattr(existing, fld))
                seen[r.id] = r
            else:
                for fld in ("email", "title", "photo_url", "profile_url"):
                    if not getattr(existing, fld) and getattr(r, fld):
                        setattr(existing, fld, getattr(r, fld))
        else:
            seen[r.id] = r
            order.append(r.id)
    return [seen[i] for i in order]


def _preference_rank(r: Faculty) -> int:
    """Higher wins. Live dept-site sources beat catalog fallback sources."""
    score = _richness(r)
    source_bonus = {
        # dedicated department HTML/REST pages (authoritative)
        "https://www.hort.iastate.edu/directory-section/faculty/": 100,
        "https://www.agron.iastate.edu/directory/": 50,
    }
    score += source_bonus.get(r.source_url, 0)
    if "engineering.iastate.edu" in r.source_url:
        score += 75
    return score


def _richness(r: Faculty) -> int:
    score = 0
    for fld in ("email", "title", "photo_url", "profile_url"):
        if getattr(r, fld):
            score += 1
    if r.title and r.title != "Faculty":
        score += 1
    return score


def write_json(path: Path, rows: list[Faculty]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = [asdict(r) for r in rows]
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"[write] {path} ({len(rows)} rows)", flush=True)


def main() -> int:
    cals_rows: list[Faculty] = []
    coe_rows: list[Faculty] = []
    stats: dict[str, int] = {}

    with httpx.Client(headers=HEADERS, timeout=TIMEOUT, follow_redirects=True) as client:
        # --- Catalog-based CALS depts (AGEDS, ANS, NREM, PPEM) -----------------
        catalog_html = fetch_catalog_html(client)
        catalog_rows = parse_catalog(catalog_html, TARGET_CATALOG_DEPTS)
        for dept in TARGET_CATALOG_DEPTS:
            c = sum(1 for r in catalog_rows if r.department == dept)
            stats[dept] = c
            print(f"[catalog] {dept}: {c}", flush=True)
        cals_rows.extend(catalog_rows)

        # --- Agronomy via WP REST ---------------------------------------------
        try:
            agron_rows = scrape_agron(client)
        except Exception as e:  # noqa: BLE001
            print(f"[agron] scrape failed: {e}", file=sys.stderr)
            agron_rows = []
        if not agron_rows:
            # fallback: catalog
            print("[agron] falling back to catalog parse", flush=True)
            fb = parse_catalog(catalog_html, {"Agronomy"})
            for r in fb:
                r.college = CALS
                r.source_url = "https://www.agron.iastate.edu/directory/"
            agron_rows = fb
        stats["Agronomy"] = len(agron_rows)
        cals_rows.extend(agron_rows)
        print(f"[agron] total: {len(agron_rows)}", flush=True)

        # --- Horticulture via WebFetch snapshot, fallback catalog -------------
        hort_rows = load_hort_snapshot()
        if not hort_rows:
            hort_rows = scrape_hort_from_catalog(catalog_html)
        stats["Horticulture"] = len(hort_rows)
        cals_rows.extend(hort_rows)
        print(f"[hort] total: {len(hort_rows)}", flush=True)

        # --- COE missing depts via engineering REST ----------------------------
        try:
            eng_rows = scrape_eng_missing(client)
        except Exception as e:  # noqa: BLE001
            print(f"[engineering] scrape failed: {e}", file=sys.stderr)
            eng_rows = []
        coe_rows.extend(eng_rows)
        for dept in ENG_DEPT_IDS:
            c = sum(1 for r in eng_rows if r.department == dept)
            stats[dept] = c
            print(f"[engineering] {dept}: {c}", flush=True)

    # --- Dedup within each output file ----------------------------------------
    cals_rows = dedupe_by_id(cals_rows)
    coe_rows = dedupe_by_id(coe_rows)

    write_json(CALS_OUT, cals_rows)
    write_json(COE_OUT, coe_rows)

    # --- Final report ---------------------------------------------------------
    _write_report(stats, cals_rows, coe_rows)
    return 0


def _write_report(stats: dict[str, int], cals_rows: list[Faculty], coe_rows: list[Faculty]) -> None:
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    cals_total = len(cals_rows)
    coe_total = len(coe_rows)
    email_ok_cals = sum(1 for r in cals_rows if r.email)
    email_ok_coe = sum(1 for r in coe_rows if r.email)
    photo_ok_cals = sum(1 for r in cals_rows if r.photo_url)
    photo_ok_coe = sum(1 for r in coe_rows if r.photo_url)

    lines = []
    lines.append("# CALS + COE-missing Faculty Scrape Report")
    lines.append("")
    lines.append(f"Generated by `backend/scripts/scrape_cals_coe_missing.py`.")
    lines.append("")
    lines.append("## Output files")
    lines.append("")
    lines.append(f"- `backend/data/cals_v2_faculty.json` — **{cals_total}** rows")
    lines.append(f"- `backend/data/coe_missing_faculty.json` — **{coe_total}** rows")
    lines.append("")
    lines.append("## Per-department counts")
    lines.append("")
    lines.append("### CALS")
    lines.append("")
    lines.append("| Department | Rows | Source |")
    lines.append("|---|---:|---|")
    cals_sources = {
        "Agricultural Education and Studies": "catalog.iastate.edu/faculty/ (dept subdomain firewalled)",
        "Agronomy": "agron.iastate.edu WP REST + profile HTML",
        "Animal Science": "catalog.iastate.edu/faculty/ (dept subdomain firewalled)",
        "Horticulture": "hort.iastate.edu via WebFetch snapshot",
        "Natural Resource Ecology and Management": "catalog.iastate.edu/faculty/ (dept subdomain firewalled)",
        "Plant Pathology, Entomology and Microbiology": "catalog.iastate.edu/faculty/ (dept subdomain firewalled)",
    }
    for dept, src in cals_sources.items():
        c = sum(1 for r in cals_rows if r.department == dept)
        lines.append(f"| {dept} | {c} | {src} |")
    lines.append("")
    lines.append("### COE (missing three)")
    lines.append("")
    lines.append("| Department | Rows | Source |")
    lines.append("|---|---:|---|")
    for dept in ENG_DEPT_IDS:
        c = sum(1 for r in coe_rows if r.department == dept)
        lines.append(f"| {dept} | {c} | engineering.iastate.edu REST |")
    lines.append("")
    lines.append("## Data quality")
    lines.append("")
    lines.append(f"- CALS rows with email: {email_ok_cals}/{cals_total}")
    lines.append(f"- CALS rows with photo: {photo_ok_cals}/{cals_total}")
    lines.append(f"- COE rows with email:  {email_ok_coe}/{coe_total}")
    lines.append(f"- COE rows with photo:  {photo_ok_coe}/{coe_total}")
    lines.append("")
    lines.append("## Data sources")
    lines.append("")
    lines.append(
        "- **Agronomy**: WP REST `/wp-json/wp/v2/people?people-category={227,250,289}` "
        "(Faculty, Emeritus, Extension), per-profile HTML for title/email/photo."
    )
    lines.append(
        "- **Horticulture**: WebFetch-generated snapshot `scripts/_hort_webfetch_snapshot.json` "
        "(Cloudflare WAF blocks our runner IP). Fallback: `catalog.iastate.edu/faculty/`."
    )
    lines.append(
        "- **Agricultural Education and Studies, Animal Science, Natural Resource "
        "Ecology and Management, Plant Pathology, Entomology and Microbiology**: "
        "parsed from `catalog.iastate.edu/faculty/` - those department subdomains "
        "route to 129.186.90.87 which is unreachable from our network; catalog is "
        "the authoritative mirror."
    )
    lines.append(
        "- **ABE / CBE / CCEE**: `engineering.iastate.edu/people/wp-json/wp/v2/profile`, "
        "filtered by the `department` taxonomy and then by the faculty subgroup ids "
        "(ABE Faculty / Emeritus / Courtesy, etc.)."
    )
    lines.append("")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[report] wrote {REPORT}", flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
