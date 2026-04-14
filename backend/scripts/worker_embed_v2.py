"""
Worker script v2 — fixes the hanging issues:
1. Shorter Qdrant timeout (10s) so hangs are detected
2. Retries on Qdrant errors instead of silent failure
3. Progress print every 10 PDFs instead of 200
4. Prefetch bulk mode via Qdrant REST API directly (bypass client hangs)
5. Smaller upsert batches (50 points)
6. Explicit flush after every log
"""
import json, sys, os, re, time, uuid as uuid_mod, sqlite3
sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
import requests
import fitz  # PyMuPDF - 10x faster than pdfminer, no hangs

BACKEND = r"D:\Dropbox\RAG-DSpace\isu-research-search\backend"
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
print(f"[W{worker_id}] Starting {len(uuids)} PDFs", flush=True)


def log(msg):
    print(f"[W{worker_id}] {msg}", flush=True)


def extract_pdf(path, max_pages=30):
    """Extract text using PyMuPDF (fitz) — fast, no hangs."""
    try:
        if os.path.getsize(path) > 50*1024*1024: return ""
        doc = fitz.open(path)
        try:
            text_parts = []
            n = min(len(doc), max_pages)
            for i in range(n):
                text_parts.append(doc[i].get_text())
            text = " ".join(text_parts)
        finally:
            doc.close()
        text = re.sub(r"\s+", " ", text).strip()
        return text if len(text) >= 50 else ""
    except Exception:
        return ""


def chunk(text, size=500, overlap=100):
    words = text.split()
    if len(words) <= size: return [text] if len(words) > 30 else []
    chunks, start = [], 0
    while start < len(words):
        c = " ".join(words[start:start+size])
        if len(c.split()) > 30: chunks.append(c)
        start += size - overlap
    return chunks


def embed(texts, max_retries=3):
    safe = [t[:8000] for t in texts]
    for attempt in range(max_retries):
        try:
            r = requests.post(
                f"{OLLAMA_URL}/api/embed",
                json={"model": model, "input": safe, "keep_alive": "24h"},
                timeout=120,
            )
            r.raise_for_status()
            return r.json().get("embeddings", [])
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)
    return []


def upsert_points(points, retry=3):
    """Upsert via direct REST API with timeout. Returns True on success."""
    url = f"{qdrant_url}/collections/{collection}/points?wait=true"
    body = {
        "points": [
            {"id": p["id"], "vector": p["vector"], "payload": p["payload"]}
            for p in points
        ]
    }
    for attempt in range(retry):
        try:
            r = requests.put(url, json=body, timeout=15)
            r.raise_for_status()
            return True
        except Exception as e:
            if attempt == retry - 1:
                log(f"  upsert FAILED: {str(e)[:100]}")
                return False
            time.sleep(1)
    return False


# Ensure collection exists
try:
    r = requests.get(f"{qdrant_url}/collections/{collection}", timeout=10)
    if r.status_code == 404:
        log("  creating collection")
        requests.put(
            f"{qdrant_url}/collections/{collection}",
            json={"vectors": {"size": dims, "distance": "Cosine"}},
            timeout=10,
        )
except Exception as e:
    log(f"  collection setup error: {e}")
    sys.exit(1)

# Build PDF path map
log("  building PDF path map...")
pdf_map = {}
for dp, _, fns in os.walk(PDF_DIR):
    for fn in fns:
        if fn.endswith(".pdf"):
            pdf_map[fn.replace(".pdf", "")] = os.path.join(dp, fn)
log(f"  {len(pdf_map):,} PDFs in filesystem")

conn = sqlite3.connect(INDEX_DB)
conn.row_factory = sqlite3.Row

done = 0
pts = 0
errs = 0
processed_uuids = []
t0 = time.time()

for uid in uuids:
    path = pdf_map.get(uid)
    if not path:
        errs += 1
        done += 1
        continue

    text = extract_pdf(path)
    if not text:
        errs += 1
        done += 1
        continue

    chunks_list = chunk(text)
    if not chunks_list:
        done += 1
        continue

    row = conn.execute(
        "SELECT title,year,type,department,collection_name,authors_json FROM items WHERE uuid=?",
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

    # Embed all chunks for this PDF
    points_for_pdf = []
    for cb in range(0, len(chunks_list), batch_size):
        batch = chunks_list[cb:cb + batch_size]
        try:
            embs = embed(batch)
            for i, emb in enumerate(embs):
                if len(emb) > dims: emb = emb[:dims]
                points_for_pdf.append({
                    "id": str(uuid_mod.uuid4()),
                    "vector": emb,
                    "payload": {
                        **meta,
                        "chunk_idx": cb + i,
                        "chunk_total": len(chunks_list),
                        "text_preview": batch[i][:200],
                    },
                })
        except Exception as e:
            errs += 1
            break

    # Upsert in smaller batches (50 points each)
    upsert_ok = True
    if points_for_pdf:
        for i in range(0, len(points_for_pdf), 50):
            if not upsert_points(points_for_pdf[i:i + 50]):
                upsert_ok = False
                break
        if upsert_ok:
            pts += len(points_for_pdf)
            processed_uuids.append(uid)
        else:
            errs += 1

    done += 1

    # Progress every 10 PDFs
    if done % 10 == 0:
        elapsed = time.time() - t0
        rate = done / max(elapsed, 0.01)
        log(f"  {done}/{len(uuids)} | {pts}pts | {errs}err | {rate:.1f}/s")

    # Save state every 50 PDFs
    if done % 50 == 0:
        state = {
            "worker_id": worker_id,
            "processed": processed_uuids,
            "points": pts,
            "errors": errs,
            "elapsed": int(time.time() - t0),
            "done": done,
        }
        with open(os.path.join(BACKEND, "data", "embed_state", f"worker_{worker_id}_progress.json"), "w") as f:
            json.dump(state, f)

conn.close()
elapsed = time.time() - t0
log(f"DONE: {done} PDFs, {pts} pts, {errs} err, {elapsed/60:.1f} min")

# Save final state
state = {
    "worker_id": worker_id,
    "processed": processed_uuids,
    "points": pts,
    "errors": errs,
    "elapsed": int(elapsed),
}
with open(os.path.join(BACKEND, "data", "embed_state", f"worker_{worker_id}_done.json"), "w") as f:
    json.dump(state, f)
