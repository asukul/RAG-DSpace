"""
Phase 4b — embed every DSpace item's title + abstract as a single "abstract chunk"
and upsert directly to the Qdrant `dspace_chunks` collection.

Why:
  The existing collection only contains chunks from ~484 papers whose PDFs were
  processed via opendataloader-pdf — barely 0.6 % of the 82,656-item harvest.
  Phase 4 (topic→paper linking via embedding similarity) only sees those 484
  papers. Embedding each item's title + abstract gives 100 % corpus coverage
  for topic linkage at ~$1 in Vertex calls.

Schema:
  Point id:    UUIDv5 of "{uuid}#abstract"
  chunk_id:    "{uuid}#abstract"
  chunk_idx:   -1                 (sentinel for "abstract chunk", not a PDF chunk)
  heading:     "Abstract"
  page:        0
  text:        the abstract (or title fallback)
  uuid/year/type/doc_title/authors/dspace_url: copied from dspace_index.db

Resume:
  On startup, scrolls Qdrant once to collect all existing chunk_ids matching
  `*#abstract` and skips them. Re-runs are safe.

Run:
    python backend/scripts/embed_abstracts_to_qdrant.py
    python backend/scripts/embed_abstracts_to_qdrant.py --limit 100        # dry-run small batch
    python backend/scripts/embed_abstracts_to_qdrant.py --no-skip          # re-embed everything
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
import traceback
import uuid as _uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

BACKEND = Path(__file__).resolve().parent.parent
DSPACE_DB = BACKEND / "data" / "dspace" / "dspace_index.db"

GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
VERTEX_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-005")
EMBED_DIM = 768

QDRANT_URL = os.getenv("QDRANT_URL", "http://35.188.64.146:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "dspace_chunks")

BATCH_SIZE = 25                 # texts per Vertex call
MAX_WORKERS = 4                 # parallel batches
QDRANT_BATCH = 256              # points per Qdrant upsert
PROGRESS_EVERY = 1000

VERTEX_PRICE_PER_M_CHARS = 0.025

# Cap embed text length so we don't blow Vertex's 2048-token (~8k char) limit.
MAX_EMBED_CHARS = 7500

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("embed_abstracts")


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def _stable_uuid(chunk_id: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, chunk_id))


def build_embed_text(title: str, abstract: str) -> str:
    title = (title or "").strip()
    abstract = (abstract or "").strip()
    if abstract:
        text = f"{title}\n\nAbstract: {abstract}"
    else:
        text = title
    if len(text) > MAX_EMBED_CHARS:
        text = text[:MAX_EMBED_CHARS]
    return text


def parse_authors(authors_json: Optional[str]) -> str:
    if not authors_json:
        return ""
    try:
        arr = json.loads(authors_json)
        if isinstance(arr, list):
            return "; ".join(str(a) for a in arr if a)
    except Exception:
        pass
    return ""


def parse_year(year_val: Any, issued: Optional[str] = None) -> str:
    if year_val:
        s = str(year_val).strip()
        if s and s[:4].isdigit():
            return s[:4]
    if issued:
        s = str(issued).strip()
        if s and s[:4].isdigit():
            return s[:4]
    return ""


def categorize_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg:
        return "quota_error"
    if any(s in msg for s in ("503", "504", "deadline", "timeout", "connection",
                              "unavailable", "transport")):
        return "transport_error"
    if "400" in msg and ("token count" in msg or "invalid_argument" in msg):
        return "token_limit_error"
    return "other_error"


# ----------------------------------------------------------------------
# Vertex client
# ----------------------------------------------------------------------

def make_vertex_client():
    from google import genai
    return genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)


def _embed_call(client, texts: List[str]) -> List[List[float]]:
    from google.genai import types as genai_types
    result = client.models.embed_content(
        model=VERTEX_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBED_DIM,
        ),
    )
    return [list(e.values) for e in result.embeddings]


def embed_batch(
    client,
    texts: List[str],
    max_attempts: int = 4,
) -> Tuple[Optional[List[List[float]]], Optional[str]]:
    last_err: Optional[BaseException] = None
    last_cat: Optional[str] = None
    for attempt in range(max_attempts):
        try:
            return _embed_call(client, texts), None
        except Exception as exc:
            last_err = exc
            last_cat = categorize_error(exc)
            if last_cat == "token_limit_error":
                if len(texts) <= 1:
                    log.error(f"single text exceeds token limit: {exc}")
                    return None, last_cat
                mid = len(texts) // 2
                log.warning(f"token_limit on batch of {len(texts)} — splitting")
                left, lcat = embed_batch(client, texts[:mid], max_attempts)
                right, rcat = embed_batch(client, texts[mid:], max_attempts)
                if left is None or right is None:
                    return None, lcat or rcat or "token_limit_error"
                return left + right, None
            if last_cat == "quota_error" and attempt < max_attempts - 1:
                wait = 5 * (2 ** attempt)
                log.warning(f"quota_error attempt {attempt+1} — sleep {wait}s")
                time.sleep(wait)
                continue
            if last_cat == "transport_error" and attempt < max_attempts - 1:
                wait = 2 * (attempt + 1)
                log.warning(f"transport_error attempt {attempt+1} — sleep {wait}s")
                time.sleep(wait)
                continue
            break
    log.error(f"batch failed permanently ({last_cat}): {last_err}")
    return None, last_cat or "other_error"


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------

def load_dspace_items() -> List[Dict[str, Any]]:
    if not DSPACE_DB.exists():
        log.error(f"dspace_index.db not found at {DSPACE_DB}")
        sys.exit(2)
    log.info(f"Loading items from {DSPACE_DB}")
    conn = sqlite3.connect(DSPACE_DB)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT uuid, title, abstract, authors_json, year, issued, type,
               dspace_url, collection_name
        FROM items
        WHERE uuid IS NOT NULL AND title IS NOT NULL AND title != ''
        ORDER BY uuid
        """
    ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    log.info(f"Loaded {len(items)} items from dspace_index.db")
    return items


def load_existing_abstract_chunk_ids(qclient: QdrantClient) -> set:
    """Scroll Qdrant for all chunk_ids ending in '#abstract'."""
    log.info("Scanning Qdrant for existing abstract chunks (resume support)...")
    found: set = set()
    offset = None
    total = 0
    t0 = time.time()
    while True:
        try:
            pts, next_off = qclient.scroll(
                collection_name=QDRANT_COLLECTION,
                limit=2000,
                offset=offset,
                with_payload=["chunk_id"],
                with_vectors=False,
                scroll_filter=qm.Filter(
                    must=[qm.FieldCondition(
                        key="chunk_idx",
                        match=qm.MatchValue(value=-1),
                    )]
                ),
            )
        except Exception as e:
            # If chunk_idx isn't indexed for filtering, fall back to a full scan.
            log.warning(f"filtered scroll failed ({e}); falling back to full scan")
            return _scan_all_for_abstract(qclient)
        for p in pts:
            cid = (p.payload or {}).get("chunk_id")
            if cid:
                found.add(cid)
        total += len(pts)
        if next_off is None:
            break
        offset = next_off
    log.info(f"Found {len(found)} existing abstract chunks in {time.time()-t0:.1f}s")
    return found


def _scan_all_for_abstract(qclient: QdrantClient) -> set:
    found: set = set()
    offset = None
    total = 0
    t0 = time.time()
    while True:
        pts, next_off = qclient.scroll(
            collection_name=QDRANT_COLLECTION,
            limit=2000,
            offset=offset,
            with_payload=["chunk_id"],
            with_vectors=False,
        )
        for p in pts:
            cid = (p.payload or {}).get("chunk_id") or ""
            if cid.endswith("#abstract"):
                found.add(cid)
        total += len(pts)
        if next_off is None:
            break
        offset = next_off
    log.info(f"Full scan: {total} points, {len(found)} abstract chunks in {time.time()-t0:.1f}s")
    return found


# ----------------------------------------------------------------------
# Qdrant point builder
# ----------------------------------------------------------------------

def to_point(item: Dict[str, Any], embedding: List[float]) -> qm.PointStruct:
    uuid = item["uuid"]
    chunk_id = f"{uuid}#abstract"
    payload = {
        "chunk_id": chunk_id,
        "uuid": uuid,
        "chunk_idx": -1,
        "doc_title": item.get("title") or "",
        "authors": parse_authors(item.get("authors_json")),
        "year": parse_year(item.get("year"), item.get("issued")),
        "type": item.get("type") or "",
        "dspace_url": item.get("dspace_url") or "",
        "heading": "Abstract",
        "page": 0,
        "text": (item.get("abstract") or "").strip() or (item.get("title") or "").strip(),
        "collection_name": item.get("collection_name") or "",
    }
    return qm.PointStruct(
        id=_stable_uuid(chunk_id),
        vector={"dense": list(embedding)},
        payload=payload,
    )


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------

def worker_embed(client, batch_items: List[Dict[str, Any]]):
    texts = [build_embed_text(it.get("title") or "", it.get("abstract") or "")
             for it in batch_items]
    char_count = sum(len(t) for t in texts)
    embeddings, err_cat = embed_batch(client, texts)
    if embeddings is None:
        return [], [(it["uuid"], err_cat or "other_error") for it in batch_items], char_count
    success: List[qm.PointStruct] = []
    for it, emb in zip(batch_items, embeddings):
        if emb and len(emb) == EMBED_DIM:
            success.append(to_point(it, emb))
    return success, [], char_count


def chunked(seq: List[Any], size: int):
    for i in range(0, len(seq), size):
        yield seq[i: i + size]


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0,
                        help="If >0, only embed the first N items (for testing)")
    parser.add_argument("--no-skip", action="store_true",
                        help="Re-embed even if an abstract chunk already exists")
    parser.add_argument("--smoke", action="store_true",
                        help="Run a single smoke query at the end")
    args = parser.parse_args()

    t_start = time.time()

    items = load_dspace_items()

    qclient = QdrantClient(url=QDRANT_URL, timeout=120)
    qclient.get_collection(QDRANT_COLLECTION)  # sanity

    if args.no_skip:
        existing = set()
        log.info("--no-skip: skipping existing-chunk lookup")
    else:
        existing = load_existing_abstract_chunk_ids(qclient)

    pending = [it for it in items if f'{it["uuid"]}#abstract' not in existing]
    log.info(f"Pending: {len(pending)} items (skipped {len(items) - len(pending)} already done)")

    if args.limit and args.limit < len(pending):
        pending = pending[: args.limit]
        log.info(f"--limit {args.limit}: embedding first {len(pending)} items")

    if not pending:
        log.info("Nothing to do.")
        return 0

    log.info(
        f"Embedding {len(pending)} items via Vertex {VERTEX_MODEL} "
        f"(batch={BATCH_SIZE}, workers={MAX_WORKERS})"
    )

    vclient = make_vertex_client()
    batches = list(chunked(pending, BATCH_SIZE))
    log.info(f"Total batches: {len(batches)}")

    failures: List[Tuple[str, str]] = []
    err_counts: Dict[str, int] = {}
    api_calls = 0
    total_chars = 0
    embedded = 0
    pending_points: List[qm.PointStruct] = []
    last_progress = 0

    def flush_qdrant(force: bool = False):
        nonlocal pending_points
        if not pending_points:
            return
        if not force and len(pending_points) < QDRANT_BATCH:
            return
        try:
            qclient.upsert(
                collection_name=QDRANT_COLLECTION,
                points=pending_points,
                wait=force,
            )
            pending_points = []
        except Exception as e:
            log.error(f"Qdrant upsert failed for {len(pending_points)} points: {e}")
            # Drop them — failures are logged separately via the embed step.
            pending_points = []

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            future_to_batch = {ex.submit(worker_embed, vclient, b): b for b in batches}
            for fut in as_completed(future_to_batch):
                api_calls += 1
                batch = future_to_batch[fut]
                try:
                    success_pts, failed, char_count = fut.result()
                except Exception as e:
                    log.error(f"worker crashed: {e}")
                    failed = [(it["uuid"], "other_error") for it in batch]
                    success_pts, char_count = [], 0

                total_chars += char_count
                if success_pts:
                    pending_points.extend(success_pts)
                    embedded += len(success_pts)
                    flush_qdrant()

                for uid, cat in failed:
                    err_counts[cat] = err_counts.get(cat, 0) + 1
                    failures.append((uid, cat))

                if embedded - last_progress >= PROGRESS_EVERY:
                    elapsed = time.time() - t_start
                    rate = embedded / elapsed if elapsed > 0 else 0
                    cost_so_far = (total_chars / 1_000_000) * VERTEX_PRICE_PER_M_CHARS
                    log.info(
                        f"progress: {embedded}/{len(pending)} "
                        f"({rate:.1f}/s) failed={len(failures)} "
                        f"chars={total_chars:,} cost_est=${cost_so_far:.4f}"
                    )
                    last_progress = embedded
    finally:
        flush_qdrant(force=True)

    elapsed = time.time() - t_start
    cost = (total_chars / 1_000_000) * VERTEX_PRICE_PER_M_CHARS
    info = qclient.get_collection(QDRANT_COLLECTION)

    print()
    print("=" * 72)
    print("ABSTRACT EMBEDDING SUMMARY")
    print("=" * 72)
    print(f"Items considered:           {len(items)}")
    print(f"Already in Qdrant (skipped):{len(items) - len(pending) if not args.limit else 'n/a'}")
    print(f"Embedded this run:          {embedded}")
    print(f"Wall time:                  {elapsed:.1f}s")
    print(f"Throughput:                 {embedded/elapsed if elapsed > 0 else 0:.1f}/s")
    print(f"Vertex API calls:           {api_calls}")
    print(f"Total chars embedded:       {total_chars:,}")
    print(f"Estimated cost:             ${cost:.4f}")
    print(f"Failures:                   {len(failures)}  {dict(err_counts)}")
    print(f"Qdrant collection points:   {info.points_count}")
    print("=" * 72)

    if failures and len(failures) > 5:
        print("\nFirst 5 failures:")
        for uid, cat in failures[:5]:
            print(f"  {uid}  {cat}")

    if args.smoke:
        print("\nSmoke query: 'machine learning'")
        from google.genai import types as genai_types
        result = vclient.models.embed_content(
            model=VERTEX_MODEL,
            contents=["machine learning"],
            config=genai_types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBED_DIM,
            ),
        )
        qv = list(result.embeddings[0].values)
        # Filter to abstract chunks only so we see the new data
        hits = qclient.query_points(
            collection_name=QDRANT_COLLECTION,
            query=qv,
            using="dense",
            limit=5,
            with_payload=True,
            query_filter=qm.Filter(
                must=[qm.FieldCondition(
                    key="chunk_idx",
                    match=qm.MatchValue(value=-1),
                )]
            ),
        )
        for hit in hits.points:
            p = hit.payload or {}
            print(f"  {hit.score:.3f}  {(p.get('doc_title') or '')[:70]}")

    return 0 if not failures else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("Interrupted")
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(2)
