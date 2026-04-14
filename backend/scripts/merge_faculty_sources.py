"""
Merge all per-college faculty JSON files into a single deduplicated faculty.json.

Resolution rules (in order of priority):
1. `verified_faculty_data.VERIFIED_FACULTY_DATA` always wins. Verified rows
   are merged in first and never overwritten.
2. Then per-college files (in priority order). For each new row, dedupe
   against the existing accumulated set:
   - PRIMARY KEY: lowercased email (when both rows have one)
   - SECONDARY KEY: name slug + same college
   - Tertiary: name slug + same dept
   When two rows merge, prefer the one with more populated fields
   (research_interests, photo_url, profile_url, title).
3. Drop obviously bad rows: empty name, names that look like nav labels
   ("Apply", "Visit", "Request information"), or lacking any iastate URL.

Run:
    cd backend
    python scripts/merge_faculty_sources.py            # write faculty.json
    python scripts/merge_faculty_sources.py --dry-run  # just print stats
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from typing import Dict, List, Optional

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
DATA = os.path.join(BACKEND, "data")
FACULTY_OUT = os.path.join(DATA, "faculty.json")

# Source files in priority order. Each is a tuple
# (file_name, default_college, default_department_or_None)
SOURCES: List[tuple] = [
    # COLLEGE sources first — these set the primary academic affiliation. Their
    # row wins for cross-source dedupe (email match), so center/institute
    # appointments below merge INTO the college row instead of stealing it.
    ("ivy_v3_faculty.json",         "Ivy College of Business",                None),  # Filtered to faculty only
    ("vpn_scraped_faculty.json",    "College of Liberal Arts and Sciences",   None),  # 9 VPN-only depts
    ("vetmed_faculty.json",         "College of Veterinary Medicine",         None),
    ("chhs_faculty.json",           "College of Health and Human Sciences",   None),
    ("cals_v2_faculty.json",        "College of Agriculture and Life Sciences", None),
    ("coe_missing_faculty.json",    "College of Engineering",                 None),
    ("design_v2_faculty.json",      "College of Design",                      None),
    # ivy_v2_faculty.json removed — superseded by ivy_v3 (filters out staff/PhD students)
    ("las_missing_faculty.json",    "College of Liberal Arts and Sciences",   None),
    # Existing files, kept as fallback for anything not yet re-scraped
    ("las_faculty.json",            "College of Liberal Arts and Sciences",   None),
    ("coe_faculty.json",            "College of Engineering",                 None),
    ("cals_faculty.json",           "College of Agriculture and Life Sciences", None),
    # design_faculty.json removed — superseded by design_v2 (orphan 'Faculty' entries got filtered)
    # ivy_faculty.json removed — superseded by ivy_v3 (filters out staff/PhD students)
    # CENTER / INSTITUTE / LIBRARY sources LAST — they merge into existing
    # college rows by email, OR add new rows if the person has no college
    # affiliation. The college (when present) keeps its primary status; the
    # center role contributes title/bio fields.
    ("library_faculty.json",        "University Library",                     None),
    ("ciras_faculty.json",          "Center for Industrial Research and Service", None),
    ("intrans_faculty.json",        "Institute for Transportation",           None),
    ("extension_faculty.json",      "ISU Extension and Outreach",             None),
    # CENTER / INSTITUTE scraped data (generic scraper output)
    # Merged last so email-matched people get their center appended to
    # affiliations[] without changing their primary college.
    ("centers_faculty.json",        None,                                     None),
]

# Department label aliases — collapse alternate names to a single canonical form.
# These come from older verified-faculty seeds that used "Department of X" while
# newer college scrapes use the bare "X". Always lookup with .lower().strip().
DEPT_ALIASES: Dict[str, str] = {
    "department of computer science": "Computer Science",
}

# These row values are nav junk that crept in from earlier scrapers
NAME_BLOCKLIST = {
    "apply", "visit", "request information", "request info", "directory",
    "give", "alumni", "contact", "events", "people",
}

# These department values are placeholders we want to drop
DEPT_PLACEHOLDERS = {
    "unknown department", "unknown",
    "college of agriculture and life sciences",
    "college of design",
    "college of engineering",
    "college of liberal arts and sciences",
    "college of veterinary medicine",
    "college of health and human sciences",
    "ivy college of business",
}


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", (name or "").lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def email_key(row: Dict) -> Optional[str]:
    e = (row.get("email") or "").strip().lower()
    return e or None


def name_key(row: Dict) -> str:
    return slugify(row.get("name") or "")


def is_junk(row: Dict) -> bool:
    name = (row.get("name") or "").strip().lower()
    if not name or name in NAME_BLOCKLIST:
        return True
    if len(name) < 3:
        return True
    # Names like "Faculty Profile" / "John Doe (placeholder)" — best effort
    if any(b in name for b in ("faculty profile", "placeholder", "test user",
                                "meet our", "our researchers", "our staff")):
        return True
    # Orphan rows from old broken scrapes: title="Faculty", no email, no
    # profile_url, no photo. These came from a roster page that listed
    # names without any enrichment and pollute the directory with empty cards.
    title = (row.get("title") or "").strip().lower()
    has_contact = bool(
        row.get("email") or row.get("profile_url") or row.get("photo_url")
    )
    if title == "faculty" and not has_contact:
        return True
    return False


def normalize(row: Dict, default_college: str) -> Dict:
    """Make sure required fields exist; drop placeholder departments."""
    out = dict(row)
    out.setdefault("research_interests", [])
    out.setdefault("courses_taught", [])
    out.setdefault("is_teaching_faculty", False)
    if not out.get("college"):
        out["college"] = default_college
    dept = (out.get("department") or "").strip()
    if dept.lower() in DEPT_PLACEHOLDERS or not dept:
        out["department"] = "Unknown Department"
    else:
        # Apply department aliases (e.g. "Department of Computer Science" -> "Computer Science")
        canonical = DEPT_ALIASES.get(dept.lower())
        if canonical:
            out["department"] = canonical
    # CALS administrators (deans, associate deans, college office staff) are
    # college-level roles with no specific department. Re-tag them so they
    # don't show as "Unknown Department".
    if (out.get("college") == "College of Agriculture and Life Sciences"
        and out.get("department") == "Unknown Department"):
        out["department"] = "Office of the Dean (CALS)"
    if not out.get("id"):
        out["id"] = slugify(out.get("name") or "anon")
    return out


def merge_into(accum: Dict[str, Dict], row: Dict) -> bool:
    """
    Try to merge `row` into `accum`. Returns True if a row was added or merged.
    """
    if is_junk(row):
        return False

    # Build candidate keys
    ek = email_key(row)
    nk = name_key(row)
    college = (row.get("college") or "").strip().lower()

    # Look up by email first
    target_id = None
    if ek and ek in accum.get("__by_email__", {}):
        target_id = accum["__by_email__"][ek]
    else:
        # Try name + college
        key2 = f"{nk}::{college}"
        if key2 in accum.get("__by_name_college__", {}):
            target_id = accum["__by_name_college__"][key2]

    if target_id is not None:
        # Merge into existing
        existing = accum["rows"][target_id]
        # If the incoming row has a center_affiliation, append it to affiliations[]
        ca = (row.get("center_affiliation") or "").strip()
        if ca:
            existing.setdefault("affiliations", [])
            if ca not in existing["affiliations"]:
                existing["affiliations"].append(ca)
        for k, v in row.items():
            if not v:
                continue
            if k == "center_affiliation":
                continue  # handled above
            cur = existing.get(k)
            # Prefer non-empty / longer / more interesting
            if cur in (None, "", [], {}):
                existing[k] = v
            elif isinstance(cur, list) and isinstance(v, list):
                # Union
                seen = {json.dumps(x, sort_keys=True) for x in cur}
                for item in v:
                    if json.dumps(item, sort_keys=True) not in seen:
                        cur.append(item)
            elif isinstance(cur, str) and isinstance(v, str):
                # Department: a real department name always beats the
                # placeholder "Unknown Department" / college-name fallback.
                if k == "department":
                    cur_is_placeholder = cur.strip().lower() in DEPT_PLACEHOLDERS
                    new_is_placeholder = v.strip().lower() in DEPT_PLACEHOLDERS
                    if cur_is_placeholder and not new_is_placeholder:
                        existing[k] = v
                    # If both are real, keep the existing (first wins).
                elif k == "college":
                    # Once a college is set, never overwrite. The SOURCES list
                    # is ordered so college files come before center/institute
                    # files; when an InTrans/CIRAS/Library/Extension scrape
                    # finds the same person by email, the college affiliation
                    # stays put.
                    pass
                else:
                    # Default: prefer longer (richer title/bio/etc.)
                    if len(v) > len(cur):
                        existing[k] = v
        # Refresh email key in case the merge added one
        if ek and ek not in accum["__by_email__"]:
            accum["__by_email__"][ek] = target_id
        return True

    # New row — add it
    # Promote center_affiliation to affiliations[] for new rows too
    ca = (row.pop("center_affiliation", "") or "").strip()
    if ca:
        row.setdefault("affiliations", [])
        if ca not in row["affiliations"]:
            row["affiliations"].append(ca)
    rid = row.get("id") or nk or f"anon-{len(accum['rows'])}"
    # Avoid id collisions across colleges (rare)
    base = rid
    n = 2
    while rid in accum["rows"]:
        rid = f"{base}-{n}"
        n += 1
    row["id"] = rid
    accum["rows"][rid] = row
    if ek:
        accum["__by_email__"][ek] = rid
    accum["__by_name_college__"][f"{nk}::{college}"] = rid
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--out", default=FACULTY_OUT)
    args = parser.parse_args()

    accum: Dict[str, Dict] = {
        "rows": {},
        "__by_email__": {},
        "__by_name_college__": {},
    }

    # 1. Verified faculty first (these are the demo's primary CS people)
    sys.path.insert(0, BACKEND)
    try:
        from verified_faculty_data import VERIFIED_FACULTY_DATA  # type: ignore
        for r in VERIFIED_FACULTY_DATA:
            r2 = normalize(dict(r), "College of Liberal Arts and Sciences")
            merge_into(accum, r2)
        print(f"Verified faculty seeded: {len(accum['rows'])}")
    except Exception as e:
        print(f"WARNING: could not load verified_faculty_data: {e}")

    # 2. Per-source files
    per_source = []
    for fname, default_college, _ in SOURCES:
        path = os.path.join(DATA, fname)
        if not os.path.exists(path):
            per_source.append((fname, 0, 0, "missing"))
            continue
        try:
            with open(path, encoding="utf-8") as f:
                rows = json.load(f)
        except Exception as e:
            per_source.append((fname, 0, 0, f"load error: {e}"))
            continue
        added_before = len(accum["rows"])
        kept = 0
        for r in rows:
            # For centers_faculty.json rows, the college field is already set
            # by the scraper (to the center name). Use it as the default.
            dc = default_college or r.get("college", "Unknown")
            r2 = normalize(dict(r), dc)
            if merge_into(accum, r2):
                kept += 1
        added_after = len(accum["rows"])
        per_source.append((fname, len(rows), added_after - added_before, "ok"))
        print(
            f"{fname:35s} read={len(rows):5d}  net new={added_after - added_before:5d}  "
            f"merged={kept - (added_after - added_before):5d}"
        )

    final = list(accum["rows"].values())
    print(f"\nTotal merged: {len(final)} faculty")

    # Per-college / per-department breakdown
    coll_counts = Counter(f.get("college", "Unknown") for f in final)
    print("\n=== By college ===")
    for c, n in coll_counts.most_common():
        print(f"  {n:5d}  {c}")

    if args.dry_run:
        print("\n--dry-run: not writing faculty.json")
        return 0

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(final, f, indent=2, ensure_ascii=False)
    print(f"\nWrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
