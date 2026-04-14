"""
Phase 2 Step 3 / Phase 3 — Reconcile DSpace items + OpenAlex works into a
single canonical paper table with multi-source provenance.

Inputs:
  backend/data/dspace/dspace_index.db    (existing DSpace SQLite, 82k items)
  backend/data/openalex_works_isu.jsonl  (bulk-pulled OpenAlex works for ISU)

Output:
  backend/data/dspace/papers.db
    papers_canonical
    paper_sources
    (paper_overrides stays empty until users edit anything)

Reconciliation rules (in order):
  1. STRONG MATCH: same DOI (normalized to lowercase, strip 'https://doi.org/')
  2. MEDIUM MATCH: title fuzzy ≥ 0.92 (token Jaccard) AND year matches AND
     first-author last name matches
  3. WEAK MATCH: title fuzzy ≥ 0.97 with no year/author signal — flagged but
     auto-merged anyway
  4. Otherwise distinct

Run:
    python backend/scripts/reconcile_papers.py
    python backend/scripts/reconcile_papers.py --dry-run
    python backend/scripts/reconcile_papers.py --limit-openalex 1000
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DSPACE_INDEX = BACKEND / "data" / "dspace" / "dspace_index.db"
OPENALEX_JSONL = BACKEND / "data" / "openalex_works_isu.jsonl"
PAPERS_DB = BACKEND / "data" / "dspace" / "papers.db"

# How many DSpace papers per match attempt — used to bucket the dedup pass
TITLE_TOKEN_MIN_LEN = 4

# ---------------------------------------------------------------------------
# Normalizers
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_doi(doi: Optional[str]) -> Optional[str]:
    if not doi:
        return None
    d = doi.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if d.startswith(prefix):
            d = d[len(prefix):]
    return d or None


_TITLE_STOP = {"a", "an", "the", "of", "and", "or", "in", "on", "for", "to", "by", "with", "from"}


def normalize_title(title: Optional[str]) -> str:
    if not title:
        return ""
    t = title.lower()
    t = re.sub(r"<[^>]+>", "", t)            # strip HTML tags
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def title_tokens(title: Optional[str]) -> set:
    norm = normalize_title(title)
    return {
        t for t in norm.split()
        if len(t) >= TITLE_TOKEN_MIN_LEN and t not in _TITLE_STOP
    }


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = a & b
    union = a | b
    if not union:
        return 0.0
    return len(inter) / len(union)


def first_author_last_name(author_str_or_list: Any) -> str:
    """Get the last name of the first author."""
    if isinstance(author_str_or_list, list):
        if not author_str_or_list:
            return ""
        first = author_str_or_list[0]
    else:
        first = author_str_or_list or ""
    if isinstance(first, dict):
        first = first.get("name") or first.get("display_name") or ""
    if not first:
        return ""
    if "," in first:
        return first.split(",", 1)[0].strip().lower()
    parts = first.strip().split()
    return parts[-1].lower() if parts else ""


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_dspace_papers() -> List[Dict[str, Any]]:
    src = sqlite3.connect(f"file:{DSPACE_INDEX}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    rows = src.execute(
        """
        SELECT uuid, title, year, type, abstract, dspace_url, authors_json,
               department, collection_name
        FROM items
        """
    ).fetchall()
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            authors = json.loads(r["authors_json"]) if r["authors_json"] else []
        except Exception:
            authors = []
        try:
            year = int(r["year"]) if r["year"] and str(r["year"]).strip().isdigit() else None
        except Exception:
            year = None
        out.append({
            "uuid": r["uuid"],
            "title": r["title"] or "",
            "year": year,
            "type": r["type"] or "",
            "abstract": r["abstract"] or "",
            "dspace_url": r["dspace_url"] or "",
            "authors": authors,
            "department": r["department"] or "",
            "collection": r["collection_name"] or "",
            "doi": None,  # DSpace harvest doesn't capture DOI cleanly
        })
    src.close()
    return out


def iter_openalex_works(limit: int = 0) -> Iterable[Dict[str, Any]]:
    if not OPENALEX_JSONL.exists():
        return
    seen = set()
    n = 0
    with OPENALEX_JSONL.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                w = json.loads(line)
            except Exception:
                continue
            wid = w.get("id")
            if not wid or wid in seen:
                continue
            seen.add(wid)
            yield w
            n += 1
            if limit and n >= limit:
                break


# ---------------------------------------------------------------------------
# Schema (mirror of paper_reconcile_service)
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
DROP TABLE IF EXISTS papers_canonical;
DROP TABLE IF EXISTS paper_sources;
DROP TABLE IF EXISTS paper_overrides;

CREATE TABLE papers_canonical (
    canonical_id          TEXT PRIMARY KEY,
    canonical_doi         TEXT,
    canonical_title       TEXT NOT NULL,
    canonical_year        INTEGER,
    canonical_type        TEXT,
    canonical_first_author TEXT,
    confidence            REAL NOT NULL DEFAULT 1.0,
    last_updated          TEXT NOT NULL
);

CREATE INDEX idx_canon_doi   ON papers_canonical(canonical_doi);
CREATE INDEX idx_canon_title ON papers_canonical(canonical_title);

CREATE TABLE paper_sources (
    canonical_id   TEXT NOT NULL,
    source         TEXT NOT NULL,
    source_id      TEXT NOT NULL,
    title          TEXT,
    authors_json   TEXT,
    year           INTEGER,
    venue          TEXT,
    doi            TEXT,
    abstract       TEXT,
    cited_by_count INTEGER,
    raw_payload    TEXT,
    fetched_at     TEXT NOT NULL,
    PRIMARY KEY (canonical_id, source, source_id)
);

CREATE INDEX idx_psources_doi   ON paper_sources(doi);
CREATE INDEX idx_psources_canon ON paper_sources(canonical_id);

CREATE TABLE paper_overrides (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    canonical_id  TEXT NOT NULL,
    user_id       INTEGER NOT NULL,
    action        TEXT NOT NULL,
    field         TEXT,
    payload_json  TEXT,
    rationale     TEXT,
    created_at    TEXT NOT NULL,
    deleted_at    TEXT
);

CREATE INDEX idx_overrides_canon ON paper_overrides(canonical_id);
CREATE INDEX idx_overrides_user  ON paper_overrides(user_id);
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit-openalex", type=int, default=0,
                        help="Process only first N OpenAlex works")
    args = parser.parse_args()

    if not DSPACE_INDEX.exists():
        print(f"ERROR: dspace_index.db not found at {DSPACE_INDEX}", file=sys.stderr)
        return 2
    if not OPENALEX_JSONL.exists():
        print(f"WARN: {OPENALEX_JSONL} not found — OpenAlex bulk pull may not be done yet")
        print(f"      Will proceed with DSpace-only canonical paper records.")

    print(f"Loading DSpace papers from {DSPACE_INDEX} ...")
    dspace_papers = load_dspace_papers()
    print(f"  loaded {len(dspace_papers)} DSpace items")

    # ---- Open output db ----
    if args.dry_run:
        out = sqlite3.connect(":memory:")
    else:
        # Write to a temp file first, then swap. This avoids PermissionError
        # when Dropbox/antivirus has a brief lock on the existing file.
        tmp_db = PAPERS_DB.with_suffix(".db.tmp")
        if tmp_db.exists():
            tmp_db.unlink()
        out = sqlite3.connect(tmp_db)
    out.executescript(SCHEMA_SQL)
    cur = out.cursor()

    # ---- Build DSpace lookup indexes ----
    print("Indexing DSpace papers by title tokens...")
    by_doi: Dict[str, str] = {}            # normalized doi -> canonical_id
    by_norm_title: Dict[str, List[str]] = defaultdict(list)  # exact normalized title -> list of canonical_ids
    by_token_first: Dict[str, List[str]] = defaultdict(list)  # token -> canonical_ids

    canonical_records: Dict[str, Dict[str, Any]] = {}

    # Seed canonical records from DSpace
    for p in dspace_papers:
        canonical_id = f"paper:dspace:{p['uuid']}"
        first_author_last = first_author_last_name(p["authors"])
        canonical_records[canonical_id] = {
            "canonical_id": canonical_id,
            "canonical_doi": normalize_doi(p["doi"]),
            "canonical_title": p["title"],
            "canonical_year": p["year"],
            "canonical_type": p["type"],
            "canonical_first_author": first_author_last,
            "confidence": 1.0,
            "last_updated": now_iso(),
            "_dspace": p,
        }
        if p["doi"]:
            d = normalize_doi(p["doi"])
            if d:
                by_doi[d] = canonical_id
        nt = normalize_title(p["title"])
        if nt:
            by_norm_title[nt].append(canonical_id)
        for tok in title_tokens(p["title"]):
            by_token_first[tok].append(canonical_id)

    print(f"  {len(by_doi)} DSpace papers with DOI, {len(by_norm_title)} unique normalized titles")

    # ---- Walk OpenAlex works, match against DSpace ----
    print()
    print(f"Walking OpenAlex works from {OPENALEX_JSONL} ...")
    n_strong = n_medium = n_new = n_seen = 0
    n_dspace_paper_total = len(canonical_records)
    t0 = time.time()

    for w in iter_openalex_works(args.limit_openalex):
        n_seen += 1
        wid = w["id"]
        wdoi = normalize_doi(w.get("doi"))
        wtitle = w.get("title") or ""
        wyear = w.get("publication_year")
        wauthors = [a.get("name", "") for a in (w.get("authors") or [])]
        w_first_last = first_author_last_name(wauthors)

        matched_canon: Optional[str] = None

        # Strong match: DOI
        if wdoi and wdoi in by_doi:
            matched_canon = by_doi[wdoi]
            n_strong += 1
        else:
            # Medium match: title token Jaccard ≥ 0.92 AND year matches AND first-author last name matches
            wtoks = title_tokens(wtitle)
            if wtoks:
                # Find candidate canonicals via token overlap
                candidate_counts: Dict[str, int] = defaultdict(int)
                for tok in wtoks:
                    if tok in by_token_first:
                        for cid in by_token_first[tok]:
                            candidate_counts[cid] += 1
                # Score top candidates
                for cid, _ in sorted(candidate_counts.items(), key=lambda x: -x[1])[:5]:
                    crec = canonical_records[cid]
                    cp = crec.get("_dspace") or crec.get("_openalex")
                    if not cp:
                        continue
                    cp_title = cp.get("title", "")
                    ctoks = title_tokens(cp_title)
                    sim = jaccard(wtoks, ctoks)
                    if sim >= 0.92:
                        if (
                            wyear is None
                            or crec["canonical_year"] is None
                            or wyear == crec["canonical_year"]
                            or abs(wyear - crec["canonical_year"]) <= 1
                        ) and (
                            not w_first_last
                            or not crec["canonical_first_author"]
                            or w_first_last == crec["canonical_first_author"]
                        ):
                            matched_canon = cid
                            n_medium += 1
                            break
                    elif sim >= 0.97:
                        # Weak match — auto-merge but with reduced confidence
                        matched_canon = cid
                        crec["confidence"] = min(crec["confidence"], 0.7)
                        n_medium += 1
                        break

        if matched_canon is None:
            # New canonical from OpenAlex
            canonical_id = f"paper:openalex:{wid}"
            canonical_records[canonical_id] = {
                "canonical_id": canonical_id,
                "canonical_doi": wdoi,
                "canonical_title": wtitle,
                "canonical_year": wyear,
                "canonical_type": w.get("type"),
                "canonical_first_author": w_first_last,
                "confidence": 0.95,
                "last_updated": now_iso(),
                "_openalex": w,
            }
            matched_canon = canonical_id
            n_new += 1
            if wdoi:
                by_doi[wdoi] = canonical_id
            for tok in title_tokens(wtitle):
                by_token_first[tok].append(canonical_id)
        else:
            # Attach OpenAlex source to the matched canonical
            canonical_records[matched_canon].setdefault("_openalex", w)
            # If DSpace canonical doesn't have a DOI but OpenAlex does, fill it in
            if wdoi and not canonical_records[matched_canon].get("canonical_doi"):
                canonical_records[matched_canon]["canonical_doi"] = wdoi

        if n_seen % 5000 == 0:
            elapsed = time.time() - t0
            print(
                f"  {n_seen} works processed: strong={n_strong} medium={n_medium} new={n_new} "
                f"({n_seen/elapsed:.0f}/s)",
                flush=True,
            )

    print(
        f"  done: {n_seen} OpenAlex works processed, "
        f"strong={n_strong} medium={n_medium} new={n_new}"
    )

    # ---- Write canonical records ----
    print()
    print("Writing papers_canonical + paper_sources tables...")
    n_canon = 0
    n_sources = 0
    for cid, rec in canonical_records.items():
        cur.execute(
            """
            INSERT OR REPLACE INTO papers_canonical
                (canonical_id, canonical_doi, canonical_title, canonical_year,
                 canonical_type, canonical_first_author, confidence, last_updated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                rec["canonical_id"],
                rec["canonical_doi"],
                rec["canonical_title"],
                rec["canonical_year"],
                rec["canonical_type"],
                rec["canonical_first_author"],
                rec["confidence"],
                rec["last_updated"],
            ),
        )
        n_canon += 1

        # DSpace source
        dp = rec.get("_dspace")
        if dp:
            cur.execute(
                """
                INSERT OR REPLACE INTO paper_sources
                    (canonical_id, source, source_id, title, authors_json, year,
                     venue, doi, abstract, cited_by_count, raw_payload, fetched_at)
                VALUES (?, 'dspace', ?, ?, ?, ?, ?, NULL, ?, NULL, NULL, ?)
                """,
                (
                    cid,
                    dp["uuid"],
                    dp["title"],
                    json.dumps(dp["authors"], ensure_ascii=False),
                    dp["year"],
                    dp["collection"],
                    dp["abstract"][:2000],
                    rec["last_updated"],
                ),
            )
            n_sources += 1

        # OpenAlex source
        ow = rec.get("_openalex")
        if ow:
            authors = [a.get("name") for a in (ow.get("authors") or []) if a.get("name")]
            cur.execute(
                """
                INSERT OR REPLACE INTO paper_sources
                    (canonical_id, source, source_id, title, authors_json, year,
                     venue, doi, abstract, cited_by_count, raw_payload, fetched_at)
                VALUES (?, 'openalex', ?, ?, ?, ?, ?, ?, NULL, ?, NULL, ?)
                """,
                (
                    cid,
                    ow["id"],
                    ow.get("title"),
                    json.dumps(authors, ensure_ascii=False),
                    ow.get("publication_year"),
                    (ow.get("host_venue") or {}).get("display_name"),
                    normalize_doi(ow.get("doi")),
                    ow.get("cited_by_count"),
                    rec["last_updated"],
                ),
            )
            n_sources += 1

        if n_canon % 10000 == 0:
            out.commit()

    out.commit()
    cur.execute("ANALYZE")
    out.commit()
    if not args.dry_run:
        out.execute("VACUUM")
    out.close()

    # Swap temp file into place
    if not args.dry_run:
        import shutil
        tmp_db = PAPERS_DB.with_suffix(".db.tmp")
        try:
            if PAPERS_DB.exists():
                PAPERS_DB.unlink()
        except PermissionError:
            # Dropbox / antivirus lock — try overwrite via shutil
            pass
        shutil.move(str(tmp_db), str(PAPERS_DB))

    print(
        f"  wrote {n_canon} canonical papers, {n_sources} source rows"
    )
    if not args.dry_run:
        size_mb = PAPERS_DB.stat().st_size / 1024 / 1024
        print(f"  papers.db size: {size_mb:.1f} MB")
    print()
    print("=" * 60)
    print(
        f"DSpace input: {n_dspace_paper_total} papers\n"
        f"OpenAlex input: {n_seen} works\n"
        f"  strong DOI matches:    {n_strong}\n"
        f"  medium fuzzy matches:  {n_medium}\n"
        f"  new OpenAlex-only:     {n_new}\n"
        f"Total canonical papers: {n_canon}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
