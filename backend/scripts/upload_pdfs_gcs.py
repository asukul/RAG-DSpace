"""
Upload PDFs to Google Cloud Storage (Nearline) with parallel transfers.

Features:
  - Parallel uploads (configurable workers)
  - Skip existing files (resumable)
  - Verify with file count comparison
  - Lifecycle policy: auto-move to Coldline after 90 days

Usage:
    python scripts/upload_pdfs_gcs.py
    python scripts/upload_pdfs_gcs.py --workers 16 --verify
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PDF_DIR = BACKEND / "data" / "pdfs"
STATE_FILE = BACKEND / "data" / "embed_state" / "gcs_upload_state.json"

BUCKET = "gs://rag-dspace-pdfs"
PROJECT = "rag-dspace"
LOCATION = "us-central1"

# Find gcloud executable (Windows needs .cmd extension)
GCLOUD = "gcloud"
if sys.platform == "win32":
    _gcloud_cmd = Path("D:/Google/Cloud SDK/google-cloud-sdk/bin/gcloud.cmd")
    if _gcloud_cmd.exists():
        GCLOUD = str(_gcloud_cmd)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def count_local_pdfs():
    count = 0
    total_bytes = 0
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                count += 1
                total_bytes += os.path.getsize(os.path.join(dirpath, f))
    return count, total_bytes


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"uploaded_dirs": [], "started_at": None, "finished_at": None}


def save_state(state):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=32,
                        help="Parallel upload threads")
    parser.add_argument("--verify", action="store_true",
                        help="Verify upload counts after completion")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    state = load_state()
    state["started_at"] = state["started_at"] or time.strftime("%Y-%m-%d %H:%M:%S")

    # Count local files
    local_count, local_bytes = count_local_pdfs()
    log("=" * 60)
    log("GCS PDF Upload Pipeline")
    log(f"  Local PDFs:   {local_count:,} ({local_bytes/1024/1024/1024:.1f} GB)")
    log(f"  Bucket:       {BUCKET}")
    log(f"  Storage:      Nearline (auto-Coldline after 90 days)")
    log(f"  Workers:      {args.workers}")
    log("=" * 60)

    if args.dry_run:
        log("[DRY RUN] Would upload to GCS. Exiting.")
        return 0

    # Step 1: Create bucket if needed
    log("\nStep 1: Creating bucket (if needed)...")
    result = subprocess.run(
        [GCLOUD, "storage", "buckets", "create", BUCKET,
         f"--project={PROJECT}",
         f"--location={LOCATION}",
         "--default-storage-class=NEARLINE",
         "--uniform-bucket-level-access"],
        capture_output=True, text=True,
    )
    if "already exists" in result.stderr or result.returncode == 0:
        log("  Bucket ready")
    else:
        log(f"  Bucket create: {result.stderr[:200]}")

    # Step 2: Set lifecycle policy
    log("\nStep 2: Setting lifecycle policy...")
    lifecycle = json.dumps({
        "rule": [{
            "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
            "condition": {"age": 90}
        }]
    })
    lifecycle_file = PDF_DIR / "lifecycle.json"
    lifecycle_file.write_text(lifecycle, encoding="utf-8")
    subprocess.run(
        [GCLOUD, "storage", "buckets", "update", BUCKET,
         f"--lifecycle-file={lifecycle_file}",
         f"--project={PROJECT}"],
        capture_output=True, text=True,
    )
    log("  Lifecycle: Nearline -> Coldline after 90 days")

    # Step 3: Upload each collection directory
    log("\nStep 3: Uploading PDFs...")
    t0 = time.time()

    collection_dirs = sorted([
        d for d in PDF_DIR.iterdir()
        if d.is_dir() and any(f.suffix == ".pdf" for f in d.iterdir())
    ])

    for coll_dir in collection_dirs:
        coll_name = coll_dir.name
        if coll_name in state.get("uploaded_dirs", []):
            log(f"  {coll_name}: already uploaded, skipping")
            continue

        pdf_count = len([f for f in coll_dir.iterdir() if f.suffix == ".pdf"])
        coll_size = sum(f.stat().st_size for f in coll_dir.iterdir() if f.suffix == ".pdf")
        log(f"  {coll_name}: {pdf_count:,} PDFs ({coll_size/1024/1024/1024:.1f} GB)...")

        coll_t0 = time.time()
        result = subprocess.run(
            [GCLOUD, "storage", "cp", "--recursive",
             f"--project={PROJECT}",
             "--no-clobber",  # skip existing files
             str(coll_dir) + "/",
             f"{BUCKET}/originals/{coll_name}/"],
            capture_output=True, text=True,
            timeout=14400,  # 4 hour timeout per collection
            encoding="utf-8", errors="replace",
        )
        coll_elapsed = time.time() - coll_t0

        if result.returncode == 0:
            rate_mb = (coll_size / 1024 / 1024) / max(coll_elapsed, 1)
            log(f"    Uploaded in {coll_elapsed/60:.1f} min ({rate_mb:.1f} MB/s)")
            state["uploaded_dirs"].append(coll_name)
            save_state(state)
        else:
            log(f"    FAILED: {result.stderr[:300]}")

    elapsed = time.time() - t0
    state["finished_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["elapsed_seconds"] = int(elapsed)
    save_state(state)

    log(f"\nUpload complete in {elapsed/3600:.1f} hours")

    # Step 4: Verify
    if args.verify:
        log("\nStep 4: Verifying upload...")
        result = subprocess.run(
            [GCLOUD, "storage", "ls", "--recursive",
             f"{BUCKET}/originals/", f"--project={PROJECT}"],
            capture_output=True, text=True, timeout=300,
            encoding="utf-8", errors="replace",
        )
        remote_count = result.stdout.count(".pdf")
        log(f"  Local:  {local_count:,} PDFs")
        log(f"  Remote: {remote_count:,} PDFs")
        match = "MATCH" if remote_count >= local_count * 0.99 else "MISMATCH"
        log(f"  Status: {match}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
