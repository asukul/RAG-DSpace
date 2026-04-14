"""
Hybrid dense + BM25 ingest for the dspace_fulltext_vertex collection.

Extends the existing `embed_vertex_batch_real.py --phase ingest` with BM25
sparse vectors so the backend can do hybrid retrieval (dense prefetch + BM25
prefetch, RRF fused). Reason: dense-only retrieval on 1M fulltext chunks is
too noisy for keyword-heavy queries like "K-12 computer science education" —
the dense embedder weighs "outreach" and "education" too strongly and pulls
plant-science papers first. BM25 brings back exact-keyword matching.

Pipeline (replacement for `--phase ingest`):
  1. Build the BM25 vocabulary from backend/data/dspace/chunk_hash_index.jsonl
     (rebuilt from PDFs on 2026-04-13). Saves to backend/data/bm25_vocab_vertex.json.
  2. Delete any existing `dspace_fulltext_vertex` collection.
  3. Recreate with BOTH dense (named "dense", 768d cosine) AND sparse
     (named "bm25") vector configs.
  4. Walk the Vertex output files; for each successful prediction:
       - lookup metadata by content-hash (same as the fixed ingest)
       - compute BM25 sparse vector from the chunk text
       - upsert a point with BOTH the dense embedding AND the sparse vector
  5. Save the vocabulary so the live backend's `_bm25_query_vector()` helper
     can build query-side sparse vectors against the same token ids.

Usage:
    python backend/scripts/embed_vertex_hybrid_ingest.py
    python backend/scripts/embed_vertex_hybrid_ingest.py --limit 10000  # smoke test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import time
import uuid as uuid_mod
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent

CHUNK_HASH_INDEX = BACKEND / "data" / "dspace" / "chunk_hash_index.jsonl"
VERTEX_OUT_PARTS = [
    BACKEND / "data" / "dspace" / "vertex_batch_output_part0",
    BACKEND / "data" / "dspace" / "vertex_batch_output_part1",
]
VOCAB_FILE = BACKEND / "data" / "bm25_vocab_vertex.json"

QDRANT_LOCAL = "http://localhost:6334"
COLLECTION = "dspace_fulltext_vertex"
DSPACE_BASE_URL = os.environ.get("DSPACE_BASE_URL", "https://dr.lib.iastate.edu")
NAMESPACE = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

BM25_K1 = 1.5
BM25_B = 0.75
BATCH_SIZE = 100
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "while", "with", "of", "to",
    "in", "on", "at", "by", "for", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can", "this",
    "that", "these", "those", "it", "its", "i", "you", "he", "she", "we", "they",
    "them", "their", "his", "her", "our", "your", "my", "me", "us",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    out = []
    for tok in TOKEN_RE.findall(text):
        t = tok.lower()
        if len(t) < 3 or t in STOP_WORDS:
            continue
        out.append(t)
    return out


def build_vocab_from_chunk_hash_index(
    limit: Optional[int] = None,
) -> Tuple[Dict[str, int], Dict[str, int], int, float]:
    """
    One-pass read of chunk_hash_index.jsonl to compute:
      - df[term]: number of chunks containing the term
      - token_to_id[term]: stable int id for the term (sorted by df desc)
      - n_docs: total chunks
      - avgdl: average tokens per chunk (after tokenize())

    chunk_hash_index.jsonl has `content_prefix` (first 200 chars) but NOT full
    content. We tokenize the prefix — that's the same thing we do at query
    time, so BM25 weighting is consistent across indexing and query.

    NOTE: in practice, full content would give better BM25 quality. We use
    prefix here because the full content lives in the Vertex output files,
    and doing a full-text BM25 build would require walking 7 GB of output
    files twice (once for vocab, once for ingest). The prefix-based vocab is
    a reasonable approximation — ~200 chars covers most distinctive keywords
    in an academic chunk.
    """
    log(f"Pass 1: build vocab from {CHUNK_HASH_INDEX.name}")
    df_counter: Counter = Counter()
    n_docs = 0
    total_len = 0
    with open(CHUNK_HASH_INDEX, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            try:
                rec = json.loads(line)
            except Exception:
                continue
            # Use title + content_prefix — gives BM25 some title signal too
            title = rec.get("title") or ""
            prefix = rec.get("content_prefix") or ""
            text = f"{title} {prefix}"
            toks = tokenize(text)
            if not toks:
                continue
            for t in set(toks):
                df_counter[t] += 1
            n_docs += 1
            total_len += len(toks)
            if n_docs % 100_000 == 0:
                log(f"  scanned {n_docs:,} chunks, vocab={len(df_counter):,}")

    avgdl = total_len / max(n_docs, 1)
    log(f"  done: {n_docs:,} docs, avgdl={avgdl:.1f}, vocab={len(df_counter):,}")

    token_to_id: Dict[str, int] = {}
    for i, (tok, _df) in enumerate(df_counter.most_common()):
        token_to_id[tok] = i
    return df_counter, token_to_id, n_docs, avgdl


def bm25_sparse(
    text: str,
    df_counter: Dict[str, int],
    token_to_id: Dict[str, int],
    n_docs: int,
    avgdl: float,
) -> Tuple[List[int], List[float]]:
    toks = tokenize(text)
    if not toks:
        return [], []
    tf = Counter(toks)
    dl = len(toks)
    indices: List[int] = []
    values: List[float] = []
    for term, freq in tf.items():
        df = df_counter.get(term, 0)
        if df == 0:
            continue
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        score = idf * (freq * (BM25_K1 + 1)) / (
            freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl)
        )
        tid = token_to_id.get(term)
        if tid is None:
            continue
        indices.append(tid)
        values.append(round(score, 4))
    return indices, values


def save_vocab(
    df_counter: Dict[str, int],
    token_to_id: Dict[str, int],
    n_docs: int,
    avgdl: float,
) -> None:
    VOCAB_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = VOCAB_FILE.with_suffix(VOCAB_FILE.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "n_docs": n_docs,
                "avgdl": avgdl,
                "k1": BM25_K1,
                "b": BM25_B,
                "df": dict(df_counter),
                "token_to_id": token_to_id,
                "collection": COLLECTION,
            },
            f,
        )
    tmp.replace(VOCAB_FILE)
    log(f"  wrote vocab to {VOCAB_FILE} ({VOCAB_FILE.stat().st_size / 1024 / 1024:.1f} MB)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None, help="Cap chunks (smoke test)")
    parser.add_argument("--skip-vocab", action="store_true",
                        help="Reuse existing bm25_vocab_vertex.json without rebuilding")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if not CHUNK_HASH_INDEX.exists():
        log(f"ERROR: {CHUNK_HASH_INDEX} not found")
        return 1

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    if args.skip_vocab and VOCAB_FILE.exists():
        log(f"Reusing existing vocab at {VOCAB_FILE}")
        with VOCAB_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
        df_counter = data["df"]
        token_to_id = data["token_to_id"]
        n_docs = data["n_docs"]
        avgdl = data["avgdl"]
    else:
        df_counter, token_to_id, n_docs, avgdl = build_vocab_from_chunk_hash_index(
            limit=args.limit
        )
        save_vocab(df_counter, token_to_id, n_docs, avgdl)

    # Build the content_hash -> metadata map for ingest (same as the fixed ingest)
    log("Building content-hash -> metadata lookup...")
    hash_to_meta: Dict[bytes, Dict[str, Any]] = {}
    with open(CHUNK_HASH_INDEX, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            h = rec.get("content_hash")
            if not h:
                continue
            hash_to_meta[bytes.fromhex(h)] = rec
    log(f"  {len(hash_to_meta):,} entries")

    # Delete any existing collection and recreate with hybrid schema
    qc = QdrantClient(url=QDRANT_LOCAL, timeout=120)
    try:
        qc.delete_collection(COLLECTION)
        log(f"Deleted existing collection {COLLECTION}")
    except Exception:
        pass

    qc.create_collection(
        collection_name=COLLECTION,
        vectors_config={
            "dense": qm.VectorParams(size=768, distance=qm.Distance.COSINE),
        },
        sparse_vectors_config={
            "bm25": qm.SparseVectorParams(
                index=qm.SparseIndexParams(on_disk=False),
            ),
        },
    )
    log(f"Created hybrid collection {COLLECTION} (dense + bm25 sparse)")

    # Walk Vertex output parts and upsert
    total = 0
    skipped_no_match = 0
    for part_idx, part_dir in enumerate(VERTEX_OUT_PARTS):
        if not part_dir.exists():
            log(f"  [part {part_idx}] missing {part_dir} — skipping")
            continue
        files = sorted(part_dir.glob("*.jsonl"))
        log(f"[part {part_idx}] {len(files)} output files")
        for out_file in files:
            log(f"  processing {out_file.name}")
            batch_points = []
            with open(out_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    instance = d.get("instance", {})
                    preds = d.get("predictions", [])
                    if not preds:
                        continue
                    embedding = preds[0].get("embeddings", {}).get("values", [])
                    if not embedding:
                        continue
                    chunk_text = instance.get("content", "")
                    if not chunk_text:
                        continue

                    meta = hash_to_meta.get(
                        hashlib.sha1(chunk_text.encode("utf-8")).digest()
                    )
                    if meta is None:
                        skipped_no_match += 1
                        continue

                    doc_uuid = meta.get("uuid", "")
                    chunk_idx_val = meta.get("chunk_idx", 0)
                    point_id = str(uuid_mod.uuid5(NAMESPACE, f"{doc_uuid}#{chunk_idx_val}"))

                    # Build BM25 sparse from the full chunk text (not the
                    # prefix we used for vocab building — more signal).
                    title = meta.get("title") or ""
                    sparse_ids, sparse_vals = bm25_sparse(
                        f"{title} {chunk_text}",
                        df_counter,
                        token_to_id,
                        n_docs,
                        avgdl,
                    )

                    payload = {
                        "uuid": doc_uuid,
                        "chunk_id": f"{doc_uuid}#{chunk_idx_val}",
                        "chunk_idx": chunk_idx_val,
                        "chunk_total": meta.get("chunk_total", 1),
                        "doc_title": title,
                        "authors": meta.get("authors", []),
                        "year": meta.get("year", ""),
                        "type": meta.get("type", ""),
                        "department": meta.get("department", ""),
                        "collection": meta.get("collection", ""),
                        "dspace_url": (
                            f"{DSPACE_BASE_URL}/items/{doc_uuid}" if doc_uuid else ""
                        ),
                        "heading": "",
                        "page": 0,
                        "text": chunk_text,
                    }

                    vector_payload: Dict[str, Any] = {"dense": embedding}
                    if sparse_ids:
                        vector_payload["bm25"] = qm.SparseVector(
                            indices=sparse_ids, values=sparse_vals
                        )

                    batch_points.append(qm.PointStruct(
                        id=point_id,
                        vector=vector_payload,
                        payload=payload,
                    ))
                    if len(batch_points) >= BATCH_SIZE:
                        qc.upsert(
                            collection_name=COLLECTION,
                            points=batch_points,
                            wait=True,
                        )
                        total += len(batch_points)
                        batch_points = []
            if batch_points:
                qc.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
                total += len(batch_points)

    log(f"Ingested {total:,} hybrid points, skipped {skipped_no_match:,} (no hash match)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
