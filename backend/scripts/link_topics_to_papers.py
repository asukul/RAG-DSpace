"""
Phase 4 (alternative) — link topics to papers via semantic similarity using
the EXISTING Vertex embeddings in Qdrant. No LLM required, no quota issues.

For each topic in kg_entities (765 topics from faculty research_interests):
  1. Embed the topic name with Vertex text-embedding-005 (one-time, 765 calls).
  2. Query Qdrant `dspace_chunks` for the top-K most similar chunks.
  3. Group by paper UUID, create `paper -ABOUT-> topic` edges in kg.db.

This is the fast, free, deterministic version of Phase 4. The LLM-driven
version (extract_topics_llm.py) will run in the background to add additional
topic surface forms not in faculty.json.

Run:
    python backend/scripts/link_topics_to_papers.py
    python backend/scripts/link_topics_to_papers.py --top-k 30 --min-score 0.55
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

from google import genai
from google.genai import types as gen_types
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
KG_DB = BACKEND / "data" / "dspace" / "kg.db"

GCP_PROJECT = os.environ.get("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://35.188.64.146:6333")
QDRANT_COLLECTION = os.environ.get("QDRANT_COLLECTION", "dspace_chunks")
EMBED_MODEL = "text-embedding-005"
EMBED_DIM = 768


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def fetch_topics(conn: sqlite3.Connection) -> List[Tuple[str, str]]:
    """Returns [(topic_id, name), ...]"""
    rows = conn.execute(
        "SELECT id, name FROM kg_entities WHERE type = 'topic' ORDER BY name"
    ).fetchall()
    return [(r[0], r[1]) for r in rows]


def embed_text(client: genai.Client, text: str) -> List[float] | None:
    try:
        result = client.models.embed_content(
            model=EMBED_MODEL,
            contents=[text],
            config=gen_types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBED_DIM,
            ),
        )
        return list(result.embeddings[0].values)
    except Exception as e:
        print(f"  embed err for {text[:40]!r}: {e}", file=sys.stderr)
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=20,
                        help="How many similar chunks to fetch per topic")
    parser.add_argument("--min-score", type=float, default=0.55,
                        help="Minimum cosine similarity to create an ABOUT edge")
    parser.add_argument("--limit-topics", type=int, default=0)
    parser.add_argument("--clear-existing", action="store_true",
                        help="Delete previous embedding_similarity ABOUT edges before re-running")
    args = parser.parse_args()

    print(f"Linking topics to papers via semantic similarity")
    print(f"  KG db:        {KG_DB}")
    print(f"  Qdrant:       {QDRANT_URL} / {QDRANT_COLLECTION}")
    print(f"  Embed model:  {EMBED_MODEL}")
    print(f"  top_k={args.top_k}, min_score={args.min_score}")
    print()

    # ---------- Open KG db (read+write) ----------
    if not KG_DB.exists():
        print(f"ERROR: kg.db not found", file=sys.stderr)
        return 2
    conn = sqlite3.connect(KG_DB)
    conn.row_factory = sqlite3.Row

    # Clear stale edges if requested
    if args.clear_existing:
        n = conn.execute(
            "DELETE FROM kg_edges WHERE predicate = 'about' AND source = 'embedding_similarity'"
        ).rowcount
        conn.commit()
        print(f"  cleared {n} previous embedding_similarity ABOUT edges")

    # Build a set of valid paper IDs so we only link to entities that exist.
    # The Qdrant collection was built from a different/older harvest, so its
    # chunk uuids don't all overlap with the current kg_entities papers.
    print("  loading valid paper IDs from kg_entities...")
    valid_papers = {
        r["id"] for r in conn.execute(
            "SELECT id FROM kg_entities WHERE type = 'paper'"
        )
    }
    print(f"  {len(valid_papers)} paper entities loaded")

    # ---------- Open Qdrant ----------
    qclient = QdrantClient(url=QDRANT_URL, timeout=60)
    qclient.get_collection(QDRANT_COLLECTION)  # sanity check

    # ---------- Vertex embedding client ----------
    eclient = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)

    # ---------- Topics ----------
    topics = fetch_topics(conn)
    if args.limit_topics:
        topics = topics[: args.limit_topics]
    print(f"  topics: {len(topics)}")

    n_edges_total = 0
    n_topics_with_edges = 0
    t0 = time.time()

    for i, (topic_id, name) in enumerate(topics, 1):
        qv = embed_text(eclient, name)
        if not qv:
            continue

        try:
            results = qclient.query_points(
                collection_name=QDRANT_COLLECTION,
                query=qv,
                using="dense",
                limit=args.top_k,
                with_payload=True,
            )
        except Exception as e:
            print(f"  qdrant err for {name!r}: {e}", file=sys.stderr)
            continue

        # Group by uuid; pick best score per paper
        per_paper: Dict[str, float] = {}
        for hit in results.points:
            uuid = (hit.payload or {}).get("uuid")
            if not uuid or hit.score < args.min_score:
                continue
            paper_eid = f"paper:dspace:{uuid}"
            # Skip Qdrant chunks whose paper isn't in our current kg_entities
            if paper_eid not in valid_papers:
                continue
            if uuid not in per_paper or hit.score > per_paper[uuid]:
                per_paper[uuid] = float(hit.score)

        if not per_paper:
            continue

        n_topics_with_edges += 1
        edges_added = 0
        for uuid, score in per_paper.items():
            paper_eid = f"paper:dspace:{uuid}"
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO kg_edges
                        (subject_id, predicate, object_id, confidence, source, source_paper_id, created_at)
                    VALUES (?, 'about', ?, ?, 'embedding_similarity', ?, ?)
                    """,
                    (paper_eid, topic_id, round(score, 4), uuid, now_iso()),
                )
                edges_added += 1
            except Exception as e:
                print(f"  insert err: {e}", file=sys.stderr)
        n_edges_total += edges_added

        if i % 25 == 0 or i == len(topics):
            conn.commit()
            elapsed = time.time() - t0
            rate = i / max(elapsed, 0.01)
            print(
                f"  [{i}/{len(topics)}] topic={name[:40]:40s}  edges={edges_added:3d}  total_edges={n_edges_total}  ({rate:.1f}/s)",
                flush=True,
            )

    conn.commit()
    conn.close()

    print()
    print("=" * 60)
    print(f"Done in {(time.time() - t0)/60:.1f} min")
    print(f"  topics with at least one edge: {n_topics_with_edges}/{len(topics)}")
    print(f"  total ABOUT edges:             {n_edges_total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
