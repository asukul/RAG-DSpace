"""
On-demand OpenAlex cache service.

The local KG only has the structural data we pre-staged. For things we DON'T
pre-stage (the world's citation graph beyond Iowa State), we lazy-fetch from
OpenAlex on demand and cache the result for 7 days in a small SQLite table.

Cached endpoints:
  - get_work(work_id)        → full Work record
  - get_author(author_id)    → full Author record (works, h-index, etc.)
  - cites_of(work_id)        → list of works that this work CITES
  - cited_by_of(work_id)     → list of works that CITE this work

Storage:
  backend/data/openalex_cache.db
    cache(key TEXT PRIMARY KEY, fetched_at TEXT, ttl_seconds INT, payload TEXT)
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

CACHE_DB_PATH = os.environ.get(
    "OPENALEX_CACHE_DB",
    str(
        Path(__file__).resolve().parent.parent
        / "data"
        / "openalex_cache.db"
    ),
)

DEFAULT_TTL_SECONDS = 7 * 24 * 3600  # 7 days
OPENALEX_BASE = "https://api.openalex.org"


def _short(s: str) -> str:
    return s.split("/")[-1] if s else ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_ts() -> int:
    return int(time.time())


class OpenAlexCacheService:
    def __init__(self, db_path: str = CACHE_DB_PATH) -> None:
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
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    key          TEXT PRIMARY KEY,
                    fetched_at   INTEGER NOT NULL,
                    ttl_seconds  INTEGER NOT NULL,
                    payload      TEXT NOT NULL,
                    error        TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_cache_fetched_at ON cache(fetched_at);
                """
            )
            self.ready = True
            logger.info(f"OpenAlexCacheService: opened {self.db_path}")
        except Exception as e:
            logger.error(f"OpenAlexCacheService open failed: {e}")
            self.ready = False

    # ------------------------------------------------------------------
    # Cache primitives
    # ------------------------------------------------------------------

    def _get_cached(self, key: str) -> Optional[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None:
            return None
        age = _now_ts() - row["fetched_at"]
        if age > row["ttl_seconds"]:
            return None  # expired
        try:
            return json.loads(row["payload"])
        except Exception:
            return None

    def _put_cached(self, key: str, payload: Dict[str, Any], ttl: int = DEFAULT_TTL_SECONDS) -> None:
        if not self.ready or self._conn is None:
            return
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO cache (key, fetched_at, ttl_seconds, payload, error)
                VALUES (?, ?, ?, ?, NULL)
                """,
                (key, _now_ts(), ttl, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()

    def stats(self) -> Dict[str, Any]:
        if not self.ready or self._conn is None:
            return {"ready": False, "rows": 0}
        with self._lock:
            n = self._conn.execute("SELECT COUNT(*) FROM cache").fetchone()[0]
            by_prefix = {
                r[0]: r[1]
                for r in self._conn.execute(
                    "SELECT substr(key, 1, instr(key, ':') - 1) AS prefix, COUNT(*) FROM cache GROUP BY prefix"
                )
            }
            db_size = os.path.getsize(self.db_path) if os.path.exists(self.db_path) else 0
        return {
            "ready": True,
            "rows": n,
            "by_prefix": by_prefix,
            "db_size_bytes": db_size,
        }

    # ------------------------------------------------------------------
    # OpenAlex fetchers (lazy import of pyalex so it's optional)
    # ------------------------------------------------------------------

    def _pyalex(self):
        import pyalex
        if not pyalex.config.email:
            pyalex.config.email = os.environ.get(
                "OPENALEX_EMAIL", "adisak.sukul@gmail.com"
            )
        return pyalex

    def get_work(self, work_id: str) -> Optional[Dict[str, Any]]:
        wid = _short(work_id)
        if not wid.startswith("W"):
            return None
        key = f"work:{wid}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        try:
            pyalex = self._pyalex()
            from pyalex import Works
            work = Works()[wid]
        except Exception as e:
            logger.warning(f"OpenAlex get_work({wid}) failed: {e}")
            return None
        if not work:
            return None
        slim = self._slim_work(work)
        self._put_cached(key, slim)
        return slim

    def get_author(self, author_id: str) -> Optional[Dict[str, Any]]:
        aid = _short(author_id)
        if not aid.startswith("A"):
            return None
        key = f"author:{aid}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached
        try:
            pyalex = self._pyalex()
            from pyalex import Authors
            author = Authors()[aid]
        except Exception as e:
            logger.warning(f"OpenAlex get_author({aid}) failed: {e}")
            return None
        if not author:
            return None
        slim = {
            "id": _short(author.get("id", "")),
            "display_name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "works_count": author.get("works_count"),
            "cited_by_count": author.get("cited_by_count"),
            "h_index": (author.get("summary_stats") or {}).get("h_index"),
            "i10_index": (author.get("summary_stats") or {}).get("i10_index"),
            "last_known_institutions": [
                {"id": _short(i.get("id", "")), "name": i.get("display_name")}
                for i in (author.get("last_known_institutions") or [])
            ],
        }
        self._put_cached(key, slim)
        return slim

    def works_by_author(self, author_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        aid = _short(author_id)
        if not aid.startswith("A"):
            return []
        key = f"works_by_author:{aid}:{limit}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached.get("works", [])
        try:
            pyalex = self._pyalex()
            from pyalex import Works
            works = Works().filter(author={"id": aid}).get(per_page=limit)
        except Exception as e:
            logger.warning(f"OpenAlex works_by_author({aid}) failed: {e}")
            return []
        slim = [self._slim_work(w) for w in works]
        self._put_cached(key, {"works": slim})
        return slim

    def cited_by_of(self, work_id: str, limit: int = 25) -> List[Dict[str, Any]]:
        """Returns the works that CITE this work."""
        wid = _short(work_id)
        if not wid.startswith("W"):
            return []
        key = f"cited_by:{wid}:{limit}"
        cached = self._get_cached(key)
        if cached is not None:
            return cached.get("works", [])
        try:
            pyalex = self._pyalex()
            from pyalex import Works
            works = Works().filter(cites=wid).get(per_page=limit)
        except Exception as e:
            logger.warning(f"OpenAlex cited_by_of({wid}) failed: {e}")
            return []
        slim = [self._slim_work(w) for w in works]
        self._put_cached(key, {"works": slim})
        return slim

    def cites_of(self, work_id: str) -> List[str]:
        """Returns the IDs of works that this work CITES (referenced_works)."""
        wid = _short(work_id)
        if not wid.startswith("W"):
            return []
        full = self.get_work(wid)
        if not full:
            return []
        return full.get("referenced_works", [])

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _slim_work(self, w: Dict[str, Any]) -> Dict[str, Any]:
        primary = w.get("primary_location") or {}
        source = primary.get("source") or {}
        return {
            "id": _short(w.get("id", "")),
            "doi": w.get("doi"),
            "title": w.get("title"),
            "publication_year": w.get("publication_year"),
            "type": w.get("type"),
            "cited_by_count": w.get("cited_by_count"),
            "host_venue": source.get("display_name"),
            "authors": [
                {
                    "id": _short((a.get("author") or {}).get("id", "")),
                    "name": (a.get("author") or {}).get("display_name"),
                    "position": a.get("author_position"),
                }
                for a in (w.get("authorships") or [])[:10]
            ],
            "referenced_works": [
                _short(r) for r in (w.get("referenced_works") or [])
            ],
        }


# Lazy singleton
_cache: Optional[OpenAlexCacheService] = None


def get_openalex_cache_service() -> OpenAlexCacheService:
    global _cache
    if _cache is None:
        _cache = OpenAlexCacheService()
    return _cache
