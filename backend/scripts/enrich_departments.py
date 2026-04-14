"""
Enrich the department field in dspace_index.db by cross-referencing
author names with faculty.json.

For each item missing a department:
  1. Parse authors (DSpace format: "Last, First" or "Last, First Middle")
  2. Match each author against faculty.json by normalized name
  3. If exactly one department match → assign it
  4. If multiple departments → log as conflict for admin resolution

Outputs:
  - Updates dspace_index.db department field
  - Writes department_conflicts.json for admin dashboard

Run:
    python scripts/enrich_departments.py
    python scripts/enrich_departments.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
FACULTY_FILE = BACKEND / "data" / "faculty.json"
CONFLICTS_FILE = BACKEND / "data" / "department_conflicts.json"


def normalize_name(name: str) -> str:
    """Normalize to 'first last' lowercase, strip middle names/initials."""
    n = name.strip()
    # Handle "Last, First Middle" format
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2:
            n = f"{parts[1]} {parts[0]}"
    # Remove suffixes
    n = re.sub(r"\b(Jr\.?|Sr\.?|III|IV|II|Ph\.?D\.?|M\.?D\.?|Dr\.?)\b", "", n, flags=re.I)
    # Remove non-alpha
    n = re.sub(r"[^a-zA-Z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n


def name_key(name: str) -> tuple[str, str]:
    """Extract (first, last) from normalized name."""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return (name, "")


def build_faculty_index(faculty: list[dict]) -> dict:
    """Build multiple lookup indexes from faculty data."""
    # exact normalized name -> list of faculty records
    by_full_name: dict[str, list[dict]] = defaultdict(list)
    # (first, last) -> list of faculty records
    by_first_last: dict[tuple, list[dict]] = defaultdict(list)
    # last name -> list of faculty records
    by_last: dict[str, list[dict]] = defaultdict(list)

    for f in faculty:
        name = f.get("name", "")
        norm = normalize_name(name)
        if not norm:
            continue

        by_full_name[norm].append(f)

        key = name_key(norm)
        if key[0] and key[1]:
            by_first_last[key].append(f)
            by_last[key[1]].append(f)

    return {
        "full": by_full_name,
        "first_last": by_first_last,
        "last": by_last,
    }


def match_author(author_name: str, index: dict) -> list[dict]:
    """Try to match a DSpace author name to faculty records.
    Returns list of matching faculty (may be >1 for conflicts).
    """
    norm = normalize_name(author_name)
    if not norm:
        return []

    # 1. Exact full name match
    matches = index["full"].get(norm, [])
    if matches:
        return matches

    # 2. First+Last match (ignoring middle names)
    key = name_key(norm)
    if key[0] and key[1]:
        matches = index["first_last"].get(key, [])
        if len(matches) == 1:
            return matches
        # If multiple matches by first+last, that's ambiguous — return all
        if matches:
            return matches

    return []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Load faculty
    with open(FACULTY_FILE, encoding="utf-8") as f:
        faculty = json.load(f)
    print(f"Loaded {len(faculty)} faculty records")

    # Build index
    fac_index = build_faculty_index(faculty)
    print(f"Faculty index: {len(fac_index['full'])} full names, "
          f"{len(fac_index['first_last'])} first+last keys")

    # Open DB
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # Get items missing department
    missing = conn.execute("""
        SELECT uuid, title, authors_json, department FROM items
        WHERE (department IS NULL OR department = '')
        AND authors_json IS NOT NULL AND authors_json != '[]'
    """).fetchall()
    print(f"Items missing department (with authors): {len(missing):,}")

    # Also get items WITH department for conflict detection
    has_dept = conn.execute("""
        SELECT uuid, title, authors_json, department FROM items
        WHERE department IS NOT NULL AND department != ''
        AND authors_json IS NOT NULL AND authors_json != '[]'
    """).fetchall()
    print(f"Items with department (for conflict check): {len(has_dept):,}")

    # Process missing-department items
    enriched = 0
    conflicts = []
    no_match = 0
    stats = {"single_dept": 0, "multi_dept": 0, "no_faculty_match": 0}

    print(f"\nProcessing {len(missing):,} items without department...")
    for i, row in enumerate(missing):
        authors = json.loads(row["authors_json"])
        if not authors:
            continue

        # Collect all departments from matched faculty
        depts_found = {}  # dept -> [faculty_names]
        matched_faculty = []

        for author in authors:
            fac_matches = match_author(author, fac_index)
            for fm in fac_matches:
                dept = fm.get("department", "")
                if dept and dept != "Unknown Department":
                    if dept not in depts_found:
                        depts_found[dept] = []
                    depts_found[dept].append(fm["name"])
                    matched_faculty.append(fm)

        if not depts_found:
            no_match += 1
            stats["no_faculty_match"] += 1
            continue

        if len(depts_found) == 1:
            # Single department — assign it
            dept = list(depts_found.keys())[0]
            if not args.dry_run:
                conn.execute(
                    "UPDATE items SET department = ? WHERE uuid = ?",
                    (dept, row["uuid"]),
                )
            enriched += 1
            stats["single_dept"] += 1
        else:
            # Multiple departments — record conflict
            conflicts.append({
                "item_uuid": row["uuid"],
                "item_title": row["title"][:200],
                "authors": authors[:5],
                "departments_found": {d: names for d, names in depts_found.items()},
                "current_department": row["department"] or "",
                "status": "pending",  # pending | resolved
                "resolution": None,   # chosen department or null
            })
            # Still assign the most common one as default
            best_dept = max(depts_found.keys(), key=lambda d: len(depts_found[d]))
            if not args.dry_run:
                conn.execute(
                    "UPDATE items SET department = ? WHERE uuid = ?",
                    (best_dept, row["uuid"]),
                )
            enriched += 1
            stats["multi_dept"] += 1

        if (i + 1) % 5000 == 0:
            if not args.dry_run:
                conn.commit()
            print(f"  {i+1:,} processed, {enriched:,} enriched, {len(conflicts):,} conflicts")

    if not args.dry_run:
        conn.commit()

    # Also scan items WITH department for faculty-mismatch conflicts
    print(f"\nScanning {len(has_dept):,} items with existing department for mismatches...")
    dept_mismatches = 0
    for row in has_dept:
        authors = json.loads(row["authors_json"])
        if not authors:
            continue

        current_dept = row["department"]
        other_depts = set()

        for author in authors[:3]:  # check first 3 authors only for speed
            fac_matches = match_author(author, fac_index)
            for fm in fac_matches:
                dept = fm.get("department", "")
                if dept and dept != "Unknown Department" and dept != current_dept:
                    other_depts.add(dept)

        # Don't log if the mismatch is just between similar dept names
        if other_depts:
            dept_mismatches += 1

    print(f"  Department mismatches found: {dept_mismatches:,}")

    # Build faculty conflict summary (faculty with multiple departments)
    faculty_conflicts = []
    for f in faculty:
        depts = set()
        if f.get("department"):
            depts.add(f["department"])
        for aff in (f.get("affiliations") or []):
            depts.add(aff)
        if len(depts) > 1:
            faculty_conflicts.append({
                "faculty_id": f["id"],
                "faculty_name": f["name"],
                "primary_department": f.get("department", ""),
                "affiliations": f.get("affiliations", []),
                "email": f.get("email", ""),
                "all_departments": sorted(depts),
                "status": "pending",
                "resolution": None,
            })

    # Save conflicts
    all_conflicts = {
        "item_conflicts": conflicts[:500],  # cap at 500 for admin UI
        "item_conflict_count": len(conflicts),
        "faculty_conflicts": faculty_conflicts,
        "faculty_conflict_count": len(faculty_conflicts),
        "stats": {
            "items_enriched": enriched,
            "single_department": stats["single_dept"],
            "multi_department": stats["multi_dept"],
            "no_faculty_match": stats["no_faculty_match"],
            "total_missing_before": len(missing),
            "dept_mismatches_in_existing": dept_mismatches,
        },
    }

    if not args.dry_run:
        with open(CONFLICTS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_conflicts, f, indent=2, ensure_ascii=False)

    # Final stats
    new_total = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NOT NULL AND department != ''"
    ).fetchone()[0]
    conn.close()

    print()
    print("=" * 60)
    print(f"Enrichment {'complete' if not args.dry_run else '[DRY RUN]'}")
    print(f"  Items enriched:           {enriched:,}")
    print(f"    Single dept (clean):    {stats['single_dept']:,}")
    print(f"    Multi dept (conflict):  {stats['multi_dept']:,}")
    print(f"  No faculty match:         {no_match:,}")
    print(f"  Item conflicts logged:    {len(conflicts):,}")
    print(f"  Faculty conflicts:        {len(faculty_conflicts):,}")
    print(f"  Dept coverage:            {new_total:,}/{120780} ({100*new_total/120780:.1f}%)")
    print(f"  Conflicts file:           {CONFLICTS_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
