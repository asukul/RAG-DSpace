"""
Populate the existing `dspace_chunks` Qdrant collection with BM25 sparse
vectors so we can run hybrid (dense + sparse) retrieval.

Strategy:
- Read all chunk text from `backend/data/chunk_embeddings.parquet` (39,255 rows).
- Tokenize each chunk (lowercase, alphanumeric, drop short tokens & stop words).
- Compute corpus-wide IDF and document length statistics.
- For every chunk, build a BM25-weighted sparse vector using the standard
  formula:
      score(t, d) = IDF(t) * (tf(t,d) * (k1 + 1)) /
                    (tf(t,d) + k1 * (1 - b + b * |d|/avgdl))
- Upsert each chunk by its existing UUIDv5(chunk_id) point ID with
  `vector={"bm25": SparseVector(indices, values)}` (partial vector update —
  the dense vector is left untouched).

This is a pre-processing job. Run on the developer workstation, then redeploy
the backend (the runtime change is in `qdrant_rag_service._retrieve` to use
hybrid retrieval).

Run:
    python backend/scripts/add_bm25_to_qdrant.py
    python backend/scripts/add_bm25_to_qdrant.py --dry-run
    python backend/scripts/add_bm25_to_qdrant.py --limit 1000     # smoke test
"""

from __future__ import annotations

import argparse
import math
import os
import re
import sys
import time
import uuid as _uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import pyarrow.parquet as pq
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

QDRANT_URL = os.environ.get("QDRANT_URL", "http://35.188.64.146:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "dspace_chunks")
PARQUET = Path(__file__).parent.parent / "data" / "chunk_embeddings.parquet"

# BM25 hyperparameters (Okapi defaults)
BM25_K1 = 1.5
BM25_B = 0.75
BATCH_SIZE = 128

# Minimal stop word list — leaving most words in is fine for this corpus
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "while", "with", "of", "to",
    "in", "on", "at", "by", "for", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can", "this",
    "that", "these", "those", "it", "its", "i", "you", "he", "she", "we", "they",
    "them", "their", "his", "her", "our", "your", "my", "me", "us",
}

TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def stable_uuid(chunk_id: str) -> str:
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, chunk_id))


def tokenize(text: str) -> List[str]:
    """Lowercase, alphanumeric, drop short tokens and stop words."""
    if not text:
        return []
    out = []
    for tok in TOKEN_RE.findall(text):
        t = tok.lower()
        if len(t) < 3 or t in STOP_WORDS:
            continue
        out.append(t)
    return out


def iter_parquet_rows(path: Path, limit: int | None = None) -> Iterable[dict]:
    pf = pq.ParquetFile(path)
    n = 0
    for batch in pf.iter_batches(batch_size=512):
        for row in batch.to_pylist():
            yield row
            n += 1
            if limit and n >= limit:
                return


def build_idf(parquet_path: Path, limit: int | None = None) -> Tuple[Dict[str, int], int, float]:
    """
    First pass: compute document frequency for each term, total document count,
    and average document length. Returns (token_to_id, N, avgdl).
    """
    df_counter: Counter[str] = Counter()
    total_len = 0
    n_docs = 0
    print("Pass 1: scanning corpus for IDF + document lengths...")
    for row in iter_parquet_rows(parquet_path, limit=limit):
        toks = tokenize(row.get("text") or "")
        if not toks:
            continue
        unique = set(toks)
        for t in unique:
            df_counter[t] += 1
        total_len += len(toks)
        n_docs += 1
        if n_docs % 5000 == 0:
            print(f"  scanned {n_docs} chunks, vocab so far: {len(df_counter)}")
    avgdl = total_len / max(n_docs, 1)
    print(f"  done: {n_docs} docs, avgdl={avgdl:.1f}, vocab={len(df_counter)}")

    # Build a stable token -> id mapping. Sort by document frequency desc so
    # the most common terms get the smallest IDs (helps Qdrant compress).
    token_to_id = {}
    for i, (tok, _df) in enumerate(df_counter.most_common()):
        token_to_id[tok] = i
    return df_counter, token_to_id, n_docs, avgdl


def bm25_sparse_vector(
    text: str,
    df_counter: Dict[str, int],
    token_to_id: Dict[str, int],
    n_docs: int,
    avgdl: float,
) -> Tuple[List[int], List[float]]:
    """
    Build a (indices, values) BM25 sparse vector for one document.
    """
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
        # Robertson-Spärck-Jones IDF (the BM25-Okapi flavor)
        idf = math.log(1 + (n_docs - df + 0.5) / (df + 0.5))
        score = idf * (freq * (BM25_K1 + 1)) / (
            freq + BM25_K1 * (1 - BM25_B + BM25_B * dl / avgdl)
        )
        indices.append(token_to_id[term])
        values.append(round(score, 4))
    return indices, values


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N chunks (smoke test)")
    parser.add_argument("--batch", type=int, default=BATCH_SIZE)
    args = parser.parse_args()

    if not PARQUET.exists():
        print(f"ERROR: parquet not found at {PARQUET}", file=sys.stderr)
        return 2

    # Pass 1: IDF + avgdl
    df_counter, token_to_id, n_docs, avgdl = build_idf(PARQUET, limit=args.limit)

    if args.dry_run:
        # Just demonstrate one sparse vector
        print()
        print("Pass 2 dry run: building sparse vector for first chunk...")
        for row in iter_parquet_rows(PARQUET, limit=1):
            ids, vals = bm25_sparse_vector(
                row.get("text") or "", df_counter, token_to_id, n_docs, avgdl
            )
            print(f"  chunk: {row['chunk_id']}")
            print(f"  text len: {len(row.get('text',''))}")
            print(f"  unique tokens: {len(ids)}")
            print(f"  top 5 (token_id, weight): {sorted(zip(ids, vals), key=lambda x: -x[1])[:5]}")
        print("dry-run complete")
        return 0

    # Pass 2: build sparse vectors and upsert
    client = QdrantClient(url=QDRANT_URL, timeout=120)
    info = client.get_collection(COLLECTION)
    print(f"Collection {COLLECTION}: {info.points_count} points")
    print()
    print(f"Pass 2: building + upserting BM25 sparse vectors (batch={args.batch})...")

    batch_points: List[qm.PointStruct] = []
    n_upserted = 0
    n_seen = 0
    n_empty = 0
    t0 = time.time()
    for row in iter_parquet_rows(PARQUET, limit=args.limit):
        n_seen += 1
        chunk_id = row["chunk_id"]
        ids, vals = bm25_sparse_vector(
            row.get("text") or "", df_counter, token_to_id, n_docs, avgdl
        )
        if not ids:
            n_empty += 1
            continue
        point = qm.PointStruct(
            id=stable_uuid(chunk_id),
            vector={"bm25": qm.SparseVector(indices=ids, values=vals)},
        )
        batch_points.append(point)
        if len(batch_points) >= args.batch:
            client.upsert(collection_name=COLLECTION, points=batch_points, wait=False)
            n_upserted += len(batch_points)
            batch_points = []
            if n_upserted % (args.batch * 10) == 0:
                rate = n_upserted / max(time.time() - t0, 0.01)
                print(f"  upserted {n_upserted}/{n_docs} ({rate:.0f} pts/s)")

    if batch_points:
        client.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
        n_upserted += len(batch_points)

    elapsed = time.time() - t0
    print()
    print(f"DONE: scanned {n_seen}, empty {n_empty}, upserted {n_upserted} sparse vectors")
    print(f"      elapsed {elapsed:.1f}s ({n_upserted/max(elapsed,0.01):.0f} pts/s)")

    # Save the token map so the runtime backend can build query-side sparse
    # vectors against the same vocabulary.
    out = Path(__file__).parent.parent / "data" / "bm25_vocab.json"
    import json
    with out.open("w", encoding="utf-8") as f:
        json.dump({
            "n_docs": n_docs,
            "avgdl": avgdl,
            "k1": BM25_K1,
            "b": BM25_B,
            "df": dict(df_counter),
            "token_to_id": token_to_id,
        }, f)
    print(f"Saved vocab: {out} ({out.stat().st_size/1024/1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
