"""
Enrich the department field in dspace_index.db using three strategies:

  Strategy A - Profile self-enrichment:
    Profile items in the DB already carry department info in authors_json
    but have an empty department column.  Copy it over.

  Strategy B - Direct profile matching:
    Match authors on missing-dept items against the 1,124 DSpace
    "Academic and Administrative Profiles" name->department records.

  Strategy C - Co-authorship propagation:
    If an author appears on OTHER items that already have a department,
    propagate that department to missing-dept items.
    Uses full normalized name for precision; falls back to first+last
    only when a single department dominates (>50% and count >= 2).

Data sources:
  - backend/data/dspace/dspace_items_51e51f6d-...-e0936a8b.jsonl  (profiles)
  - backend/data/dspace/dspace_index.db  (items + authors tables)

Run:
    python scripts/enrich_dept_profiles.py
    python scripts/enrich_dept_profiles.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"

PROFILES_JSONL = (
    BACKEND / "data" / "dspace"
    / "dspace_items_51e51f6d-6bca-492f-91ff-22c9e0936a8b.jsonl"
)


# ── Name normalization helpers ──────────────────────────────────────

def normalize(name: str) -> str:
    """Lowercase, strip suffixes/titles, collapse whitespace."""
    n = name.strip()
    n = re.sub(
        r"\b(Jr\.?|Sr\.?|III|IV|II|Ph\.?D\.?|M\.?D\.?|Dr\.?|Prof\.?)\b",
        "", n, flags=re.I,
    )
    n = re.sub(r"[^a-zA-Z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n


def full_norm(name: str) -> str:
    """Normalize 'Last, First Middle' -> 'first middle last'."""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            last = normalize(parts[0])
            firsts = normalize(parts[1])
            return f"{firsts} {last}".strip()
    return normalize(name)


def first_last(name: str) -> tuple[str, str]:
    """Parse 'Last, First Middle' -> (first, last) normalized."""
    if "," in name:
        parts = [p.strip() for p in name.split(",", 1)]
        if len(parts) == 2:
            last = normalize(parts[0])
            first_tok = normalize(parts[1]).split()
            first = first_tok[0] if first_tok else ""
            return (first, last)
    n = normalize(name)
    parts = n.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return (n, "")


def pick_best_dept(depts: list[str]) -> str:
    """Given multiple departments, prefer the most specific one."""
    if not depts:
        return ""
    if len(depts) == 1:
        return depts[0]

    def score(d: str) -> int:
        dl = d.lower()
        if dl.startswith("department of"):
            return 4
        if dl.startswith("school of"):
            return 3
        if "program" in dl:
            return 2
        if dl.startswith("college of"):
            return 1
        return 0

    return sorted(depts, key=score, reverse=True)[0]


# ── Main ────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich departments from DSpace profiles + co-authorship"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would change without writing to DB")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # ================================================================
    # Step 1: Load profile name -> department mapping from JSONL
    # ================================================================
    print("=" * 64)
    print("Step 1: Loading profile name -> department mapping")
    print("=" * 64)

    if not PROFILES_JSONL.exists():
        print(f"ERROR: Profiles JSONL not found: {PROFILES_JSONL}", file=sys.stderr)
        return 1

    profile_depts: dict[str, list[str]] = {}
    profile_count = 0
    with open(PROFILES_JSONL, "r", encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            profile_count += 1
            name = rec.get("title", "").strip()
            depts = [a for a in rec.get("authors", []) if a]
            if name and depts:
                profile_depts[name] = depts

    print(f"  Profiles read:           {profile_count:,}")
    print(f"  Profiles with dept info: {len(profile_depts):,}")

    # Build profile indexes (full-name and first-last)
    prof_full: dict[str, list[str]] = {}    # full_norm -> dept list
    prof_fl: dict[tuple, list[str]] = {}    # (first,last) -> dept list

    for raw_name, depts in profile_depts.items():
        fn = full_norm(raw_name)
        if fn and fn not in prof_full:
            prof_full[fn] = depts
        # Also raw normalized form (e.g., "adams daniel" for "Adams, Daniel")
        raw_norm = normalize(raw_name)
        if raw_norm and raw_norm not in prof_full:
            prof_full[raw_norm] = depts
        fl = first_last(raw_name)
        if fl[0] and fl[1] and fl not in prof_fl:
            prof_fl[fl] = depts

    print(f"  Profile full-name keys:  {len(prof_full):,}")
    print(f"  Profile first-last keys: {len(prof_fl):,}")

    # ================================================================
    # Step 2: Build co-authorship dept index from existing DB data
    # ================================================================
    print()
    print("=" * 64)
    print("Step 2: Building co-authorship department index")
    print("=" * 64)

    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # All author->dept associations from items that already have departments
    rows = conn.execute("""
        SELECT a.author_name, i.department
        FROM authors a
        JOIN items i ON a.item_uuid = i.uuid
        WHERE i.department IS NOT NULL AND i.department != ''
    """).fetchall()

    coauth_full: dict[str, Counter] = defaultdict(Counter)
    coauth_fl: dict[tuple, Counter] = defaultdict(Counter)

    for row in rows:
        author_name = row["author_name"]
        dept = row["department"]
        fn = full_norm(author_name)
        if fn:
            coauth_full[fn][dept] += 1
        fl = first_last(author_name)
        if fl[0] and fl[1]:
            coauth_fl[fl][dept] += 1

    print(f"  Co-auth full-name keys:  {len(coauth_full):,}")
    print(f"  Co-auth first-last keys: {len(coauth_fl):,}")

    # ================================================================
    # Step 3A: Enrich profile items themselves
    # ================================================================
    print()
    print("=" * 64)
    print("Step 3A: Enriching profile items (self-department)")
    print("=" * 64)

    profile_missing = conn.execute("""
        SELECT uuid, title, authors_json FROM items
        WHERE (department IS NULL OR department = '')
        AND collection_name = 'Academic and Administrative Profiles'
        AND authors_json IS NOT NULL AND authors_json != '[]'
    """).fetchall()

    enriched_profiles = 0
    for row in profile_missing:
        depts = json.loads(row["authors_json"])
        if depts:
            dept = pick_best_dept(depts)
            if dept:
                if not args.dry_run:
                    conn.execute(
                        "UPDATE items SET department = ? WHERE uuid = ?",
                        (dept, row["uuid"]),
                    )
                enriched_profiles += 1

    if not args.dry_run:
        conn.commit()
    print(f"  Profile items enriched:  {enriched_profiles:,}")

    # ================================================================
    # Step 3B: Enrich regular items via profile match + co-authorship
    # ================================================================
    print()
    print("=" * 64)
    print("Step 3B: Enriching items (profile match + co-authorship)")
    print("=" * 64)

    missing = conn.execute("""
        SELECT uuid, title, authors_json FROM items
        WHERE (department IS NULL OR department = '')
        AND collection_name NOT IN (
            'Academic and Administrative Profiles',
            'Academic and Administrative Units'
        )
    """).fetchall()
    print(f"  Items missing department: {len(missing):,}")

    enriched_profile_match = 0
    enriched_coauth_full = 0
    enriched_coauth_fl = 0
    no_match = 0
    examples: list[str] = []

    for i, row in enumerate(missing):
        raw = row["authors_json"]
        if not raw or raw == "[]":
            no_match += 1
            continue
        authors = json.loads(raw)
        if not authors:
            no_match += 1
            continue

        assigned_dept = None
        strategy = ""

        # --- Strategy B: direct profile name match ---
        for author in authors:
            fn = full_norm(author)
            if fn in prof_full:
                assigned_dept = pick_best_dept(prof_full[fn])
                strategy = "profile-full"
                break
            fl = first_last(author)
            if fl[0] and fl[1] and fl in prof_fl:
                assigned_dept = pick_best_dept(prof_fl[fl])
                strategy = "profile-fl"
                break

        # --- Strategy C: co-authorship propagation ---
        if not assigned_dept:
            for author in authors:
                fn = full_norm(author)
                if fn in coauth_full:
                    counter = coauth_full[fn]
                    top_dept, top_cnt = counter.most_common(1)[0]
                    # Accept if: single dept, or majority with count >= 2
                    if len(counter) == 1:
                        assigned_dept = top_dept
                        strategy = "coauth-full-single"
                        break
                    elif top_cnt >= 2:
                        total = sum(counter.values())
                        if top_cnt / total > 0.5:
                            assigned_dept = top_dept
                            strategy = "coauth-full-majority"
                            break

        if not assigned_dept:
            for author in authors:
                fl = first_last(author)
                if fl[0] and fl[1] and fl in coauth_fl:
                    counter = coauth_fl[fl]
                    top_dept, top_cnt = counter.most_common(1)[0]
                    total = sum(counter.values())
                    # Stricter for first-last: need majority AND count >= 3
                    if top_cnt >= 3 and top_cnt / total > 0.6:
                        assigned_dept = top_dept
                        strategy = "coauth-fl"
                        break

        if not assigned_dept:
            no_match += 1
            continue

        # Track which strategy worked
        if strategy.startswith("profile"):
            enriched_profile_match += 1
        elif strategy.startswith("coauth-full"):
            enriched_coauth_full += 1
        else:
            enriched_coauth_fl += 1

        if not args.dry_run:
            conn.execute(
                "UPDATE items SET department = ? WHERE uuid = ?",
                (assigned_dept, row["uuid"]),
            )

        if len(examples) < 15:
            title_short = row["title"][:50] if row["title"] else "(no title)"
            auth_short = ", ".join(authors[:2])[:30]
            examples.append(
                f"    {title_short:50s} | {auth_short:30s} -> {assigned_dept}  [{strategy}]"
            )

        if (i + 1) % 3000 == 0:
            if not args.dry_run:
                conn.commit()
            total_so_far = enriched_profile_match + enriched_coauth_full + enriched_coauth_fl
            print(f"    ... {i+1:,} processed, {total_so_far:,} enriched")

    if not args.dry_run:
        conn.commit()

    enriched_regular = enriched_profile_match + enriched_coauth_full + enriched_coauth_fl

    # ================================================================
    # Step 4: Summary
    # ================================================================
    print()
    print("=" * 64)
    print("Results")
    print("=" * 64)

    total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    has_dept = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NOT NULL AND department != ''"
    ).fetchone()[0]
    still_missing = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NULL OR department = ''"
    ).fetchone()[0]

    conn.close()

    total_enriched = enriched_profiles + enriched_regular

    print(f"  Strategy A (profile self-dept):     {enriched_profiles:,}")
    print(f"  Strategy B (profile name match):    {enriched_profile_match:,}")
    print(f"  Strategy C (co-auth full-name):     {enriched_coauth_full:,}")
    print(f"  Strategy C (co-auth first-last):    {enriched_coauth_fl:,}")
    print(f"  ----------------------------------------")
    print(f"  Total enriched this run:            {total_enriched:,}")
    print(f"  No match found:                     {no_match:,}")
    print()
    print(f"  DB coverage after enrichment:")
    print(f"    Total items:       {total_items:,}")
    print(f"    With department:   {has_dept:,}")
    print(f"    Still missing:     {still_missing:,}")
    print(f"    Coverage:          {100 * has_dept / total_items:.1f}%")

    if examples:
        print()
        print("  Sample matches:")
        for ex in examples:
            print(ex)

    mode = "LIVE" if not args.dry_run else "DRY RUN"
    print()
    print(f"  [{mode}] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
