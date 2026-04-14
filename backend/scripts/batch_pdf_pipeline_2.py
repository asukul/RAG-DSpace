"""Batch 2 PDF download + chunk pipeline."""
import os, sys, json, time, traceback
from pathlib import Path

# Java setup
JDK_ROOT = Path.home() / ".jdk"
jdks = sorted(JDK_ROOT.glob("jdk-*"), reverse=True)
if jdks:
    java_home = str(jdks[0])
    os.environ["JAVA_HOME"] = java_home
    os.environ["PATH"] = str(Path(java_home) / "bin") + os.pathsep + os.environ.get("PATH", "")

import httpx
import opendataloader_pdf

BATCH_ID = 2
SCRATCH = Path(f"C:/temp/isu-rag-scratch/batch_{BATCH_ID}")
PDF_DIR = SCRATCH / "pdfs"
EXTRACT_DIR = SCRATCH / "extracted"
STATUS_FILE = SCRATCH / "status.json"
CHUNKS_OUT = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend/data/document_chunks")
INDEX_FILE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend/data/indexed_documents.json")

PDF_DIR.mkdir(parents=True, exist_ok=True)
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
CHUNKS_OUT.mkdir(parents=True, exist_ok=True)

LIKELY_PDF_TYPES = {"thesis", "Thesis", "dissertation", "creative component", "article", "Article"}
API = "https://dr.lib.iastate.edu/server/api/core"
MAX_BYTES = 50_000_000


def load_slice():
    docs = json.load(open(INDEX_FILE, encoding="utf-8"))
    filtered = [d for d in docs if d.get("type") in LIKELY_PDF_TYPES]
    mine = [d for i, d in enumerate(filtered) if i % 4 == 2]
    return mine


def find_pdf_bitstream(client, uuid):
    r = client.get(f"{API}/items/{uuid}/bundles")
    r.raise_for_status()
    bundles = r.json().get("_embedded", {}).get("bundles", [])
    for b in bundles:
        if b.get("name") not in ("ORIGINAL", "CONTENT"):
            continue
        bid = b["uuid"]
        r2 = client.get(f"{API}/bundles/{bid}/bitstreams")
        r2.raise_for_status()
        bss = r2.json().get("_embedded", {}).get("bitstreams", [])
        for bs in bss:
            mime = (bs.get("mimeType") or "").lower()
            name = (bs.get("name") or "").lower()
            if "pdf" in mime or name.endswith(".pdf"):
                return bs
    return None


def download_pdf(client, bs, dest):
    size = bs.get("sizeBytes") or 0
    if size > MAX_BYTES:
        return "too_large"
    bs_uuid = bs["uuid"]
    r = client.get(f"{API}/bitstreams/{bs_uuid}/content")
    r.raise_for_status()
    dest.write_bytes(r.content)
    return "ok"


def chunk_by_headings(json_path, max_chunk_chars=2000):
    with open(json_path, "r", encoding="utf-8") as f:
        doc = json.load(f)
    chunks = []
    current = {"heading": "", "page": 1, "text": "", "element_count": 0}

    def flush():
        nonlocal current
        if current["text"].strip():
            chunks.append({**current, "text": current["text"].strip()})
        current = {"heading": current["heading"], "page": current["page"], "text": "", "element_count": 0}

    def walk(node):
        nonlocal current
        if not isinstance(node, dict):
            return
        ntype = node.get("type", "")
        text = node.get("text", "") or node.get("content", "")
        page = node.get("page number", current["page"])
        if ntype == "heading":
            flush()
            current["heading"] = text
            current["page"] = page
        elif text:
            if len(current["text"]) + len(text) > max_chunk_chars:
                flush()
            current["text"] += text + "\n"
            current["page"] = page
            current["element_count"] += 1
        for child in node.get("kids", []):
            walk(child)

    for child in doc.get("kids", []):
        walk(child)
    flush()
    return chunks


def process_doc(client, doc, stats):
    uuid = doc["uuid"]
    chunks_path = CHUNKS_OUT / f"{uuid}.json"
    if chunks_path.exists():
        stats["already_done"] += 1
        return

    pdf_path = PDF_DIR / f"{uuid}.pdf"
    try:
        bs = find_pdf_bitstream(client, uuid)
    except Exception as e:
        stats["download_error"] += 1
        stats["errors"].append({"uuid": uuid, "stage": "find", "err": str(e)[:200]})
        return
    if not bs:
        stats["no_pdf"] += 1
        return

    try:
        result = download_pdf(client, bs, pdf_path)
    except Exception as e:
        stats["download_error"] += 1
        stats["errors"].append({"uuid": uuid, "stage": "download", "err": str(e)[:200]})
        return
    if result == "too_large":
        stats["too_large"] += 1
        return

    out_dir = EXTRACT_DIR / uuid
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        opendataloader_pdf.convert(
            input_path=str(pdf_path),
            output_dir=str(out_dir),
            format="json",
            quiet=True,
            reading_order="xycut",
            table_method="cluster",
        )
    except Exception as e:
        stats["extract_error"] += 1
        stats["errors"].append({"uuid": uuid, "stage": "extract", "err": str(e)[:200]})
        try: pdf_path.unlink()
        except: pass
        return

    json_file = out_dir / f"{uuid}.json"
    if not json_file.exists():
        # opendataloader sometimes nests
        cands = list(out_dir.rglob(f"{uuid}.json"))
        if cands:
            json_file = cands[0]
    if not json_file.exists():
        stats["extract_error"] += 1
        stats["errors"].append({"uuid": uuid, "stage": "extract", "err": "no json output"})
        try: pdf_path.unlink()
        except: pass
        return

    try:
        chunks = chunk_by_headings(str(json_file))
    except Exception as e:
        stats["chunk_error"] += 1
        stats["errors"].append({"uuid": uuid, "stage": "chunk", "err": str(e)[:200]})
        try: pdf_path.unlink()
        except: pass
        return

    with open(chunks_path, "w", encoding="utf-8") as f:
        json.dump(chunks, f, ensure_ascii=False, indent=2)
    stats["success"] += 1
    stats["sample_chunks"].append({
        "uuid": uuid,
        "n_chunks": len(chunks),
        "first_heading": chunks[0]["heading"] if chunks else "",
        "first_text": (chunks[0]["text"][:100] if chunks else ""),
    })

    try: pdf_path.unlink()
    except: pass


def main():
    t0 = time.time()
    docs = load_slice()
    print(f"Slice size: {len(docs)}")
    stats = {
        "total": len(docs), "success": 0, "already_done": 0,
        "no_pdf": 0, "too_large": 0, "download_error": 0,
        "extract_error": 0, "chunk_error": 0,
        "errors": [], "sample_chunks": [],
    }
    test_only = "--test" in sys.argv

    with httpx.Client(timeout=30.0, follow_redirects=True, headers={"User-Agent": "isu-rag-batch2/1.0"}) as client:
        for i, doc in enumerate(docs):
            if test_only and i >= 1:
                break
            try:
                process_doc(client, doc, stats)
            except Exception as e:
                stats["errors"].append({"uuid": doc.get("uuid"), "stage": "outer", "err": str(e)[:200]})
                traceback.print_exc()
            if (i + 1) % 10 == 0:
                stats["elapsed"] = round(time.time() - t0, 1)
                stats["progress"] = i + 1
                STATUS_FILE.write_text(json.dumps(stats, indent=2))
                print(f"[{i+1}/{len(docs)}] success={stats['success']} no_pdf={stats['no_pdf']} too_large={stats['too_large']} dl_err={stats['download_error']} ex_err={stats['extract_error']}")

    stats["elapsed"] = round(time.time() - t0, 1)
    STATUS_FILE.write_text(json.dumps(stats, indent=2))
    print(json.dumps({k: v for k, v in stats.items() if k not in ("errors",)}, indent=2))


if __name__ == "__main__":
    main()
