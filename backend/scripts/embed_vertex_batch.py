"""
Embed full-text PDF chunks using Vertex AI text-embedding-005.

Pipeline:
  1. Scan downloaded PDFs in backend/data/pdfs/
  2. Extract text via pdfminer (30s timeout, skip >50MB)
  3. Chunk (500 words, 100 overlap)
  4. Save chunks to vertex_chunks.jsonl (reproducibility)
  5. Embed via google-genai SDK (Vertex AI text-embedding-005, 768d)
  6. Upsert to local Qdrant collection dspace_fulltext_vertex

Resumable: tracks progress in embed_state_vertex.json.

Usage:
    python scripts/embed_vertex_batch.py --limit 100   # test run
    python scripts/embed_vertex_batch.py                # full run
    python scripts/embed_vertex_batch.py --resume       # continue
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import sqlite3
import sys
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any

from pdfminer.high_level import extract_text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
STATE_DIR = BACKEND / "data" / "embed_state"
CHUNKS_DIR = BACKEND / "data" / "dspace"

QDRANT_URL = "http://localhost:6334"
COLLECTION = "dspace_fulltext_vertex"
DIMS = 768
VERTEX_BATCH_MAX = 250  # Vertex AI max texts per embed call
VERTEX_PROJECT = "rag-dspace"
VERTEX_LOCATION = "us-central1"
VERTEX_MODEL = "text-embedding-005"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# PDF extraction (CPU-bound, parallelized with threads)
# ---------------------------------------------------------------------------

def extract_pdf_text(pdf_path: str, max_pages: int = 30) -> str:
    """Extract text from a PDF with 30-second timeout. Skip >50MB files."""
    try:
        if os.path.getsize(pdf_path) > 50 * 1024 * 1024:
            return ""

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
    """Split text into word-level chunks with overlap."""
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


# ---------------------------------------------------------------------------
# Vertex AI embedding with rate-limit handling
# ---------------------------------------------------------------------------

def create_vertex_client():
    """Create google-genai client for Vertex AI."""
    from google import genai
    return genai.Client(vertexai=True, project=VERTEX_PROJECT, location=VERTEX_LOCATION)


def vertex_embed_batch(client, texts: list[str], max_retries: int = 6) -> list[list[float]]:
    """
    Embed a batch of texts (max 250) via Vertex AI text-embedding-005.
    Handles 429 rate limits with exponential backoff.
    Handles token-limit errors by splitting into smaller batches.
    """
    from google.genai import types as gen_types

    # Truncate each text to ~3000 chars (~750 tokens) to stay well within
    # the 20000-token-per-request limit even at batch size 250
    safe_texts = [t[:3000] for t in texts]

    backoff = 2.0
    for attempt in range(max_retries):
        try:
            result = client.models.embed_content(
                model=VERTEX_MODEL,
                contents=safe_texts,
                config=gen_types.EmbedContentConfig(
                    task_type="RETRIEVAL_DOCUMENT",
                    output_dimensionality=DIMS,
                ),
            )
            return [list(e.values) for e in result.embeddings]
        except Exception as e:
            err_str = str(e)
            # Rate limit (429) or quota exceeded
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str or "quota" in err_str.lower():
                wait = backoff * (2 ** attempt)
                log(f"    Rate limited (attempt {attempt+1}/{max_retries}), "
                    f"waiting {wait:.0f}s...")
                time.sleep(wait)
                continue
            # Token limit exceeded or batch too large -- split in half
            if ("token" in err_str.lower() or "20000" in err_str
                    or "INVALID_ARGUMENT" in err_str) and len(safe_texts) > 1:
                mid = len(safe_texts) // 2
                left = vertex_embed_batch(client, safe_texts[:mid], max_retries)
                right = vertex_embed_batch(client, safe_texts[mid:], max_retries)
                return left + right
            if attempt < max_retries - 1:
                time.sleep(backoff)
                continue
            raise

    return []


# ---------------------------------------------------------------------------
# State management (resumable)
# ---------------------------------------------------------------------------

def load_state(state_file: Path) -> dict:
    if state_file.exists():
        try:
            return json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "processed_uuids": [],
        "total_chunks": 0,
        "total_points": 0,
        "errors": 0,
        "error_uuids": [],
    }


def save_state(state: dict, state_file: Path) -> None:
    tmp = state_file.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(state_file)
    except PermissionError:
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Embed PDF chunks via Vertex AI")
    parser.add_argument("--limit", type=int, default=0,
                        help="Max PDFs to process (0=all)")
    parser.add_argument("--chunk-size", type=int, default=500,
                        help="Chunk size in words")
    parser.add_argument("--overlap", type=int, default=100,
                        help="Chunk overlap in words")
    parser.add_argument("--extract-workers", type=int, default=32,
                        help="Thread workers for PDF extraction")
    parser.add_argument("--embed-workers", type=int, default=4,
                        help="Parallel Vertex API workers")
    parser.add_argument("--qdrant-url", default=QDRANT_URL)
    parser.add_argument("--resume", action="store_true",
                        help="Resume from state file")
    parser.add_argument("--extract-only", action="store_true",
                        help="Only extract and chunk, skip embedding")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)

    state_file = STATE_DIR / "embed_state_vertex.json"
    state = load_state(state_file)
    processed_set = set(state["processed_uuids"])

    chunks_jsonl = CHUNKS_DIR / "vertex_chunks.jsonl"

    log("=" * 60)
    log("Vertex AI PDF Full-Text Embedding Pipeline")
    log(f"  Model:            {VERTEX_MODEL} ({DIMS}d)")
    log(f"  Collection:       {COLLECTION}")
    log(f"  Qdrant:           {args.qdrant_url}")
    log(f"  Chunk size:       {args.chunk_size} words, {args.overlap} overlap")
    log(f"  Extract workers:  {args.extract_workers}")
    log(f"  Embed workers:    {args.embed_workers}")
    log(f"  Already done:     {len(processed_set):,} PDFs")
    log("=" * 60)

    # ---- Collect PDF files ----
    pdf_files: list[tuple[str, str]] = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                uid = f.replace(".pdf", "")
                if uid not in processed_set:
                    pdf_files.append((uid, os.path.join(dirpath, f)))

    if args.limit:
        pdf_files = pdf_files[: args.limit]

    log(f"  PDFs to process:  {len(pdf_files):,}")
    if not pdf_files:
        log("Nothing to process!")
        return 0

    # ---- Load metadata from SQLite ----
    log("  Loading metadata from dspace_index.db...")
    meta_conn = sqlite3.connect(str(INDEX_DB))
    meta_conn.row_factory = sqlite3.Row
    meta_cache: dict[str, dict] = {}
    for row in meta_conn.execute(
        "SELECT uuid, title, year, type, department, collection_name, authors_json "
        "FROM items"
    ):
        uid = row["uuid"]
        authors = []
        try:
            authors = json.loads(row["authors_json"] or "[]")[:5]
        except Exception:
            pass
        meta_cache[uid] = {
            "uuid": uid,
            "title": row["title"] or "",
            "year": row["year"] or "",
            "type": row["type"] or "",
            "department": row["department"] or "",
            "collection": row["collection_name"] or "",
            "authors": authors,
        }
    meta_conn.close()
    log(f"  Metadata loaded: {len(meta_cache):,} items")

    # ---- Phase 1: Extract text from PDFs (32 thread workers) ----
    log("")
    log("Phase 1: Extracting text from PDFs...")
    t0 = time.time()

    extracted: list[tuple[str, str, str]] = []  # (uid, pdf_path, text)
    extract_errors = 0
    done_count = 0

    def _do_extract(uid_path):
        uid, pdf_path = uid_path
        text = extract_pdf_text(pdf_path)
        return uid, pdf_path, text

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.extract_workers) as pool:
        futures = {pool.submit(_do_extract, item): item for item in pdf_files}
        for future in concurrent.futures.as_completed(futures):
            try:
                uid, pdf_path, text = future.result()
                if text and len(text) >= 100:
                    extracted.append((uid, pdf_path, text))
                else:
                    # Mark as processed even if empty (don't retry)
                    processed_set.add(uid)
                done_count += 1
            except Exception:
                extract_errors += 1
                done_count += 1

            if done_count % 500 == 0:
                elapsed = time.time() - t0
                rate = done_count / max(elapsed, 0.01)
                log(f"  Extracted {done_count:,}/{len(pdf_files):,} "
                    f"({len(extracted):,} with text) | {rate:.1f} PDF/s")

    extract_time = time.time() - t0
    log(f"  Extraction done: {len(extracted):,} PDFs with text, "
        f"{extract_errors} errors, {extract_time:.1f}s")

    # ---- Phase 2: Chunk text and save to JSONL ----
    log("")
    log("Phase 2: Chunking text...")

    all_chunks: list[dict] = []  # {uid, chunk_idx, chunk_total, text, meta}
    for uid, pdf_path, text in extracted:
        chunks = chunk_text(text, args.chunk_size, args.overlap)
        if not chunks:
            processed_set.add(uid)
            continue
        meta = meta_cache.get(uid, {
            "uuid": uid, "title": "", "year": "", "type": "",
            "department": "", "collection": "", "authors": [],
        })
        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "uuid": uid,
                "chunk_idx": i,
                "chunk_total": len(chunks),
                "text": chunk,
                "title": meta.get("title", ""),
                "year": meta.get("year", ""),
                "type": meta.get("type", ""),
                "department": meta.get("department", ""),
                "collection": meta.get("collection", ""),
                "authors": meta.get("authors", []),
            })

    log(f"  Total chunks: {len(all_chunks):,} from {len(extracted):,} PDFs")

    # Save chunks to JSONL for reproducibility
    log(f"  Saving chunks to {chunks_jsonl}...")
    # Append mode so we don't lose previous chunks on resume
    mode = "a" if args.resume and chunks_jsonl.exists() else "w"
    with open(chunks_jsonl, mode, encoding="utf-8") as fout:
        for c in all_chunks:
            fout.write(json.dumps(c, ensure_ascii=False) + "\n")
    log(f"  Saved {len(all_chunks):,} chunk records")

    if args.extract_only:
        log("  --extract-only: skipping embedding phase")
        # Save state for empties
        state["processed_uuids"] = list(processed_set)
        save_state(state, state_file)
        return 0

    # ---- Phase 3: Embed via Vertex AI and upsert to Qdrant ----
    log("")
    log("Phase 3: Embedding via Vertex AI and upserting to Qdrant...")

    # Create Vertex AI client
    log("  Initializing Vertex AI client...")
    client = create_vertex_client()

    # Test connection
    log("  Testing embedding API...")
    try:
        test_result = vertex_embed_batch(client, ["connectivity test"])
        assert len(test_result) == 1 and len(test_result[0]) == DIMS
        log(f"  API OK, got {DIMS}d vector")
    except Exception as e:
        log(f"  ERROR: Vertex AI connection failed: {e}")
        return 1

    # Connect to Qdrant
    log(f"  Connecting to Qdrant at {args.qdrant_url}...")
    qclient = QdrantClient(url=args.qdrant_url, timeout=60)

    try:
        info = qclient.get_collection(COLLECTION)
        log(f"  Collection exists: {info.points_count:,} points")
    except Exception:
        log(f"  Creating collection {COLLECTION} ({DIMS}d)...")
        qclient.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(
                size=DIMS,
                distance=qm.Distance.COSINE,
            ),
        )
        log("  Collection created")

    # Group chunks by UUID so we can track per-PDF completion
    from collections import defaultdict
    uid_chunks: dict[str, list[dict]] = defaultdict(list)
    for c in all_chunks:
        uid_chunks[c["uuid"]].append(c)

    total_chunks = state["total_chunks"]
    total_points = state["total_points"]
    errors = state["errors"]
    error_uuids = list(state.get("error_uuids", []))
    pdfs_embedded = 0
    t_embed = time.time()

    # Process each PDF's chunks: embed in batches of 250, then upsert
    uid_list = list(uid_chunks.keys())
    log(f"  Embedding {len(uid_list):,} PDFs ({len(all_chunks):,} chunks)...")

    # We use parallel workers for Vertex API calls but serialize per-PDF
    # to keep things manageable. With 4 workers, we process 4 PDFs at a time.

    def embed_one_pdf(uid: str) -> dict:
        """Embed all chunks for one PDF and upsert to Qdrant."""
        chunks_for_uid = uid_chunks[uid]
        all_points = []
        chunk_count = len(chunks_for_uid)

        # Embed in batches of VERTEX_BATCH_MAX
        for batch_start in range(0, chunk_count, VERTEX_BATCH_MAX):
            batch = chunks_for_uid[batch_start: batch_start + VERTEX_BATCH_MAX]
            texts = [c["text"] for c in batch]

            try:
                embeddings = vertex_embed_batch(client, texts)
            except Exception as e:
                return {
                    "uid": uid, "status": "embed_error",
                    "error": str(e)[:200],
                    "chunks": chunk_count, "points": len(all_points),
                }

            for i, emb in enumerate(embeddings):
                c = batch[i]
                point_id = str(uuid_mod.uuid4())
                all_points.append(qm.PointStruct(
                    id=point_id,
                    vector=emb,
                    payload={
                        "uuid": c["uuid"],
                        "title": c["title"],
                        "year": c["year"],
                        "type": c["type"],
                        "department": c["department"],
                        "collection": c["collection"],
                        "authors": c["authors"],
                        "chunk_idx": c["chunk_idx"],
                        "chunk_total": c["chunk_total"],
                        "text_preview": c["text"][:300],
                    },
                ))

        # Upsert to Qdrant in batches of 100
        if all_points:
            try:
                for i in range(0, len(all_points), 100):
                    qclient.upsert(
                        collection_name=COLLECTION,
                        points=all_points[i: i + 100],
                    )
            except Exception as e:
                return {
                    "uid": uid, "status": "qdrant_error",
                    "error": str(e)[:200],
                    "chunks": chunk_count, "points": 0,
                }

        return {
            "uid": uid, "status": "ok",
            "chunks": chunk_count, "points": len(all_points),
        }

    # Use thread pool with embed_workers for parallelism
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.embed_workers) as pool:
        futures = {pool.submit(embed_one_pdf, uid): uid for uid in uid_list}

        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            uid = result["uid"]
            processed_set.add(uid)
            total_chunks += result.get("chunks", 0)
            total_points += result.get("points", 0)

            if result["status"] != "ok":
                errors += 1
                error_uuids.append(uid)
                if errors <= 10:
                    log(f"    ERROR [{uid}]: {result.get('error', result['status'])}")

            pdfs_embedded += 1

            # Progress report every 500 PDFs
            if pdfs_embedded % 500 == 0 or pdfs_embedded == len(uid_list):
                elapsed = time.time() - t_embed
                rate = pdfs_embedded / max(elapsed, 0.01)
                remaining = len(uid_list) - pdfs_embedded
                eta_m = remaining / max(rate, 0.01) / 60
                log(f"  [{pdfs_embedded:,}/{len(uid_list):,}] "
                    f"chunks={total_chunks:,} points={total_points:,} "
                    f"err={errors} | {rate:.1f} PDF/s | ETA {eta_m:.1f}m")

            # Save state every 100 PDFs
            if pdfs_embedded % 100 == 0:
                state["processed_uuids"] = list(processed_set)
                state["total_chunks"] = total_chunks
                state["total_points"] = total_points
                state["errors"] = errors
                state["error_uuids"] = error_uuids[-100:]  # keep last 100
                state["elapsed_seconds"] = int(time.time() - t_embed)
                state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
                save_state(state, state_file)

    # ---- Final state save ----
    total_elapsed = time.time() - t0
    state["processed_uuids"] = list(processed_set)
    state["total_chunks"] = total_chunks
    state["total_points"] = total_points
    state["errors"] = errors
    state["error_uuids"] = error_uuids[-100:]
    state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["elapsed_seconds"] = int(total_elapsed)
    save_state(state, state_file)

    log("")
    log("=" * 60)
    log("Embedding complete")
    log(f"  PDFs processed:   {pdfs_embedded:,}")
    log(f"  Total chunks:     {total_chunks:,}")
    log(f"  Qdrant points:    {total_points:,}")
    log(f"  Errors:           {errors}")
    log(f"  Extract time:     {extract_time:.1f}s")
    log(f"  Embed time:       {time.time() - t_embed:.1f}s")
    log(f"  Total duration:   {total_elapsed:.1f}s ({total_elapsed/60:.1f}m)")
    log(f"  Collection:       {COLLECTION}")
    log(f"  Chunks JSONL:     {chunks_jsonl}")
    log(f"  State file:       {state_file}")
    log("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
