#!/usr/bin/env python3
"""
Merge the scraped faculty-sites directory data into the existing faculty.json.

Matching strategy (in priority order):
  1. Exact normalized name match (lowercase, stripped, no punctuation)
  2. Name-parts set match (handles reordering, dropped middle initials)
  3. Last-name + first-name-prefix match (catches Steve/Steven, Cliff/Clifford, etc.)
  4. Slug from URL matched against faculty record id

Adds/updates the `faculty_site_url` field on matched records.
Reports matched, unmatched, and total counts.
"""

import json
import re
import sys
import unicodedata
from pathlib import Path

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
FACULTY_JSON = DATA_DIR / "faculty.json"
SITES_JSON = DATA_DIR / "faculty_sites_directory.json"

# Common title/suffix tokens to strip before matching
STRIP_TOKENS = {
    "phd", "ph d", "md", "dvm", "pe", "aia", "leed", "ap", "gisp",
    "jr", "sr", "ii", "iii", "iv", "dr", "prof", "professor",
}


def normalize(name: str) -> str:
    """Lowercase, strip accents, collapse whitespace, remove punctuation."""
    nfkd = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Also handle non-breaking spaces and other unicode whitespace
    s = stripped.lower().strip()
    s = re.sub(r"[.,'\"\-()@]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def clean_name(name: str) -> str:
    """Normalize and remove titles/suffixes."""
    n = normalize(name)
    parts = n.split()
    cleaned = [p for p in parts if p not in STRIP_TOKENS]
    return " ".join(cleaned)


def name_parts(name: str) -> list[str]:
    """Return ordered word-parts of a cleaned name."""
    return clean_name(name).split()


def last_name(parts: list[str]) -> str:
    """Guess last name (last token)."""
    return parts[-1] if parts else ""


def first_name(parts: list[str]) -> str:
    """Guess first name (first token)."""
    return parts[0] if parts else ""


def extract_url_slug(url: str) -> str:
    """Extract the username slug from a faculty.sites URL."""
    # https://faculty.sites.iastate.edu/pavan/ -> pavan
    m = re.search(r"faculty\.sites\.iastate\.edu/([^/]+)", url)
    return m.group(1).lower() if m else ""


def main():
    # Load data
    with open(FACULTY_JSON, "r", encoding="utf-8") as f:
        faculty = json.load(f)
    with open(SITES_JSON, "r", encoding="utf-8") as f:
        sites = json.load(f)

    print(f"Faculty database: {len(faculty)} entries")
    print(f"Faculty sites directory: {len(sites)} entries")

    # ---- Build indexes on faculty.json ----

    # Index 1: exact cleaned name -> list of (index, cleaned_name)
    exact_index: dict[str, list[int]] = {}
    for i, rec in enumerate(faculty):
        key = clean_name(rec["name"])
        exact_index.setdefault(key, []).append(i)

    # Index 2: frozenset of name parts -> list of faculty indices
    parts_index: dict[frozenset, list[int]] = {}
    for i, rec in enumerate(faculty):
        parts = name_parts(rec["name"])
        key = frozenset(parts)
        if len(key) >= 2:
            parts_index.setdefault(key, []).append(i)

    # Index 3: last_name -> list of (index, first_name, full_parts)
    lastname_index: dict[str, list[tuple[int, str, list[str]]]] = {}
    for i, rec in enumerate(faculty):
        parts = name_parts(rec["name"])
        if len(parts) >= 2:
            ln = last_name(parts)
            fn = first_name(parts)
            lastname_index.setdefault(ln, []).append((i, fn, parts))

    # Index 4: faculty id -> index
    id_index: dict[str, int] = {}
    for i, rec in enumerate(faculty):
        fid = rec.get("id", "")
        if fid:
            id_index[fid] = i

    matched = 0
    matched_details = []
    unmatched_list = []

    for site_entry in sites:
        site_name = site_entry["name"]
        site_url = site_entry["faculty_site_url"]
        cleaned = clean_name(site_name)
        site_p = name_parts(site_name)
        site_ln = last_name(site_p)
        site_fn = first_name(site_p)
        url_slug = extract_url_slug(site_url)

        match_indices = None
        match_method = ""

        # Strategy 1: exact cleaned name match
        if cleaned in exact_index:
            match_indices = exact_index[cleaned]
            match_method = "exact"

        # Strategy 2: name parts set match (reordering, middle initials dropped)
        if match_indices is None and len(site_p) >= 2:
            site_set = frozenset(site_p)
            if site_set in parts_index:
                match_indices = parts_index[site_set]
                match_method = "parts-exact"

        # Strategy 2b: subset/superset parts match
        if match_indices is None and len(site_p) >= 2:
            site_set = frozenset(site_p)
            best = None
            best_score = 0
            for fkey, indices in parts_index.items():
                if len(fkey) < 2:
                    continue
                overlap = len(site_set & fkey)
                if overlap >= 2:
                    ratio = overlap / max(len(site_set), len(fkey))
                    if ratio > best_score and ratio >= 0.65:
                        best_score = ratio
                        best = indices
            if best:
                match_indices = best
                match_method = f"parts-overlap({best_score:.0%})"

        # Strategy 3: last name + first name prefix (Steve/Steven, Cliff/Clifford, etc.)
        if match_indices is None and site_ln in lastname_index and len(site_fn) >= 3:
            candidates = lastname_index[site_ln]
            for idx, fac_fn, fac_parts in candidates:
                # Check if one first name starts with the other (min 3 chars)
                if (fac_fn.startswith(site_fn[:3]) or site_fn.startswith(fac_fn[:3])):
                    match_indices = [idx]
                    match_method = f"lastname+prefix({site_fn}/{fac_fn})"
                    break

        # Strategy 4: URL slug matches faculty id
        if match_indices is None and url_slug and url_slug in id_index:
            match_indices = [id_index[url_slug]]
            match_method = f"id-slug({url_slug})"

        # Strategy 5: URL slug appears in a faculty name or id (partial)
        if match_indices is None and url_slug and len(url_slug) >= 4:
            for i, rec in enumerate(faculty):
                fid = rec.get("id", "")
                if url_slug in fid or fid in url_slug:
                    # Verify last name matches to avoid false positives
                    fac_p = name_parts(rec["name"])
                    fac_ln = last_name(fac_p)
                    if fac_ln == site_ln:
                        match_indices = [i]
                        match_method = f"slug-in-id({url_slug}/{fid})"
                        break

        if match_indices:
            for idx in match_indices:
                faculty[idx]["faculty_site_url"] = site_url
            matched += 1
            matched_details.append(
                f"  {site_name:45s} -> {faculty[match_indices[0]]['name']:45s} [{match_method}]"
            )
        else:
            unmatched_list.append(site_entry)

    # Save updated faculty.json
    with open(FACULTY_JSON, "w", encoding="utf-8") as f:
        json.dump(faculty, f, indent=2, ensure_ascii=False)

    # Count how many faculty records now have the field
    with_url = sum(1 for rec in faculty if "faculty_site_url" in rec)

    print(f"\n{'='*60}")
    print(f"RESULTS")
    print(f"{'='*60}")
    print(f"Matched:   {matched} / {len(sites)} site entries")
    print(f"Unmatched: {len(unmatched_list)} site entries (not found in faculty.json)")
    print(f"Faculty records now with faculty_site_url: {with_url}")
    print(f"Faculty database total: {len(faculty)}")

    # Print match details
    print(f"\n--- Match details ({matched}) ---")
    for line in matched_details:
        print(line)

    if unmatched_list:
        print(f"\n--- Unmatched entries ({len(unmatched_list)}) ---")
        for entry in sorted(unmatched_list, key=lambda e: e["name"]):
            print(f"  {entry['name']:45s}  {entry['faculty_site_url']}")

    # Save unmatched to a separate file for review
    unmatched_path = DATA_DIR / "faculty_sites_unmatched.json"
    with open(unmatched_path, "w", encoding="utf-8") as f:
        json.dump(unmatched_list, f, indent=2, ensure_ascii=False)
    print(f"\nUnmatched entries saved to {unmatched_path}")
    print(f"Updated faculty.json saved to {FACULTY_JSON}")


if __name__ == "__main__":
    main()
