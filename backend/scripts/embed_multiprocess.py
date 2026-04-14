"""
Multi-PROCESS PDF embedding — bypasses Python GIL.

Spawns N independent Python processes, each handling a slice of PDFs.
Each process does its own: extraction -> chunking -> Ollama embedding -> Qdrant upsert.

This truly uses N CPU cores since each process has its own GIL.

Usage:
    python scripts/embed_multiprocess.py --processes 16 --model nomic-embed-text
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
STATE_DIR = BACKEND / "data" / "embed_state"
EMBED_SCRIPT = BACKEND / "scripts" / "embed_pdfs_ollama.py"


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_all_pdfs():
    """Get all PDF UUIDs."""
    pdfs = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                pdfs.append(f.replace(".pdf", ""))
    return pdfs


def get_processed(suffix):
    """Get already-processed UUIDs from state file."""
    state_file = STATE_DIR / f"embed_state_{suffix}.json"
    if state_file.exists():
        try:
            s = json.loads(state_file.read_text(encoding="utf-8"))
            return set(s.get("processed_uuids", []))
        except:
            pass
    return set()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--processes", type=int, default=16,
                        help="Number of parallel Python processes")
    parser.add_argument("--model", default="nomic-embed-text")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--qdrant-url", default="http://localhost:6334")
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    MODEL_CONFIGS = {
        "nomic-embed-text": "nomic",
        "mxbai-embed-large": "mxbai",
        "bge-m3": "bge_m3",
        "snowflake-arctic-embed2": "arctic2",
    }
    suffix = MODEL_CONFIGS.get(args.model, "custom")
    collection = args.collection or f"dspace_fulltext_{suffix}"

    # Get remaining PDFs
    all_pdfs = get_all_pdfs()
    processed = get_processed(suffix)
    remaining = [uid for uid in all_pdfs if uid not in processed]

    log(f"Multi-Process Embedding Launcher")
    log(f"  Model:      {args.model}")
    log(f"  Collection: {collection}")
    log(f"  Qdrant:     {args.qdrant_url}")
    log(f"  Total PDFs: {len(all_pdfs):,}")
    log(f"  Processed:  {len(processed):,}")
    log(f"  Remaining:  {len(remaining):,}")
    log(f"  Processes:  {args.processes}")

    if not remaining:
        log("Nothing to process!")
        return 0

    # Split remaining PDFs into N chunks
    chunk_size = len(remaining) // args.processes + 1
    slices = []
    for i in range(0, len(remaining), chunk_size):
        slices.append(remaining[i:i + chunk_size])

    log(f"  Slices:     {len(slices)} x ~{chunk_size:,} PDFs each")

    # Write slice files for each process
    slice_dir = STATE_DIR / "slices"
    slice_dir.mkdir(parents=True, exist_ok=True)

    for i, s in enumerate(slices):
        slice_file = slice_dir / f"slice_{suffix}_{i}.json"
        slice_file.write_text(json.dumps(s), encoding="utf-8")

    # Use the v2 worker script (fixed version)
    v2_script = BACKEND / "scripts" / "worker_embed_v2.py"
    if v2_script.exists():
        worker_script = v2_script
        log(f"  Using worker_embed_v2.py")
    else:
        worker_script = STATE_DIR / "worker_embed.py"
        worker_script.write_text(f'''
import json, sys, os, re, time, uuid as uuid_mod, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
from pdfminer.high_level import extract_text
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
import concurrent.futures

BACKEND = r"{BACKEND}"
PDF_DIR = os.path.join(BACKEND, "data", "pdfs")
INDEX_DB = os.path.join(BACKEND, "data", "dspace", "dspace_index.db")
OLLAMA_URL = "http://localhost:11434"

slice_file = sys.argv[1]
model = sys.argv[2]
collection = sys.argv[3]
qdrant_url = sys.argv[4]
batch_size = int(sys.argv[5])
dims = int(sys.argv[6])
worker_id = sys.argv[7]

uuids = json.loads(open(slice_file, encoding="utf-8").read())
print(f"[Worker {{worker_id}}] Processing {{len(uuids)}} PDFs", flush=True)

def extract_pdf(path, max_pages=30):
    try:
        if os.path.getsize(path) > 50*1024*1024: return ""
        def _e(): return extract_text(path, maxpages=max_pages)
        with concurrent.futures.ThreadPoolExecutor(1) as ex:
            text = ex.submit(_e).result(timeout=30)
        text = re.sub(r"\\s+", " ", text).strip()
        return text if len(text) >= 50 else ""
    except: return ""

def chunk(text, size=500, overlap=100):
    words = text.split()
    if len(words) <= size: return [text] if len(words) > 30 else []
    chunks, start = [], 0
    while start < len(words):
        c = " ".join(words[start:start+size])
        if len(c.split()) > 30: chunks.append(c)
        start += size - overlap
    return chunks

def embed(texts):
    safe = [t[:8000] for t in texts]
    r = requests.post(f"{{OLLAMA_URL}}/api/embed", json={{"model": model, "input": safe}}, timeout=300)
    r.raise_for_status()
    return r.json().get("embeddings", [])

# Connect
qc = QdrantClient(url=qdrant_url, timeout=60)
try: qc.get_collection(collection)
except: qc.create_collection(collection_name=collection, vectors_config=qm.VectorParams(size=dims, distance=qm.Distance.COSINE))

conn = sqlite3.connect(INDEX_DB)
conn.row_factory = sqlite3.Row

# Find PDF files
pdf_map = {{}}
for dp, _, fns in os.walk(PDF_DIR):
    for fn in fns:
        if fn.endswith(".pdf"):
            pdf_map[fn.replace(".pdf","")] = os.path.join(dp, fn)

done = 0
pts = 0
errs = 0
t0 = time.time()

for uid in uuids:
    path = pdf_map.get(uid)
    if not path: errs += 1; continue
    text = extract_pdf(path)
    if not text: errs += 1; continue
    chunks_list = chunk(text)
    if not chunks_list: continue

    row = conn.execute("SELECT title,year,type,department,collection_name,authors_json FROM items WHERE uuid=?", (uid,)).fetchone()
    meta = {{"uuid": uid}}
    if row:
        meta.update({{"title": row["title"] or "", "year": row["year"] or "", "type": row["type"] or "", "department": row["department"] or "", "collection": row["collection_name"] or ""}})
        try: meta["authors"] = json.loads(row["authors_json"] or "[]")[:5]
        except: meta["authors"] = []

    points = []
    for cb in range(0, len(chunks_list), batch_size):
        batch = chunks_list[cb:cb+batch_size]
        try:
            embs = embed(batch)
            for i, emb in enumerate(embs):
                if len(emb) > dims: emb = emb[:dims]
                points.append(qm.PointStruct(id=str(uuid_mod.uuid4()), vector=emb,
                    payload={{**meta, "chunk_idx": cb+i, "chunk_total": len(chunks_list), "text_preview": batch[i][:200]}}))
        except: errs += 1; break

    if points:
        try:
            for i in range(0, len(points), 100):
                qc.upsert(collection_name=collection, points=points[i:i+100])
            pts += len(points)
        except: errs += 1

    done += 1
    if done % 200 == 0:
        elapsed = time.time() - t0
        print(f"[Worker {{worker_id}}] {{done}}/{{len(uuids)}} | {{pts}} pts | {{errs}} err | {{done/elapsed:.1f}}/s", flush=True)

conn.close()
elapsed = time.time() - t0
print(f"[Worker {{worker_id}}] DONE: {{done}} PDFs, {{pts}} pts, {{errs}} err, {{elapsed/60:.1f}} min", flush=True)

# Save worker state
state = {{"worker_id": worker_id, "processed": uuids[:done], "points": pts, "errors": errs, "elapsed": int(elapsed)}}
open(os.path.join(r"{STATE_DIR}", f"worker_{{worker_id}}_done.json"), "w").write(json.dumps(state))
''', encoding="utf-8")

    # Launch N processes
    log(f"\nLaunching {len(slices)} worker processes...")
    dims = {"nomic-embed-text": 768, "mxbai-embed-large": 1024, "bge-m3": 1024, "snowflake-arctic-embed2": 1024}.get(args.model, 768)

    procs = []
    env = os.environ.copy()
    env["OLLAMA_NUM_PARALLEL"] = str(min(args.processes, 16))

    for i, s in enumerate(slices):
        slice_file = slice_dir / f"slice_{suffix}_{i}.json"
        p = subprocess.Popen(
            [sys.executable, str(worker_script),
             str(slice_file), args.model, collection, args.qdrant_url,
             str(args.batch_size), str(dims), str(i)],
            cwd=str(BACKEND),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
        )
        procs.append((i, p))
        log(f"  Worker {i}: PID {p.pid}, {len(s):,} PDFs")

    # Monitor until all done
    log(f"\nAll {len(procs)} workers launched. Monitoring...")
    while True:
        all_done = True
        for i, p in procs:
            if p.poll() is None:
                all_done = False
                # Read any available output
                try:
                    line = p.stdout.readline()
                    if line.strip():
                        log(f"  {line.strip()}")
                except:
                    pass

        if all_done:
            break
        time.sleep(5)

    # Collect results
    log(f"\nAll workers finished. Collecting results...")
    total_pts = 0
    total_done = 0
    total_err = 0
    all_processed = []

    for i, _ in procs:
        done_file = STATE_DIR / f"worker_{i}_done.json"
        if done_file.exists():
            ws = json.loads(done_file.read_text(encoding="utf-8"))
            total_pts += ws.get("points", 0)
            total_done += len(ws.get("processed", []))
            total_err += ws.get("errors", 0)
            all_processed.extend(ws.get("processed", []))

    # Update main state file
    state_file = STATE_DIR / f"embed_state_{suffix}.json"
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
    else:
        state = {"processed_uuids": [], "total_points": 0, "errors": 0}

    existing = set(state.get("processed_uuids", []))
    existing.update(all_processed)
    state["processed_uuids"] = list(existing)
    state["total_points"] = state.get("total_points", 0) + total_pts
    state["errors"] = state.get("errors", 0) + total_err
    state["last_updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    log(f"\nResults:")
    log(f"  PDFs processed: {total_done:,}")
    log(f"  Points created: {total_pts:,}")
    log(f"  Errors:         {total_err:,}")
    log(f"  Total in state: {len(existing):,} PDFs, {state['total_points']:,} pts")

    return 0


if __name__ == "__main__":
    sys.exit(main())
