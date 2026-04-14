"""
Rebuild bm25_vocab_vertex.json from FULL chunk text instead of content_prefix.

Root cause from 2026-04-13: the earlier hybrid-ingest script built the BM25
vocab from `chunk_hash_index.jsonl`'s `content_prefix` field (first 200 chars
of each chunk). Author names and affiliations usually live past char 200 in
academic papers (the title block comes first, then author list, then
affiliations, then abstract). Result: "adisak" had token_id=None in the vocab
and "sukul" had doc_freq=1 — effectively invisible to BM25 retrieval.

Name queries like "Adisak Sukul" therefore returned zero BM25 hits, the
system fell back to pure dense retrieval, dense pulled semantically-noisy
papers, and the LLM hallucinated Sukul into chemistry papers he never wrote.

This script walks the Vertex output files (where every point's full chunk
text lives in `instance.content`) and builds a proper full-text BM25 vocab.
It ALSO walks chunk_hash_index once to get the title + metadata for each
chunk (via content_hash lookup), so the indexed text is title + full content
instead of title + prefix.

After running this, re-run `embed_vertex_hybrid_ingest.py --skip-vocab` which
will read the new vocab and re-upsert the sparse vectors using it.

Usage:
    python backend/scripts/rebuild_bm25_vocab_fulltext.py
    python backend/scripts/rebuild_bm25_vocab_fulltext.py --limit 50000
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
CHUNK_HASH_INDEX = BACKEND / "data" / "dspace" / "chunk_hash_index.jsonl"
VERTEX_OUT_PARTS = [
    BACKEND / "data" / "dspace" / "vertex_batch_output_part0",
    BACKEND / "data" / "dspace" / "vertex_batch_output_part1",
]
VOCAB_FILE = BACKEND / "data" / "bm25_vocab_vertex.json"

BM25_K1 = 1.5
BM25_B = 0.75
STOP_WORDS = {
    "a", "an", "the", "and", "or", "but", "if", "while", "with", "of", "to",
    "in", "on", "at", "by", "for", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can", "this",
    "that", "these", "those", "it", "its", "i", "you", "he", "she", "we", "they",
    "them", "their", "his", "her", "our", "your", "my", "me", "us",
}
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def tokenize(text: str) -> List[str]:
    if not text:
        return []
    out = []
    for tok in TOKEN_RE.findall(text):
        t = tok.lower()
        if len(t) < 3 or t in STOP_WORDS:
            continue
        out.append(t)
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None,
                        help="Max chunks to process (smoke test)")
    args = parser.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # First, build a title map: content_hash -> title (from the metadata index)
    log("Loading title map from chunk_hash_index.jsonl...")
    hash_to_title: Dict[bytes, str] = {}
    with open(CHUNK_HASH_INDEX, encoding="utf-8") as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            h = rec.get("content_hash")
            if not h:
                continue
            hash_to_title[bytes.fromhex(h)] = rec.get("title") or ""
    log(f"  loaded {len(hash_to_title):,} title entries")

    # Walk Vertex output files and compute DF over title + full content
    log("Walking Vertex output files for full-text DF...")
    df_counter: Counter = Counter()
    n_docs = 0
    total_len = 0
    seen_hashes: set = set()

    for part_idx, part_dir in enumerate(VERTEX_OUT_PARTS):
        if not part_dir.exists():
            log(f"  [part {part_idx}] missing {part_dir} — skipping")
            continue
        files = sorted(part_dir.glob("*.jsonl"))
        log(f"[part {part_idx}] {len(files)} output files")
        for out_file in files:
            with open(out_file, encoding="utf-8") as f:
                for line in f:
                    if args.limit and n_docs >= args.limit:
                        break
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    instance = d.get("instance", {})
                    chunk_text = instance.get("content", "")
                    if not chunk_text:
                        continue

                    h = hashlib.sha1(chunk_text.encode("utf-8")).digest()
                    if h in seen_hashes:
                        continue
                    seen_hashes.add(h)

                    title = hash_to_title.get(h, "")
                    merged = f"{title} {chunk_text}"
                    toks = tokenize(merged)
                    if not toks:
                        continue
                    for t in set(toks):
                        df_counter[t] += 1
                    n_docs += 1
                    total_len += len(toks)
                    if n_docs % 100_000 == 0:
                        log(f"  scanned {n_docs:,} chunks, vocab={len(df_counter):,}")
            if args.limit and n_docs >= args.limit:
                break
        if args.limit and n_docs >= args.limit:
            break

    avgdl = total_len / max(n_docs, 1)
    log(f"Done scanning: {n_docs:,} docs, vocab={len(df_counter):,}, avgdl={avgdl:.1f}")

    # Sanity check: verify that important name tokens are now in the vocab
    log("Sanity check — name token frequencies:")
    for tok in ["sukul", "adisak", "tavanapong", "aluru", "rajan", "cai", "wong",
                "chaudhuri", "curcumin", "petrich"]:
        d = df_counter.get(tok, 0)
        log(f"  {tok}: df={d}")

    # Sort by df desc → stable token_id (most common gets smallest id)
    token_to_id: Dict[str, int] = {}
    for i, (tok, _df) in enumerate(df_counter.most_common()):
        token_to_id[tok] = i

    # Save the new vocab
    log(f"Writing vocab to {VOCAB_FILE}...")
    tmp = VOCAB_FILE.with_suffix(VOCAB_FILE.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        json.dump({
            "n_docs": n_docs,
            "avgdl": avgdl,
            "k1": BM25_K1,
            "b": BM25_B,
            "df": dict(df_counter),
            "token_to_id": token_to_id,
            "collection": "dspace_fulltext_vertex",
            "source": "fulltext (instance.content from Vertex output)",
        }, f)
    tmp.replace(VOCAB_FILE)
    log(f"  wrote {VOCAB_FILE.stat().st_size / 1024 / 1024:.1f} MB")

    return 0


if __name__ == "__main__":
    sys.exit(main())
