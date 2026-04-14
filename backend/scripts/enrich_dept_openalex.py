"""
Recover department information for DSpace items using OpenAlex author data.

Strategy (two passes):
  Pass 1 — OpenAlex name match + author propagation from existing dept data
    For each item missing a department:
    a) Match its authors against the 74k OpenAlex ISU author set
    b) For matched authors, look up their department from OTHER items in
       dspace_index.db that already have departments assigned
    c) Assign the most-frequent department found

  Pass 2 — Pure author propagation (no OpenAlex required)
    For items still missing a department after Pass 1:
    a) Look up each author directly in the authors table
    b) Find items by that author that DO have a department
    c) Assign the most-frequent department

Run:
    python scripts/enrich_dept_openalex.py
    python scripts/enrich_dept_openalex.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
OPENALEX_AUTHORS = BACKEND / "data" / "openalex_isu_authors.json"

TOTAL_ITEMS = 120_780  # for coverage percentage


# ── Name normalization ──────────────────────────────────────────────

def strip_accents(s: str) -> str:
    """Remove diacritics/accents."""
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize(name: str) -> str:
    """Normalize to 'first last' lowercase, stripping middle names, suffixes,
    accents, and punctuation. Works on both 'First Last' and 'Last, First'."""
    n = name.strip()
    # Handle "Last, First Middle" -> "First Last"
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2 and parts[1]:
            n = f"{parts[1]} {parts[0]}"
    # Strip accents
    n = strip_accents(n)
    # Remove suffixes
    n = re.sub(
        r"\b(Jr\.?|Sr\.?|III|IV|II|Ph\.?D\.?|M\.?D\.?|Dr\.?|Prof\.?)\b",
        "", n, flags=re.I,
    )
    # Keep only letters, spaces, hyphens
    n = re.sub(r"[^a-zA-Z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n


def first_last(name: str) -> tuple[str, str]:
    """Extract (first, last) from a normalized name string."""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return ("", "")


# ── Build OpenAlex lookup ───────────────────────────────────────────

def build_openalex_index(authors: list[dict]) -> dict[str, set[str]]:
    """Build a name -> set(openalex_ids) lookup from OpenAlex ISU authors.

    Indexes both display_name and display_name_alternatives, using
    (first, last) as the key to handle middle-name variations.
    """
    # (first, last) -> set of openalex IDs
    fl_index: dict[tuple[str, str], set[str]] = defaultdict(set)

    for a in authors:
        oa_id = a["id"]
        # Primary display name
        norm = normalize(a["display_name"])
        fl = first_last(norm)
        if fl[0] and fl[1]:
            fl_index[fl].add(oa_id)

        # Alternatives — many are noisy, so only use clean short ones
        for alt in (a.get("display_name_alternatives") or []):
            # Skip very long strings (often contain affiliations)
            if len(alt) > 60:
                continue
            # Skip initials-only like "J. Wu"
            alt_norm = normalize(alt)
            alt_fl = first_last(alt_norm)
            if alt_fl[0] and alt_fl[1] and len(alt_fl[0]) > 1:
                fl_index[alt_fl].add(oa_id)

    return fl_index


# ── Build author-to-department map from existing DB data ────────────

def build_author_dept_map(conn: sqlite3.Connection) -> dict[str, str]:
    """For every author that appears on an item WITH a department,
    find their most-frequent department.

    Returns { author_name_normalized: best_department }.
    """
    rows = conn.execute("""
        SELECT a.author_name, i.department
        FROM authors a
        JOIN items i ON a.item_uuid = i.uuid
        WHERE i.department IS NOT NULL AND i.department != ''
    """).fetchall()

    # author_name -> Counter of departments
    dept_counts: dict[str, Counter] = defaultdict(Counter)
    for author_name, dept in rows:
        norm = normalize(author_name)
        fl = first_last(norm)
        if fl[0] and fl[1]:
            key = f"{fl[0]} {fl[1]}"
            dept_counts[key][dept] += 1

    # Pick the most common department for each author
    result: dict[str, str] = {}
    for key, counter in dept_counts.items():
        best_dept, _count = counter.most_common(1)[0]
        result[key] = best_dept

    return result


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich DSpace department field using OpenAlex author data"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print stats without writing to DB")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # ── Load OpenAlex authors ───────────────────────────────────────
    print(f"Loading OpenAlex authors from {OPENALEX_AUTHORS} ...")
    with open(OPENALEX_AUTHORS, encoding="utf-8") as f:
        oa_authors = json.load(f)
    print(f"  Loaded {len(oa_authors):,} OpenAlex ISU authors")

    oa_index = build_openalex_index(oa_authors)
    print(f"  OpenAlex (first,last) index: {len(oa_index):,} unique keys")

    # ── Open DB ─────────────────────────────────────────────────────
    conn = sqlite3.connect(INDEX_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row

    before_count = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NOT NULL AND department != ''"
    ).fetchone()[0]
    print(f"\nDepartment coverage before: {before_count:,}/{TOTAL_ITEMS}")

    # ── Build author -> dept map from existing data ─────────────────
    print("Building author-to-department map from existing items ...")
    author_dept_map = build_author_dept_map(conn)
    print(f"  {len(author_dept_map):,} authors with known department")

    # ── Fetch items missing department ──────────────────────────────
    missing = conn.execute("""
        SELECT uuid, authors_json FROM items
        WHERE (department IS NULL OR department = '')
          AND authors_json IS NOT NULL AND authors_json != '[]'
    """).fetchall()
    print(f"\nItems missing department (with authors): {len(missing):,}")

    # ── Pass 1: OpenAlex match + author propagation ─────────────────
    print("\n--- Pass 1: OpenAlex match + author dept propagation ---")
    p1_enriched = 0
    p1_oa_match_no_dept = 0
    p1_no_match = 0
    updates: list[tuple[str, str]] = []  # (dept, uuid)

    for i, row in enumerate(missing):
        try:
            authors = json.loads(row["authors_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not authors:
            continue

        dept_votes: Counter = Counter()

        for author_name in authors:
            norm = normalize(author_name)
            fl = first_last(norm)
            if not fl[0] or not fl[1]:
                continue
            fl_key = f"{fl[0]} {fl[1]}"

            # Check if this author is in the OpenAlex ISU set
            is_oa_match = bool(oa_index.get(fl, set()))

            if is_oa_match:
                # Try to find their department from existing items
                dept = author_dept_map.get(fl_key)
                if dept:
                    dept_votes[dept] += 1

        if dept_votes:
            best_dept = dept_votes.most_common(1)[0][0]
            updates.append((best_dept, row["uuid"]))
            p1_enriched += 1
        else:
            p1_no_match += 1

        if (i + 1) % 5000 == 0:
            print(f"  {i + 1:,} processed, {p1_enriched:,} enriched ...")

    # Commit Pass 1
    if updates and not args.dry_run:
        for batch_start in range(0, len(updates), 1000):
            batch = updates[batch_start : batch_start + 1000]
            conn.executemany(
                "UPDATE items SET department = ? WHERE uuid = ?", batch
            )
            conn.commit()
        print(f"  Committed {len(updates):,} updates")

    print(f"  Pass 1 enriched:          {p1_enriched:,}")
    print(f"  Pass 1 no match:          {p1_no_match:,}")

    # ── Update author_dept_map with new assignments ─────────────────
    # So pass 2 can leverage newly assigned departments
    if updates and not args.dry_run:
        print("\nRebuilding author-dept map after Pass 1 ...")
        author_dept_map = build_author_dept_map(conn)
        print(f"  {len(author_dept_map):,} authors with known department")

    # ── Pass 2: Pure author propagation (no OpenAlex needed) ────────
    # Re-fetch items still missing department
    still_missing = conn.execute("""
        SELECT uuid, authors_json FROM items
        WHERE (department IS NULL OR department = '')
          AND authors_json IS NOT NULL AND authors_json != '[]'
    """).fetchall()
    print(f"\n--- Pass 2: Pure author propagation ---")
    print(f"Items still missing department: {len(still_missing):,}")

    p2_enriched = 0
    updates2: list[tuple[str, str]] = []

    for i, row in enumerate(still_missing):
        try:
            authors = json.loads(row["authors_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        if not authors:
            continue

        dept_votes: Counter = Counter()

        for author_name in authors:
            norm = normalize(author_name)
            fl = first_last(norm)
            if not fl[0] or not fl[1]:
                continue
            fl_key = f"{fl[0]} {fl[1]}"

            dept = author_dept_map.get(fl_key)
            if dept:
                dept_votes[dept] += 1

        if dept_votes:
            best_dept = dept_votes.most_common(1)[0][0]
            updates2.append((best_dept, row["uuid"]))
            p2_enriched += 1

        if (i + 1) % 5000 == 0:
            print(f"  {i + 1:,} processed, {p2_enriched:,} enriched ...")

    # Commit Pass 2
    if updates2 and not args.dry_run:
        for batch_start in range(0, len(updates2), 1000):
            batch = updates2[batch_start : batch_start + 1000]
            conn.executemany(
                "UPDATE items SET department = ? WHERE uuid = ?", batch
            )
            conn.commit()
        print(f"  Committed {len(updates2):,} updates")

    print(f"  Pass 2 enriched:          {p2_enriched:,}")

    # ── Final stats ─────────────────────────────────────────────────
    after_count = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NOT NULL AND department != ''"
    ).fetchone()[0]
    remaining = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NULL OR department = ''"
    ).fetchone()[0]

    conn.close()

    total_enriched = p1_enriched + p2_enriched

    print()
    print("=" * 60)
    print(f"Enrichment {'complete' if not args.dry_run else '[DRY RUN]'}")
    print(f"  Pass 1 (OpenAlex + propagation):  {p1_enriched:,}")
    print(f"  Pass 2 (pure propagation):        {p2_enriched:,}")
    print(f"  Total enriched:                   {total_enriched:,}")
    print(f"  Dept before:  {before_count:,}/{TOTAL_ITEMS} ({100*before_count/TOTAL_ITEMS:.1f}%)")
    print(f"  Dept after:   {after_count:,}/{TOTAL_ITEMS} ({100*after_count/TOTAL_ITEMS:.1f}%)")
    print(f"  Still missing: {remaining:,}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
