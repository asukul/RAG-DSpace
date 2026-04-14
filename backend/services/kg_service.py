"""
Knowledge Graph runtime service.

Reads from `backend/data/dspace/kg.db` (built by `backend/scripts/build_kg.py`).
Provides:
  - get_entity(entity_id)
  - search(query, types, limit)
  - graph_around(root_id, depth)            -> {nodes, edges}
  - papers_by_author(author_id, limit)
  - related_to_paper(paper_uuid, limit)
  - stats()

Designed to read-only — the seeder writes the file once on the workstation
and the backend just queries it. SQLite handles concurrent reads on its own.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get(
    "KG_DB_PATH",
    str(
        Path(__file__).resolve().parent.parent
        / "data"
        / "dspace"
        / "kg.db"
    ),
)

# Faculty -> OpenAlex match table built by `match_faculty_openalex.py`.
# Loaded once on startup, indexed by faculty_id.
FACULTY_OPENALEX_MATCH = (
    Path(__file__).resolve().parent.parent / "data" / "faculty_openalex_match.json"
)


def _load_openalex_matches() -> Dict[str, Dict[str, Any]]:
    """Returns { faculty_id: {openalex_id, h_index, works_count, ...} }."""
    if not FACULTY_OPENALEX_MATCH.exists():
        return {}
    try:
        with FACULTY_OPENALEX_MATCH.open(encoding="utf-8") as f:
            rows = json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {FACULTY_OPENALEX_MATCH}: {e}")
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        fid = r.get("faculty_id")
        if fid and r.get("openalex_id"):
            out[fid] = r
    return out


def _row_to_entity(row: sqlite3.Row) -> Dict[str, Any]:
    payload: Optional[Dict[str, Any]] = None
    if row["payload_json"]:
        try:
            payload = json.loads(row["payload_json"])
        except Exception:
            payload = None
    return {
        "id": row["id"],
        "type": row["type"],
        "name": row["name"],
        "canonical_id": row["canonical_id"],
        "payload": payload or {},
    }


def _row_to_edge(row: sqlite3.Row) -> Dict[str, Any]:
    return {
        "subject": row["subject_id"],
        "predicate": row["predicate"],
        "object": row["object_id"],
        "confidence": row["confidence"],
        "source": row["source"],
    }


class KGService:
    def __init__(self, db_path: str = DB_PATH) -> None:
        self.db_path = db_path
        self._lock = threading.Lock()
        self._conn: Optional[sqlite3.Connection] = None
        self.ready = False
        self.openalex_matches: Dict[str, Dict[str, Any]] = {}
        self._open()

    def _open(self) -> None:
        if not os.path.exists(self.db_path):
            logger.warning(f"KGService: kg.db not found at {self.db_path}")
            self.ready = False
            return
        try:
            self._conn = sqlite3.connect(
                f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
            n = self._conn.execute("SELECT COUNT(*) FROM kg_entities").fetchone()[0]
            logger.info(f"KGService: opened {self.db_path} ({n} entities)")
            self.openalex_matches = _load_openalex_matches()
            logger.info(
                f"KGService: loaded {len(self.openalex_matches)} faculty<->OpenAlex matches"
            )
            self.ready = True
        except Exception as e:
            logger.error(f"KGService: open failed: {e}")
            self.ready = False

    def _enrich_entity(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """
        If this is a faculty entity, attach OpenAlex stats from the match
        table to the payload (if we have a match).
        """
        if entity.get("type") != "faculty":
            return entity
        # faculty:isu:<id> -> id
        eid = entity.get("id", "")
        prefix = "faculty:isu:"
        if not eid.startswith(prefix):
            return entity
        fid = eid[len(prefix):]
        match = self.openalex_matches.get(fid)
        if not match:
            return entity
        payload = dict(entity.get("payload") or {})
        payload["openalex"] = {
            "id": match.get("openalex_id"),
            "display_name": match.get("openalex_display_name"),
            "h_index": match.get("h_index"),
            "i10_index": match.get("i10_index"),
            "works_count": match.get("works_count"),
            "cited_by_count": match.get("cited_by_count"),
            "orcid": match.get("orcid"),
            "match_confidence": match.get("confidence"),
        }
        entity["payload"] = payload
        return entity

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def stats(self) -> Dict[str, Any]:
        if not self.ready or self._conn is None:
            return {"ready": False, "entities": {}, "edges": {}}
        with self._lock:
            entities = {
                r["type"]: r["c"]
                for r in self._conn.execute(
                    "SELECT type, COUNT(*) AS c FROM kg_entities GROUP BY type"
                )
            }
            edges = {
                r["predicate"]: r["c"]
                for r in self._conn.execute(
                    "SELECT predicate, COUNT(*) AS c FROM kg_edges GROUP BY predicate"
                )
            }
        return {
            "ready": True,
            "entities": entities,
            "edges": edges,
            "total_entities": sum(entities.values()),
            "total_edges": sum(edges.values()),
        }

    def get_entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM kg_entities WHERE id = ?", (entity_id,)
            ).fetchone()
        return self._enrich_entity(_row_to_entity(row)) if row else None

    def search(
        self,
        query: str,
        types: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return []
        q = (query or "").strip()
        if len(q) < 2:
            return []
        # Simple LIKE search on name. FTS would be better; revisit if slow.
        like = f"%{q.lower()}%"
        sql = "SELECT * FROM kg_entities WHERE LOWER(name) LIKE ?"
        params: List[Any] = [like]
        if types:
            placeholders = ",".join("?" for _ in types)
            sql += f" AND type IN ({placeholders})"
            params.extend(types)
        # Prefer entities whose name STARTS with the query, then alphabetic
        sql += " ORDER BY CASE WHEN LOWER(name) LIKE ? THEN 0 ELSE 1 END, name LIMIT ?"
        params.extend([f"{q.lower()}%", limit])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [self._enrich_entity(_row_to_entity(r)) for r in rows]

    def graph_around(
        self,
        root_id: str,
        depth: int = 2,
        max_nodes: int = 200,
    ) -> Dict[str, Any]:
        """
        BFS expansion from a root entity, capped at `depth` hops and `max_nodes`
        total nodes. Returns { root_id, nodes: [...], edges: [...] }.
        """
        if not self.ready or self._conn is None:
            return {"root_id": root_id, "nodes": [], "edges": []}

        depth = max(1, min(depth, 3))
        max_nodes = max(10, min(max_nodes, 500))

        visited: Set[str] = {root_id}
        frontier: Set[str] = {root_id}
        edges_collected: List[Dict[str, Any]] = []
        edge_keys: Set[Tuple[str, str, str]] = set()

        with self._lock:
            for hop in range(depth):
                if not frontier or len(visited) >= max_nodes:
                    break
                placeholders = ",".join("?" for _ in frontier)
                # Outgoing edges
                rows_out = self._conn.execute(
                    f"""
                    SELECT subject_id, predicate, object_id, confidence, source
                    FROM kg_edges
                    WHERE subject_id IN ({placeholders})
                    LIMIT 5000
                    """,
                    list(frontier),
                ).fetchall()
                # Incoming edges
                rows_in = self._conn.execute(
                    f"""
                    SELECT subject_id, predicate, object_id, confidence, source
                    FROM kg_edges
                    WHERE object_id IN ({placeholders})
                    LIMIT 5000
                    """,
                    list(frontier),
                ).fetchall()

                next_frontier: Set[str] = set()
                for r in list(rows_out) + list(rows_in):
                    key = (r["subject_id"], r["predicate"], r["object_id"])
                    if key in edge_keys:
                        continue
                    edge_keys.add(key)
                    edges_collected.append(_row_to_edge(r))
                    other = r["object_id"] if r["subject_id"] in visited else r["subject_id"]
                    if other not in visited and len(visited) < max_nodes:
                        visited.add(other)
                        next_frontier.add(other)
                frontier = next_frontier

            if not visited:
                return {"root_id": root_id, "nodes": [], "edges": []}
            placeholders = ",".join("?" for _ in visited)
            ent_rows = self._conn.execute(
                f"SELECT * FROM kg_entities WHERE id IN ({placeholders})",
                list(visited),
            ).fetchall()

        nodes = [self._enrich_entity(_row_to_entity(r)) for r in ent_rows]
        # Filter edges to those whose endpoints are both in our node set
        present_ids = {n["id"] for n in nodes}
        edges_filtered = [
            e for e in edges_collected
            if e["subject"] in present_ids and e["object"] in present_ids
        ]
        return {
            "root_id": root_id,
            "nodes": nodes,
            "edges": edges_filtered,
            "depth": depth,
            "node_count": len(nodes),
            "edge_count": len(edges_filtered),
            "truncated": len(visited) >= max_nodes,
        }

    def papers_by_author(
        self, author_id: str, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Return papers (kg_entities of type 'paper') authored by an author entity."""
        if not self.ready or self._conn is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT e.*
                FROM kg_edges k
                JOIN kg_entities e ON e.id = k.object_id
                WHERE k.subject_id = ? AND k.predicate = 'authored' AND e.type = 'paper'
                LIMIT ?
                """,
                (author_id, limit),
            ).fetchall()
        return [_row_to_entity(r) for r in rows]

    def authors_of_paper(self, paper_id: str) -> List[Dict[str, Any]]:
        if not self.ready or self._conn is None:
            return []
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT e.*
                FROM kg_edges k
                JOIN kg_entities e ON e.id = k.subject_id
                WHERE k.object_id = ? AND k.predicate = 'authored'
                """,
                (paper_id,),
            ).fetchall()
        return [_row_to_entity(r) for r in rows]


# Lazy singleton
_kg_service: Optional[KGService] = None


def get_kg_service() -> KGService:
    global _kg_service
    if _kg_service is None:
        _kg_service = KGService()
    return _kg_service
