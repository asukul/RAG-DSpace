"""
Master autonomous pipeline — runs after PDF download completes.

Stages:
  1. Validate all downloaded PDFs
  2. Finish nomic-embed-text embedding (catch newly downloaded)
  3. Run next models: mxbai-embed-large, bge-m3, snowflake-arctic-embed2
  4. Deploy to GCP
  5. Upload PDFs to GCS (Nearline storage, cost-effective)

Usage:
    python scripts/master_pipeline.py
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PDF_DIR = BACKEND / "data" / "pdfs"
STATE_DIR = BACKEND / "data" / "embed_state"
PROJECT_ROOT = BACKEND.parent

MODELS_QUEUE = [
    {"name": "nomic-embed-text", "collection": "dspace_fulltext_nomic", "suffix": "nomic", "dims": 768},
    {"name": "mxbai-embed-large", "collection": "dspace_fulltext_mxbai", "suffix": "mxbai", "dims": 1024},
    {"name": "bge-m3", "collection": "dspace_fulltext_bge_m3", "suffix": "bge_m3", "dims": 1024},
    {"name": "snowflake-arctic-embed2", "collection": "dspace_fulltext_arctic2", "suffix": "arctic2", "dims": 1024},
]


def log(msg):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def run_cmd(cmd, timeout=None):
    """Run a command and return (returncode, stdout)."""
    log(f"  CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           cwd=str(BACKEND), encoding="utf-8", errors="replace")
    if result.returncode != 0:
        log(f"  STDERR: {result.stderr[:500]}")
    return result.returncode, result.stdout


def count_pdfs():
    count = 0
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                count += 1
    return count


def wait_for_download():
    """Wait until PDF download is complete."""
    dl_state = PDF_DIR / "download_state.json"
    while True:
        if dl_state.exists():
            try:
                s = json.loads(dl_state.read_text(encoding="utf-8"))
                stats = s.get("stats", {})
                if stats.get("finished_at"):
                    log(f"  Download complete: {len(s.get('downloaded',{})):,} PDFs")
                    return True
                downloaded = len(s.get("downloaded", {}))
                log(f"  Download in progress: {downloaded:,} PDFs...")
            except Exception:
                pass
        time.sleep(300)  # check every 5 min


def validate_pdfs():
    """Validate all downloaded PDFs."""
    log("=" * 60)
    log("Stage 1: Validating PDFs")
    log("=" * 60)

    total = 0
    valid = 0
    corrupt = 0
    corrupt_files = []

    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if not f.endswith(".pdf"):
                continue
            total += 1
            fpath = os.path.join(dirpath, f)
            try:
                size = os.path.getsize(fpath)
                if size < 100:
                    corrupt += 1
                    corrupt_files.append(fpath)
                    continue
                with open(fpath, "rb") as fh:
                    header = fh.read(5)
                if header[:4] != b"%PDF":
                    corrupt += 1
                    corrupt_files.append(fpath)
                    continue
                valid += 1
            except Exception:
                corrupt += 1

    log(f"  Total:   {total:,}")
    log(f"  Valid:   {valid:,} ({100*valid/max(total,1):.1f}%)")
    log(f"  Corrupt: {corrupt:,}")

    # Save validation results
    results = {
        "total": total, "valid": valid, "corrupt": corrupt,
        "corrupt_files": corrupt_files[:100],
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    (STATE_DIR / "pdf_validation.json").write_text(
        json.dumps(results, indent=2), encoding="utf-8"
    )
    return valid


def run_embedding(model_info):
    """Run embedding for one model."""
    name = model_info["name"]
    collection = model_info["collection"]
    suffix = model_info["suffix"]

    log("=" * 60)
    log(f"Embedding: {name} -> {collection}")
    log("=" * 60)

    state_file = STATE_DIR / f"embed_state_{suffix}.json"

    # Check if already complete
    if state_file.exists():
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            done = len(s.get("processed_uuids", []))
            total_pdfs = count_pdfs()
            if done >= total_pdfs * 0.95:  # 95% threshold
                log(f"  Already {done:,}/{total_pdfs:,} done — skipping")
                return True
        except Exception:
            pass

    # Run embedding
    cmd = [
        sys.executable, str(BACKEND / "scripts" / "embed_pdfs_ollama.py"),
        "--model", name,
        "--collection", collection,
        "--batch-size", "64",
        "--workers", "32",
        "--resume",
    ]
    env = os.environ.copy()
    env["OLLAMA_NUM_PARALLEL"] = "8"

    log(f"  Starting {name} with 32 workers...")
    proc = subprocess.Popen(
        cmd, cwd=str(BACKEND), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        encoding="utf-8", errors="replace",
    )

    # Monitor until done
    while proc.poll() is None:
        time.sleep(60)  # check every minute
        if state_file.exists():
            try:
                s = json.loads(state_file.read_text(encoding="utf-8"))
                done = len(s.get("processed_uuids", []))
                pts = s.get("total_points", 0)
                err = s.get("errors", 0)
                log(f"  {name}: {done:,} PDFs, {pts:,} points, {err} errors")
            except Exception:
                pass

    rc = proc.returncode
    log(f"  {name} finished with exit code {rc}")

    # Final stats
    if state_file.exists():
        s = json.loads(state_file.read_text(encoding="utf-8"))
        log(f"  Final: {len(s.get('processed_uuids',[])):,} PDFs, "
            f"{s.get('total_points',0):,} points, {s.get('errors',0)} errors")

    return rc == 0


def deploy_gcp():
    """Deploy to GCP Cloud Run."""
    log("=" * 60)
    log("Deploying to GCP")
    log("=" * 60)

    jwt_file = PROJECT_ROOT / ".jwt_secret_local"
    if not jwt_file.exists():
        log("  ERROR: .jwt_secret_local not found")
        return False

    jwt_secret = jwt_file.read_text().strip()
    client_id = "623732207442-k8uq085k1vjaqs1c9eaug66bcan97saj.apps.googleusercontent.com"

    cmd = [
        "gcloud", "builds", "submit",
        "--config=cloudbuild.yaml",
        "--project=rag-dspace",
        f"--substitutions=_GOOGLE_OAUTH_CLIENT_ID={client_id},"
        f"_JWT_SECRET={jwt_secret},"
        f"_DEFAULT_ADMIN_EMAIL=adisak.sukul@gmail.com",
        "--gcs-source-staging-dir=gs://rag-dspace_cloudbuild/source",
        ".",
    ]

    result = subprocess.run(
        cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True,
        timeout=600, encoding="utf-8", errors="replace",
    )

    if result.returncode == 0:
        log("  Deploy SUCCESS")
    else:
        log(f"  Deploy FAILED: {result.stderr[:300]}")

    return result.returncode == 0


def upload_to_gcs():
    """Upload PDFs to GCS using Nearline storage class (cost-effective)."""
    log("=" * 60)
    log("Uploading PDFs to GCS (Nearline storage)")
    log("=" * 60)

    bucket = "gs://rag-dspace-pdfs"

    # Create bucket with Nearline storage class if it doesn't exist
    log("  Creating bucket (if needed)...")
    subprocess.run(
        ["gcloud", "storage", "buckets", "create", bucket,
         "--project=rag-dspace",
         "--location=us-central1",
         "--default-storage-class=NEARLINE",
         "--uniform-bucket-level-access"],
        capture_output=True, text=True,
    )

    # Upload with parallel composite uploads for speed
    log("  Uploading PDFs (parallel, resumable)...")

    # Upload each collection directory
    for collection_dir in sorted(PDF_DIR.iterdir()):
        if not collection_dir.is_dir():
            continue

        pdf_count = len([f for f in collection_dir.iterdir() if f.suffix == ".pdf"])
        if pdf_count == 0:
            continue

        log(f"  Uploading {collection_dir.name}/ ({pdf_count:,} PDFs)...")
        result = subprocess.run(
            ["gcloud", "storage", "cp", "--recursive",
             "--project=rag-dspace",
             str(collection_dir),
             f"{bucket}/originals/"],
            capture_output=True, text=True, timeout=7200,
            encoding="utf-8", errors="replace",
        )

        if result.returncode == 0:
            log(f"    {collection_dir.name}: uploaded")
        else:
            log(f"    {collection_dir.name}: FAILED — {result.stderr[:200]}")

    # Set lifecycle policy: move to Coldline after 90 days
    lifecycle = {
        "rule": [{
            "action": {"type": "SetStorageClass", "storageClass": "COLDLINE"},
            "condition": {"age": 90}
        }]
    }
    lifecycle_file = PDF_DIR / "lifecycle.json"
    lifecycle_file.write_text(json.dumps(lifecycle), encoding="utf-8")

    subprocess.run(
        ["gcloud", "storage", "buckets", "update", bucket,
         f"--lifecycle-file={lifecycle_file}",
         "--project=rag-dspace"],
        capture_output=True, text=True,
    )
    log("  Lifecycle policy set: Nearline -> Coldline after 90 days")

    return True


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    STATE_DIR.mkdir(parents=True, exist_ok=True)

    log("=" * 60)
    log("MASTER PIPELINE — Autonomous Execution")
    log("=" * 60)

    # Wait for download to finish
    log("\nWaiting for PDF download to complete...")
    wait_for_download()

    # Stage 1: Validate
    valid_count = validate_pdfs()

    # Stage 2-5: Embed with each model
    for model_info in MODELS_QUEUE:
        success = run_embedding(model_info)
        if not success:
            log(f"  WARNING: {model_info['name']} had issues, continuing...")

    # Stage 6: Deploy
    deploy_gcp()

    # Stage 7: Upload to GCS
    upload_to_gcs()

    log("\n" + "=" * 60)
    log("MASTER PIPELINE COMPLETE")
    log("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
