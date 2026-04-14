"""Simple launcher for worker_embed_v2.py — no rewriting of worker script."""
import json, os, sys, subprocess, time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
PDF_DIR = BACKEND / "data" / "pdfs"
STATE_DIR = BACKEND / "data" / "embed_state"
WORKER = BACKEND / "scripts" / "worker_embed_v2.py"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import argparse
p = argparse.ArgumentParser()
p.add_argument("--processes", type=int, default=8)
p.add_argument("--model", default="nomic-embed-text")
p.add_argument("--collection", default=None)
p.add_argument("--qdrant-url", default="http://localhost:6334")
p.add_argument("--batch-size", type=int, default=32)
args = p.parse_args()

MODEL_DIMS = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "bge-m3": 1024,
    "snowflake-arctic-embed2": 1024,
}
SUFFIX = {
    "nomic-embed-text": "nomic",
    "mxbai-embed-large": "mxbai",
    "bge-m3": "bge_m3",
    "snowflake-arctic-embed2": "arctic2",
}

suffix = SUFFIX.get(args.model, "custom")
collection = args.collection or f"dspace_fulltext_{suffix}"
dims = MODEL_DIMS.get(args.model, 768)

# Get PDFs and filter out processed
all_pdfs = []
for dirpath, _, filenames in os.walk(PDF_DIR):
    for f in filenames:
        if f.endswith(".pdf"):
            all_pdfs.append(f.replace(".pdf", ""))

state_file = STATE_DIR / f"embed_state_{suffix}.json"
processed = set()
if state_file.exists():
    with open(state_file, encoding="utf-8") as f:
        s = json.load(f)
    processed = set(s.get("processed_uuids", []))

remaining = [uid for uid in all_pdfs if uid not in processed]
log(f"Total: {len(all_pdfs):,}, processed: {len(processed):,}, remaining: {len(remaining):,}")

if not remaining:
    log("Nothing to do")
    sys.exit(0)

# Split into slices
chunk_size = len(remaining) // args.processes + 1
slice_dir = STATE_DIR / "slices"
slice_dir.mkdir(parents=True, exist_ok=True)

procs = []
env = os.environ.copy()
env["PYTHONUNBUFFERED"] = "1"

for i in range(args.processes):
    slice_data = remaining[i * chunk_size:(i + 1) * chunk_size]
    if not slice_data:
        break
    slice_file = slice_dir / f"slice_{suffix}_{i}.json"
    slice_file.write_text(json.dumps(slice_data), encoding="utf-8")

    proc = subprocess.Popen(
        [
            sys.executable, "-u", str(WORKER),
            str(slice_file), args.model, collection, args.qdrant_url,
            str(args.batch_size), str(dims), str(i),
        ],
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    procs.append((i, proc, len(slice_data)))
    log(f"  Worker {i}: PID {proc.pid}, {len(slice_data):,} PDFs")

log(f"\nAll {len(procs)} workers launched. Streaming output...\n")

# Stream output from all workers
import select
import io

while True:
    all_done = True
    for i, p, _ in procs:
        if p.poll() is None:
            all_done = False
        # Read any available lines (non-blocking)
        try:
            line = p.stdout.readline()
            if line:
                print(f"  {line.rstrip()}", flush=True)
        except:
            pass
    if all_done:
        break
    time.sleep(0.5)

log("All workers finished")
