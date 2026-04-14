"""Deterministic single-pass rebuild of a chunk-hash -> (uuid, metadata) index.

Motivation: the pre-existing `vertex_batch_chunks.jsonl` and
`vertex_batch_metadata.jsonl` were discovered (2026-04-13) to be misaligned past
line 124,761 — only 10.8% of the 1.15M-line files share the same document per
row, most likely because the extract phase was run twice with different thread
orderings and the two files were concatenated from different runs.

This script walks the PDF corpus in a deterministic order (sorted by file path),
re-extracts text with the SAME `fitz` settings the original pipeline used
(`max_pages=30`, `chunk_size=500`, `overlap=100`, `truncate 3000 chars`), and
writes ONE output file with:

    {
      "uuid": "...",
      "chunk_idx": 0,
      "chunk_total": 12,
      "content_hash": "<sha1 of the 3000-char-truncated chunk>",
      "title": "...", "year": "...", "authors": [...], ...
    }

The hash is the same as what `phase_ingest` computes on `instance.content` from
the Vertex output, so the ingest code can look up the correct metadata via
hash without relying on file line order.

This run does NOT touch Vertex, does NOT upsert to Qdrant, does NOT re-embed.
It only rebuilds the chunk -> metadata lookup.

Usage:
    python backend/scripts/rebuild_chunk_uuid_index.py
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
OUTPUT = BACKEND / "data" / "dspace" / "chunk_hash_index.jsonl"


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Identical to the original extract phase's chunker."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text] if len(words) > 30 else []
    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if len(chunk.split()) > 30:
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


def extract_pdf(pdf_path: str, max_pages: int = 30) -> str:
    """Identical to `vertex_extract_fast.extract_pdf_fitz`."""
    try:
        if os.path.getsize(pdf_path) > 50 * 1024 * 1024:
            return ""
        doc = fitz.open(pdf_path)
        try:
            parts = []
            n = min(len(doc), max_pages)
            for i in range(n):
                parts.append(doc[i].get_text())
            text = " ".join(parts)
        finally:
            doc.close()
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) >= 50 else ""
    except Exception:
        return ""


def main() -> int:
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Discover PDFs deterministically (sorted path order).
    log(f"Scanning {PDF_DIR}...")
    pdf_files: list[tuple[str, str]] = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                uid = f[: -len(".pdf")]
                pdf_files.append((uid, os.path.join(dirpath, f)))
    pdf_files.sort(key=lambda t: t[1])
    log(f"  Found {len(pdf_files):,} PDFs")

    # Preload all metadata from dspace_index.db into a dict keyed by uuid.
    log(f"Loading metadata from {INDEX_DB}...")
    meta_by_uuid: dict[str, dict] = {}
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row
    for row in conn.execute(
        "SELECT uuid, title, year, type, department, collection_name, authors_json FROM items"
    ):
        try:
            authors = json.loads(row["authors_json"] or "[]")[:5]
        except Exception:
            authors = []
        meta_by_uuid[row["uuid"]] = {
            "title": row["title"] or "",
            "year": row["year"] or "",
            "type": row["type"] or "",
            "department": row["department"] or "",
            "collection": row["collection_name"] or "",
            "authors": authors,
        }
    conn.close()
    log(f"  Loaded metadata for {len(meta_by_uuid):,} items")

    # Walk PDFs single-threaded, deterministically. PyMuPDF is fast enough that
    # 97k PDFs × ~100ms/PDF ≈ 16 min on this workstation.
    t0 = time.time()
    chunks_written = 0
    errors = 0
    missing_meta = 0
    hashes_seen: set[bytes] = set()
    duplicate_hashes = 0

    with open(OUTPUT, "w", encoding="utf-8") as out:
        for i, (uid, path) in enumerate(pdf_files):
            if i and i % 1000 == 0:
                elapsed = time.time() - t0
                rate = i / max(elapsed, 0.01)
                log(f"  {i:,}/{len(pdf_files):,} PDFs | {chunks_written:,} chunks | "
                    f"{errors} extract errors | {missing_meta} missing meta | "
                    f"{rate:.0f} PDF/s")

            text = extract_pdf(path)
            if not text:
                errors += 1
                continue

            chunks = chunk_text(text)
            if not chunks:
                errors += 1
                continue

            meta = meta_by_uuid.get(uid)
            if meta is None:
                missing_meta += 1
                continue

            total_chunks = len(chunks)
            for ci, chunk in enumerate(chunks):
                text_trunc = chunk[:3000]
                h = hashlib.sha1(text_trunc.encode("utf-8")).digest()
                if h in hashes_seen:
                    duplicate_hashes += 1
                    # Skip duplicates so the lookup stays 1:1. Content-identical
                    # chunks produce the same embedding anyway; losing one chunk's
                    # attribution for a handful of boilerplate is acceptable.
                    continue
                hashes_seen.add(h)
                record = {
                    "uuid": uid,
                    "chunk_idx": ci,
                    "chunk_total": total_chunks,
                    "content_hash": h.hex(),
                    "content_prefix": text_trunc[:200],
                    **meta,
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                chunks_written += 1

    elapsed = time.time() - t0
    log(f"\nDone in {elapsed/60:.1f} min")
    log(f"  {chunks_written:,} unique chunks")
    log(f"  {errors:,} extraction errors")
    log(f"  {missing_meta:,} PDFs without metadata in dspace_index.db")
    log(f"  {duplicate_hashes:,} duplicate content hashes skipped")
    log(f"  Output: {OUTPUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
