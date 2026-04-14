"""
Stage 1: Download PDFs from ISU DSpace to local disk.

For each item with has_bitstream=1 in dspace_index.db:
  1. Call DSpace API to discover the ORIGINAL bundle's bitstream URL
  2. Download the PDF to local disk organized by collection
  3. Track progress in a state file for resume support

Storage: backend/data/pdfs/{collection_slug}/{uuid}.pdf
State:   backend/data/pdfs/download_state.json

Usage:
    python scripts/download_pdfs.py                  # full download
    python scripts/download_pdfs.py --limit 100      # test with 100 items
    python scripts/download_pdfs.py --workers 3      # parallel downloads
    python scripts/download_pdfs.py --collection "Theses and Dissertations"
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import requests

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
PDF_DIR = BACKEND / "data" / "pdfs"
STATE_FILE = PDF_DIR / "download_state.json"

DSPACE_API = "https://dr.lib.iastate.edu/server/api"
SLEEP_BETWEEN = 0.2  # 200ms politeness per request
REQUEST_TIMEOUT = 120  # 2 min timeout for large PDFs
MAX_RETRIES = 3
BACKOFF_BASE = 2.0

HEADERS = {
    "User-Agent": "ISU-Research-RAG/1.0 (PDF pipeline, contact: adisak@iastate.edu)",
    "Accept": "application/json",
}

# Thread-safe state management
state_lock = Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().strip()).strip("-")


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"downloaded": {}, "errors": {}, "started_at": now_iso(), "stats": {}}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except PermissionError:
        STATE_FILE.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def discover_bitstream_url(item_uuid: str, session: requests.Session) -> tuple[str | None, int]:
    """Discover the ORIGINAL bundle PDF URL for an item. Returns (url, size_bytes)."""
    url = f"{DSPACE_API}/core/items/{item_uuid}?embed=bundles/bitstreams"

    for attempt in range(MAX_RETRIES):
        try:
            resp = session.get(url, headers=HEADERS, timeout=30)
            if resp.status_code == 404:
                return None, 0
            resp.raise_for_status()
            data = resp.json()

            # Navigate: _embedded.bundles -> find ORIGINAL -> _embedded.bitstreams -> find PDF
            bundles = data.get("_embedded", {}).get("bundles", [])
            if isinstance(bundles, dict):
                bundles = bundles.get("_embedded", {}).get("bundles", [])

            for bundle in bundles:
                if not isinstance(bundle, dict):
                    continue
                if bundle.get("name") != "ORIGINAL":
                    continue

                bitstreams = bundle.get("_embedded", {}).get("bitstreams", [])
                if isinstance(bitstreams, dict):
                    bitstreams = bitstreams.get("_embedded", {}).get("bitstreams", [])

                # Prefer .pdf, fall back to first bitstream
                pdf_bit = None
                first_bit = None
                for bit in bitstreams:
                    if not isinstance(bit, dict):
                        continue
                    if first_bit is None:
                        first_bit = bit
                    name = (bit.get("name") or "").lower()
                    if name.endswith(".pdf"):
                        pdf_bit = bit
                        break

                chosen = pdf_bit or first_bit
                if chosen:
                    dl_url = chosen.get("_links", {}).get("content", {}).get("href", "")
                    size = chosen.get("sizeBytes", 0)
                    return dl_url, size

            return None, 0

        except requests.exceptions.RequestException as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_BASE ** attempt)
            else:
                raise

    return None, 0


def download_pdf(item_uuid: str, collection_slug: str, session: requests.Session) -> dict:
    """Download a single PDF. Returns status dict."""
    out_dir = PDF_DIR / collection_slug
    out_path = out_dir / f"{item_uuid}.pdf"

    # Skip if already downloaded
    if out_path.exists() and out_path.stat().st_size > 0:
        return {"uuid": item_uuid, "status": "exists", "size": out_path.stat().st_size}

    try:
        # Discover bitstream URL
        dl_url, expected_size = discover_bitstream_url(item_uuid, session)
        if not dl_url:
            return {"uuid": item_uuid, "status": "no_bitstream", "size": 0}

        # Download
        time.sleep(SLEEP_BETWEEN)
        out_dir.mkdir(parents=True, exist_ok=True)

        for attempt in range(MAX_RETRIES):
            try:
                resp = session.get(
                    dl_url,
                    headers={"User-Agent": HEADERS["User-Agent"]},
                    timeout=REQUEST_TIMEOUT,
                    stream=True,
                )
                resp.raise_for_status()

                # Stream to disk
                tmp_path = out_path.with_suffix(".tmp")
                total = 0
                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=65536):
                        f.write(chunk)
                        total += len(chunk)

                # Rename
                tmp_path.replace(out_path)
                return {"uuid": item_uuid, "status": "ok", "size": total}

            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(BACKOFF_BASE ** attempt)
                else:
                    return {"uuid": item_uuid, "status": "error", "error": str(e), "size": 0}

    except Exception as e:
        return {"uuid": item_uuid, "status": "error", "error": str(e), "size": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download PDFs from ISU DSpace")
    parser.add_argument("--limit", type=int, default=0, help="Max items to download (0=all)")
    parser.add_argument("--workers", type=int, default=2, help="Parallel download workers")
    parser.add_argument("--collection", default=None, help="Only download from this collection")
    parser.add_argument("--sleep", type=float, default=0.2, help="Seconds between requests")
    args = parser.parse_args()

    global SLEEP_BETWEEN
    SLEEP_BETWEEN = args.sleep

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    PDF_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()

    # Get items to download
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    query = """
        SELECT uuid, collection_name, title, type FROM items
        WHERE has_bitstream = 1
    """
    params = []
    if args.collection:
        query += " AND collection_name = ?"
        params.append(args.collection)
    query += " ORDER BY collection_name, uuid"
    if args.limit:
        query += f" LIMIT {args.limit}"

    items = conn.execute(query, params).fetchall()
    conn.close()

    # Filter out already downloaded
    already = set(state.get("downloaded", {}).keys())
    to_download = [(r["uuid"], slugify(r["collection_name"]), r["title"], r["type"])
                   for r in items if r["uuid"] not in already]

    log("=" * 60)
    log("ISU DSpace PDF Downloader")
    log(f"  Total items with bitstream: {len(items):,}")
    log(f"  Already downloaded:         {len(already):,}")
    log(f"  To download:                {len(to_download):,}")
    log(f"  Workers:                    {args.workers}")
    log(f"  Sleep between requests:     {SLEEP_BETWEEN}s")
    log(f"  Output directory:           {PDF_DIR}")
    log("=" * 60)

    if not to_download:
        log("Nothing to download!")
        return 0

    # Download with thread pool
    session = requests.Session()
    t0 = time.time()
    completed = 0
    total_bytes = 0
    errors = 0

    def do_download(item):
        uuid, coll_slug, title, item_type = item
        return download_pdf(uuid, coll_slug, session)

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(do_download, item): item for item in to_download}

        for future in as_completed(futures):
            result = future.result()
            uuid = result["uuid"]
            status = result["status"]

            if status == "ok":
                with state_lock:
                    state["downloaded"][uuid] = {
                        "size": result["size"],
                        "time": now_iso(),
                    }
                total_bytes += result["size"]
                completed += 1
            elif status == "exists":
                completed += 1
                total_bytes += result["size"]
            elif status == "error":
                with state_lock:
                    state["errors"][uuid] = result.get("error", "unknown")
                errors += 1
            # no_bitstream — skip silently

            total_done = completed + errors
            if total_done % 50 == 0 or total_done == len(to_download):
                elapsed = time.time() - t0
                rate = completed / max(elapsed, 0.01)
                gb = total_bytes / 1024 / 1024 / 1024
                eta_min = (len(to_download) - total_done) / max(rate, 0.01) / 60
                log(f"  [{total_done:,}/{len(to_download):,}] "
                    f"ok={completed:,} err={errors:,} "
                    f"{gb:.1f} GB | {rate:.1f}/s | ETA {eta_min:.0f}m")

                # Save state periodically
                with state_lock:
                    state["stats"] = {
                        "completed": completed,
                        "errors": errors,
                        "total_bytes": total_bytes,
                        "elapsed_seconds": int(elapsed),
                        "last_updated": now_iso(),
                    }
                    save_state(state)

    # Final save
    elapsed = time.time() - t0
    state["stats"] = {
        "completed": completed,
        "errors": errors,
        "total_bytes": total_bytes,
        "elapsed_seconds": int(elapsed),
        "finished_at": now_iso(),
    }
    save_state(state)

    log("")
    log("=" * 60)
    log(f"Download complete")
    log(f"  Downloaded:    {completed:,} PDFs")
    log(f"  Errors:        {errors:,}")
    log(f"  Total size:    {total_bytes/1024/1024/1024:.1f} GB")
    log(f"  Duration:      {elapsed/3600:.1f} hours")
    log(f"  Rate:          {completed/max(elapsed,0.01):.1f} PDFs/s")
    log(f"  State file:    {STATE_FILE}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
