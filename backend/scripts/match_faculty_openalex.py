"""
Phase 2 Step 1 — match every ISU faculty member to a canonical OpenAlex
author ID.

Strategy: bulk-pull all 74k ISU authors via cursor pagination ONCE, build a
local in-memory name index, then match each of the 3,451 faculty against
the index. ~6 min total instead of ~42 hours per-faculty queries.

Output:
  backend/data/openalex_isu_authors.json    (all 74k authors, raw + extracted fields)
  backend/data/faculty_openalex_match.json  (3,451 faculty -> openalex_id mapping)

Run:
    python backend/scripts/match_faculty_openalex.py
    python backend/scripts/match_faculty_openalex.py --skip-bulk-pull
        (use existing openalex_isu_authors.json without re-downloading)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyalex
from pyalex import Authors

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
FACULTY_JSON = BACKEND / "data" / "faculty.json"
AUTHORS_DUMP = BACKEND / "data" / "openalex_isu_authors.json"
MATCH_OUT = BACKEND / "data" / "faculty_openalex_match.json"

ISU_INSTITUTION_ID = "I173911158"
PER_PAGE = 200


def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2:
            n = f"{parts[1]} {parts[0]}"
    n = re.sub(r"[^A-Za-z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n.lower()


def short_id(openalex_id: str) -> str:
    if not openalex_id:
        return ""
    return openalex_id.split("/")[-1]


def bulk_pull_authors(email: str) -> List[Dict[str, Any]]:
    pyalex.config.email = email
    print(f"Bulk pulling all ISU authors from OpenAlex (per_page={PER_PAGE})...")

    all_authors: List[Dict[str, Any]] = []
    pager = (
        Authors()
        .filter(affiliations={"institution": {"id": ISU_INSTITUTION_ID}})
        .paginate(per_page=PER_PAGE, n_max=None)
    )
    t0 = time.time()
    page_n = 0
    for page in pager:
        page_n += 1
        for author in page:
            all_authors.append({
                "id": short_id(author.get("id", "")),
                "display_name": author.get("display_name") or "",
                "display_name_alternatives": author.get("display_name_alternatives") or [],
                "orcid": author.get("orcid"),
                "works_count": author.get("works_count") or 0,
                "cited_by_count": author.get("cited_by_count") or 0,
                "h_index": (author.get("summary_stats") or {}).get("h_index"),
                "i10_index": (author.get("summary_stats") or {}).get("i10_index"),
                "last_known_institutions": [
                    inst.get("display_name")
                    for inst in (author.get("last_known_institutions") or [])
                ],
            })
        elapsed = time.time() - t0
        rate = len(all_authors) / max(elapsed, 0.01)
        print(
            f"  page {page_n}: {len(all_authors)} authors so far ({rate:.0f}/s)",
            flush=True,
        )

    print(f"Done. {len(all_authors)} ISU authors pulled in {(time.time()-t0)/60:.1f} min")
    return all_authors


def build_name_index(authors: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Map normalized name -> list of author records."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for a in authors:
        name = a.get("display_name") or ""
        idx[normalize_name(name)].append(a)
        # Also index alternative names
        for alt in a.get("display_name_alternatives") or []:
            idx[normalize_name(alt)].append(a)
    return idx


def pick_best(name: str, candidates: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], float]:
    """Pick the best matching author from a list of candidates with the same normalized name."""
    if not candidates:
        return None, 0.0
    if len(candidates) == 1:
        return candidates[0], 0.92
    # Multiple authors share this name. Heuristic: pick the one whose
    # display_name (NOT just normalized) is exactly equal — capitalization can differ.
    target = name.strip()
    exact = [c for c in candidates if (c.get("display_name") or "").strip() == target]
    if len(exact) == 1:
        return exact[0], 0.85
    # Otherwise pick the one with the most works (heuristic for "main" identity)
    sorted_by_works = sorted(candidates, key=lambda c: -(c.get("works_count") or 0))
    # If the top is dramatically larger than #2, take it
    top = sorted_by_works[0]
    if (top.get("works_count") or 0) >= 3 * ((sorted_by_works[1].get("works_count") or 1) if len(sorted_by_works) > 1 else 1):
        return top, 0.7
    return top, 0.55


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="adisak.sukul@gmail.com",
                        help="Email for OpenAlex polite pool")
    parser.add_argument("--skip-bulk-pull", action="store_true",
                        help="Reuse the existing openalex_isu_authors.json")
    args = parser.parse_args()

    # ---------- 1. Pull (or reuse) all ISU authors ----------
    if args.skip_bulk_pull and AUTHORS_DUMP.exists():
        print(f"Reusing {AUTHORS_DUMP}")
        with AUTHORS_DUMP.open(encoding="utf-8") as f:
            authors = json.load(f)
        print(f"  {len(authors)} authors loaded")
    else:
        authors = bulk_pull_authors(args.email)
        AUTHORS_DUMP.parent.mkdir(parents=True, exist_ok=True)
        with AUTHORS_DUMP.open("w", encoding="utf-8") as f:
            json.dump(authors, f, ensure_ascii=False)
        print(f"  saved to {AUTHORS_DUMP}")

    # ---------- 2. Build name index ----------
    print()
    print("Building name index...")
    idx = build_name_index(authors)
    print(f"  {len(idx)} unique normalized names")

    # ---------- 3. Match each faculty ----------
    print()
    print("Matching faculty.json against the index...")
    with FACULTY_JSON.open(encoding="utf-8") as f:
        faculty = json.load(f)

    results: List[Dict[str, Any]] = []
    matched = no_match = ambiguous = 0

    for fac in faculty:
        name = fac.get("name") or ""
        norm = normalize_name(name)
        candidates = idx.get(norm, [])
        picked, conf = pick_best(name, candidates)

        rec: Dict[str, Any] = {
            "faculty_id": fac.get("id"),
            "name": name,
            "department": fac.get("department"),
            "candidates": len(candidates),
            "openalex_id": None,
            "openalex_display_name": None,
            "confidence": conf,
            "works_count": None,
            "cited_by_count": None,
            "h_index": None,
            "i10_index": None,
            "orcid": None,
        }
        if picked:
            rec["openalex_id"] = picked["id"]
            rec["openalex_display_name"] = picked.get("display_name")
            rec["works_count"] = picked.get("works_count")
            rec["cited_by_count"] = picked.get("cited_by_count")
            rec["h_index"] = picked.get("h_index")
            rec["i10_index"] = picked.get("i10_index")
            rec["orcid"] = picked.get("orcid")
            matched += 1
            if len(candidates) > 1:
                ambiguous += 1
        else:
            no_match += 1

        results.append(rec)

    MATCH_OUT.parent.mkdir(parents=True, exist_ok=True)
    with MATCH_OUT.open("w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"Matching done. Wrote {len(results)} rows to {MATCH_OUT}")
    print(f"  matched:   {matched} ({100*matched/len(results):.1f}%)")
    print(f"  no_match:  {no_match}")
    print(f"  ambiguous: {ambiguous} (had >1 candidate)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
