"""
Faculty name reconciliation — merge duplicates, normalize names, remove junk.

Duplicates arise because the same person is scraped from multiple sources
(department page + center page). This script:
  1. Removes junk entries (non-person records).
  2. Merges exact-name duplicates (combine affiliations, keep richest record).
  3. Merges fuzzy variants (same first+last, same department) — prefers the
     shorter (canonical) name form unless the longer one has richer data.
  4. Writes the cleaned faculty.json (backs up original first).

Run:
    python backend/scripts/reconcile_faculty_names.py
    python backend/scripts/reconcile_faculty_names.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
FACULTY_FILE = BACKEND / "data" / "faculty.json"

# ── Junk patterns: entries that aren't real people ─────────────────────────────
JUNK_NAMES = {
    "Faculty and Scientific Staff",
    "Faculty and Staff",
    "Postdoctoral Research Associates",
    "Post-Doctoral Research Associates",
}

# ── Known FALSE POSITIVES: same normalized (first,last) but different people ──
# These will NOT be merged even if they share a last name.
FALSE_POSITIVE_PAIRS = {
    # Different first names that normalize to same key
    ("dr-han-na-lee", "dr-keunsub-lee"),
    ("dr-david-peters", "dr-reuben-peters"),
    ("dr-alison-phillips", "dr-warren-phillips"),
    ("md-mehedi-hasan", "md-shazid-hasan"),
    ("md-muzakker-hossain", "md-arafat-hossain"),
    ("md-mahbubur-rahman", "md-khaledur-rahman"),
    ("md-mahbubur-rahman", "md-lutfor-rahman"),
    ("md-khaledur-rahman", "md-lutfor-rahman"),
    ("john-hemmingson-hill", "john-hill"),
    # Thomas Harrington in NREM vs Thomas C Harrington in PPEM — different depts
    ("thomas-harrington", "thomas-c-harrington"),
}


def normalize_key(name: str) -> tuple[str, str]:
    """Normalize name to (first, last) for fuzzy grouping."""
    n = name.lower().strip()
    n = re.sub(r"[^a-z\s]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    parts = n.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return (n, "")


def richness_score(entry: dict) -> int:
    """Score how much useful data a record has (higher = richer)."""
    score = 0
    if entry.get("email"):
        score += 5
    if entry.get("photo_url"):
        score += 3
    if entry.get("research_interests"):
        score += len(entry["research_interests"])
    if entry.get("courses_taught"):
        score += len(entry["courses_taught"]) * 2
    if entry.get("research_areas"):
        score += len(entry["research_areas"])
    if entry.get("rank"):
        score += 2
    if entry.get("profile_url"):
        score += 1
    if entry.get("college"):
        score += 1
    return score


def merge_records(primary: dict, secondary: dict) -> dict:
    """Merge secondary into primary, combining list fields, preferring primary scalars."""
    merged = dict(primary)

    # Combine list fields (deduplicated)
    for field in ("affiliations", "research_interests", "research_areas", "courses_taught"):
        plist = list(primary.get(field) or [])
        slist = list(secondary.get(field) or [])
        combined = list(dict.fromkeys(plist + slist))  # dedupe preserving order
        if combined:
            merged[field] = combined

    # Fill in missing scalar fields from secondary
    for field in ("email", "photo_url", "rank", "title", "college", "department",
                  "profile_url", "source_url", "group"):
        if not merged.get(field) and secondary.get(field):
            merged[field] = secondary[field]

    # is_teaching_faculty: True if either says True
    if secondary.get("is_teaching_faculty"):
        merged["is_teaching_faculty"] = True

    return merged


def are_false_positives(a: dict, b: dict) -> bool:
    """Check if two entries are known false positives (different people)."""
    pair1 = (a["id"], b["id"])
    pair2 = (b["id"], a["id"])
    return pair1 in FALSE_POSITIVE_PAIRS or pair2 in FALSE_POSITIVE_PAIRS


def same_department_family(a: dict, b: dict) -> bool:
    """Check if two entries are from the same department family."""
    da = (a.get("department") or "").lower()
    db = (b.get("department") or "").lower()
    if not da or not db:
        return True  # can't distinguish, assume same
    # Exact match
    if da == db:
        return True
    # One contains the other (e.g. "Agronomy" vs "Department of Agronomy")
    if da in db or db in da:
        return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't write, just report")
    args = parser.parse_args()

    with open(FACULTY_FILE, encoding="utf-8") as f:
        data = json.load(f)

    print(f"Loaded {len(data)} faculty records")
    print()

    # ── Step 1: Remove junk ────────────────────────────────────────────────────
    junk_removed = [f for f in data if f["name"] in JUNK_NAMES]
    data = [f for f in data if f["name"] not in JUNK_NAMES]
    print(f"Step 1: Removed {len(junk_removed)} junk entries:")
    for j in junk_removed:
        print(f"  - \"{j['name']}\" (id={j['id']})")
    print()

    # ── Step 2: Merge exact-name duplicates ────────────────────────────────────
    by_name: dict[str, list[dict]] = defaultdict(list)
    for f in data:
        by_name[f["name"]].append(f)

    merged_data = []
    exact_merge_count = 0
    for name, entries in by_name.items():
        if len(entries) == 1:
            merged_data.append(entries[0])
            continue

        # Sort by richness — richest becomes primary
        entries.sort(key=richness_score, reverse=True)
        primary = entries[0]
        for secondary in entries[1:]:
            primary = merge_records(primary, secondary)
            exact_merge_count += 1
        merged_data.append(primary)

    print(f"Step 2: Merged {exact_merge_count} exact-name duplicates -> {len(merged_data)} records")
    print()

    # ── Step 3: Merge fuzzy variants (same first+last, same dept) ──────────────
    by_norm: dict[tuple, list[int]] = defaultdict(list)
    for i, f in enumerate(merged_data):
        key = normalize_key(f["name"])
        by_norm[key].append(i)

    to_remove = set()
    fuzzy_merge_count = 0

    for key, indices in by_norm.items():
        if len(indices) < 2:
            continue

        # Try all pairs within this group
        entries = [(i, merged_data[i]) for i in indices]

        # Skip groups where all entries are genuinely different people
        # Build merge clusters
        clusters: list[list[int]] = []
        for idx, entry in entries:
            placed = False
            for cluster in clusters:
                # Check if this entry should merge with any member of this cluster
                can_merge = True
                for cidx in cluster:
                    centry = merged_data[cidx]
                    if are_false_positives(entry, centry):
                        can_merge = False
                        break
                    if not same_department_family(entry, centry):
                        can_merge = False
                        break
                if can_merge:
                    cluster.append(idx)
                    placed = True
                    break
            if not placed:
                clusters.append([idx])

        for cluster in clusters:
            if len(cluster) < 2:
                continue

            # Sort: prefer shorter name (canonical), then richness
            cluster_entries = [(i, merged_data[i]) for i in cluster]
            cluster_entries.sort(key=lambda x: (len(x[1]["name"]), -richness_score(x[1])))

            primary_idx, primary = cluster_entries[0]
            for sec_idx, secondary in cluster_entries[1:]:
                print(f"  Fuzzy merge: \"{secondary['name']}\" -> \"{primary['name']}\"")
                merged_data[primary_idx] = merge_records(primary, secondary)
                primary = merged_data[primary_idx]
                to_remove.add(sec_idx)
                fuzzy_merge_count += 1

    final_data = [f for i, f in enumerate(merged_data) if i not in to_remove]
    print(f"\nStep 3: Merged {fuzzy_merge_count} fuzzy variants -> {len(final_data)} records")
    print()

    # ── Summary ────────────────────────────────────────────────────────────────
    total_removed = len(data) + len(junk_removed) - len(final_data)
    print("=" * 60)
    print(f"Original:       {len(data) + len(junk_removed)}")
    print(f"Junk removed:   {len(junk_removed)}")
    print(f"Exact merges:   {exact_merge_count}")
    print(f"Fuzzy merges:   {fuzzy_merge_count}")
    print(f"Final count:    {len(final_data)}")
    print(f"Net reduction:  {total_removed}")

    # Verify affiliations got combined
    with_aff = sum(1 for f in final_data if f.get("affiliations") and len(f["affiliations"]) > 0)
    max_aff = max((len(f.get("affiliations", [])) for f in final_data), default=0)
    print(f"Faculty with affiliations: {with_aff} (max {max_aff} per person)")

    if args.dry_run:
        print("\n[DRY RUN] No files written.")
        return 0

    # Backup and write
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = FACULTY_FILE.with_suffix(f".json.bak.{timestamp}")
    shutil.copy2(FACULTY_FILE, backup)
    print(f"\nBackup: {backup}")

    with open(FACULTY_FILE, "w", encoding="utf-8") as f:
        json.dump(final_data, f, ensure_ascii=False, indent=2)
    print(f"Written: {FACULTY_FILE} ({len(final_data)} records)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
