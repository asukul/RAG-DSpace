"""Batch 0/24 PDF download + opendataloader-pdf chunking pipeline."""
import os
import sys
import json
import time
from pathlib import Path

# --- Java setup BEFORE importing opendataloader_pdf ---
jdk_root = Path.home() / ".jdk"
jdks = sorted(jdk_root.glob("jdk-*"), reverse=True)
if not jdks:
    print("ERROR: no JDK found under ~/.jdk", file=sys.stderr)
    sys.exit(1)
java_home = str(jdks[0]).replace("\\", "/")
os.environ["JAVA_HOME"] = java_home
os.environ["PATH"] = str(Path(java_home) / "bin") + os.pathsep + os.environ.get("PATH", "")
print(f"[setup] JAVA_HOME={java_home}")

import httpx
import opendataloader_pdf
print(f"[setup] opendataloader_pdf imported OK")

BACKEND = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
INDEX_PATH = BACKEND / "data" / "indexed_documents.json"
CHUNKS_DIR = BACKEND / "data" / "document_chunks"
SCRATCH = Path("C:/temp/isu-rag-scratch/batch_0_24")
PDF_DIR = SCRATCH / "pdfs"
EXTRACT_DIR = SCRATCH / "extracted"
STATUS_PATH = SCRATCH / "status.json"

CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
PDF_DIR.mkdir(parents=True, exist_ok=True)
EXTRACT_DIR.mkdir(parents=True, exist_ok=True)

TYPES_OK = {"thesis", "Thesis", "dissertation", "creative component", "article", "Article"}
API = "https://dr.lib.iastate.edu/server/api/core"
MAX_BYTES = 50_000_000


def chunk_by_headings(json_path: str, max_chunk_chars: int = 2000):
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


def download_pdf(client: httpx.Client, uuid: str) -> tuple[str, Path | None]:
    """Returns (status, path). status in {ok, no_pdf, too_large, download_error}."""
    try:
        r = client.get(f"{API}/items/{uuid}/bundles")
        r.raise_for_status()
        bundles = r.json().get("_embedded", {}).get("bundles", [])
    except Exception as e:
        print(f"  bundles error: {e}")
        return ("download_error", None)

    target_bundles = [b for b in bundles if b.get("name") in ("ORIGINAL", "CONTENT")]
    if not target_bundles:
        return ("no_pdf", None)

    for bundle in target_bundles:
        buuid = bundle.get("uuid")
        try:
            r = client.get(f"{API}/bundles/{buuid}/bitstreams")
            r.raise_for_status()
            bitstreams = r.json().get("_embedded", {}).get("bitstreams", [])
        except Exception as e:
            print(f"  bitstreams error: {e}")
            continue

        for bs in bitstreams:
            name = (bs.get("name") or "").lower()
            mime = ""
            fmt = bs.get("_embedded", {}).get("format") or {}
            if isinstance(fmt, dict):
                mime = (fmt.get("mimetype") or "").lower()
            is_pdf = "pdf" in mime or name.endswith(".pdf")
            if not is_pdf:
                continue
            size = bs.get("sizeBytes", 0) or 0
            if size > MAX_BYTES:
                return ("too_large", None)
            bsuuid = bs.get("uuid")
            try:
                pdf_path = PDF_DIR / f"{uuid}.pdf"
                with client.stream("GET", f"{API}/bitstreams/{bsuuid}/content") as resp:
                    resp.raise_for_status()
                    with open(pdf_path, "wb") as f:
                        for chunk in resp.iter_bytes():
                            f.write(chunk)
                return ("ok", pdf_path)
            except Exception as e:
                print(f"  download error: {e}")
                return ("download_error", None)

    return ("no_pdf", None)


def extract_and_chunk(uuid: str, pdf_path: Path) -> tuple[str, list | None]:
    outdir = EXTRACT_DIR / uuid
    outdir.mkdir(parents=True, exist_ok=True)
    try:
        opendataloader_pdf.convert(
            input_path=str(pdf_path),
            output_dir=str(outdir),
            format="json",
            quiet=True,
            reading_order="xycut",
            table_method="cluster",
        )
    except Exception as e:
        print(f"  extract error: {e}")
        return ("extract_error", None)

    # Find the JSON the tool produced
    json_files = list(outdir.rglob("*.json"))
    if not json_files:
        return ("extract_error", None)
    # Prefer stem match
    preferred = [j for j in json_files if j.stem == pdf_path.stem]
    json_file = preferred[0] if preferred else json_files[0]
    try:
        chunks = chunk_by_headings(str(json_file))
    except Exception as e:
        print(f"  chunk error: {e}")
        return ("extract_error", None)
    return ("ok", chunks)


def main():
    t0 = time.time()
    with open(INDEX_PATH, "r", encoding="utf-8") as f:
        docs = json.load(f)
    print(f"[load] {len(docs)} total docs")

    filtered = [d for d in docs if d.get("type") in TYPES_OK]
    print(f"[filter] {len(filtered)} after type filter")

    slice_docs = [d for i, d in enumerate(filtered) if i % 24 == 0]
    print(f"[slice] {len(slice_docs)} in batch_0_24")

    stats = {
        "total": len(slice_docs),
        "success": 0,
        "skipped_existing": 0,
        "no_pdf": 0,
        "too_large": 0,
        "download_error": 0,
        "extract_error": 0,
        "per_doc": [],
    }

    def save_status():
        with open(STATUS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=2)

    with httpx.Client(timeout=30.0, follow_redirects=True,
                      headers={"User-Agent": "isu-rag-ingest/0.1", "Accept": "application/json"}) as client:
        for i, doc in enumerate(slice_docs):
            uuid = doc["uuid"]
            chunks_path = CHUNKS_DIR / f"{uuid}.json"
            print(f"[{i+1}/{len(slice_docs)}] {uuid} ({doc.get('type')})")
            if chunks_path.exists():
                stats["skipped_existing"] += 1
                print("  skipped (exists)")
                stats["per_doc"].append({"uuid": uuid, "status": "skipped_existing"})
                if (i + 1) % 5 == 0:
                    save_status()
                continue

            dl_status, pdf_path = download_pdf(client, uuid)
            if dl_status != "ok":
                stats[dl_status] += 1
                stats["per_doc"].append({"uuid": uuid, "status": dl_status})
                if (i + 1) % 5 == 0:
                    save_status()
                continue

            ex_status, chunks = extract_and_chunk(uuid, pdf_path)
            if ex_status != "ok":
                stats["extract_error"] += 1
                stats["per_doc"].append({"uuid": uuid, "status": "extract_error"})
                try:
                    pdf_path.unlink()
                except Exception:
                    pass
                if (i + 1) % 5 == 0:
                    save_status()
                continue

            with open(chunks_path, "w", encoding="utf-8") as f:
                json.dump(chunks, f, indent=2, ensure_ascii=False)
            stats["success"] += 1
            stats["per_doc"].append({"uuid": uuid, "status": "success", "chunks": len(chunks)})
            print(f"  success: {len(chunks)} chunks")
            try:
                pdf_path.unlink()
            except Exception:
                pass
            if (i + 1) % 5 == 0:
                save_status()

    stats["wall_time_s"] = round(time.time() - t0, 1)
    save_status()

    print("\n=== RESULT ===")
    for k in ("total", "success", "skipped_existing", "no_pdf", "too_large", "download_error", "extract_error", "wall_time_s"):
        print(f"{k}: {stats[k]}")


if __name__ == "__main__":
    main()
