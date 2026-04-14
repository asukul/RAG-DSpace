"""
Local DSpace metadata service.

Reads from `backend/data/dspace/dspace_index.db` (built by
`backend/scripts/index_dspace_items.py`). Provides:
  - search(query, limit) - FTS5 over title + abstract + authors
  - papers_by_author(name, limit)
  - papers_by_uuid(uuid)
  - stats()

This is meant as a fast local supplement to the live `DSpaceService` that
hits dr.lib.iastate.edu directly. The local service has more items (~82k vs
the 50-item single-page live cap) and is much faster (no HTTP RTT).
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "DSPACE_INDEX_DB",
    os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "data",
        "dspace",
        "dspace_index.db",
    ),
)


def _row_to_item(row: sqlite3.Row) -> Dict[str, Any]:
    try:
        authors = json.loads(row["authors_json"]) if row["authors_json"] else []
    except Exception:
        authors = []
    try:
        subjects = json.loads(row["subjects_json"]) if row["subjects_json"] else []
    except Exception:
        subjects = []
    return {
        "uuid": row["uuid"],
        "title": row["title"],
        "authors": authors,
        "advisors": [],         # not captured by harvester (Stage B)
        "contributors": [],
        "abstract": (row["abstract"] or "")[:300] + ("..." if row["abstract"] and len(row["abstract"]) > 300 else ""),
        "date": row["issued"] or row["year"] or "",
        "year": row["year"] or "",
        "type": row["type"] or "",
        "department": row["department"] or "",
        "url": row["dspace_url"],
        "collection": row["collection_name"],
        "has_bitstream": bool(row["has_bitstream"]),
    }


class DSpaceLocalService:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self.ready = False
        self._open()

    def _open(self) -> None:
        if not os.path.exists(self.db_path):
            logger.warning(f"DSpaceLocalService: DB not found at {self.db_path}")
            self.ready = False
            return
        try:
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            # Quick sanity check
            n = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            logger.info(f"DSpaceLocalService: opened {self.db_path} ({n} items)")
            self.ready = True
        except Exception as e:
            logger.error(f"DSpaceLocalService: open failed: {e}")
            self.ready = False

    def stats(self) -> Dict[str, Any]:
        if not self.ready or self._conn is None:
            return {"ready": False, "items": 0}
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            with_abs = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE abstract IS NOT NULL AND abstract != ''"
            ).fetchone()[0]
            with_bs = self._conn.execute(
                "SELECT COUNT(*) FROM items WHERE has_bitstream = 1"
            ).fetchone()[0]
            collections = [
                {"name": r[0], "count": r[1]}
                for r in self._conn.execute(
                    "SELECT collection_name, COUNT(*) FROM items GROUP BY collection_name ORDER BY 2 DESC"
                )
            ]
        return {
            "ready": True,
            "items": n,
            "with_abstract": with_abs,
            "with_bitstream": with_bs,
            "collections": collections,
        }

    def _fts_query(self, query: str) -> str:
        """
        Sanitize query for FTS5: strip special syntax characters and join
        meaningful words with implicit AND. Wrap in quotes only when needed.
        """
        cleaned = []
        for tok in query.replace('"', "").split():
            t = tok.strip()
            if not t or t.lower() in ("and", "or", "not"):
                continue
            # Drop short stop tokens
            if len(t) < 2:
                continue
            cleaned.append(t)
        if not cleaned:
            return ""
        return " ".join(cleaned)

    def search(self, query: str, limit: int = 30) -> List[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return []
        q = self._fts_query(query)
        if not q:
            return []
        with self._lock:
            try:
                rows = self._conn.execute(
                    """
                    SELECT i.* FROM items_fts f
                    JOIN items i ON i.uuid = f.uuid
                    WHERE items_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (q, limit),
                ).fetchall()
            except sqlite3.OperationalError as e:
                logger.debug(f"DSpaceLocalService search err for {q!r}: {e}")
                return []
        return [_row_to_item(r) for r in rows]

    def papers_by_author(self, author_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return []
        # Normalize "First Last" and "Last, First"
        parts = [p.strip() for p in author_name.replace(",", " ").split() if p.strip()]
        if not parts:
            return []
        last = parts[-1]
        first = parts[0]
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT DISTINCT i.* FROM items i
                JOIN authors a ON a.item_uuid = i.uuid
                WHERE a.author_name LIKE ? AND a.author_name LIKE ?
                ORDER BY i.year DESC
                LIMIT ?
                """,
                (f"%{last}%", f"%{first}%", limit),
            ).fetchall()
        return [_row_to_item(r) for r in rows]

    def papers_by_uuid(self, uuid: str) -> Optional[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM items WHERE uuid = ?", (uuid,)
            ).fetchone()
        return _row_to_item(row) if row else None

    def suggest_titles(self, prefix: str, limit: int = 8) -> List[Dict[str, Any]]:
        """
        Cheap title suggestions for an autocomplete dropdown.

        Strategy: take the last token of the prefix, append `*`, and run an
        FTS5 prefix-MATCH against the title column only. Returns shape:
        [{ "uuid", "title", "year" }, ...]
        """
        if not self.ready or self._conn is None:
            return []
        prefix = (prefix or "").strip()
        if len(prefix) < 2:
            return []
        # Split on whitespace and append * to the last token; quote the
        # earlier ones so multi-word prefixes still work.
        tokens = [t for t in prefix.split() if t]
        if not tokens:
            return []
        # Drop FTS5 special characters from each token
        safe = []
        for t in tokens:
            tt = "".join(c for c in t if c.isalnum() or c in "-")
            if len(tt) >= 2:
                safe.append(tt)
        if not safe:
            return []
        last = safe[-1] + "*"
        rest = " ".join(safe[:-1])
        match_q = f"{rest} {last}".strip()
        try:
            with self._lock:
                rows = self._conn.execute(
                    """
                    SELECT i.uuid, i.title, i.year
                    FROM items_fts f
                    JOIN items i ON i.uuid = f.uuid
                    WHERE items_fts MATCH ?
                      AND i.title IS NOT NULL AND i.title != ''
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (f"title:({match_q})", limit),
                ).fetchall()
        except sqlite3.OperationalError as e:
            logger.debug(f"suggest_titles err for {match_q!r}: {e}")
            return []
        return [
            {"uuid": r["uuid"], "title": r["title"], "year": r["year"] or ""}
            for r in rows
        ]

    def suggest_authors(self, prefix: str, limit: int = 8) -> List[Dict[str, Any]]:
        """Authors whose name contains the prefix (case-insensitive)."""
        if not self.ready or self._conn is None:
            return []
        prefix = (prefix or "").strip()
        if len(prefix) < 2:
            return []
        like = f"%{prefix.lower()}%"
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT author_name, COUNT(*) AS papers
                FROM authors
                WHERE LOWER(author_name) LIKE ?
                GROUP BY author_name
                ORDER BY papers DESC
                LIMIT ?
                """,
                (like, limit),
            ).fetchall()
        return [{"name": r["author_name"], "papers": r["papers"]} for r in rows]


# Lazy singleton
_dspace_local_service: Optional[DSpaceLocalService] = None


def get_dspace_local_service() -> DSpaceLocalService:
    global _dspace_local_service
    if _dspace_local_service is None:
        _dspace_local_service = DSpaceLocalService()
    return _dspace_local_service
