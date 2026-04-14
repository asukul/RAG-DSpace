"""
Phase 1: Benchmark embedding models on sample academic PDF chunks.

Pipeline:
  1. Extract text from sample PDFs using pdfminer
  2. Chunk text (500 tokens, 100 overlap)
  3. Run each Ollama embedding model on identical chunks
  4. Measure: throughput (chunks/sec), VRAM, embedding dimensions
  5. Compute inter-model similarity (how different are the results?)
  6. Save results for analysis

Usage:
    python scripts/benchmark_embeddings.py --sample 500 --chunks 2000
    python scripts/benchmark_embeddings.py --sample 100 --chunks 500   # quick test
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
from typing import Any

import requests
from pdfminer.high_level import extract_text

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
PDF_DIR = BACKEND / "data" / "pdfs"
INDEX_DB = BACKEND / "data" / "dspace" / "dspace_index.db"
RESULTS_DIR = BACKEND.parent / "tests" / "results"

OLLAMA_URL = "http://localhost:11434"

MODELS = [
    {"name": "nomic-embed-text", "dims": 768, "label": "nomic-768"},
    {"name": "mxbai-embed-large", "dims": 1024, "label": "mxbai-1024"},
    {"name": "snowflake-arctic-embed2", "dims": 1024, "label": "arctic2-1024"},
    {"name": "bge-m3", "dims": 1024, "label": "bge-m3-1024"},
    {"name": "qwen3-embedding:0.6b", "dims": 1024, "label": "qwen3-0.6b-1024"},
    {"name": "qwen3-embedding:4b", "dims": 1024, "label": "qwen3-4b-1024"},
    {"name": "qwen3-embedding:8b", "dims": 1024, "label": "qwen3-8b-1024"},
]

# Matryoshka dimension sweep for qwen3-embedding:4b
MATRYOSHKA_DIMS = [128, 256, 512, 1024, 2048, 4096]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_gpu_mem() -> dict:
    """Get GPU memory usage via nvidia-smi."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,memory.free",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split(",")
        return {
            "used_mb": int(parts[0].strip()),
            "total_mb": int(parts[1].strip()),
            "free_mb": int(parts[2].strip()),
        }
    except Exception:
        return {"used_mb": 0, "total_mb": 0, "free_mb": 0}


def extract_pdf_text(pdf_path: str, max_pages: int = 50) -> str:
    """Extract text from a PDF file."""
    try:
        text = extract_text(pdf_path, maxpages=max_pages)
        # Clean up
        text = re.sub(r"\s+", " ", text).strip()
        return text
    except Exception as e:
        return ""


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks by word count (~tokens)."""
    words = text.split()
    if len(words) <= chunk_size:
        return [text] if len(words) > 20 else []

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        if len(chunk.split()) > 20:  # skip tiny fragments
            chunks.append(chunk)
        start += chunk_size - overlap

    return chunks


def ollama_embed(model: str, texts: list[str], dims: int | None = None) -> tuple[list[list[float]], float]:
    """Embed texts via Ollama API. Returns (embeddings, elapsed_seconds)."""
    payload: dict[str, Any] = {"model": model, "input": texts}
    # For qwen3 models, we can request specific dimensions
    if dims and "qwen3" in model:
        payload["options"] = {"num_ctx": 4096}
        # Ollama doesn't have a native dim parameter for truncation,
        # but we can truncate Matryoshka embeddings post-hoc

    t0 = time.time()
    resp = requests.post(f"{OLLAMA_URL}/api/embed", json=payload, timeout=300)
    elapsed = time.time() - t0
    resp.raise_for_status()
    data = resp.json()
    embeddings = data.get("embeddings", [])
    return embeddings, elapsed


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def truncate_embedding(emb: list[float], target_dim: int) -> list[float]:
    """Truncate embedding to target dimensions (Matryoshka)."""
    return emb[:target_dim]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=200,
                        help="Number of PDFs to sample")
    parser.add_argument("--chunks", type=int, default=1000,
                        help="Max chunks to embed per model")
    parser.add_argument("--batch-size", type=int, default=32,
                        help="Batch size for embedding API calls")
    parser.add_argument("--chunk-size", type=int, default=500,
                        help="Words per chunk")
    parser.add_argument("--overlap", type=int, default=100,
                        help="Word overlap between chunks")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── Step 1: Collect PDF files ──────────────────────────────────────────────
    log("Step 1: Collecting PDF files...")
    pdf_files = []
    for dirpath, _, filenames in os.walk(PDF_DIR):
        for f in filenames:
            if f.endswith(".pdf"):
                pdf_files.append(os.path.join(dirpath, f))

    log(f"  Found {len(pdf_files):,} PDFs")
    if len(pdf_files) == 0:
        log("  ERROR: No PDFs found!")
        return 1

    # Sample
    sample_size = min(args.sample, len(pdf_files))
    random.seed(42)  # reproducible
    sampled = random.sample(pdf_files, sample_size)
    log(f"  Sampled {sample_size} PDFs for extraction")

    # ── Step 2: Extract text and chunk ─────────────────────────────────────────
    log("Step 2: Extracting text and chunking...")
    all_chunks = []
    extraction_stats = {"success": 0, "empty": 0, "error": 0}

    for i, pdf_path in enumerate(sampled):
        text = extract_pdf_text(pdf_path)
        if not text or len(text) < 100:
            extraction_stats["empty"] += 1
            continue

        chunks = chunk_text(text, args.chunk_size, args.overlap)
        for chunk in chunks:
            uuid = os.path.basename(pdf_path).replace(".pdf", "")
            all_chunks.append({"text": chunk, "uuid": uuid, "source": pdf_path})
        extraction_stats["success"] += 1

        if (i + 1) % 50 == 0:
            log(f"  {i+1}/{sample_size} PDFs processed, {len(all_chunks):,} chunks so far")

    log(f"  Extraction: {extraction_stats}")
    log(f"  Total chunks: {len(all_chunks):,}")

    # Cap chunks
    if len(all_chunks) > args.chunks:
        random.shuffle(all_chunks)
        all_chunks = all_chunks[:args.chunks]
        log(f"  Capped to {args.chunks} chunks for benchmarking")

    # Prepare texts
    texts = [c["text"] for c in all_chunks]
    avg_len = sum(len(t.split()) for t in texts) / len(texts)
    log(f"  Average chunk length: {avg_len:.0f} words")

    # Save chunks for reproducibility
    chunks_file = RESULTS_DIR / "benchmark_chunks.json"
    with open(chunks_file, "w", encoding="utf-8") as f:
        json.dump([{"text": c["text"][:500], "uuid": c["uuid"]} for c in all_chunks],
                  f, ensure_ascii=False)
    log(f"  Saved chunks to {chunks_file}")

    # ── Step 3: Benchmark each model ───────────────────────────────────────────
    results = []

    for model_info in MODELS:
        model_name = model_info["name"]
        model_dims = model_info["dims"]
        model_label = model_info["label"]

        log(f"\n{'='*60}")
        log(f"Benchmarking: {model_name} ({model_dims}d)")
        log(f"{'='*60}")

        # GPU baseline
        gpu_before = get_gpu_mem()

        # Warm up (load model)
        log(f"  Warming up model...")
        try:
            ollama_embed(model_name, ["warmup text for model loading"], model_dims)
        except Exception as e:
            log(f"  ERROR warming up {model_name}: {e}")
            continue

        gpu_after_load = get_gpu_mem()
        vram_model = gpu_after_load["used_mb"] - gpu_before["used_mb"]
        log(f"  VRAM after load: +{vram_model} MB (total used: {gpu_after_load['used_mb']} MB)")

        # Embed in batches
        all_embeddings = []
        total_time = 0
        batch_times = []

        for batch_start in range(0, len(texts), args.batch_size):
            batch = texts[batch_start:batch_start + args.batch_size]
            try:
                embeddings, elapsed = ollama_embed(model_name, batch, model_dims)
                all_embeddings.extend(embeddings)
                total_time += elapsed
                batch_times.append(elapsed)
            except Exception as e:
                log(f"  ERROR at batch {batch_start}: {e}")
                break

            if (batch_start + args.batch_size) % 200 == 0:
                done = min(batch_start + args.batch_size, len(texts))
                rate = done / total_time if total_time > 0 else 0
                log(f"  {done}/{len(texts)} chunks | {rate:.1f} chunks/s | "
                    f"avg batch: {sum(batch_times)/len(batch_times):.2f}s")

        if not all_embeddings:
            log(f"  SKIPPED {model_name} — no embeddings produced")
            continue

        gpu_during = get_gpu_mem()
        actual_dims = len(all_embeddings[0])
        throughput = len(all_embeddings) / total_time if total_time > 0 else 0

        log(f"  Done: {len(all_embeddings)} embeddings in {total_time:.1f}s")
        log(f"  Throughput: {throughput:.1f} chunks/sec")
        log(f"  Actual dimensions: {actual_dims}")
        log(f"  VRAM during embedding: {gpu_during['used_mb']} MB")

        # Compute self-similarity stats (how spread out are the embeddings?)
        sample_pairs = min(500, len(all_embeddings) * (len(all_embeddings) - 1) // 2)
        sims = []
        for _ in range(sample_pairs):
            i, j = random.sample(range(len(all_embeddings)), 2)
            sims.append(cosine_similarity(all_embeddings[i], all_embeddings[j]))

        avg_sim = sum(sims) / len(sims)
        min_sim = min(sims)
        max_sim = max(sims)

        result = {
            "model": model_name,
            "label": model_label,
            "dimensions": actual_dims,
            "chunks_embedded": len(all_embeddings),
            "total_time_sec": round(total_time, 2),
            "throughput_chunks_per_sec": round(throughput, 1),
            "vram_model_mb": vram_model,
            "vram_during_mb": gpu_during["used_mb"],
            "avg_pairwise_similarity": round(avg_sim, 4),
            "min_pairwise_similarity": round(min_sim, 4),
            "max_pairwise_similarity": round(max_sim, 4),
            "avg_batch_time_sec": round(sum(batch_times) / len(batch_times), 3),
            "bytes_per_point": actual_dims * 4,  # float32
        }
        results.append(result)

        # Store first 100 embeddings for cross-model comparison
        result["_sample_embeddings"] = all_embeddings[:100]

        log(f"  Avg pairwise similarity: {avg_sim:.4f} (spread: {min_sim:.4f} - {max_sim:.4f})")

    # ── Step 4: Matryoshka dimension sweep (qwen3:4b) ──────────────────────────
    log(f"\n{'='*60}")
    log(f"Matryoshka Dimension Sweep: qwen3-embedding:4b")
    log(f"{'='*60}")

    # Use existing qwen3:4b embeddings (full dims) and truncate
    qwen3_result = next((r for r in results if r["model"] == "qwen3-embedding:4b"), None)
    if qwen3_result and "_sample_embeddings" in qwen3_result:
        full_embs = qwen3_result["_sample_embeddings"]
        full_dim = len(full_embs[0])
        log(f"  Full dimensions: {full_dim}")

        matryoshka_results = []
        for target_dim in MATRYOSHKA_DIMS:
            if target_dim > full_dim:
                continue
            truncated = [truncate_embedding(e, target_dim) for e in full_embs]

            # Measure quality: cosine similarity between full and truncated
            preservation = []
            for i in range(min(50, len(full_embs))):
                for j in range(i + 1, min(50, len(full_embs))):
                    full_sim = cosine_similarity(full_embs[i], full_embs[j])
                    trunc_sim = cosine_similarity(truncated[i], truncated[j])
                    if full_sim != 0:
                        preservation.append(trunc_sim / full_sim)

            avg_preservation = sum(preservation) / len(preservation) if preservation else 0
            storage_ratio = target_dim / full_dim

            matryoshka_results.append({
                "dims": target_dim,
                "similarity_preservation": round(avg_preservation, 4),
                "storage_ratio": round(storage_ratio, 4),
                "bytes_per_point": target_dim * 4,
            })
            log(f"  {target_dim:5d}d: preservation={avg_preservation:.4f} | "
                f"storage={storage_ratio:.1%} of full | {target_dim*4} bytes/point")
    else:
        matryoshka_results = []
        log("  Skipped — qwen3:4b not available")

    # ── Step 5: Cross-model similarity ─────────────────────────────────────────
    log(f"\n{'='*60}")
    log(f"Cross-Model Similarity Analysis")
    log(f"{'='*60}")

    # For models with same dims, compare their embeddings of same chunks
    cross_model = []
    for i, r1 in enumerate(results):
        if "_sample_embeddings" not in r1:
            continue
        for j, r2 in enumerate(results):
            if j <= i or "_sample_embeddings" not in r2:
                continue
            # Use min dimensions
            min_dim = min(len(r1["_sample_embeddings"][0]), len(r2["_sample_embeddings"][0]))
            n = min(100, len(r1["_sample_embeddings"]), len(r2["_sample_embeddings"]))

            sims = []
            for k in range(n):
                e1 = r1["_sample_embeddings"][k][:min_dim]
                e2 = r2["_sample_embeddings"][k][:min_dim]
                sims.append(cosine_similarity(e1, e2))

            avg = sum(sims) / len(sims)
            cross_model.append({
                "model_a": r1["label"],
                "model_b": r2["label"],
                "avg_cosine_similarity": round(avg, 4),
                "compared_dims": min_dim,
            })
            log(f"  {r1['label']:15s} vs {r2['label']:15s}: {avg:.4f} (at {min_dim}d)")

    # ── Save results ───────────────────────────────────────────────────────────
    # Remove large embedding arrays before saving
    for r in results:
        r.pop("_sample_embeddings", None)

    output = {
        "benchmark_config": {
            "sample_pdfs": sample_size,
            "max_chunks": args.chunks,
            "chunk_size": args.chunk_size,
            "overlap": args.overlap,
            "batch_size": args.batch_size,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        },
        "extraction_stats": extraction_stats,
        "total_chunks": len(texts),
        "avg_chunk_words": round(avg_len),
        "model_results": results,
        "matryoshka_sweep": matryoshka_results,
        "cross_model_similarity": cross_model,
    }

    out_file = RESULTS_DIR / "embedding_benchmark_results.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    log(f"\nResults saved to {out_file}")

    # ── Print summary table ────────────────────────────────────────────────────
    log(f"\n{'='*80}")
    log(f"BENCHMARK SUMMARY")
    log(f"{'='*80}")
    log(f"{'Model':20s} {'Dims':>6s} {'Speed':>10s} {'VRAM':>8s} {'AvgSim':>8s} {'Bytes/pt':>10s}")
    log(f"{'-'*70}")
    for r in sorted(results, key=lambda x: -x["throughput_chunks_per_sec"]):
        log(f"  {r['label']:18s} {r['dimensions']:>6d} "
            f"{r['throughput_chunks_per_sec']:>8.1f}/s "
            f"{r['vram_during_mb']:>6d}MB "
            f"{r['avg_pairwise_similarity']:>8.4f} "
            f"{r['bytes_per_point']:>8d}B")

    return 0


if __name__ == "__main__":
    sys.exit(main())
