"""
LLM-assisted semantic chunking using Claude Opus 4.6.

Instead of naive fixed-size word chunks, uses Claude to:
1. Identify semantic sections (Abstract, Introduction, Methods, Results, etc.)
2. Create meaningful chunks at natural boundaries
3. Add section labels and context to each chunk
4. Generate a brief summary per chunk for enhanced retrieval

This produces higher-quality chunks for RAG comparison experiments.

Chunking strategies compared:
  A) Naive: fixed 500-word chunks with 100-word overlap (baseline)
  B) Claude Semantic: LLM identifies section boundaries + summarizes
  C) Claude Enhanced: LLM rewrites each chunk with context for retrieval

Usage:
    python scripts/chunk_with_claude.py --sample 100 --strategy semantic
    python scripts/chunk_with_claude.py --sample 50 --strategy enhanced
    python scripts/chunk_with_claude.py --sample 200 --strategy all
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sqlite3
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import concurrent.futures

import anthropic
from pdfminer.high_level import extract_text

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
OUTPUT_DIR = BACKEND / "data" / "dspace" / "claude_chunks"

MODEL = "claude-opus-4-6"


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
        return text if len(text) >= 200 else ""
    except Exception:
        return ""


def naive_chunk(text: str, chunk_size: int = 500, overlap: int = 100) -> list[dict]:
    """Strategy A: Naive fixed-size chunking."""
    words = text.split()
    if len(words) <= chunk_size:
        return [{"text": text, "section": "full", "strategy": "naive"}] if len(words) > 30 else []
    chunks = []
    start = 0
    idx = 0
    while start < len(words):
        end = start + chunk_size
        chunk_text = " ".join(words[start:end])
        if len(chunk_text.split()) > 30:
            chunks.append({
                "text": chunk_text,
                "section": f"chunk_{idx}",
                "strategy": "naive",
                "chunk_idx": idx,
            })
            idx += 1
        start += chunk_size - overlap
    return chunks


def claude_semantic_chunk(client: anthropic.Anthropic, text: str, title: str = "") -> list[dict]:
    """Strategy B: Claude identifies semantic sections and creates chunks."""
    # Truncate to ~6000 words to fit in context
    words = text.split()
    if len(words) > 6000:
        text = " ".join(words[:6000])

    prompt = f"""You are analyzing an academic paper for a retrieval-augmented generation (RAG) system.

Paper title: {title}

Text:
{text}

Task: Split this paper into semantically meaningful chunks for retrieval. Each chunk should:
1. Cover one coherent topic or section
2. Be 200-800 words long
3. Be self-contained enough to answer a question about its topic
4. Have a descriptive section label

Return a JSON array where each element has:
- "section": section name (e.g., "Abstract", "Introduction", "Methods - Data Collection", "Results - Model Performance", etc.)
- "text": the chunk text (verbatim from the paper, 200-800 words)
- "summary": a 1-2 sentence summary of what this chunk covers (for enhanced retrieval)

Return ONLY valid JSON, no markdown or explanation."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()

        # Parse JSON (handle markdown code blocks)
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        chunks = json.loads(content)
        for c in chunks:
            c["strategy"] = "claude_semantic"
        return chunks
    except Exception as e:
        log(f"    Claude semantic error: {e}")
        return []


def claude_enhanced_chunk(client: anthropic.Anthropic, text: str, title: str = "") -> list[dict]:
    """Strategy C: Claude creates retrieval-optimized chunks with context."""
    words = text.split()
    if len(words) > 6000:
        text = " ".join(words[:6000])

    prompt = f"""You are preparing an academic paper for a semantic search system.

Paper title: {title}

Text:
{text}

Task: Create retrieval-optimized chunks. For each chunk:
1. Include the paper title and section context at the start
2. Rewrite slightly to be self-contained (a reader should understand it without the rest of the paper)
3. Keep the factual content accurate — don't add information not in the paper
4. Each chunk should be 200-600 words
5. Optimize for someone searching for specific facts, methods, or results

Return a JSON array where each element has:
- "section": descriptive section name
- "text": the retrieval-optimized chunk text
- "summary": a search-query-style summary (what question does this chunk answer?)
- "keywords": list of 3-5 key terms for this chunk

Return ONLY valid JSON, no markdown or explanation."""

    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.content[0].text.strip()
        if content.startswith("```"):
            content = re.sub(r"^```\w*\n?", "", content)
            content = re.sub(r"\n?```$", "", content)

        chunks = json.loads(content)
        for c in chunks:
            c["strategy"] = "claude_enhanced"
        return chunks
    except Exception as e:
        log(f"    Claude enhanced error: {e}")
        return []


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=100,
                        help="Number of PDFs to process")
    parser.add_argument("--strategy", default="all",
                        choices=["naive", "semantic", "enhanced", "all"])
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Initialize Claude client
    client = anthropic.Anthropic()  # uses ANTHROPIC_API_KEY env var
    log(f"Claude client initialized (model: {MODEL})")

    # Collect PDFs
    pdf_files = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                pdf_files.append((f.replace(".pdf", ""), os.path.join(dirpath, f)))

    log(f"Found {len(pdf_files):,} PDFs")

    # Sample
    random.seed(args.seed)
    sample = random.sample(pdf_files, min(args.sample, len(pdf_files)))
    log(f"Sampled {len(sample)} PDFs")

    # Load metadata
    conn = sqlite3.connect(INDEX_DB)
    conn.row_factory = sqlite3.Row

    # Process each PDF
    results = {
        "config": {
            "sample_size": len(sample),
            "strategy": args.strategy,
            "model": MODEL,
            "seed": args.seed,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "documents": [],
    }

    strategies = []
    if args.strategy in ("naive", "all"):
        strategies.append("naive")
    if args.strategy in ("semantic", "all"):
        strategies.append("semantic")
    if args.strategy in ("enhanced", "all"):
        strategies.append("enhanced")

    t0 = time.time()
    processed = 0
    total_chunks = {"naive": 0, "semantic": 0, "enhanced": 0}
    errors = 0

    for uid, pdf_path in sample:
        processed += 1
        text = extract_pdf_text(pdf_path)
        if not text:
            errors += 1
            continue

        # Get metadata
        row = conn.execute(
            "SELECT title, year, type, department FROM items WHERE uuid = ?",
            (uid,),
        ).fetchone()
        title = row["title"] if row else ""

        doc_result = {
            "uuid": uid,
            "title": title,
            "year": row["year"] if row else "",
            "type": row["type"] if row else "",
            "text_length": len(text.split()),
            "chunks": {},
        }

        log(f"  [{processed}/{len(sample)}] {title[:60]}...")

        # Strategy A: Naive
        if "naive" in strategies:
            naive = naive_chunk(text)
            doc_result["chunks"]["naive"] = naive
            total_chunks["naive"] += len(naive)

        # Strategy B: Claude Semantic
        if "semantic" in strategies:
            semantic = claude_semantic_chunk(client, text, title)
            doc_result["chunks"]["semantic"] = semantic
            total_chunks["semantic"] += len(semantic)
            time.sleep(0.5)  # rate limit politeness

        # Strategy C: Claude Enhanced
        if "enhanced" in strategies:
            enhanced = claude_enhanced_chunk(client, text, title)
            doc_result["chunks"]["enhanced"] = enhanced
            total_chunks["enhanced"] += len(enhanced)
            time.sleep(0.5)

        results["documents"].append(doc_result)

        if processed % 10 == 0:
            elapsed = time.time() - t0
            log(f"  Progress: {processed}/{len(sample)} | "
                f"Chunks: naive={total_chunks['naive']} semantic={total_chunks['semantic']} "
                f"enhanced={total_chunks['enhanced']} | {elapsed/60:.1f} min")

    conn.close()
    elapsed = time.time() - t0

    # Save results
    results["stats"] = {
        "processed": processed,
        "errors": errors,
        "total_chunks": total_chunks,
        "elapsed_seconds": int(elapsed),
        "avg_chunks_per_doc": {
            k: round(v / max(processed - errors, 1), 1)
            for k, v in total_chunks.items()
        },
    }

    out_file = OUTPUT_DIR / f"claude_chunks_{args.strategy}_{len(sample)}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    log(f"\n{'='*60}")
    log(f"Claude Chunking Complete")
    log(f"  PDFs processed: {processed - errors}")
    log(f"  Errors:         {errors}")
    log(f"  Duration:       {elapsed/60:.1f} min")
    log(f"  Chunks:")
    for strategy, count in total_chunks.items():
        if count > 0:
            avg = count / max(processed - errors, 1)
            log(f"    {strategy:12s}: {count:,} total ({avg:.1f} per doc)")
    log(f"  Output: {out_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
