"""
Sync Qdrant collections from local to remote (or vice versa).

Scrolls through all points in the source collection and upserts
them into the destination. Skips points that already exist in the
destination (by count comparison).

Usage:
    # Local -> Remote
    python scripts/sync_qdrant.py --source http://localhost:6334 --dest http://35.188.64.146:6333 --collection dspace_fulltext_nomic

    # Remote -> Local
    python scripts/sync_qdrant.py --source http://35.188.64.146:6333 --dest http://localhost:6334 --collection dspace_fulltext_nomic
"""

import argparse
import sys
import time

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, help="Source Qdrant URL")
    parser.add_argument("--dest", required=True, help="Destination Qdrant URL")
    parser.add_argument("--collection", required=True, help="Collection name")
    parser.add_argument("--batch-size", type=int, default=100)
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    src = QdrantClient(url=args.source, timeout=60)
    dst = QdrantClient(url=args.dest, timeout=60)

    # Check source
    src_info = src.get_collection(args.collection)
    log(f"Source ({args.source}): {src_info.points_count:,} points")

    # Create dest collection if needed
    try:
        dst_info = dst.get_collection(args.collection)
        log(f"Dest ({args.dest}): {dst_info.points_count:,} points")
        if dst_info.points_count >= src_info.points_count:
            log("Destination already has >= source points. Nothing to sync.")
            return 0
    except Exception:
        log(f"Creating collection {args.collection} on destination...")
        # Copy BOTH dense + sparse vector configs. Older versions of this
        # script only copied `vectors` which breaks hybrid collections — the
        # sparse slot must exist on dst before any upsert with a sparse
        # vector lands.
        create_kwargs = {
            "collection_name": args.collection,
            "vectors_config": src_info.config.params.vectors,
        }
        sparse = getattr(src_info.config.params, "sparse_vectors", None) or {}
        if sparse:
            create_kwargs["sparse_vectors_config"] = sparse
            log(f"  src has sparse vectors: {list(sparse.keys())}")
        dst.create_collection(**create_kwargs)
        log("Created.")

    # Scroll and upsert
    total = 0
    offset = None
    t0 = time.time()

    while True:
        results, next_offset = src.scroll(
            collection_name=args.collection,
            limit=args.batch_size,
            offset=offset,
            with_payload=True,
            with_vectors=True,
        )

        if not results:
            break

        points = [
            qm.PointStruct(
                id=p.id,
                vector=p.vector,
                payload=p.payload,
            )
            for p in results
        ]

        dst.upsert(collection_name=args.collection, points=points)
        total += len(points)

        if total % 1000 == 0:
            elapsed = time.time() - t0
            rate = total / max(elapsed, 0.01)
            log(f"  Synced {total:,} points ({rate:.0f}/s)")

        offset = next_offset
        if offset is None:
            break

    elapsed = time.time() - t0
    log(f"\nSync complete: {total:,} points in {elapsed/60:.1f} min")

    # Verify
    dst_info = dst.get_collection(args.collection)
    log(f"Destination now has {dst_info.points_count:,} points")

    return 0


if __name__ == "__main__":
    sys.exit(main())
