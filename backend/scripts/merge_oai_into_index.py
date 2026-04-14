"""
Merge OAI-PMH harvest data into the existing dspace_index.db.

The OAI-PMH harvest provides richer subject metadata (93% have subjects,
avg 4.1 per record) that the Discovery API doesn't capture. This script:

1. Matches OAI records to existing index items by DSpace handle URL
2. Updates the subjects_json field for matched items
3. Reports new items found in OAI but missing from the index

Run:
    python scripts/merge_oai_into_index.py
    python scripts/merge_oai_into_index.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
OAI_FILE = BACKEND / "data" / "dspace" / "oai_harvest.jsonl"
SUBJECT_FILE = BACKEND / "data" / "dspace" / "dspace_subject_harvest.jsonl"


def extract_handle_id(dspace_url: str) -> str:
    """Extract the numeric handle ID from a DSpace URL or handle.
    e.g., 'https://dr.lib.iastate.edu/handle/20.500.12876/68760' -> '20.500.12876/68760'
    """
    m = re.search(r"20\.500\.12876/(\d+)", dspace_url)
    if m:
        return m.group(0)
    return ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("Merging OAI-PMH + Subject harvest data into dspace_index.db")
    print(f"  Index DB:      {INDEX_DB}")
    print(f"  OAI file:      {OAI_FILE}")
    print(f"  Subject file:  {SUBJECT_FILE}")
    print()

    # Load the index — build a lookup by handle and by dspace_url
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # Check if subjects_json column exists
    cols = [c[1] for c in conn.execute("PRAGMA table_info(items)").fetchall()]
    has_subjects = "subjects_json" in cols
    print(f"  Index has subjects_json column: {has_subjects}")

    if not has_subjects:
        print("  Adding subjects_json column...")
        if not args.dry_run:
            conn.execute("ALTER TABLE items ADD COLUMN subjects_json TEXT DEFAULT '[]'")
            conn.commit()

    # Build lookups: uuid, title
    print("  Building lookups from index...")
    uuid_set = set()
    title_to_uuid = {}
    for row in conn.execute("SELECT uuid, title FROM items"):
        uid = row["uuid"]
        uuid_set.add(uid)
        t = (row["title"] or "").lower().strip()
        if t:
            title_to_uuid[t] = uid
    print(f"  {len(uuid_set):,} items by UUID, {len(title_to_uuid):,} by title")

    # ── Process OAI-PMH records ──
    updated = 0
    not_found = 0
    total_subjects_added = 0

    if OAI_FILE.exists():
        print(f"\n  Processing OAI-PMH records...")
        with open(OAI_FILE, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                rec = json.loads(line)
                handle = rec.get("handle", "")
                subjects = rec.get("subjects", [])

                if not handle or not subjects:
                    continue

                # Match by title (OAI uses handles, index uses UUIDs — different ID spaces)
                title = (rec.get("title", "") or "").lower().strip()
                uuid = title_to_uuid.get(title)
                if not uuid:
                    not_found += 1
                    continue

                subjects_json = json.dumps(subjects, ensure_ascii=False)
                if not args.dry_run:
                    conn.execute(
                        "UPDATE items SET subjects_json = ? WHERE uuid = ?",
                        (subjects_json, uuid),
                    )
                updated += 1
                total_subjects_added += len(subjects)

                if line_num % 5000 == 0:
                    if not args.dry_run:
                        conn.commit()
                    print(f"    {line_num:,} OAI records processed, {updated:,} updated")

        if not args.dry_run:
            conn.commit()
        print(f"  OAI-PMH: {updated:,} items updated with subjects, {not_found:,} not found in index")
        print(f"  Total subject tags added: {total_subjects_added:,}")

    # ── Process Subject harvest records ──
    subj_updated = 0
    subj_not_found = 0
    subj_subjects_added = 0

    if SUBJECT_FILE.exists():
        print(f"\n  Processing Subject harvest records...")
        # Subject harvest uses UUIDs directly — uuid_set and title_to_uuid already built above

        with open(SUBJECT_FILE, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                rec = json.loads(line)
                subjects = rec.get("subjects", [])
                if not subjects:
                    continue

                # Try to find by UUID, then by handle in dspace_url, then by title
                uuid = rec.get("uuid", "")
                found_uuid = None

                if uuid in uuid_set:
                    found_uuid = uuid
                else:
                    # Try handle from dspace_url
                    dspace_url = rec.get("dspace_url", "")
                    handle = extract_handle_id(dspace_url)
                    if handle and handle in url_to_uuid:
                        found_uuid = url_to_uuid[handle]
                    else:
                        # Try title match
                        title = (rec.get("title", "") or "").lower().strip()[:100]
                        if title and title in title_to_uuid:
                            found_uuid = title_to_uuid[title]

                if not found_uuid:
                    subj_not_found += 1
                    continue

                # Merge subjects with existing
                existing_json = conn.execute(
                    "SELECT subjects_json FROM items WHERE uuid = ?",
                    (found_uuid,),
                ).fetchone()

                existing_subjects = []
                if existing_json and existing_json["subjects_json"]:
                    try:
                        existing_subjects = json.loads(existing_json["subjects_json"])
                    except:
                        pass

                # Union
                merged = list(dict.fromkeys(existing_subjects + subjects))
                new_count = len(merged) - len(existing_subjects)

                if new_count > 0:
                    if not args.dry_run:
                        conn.execute(
                            "UPDATE items SET subjects_json = ? WHERE uuid = ?",
                            (json.dumps(merged, ensure_ascii=False), found_uuid),
                        )
                    subj_updated += 1
                    subj_subjects_added += new_count

                if line_num % 5000 == 0:
                    if not args.dry_run:
                        conn.commit()
                    print(f"    {line_num:,} subject records processed, {subj_updated:,} enriched")

        if not args.dry_run:
            conn.commit()
        print(f"  Subject harvest: {subj_updated:,} items enriched, {subj_not_found:,} not found")
        print(f"  Additional subject tags: {subj_subjects_added:,}")

    # Final stats
    total_with_subjects = conn.execute(
        "SELECT COUNT(*) FROM items WHERE subjects_json IS NOT NULL AND subjects_json != '[]'"
    ).fetchone()[0]
    total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    conn.close()

    print()
    print("=" * 60)
    print(f"Items with subjects: {total_with_subjects:,} / {total_items:,} ({100*total_with_subjects/max(total_items,1):.0f}%)")
    print(f"Total updates:       {updated + subj_updated:,}")
    if args.dry_run:
        print("[DRY RUN] No changes written.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
