"""
Build a SQLite index from the harvested DSpace JSONL files.

Inputs:  backend/data/dspace/dspace_items_*.jsonl
Output:  backend/data/dspace/dspace_index.db   (SQLite, FTS5-enabled)
         backend/data/dspace/dspace_index_stats.json  (summary stats)

The DB has:
  items(uuid, handle, collection, title, year, type, abstract, dspace_url,
        authors_json, departments_json, subject_json, has_bitstream)
  authors(item_uuid, author_name)
  authors_idx (B-tree on author_name)
  items_fts (FTS5 virtual table over title + abstract for fast text search)

After this builds, the backend can use it to:
  - Replace the live DSpace API call with a local lookup (much faster)
  - Pre-compute author -> papers and dept -> papers maps for the people sidebar
  - Drive a Stage B PDF download with the bitstream paths

Run:
  python backend/scripts/index_dspace_items.py
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from collections import Counter
from typing import Iterator, Dict, Any

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.dirname(HERE)
DSPACE_DIR = os.path.join(BACKEND, "data", "dspace")
DB_PATH = os.path.join(DSPACE_DIR, "dspace_index.db")
STATS_PATH = os.path.join(DSPACE_DIR, "dspace_index_stats.json")


def iter_jsonl(path: str) -> Iterator[Dict[str, Any]]:
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        DROP TABLE IF EXISTS items;
        DROP TABLE IF EXISTS authors;
        DROP TABLE IF EXISTS items_fts;

        CREATE TABLE items (
            uuid              TEXT PRIMARY KEY,
            handle            TEXT,
            collection_uuid   TEXT,
            collection_name   TEXT,
            title             TEXT,
            year              TEXT,
            issued            TEXT,
            type              TEXT,
            abstract          TEXT,
            dspace_url        TEXT,
            authors_json      TEXT,
            department        TEXT,
            subjects_json     TEXT,
            has_bitstream     INTEGER NOT NULL DEFAULT 0,
            bitstream_path    TEXT
        );

        CREATE TABLE authors (
            item_uuid   TEXT NOT NULL,
            author_name TEXT NOT NULL,
            FOREIGN KEY (item_uuid) REFERENCES items(uuid) ON DELETE CASCADE
        );

        CREATE INDEX idx_items_collection ON items(collection_uuid);
        CREATE INDEX idx_items_year ON items(year);
        CREATE INDEX idx_items_dept ON items(department);
        CREATE INDEX idx_authors_name ON authors(author_name);
        CREATE INDEX idx_authors_item ON authors(item_uuid);

        CREATE VIRTUAL TABLE items_fts USING fts5(
            uuid UNINDEXED,
            title,
            abstract,
            authors,
            tokenize = 'porter unicode61'
        );
        """
    )


def upsert_item(conn: sqlite3.Connection, item: Dict[str, Any]) -> bool:
    uuid = item.get("uuid")
    if not uuid:
        return False
    authors = item.get("authors") or []
    if isinstance(authors, str):
        authors = [a.strip() for a in authors.split(";") if a.strip()]
    subjects = item.get("subject") or []
    if isinstance(subjects, str):
        subjects = [s.strip() for s in subjects.split(";") if s.strip()]

    conn.execute(
        """
        INSERT OR REPLACE INTO items
            (uuid, handle, collection_uuid, collection_name, title, year, issued,
             type, abstract, dspace_url, authors_json, department, subjects_json,
             has_bitstream, bitstream_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            uuid,
            item.get("handle", ""),
            item.get("collection_uuid", ""),
            item.get("collection_name", ""),
            item.get("title", ""),
            item.get("year", ""),
            item.get("issued", ""),
            item.get("type", ""),
            item.get("abstract", ""),
            item.get("dspace_url", ""),
            json.dumps(authors, ensure_ascii=False),
            item.get("department", ""),
            json.dumps(subjects, ensure_ascii=False),
            1 if item.get("bitstream_present") else 0,
            item.get("bitstream_path", ""),
        ),
    )

    # Replace any prior author rows for this uuid
    conn.execute("DELETE FROM authors WHERE item_uuid = ?", (uuid,))
    for a in authors:
        if a:
            conn.execute(
                "INSERT INTO authors (item_uuid, author_name) VALUES (?, ?)",
                (uuid, a),
            )

    # FTS row
    conn.execute(
        "INSERT INTO items_fts (uuid, title, abstract, authors) VALUES (?, ?, ?, ?)",
        (
            uuid,
            item.get("title", ""),
            item.get("abstract", ""),
            "; ".join(authors),
        ),
    )
    return True


def main() -> int:
    if not os.path.isdir(DSPACE_DIR):
        print(f"ERROR: {DSPACE_DIR} not found", file=sys.stderr)
        return 2

    jsonl_files = sorted(
        os.path.join(DSPACE_DIR, f)
        for f in os.listdir(DSPACE_DIR)
        if f.startswith("dspace_items_") and f.endswith(".jsonl")
    )
    if not jsonl_files:
        print(f"ERROR: no dspace_items_*.jsonl files in {DSPACE_DIR}", file=sys.stderr)
        return 2

    print(f"Found {len(jsonl_files)} JSONL files. Building index at {DB_PATH}...")
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    init_db(conn)

    by_collection = Counter()
    by_dept = Counter()
    by_year = Counter()
    author_count = Counter()
    with_abstract = 0
    with_bitstream = 0
    total = 0

    for path in jsonl_files:
        cname = "?"
        for item in iter_jsonl(path):
            if upsert_item(conn, item):
                total += 1
                if item.get("abstract"):
                    with_abstract += 1
                if item.get("bitstream_present"):
                    with_bitstream += 1
                cn = item.get("collection_name") or "?"
                by_collection[cn] += 1
                cname = cn
                d = item.get("department") or ""
                if d:
                    by_dept[d] += 1
                y = item.get("year") or item.get("issued", "")[:4]
                if y:
                    by_year[y] += 1
                for a in item.get("authors") or []:
                    if isinstance(a, str) and a.strip():
                        author_count[a.strip()] += 1
                if total % 5000 == 0:
                    conn.commit()
                    print(f"  {total} items indexed ({cname})...")
        print(f"  done {os.path.basename(path)} ({by_collection.get(cname, 0)} from this file)")

    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()
    conn.close()

    print(f"\nIndexed {total} total items into {DB_PATH}")
    print()
    print("=== By collection ===")
    for k, v in by_collection.most_common():
        print(f"  {v:>6}  {k}")
    print()
    print(f"items with abstract:  {with_abstract:>6} ({100*with_abstract/total:.1f}%)")
    print(f"items with bitstream: {with_bitstream:>6} ({100*with_bitstream/total:.1f}%)")
    print()
    print("=== Top departments ===")
    for k, v in by_dept.most_common(15):
        print(f"  {v:>5}  {k}")
    print()
    print("=== Top 15 authors (by paper count) ===")
    for k, v in author_count.most_common(15):
        print(f"  {v:>5}  {k}")
    print()
    print("=== Year distribution (top 10) ===")
    for k, v in sorted(by_year.most_common(10), key=lambda x: -int(x[0]) if x[0].isdigit() else 0):
        print(f"  {v:>5}  {k}")

    stats = {
        "total_items": total,
        "with_abstract": with_abstract,
        "with_bitstream": with_bitstream,
        "by_collection": dict(by_collection),
        "by_year": dict(by_year),
        "top_authors": dict(author_count.most_common(50)),
        "top_departments": dict(by_dept.most_common(30)),
    }
    with open(STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2, ensure_ascii=False)
    print(f"\nStats: {STATS_PATH}")
    print(f"DB:    {DB_PATH}")

    db_size = os.path.getsize(DB_PATH)
    print(f"DB size: {db_size/1024/1024:.1f} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
