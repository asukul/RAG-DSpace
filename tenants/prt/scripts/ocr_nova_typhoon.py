"""Typhoon-OCR a manifest of PDFs against an Ollama server (built for ISU Nova).

Nova-side port of ocr_prt_typhoon.py. Key points learned the hard way (2026-05-22):
  - Force ollama's cuda_v12 runner on Nova (driver 13.0 auto-picks cuda_v13, which is
    BROKEN for vision -> degenerate output). Done at the env level (cuda_v13 moved aside).
  - In the Slurm job: `unset CUDA_VISIBLE_DEVICES` (Slurm sets it to 0, breaking ollama
    GPU discovery; cgroup already isolates the GPU).
  - Use typhoon-ocr's NATIVE prompt (below). The model is fine-tuned to expect it; any
    other prompt makes it echo the template instead of OCRing.
  - Set num_ctx per request (avoids the 256k auto-context CUDA VMM-pool SIGABRT).

Input is a manifest CSV (doc_id,pdf_path[,...]); with --pdf-base, PDFs are looked up as
<pdf-base>/<doc_id>.pdf. Output goes to <out-dir>/<shard>/<doc_id>.txt. Skip-guard makes
the job resumable. By default the typhoon Markdown is flattened to plain text to match the
existing PRT corpus; pass --keep-markdown to retain tables/page-numbers/structure.

Usage (inside the Slurm job, after ollama serve is up):
    OLLAMA_HOST=127.0.0.1:PORT python ocr_nova_typhoon.py \
        --manifest queue.csv --pdf-base /ptmp/.../pdfs --out-dir /ptmp/.../papers_text_typhoon \
        --parallel 8
"""
from __future__ import annotations

import argparse
import base64
import concurrent.futures
import csv
import json
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://127.0.0.1:11434")
if not OLLAMA_HOST.startswith("http"):
    OLLAMA_HOST = "http://" + OLLAMA_HOST
MODEL = os.getenv("OLLAMA_MODEL", "scb10x/typhoon-ocr1.5-3b")
PNG_DPI_SCALE = 2.0
MAX_PAGES_PER_DOC = 6
NUM_PREDICT = 1200          # native prompt can be verbose on dense pages; headroom vs 500
NUM_CTX = 16384             # cap context: avoids the 256k auto-context VMM-pool crash
PER_PAGE_TIMEOUT_S = 180
KEEP_ALIVE = "2h"

# typhoon-ocr1.5's NATIVE prompt — the model is fine-tuned to expect exactly this. Any
# other prompt makes it echo this template (and skip OCR) on sparse/cover pages.
PROMPT = (
    "Extract all text from the image.\n\n"
    "Instructions:\n"
    "- Only return the clean Markdown.\n"
    "- Do not include any explanation or extra text.\n"
    "- You must include all information on the page.\n\n"
    "Formatting Rules:\n"
    "- Tables: Render tables using <table>...</table> in clean HTML format.\n"
    "- Equations: Render equations using LaTeX syntax with inline ($...$) and block ($$...$$).\n"
    "- Page Numbers: Wrap page numbers in <page_number>...</page_number>.\n"
    "- Checkboxes: Use ☐ for unchecked and ☑ for checked boxes."
)

_FIGURE_BLOCK_RE = re.compile(r"<figure>.*?</figure>\s*", re.DOTALL | re.IGNORECASE)
_FIGURE_OPEN_UNCLOSED_RE = re.compile(r"<figure>[^<]*$", re.DOTALL | re.IGNORECASE)

_LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    with _LOG_LOCK:
        print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def shard_for(doc_id: str) -> str:
    return doc_id[-2:] if len(doc_id) >= 2 else "00"


def strip_figure_captions(text: str) -> str:
    text = _FIGURE_BLOCK_RE.sub("", text)
    text = _FIGURE_OPEN_UNCLOSED_RE.sub("", text)
    return text.strip()


_VISION_TOK_RE = re.compile(r"<\|[a-zA-Z_]+\|>")
_EXTRACT_LOOP_RE = re.compile(
    r"(?:Extract(?:\s+all)?(?:\s+text)?(?:\s+from\s+the\s+image)?\.?\s*){2,}", re.I)


def strip_degenerate(text: str) -> str:
    """Strip the degenerate output typhoon emits on near-blank/emblem/cover pages:
    looping <|vision_end|> tokens and repeated 'Extract all text from the image'
    fragments. A purely-degenerate page becomes empty (a blank cover page — fine)."""
    text = _VISION_TOK_RE.sub("", text)
    text = _EXTRACT_LOOP_RE.sub("", text)
    # also strip a lone echo of the instruction phrase (never valid Thai OCR)
    text = re.sub(r"Extract all text from the image\.?", "", text, flags=re.I)
    return text.strip()


def flatten_markdown(text: str) -> str:
    """Flatten typhoon's Markdown to plain text to match the existing plain-text corpus.
    Keeps every word; drops structural tags. Table cells become space/newline-separated."""
    text = re.sub(r"</?(?:table|thead|tbody|tr)\b[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"</?(?:td|th)\b[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<page_number>\s*(.*?)\s*</page_number>", r"\1", text, flags=re.I | re.S)
    text = re.sub(r"</?[a-zA-Z][^>]*>", "", text)            # any remaining html-ish tags
    text = text.replace("$$", "").replace("$", "")            # latex delimiters
    text = re.sub(r"(?m)^\s{0,3}#{1,6}\s+", "", text)         # markdown headings
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text, flags=re.S)  # bold
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def render_pdf_pages(pdf_path: Path, max_pages: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        log(f"  fitz.open FAILED {pdf_path.name}: {e}")
        return []
    try:
        for i in range(min(len(doc), max_pages)):
            try:
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(PNG_DPI_SCALE, PNG_DPI_SCALE))
                p = out_dir / f"page-{i+1:03d}.png"
                pix.save(str(p))
                paths.append(p)
            except Exception as e:
                log(f"  render FAILED page {i+1} of {pdf_path.name}: {e}")
                continue
    finally:
        doc.close()
    return paths


def ocr_one_page(img_path: Path) -> Optional[str]:
    t0 = time.time()
    try:
        with img_path.open("rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        payload = json.dumps({
            "model": MODEL, "prompt": PROMPT, "images": [b64], "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": {"temperature": 0.0, "num_predict": NUM_PREDICT, "num_ctx": NUM_CTX},
        }).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/generate", data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=PER_PAGE_TIMEOUT_S) as r:
            d = json.loads(r.read())
        return (d.get("response") or "").strip()
    except Exception as e:
        log(f"  ollama page FAILED {img_path.parent.name}/{img_path.name} after {time.time()-t0:.1f}s: {e}")
        return None


def ocr_one_doc(doc_id: str, pdf_path: Path, out_dir: Path, keep_markdown: bool) -> dict:
    out_path = out_dir / shard_for(doc_id) / f"{doc_id}.txt"
    if out_path.exists() and out_path.stat().st_size >= 30:
        return {"status": "skip_done"}
    if not pdf_path.exists():
        return {"status": "failed_no_pdf"}
    t0 = time.time()
    import tempfile
    with tempfile.TemporaryDirectory(prefix=f"nvtyph-{doc_id}-") as td:
        pages = render_pdf_pages(pdf_path, MAX_PAGES_PER_DOC, Path(td))
        if not pages:
            return {"status": "failed_render", "elapsed_s": round(time.time() - t0, 1)}
        page_texts = []
        n_ok = 0
        for p in pages:
            txt = ocr_one_page(p)
            if txt is None:
                page_texts.append("[ocr error]")
            else:
                n_ok += 1
                t = strip_degenerate(strip_figure_captions(txt))
                if not keep_markdown:
                    t = flatten_markdown(t)
                page_texts.append(t)
        if n_ok == 0:
            return {"status": "failed_all_pages", "pages": len(pages), "elapsed_s": round(time.time() - t0, 1)}
        text = "\n---PAGE-BREAK---\n".join(page_texts).strip()
    if len(text) < 30:
        return {"status": "failed_too_short", "chars": len(text), "elapsed_s": round(time.time() - t0, 1)}
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return {"status": "ok", "chars": len(text), "pages": len(pages), "elapsed_s": round(time.time() - t0, 1)}


def load_manifest(path: Path, pdf_base: Optional[Path]) -> list[tuple[str, Path]]:
    rows = []
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            did = (row.get("doc_id") or "").strip()
            pp = (row.get("pdf_path") or "").strip()
            if not did or not pp:
                continue
            # With --pdf-base, PDFs were staged renamed to <doc_id>.pdf under it.
            p = (pdf_base / f"{did}.pdf") if pdf_base else Path(pp)
            rows.append((did, p))
    return rows


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--pdf-base", type=Path, default=None,
                    help="If set, PDFs are looked up as <pdf-base>/<doc_id>.pdf")
    ap.add_argument("--parallel", type=int, default=8)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--keep-markdown", action="store_true",
                    help="Keep typhoon's Markdown (tables/page-numbers); default flattens to plain text")
    ap.add_argument("--shard-index", type=int, default=0, help="this task's 0-based shard id")
    ap.add_argument("--shard-count", type=int, default=1, help="total shards (Slurm-array parallelism)")
    args = ap.parse_args()

    docs = load_manifest(args.manifest, args.pdf_base)
    if args.shard_count > 1:
        docs = [d for i, d in enumerate(docs) if i % args.shard_count == args.shard_index]
    if args.max:
        docs = docs[: args.max]
    log("=== Nova Typhoon OCR ===")
    log(f"  ollama   : {OLLAMA_HOST}  model={MODEL}")
    log(f"  manifest : {args.manifest}  ({len(docs):,} docs)")
    log(f"  pdf-base : {args.pdf_base}")
    log(f"  out-dir  : {args.out_dir}")
    log(f"  parallel : {args.parallel}   keep_markdown={args.keep_markdown}   shard={args.shard_index}/{args.shard_count}")

    t_start = time.time()
    ok = failed = skipped = no_pdf = 0
    done = 0
    total = len(docs)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
        futs = {ex.submit(ocr_one_doc, did, pdf, args.out_dir, args.keep_markdown): did for did, pdf in docs}
        for fut in concurrent.futures.as_completed(futs):
            did = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                res = {"status": "failed_call", "err": str(e)[:160]}
            st = res.get("status")
            if st == "ok": ok += 1
            elif st == "skip_done": skipped += 1
            elif st == "failed_no_pdf": no_pdf += 1
            else: failed += 1
            done += 1
            if done % 25 == 0 or done <= 5:
                el = time.time() - t_start
                log(f"  {done:,}/{total:,}  ok={ok:,} skip={skipped:,} fail={failed:,} no_pdf={no_pdf:,}  ({ok/el if el>0 else 0:.2f} ok/s)")
    el = time.time() - t_start
    log(f"DONE — ok={ok:,} skip={skipped:,} fail={failed:,} no_pdf={no_pdf:,} in {el/60:.1f} min ({ok/el if el>0 else 0:.2f} ok/s)")


if __name__ == "__main__":
    main()
