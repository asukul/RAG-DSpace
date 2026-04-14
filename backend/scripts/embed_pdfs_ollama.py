"""
Embed full-text PDF chunks using Ollama embedding models locally.

Pipeline:
  1. Scan downloaded PDFs in backend/data/pdfs/
  2. Extract text via pdfminer
  3. Chunk (500 tokens, 100 overlap)
  4. Embed via Ollama API
  5. Upsert to Qdrant collection

Resumable: tracks progress in a state file per model.

Usage:
    python scripts/embed_pdfs_ollama.py --model nomic-embed-text --collection dspace_fulltext_nomic
    python scripts/embed_pdfs_ollama.py --model bge-m3 --collection dspace_fulltext_bge
    python scripts/embed_pdfs_ollama.py --resume  # continue from where it left off
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any

import requests
from pdfminer.high_level import extract_text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
STATE_DIR = BACKEND / "data" / "embed_state"

OLLAMA_URL = "http://localhost:11434"
QDRANT_URL = os.environ.get("QDRANT_URL", "http://35.188.64.146:6333")

# Model configs
MODEL_CONFIGS = {
    "nomic-embed-text": {"dims": 768, "collection_suffix": "nomic"},
    "mxbai-embed-large": {"dims": 1024, "collection_suffix": "mxbai"},
    "snowflake-arctic-embed2": {"dims": 1024, "collection_suffix": "arctic2"},
    "bge-m3": {"dims": 1024, "collection_suffix": "bge_m3"},
    "qwen3-embedding:0.6b": {"dims": 1024, "collection_suffix": "qwen3_06b"},
    "qwen3-embedding:4b": {"dims": 2560, "collection_suffix": "qwen3_4b"},
    "qwen3-embedding:8b": {"dims": 4096, "collection_suffix": "qwen3_8b"},
}


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_pdf_text(pdf_path: str, max_pages: int = 30) -> str:
    import concurrent.futures
    try:
        # Skip files > 50MB (likely scanned image PDFs)
        if os.path.getsize(pdf_path) > 50 * 1024 * 1024:
            return ""

        # Run extraction with 30-second timeout
        def _extract():
            return extract_text(pdf_path, maxpages=max_pages)

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_extract)
            text = future.result(timeout=30)

        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < 50:
            return ""
        return text
    except (concurrent.futures.TimeoutError, Exception):
        return ""


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text] if len(words) > 30 else []
    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if len(chunk.split()) > 30:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def ollama_embed(model: str, texts: list[str]) -> list[list[float]]:
    # Truncate individual texts to ~8000 chars to avoid 400 errors
    safe_texts = [t[:8000] for t in texts]
    for attempt in range(3):
        try:
            resp = requests.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": model, "input": safe_texts},
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json().get("embeddings", [])
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 400 and len(safe_texts) > 1:
                # Try smaller batch
                mid = len(safe_texts) // 2
                left = ollama_embed(model, safe_texts[:mid])
                right = ollama_embed(model, safe_texts[mid:])
                return left + right
            if attempt < 2:
                time.sleep(1)
            else:
                raise


def load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"processed_uuids": [], "total_chunks": 0, "total_points": 0, "errors": 0}


def save_state(state: dict, state_file: Path) -> None:
    tmp = state_file.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(state_file)
    except PermissionError:
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="nomic-embed-text",
                        help="Ollama model name")
    parser.add_argument("--collection", default=None,
                        help="Qdrant collection name (auto-generated if not set)")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Embedding batch size")
    parser.add_argument("--chunk-size", type=int, default=500)
    parser.add_argument("--overlap", type=int, default=100)
    parser.add_argument("--limit", type=int, default=0,
                        help="Max PDFs to process (0=all)")
    parser.add_argument("--workers", type=int, default=4,
                        help="Parallel PDF processing workers")
    parser.add_argument("--qdrant-url", default=None,
                        help="Qdrant URL (default: env QDRANT_URL or remote)")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    model = args.model
    config = MODEL_CONFIGS.get(model, {"dims": 768, "collection_suffix": "custom"})
    dims = config["dims"]
    collection = args.collection or f"dspace_fulltext_{config['collection_suffix']}"

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state_file = STATE_DIR / f"embed_state_{config['collection_suffix']}.json"
    state = load_state(state_file)
    processed_set = set(state["processed_uuids"])

    log("=" * 60)
    log(f"PDF Full-Text Embedding Pipeline")
    log(f"  Model:       {model} ({dims}d)")
    log(f"  Collection:  {collection}")
    log(f"  Qdrant:      {QDRANT_URL}")
    log(f"  Chunk size:  {args.chunk_size} words, {args.overlap} overlap")
    log(f"  Batch size:  {args.batch_size}")
    log(f"  Already done: {len(processed_set):,} PDFs")
    log("=" * 60)

    # Collect PDF files
    pdf_files = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                uid = f.replace(".pdf", "")
                if uid not in processed_set:
                    pdf_files.append((uid, os.path.join(dirpath, f)))

    if args.limit:
        pdf_files = pdf_files[:args.limit]

    log(f"  PDFs to process: {len(pdf_files):,}")

    if not pdf_files:
        log("Nothing to process!")
        return 0

    # Warm up Ollama
    log("  Warming up model...")
    try:
        ollama_embed(model, ["warmup"])
    except Exception as e:
        log(f"  ERROR: Cannot connect to Ollama: {e}")
        return 1

    # Connect to Qdrant
    qdrant_url = args.qdrant_url or QDRANT_URL
    log(f"  Connecting to Qdrant at {qdrant_url}...")
    qclient = QdrantClient(url=qdrant_url, timeout=60)

    # Create or verify collection
    try:
        info = qclient.get_collection(collection)
        log(f"  Collection exists: {info.points_count} points")
    except Exception:
        log(f"  Creating collection {collection} ({dims}d)...")
        qclient.create_collection(
            collection_name=collection,
            vectors_config=qm.VectorParams(
                size=dims,
                distance=qm.Distance.COSINE,
            ),
        )
        log(f"  Collection created")

    # Load item metadata for payload
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # Parallel pipeline using threads. GIL limits CPU parallelism but
    # pdfminer releases GIL during I/O, so threads still help.
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0 = time.time()
    total_chunks = state["total_chunks"]
    total_points = state["total_points"]
    errors = state["errors"]
    pdfs_done = 0

    # Phase A: Extract text from PDFs using multiple processes (CPU-bound)
    # Phase B: Embed extracted text via Ollama (GPU-bound)
    # Run extraction in large batches, then embed each batch.

    num_workers = args.workers
    log(f"  Starting {num_workers} parallel thread workers...")

    def process_one_pdf(uid_path):
        uid, pdf_path = uid_path
        text = extract_pdf_text(pdf_path)
        if not text or len(text) < 100:
            return {"uid": uid, "status": "empty", "chunks": 0, "points": 0}

        meta_conn = sqlite3.connect(INDEX_DB)
        meta_conn.row_factory = sqlite3.Row
        row = meta_conn.execute(
            "SELECT title, year, type, department, collection_name, authors_json FROM items WHERE uuid = ?",
            (uid,),
        ).fetchone()
        meta = {}
        if row:
            meta = {
                "uuid": uid, "title": row["title"] or "", "year": row["year"] or "",
                "type": row["type"] or "", "department": row["department"] or "",
                "collection": row["collection_name"] or "",
            }
            try: meta["authors"] = json.loads(row["authors_json"] or "[]")[:5]
            except: meta["authors"] = []
        meta_conn.close()

        chunks = chunk_text(text, args.chunk_size, args.overlap)
        if not chunks:
            return {"uid": uid, "status": "no_chunks", "chunks": 0, "points": 0}

        all_points = []
        for cb_start in range(0, len(chunks), args.batch_size):
            batch = chunks[cb_start:cb_start + args.batch_size]
            try:
                embeddings = ollama_embed(model, batch)
                for i, emb in enumerate(embeddings):
                    if len(emb) > dims: emb = emb[:dims]
                    all_points.append(qm.PointStruct(
                        id=str(uuid_mod.uuid4()), vector=emb,
                        payload={**meta, "chunk_idx": cb_start + i,
                                 "chunk_total": len(chunks),
                                 "heading": f"Chunk {cb_start+i+1}/{len(chunks)}",
                                 "text_preview": batch[i][:200]},
                    ))
            except Exception as e:
                return {"uid": uid, "status": "error", "error": str(e),
                        "chunks": len(chunks), "points": len(all_points)}

        if all_points:
            try:
                for i in range(0, len(all_points), 100):
                    qclient.upsert(collection_name=collection, points=all_points[i:i+100])
            except Exception as e:
                return {"uid": uid, "status": "qdrant_error", "chunks": len(chunks), "points": 0}

        return {"uid": uid, "status": "ok", "chunks": len(chunks), "points": len(all_points)}

    from threading import Lock
    state_lock = Lock()

    with ThreadPoolExecutor(max_workers=num_workers) as pool:
        futures = {pool.submit(process_one_pdf, item): item for item in pdf_files}
        for future in as_completed(futures, timeout=None):
            result = future.result()
            with state_lock:
                processed_set.add(result["uid"])
                total_chunks += result.get("chunks", 0)
                total_points += result.get("points", 0)
                if result["status"] not in ("ok", "no_chunks", "empty"):
                    errors += 1
                pdfs_done += 1

                if pdfs_done % 100 == 0 or pdfs_done == len(pdf_files):
                    elapsed = time.time() - t0
                    rate = pdfs_done / max(elapsed, 0.01)
                    remaining = len(pdf_files) - pdfs_done
                    eta_h = remaining / max(rate, 0.01) / 3600
                    log(f"  [{pdfs_done:,}/{len(pdf_files):,}] "
                        f"chunks={total_chunks:,} points={total_points:,} "
                        f"err={errors} | {rate:.1f} PDF/s | ETA {eta_h:.1f}h")
                    state["processed_uuids"] = list(processed_set)
                    state["total_chunks"] = total_chunks
                    state["total_points"] = total_points
                    state["errors"] = errors
                    state["elapsed_seconds"] = int(elapsed)
                    state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                    save_state(state, state_file)

    conn.close()

    # Final state save
    elapsed = time.time() - t0
    state["processed_uuids"] = list(processed_set)
    state["total_chunks"] = total_chunks
    state["total_points"] = total_points
    state["errors"] = errors
    state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["elapsed_seconds"] = int(elapsed)
    save_state(state, state_file)

    log("")
    log("=" * 60)
    log(f"Embedding complete")
    log(f"  PDFs processed:  {pdfs_done:,}")
    log(f"  Total chunks:    {total_chunks:,}")
    log(f"  Qdrant points:   {total_points:,}")
    log(f"  Errors:          {errors}")
    log(f"  Duration:        {elapsed/3600:.1f} hours")
    log(f"  Rate:            {pdfs_done/max(elapsed,0.01):.1f} PDFs/s")
    log(f"  Collection:      {collection}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
