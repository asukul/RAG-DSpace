"""
arXiv CS abstract-level embedding pipeline.

Reads the harvested arXiv OAI-PMH records from backend/data/arxiv_cs/oai_records,
extracts `title + abstract` per paper, submits to Vertex Batch with
text-embedding-005, and upserts results into a new Qdrant collection
`arxiv_cs_vertex` on the LOCAL Docker Qdrant.

Expected cost at the verified $1.95 / 1 B chars rate:
  ~200k papers * ~1.5 kB (title + abstract) = ~300 M chars ≈ **$0.58 total**

Pipeline phases match embed_mit_abstracts.py: extract, upload, submit, check, ingest.

Usage:
  python backend/scripts/embed_arxiv_abstracts.py --phase extract
  python backend/scripts/embed_arxiv_abstracts.py --phase upload
  python backend/scripts/embed_arxiv_abstracts.py --phase submit
  python backend/scripts/embed_arxiv_abstracts.py --phase check
  python backend/scripts/embed_arxiv_abstracts.py --phase ingest
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid as uuid_mod
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
OAI_DIR = BACKEND / "data" / "arxiv_cs" / "oai_records"
CHUNKS_JSONL = BACKEND / "data" / "arxiv_cs" / "vertex_batch_chunks.jsonl"
METADATA_JSONL = BACKEND / "data" / "arxiv_cs" / "vertex_batch_metadata.jsonl"
STATE_FILE = BACKEND / "data" / "embed_state" / "arxiv_cs_state.json"

GCS_BUCKET = "gs://rag-dspace-pdfs"
GCS_INPUT = f"{GCS_BUCKET}/batch-embed-arxiv/full_input.jsonl"
GCS_OUTPUT_PREFIX = f"{GCS_BUCKET}/batch-embed-arxiv/full_output/"
GCLOUD = "D:/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd"
PROJECT = "rag-dspace"
LOCATION = "us-central1"
MODEL = "publishers/google/models/text-embedding-005"

QDRANT_LOCAL = "http://localhost:6334"
COLLECTION = "arxiv_cs_vertex"

NAMESPACE = uuid_mod.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")

STATE_NAMES = {
    0: "UNSPECIFIED", 1: "QUEUED", 2: "PENDING", 3: "RUNNING",
    4: "SUCCEEDED", 5: "FAILED", 6: "CANCELLING", 7: "CANCELLED",
    8: "PAUSED", 9: "EXPIRED",
}

_WS = re.compile(r"\s+")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def extract_paper_content(rec: Dict[str, Any]) -> str:
    """
    Build a single embedding text for an arXiv paper: title + abstract + categories.
    """
    title = _WS.sub(" ", (rec.get("title") or "").strip())
    abstract = _WS.sub(" ", (rec.get("abstract") or "").strip())
    categories = (rec.get("categories") or "").strip()
    parts = []
    if title:
        parts.append(f"Title: {title}")
    if categories:
        parts.append(f"Categories: {categories}")
    if abstract:
        parts.append(f"Abstract: {abstract}")
    text = "\n".join(parts)
    return text[:3000]


def phase_extract(args) -> None:
    log("Phase 1: Extract arXiv CS OAI records")
    if not OAI_DIR.exists():
        log(f"  ERROR: no arXiv OAI records at {OAI_DIR}")
        log(f"         run harvest_arxiv_cs.py first")
        return

    batch_files = sorted(OAI_DIR.glob("batch_*.jsonl"))
    if not batch_files:
        log(f"  ERROR: no batch_*.jsonl files in {OAI_DIR}")
        return
    log(f"  {len(batch_files)} batch files")

    CHUNKS_JSONL.parent.mkdir(parents=True, exist_ok=True)
    METADATA_JSONL.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped_empty = 0
    total_chars = 0
    with open(CHUNKS_JSONL, "w", encoding="utf-8") as cf, \
         open(METADATA_JSONL, "w", encoding="utf-8") as mf:
        for batch_file in batch_files:
            with open(batch_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        rec = json.loads(line)
                    except Exception:
                        continue
                    content = extract_paper_content(rec)
                    if not content or len(content) < 50:
                        skipped_empty += 1
                        continue
                    arxiv_id = rec.get("id", "") or rec.get("identifier", "")
                    # arxiv id is like "2109.12345v1"; strip version for URL
                    arxiv_base = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

                    authors_list = []
                    for au in (rec.get("authors") or []):
                        fn = (au.get("forenames") or "").strip()
                        kn = (au.get("keyname") or "").strip()
                        if fn and kn:
                            authors_list.append(f"{kn}, {fn}")
                        elif kn:
                            authors_list.append(kn)

                    cf.write(json.dumps(
                        {"content": content, "task_type": "RETRIEVAL_DOCUMENT"},
                        ensure_ascii=False,
                    ) + "\n")

                    meta = {
                        "uuid": arxiv_id,
                        "doc_title": (rec.get("title") or "").strip(),
                        "authors": authors_list[:10],
                        "year": (rec.get("created") or rec.get("datestamp") or "")[:4],
                        "type": "article",
                        "department": "",
                        "collection": rec.get("categories") or "",
                        "dspace_url": f"https://arxiv.org/abs/{arxiv_base}" if arxiv_base else "",
                        "heading": "",
                        "page": 0,
                        "text": content,
                        "content_hash": hashlib.sha1(content.encode("utf-8")).hexdigest(),
                        "doi": rec.get("doi") or "",
                    }
                    mf.write(json.dumps(meta, ensure_ascii=False) + "\n")

                    written += 1
                    total_chars += len(content)

    log(f"  wrote {written:,} instances, skipped {skipped_empty:,} empty")
    log(f"  total chars: {total_chars:,} ({total_chars/1e9:.3f} B)")
    log(f"  estimated cost at $1.95/1B: ${total_chars/1e9*1.95:.3f}")

    state = load_state()
    state["extract"] = {
        "written": written,
        "skipped_empty": skipped_empty,
        "total_chars": total_chars,
        "chunks_file": str(CHUNKS_JSONL),
        "metadata_file": str(METADATA_JSONL),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


def phase_upload(args) -> None:
    log("Phase 2: Upload arXiv chunks to GCS")
    if not CHUNKS_JSONL.exists():
        log(f"  ERROR: {CHUNKS_JSONL} not found. Run --phase extract first.")
        return
    size_mb = CHUNKS_JSONL.stat().st_size / 1024 / 1024
    log(f"  uploading {size_mb:.1f} MB -> {GCS_INPUT}")
    result = subprocess.run(
        [GCLOUD, "storage", "cp", str(CHUNKS_JSONL), GCS_INPUT, f"--project={PROJECT}"],
        capture_output=True, text=True, timeout=1800,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        log(f"  FAILED: {result.stderr[:300]}")
        return
    log("  upload complete")
    state = load_state()
    state["upload"] = {
        "gcs_input": GCS_INPUT,
        "size_mb": round(size_mb, 2),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


def phase_submit(args) -> None:
    log("Phase 3: Submit Vertex BatchPredictionJob for arXiv CS")
    from google.cloud import aiplatform
    aiplatform.init(project=PROJECT, location=LOCATION)

    state = load_state()
    if state.get("submit", {}).get("job_name") and not args.force:
        log(f"  Already submitted: {state['submit']['job_name']}")
        log(f"  Use --force to resubmit.")
        return

    display = f"embed-arxiv-cs-{time.strftime('%Y%m%d-%H%M')}"
    log(f"  display name: {display}")
    job = aiplatform.BatchPredictionJob.create(
        job_display_name=display,
        model_name=MODEL,
        instances_format="jsonl",
        gcs_source=GCS_INPUT,
        gcs_destination_prefix=GCS_OUTPUT_PREFIX,
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
        log("  WARNING: resource_name unavailable; check Vertex dashboard")
        return

    log(f"  job: {job_name}")
    state["submit"] = {
        "job_name": job_name,
        "display_name": display,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


def phase_check(args) -> None:
    log("Phase 4: Check arXiv batch job")
    from google.cloud import aiplatform
    aiplatform.init(project=PROJECT, location=LOCATION)
    state = load_state()
    job_name = state.get("submit", {}).get("job_name")
    if not job_name:
        log("  ERROR: no submitted job.")
        return
    job = aiplatform.BatchPredictionJob(job_name)
    try:
        state_int = int(job.state)
    except Exception:
        state_int = getattr(job.state, "value", -1)
    state_name = STATE_NAMES.get(state_int, f"UNK({state_int})")
    log(f"  state: {state_int} ({state_name})")
    if state_int == 4:
        out_dir = job.output_info.gcs_output_directory
        log(f"  output_dir: {out_dir}")
        state["check"] = {"state": "SUCCEEDED", "output_dir": out_dir}
        save_state(state)
    elif state_int == 5:
        err = getattr(job.error, "message", None) or str(job.error)
        log(f"  ERROR: {err}")
        state["check"] = {"state": "FAILED", "error": err}
        save_state(state)


def phase_ingest(args) -> None:
    log("Phase 5: Ingest arXiv batch output to Qdrant")
    state = load_state()
    output_dir = state.get("check", {}).get("output_dir")
    if not output_dir:
        log("  ERROR: no output_dir in state. Run --phase check first.")
        return

    log("  Loading metadata (content_hash -> meta)...")
    hash_to_meta: Dict[bytes, Dict[str, Any]] = {}
    with open(METADATA_JSONL, encoding="utf-8") as f:
        for line in f:
            try:
                m = json.loads(line)
            except Exception:
                continue
            h = bytes.fromhex(m["content_hash"])
            hash_to_meta[h] = m
    log(f"  {len(hash_to_meta):,} metadata entries")

    local_output = BACKEND / "data" / "arxiv_cs" / "vertex_batch_output"
    local_output.mkdir(exist_ok=True)
    log(f"  Downloading output from {output_dir}")
    result = subprocess.run(
        [GCLOUD, "storage", "cp", f"{output_dir}/*.jsonl", str(local_output) + "/",
         f"--project={PROJECT}"],
        capture_output=True, text=True, timeout=3600,
        encoding="utf-8", errors="replace",
    )
    if result.returncode != 0:
        log(f"  download failed: {result.stderr[:300]}")
        return

    from qdrant_client import QdrantClient
    from qdrant_client.http import models as qm
    qclient = QdrantClient(url=QDRANT_LOCAL, timeout=60)
    try:
        qclient.get_collection(COLLECTION)
        log(f"  Collection {COLLECTION} exists")
    except Exception:
        qclient.create_collection(
            collection_name=COLLECTION,
            vectors_config={
                "dense": qm.VectorParams(size=768, distance=qm.Distance.COSINE),
            },
        )
        log(f"  Created {COLLECTION} with named 'dense' vector")

    total = 0
    skipped = 0
    for out_file in sorted(local_output.glob("*.jsonl")):
        log(f"  processing {out_file.name}")
        batch_points = []
        with open(out_file, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except Exception:
                    continue
                instance = d.get("instance", {})
                predictions = d.get("predictions", [])
                if not predictions:
                    skipped += 1
                    continue
                embedding = predictions[0].get("embeddings", {}).get("values", [])
                if not embedding:
                    skipped += 1
                    continue
                content = instance.get("content", "")
                if not content:
                    skipped += 1
                    continue
                h = hashlib.sha1(content.encode("utf-8")).digest()
                meta = hash_to_meta.get(h)
                if not meta:
                    skipped += 1
                    continue
                uid = meta.get("uuid", "")
                point_id = str(uuid_mod.uuid5(NAMESPACE, f"arxiv:{uid}"))
                batch_points.append(qm.PointStruct(
                    id=point_id,
                    vector={"dense": embedding},
                    payload={k: v for k, v in meta.items() if k != "content_hash"},
                ))
                if len(batch_points) >= 200:
                    qclient.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
                    total += len(batch_points)
                    batch_points = []
        if batch_points:
            qclient.upsert(collection_name=COLLECTION, points=batch_points, wait=True)
            total += len(batch_points)

    log(f"  ingested {total:,} points, skipped {skipped:,}")
    state["ingest"] = {
        "points": total,
        "skipped": skipped,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    save_state(state)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", required=True,
                        choices=["extract", "upload", "submit", "check", "ingest"])
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    phases = {
        "extract": phase_extract,
        "upload": phase_upload,
        "submit": phase_submit,
        "check": phase_check,
        "ingest": phase_ingest,
    }
    phases[args.phase](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
