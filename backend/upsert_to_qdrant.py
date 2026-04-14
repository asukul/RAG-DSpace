"""
Bulk upsert pre-computed chunk embeddings (Vertex text-embedding-005, 768d)
into the Qdrant 'dspace_chunks' collection on the GCE VM.

Reads:  data/chunk_embeddings.parquet
Writes: dspace_chunks collection on http://35.188.64.146:6333

Idempotent — re-running will overwrite existing points with the same id.
"""

import argparse
import json
import logging
import os
import time
import uuid as _uuid
from pathlib import Path
from typing import Iterable, List

import pyarrow.parquet as pq
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://35.188.64.146:6333")
COLLECTION = os.getenv("QDRANT_COLLECTION", "dspace_chunks")
PARQUET = Path(__file__).parent / "data" / "chunk_embeddings.parquet"
VECTOR_DIM = 768
BATCH_SIZE = 256


def _stable_uuid(chunk_id: str) -> str:
    """
    Qdrant point IDs must be either uint64 or UUID. Hash the chunk_id
    deterministically to a UUIDv5 so re-runs hit the same id.
    """
    return str(_uuid.uuid5(_uuid.NAMESPACE_URL, chunk_id))


def ensure_collection(client: QdrantClient) -> None:
    """Create the collection if missing, with named dense vector + payload indexes."""
    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION in existing:
        info = client.get_collection(COLLECTION)
        logger.info(f"Collection '{COLLECTION}' exists: {info.points_count or 0} points")
        return

    logger.info(f"Creating collection '{COLLECTION}' with dense vector dim={VECTOR_DIM}")
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={
            "dense": qm.VectorParams(
                size=VECTOR_DIM,
                distance=qm.Distance.COSINE,
                on_disk=False,  # 39k vectors fit comfortably in RAM
            ),
        },
        # Sparse vectors for hybrid (BM25) — populated later via partial upsert
        sparse_vectors_config={
            "bm25": qm.SparseVectorParams(
                index=qm.SparseIndexParams(on_disk=False),
            ),
        },
        optimizers_config=qm.OptimizersConfigDiff(default_segment_number=2),
    )

    # Payload indexes for fast filtering on common library facets
    for field, schema in [
        ("uuid", qm.PayloadSchemaType.KEYWORD),
        ("year", qm.PayloadSchemaType.KEYWORD),
        ("type", qm.PayloadSchemaType.KEYWORD),
        ("page", qm.PayloadSchemaType.INTEGER),
    ]:
        client.create_payload_index(
            collection_name=COLLECTION,
            field_name=field,
            field_schema=schema,
        )
    logger.info(f"Collection '{COLLECTION}' created with payload indexes")


def iter_rows(path: Path) -> Iterable[dict]:
    """Stream parquet rows without loading the whole file into RAM."""
    parquet_file = pq.ParquetFile(path)
    for batch in parquet_file.iter_batches(batch_size=BATCH_SIZE):
        for row in batch.to_pylist():
            yield row


def to_point(row: dict) -> qm.PointStruct:
    """Build a Qdrant PointStruct from a parquet row."""
    chunk_id = row["chunk_id"]
    payload = {
        "chunk_id": chunk_id,
        "uuid": row.get("uuid", ""),
        "chunk_idx": int(row.get("chunk_idx", 0) or 0),
        "doc_title": row.get("doc_title", "") or "",
        "authors": row.get("authors", "") or "",
        "year": row.get("year", "") or "",
        "type": row.get("type", "") or "",
        "dspace_url": row.get("dspace_url", "") or "",
        "heading": row.get("heading", "") or "",
        "page": int(row.get("page", 0) or 0),
        "text": row.get("text", "") or "",
    }
    embedding = row["embedding"]
    if hasattr(embedding, "tolist"):
        embedding = embedding.tolist()
    return qm.PointStruct(
        id=_stable_uuid(chunk_id),
        vector={"dense": list(embedding)},
        payload=payload,
    )


def upsert_all(parquet_path: Path) -> dict:
    if not parquet_path.exists():
        raise FileNotFoundError(f"Embeddings parquet not found: {parquet_path}")

    client = QdrantClient(url=QDRANT_URL, timeout=120)
    ensure_collection(client)

    total = 0
    failed = 0
    t0 = time.time()
    batch: List[qm.PointStruct] = []

    for row in iter_rows(parquet_path):
        try:
            batch.append(to_point(row))
        except Exception as e:
            failed += 1
            logger.warning(f"row build failed: {e}")
            continue

        if len(batch) >= BATCH_SIZE:
            try:
                client.upsert(collection_name=COLLECTION, points=batch, wait=False)
                total += len(batch)
                batch = []
                if total % (BATCH_SIZE * 4) == 0:
                    logger.info(f"upserted {total} points ({total/(time.time()-t0):.0f} pts/s)")
            except Exception as e:
                failed += len(batch)
                logger.error(f"upsert batch failed: {e}")
                batch = []

    if batch:
        try:
            client.upsert(collection_name=COLLECTION, points=batch, wait=True)
            total += len(batch)
        except Exception as e:
            failed += len(batch)
            logger.error(f"final upsert failed: {e}")

    elapsed = time.time() - t0
    info = client.get_collection(COLLECTION)
    return {
        "upserted": total,
        "failed": failed,
        "elapsed_s": round(elapsed, 1),
        "rate_per_s": round(total / max(elapsed, 0.01), 1),
        "collection_count": info.points_count,
    }


def smoke_query(query_text: str, top_k: int = 5) -> None:
    """Run a single end-to-end retrieval against the populated collection."""
    from services.embedding_service import embedding_service

    embedding_service.configure()
    if embedding_service.backend != "vertex":
        logger.warning(f"smoke query: backend={embedding_service.backend}, expected vertex")

    qv = embedding_service._embed_one(query_text, task_type="RETRIEVAL_QUERY")
    if not qv:
        logger.error("smoke query: failed to embed query")
        return

    client = QdrantClient(url=QDRANT_URL, timeout=120)
    results = client.query_points(
        collection_name=COLLECTION,
        query=qv,
        using="dense",
        limit=top_k,
        with_payload=True,
    )
    print(f"\nSmoke query: {query_text!r}")
    for hit in results.points:
        p = hit.payload or {}
        title = (p.get("doc_title") or "")[:60]
        heading = (p.get("heading") or "")[:40]
        text = (p.get("text") or "")[:80]
        print(f"  {hit.score:.3f}  {title}  | {heading}  p.{p.get('page')}  {text!r}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-only", action="store_true", help="skip upsert, run a smoke query")
    parser.add_argument("--query", default="machine learning healthcare")
    args = parser.parse_args()

    if not args.smoke_only:
        result = upsert_all(PARQUET)
        print(json.dumps(result, indent=2))

    smoke_query(args.query)
