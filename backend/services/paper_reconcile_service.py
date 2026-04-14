"""
Paper reconciliation service.

Provides the merged-view API for a single paper that may exist in multiple
sources (DSpace, OpenAlex, Crossref, scholarly, user_edit). Handles user
overrides on top of the canonical record.

Storage:
  backend/data/dspace/papers.db
    papers_canonical(canonical_id, canonical_doi, canonical_title,
                     canonical_year, canonical_type, canonical_first_author,
                     confidence, last_updated)
    paper_sources(canonical_id, source, source_id, title, authors_json,
                  year, venue, doi, abstract, cited_by_count, raw_payload,
                  fetched_at)
    paper_overrides(id, canonical_id, user_id, action, field, payload_json,
                    rationale, created_at)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "PAPERS_DB_PATH",
    str(
        Path(__file__).resolve().parent.parent
        / "data"
        / "dspace"
        / "papers.db"
    ),
)

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS papers_canonical (
    canonical_id          TEXT PRIMARY KEY,
    canonical_doi         TEXT,
    canonical_title       TEXT NOT NULL,
    canonical_year        INTEGER,
    canonical_type        TEXT,
    canonical_first_author TEXT,
    confidence            REAL NOT NULL DEFAULT 1.0,
    last_updated          TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_canon_doi   ON papers_canonical(canonical_doi);
CREATE INDEX IF NOT EXISTS idx_canon_title ON papers_canonical(canonical_title);

CREATE TABLE IF NOT EXISTS paper_sources (
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

CREATE INDEX IF NOT EXISTS idx_psources_doi    ON paper_sources(doi);
CREATE INDEX IF NOT EXISTS idx_psources_canon  ON paper_sources(canonical_id);

CREATE TABLE IF NOT EXISTS paper_overrides (
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

CREATE INDEX IF NOT EXISTS idx_overrides_canon ON paper_overrides(canonical_id);
CREATE INDEX IF NOT EXISTS idx_overrides_user  ON paper_overrides(user_id);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PaperReconcileService:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self.ready = False
        self._open()

    def _open(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()
            self.ready = True
            logger.info(f"PaperReconcileService: opened {self.db_path}")
        except Exception as e:
            logger.error(f"PaperReconcileService open failed: {e}")
            self.ready = False

    def stats(self) -> Dict[str, Any]:
        if not self.ready or self._conn is None:
            return {"ready": False, "papers": 0, "sources": 0, "overrides": 0}
        with self._lock:
            n_p = self._conn.execute("SELECT COUNT(*) FROM papers_canonical").fetchone()[0]
            n_s = self._conn.execute("SELECT COUNT(*) FROM paper_sources").fetchone()[0]
            n_o = self._conn.execute(
                "SELECT COUNT(*) FROM paper_overrides WHERE deleted_at IS NULL"
            ).fetchone()[0]
            by_source = {
                r[0]: r[1] for r in self._conn.execute(
                    "SELECT source, COUNT(*) FROM paper_sources GROUP BY source"
                )
            }
        return {
            "ready": True,
            "papers": n_p,
            "sources": n_s,
            "overrides": n_o,
            "by_source": by_source,
        }

    def get_paper(self, canonical_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the merged paper view: canonical fields + a list of sources
        + the most recent override per field.
        """
        if not self.ready or self._conn is None:
            return None
        with self._lock:
            canon = self._conn.execute(
                "SELECT * FROM papers_canonical WHERE canonical_id = ?",
                (canonical_id,),
            ).fetchone()
            if canon is None:
                return None
            sources = self._conn.execute(
                "SELECT * FROM paper_sources WHERE canonical_id = ? ORDER BY source",
                (canonical_id,),
            ).fetchall()
            overrides = self._conn.execute(
                """
                SELECT * FROM paper_overrides
                WHERE canonical_id = ? AND deleted_at IS NULL
                ORDER BY created_at ASC
                """,
                (canonical_id,),
            ).fetchall()

        merged = {
            "canonical_id": canon["canonical_id"],
            "doi":   canon["canonical_doi"],
            "title": canon["canonical_title"],
            "year":  canon["canonical_year"],
            "type":  canon["canonical_type"],
            "first_author": canon["canonical_first_author"],
            "confidence":   canon["confidence"],
            "last_updated": canon["last_updated"],
            "sources": [
                {
                    "source":         s["source"],
                    "source_id":      s["source_id"],
                    "title":          s["title"],
                    "authors":        json.loads(s["authors_json"]) if s["authors_json"] else [],
                    "year":           s["year"],
                    "venue":          s["venue"],
                    "doi":            s["doi"],
                    "abstract":       s["abstract"],
                    "cited_by_count": s["cited_by_count"],
                    "fetched_at":     s["fetched_at"],
                }
                for s in sources
            ],
            "overrides": [],
        }

        # Apply overrides in order
        for o in overrides:
            override_record = {
                "id":          o["id"],
                "user_id":     o["user_id"],
                "action":      o["action"],
                "field":       o["field"],
                "payload":     json.loads(o["payload_json"]) if o["payload_json"] else None,
                "rationale":   o["rationale"],
                "created_at":  o["created_at"],
            }
            merged["overrides"].append(override_record)
            if o["action"] == "edit_field" and o["field"]:
                payload = override_record["payload"] or {}
                if "new" in payload:
                    merged[o["field"]] = payload["new"]
        return merged

    def add_override(
        self,
        canonical_id: str,
        user_id: int,
        action: str,
        field: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        rationale: Optional[str] = None,
    ) -> int:
        if not self.ready or self._conn is None:
            raise RuntimeError("PaperReconcileService not ready")
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO paper_overrides
                    (canonical_id, user_id, action, field, payload_json, rationale, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    user_id,
                    action,
                    field,
                    json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                    rationale,
                    _now_iso(),
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def soft_delete_override(self, override_id: int) -> bool:
        if not self.ready or self._conn is None:
            return False
        with self._lock:
            cur = self._conn.execute(
                "UPDATE paper_overrides SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL",
                (_now_iso(), override_id),
            )
            self._conn.commit()
            return cur.rowcount > 0

    def add_source(
        self,
        canonical_id: str,
        source: str,
        source_id: str,
        *,
        title: Optional[str] = None,
        authors: Optional[List[str]] = None,
        year: Optional[int] = None,
        venue: Optional[str] = None,
        doi: Optional[str] = None,
        abstract: Optional[str] = None,
        cited_by_count: Optional[int] = None,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not self.ready or self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO paper_sources
                    (canonical_id, source, source_id, title, authors_json, year, venue,
                     doi, abstract, cited_by_count, raw_payload, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    source,
                    source_id,
                    title,
                    json.dumps(authors or [], ensure_ascii=False),
                    year,
                    venue,
                    doi,
                    abstract,
                    cited_by_count,
                    json.dumps(raw_payload, ensure_ascii=False) if raw_payload else None,
                    _now_iso(),
                ),
            )
            self._conn.commit()

    def upsert_canonical(
        self,
        canonical_id: str,
        title: str,
        *,
        doi: Optional[str] = None,
        year: Optional[int] = None,
        type_: Optional[str] = None,
        first_author: Optional[str] = None,
        confidence: float = 1.0,
    ) -> None:
        if not self.ready or self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO papers_canonical
                    (canonical_id, canonical_doi, canonical_title, canonical_year,
                     canonical_type, canonical_first_author, confidence, last_updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (canonical_id, doi, title, year, type_, first_author, confidence, _now_iso()),
            )
            self._conn.commit()


# Lazy singleton
_pr_service: Optional[PaperReconcileService] = None


def get_paper_reconcile_service() -> PaperReconcileService:
    global _pr_service
    if _pr_service is None:
        _pr_service = PaperReconcileService()
    return _pr_service
