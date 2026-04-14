"""
Recover department info for items missing it in dspace_index.db.

Three enrichment passes, applied in order of confidence:

  Pass 1 — OAI contributor metadata (highest confidence)
    The OAI-PMH harvest stores dc:contributor values as a 'contributors'
    list.  For theses, this contains advisor names and department names.
    Match OAI records to DB items by title.  For each contributor:
      a) If it looks like a department name -> use it directly.
      b) If it looks like a person name -> look up in faculty.json.

  Pass 2 — Same-author department propagation
    If the same author string appears on another item that already HAS a
    department, propagate that department.  Only used when a single
    department dominates (>=60 % of that author's publications).

  Pass 3 — Author -> faculty.json match
    Match the item's own authors against faculty.json (same approach as
    enrich_departments.py, but runs only on items still missing after
    passes 1-2).

Run:
    python scripts/enrich_dept_advisors.py
    python scripts/enrich_dept_advisors.py --dry-run
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
FACULTY_FILE = BACKEND / "data" / "faculty.json"
OAI_FILE = BACKEND / "data" / "dspace" / "oai_harvest.jsonl"

# Minimum ratio of an author's publications in one dept to propagate
SAME_AUTHOR_MIN_RATIO = 0.60
SAME_AUTHOR_MIN_COUNT = 1  # need at least 1 item with that dept


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """Normalize to 'first last' lowercase, strip middle names/initials."""
    n = name.strip()
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2:
            n = f"{parts[1]} {parts[0]}"
    n = re.sub(r"\b(Jr\.?|Sr\.?|III|IV|II|Ph\.?D\.?|M\.?D\.?|Dr\.?)\b",
               "", n, flags=re.I)
    n = re.sub(r"[^a-zA-Z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip().lower()
    return n


def name_key(name: str) -> tuple[str, str]:
    """Extract (first, last) from normalized name."""
    parts = name.split()
    if len(parts) >= 2:
        return (parts[0], parts[-1])
    return (name, "")


# ---------------------------------------------------------------------------
# Department detection heuristics
# ---------------------------------------------------------------------------

DEPT_KEYWORDS = [
    "department", "school of", "program", "center for", "institute",
    "laboratory", "lab ", "college of", "extension", "interdepartmental",
]

# Single-word or short department names that could be mistaken for person names
KNOWN_SHORT_DEPTS = {
    "english", "zoology", "chemistry", "physics", "mathematics",
    "statistics", "botany", "geology", "history", "philosophy",
    "sociology", "anthropology", "psychology", "economics", "accounting",
    "architecture", "genetics", "agronomy", "entomology", "forestry",
    "horticulture", "meteorology", "microbiology", "kinesiology",
    "curriculum and instruction", "art and design", "art and visual culture",
    "music", "theatre", "rhetoric and professional communication",
    "world languages and cultures", "theses and dissertations",
    "veterinary pathology", "veterinary microbiology",
    "veterinary clinical sciences",
    "veterinary diagnostic and production animal medicine",
}


def looks_like_department(text: str, known_depts: set[str]) -> bool:
    """Heuristic: does this contributor string look like a department?"""
    t = text.strip()
    tl = t.lower()

    if tl in known_depts:
        return True
    if tl.startswith("department of "):
        core = tl[len("department of "):]
        if core in known_depts:
            return True
    for kw in DEPT_KEYWORDS:
        if kw in tl:
            return True
    if tl in KNOWN_SHORT_DEPTS:
        return True
    # Parenthetical college abbreviation: (LAS), (ENG), (CALS)
    if re.search(r"\([A-Z]{2,}\)", t):
        return True
    # Multi-word containing "and" + "Science/Engineering/Studies/Education"
    if re.search(r"\b(sciences?|engineering|studies|education)\b", tl, re.I):
        return True

    return False


def normalize_department(raw: str, canonical: dict[str, str]) -> str:
    """Map a raw department string to its canonical DB form if possible."""
    r = raw.strip()
    rl = r.lower()
    if rl in canonical:
        return canonical[rl]
    if rl.startswith("department of "):
        core = rl[len("department of "):]
        if core in canonical:
            return canonical[core]
    prefixed = f"department of {rl}"
    if prefixed in canonical:
        return canonical[prefixed]
    return r


# ---------------------------------------------------------------------------
# Faculty index
# ---------------------------------------------------------------------------

def build_faculty_index(faculty: list[dict]) -> dict:
    by_full: dict[str, list[dict]] = defaultdict(list)
    by_fl: dict[tuple, list[dict]] = defaultdict(list)
    for f in faculty:
        name = f.get("name", "")
        dept = f.get("department", "")
        if not name or not dept or dept == "Unknown Department":
            continue
        norm = normalize_name(name)
        if not norm:
            continue
        by_full[norm].append(f)
        key = name_key(norm)
        if key[0] and key[1]:
            by_fl[key].append(f)
    return {"full": by_full, "first_last": by_fl}


def faculty_dept(name_str: str, fac_index: dict) -> str | None:
    """Return the department for a person name via faculty.json, or None."""
    norm = normalize_name(name_str)
    if not norm or len(norm) < 4:
        return None
    # Exact full name
    ms = fac_index["full"].get(norm, [])
    if len(ms) == 1:
        return ms[0].get("department")
    if len(ms) > 1:
        ds = [m["department"] for m in ms if m.get("department")]
        if ds:
            return max(set(ds), key=ds.count)
    # First+Last
    key = name_key(norm)
    if key[0] and key[1]:
        ms = fac_index["first_last"].get(key, [])
        if len(ms) == 1:
            return ms[0].get("department")
    return None


# ---------------------------------------------------------------------------
# OAI contributor extraction (Pass 1 helper)
# ---------------------------------------------------------------------------

def dept_from_contributors(
    contributors: list[str],
    known_lower: set[str],
    canonical: dict[str, str],
    fac_idx: dict,
) -> tuple[str | None, str]:
    """Return (dept, source) from OAI contributors list.
    source is 'oai_direct' or 'oai_advisor', or '' on failure.
    """
    # Prefer direct department names (iterate backwards: dept is usually last)
    for c in reversed(contributors):
        if looks_like_department(c, known_lower):
            return normalize_department(c, canonical), "oai_direct"
    # Try advisor -> faculty match
    for c in contributors:
        if looks_like_department(c, known_lower):
            continue
        d = faculty_dept(c, fac_idx)
        if d:
            return d, "oai_advisor"
    return None, ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich department field via OAI advisors, author propagation, and faculty match"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    # ── Load faculty ─────────────────────────────────────────────────
    print(f"Loading faculty from {FACULTY_FILE} ...")
    with open(FACULTY_FILE, encoding="utf-8") as f:
        faculty = json.load(f)
    fac_idx = build_faculty_index(faculty)
    print(f"  {len(faculty):,} faculty -> "
          f"{len(fac_idx['full']):,} full-name keys, "
          f"{len(fac_idx['first_last']):,} first+last keys")

    # ── Open DB ──────────────────────────────────────────────────────
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    total_items = conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
    before_missing = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NULL OR department = ''"
    ).fetchone()[0]
    print(f"\nDB: {total_items:,} items, {before_missing:,} missing department "
          f"({100*before_missing/total_items:.1f}%)")

    # ── Build canonical dept lookup ──────────────────────────────────
    known_raw = set()
    for row in conn.execute(
        "SELECT DISTINCT department FROM items "
        "WHERE department IS NOT NULL AND department != ''"
    ):
        known_raw.add(row["department"])
    canonical: dict[str, str] = {}
    for d in known_raw:
        canonical[d.lower()] = d
        dl = d.lower()
        if dl.startswith("department of "):
            core = dl[len("department of "):]
            if core not in canonical:
                canonical[core] = d
    known_lower = set(canonical.keys())
    print(f"  {len(known_raw)} known departments, {len(canonical)} lookup keys")

    # ── Load items missing department ────────────────────────────────
    missing = conn.execute("""
        SELECT uuid, title, authors_json, collection_name FROM items
        WHERE (department IS NULL OR department = '')
    """).fetchall()
    # Index by title (lowercase) and by uuid
    title_to_missing: dict[str, list[dict]] = defaultdict(list)
    missing_uuids: set[str] = set()
    missing_by_uuid: dict[str, dict] = {}
    for row in missing:
        info = {
            "uuid": row["uuid"],
            "title": row["title"] or "",
            "authors_json": row["authors_json"] or "[]",
            "collection_name": row["collection_name"] or "",
        }
        t = info["title"].strip().lower()
        if t:
            title_to_missing[t].append(info)
        missing_uuids.add(info["uuid"])
        missing_by_uuid[info["uuid"]] = info

    print(f"  {len(missing):,} items missing department")

    # Track all updates: uuid -> (dept, source)
    updates: dict[str, tuple[str, str]] = {}

    # ==================================================================
    # PASS 1: OAI contributor metadata
    # ==================================================================
    print(f"\n{'='*60}")
    print("Pass 1: OAI contributor metadata")
    print(f"  Loading {OAI_FILE} ...")

    oai_by_title: dict[str, list[str]] = {}
    oai_total = 0
    with open(OAI_FILE, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            oai_total += 1
            contribs = rec.get("contributors", [])
            if not contribs:
                continue
            t = (rec.get("title", "") or "").strip().lower()
            if t:
                oai_by_title[t] = contribs
    print(f"  {oai_total:,} OAI records, {len(oai_by_title):,} with title+contributors")

    p1_direct = 0
    p1_advisor = 0
    p1_no_match = 0
    p1_no_dept = 0
    for title_lower, items in title_to_missing.items():
        contribs = oai_by_title.get(title_lower)
        if not contribs:
            p1_no_match += len(items)
            continue
        dept, source = dept_from_contributors(contribs, known_lower, canonical, fac_idx)
        if not dept:
            p1_no_dept += len(items)
            continue
        for item in items:
            uid = item["uuid"]
            if uid not in updates:
                updates[uid] = (dept, source)
                if source == "oai_direct":
                    p1_direct += 1
                else:
                    p1_advisor += 1

    p1_total = p1_direct + p1_advisor
    print(f"  Matched: {p1_total:,}  (direct dept: {p1_direct:,}, "
          f"advisor->faculty: {p1_advisor:,})")
    print(f"  No OAI title match: {p1_no_match:,} items")
    print(f"  No dept from OAI contribs: {p1_no_dept:,} items")

    # ==================================================================
    # PASS 2: Same-author department propagation
    # ==================================================================
    print(f"\n{'='*60}")
    print("Pass 2: Same-author department propagation")

    # Build author -> department counter from items WITH department
    print("  Building author->department index from DB ...")
    author_depts: dict[str, Counter] = defaultdict(Counter)
    for row in conn.execute("""
        SELECT authors_json, department FROM items
        WHERE department IS NOT NULL AND department != ''
        AND authors_json IS NOT NULL AND authors_json != '[]'
    """):
        dept = row["department"]
        try:
            authors = json.loads(row["authors_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        for a in authors:
            a = a.strip()
            if a:
                author_depts[a.lower()][dept] += 1
    print(f"  {len(author_depts):,} unique author strings with department info")

    p2_count = 0
    still_missing = [uid for uid in missing_uuids if uid not in updates]
    for uid in still_missing:
        info = missing_by_uuid[uid]
        try:
            authors = json.loads(info["authors_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        best_dept = None
        best_score = 0.0
        for a in authors:
            al = a.strip().lower()
            if not al:
                continue
            cnts = author_depts.get(al)
            if not cnts:
                continue
            top_dept, top_count = cnts.most_common(1)[0]
            total_for_author = sum(cnts.values())
            ratio = top_count / total_for_author
            if (ratio >= SAME_AUTHOR_MIN_RATIO
                    and top_count >= SAME_AUTHOR_MIN_COUNT
                    and ratio > best_score):
                best_dept = top_dept
                best_score = ratio
        if best_dept:
            updates[uid] = (best_dept, "same_author")
            p2_count += 1

    print(f"  Matched: {p2_count:,} items via same-author propagation")

    # ==================================================================
    # PASS 3: Author -> faculty.json match (items still missing)
    # ==================================================================
    print(f"\n{'='*60}")
    print("Pass 3: Author -> faculty.json match")

    p3_count = 0
    still_missing2 = [uid for uid in missing_uuids if uid not in updates]
    for uid in still_missing2:
        info = missing_by_uuid[uid]
        try:
            authors = json.loads(info["authors_json"])
        except (json.JSONDecodeError, TypeError):
            continue
        for a in authors:
            d = faculty_dept(a, fac_idx)
            if d:
                updates[uid] = (d, "faculty_match")
                p3_count += 1
                break

    print(f"  Matched: {p3_count:,} items via direct faculty match")

    # ==================================================================
    # Apply updates
    # ==================================================================
    grand_total = len(updates)
    print(f"\n{'='*60}")
    print(f"Total items to update: {grand_total:,}")

    # Breakdown by source
    src_counts: Counter = Counter()
    coll_counts: Counter = Counter()
    for uid, (dept, src) in updates.items():
        src_counts[src] += 1
        coll_counts[missing_by_uuid[uid]["collection_name"]] += 1

    print("  By source:")
    for src, cnt in src_counts.most_common():
        print(f"    {cnt:>6}  {src}")
    print("  By collection:")
    for coll, cnt in coll_counts.most_common():
        print(f"    {cnt:>6}  {coll}")

    if not args.dry_run and updates:
        print(f"\nWriting {grand_total:,} updates to {INDEX_DB} ...")
        for i, (uid, (dept, _src)) in enumerate(updates.items()):
            conn.execute(
                "UPDATE items SET department = ? WHERE uuid = ?",
                (dept, uid),
            )
            if (i + 1) % 1000 == 0:
                conn.commit()
                print(f"  committed {i+1:,} / {grand_total:,}")
        conn.commit()
        print(f"  Done. All {grand_total:,} updates committed.")
    elif args.dry_run:
        print(f"\n[DRY RUN] Would update {grand_total:,} items.")

    # ── Final report ─────────────────────────────────────────────────
    after_missing = conn.execute(
        "SELECT COUNT(*) FROM items WHERE department IS NULL OR department = ''"
    ).fetchone()[0]
    conn.close()

    covered = total_items - after_missing
    print(f"\n{'='*60}")
    print(f"RESULT  {'(committed)' if not args.dry_run else '(dry-run)'}")
    print(f"  Before:  {before_missing:,} missing department")
    print(f"  Updated: {grand_total:,}")
    print(f"  After:   {after_missing:,} missing department")
    print(f"  Coverage: {covered:,} / {total_items:,} ({100*covered/total_items:.1f}%)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
