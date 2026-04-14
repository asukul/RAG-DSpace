"""Scrape Iowa State University College of Veterinary Medicine (CVM) faculty.

Covers all 5 CVM departments:
  - Biomedical Sciences (BMS)
  - Veterinary Clinical Sciences (VCS)
  - Veterinary Diagnostic and Production Animal Medicine (VDPAM)
  - Veterinary Microbiology and Preventive Medicine (VMPM)
  - Veterinary Pathology (VPATH)

Every CVM person has an individual profile page at
  https://vetmed.iastate.edu/directory/pub/info/<id>
which carries the authoritative title (e.g., "Associate Professor").

Two directory-page layouts are handled:
  A) Classic HTML table with class "td_field_last_name" (BMS, VDPAM, VMPM, VPATH).
     Sections are separated by <h2>Faculty</h2> / <h2>Staff</h2> and we split
     on the byte offset of those headings.
  B) Card grid with class "faculty-staff-card" (VCS). We keep a card only
     if its body title matches a faculty rank pattern; everything else
     (Resident, Intern, Veterinary Technician, Clerk, Administrative
     Assistant, etc.) is skipped.

Output: backend/data/vetmed_faculty.json with the schema used by the other
college files, plus the richer fields requested for this scrape
(research_interests, courses_taught, is_teaching_faculty, source_url).
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup

BASE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
OUT_PATH = BASE / "data" / "vetmed_faculty.json"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
HTTP_TIMEOUT = 30.0
PROFILE_SLEEP = 0.25  # 250ms between profile-page fetches
COLLEGE = "College of Veterinary Medicine"

DEPARTMENTS: list[dict] = [
    {
        "key": "BMS",
        "name": "Biomedical Sciences",
        "url": "https://vetmed.iastate.edu/bms/about/who-we-are/faculty-staff/",
        "layout": "table",
    },
    {
        "key": "VCS",
        "name": "Veterinary Clinical Sciences",
        "url": "https://vetmed.iastate.edu/vcs/directories/faculty-staff-directory/",
        "layout": "cards",
    },
    {
        "key": "VDPAM",
        "name": "Veterinary Diagnostic and Production Animal Medicine",
        "url": "https://vetmed.iastate.edu/vdpam/faculty-staff/faculty-directory",
        "layout": "table",
    },
    {
        "key": "VMPM",
        "name": "Veterinary Microbiology and Preventive Medicine",
        "url": "https://vetmed.iastate.edu/vmpm/directories/vmpm-faculty/",
        "layout": "table",
    },
    {
        "key": "VPATH",
        "name": "Veterinary Pathology",
        "url": "https://vetmed.iastate.edu/vpath/directories/faculty-staff/",
        "layout": "table",
    },
]

# Section headings treated as staff (not faculty) when splitting tables
STAFF_HEADINGS = {"staff"}
# Section headings treated as faculty
FACULTY_HEADINGS = {"faculty", "administration"}

# Title keywords that mark a VCS card as faculty
FACULTY_TITLE_PATTERNS = [
    re.compile(r"\bprofessor\b", re.IGNORECASE),            # Professor / Associate Professor / Clinical Prof / Teaching Prof / Morrill Prof
    re.compile(r"\bchair\b", re.IGNORECASE),                 # Department Chair
    re.compile(r"\blecturer\b", re.IGNORECASE),
    re.compile(r"\binstructor\b", re.IGNORECASE),
    re.compile(r"\bdean\b", re.IGNORECASE),                  # Associate Dean etc (faculty admin)
    re.compile(r"\bclinician\b", re.IGNORECASE),
    re.compile(r"\bfaculty\b", re.IGNORECASE),
]

# Title keywords that explicitly exclude a card (match ANY -> skip)
NON_FACULTY_TITLE_PATTERNS = [
    re.compile(r"\bresident\b", re.IGNORECASE),
    re.compile(r"\bintern\b", re.IGNORECASE),
    re.compile(r"\btechnician\b", re.IGNORECASE),
    re.compile(r"\bclerk\b", re.IGNORECASE),
    re.compile(r"\badministrative assistant\b", re.IGNORECASE),
    re.compile(r"\bsecretary\b", re.IGNORECASE),
    re.compile(r"\bspecialist\b", re.IGNORECASE),             # Program Specialist, Student Services Specialist
    re.compile(r"\btechnologist\b", re.IGNORECASE),
    re.compile(r"\bsonographer\b", re.IGNORECASE),
    re.compile(r"\btherapist\b", re.IGNORECASE),
    re.compile(r"\bcaretaker\b", re.IGNORECASE),
    re.compile(r"\bmanager\b", re.IGNORECASE),                # Manager Clinical Support
    re.compile(r"\blocum\b", re.IGNORECASE),                  # Locum Tenen
    re.compile(r"\bbudget\b", re.IGNORECASE),
    re.compile(r"\bfinance\b", re.IGNORECASE),
    re.compile(r"\bassistant iii?\b", re.IGNORECASE),
    re.compile(r"\bagricultural assistant\b", re.IGNORECASE),
]


@dataclass
class FacultyRow:
    id: str
    name: str
    title: str
    department: str
    college: str
    email: str
    profile_url: str
    photo_url: str | None
    research_interests: list[str] = field(default_factory=list)
    courses_taught: list[str] = field(default_factory=list)
    is_teaching_faculty: bool = False
    source_url: str = ""


# ---------- helpers ----------

def slugify(name: str) -> str:
    """Kebab-case slug for stable IDs. e.g. 'Joshua R. Beck' -> 'joshua-r-beck'."""
    n = unicodedata.normalize("NFKD", name)
    n = n.encode("ascii", "ignore").decode("ascii")
    n = n.lower()
    n = re.sub(r"[^a-z0-9]+", "-", n)
    return n.strip("-")


def http_get(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return resp.read().decode("utf-8", errors="ignore")


def normalize_name(first: str, last: str) -> str:
    """Combine first/last into 'First Last' (profile pages give 'First M Last')."""
    first = re.sub(r"\s+", " ", first.strip())
    last = re.sub(r"\s+", " ", last.strip())
    return f"{first} {last}".strip()


def is_faculty_title(title: str) -> bool:
    """Card-layout (VCS) filter: title must have a faculty token to pass.

    Faculty tokens win over non-faculty tokens so that e.g. a 'Lecturer ...
    Specialist' is still counted as faculty.
    """
    if not title:
        return False
    if any(p.search(title) for p in FACULTY_TITLE_PATTERNS):
        return True
    return False


def is_clearly_non_faculty(title: str) -> bool:
    """Table-layout (BMS/VDPAM/VMPM/VPATH) safety-net: only filter out
    profiles whose title has a non-faculty token AND no faculty token."""
    if not title:
        return False
    if any(p.search(title) for p in FACULTY_TITLE_PATTERNS):
        return False
    return any(p.search(title) for p in NON_FACULTY_TITLE_PATTERNS)


# ---------- directory-page parsers ----------

def parse_table_layout(html: str, dept: dict) -> list[dict]:
    """Parse table-style directories.

    Two column schemas exist across CVM:
      A) BMS: Picture | Last | First | Department | Phone | Email | Room
         - anchor text is last name only; first name in td_field_first_name;
           no per-row title cell, so we must hit the profile page.
      B) VDPAM/VMPM/VPATH: Picture | Full-name+degrees | Professional Title |
                           Phone | Email | Room
         - anchor text is 'First Last' (+ '<br>degrees'); title is already
           present in td_field_professional_title, so profile-page fetch is
           still nice-to-have but not required.

    We locate <h2> section headings and keep only rows that fall under a
    heading considered 'faculty-ish' (Faculty, Administration). Rows under
    'Staff' headings are skipped. If there are no Faculty/Staff headings
    at all (VMPM), everything is treated as faculty.
    """
    # Find h2 section boundaries (byte offset + lowercase text)
    heading_spans: list[tuple[int, str]] = []
    for m in re.finditer(r"<h2[^>]*>([^<]+)</h2>", html):
        heading_spans.append((m.start(), m.group(1).strip().lower()))
    # Check if there are any faculty/staff-type splits at all
    has_fac_staff_split = any(
        t in FACULTY_HEADINGS or t in STAFF_HEADINGS for _, t in heading_spans
    )

    def section_for(pos: int) -> str:
        current = ""
        for start, title in heading_spans:
            if start < pos:
                current = title
            else:
                break
        return current

    results: list[dict] = []
    soup = BeautifulSoup(html, "lxml")

    # Iterate in document order so we can compute each row's byte offset.
    for tr in soup.find_all("tr"):
        last_td = tr.find("td", class_=re.compile(r"\btd_field_last_name\b"))
        if not last_td:
            continue
        anchor = last_td.find("a", href=True)
        if not anchor:
            continue
        href = anchor["href"]

        # Decide the row's section using the byte offset of this specific href.
        # hrefs are unique per person so `.find(href)` is safe.
        pos = html.find(href)
        section = section_for(pos) if heading_spans else ""

        # If this page splits faculty vs staff, keep only faculty-ish sections.
        if has_fac_staff_split:
            if section in STAFF_HEADINGS:
                continue
            if section not in FACULTY_HEADINGS:
                # row lives outside any Faculty/Administration section — skip
                continue
        # Else: no split at all (e.g. VMPM) — keep all rows.

        # --- Name extraction ---
        # Schema A (BMS): anchor text is last name, first name in first_td.
        # Schema B (VDPAM/VMPM/VPATH): anchor text is 'First Last' plus
        # optional '<br>degrees'. Use the first text line before any <br>.
        first_td = tr.find("td", class_=re.compile(r"\btd_field_first_name\b"))
        title_td = tr.find("td", class_=re.compile(r"\btd_field_professional_title\b"))

        # Get anchor's text line-by-line: BeautifulSoup collapses <br> to newlines
        # when separator='\n'
        anchor_text_lines = [
            ln.strip() for ln in anchor.get_text("\n", strip=True).split("\n") if ln.strip()
        ]
        if not anchor_text_lines:
            continue
        primary_line = anchor_text_lines[0]

        if first_td:
            # Schema A
            last_name = primary_line
            first_name = first_td.get_text(" ", strip=True)
            name = normalize_name(first_name, last_name)
        else:
            # Schema B: first line already holds 'First Last'. Strip any trailing
            # comma-separated credentials so we keep a clean display name.
            name = re.sub(r"\s+", " ", primary_line).strip()
            # If the name has comma-separated degrees ("Bryan Bellaire, PhD"),
            # drop those. But NOT if there's no comma and degrees are just
            # space-separated capitals — that's handled by the profile page.

        if not name:
            continue

        profile_url = href if href.startswith("http") else f"https://vetmed.iastate.edu{href}"

        # --- Email ---
        email = ""
        email_td = tr.find("td", class_=re.compile(r"\btd_field_email\b"))
        if email_td:
            a = email_td.find("a", href=True)
            if a and a["href"].lower().startswith("mailto:"):
                email = a["href"][7:].strip()
            else:
                email = email_td.get_text(strip=True)

        # --- Photo ---
        photo_url = None
        pic_td = tr.find("td", class_=re.compile(r"\btd_picture\b"))
        if pic_td:
            img = pic_td.find("img", src=True)
            if img:
                photo_url = img["src"]

        # --- Directory title (schema B only) ---
        directory_title = ""
        if title_td:
            directory_title = title_td.get_text(" ", strip=True)

        results.append({
            "name": name,
            "profile_url": profile_url,
            "email": email,
            "photo_url": photo_url,
            "directory_title": directory_title,
        })
    return results


def parse_card_layout(html: str, dept: dict) -> list[dict]:
    """Parse VCS card-style directory.

    Each card has:
      .faculty-staff-card__content-title   -> <a>Name, credentials*</a>
      .faculty-staff-card__content-body    -> title (e.g. 'Clinical Assistant Professor')
      .faculty-staff-card__content-contact -> mailto link, etc
    We filter out non-faculty by body title, and also strip trailing
    credential letters from the displayed name (', DVM, MS, Diplomate...').
    """
    soup = BeautifulSoup(html, "lxml")
    results: list[dict] = []

    for card in soup.find_all(class_="faculty-staff-card"):
        title_p = card.find(class_="faculty-staff-card__content-title")
        body_p = card.find(class_="faculty-staff-card__content-body")
        if not title_p:
            continue

        anchor = title_p.find("a", href=True)
        if not anchor:
            continue

        raw_name = anchor.get_text(" ", strip=True)
        # Drop trailing asterisks and arrow icon text
        raw_name = raw_name.replace("*", "").strip()
        # Strip trailing credentials after a comma
        name = raw_name.split(",")[0].strip()
        if not name:
            continue

        title = (body_p.get_text(" ", strip=True) if body_p else "").strip()
        if not is_faculty_title(title):
            continue

        profile_url = anchor["href"]
        if not profile_url.startswith("http"):
            profile_url = f"https://vetmed.iastate.edu{profile_url}"

        email = ""
        contact = card.find(class_="faculty-staff-card__content-contact")
        if contact:
            for a in contact.find_all("a", href=True):
                if a["href"].lower().startswith("mailto:"):
                    email = a["href"][7:].strip()
                    break

        photo_url = None
        media = card.find(class_="faculty-staff-card__media")
        if media:
            img = media.find("img", src=True)
            if img:
                photo_url = img["src"]

        results.append({
            "name": name,
            "profile_url": profile_url,
            "email": email,
            "photo_url": photo_url,
            "directory_title": title,  # VCS cards already have the title
        })
    return results


# ---------- profile-page parser ----------

# Some profiles pack multi-line titles inside a single <i> tag using <br/>
# separators, e.g. <i>Associate Dean<br/>Professor<br/>Endowed Chair</i>.
# Grab the full inner text of that <i>.
_PROFILE_TITLE_RE = re.compile(
    r"<p>\s*<i>(.+?)</i>", re.IGNORECASE | re.DOTALL
)


def parse_profile_page(html: str) -> dict:
    """Extract title, full name, photo from an individual profile page.

    The relevant chunk is a <p> block containing:
      <p><i>Associate Professor</i><br>
         <a href="/bms">Biomedical Sciences</a><br>
         <a href="mailto:...">email</a><br>...
    """
    out: dict = {"title": "", "full_name": "", "photo_url": None}

    # Title: italicized text right after the profile photo
    m = _PROFILE_TITLE_RE.search(html)
    if m:
        raw = m.group(1)
        # Replace <br> variants with a separator and strip inner tags
        raw = re.sub(r"<br\s*/?>", " | ", raw, flags=re.IGNORECASE)
        raw = re.sub(r"<[^>]+>", "", raw)
        raw = re.sub(r"\s+", " ", raw).strip(" |")
        out["title"] = raw.strip()

    # Full name: <h1> or page <title>. Prefer <h1>.
    soup = BeautifulSoup(html, "lxml")
    h1 = soup.find("h1")
    if h1:
        out["full_name"] = h1.get_text(" ", strip=True)
    else:
        t = soup.find("title")
        if t:
            txt = t.get_text(" ", strip=True)
            txt = re.sub(r"\s*-\s*CVM Directory\s*$", "", txt)
            out["full_name"] = txt

    # Photo from the directory image path
    img = soup.find("img", src=re.compile(r"/directory/pub/images/"))
    if img:
        src = img.get("src", "")
        if src:
            if not src.startswith("http"):
                src = f"https://vetmed.iastate.edu{src}"
            out["photo_url"] = src

    return out


# ---------- main pipeline ----------

def scrape_department(dept: dict, errors: list[str]) -> list[FacultyRow]:
    print(f"\n[{dept['key']}] fetching {dept['url']}")
    try:
        html = http_get(dept["url"])
    except Exception as e:
        errors.append(f"{dept['key']} directory fetch failed: {e}")
        print(f"  FAIL: {e}")
        return []

    if dept["layout"] == "table":
        listings = parse_table_layout(html, dept)
    else:
        listings = parse_card_layout(html, dept)

    print(f"[{dept['key']}] directory listings: {len(listings)}")

    rows: list[FacultyRow] = []
    seen_emails: set[str] = set()
    seen_slugs: set[str] = set()

    for i, entry in enumerate(listings):
        profile_url = entry["profile_url"]
        # Fetch profile page for authoritative title + better name
        title = entry.get("directory_title", "") or ""
        full_name = entry["name"]
        photo_url = entry.get("photo_url")
        email = entry.get("email", "")

        try:
            prof_html = http_get(profile_url)
            prof = parse_profile_page(prof_html)
            if prof.get("title"):
                title = prof["title"]
            if prof.get("full_name"):
                full_name = prof["full_name"]
            if prof.get("photo_url"):
                photo_url = prof["photo_url"]
        except Exception as e:
            errors.append(f"{dept['key']} profile {profile_url} failed: {e}")
            print(f"  profile FAIL {profile_url}: {e}")
        finally:
            time.sleep(PROFILE_SLEEP)

        # For table-layout sections we didn't pre-filter on title (the HTML
        # already splits faculty vs staff via <h2>). But individual profile
        # titles are more specific, so also respect the non-faculty patterns
        # as a safety net, while keeping everything with at least one
        # faculty-ish token.
        if dept["layout"] == "table":
            if is_clearly_non_faculty(title):
                print(f"  skip non-faculty by title: {full_name} - {title!r}")
                continue
            # When table section was "faculty" but the profile has no title,
            # keep the row anyway (some emeriti list only a degree line).

        # For VCS, we already filtered. Re-check in case profile-page title changed.
        if dept["layout"] == "cards":
            if title and not is_faculty_title(title):
                print(f"  skip non-faculty (post profile): {full_name} — {title!r}")
                continue

        slug = slugify(full_name)
        if not slug:
            continue
        # Dedupe within department; prefer email if present
        dedupe_key = email.lower() if email else slug
        if email and email.lower() in seen_emails:
            continue
        if slug in seen_slugs:
            continue
        seen_emails.add(email.lower() if email else "")
        seen_slugs.add(slug)

        rows.append(FacultyRow(
            id=slug,
            name=full_name,
            title=title or "Faculty",
            department=dept["name"],
            college=COLLEGE,
            email=email,
            profile_url=profile_url,
            photo_url=photo_url,
            research_interests=[],
            courses_taught=[],
            is_teaching_faculty=False,
            source_url=dept["url"],
        ))
        if (i + 1) % 25 == 0:
            print(f"  ... processed {i + 1}/{len(listings)}")

    print(f"[{dept['key']}] kept {len(rows)} faculty")
    return rows


def main() -> dict:
    errors: list[str] = []
    all_rows: list[FacultyRow] = []
    per_dept_counts: dict[str, int] = {}

    for dept in DEPARTMENTS:
        rows = scrape_department(dept, errors)
        per_dept_counts[dept["key"]] = len(rows)
        all_rows.extend(rows)

    # Global dedupe across departments (joint appointments) — keep first seen.
    unique: dict[str, FacultyRow] = {}
    for r in all_rows:
        key = r.email.lower() if r.email else r.id
        if key not in unique:
            unique[key] = r
    deduped = list(unique.values())
    dup_count = len(all_rows) - len(deduped)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUT_PATH.open("w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in deduped], f, indent=2, ensure_ascii=False)

    print("\n=== SUMMARY ===")
    for dept in DEPARTMENTS:
        print(f"  {dept['key']:<6} {per_dept_counts[dept['key']]:>4}  {dept['name']}")
    print(f"  TOTAL (pre-dedupe): {len(all_rows)}")
    print(f"  TOTAL (post-dedupe): {len(deduped)}  (removed {dup_count} duplicates)")
    print(f"  errors: {len(errors)}")
    print(f"  wrote: {OUT_PATH}")

    return {
        "per_dept": per_dept_counts,
        "total_pre": len(all_rows),
        "total_post": len(deduped),
        "dup_removed": dup_count,
        "errors": errors,
        "out_path": str(OUT_PATH),
    }


if __name__ == "__main__":
    main()
