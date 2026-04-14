"""
Copy all points from dspace_fulltext_nomic → dspace_fulltext_nomic_full
via Qdrant scroll + upsert REST API.

Used to preserve the 65% research baseline while letting a second copy
grow to 100% as Nomic finishes the remaining PDFs.

Run:
    python backend/scripts/copy_nomic_collection.py
"""
import json
import sys
import time

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

QDRANT = "http://localhost:6334"
SOURCE = "dspace_fulltext_nomic"
TARGET = "dspace_fulltext_nomic_full"
BATCH = 500


def get_count(name: str) -> int:
    r = requests.post(
        f"{QDRANT}/collections/{name}/points/count",
        json={"exact": True},
        timeout=60,
    )
    return r.json()["result"]["count"]


def main() -> None:
    src_before = get_count(SOURCE)
    tgt_before = get_count(TARGET)
    print(f"source {SOURCE}: {src_before:,} points")
    print(f"target {TARGET}: {tgt_before:,} points")
    if tgt_before >= src_before:
        print("target already has >= source points — nothing to do")
        return

    print(f"Copying {src_before:,} points in batches of {BATCH}")
    t0 = time.time()
    offset = None
    copied = 0
    batch_num = 0

    while True:
        body = {"limit": BATCH, "with_vector": True, "with_payload": True}
        if offset is not None:
            body["offset"] = offset

        r = requests.post(
            f"{QDRANT}/collections/{SOURCE}/points/scroll",
            json=body,
            timeout=60,
        )
        r.raise_for_status()
        result = r.json()["result"]
        points = result["points"]
        if not points:
            break

        upsert_points = [
            {"id": p["id"], "vector": p["vector"], "payload": p.get("payload", {})}
            for p in points
        ]
        ur = requests.put(
            f"{QDRANT}/collections/{TARGET}/points?wait=true",
            json={"points": upsert_points},
            timeout=120,
        )
        ur.raise_for_status()

        copied += len(upsert_points)
        batch_num += 1
        offset = result.get("next_page_offset")

        if batch_num % 10 == 0 or offset is None:
            elapsed = time.time() - t0
            rate = copied / max(elapsed, 0.01)
            eta = (src_before - copied) / max(rate, 1) if rate > 0 else -1
            print(
                f"  batch {batch_num}: {copied:,}/{src_before:,} "
                f"({100*copied/src_before:.1f}%) rate={rate:.0f}/s eta={eta/60:.1f}min",
                flush=True,
            )

        if offset is None:
            break

    final = get_count(TARGET)
    elapsed = time.time() - t0
    print(f"\nDone in {elapsed/60:.1f} min")
    print(f"source {SOURCE}: {get_count(SOURCE):,} points")
    print(f"target {TARGET}: {final:,} points")
    if final >= src_before:
        print(f"OK  copied {copied:,} points (target has all source data)")
    else:
        print(f"WARNING  target has {final:,} but source has {src_before:,} — short by {src_before-final:,}")


if __name__ == "__main__":
    main()
