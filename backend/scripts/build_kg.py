"""
Phase 1 KG seeder.

Builds a SQLite knowledge graph from existing local data:
  - backend/data/dspace/dspace_index.db  (82,656 papers harvested from DSpace)
  - backend/data/faculty.json            (3,451 ISU faculty)

No LLM calls. Pure structural extraction.

Output:
  backend/data/dspace/kg.db
    - kg_entities(id, type, name, canonical_id, payload_json)
    - kg_edges(subject_id, predicate, object_id, confidence, source, source_paper_id, created_at)

Entity types created:
  paper:dspace:<uuid>
  author:dspace:<slug>            (from author strings on DSpace items)
  faculty:isu:<faculty_id>        (from faculty.json — these are the curated ISU profiles)
  department:isu:<dept_slug>
  college:isu:<college_slug>
  topic:isu:<topic_slug>          (from faculty research_interests + research_areas)

Predicates created:
  authored          (author -> paper)
  advised           (faculty/author -> paper)         # for major-professor / advisor
  affiliated_with   (faculty -> department)
  belongs_to        (department -> college)
  interested_in     (faculty -> topic)
  same_as           (author -> faculty)               # link DSpace author strings to ISU faculty rows by name match

Run:
    python backend/scripts/build_kg.py
    python backend/scripts/build_kg.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DSPACE_INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
KG_DB = BACKEND / "data" / "dspace" / "kg.db"
FACULTY_JSON = BACKEND / "data" / "faculty.json"


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

SCHEMA_SQL = """
DROP TABLE IF EXISTS kg_entities;
DROP TABLE IF EXISTS kg_edges;
DROP TABLE IF EXISTS kg_meta;

CREATE TABLE kg_entities (
    id            TEXT PRIMARY KEY,
    type          TEXT NOT NULL,
    name          TEXT NOT NULL,
    canonical_id  TEXT,
    payload_json  TEXT
);

CREATE INDEX idx_kg_entities_type ON kg_entities(type);
CREATE INDEX idx_kg_entities_name ON kg_entities(name);

CREATE TABLE kg_edges (
    subject_id      TEXT NOT NULL,
    predicate       TEXT NOT NULL,
    object_id       TEXT NOT NULL,
    confidence      REAL NOT NULL DEFAULT 1.0,
    source          TEXT NOT NULL,
    source_paper_id TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (subject_id, predicate, object_id, source)
);

CREATE INDEX idx_kg_edges_subject_pred ON kg_edges(subject_id, predicate);
CREATE INDEX idx_kg_edges_object_pred  ON kg_edges(object_id, predicate);
CREATE INDEX idx_kg_edges_predicate    ON kg_edges(predicate);

CREATE TABLE kg_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9\s-]", "", (s or "").lower())
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalize_name(name: str) -> str:
    """
    Normalize an author or faculty name into a comparable token.
    'Sukul, Adisak' -> 'adisak sukul'
    'Adisak Sukul'  -> 'adisak sukul'
    'Sukul, A.'     -> 'a sukul'
    """
    if not name:
        return ""
    n = name.strip()
    # Split on comma "Last, First Middle" -> "First Middle Last"
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2:
            n = f"{parts[1]} {parts[0]}"
    n = re.sub(r"[^A-Za-z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n.lower()


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def iter_dspace_items(db: sqlite3.Connection) -> Iterable[Dict[str, Any]]:
    cur = db.execute(
        """
        SELECT uuid, title, year, type, abstract, dspace_url,
               authors_json, department, collection_name
        FROM items
        """
    )
    for row in cur:
        try:
            authors = json.loads(row["authors_json"]) if row["authors_json"] else []
        except Exception:
            authors = []
        yield {
            "uuid": row["uuid"],
            "title": row["title"] or "",
            "year": row["year"] or "",
            "type": row["type"] or "",
            "abstract": (row["abstract"] or "")[:600],
            "dspace_url": row["dspace_url"] or "",
            "authors": authors,
            "department": row["department"] or "",
            "collection": row["collection_name"] or "",
        }


def load_faculty() -> List[Dict[str, Any]]:
    with FACULTY_JSON.open(encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def upsert_entity(
    cur: sqlite3.Cursor, eid: str, etype: str, name: str, payload: Optional[Dict] = None
) -> None:
    cur.execute(
        """
        INSERT OR REPLACE INTO kg_entities (id, type, name, canonical_id, payload_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            eid,
            etype,
            name,
            None,
            json.dumps(payload, ensure_ascii=False) if payload else None,
        ),
    )


def upsert_edge(
    cur: sqlite3.Cursor,
    subject_id: str,
    predicate: str,
    object_id: str,
    *,
    confidence: float = 1.0,
    source: str = "dspace",
    source_paper_id: Optional[str] = None,
    created_at: Optional[str] = None,
) -> None:
    cur.execute(
        """
        INSERT OR REPLACE INTO kg_edges
            (subject_id, predicate, object_id, confidence, source, source_paper_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            subject_id,
            predicate,
            object_id,
            confidence,
            source,
            source_paper_id,
            created_at or now_iso(),
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true",
                        help="Build the in-memory graph but do not write kg.db")
    parser.add_argument("--limit", type=int, default=0,
                        help="Limit DSpace items processed (smoke test)")
    args = parser.parse_args()

    if not DSPACE_INDEX_DB.exists():
        print(f"ERROR: dspace_index.db not found at {DSPACE_INDEX_DB}", file=sys.stderr)
        return 2
    if not FACULTY_JSON.exists():
        print(f"ERROR: faculty.json not found at {FACULTY_JSON}", file=sys.stderr)
        return 2

    print(f"Loading from:")
    print(f"  {DSPACE_INDEX_DB}")
    print(f"  {FACULTY_JSON}")
    print(f"Writing to:    {KG_DB}{' (DRY RUN)' if args.dry_run else ''}")
    print()

    # ---------- destination DB ----------
    if args.dry_run:
        out = sqlite3.connect(":memory:")
    else:
        if KG_DB.exists():
            KG_DB.unlink()
        KG_DB.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(KG_DB)
    out.row_factory = sqlite3.Row
    out.executescript(SCHEMA_SQL)
    cur = out.cursor()

    # ---------- source DB ----------
    src = sqlite3.connect(f"file:{DSPACE_INDEX_DB}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row

    # ---------- 1. Faculty + Departments + Colleges + Topics ----------
    print("Pass 1: faculty, departments, colleges, topics...")
    faculty_rows = load_faculty()
    print(f"  loaded {len(faculty_rows)} faculty rows")

    dept_to_id: Dict[str, str] = {}
    college_to_id: Dict[str, str] = {}
    topic_to_id: Dict[str, str] = {}
    faculty_by_norm_name: Dict[str, str] = {}  # normalized name -> faculty entity id

    n_fac = n_dept = n_col = n_topic = 0

    for f in faculty_rows:
        fid = f.get("id")
        fname = f.get("name")
        if not fid or not fname:
            continue
        fac_eid = f"faculty:isu:{fid}"
        upsert_entity(cur, fac_eid, "faculty", fname, payload={
            "rank": f.get("rank"),
            "title": f.get("title"),
            "email": f.get("email"),
            "department": f.get("department"),
            "college": f.get("college"),
            "profile_url": f.get("profile_url"),
            "photo_url": f.get("photo_url"),
            "research_interests": f.get("research_interests", []),
            "research_areas": f.get("research_areas", []),
        })
        n_fac += 1
        faculty_by_norm_name[normalize_name(fname)] = fac_eid

        # Department
        dept = (f.get("department") or "").strip()
        if dept and dept != "Unknown Department":
            if dept not in dept_to_id:
                dept_eid = f"department:isu:{slugify(dept)}"
                dept_to_id[dept] = dept_eid
                upsert_entity(cur, dept_eid, "department", dept)
                n_dept += 1
            upsert_edge(cur, fac_eid, "affiliated_with", dept_to_id[dept], source="faculty_json")

        # College
        college = (f.get("college") or "").strip()
        if college:
            if college not in college_to_id:
                col_eid = f"college:isu:{slugify(college)}"
                college_to_id[college] = col_eid
                upsert_entity(cur, col_eid, "college", college)
                n_col += 1
            if dept and dept in dept_to_id:
                upsert_edge(
                    cur,
                    dept_to_id[dept],
                    "belongs_to",
                    college_to_id[college],
                    source="faculty_json",
                )

        # Topics from research_interests + research_areas
        topics = list(f.get("research_interests") or []) + list(f.get("research_areas") or [])
        for t in topics:
            t = (t or "").strip()
            if not t:
                continue
            if t not in topic_to_id:
                t_eid = f"topic:isu:{slugify(t)}"
                topic_to_id[t] = t_eid
                upsert_entity(cur, t_eid, "topic", t)
                n_topic += 1
            upsert_edge(cur, fac_eid, "interested_in", topic_to_id[t], source="faculty_json")

    out.commit()
    print(
        f"  inserted: {n_fac} faculty, {n_dept} departments, "
        f"{n_col} colleges, {n_topic} topics"
    )

    # ---------- 2. Papers + Authors + DSpace department/collection links ----------
    print()
    print("Pass 2: papers, authors, edges...")
    n_papers = 0
    n_auth_entities = 0
    n_authored_edges = 0
    n_paper_dept_edges = 0
    n_author_to_faculty_edges = 0

    # cache author entity ids by normalized name
    author_norm_to_id: Dict[str, str] = {}
    # cache author display names (one per slug)
    author_id_to_display: Dict[str, str] = {}

    t0 = time.time()
    seen_papers = 0

    for item in iter_dspace_items(src):
        seen_papers += 1
        if args.limit and seen_papers > args.limit:
            break

        paper_eid = f"paper:dspace:{item['uuid']}"
        # Note: abstracts intentionally NOT in payload — they live in dspace_index.db.
        # Backend joins both DBs at query time when a user opens an entity.
        upsert_entity(cur, paper_eid, "paper", item["title"], payload={
            "year": item["year"],
            "type": item["type"],
            "dspace_url": item["dspace_url"],
            "department": item["department"],
            "collection": item["collection"],
        })
        n_papers += 1

        # Department edge (paper -> department) using faculty.json's normalized
        # department name when we recognize it
        item_dept = item.get("department", "")
        if item_dept:
            # Try exact match first
            if item_dept in dept_to_id:
                upsert_edge(
                    cur, paper_eid, "from_department", dept_to_id[item_dept],
                    source="dspace", source_paper_id=item["uuid"],
                )
                n_paper_dept_edges += 1

        # Authors
        for author_str in item.get("authors", []):
            if not isinstance(author_str, str) or not author_str.strip():
                continue
            norm = normalize_name(author_str)
            if not norm:
                continue
            display = author_str.strip()

            # Make a stable author entity id by normalized name
            slug = slugify(norm)
            if not slug:
                continue
            author_eid = author_norm_to_id.get(norm)
            if author_eid is None:
                author_eid = f"author:dspace:{slug}"
                author_norm_to_id[norm] = author_eid
                author_id_to_display[author_eid] = display
                upsert_entity(cur, author_eid, "author", display, payload={
                    "normalized_name": norm,
                })
                n_auth_entities += 1

            # AUTHORED edge
            upsert_edge(
                cur, author_eid, "authored", paper_eid,
                source="dspace", source_paper_id=item["uuid"],
            )
            n_authored_edges += 1

            # SAME_AS link to ISU faculty if normalized name matches
            fac_eid = faculty_by_norm_name.get(norm)
            if fac_eid:
                upsert_edge(
                    cur, author_eid, "same_as", fac_eid,
                    confidence=0.9,
                    source="name_match",
                    source_paper_id=item["uuid"],
                )
                n_author_to_faculty_edges += 1

        if seen_papers % 5000 == 0:
            out.commit()
            elapsed = time.time() - t0
            print(
                f"  processed {seen_papers} papers, {n_auth_entities} unique authors "
                f"({seen_papers/elapsed:.0f} papers/s)"
            )

    out.commit()
    print(
        f"  inserted: {n_papers} papers, {n_auth_entities} unique authors, "
        f"{n_authored_edges} authored edges, {n_paper_dept_edges} paper-department edges, "
        f"{n_author_to_faculty_edges} author-faculty SAME_AS edges"
    )

    # ---------- 3. Coauthored edges (derived from shared papers) ----------
    print()
    print("Pass 3: coauthored edges...")
    cur.execute(
        """
        INSERT OR REPLACE INTO kg_edges (subject_id, predicate, object_id, confidence, source, source_paper_id, created_at)
        SELECT DISTINCT
            a1.subject_id AS subj,
            'coauthored' AS predicate,
            a2.subject_id AS obj,
            1.0,
            'derived',
            a1.object_id,
            ?
        FROM kg_edges a1
        JOIN kg_edges a2
          ON a1.object_id = a2.object_id
         AND a1.predicate = 'authored'
         AND a2.predicate = 'authored'
         AND a1.subject_id < a2.subject_id
        """,
        (now_iso(),),
    )
    out.commit()
    n_coauth = cur.execute(
        "SELECT COUNT(*) FROM kg_edges WHERE predicate = 'coauthored'"
    ).fetchone()[0]
    print(f"  inserted: {n_coauth} coauthored edges")

    # ---------- 4. Stats + meta ----------
    print()
    print("Pass 4: stats + meta...")
    counts = {}
    for row in cur.execute("SELECT type, COUNT(*) FROM kg_entities GROUP BY type"):
        counts[row[0]] = row[1]
    print(f"  Entity counts:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"    {v:>7}  {k}")

    edge_counts: Dict[str, int] = {}
    for row in cur.execute("SELECT predicate, COUNT(*) FROM kg_edges GROUP BY predicate"):
        edge_counts[row[0]] = row[1]
    print(f"  Edge counts:")
    for k, v in sorted(edge_counts.items(), key=lambda x: -x[1]):
        print(f"    {v:>7}  {k}")

    cur.execute(
        "INSERT INTO kg_meta(key, value) VALUES (?, ?)",
        ("built_at", now_iso()),
    )
    cur.execute(
        "INSERT INTO kg_meta(key, value) VALUES (?, ?)",
        ("entities", json.dumps(counts)),
    )
    cur.execute(
        "INSERT INTO kg_meta(key, value) VALUES (?, ?)",
        ("edges", json.dumps(edge_counts)),
    )
    out.commit()

    cur.execute("ANALYZE")
    out.commit()
    if not args.dry_run:
        out.execute("VACUUM")
    out.close()
    src.close()

    if not args.dry_run:
        size_mb = KG_DB.stat().st_size / 1024 / 1024
        print(f"\nDB size: {size_mb:.1f} MB")
        print(f"Path:    {KG_DB}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
