"""
Vertex AI BATCH embedding pipeline — $1.50 for all 97k PDFs.

Pipeline:
  1. Extract text from all PDFs, chunk, save as JSONL
  2. Upload JSONL to GCS
  3. Submit batch prediction job
  4. Wait for completion
  5. Download results, parse embeddings
  6. Upsert to local Qdrant

Input JSONL format (per line):
  {"content": "chunk text", "task_type": "RETRIEVAL_DOCUMENT"}

Output JSONL format (per line):
  {"instance": {...}, "predictions": [{"embeddings": {"values": [...]}}]}

Usage:
    python scripts/embed_vertex_batch_real.py --phase extract    # Phase 1: extract+chunk
    python scripts/embed_vertex_batch_real.py --phase upload     # Phase 2: upload to GCS
    python scripts/embed_vertex_batch_real.py --phase submit     # Phase 3: submit batch job
    python scripts/embed_vertex_batch_real.py --phase check      # Phase 4: check job status
    python scripts/embed_vertex_batch_real.py --phase ingest     # Phase 5: download + upsert to Qdrant
    python scripts/embed_vertex_batch_real.py --phase all        # Run all phases

COST ESTIMATE: ~$1.50 for 97k PDFs (batch pricing: $0.0002/1M chars)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid as uuid_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from pdfminer.high_level import extract_text
import concurrent.futures

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
STATE_DIR = BACKEND / "data" / "embed_state"

CHUNKS_JSONL = BACKEND / "data" / "dspace" / "vertex_batch_chunks.jsonl"
METADATA_JSONL = BACKEND / "data" / "dspace" / "vertex_batch_metadata.jsonl"
# Authoritative hash -> metadata lookup, rebuilt from PDFs directly by
# `rebuild_chunk_uuid_index.py`. Used by --phase ingest because the legacy
# chunks/metadata files drift apart past line 124,761 (discovered 2026-04-13).
CHUNK_HASH_INDEX = BACKEND / "data" / "dspace" / "chunk_hash_index.jsonl"
STATE_FILE = STATE_DIR / "vertex_batch_state.json"
SPLIT_DIR = BACKEND / "data" / "dspace" / "vertex_batch_split"

GCS_BUCKET = "gs://rag-dspace-pdfs"
GCS_INPUT = f"{GCS_BUCKET}/batch-embed/full_input.jsonl"
GCS_OUTPUT_PREFIX = f"{GCS_BUCKET}/batch-embed/full_output/"
VERTEX_BATCH_LIMIT = 1_000_000  # hard cap on instances per BatchPredictionJob
GCLOUD = "D:/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
PROJECT = "rag-dspace"
LOCATION = "us-central1"
MODEL = "publishers/google/models/text-embedding-005"
QDRANT_LOCAL = "http://localhost:6334"
COLLECTION = "dspace_fulltext_vertex"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_pdf_text(pdf_path: str, max_pages: int = 30) -> str:
    try:
        if os.path.getsize(pdf_path) > 50 * 1024 * 1024:
            return ""
        def _extract():
            return extract_text(pdf_path, maxpages=max_pages)
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_extract)
            text = future.result(timeout=30)
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) >= 50 else ""
    except Exception:
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


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except: pass
    return {}


def save_state(state):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def ensure_split(total: int) -> list[Path]:
    """Idempotently split CHUNKS_JSONL into `total` near-equal parts under SPLIT_DIR.

    Skips work if existing split files already sum to the master file's byte size.
    Returns the list of split file paths in part order.
    """
    SPLIT_DIR.mkdir(parents=True, exist_ok=True)
    part_paths = [SPLIT_DIR / f"chunks_part{i}.jsonl" for i in range(total)]

    if all(p.exists() for p in part_paths):
        master_size = CHUNKS_JSONL.stat().st_size
        split_size = sum(p.stat().st_size for p in part_paths)
        if split_size == master_size:
            log(f"  Split files fresh: {total} parts, {master_size/1024/1024:.1f} MB total")
            return part_paths
        log(f"  Split files stale (sum {split_size} != master {master_size}); regenerating")

    log(f"  Counting lines in {CHUNKS_JSONL.name}...")
    total_lines = 0
    with open(CHUNKS_JSONL, "rb") as f:
        for _ in f:
            total_lines += 1

    for i in range(total):
        if total_lines // max(total, 1) >= VERTEX_BATCH_LIMIT:
            log(f"  ERROR: part would have ~{total_lines//total:,} lines, still exceeds "
                f"Vertex limit {VERTEX_BATCH_LIMIT:,}. Increase --total.")
            sys.exit(1)

    per_part = (total_lines + total - 1) // total  # ceiling
    log(f"  Splitting {total_lines:,} lines into {total} parts of ~{per_part:,}")

    with open(CHUNKS_JSONL, "rb") as src:
        for idx in range(total):
            with open(part_paths[idx], "wb") as dst:
                written = 0
                while written < per_part:
                    line = src.readline()
                    if not line:
                        break
                    dst.write(line)
                    written += 1

    for i, p in enumerate(part_paths):
        size_mb = p.stat().st_size / 1024 / 1024
        log(f"  part {i}: {p.name} ({size_mb:.1f} MB)")
    return part_paths


def resolve_parts(total: int) -> list[dict]:
    """Return a list of part specs, each a dict with idx/local_path/gcs_input/gcs_output_prefix.

    For total==1 uses the master file and default GCS paths (back-compat).
    For total>1 splits the master file and uses `*_part{i}` GCS paths.
    """
    if total == 1:
        return [{
            "idx": 0,
            "local_path": CHUNKS_JSONL,
            "gcs_input": GCS_INPUT,
            "gcs_output_prefix": GCS_OUTPUT_PREFIX,
        }]

    split_files = ensure_split(total)
    return [
        {
            "idx": i,
            "local_path": p,
            "gcs_input": f"{GCS_BUCKET}/batch-embed/full_input_part{i}.jsonl",
            "gcs_output_prefix": f"{GCS_BUCKET}/batch-embed/full_output_part{i}/",
        }
        for i, p in enumerate(split_files)
    ]


def ensure_parts_state(state: dict, total: int) -> None:
    """Make sure state['parts'] is a list of `total` dicts. Mutates state in place."""
    parts = state.get("parts")
    if not isinstance(parts, list) or len(parts) != total:
        state["parts"] = [{} for _ in range(total)]


def phase_extract(args):
    """Phase 1: Extract text from PDFs and create input JSONL."""
    log("Phase 1: Extract + Chunk PDFs")

    # Collect PDFs
    pdf_files = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                pdf_files.append((f.replace(".pdf", ""), os.path.join(dirpath, f)))
    log(f"  Found {len(pdf_files):,} PDFs")

    # Load metadata
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # Extract and chunk with parallel workers
    chunks_written = 0
    metadata_written = 0
    errors = 0
    t0 = time.time()
    from threading import Lock
    write_lock = Lock()

    cf = open(CHUNKS_JSONL, "w", encoding="utf-8")
    mf = open(METADATA_JSONL, "w", encoding="utf-8")

    def process_and_write(uid_path):
        nonlocal chunks_written, metadata_written, errors
        uid, pdf_path = uid_path
        text = extract_pdf_text(pdf_path)
        if not text:
            errors += 1
            return
        chunks = chunk_text(text)
        if not chunks:
            errors += 1
            return

        # Get metadata (each thread opens its own DB connection)
        meta_conn = sqlite3.connect(INDEX_DB)
        meta_conn.row_factory = sqlite3.Row
        row = meta_conn.execute(
            "SELECT title, year, type, department, collection_name, authors_json FROM items WHERE uuid = ?",
            (uid,),
        ).fetchone()
        meta = {"uuid": uid}
        if row:
            meta.update({
                "title": row["title"] or "",
                "year": row["year"] or "",
                "type": row["type"] or "",
                "department": row["department"] or "",
                "collection": row["collection_name"] or "",
            })
            try:
                meta["authors"] = json.loads(row["authors_json"] or "[]")[:5]
            except:
                meta["authors"] = []
        meta_conn.close()

        # Write immediately with lock
        with write_lock:
            for i, chunk in enumerate(chunks):
                text_trunc = chunk[:3000]
                cf.write(json.dumps({
                    "content": text_trunc,
                    "task_type": "RETRIEVAL_DOCUMENT",
                }, ensure_ascii=False) + "\n")
                mf.write(json.dumps({
                    **meta,
                    "chunk_idx": i,
                    "chunk_total": len(chunks),
                    "text_preview": text_trunc[:200],
                }, ensure_ascii=False) + "\n")
                chunks_written += 1
                metadata_written += 1

    done = 0
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = {pool.submit(process_and_write, item): item for item in pdf_files}
        for future in as_completed(futures):
            future.result()  # propagate exceptions
            done += 1
            if done % 1000 == 0:
                cf.flush()
                mf.flush()
                elapsed = time.time() - t0
                log(f"  {done:,}/{len(pdf_files):,} PDFs | {chunks_written:,} chunks | "
                    f"{errors} errors | {done/max(elapsed,0.01):.1f} PDF/s")

    cf.close()
    mf.close()

    conn.close()
    elapsed = time.time() - t0

    state = load_state()
    state["extract"] = {
        "chunks": chunks_written,
        "pdfs": len(pdf_files),
        "errors": errors,
        "elapsed": int(elapsed),
        "chunks_file": str(CHUNKS_JSONL),
        "metadata_file": str(METADATA_JSONL),
    }
    save_state(state)

    # Estimate cost
    file_size = CHUNKS_JSONL.stat().st_size
    est_chars = file_size  # roughly 1 byte per char for ASCII
    est_cost = (est_chars / 1_000_000) * 0.0002
    log(f"\n  Done: {chunks_written:,} chunks from {len(pdf_files):,} PDFs in {elapsed/60:.1f} min")
    log(f"  JSONL size: {file_size/1024/1024:.1f} MB")
    log(f"  Estimated batch cost: ${est_cost:.2f}")


def phase_upload(args):
    """Phase 2: Upload chunks JSONL to GCS (splits into parts if --total > 1)."""
    log("Phase 2: Upload to GCS")

    if not CHUNKS_JSONL.exists():
        log("  ERROR: Run --phase extract first")
        return

    parts = resolve_parts(args.total)
    state = load_state()
    ensure_parts_state(state, args.total)
    state["total_parts"] = args.total

    for part in parts:
        if args.part is not None and part["idx"] != args.part:
            continue
        local = part["local_path"]
        gcs_input = part["gcs_input"]
        size_gb = local.stat().st_size / 1024 / 1024 / 1024
        log(f"  [part {part['idx']}] uploading {local.name} ({size_gb:.2f} GB) to {gcs_input}")

        result = subprocess.run(
            [GCLOUD, "storage", "cp", str(local), gcs_input, f"--project={PROJECT}"],
            capture_output=True, text=True, timeout=3600,
            encoding="utf-8", errors="replace",
        )

        if result.returncode == 0:
            log(f"  [part {part['idx']}] upload complete")
            state["parts"][part["idx"]]["upload"] = {
                "gcs_input": gcs_input,
                "local_file": str(local),
                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
            save_state(state)
        else:
            log(f"  [part {part['idx']}] FAILED: {result.stderr[:300]}")
            return


def phase_submit(args):
    """Phase 3: Submit batch prediction job(s). One job per part."""
    log("Phase 3: Submit batch job")

    parts = resolve_parts(args.total)
    state = load_state()
    ensure_parts_state(state, args.total)

    total_bytes = sum(p["local_path"].stat().st_size for p in parts)
    est_cost = (total_bytes / 1_000_000) * 0.0002
    log(f"  Estimated total cost across {args.total} part(s): ${est_cost:.2f}")

    if est_cost > 50 and not args.force:
        log(f"  WARNING: Cost exceeds $50. Use --force to override.")
        return

    from google.cloud import aiplatform
    aiplatform.init(project=PROJECT, location=LOCATION)

    stamp = time.strftime("%Y%m%d-%H%M")

    for part in parts:
        if args.part is not None and part["idx"] != args.part:
            continue

        # Guard: skip parts that already have a live job recorded
        prev = state["parts"][part["idx"]].get("submit", {}).get("job_name")
        if prev and not args.force:
            log(f"  [part {part['idx']}] already has job {prev}; pass --force to resubmit")
            continue

        display = f"embed-fulltext-part{part['idx']}-of-{args.total}-{stamp}"
        log(f"  [part {part['idx']}] submitting {display}")
        log(f"  [part {part['idx']}] gcs_source={part['gcs_input']}")
        log(f"  [part {part['idx']}] gcs_destination_prefix={part['gcs_output_prefix']}")

        job = aiplatform.BatchPredictionJob.create(
            job_display_name=display,
            model_name=MODEL,
            instances_format="jsonl",
            gcs_source=part["gcs_input"],
            gcs_destination_prefix=part["gcs_output_prefix"],
            predictions_format="jsonl",
            sync=False,
        )

        job_name = None
        for _ in range(20):
            try:
                job_name = job.resource_name
                break
            except RuntimeError:
                time.sleep(2)

        if not job_name:
            log(f"  [part {part['idx']}] WARNING: resource_name unavailable after 40s — check Vertex dashboard")
            continue

        log(f"  [part {part['idx']}] job: {job_name}")
        state["parts"][part["idx"]]["submit"] = {
            "job_name": job_name,
            "display_name": display,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_state(state)

    log(f"  Monitor: https://console.cloud.google.com/ai/platform/locations/{LOCATION}/batch-predictions/?project={PROJECT}")


def phase_check(args):
    """Phase 4: Check batch job status for all parts."""
    log("Phase 4: Check job status")

    from google.cloud import aiplatform

    # JobState enum values (stable ordering from aiplatform_v1.JobState):
    #   0 UNSPECIFIED, 1 QUEUED, 2 PENDING, 3 RUNNING,
    #   4 SUCCEEDED, 5 FAILED, 6 CANCELLING, 7 CANCELLED,
    #   8 PAUSED, 9 EXPIRED
    STATE_NAMES = {
        0: "UNSPECIFIED", 1: "QUEUED", 2: "PENDING", 3: "RUNNING",
        4: "SUCCEEDED", 5: "FAILED", 6: "CANCELLING", 7: "CANCELLED",
        8: "PAUSED", 9: "EXPIRED",
    }

    def coerce_state(js) -> int:
        try:
            return int(js)
        except Exception:
            v = getattr(js, "value", None)
            if v is not None:
                return int(v)
            s = str(js)
            for k, name in STATE_NAMES.items():
                if name in s:
                    return k
            return -1

    aiplatform.init(project=PROJECT, location=LOCATION)

    state = load_state()
    parts_state = state.get("parts", [])
    if not parts_state:
        log("  ERROR: No parts submitted. Run --phase submit first")
        return

    all_done = True
    any_failed = False

    for idx, part_state in enumerate(parts_state):
        if args.part is not None and idx != args.part:
            continue
        job_name = part_state.get("submit", {}).get("job_name")
        if not job_name:
            log(f"  [part {idx}] no job submitted")
            all_done = False
            continue

        job = aiplatform.BatchPredictionJob(job_name)
        state_int = coerce_state(job.state)
        state_name = STATE_NAMES.get(state_int, f"UNKNOWN({state_int})")
        log(f"  [part {idx}] {job_name}")
        log(f"  [part {idx}] state: {state_int} ({state_name})")

        if state_int == 4:  # SUCCEEDED
            output_dir = job.output_info.gcs_output_directory
            log(f"  [part {idx}] output: {output_dir}")
            part_state["check"] = {"state": "SUCCEEDED", "output_dir": output_dir}
        elif state_int == 5:  # FAILED
            err_msg = getattr(job.error, "message", None) or str(job.error)
            log(f"  [part {idx}] ERROR: {err_msg}")
            part_state["check"] = {"state": "FAILED", "error": err_msg}
            all_done = False
            any_failed = True
        else:
            log(f"  [part {idx}] still running")
            all_done = False

    save_state(state)
    if any_failed:
        log("  At least one part FAILED. Fix and resubmit before --phase ingest.")
    elif all_done:
        log("  All parts SUCCEEDED. Ready for --phase ingest.")


def phase_ingest(args):
    """Phase 5: Download results from all parts and upsert to Qdrant.

    Rebuilt 2026-04-13 to match the live backend's query contract:
      - Collection is created with a NAMED "dense" vector (not default unnamed).
        The backend uses `query_points(..., using="dense")` which requires this.
      - Full chunk text (from the Vertex input `instance.content`) is stored in
        `payload["text"]` so the LLM receives real context rather than a 200-char
        preview.
      - Payload field names match the backend's expectations: `doc_title` (not
        `title`), `dspace_url`, `chunk_id`. Other fields carried through.
      - Point IDs are deterministic UUID5 values derived from
        `(doc_uuid, chunk_idx)`, so re-running ingest upserts existing points
        instead of duplicating them with new random UUIDs.
      - **Metadata is joined by content-hash, not by line index.** Vertex Batch
        does NOT preserve input line order in its output files (verified empirically
        2026-04-13), so the previous in-order ingest produced scrambled
        title-to-text pairings. The chunks file and metadata file are in lockstep
        because they were written together under a lock during extract, so we
        hash each chunk's content once and look up metadata by that hash during
        output processing.
    """
    import hashlib

    log("Phase 5: Ingest results to Qdrant")

    state = load_state()
    parts_state = state.get("parts", [])
    if not parts_state:
        log("  ERROR: No parts found in state. Run --phase check first")
        return

    ready_parts = []
    for idx, part_state in enumerate(parts_state):
        if args.part is not None and idx != args.part:
            continue
        output_dir = part_state.get("check", {}).get("output_dir")
        if not output_dir:
            log(f"  [part {idx}] not ready (no check.output_dir). Run --phase check")
            if args.part is not None:
                return
            continue
        ready_parts.append((idx, output_dir))

    if not ready_parts:
        log("  No ready parts to ingest.")
        return

    # Load the authoritative chunk -> metadata lookup. This is built by
    # `rebuild_chunk_uuid_index.py` directly from PDFs, so hashes are 1:1 with
    # (uuid, chunk_idx, metadata) without relying on the legacy chunks /
    # metadata files that drift past line 124,761.
    if not CHUNK_HASH_INDEX.exists():
        log(f"  ERROR: {CHUNK_HASH_INDEX} not found. Run:")
        log(f"         python backend/scripts/rebuild_chunk_uuid_index.py")
        return

    log(f"  Loading chunk-hash index from {CHUNK_HASH_INDEX.name}...")

    def _hash(s: str) -> bytes:
        return hashlib.sha1(s.encode("utf-8")).digest()

    hash_to_meta: Dict[bytes, Dict[str, Any]] = {}
    with open(CHUNK_HASH_INDEX, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            h_hex = rec.get("content_hash")
            if not h_hex:
                continue
            hash_to_meta[bytes.fromhex(h_hex)] = rec
    log(f"  Loaded {len(hash_to_meta):,} chunk-hash entries")

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm

    qclient = QdrantClient(url=QDRANT_LOCAL, timeout=60)

    DSPACE_BASE_URL = os.environ.get("DSPACE_BASE_URL", "https://dr.lib.iastate.edu")
    NAMESPACE = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")  # uuid.NAMESPACE_URL

    # Create collection with backend-compatible schema: a named "dense" vector.
    try:
        existing = qclient.get_collection(COLLECTION)
        # Sanity check: if the existing collection doesn't have a named "dense"
        # vector, that's the old bad schema — refuse to ingest into it.
        vcfg = existing.config.params.vectors
        if isinstance(vcfg, dict) and "dense" in vcfg:
            log(f"  Collection {COLLECTION} exists with named 'dense' vector — reusing")
        else:
            log(f"  ERROR: {COLLECTION} exists with wrong schema (expected named 'dense' vector).")
            log(f"         Delete the collection first:")
            log(f"           curl -X DELETE http://localhost:6334/collections/{COLLECTION}")
            return
    except Exception:
        qclient.create_collection(
            collection_name=COLLECTION,
            vectors_config={
                "dense": qm.VectorParams(size=768, distance=qm.Distance.COSINE),
            },
        )
        log(f"  Created collection {COLLECTION} with named 'dense' vector (768d, cosine)")

    total_points = 0
    total_skipped_no_match = 0  # chunks whose instance.content didn't hash-match metadata

    for idx, output_dir in ready_parts:
        local_output_dir = BACKEND / "data" / "dspace" / f"vertex_batch_output_part{idx}"
        local_output_dir.mkdir(exist_ok=True)

        # If we already have the output files locally, skip the GCS download.
        local_files = sorted(local_output_dir.glob("*.jsonl"))
        if local_files:
            log(f"  [part {idx}] {len(local_files)} output files already local; "
                f"skipping GCS download")
        else:
            log(f"  [part {idx}] downloading from {output_dir}")
            result = subprocess.run(
                [GCLOUD, "storage", "cp", f"{output_dir}/*.jsonl",
                 str(local_output_dir) + "/", f"--project={PROJECT}"],
                capture_output=True, text=True, timeout=3600,
                encoding="utf-8", errors="replace",
            )
            if result.returncode != 0:
                log(f"  [part {idx}] download failed: {result.stderr[:300]}")
                return
            local_files = sorted(local_output_dir.glob("*.jsonl"))

        part_points = 0
        part_skipped = 0
        for output_file in local_files:
            log(f"  [part {idx}] processing {output_file.name}")
            batch_points = []

            with open(output_file, encoding="utf-8") as f:
                for line in f:
                    d = json.loads(line)
                    instance = d.get("instance", {})
                    predictions = d.get("predictions", [])
                    if not predictions:
                        continue
                    embedding = predictions[0].get("embeddings", {}).get("values", [])
                    if not embedding:
                        continue

                    # The full chunk text is in the instance we submitted.
                    chunk_text = instance.get("content", "")
                    if not chunk_text:
                        continue

                    # Look up metadata by content hash via the authoritative
                    # chunk_hash_index (rebuilt from PDFs). Vertex doesn't
                    # preserve input order across output shards, so we can't
                    # use the output's line index to locate metadata.
                    meta = hash_to_meta.get(_hash(chunk_text))
                    if meta is None:
                        part_skipped += 1
                        continue

                    doc_uuid = meta.get("uuid", "")
                    chunk_idx_val = meta.get("chunk_idx", 0)
                    chunk_total = meta.get("chunk_total", 1)

                    # Deterministic UUID5 so re-ingest upserts cleanly
                    point_id = str(uuid_mod.uuid5(NAMESPACE, f"{doc_uuid}#{chunk_idx_val}"))

                    payload = {
                        "uuid": doc_uuid,
                        "chunk_id": f"{doc_uuid}#{chunk_idx_val}",
                        "chunk_idx": chunk_idx_val,
                        "chunk_total": chunk_total,
                        "doc_title": meta.get("title", ""),
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

                    batch_points.append(qm.PointStruct(
                        id=point_id,
                        vector={"dense": embedding},
                        payload=payload,
                    ))

                    if len(batch_points) >= 100:
                        qclient.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
                        part_points += len(batch_points)
                        batch_points = []

            if batch_points:
                qclient.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
                part_points += len(batch_points)

        parts_state[idx]["ingest"] = {
            "points": part_points,
            "skipped_no_match": part_skipped,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        save_state(state)
        total_points += part_points
        total_skipped_no_match += part_skipped
        log(f"  [part {idx}] done: {part_points:,} points, {part_skipped:,} skipped (no hash match)")

    log(f"\n  Ingested {total_points:,} total points to {COLLECTION}")
    if total_skipped_no_match:
        log(f"  Skipped {total_skipped_no_match:,} output lines without a metadata hash match")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["extract", "upload", "submit", "check", "ingest", "all"])
    parser.add_argument("--total", type=int, default=1,
                        help="Number of parts to split the input into. Vertex Batch caps at "
                             f"{VERTEX_BATCH_LIMIT:,} instances per job. Default 1 (single job).")
    parser.add_argument("--part", type=int, default=None,
                        help="Operate on this part only (0-indexed). Default: all parts.")
    parser.add_argument("--force", action="store_true",
                        help="Override cost safety check / resubmit live parts")
    args = parser.parse_args()

    if args.total < 1:
        parser.error("--total must be >= 1")
    if args.part is not None and (args.part < 0 or args.part >= args.total):
        parser.error(f"--part must be in [0, {args.total - 1}]")

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    phases = {
        "extract": phase_extract,
        "upload": phase_upload,
        "submit": phase_submit,
        "check": phase_check,
        "ingest": phase_ingest,
    }

    if args.phase == "all":
        for name in ["extract", "upload", "submit"]:
            phases[name](args)
            log("")
        log("Batch job submitted. Run --phase check periodically, then --phase ingest when done.")
    else:
        phases[args.phase](args)


if __name__ == "__main__":
    sys.exit(main())
