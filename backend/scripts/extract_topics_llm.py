"""
Phase 4 — LLM topic extraction for DSpace papers.

For each paper in dspace_index.db with an abstract, ask Gemini 2.5 Flash Lite
to extract:
  - topics:    high-level subject categories
  - methods:   methodology used
  - datasets:  named datasets if mentioned

Output:
  backend/data/llm_topics.jsonl

Idempotent + resumable: skips uuids already present in the output file.

Run:
    python backend/scripts/extract_topics_llm.py
    python backend/scripts/extract_topics_llm.py --limit 50
    python backend/scripts/extract_topics_llm.py --workers 8
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, Set

from google import genai
from google.genai import types as gen_types

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DSPACE_INDEX = BACKEND / "data" / "dspace" / "dspace_index.db"
OUT = BACKEND / "data" / "llm_topics.jsonl"

GCP_PROJECT = os.environ.get("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.environ.get("GCP_LOCATION", "us-central1")
MODEL = os.environ.get("GEMINI_GEN_MODEL", "gemini-2.5-flash-lite")

PROMPT_TEMPLATE = """You are an academic research librarian indexing a paper.
Read the title and abstract below and return a JSON object with three fields:

  topics:   3-7 high-level academic subject areas this paper belongs to.
            Use natural-language phrases like "machine learning",
            "polymer chemistry", "agricultural economics", "veterinary
            pathology". Lowercase. Plural OK.
  methods:  0-5 specific techniques, algorithms, or methodologies used.
  datasets: 0-3 named public datasets mentioned, if any.

If a field has no obvious entries, return an empty list. Be concise. Do not invent.

PAPER TITLE: {title}

ABSTRACT:
{abstract}
"""


def already_done_uuids(path: Path) -> Set[str]:
    """Returns uuids that have a successful (non-error) extraction recorded."""
    seen: Set[str] = set()
    if not path.exists():
        return seen
    with path.open(encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                u = d.get("uuid")
                if u and "error" not in d:
                    seen.add(u)
            except Exception:
                continue
    return seen


def compact_output(path: Path) -> int:
    """
    Drop error rows from the output file. Keeps the file lean and lets resume
    re-process anything that previously failed.
    Returns the number of dropped rows.
    """
    if not path.exists():
        return 0
    tmp = path.with_suffix(".jsonl.tmp")
    dropped = 0
    with path.open(encoding="utf-8", errors="replace") as fin, tmp.open("w", encoding="utf-8") as fout:
        for line in fin:
            line_s = line.strip()
            if not line_s:
                continue
            try:
                d = json.loads(line_s)
            except Exception:
                continue
            if "error" in d:
                dropped += 1
                continue
            fout.write(line)
    tmp.replace(path)
    return dropped


def iter_papers(limit: int = 0) -> Iterable[Dict[str, Any]]:
    src = sqlite3.connect(f"file:{DSPACE_INDEX}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    cur = src.execute(
        """
        SELECT uuid, title, abstract
        FROM items
        WHERE abstract IS NOT NULL AND abstract != ''
        """
    )
    n = 0
    for row in cur:
        yield {
            "uuid": row["uuid"],
            "title": row["title"] or "",
            "abstract": (row["abstract"] or "")[:3000],
        }
        n += 1
        if limit and n >= limit:
            break
    src.close()


def extract_one(client, item):
    """One Gemini call with exponential backoff on 429 / 5xx errors."""
    prompt = PROMPT_TEMPLATE.format(title=item["title"], abstract=item["abstract"])
    cfg = gen_types.GenerateContentConfig(
        temperature=0.1,
        max_output_tokens=400,
        response_mime_type="application/json",
        response_schema={
            "type": "OBJECT",
            "properties": {
                "topics":   {"type": "ARRAY", "items": {"type": "STRING"}},
                "methods":  {"type": "ARRAY", "items": {"type": "STRING"}},
                "datasets": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["topics", "methods", "datasets"],
        },
    )
    last_err = None
    for attempt in range(5):
        try:
            resp = client.models.generate_content(model=MODEL, contents=prompt, config=cfg)
            text = (getattr(resp, "text", "") or "").strip()
            try:
                data = json.loads(text)
            except json.JSONDecodeError:
                return {"uuid": item["uuid"], "error": "json_parse", "raw": text[:500]}
            return {
                "uuid": item["uuid"],
                "topics":   [t.strip().lower() for t in (data.get("topics") or []) if t and t.strip()],
                "methods":  [t.strip().lower() for t in (data.get("methods") or []) if t and t.strip()],
                "datasets": [t.strip()         for t in (data.get("datasets") or []) if t and t.strip()],
                "model": MODEL,
            }
        except Exception as e:
            last_err = str(e)
            msg = last_err.lower()
            # Backoff on rate-limit / transient
            if "429" in msg or "resource_exhausted" in msg or "503" in msg or "504" in msg or "deadline" in msg:
                time.sleep(min(2 ** attempt, 30) + (attempt * 0.5))
                continue
            # Permanent error — give up
            return {"uuid": item["uuid"], "error": last_err[:300]}
    return {"uuid": item["uuid"], "error": (last_err or "exhausted retries")[:300]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--workers", type=int, default=6)
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    dropped = compact_output(out_path)
    if dropped:
        print(f"Compacted output: removed {dropped} previous error rows")
    done = already_done_uuids(out_path)
    print(f"Resuming: {len(done)} papers already processed (success only)")

    client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)
    print(f"Vertex client ready (project={GCP_PROJECT}, model={MODEL})")
    print()

    total_processed = 0
    n_topics = 0
    n_errors = 0
    t0 = time.time()

    work_iter = (p for p in iter_papers(args.limit) if p["uuid"] not in done)
    fout = out_path.open("a", encoding="utf-8")

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        in_flight = []
        BATCH = max(args.workers * 4, 24)
        for _ in range(BATCH):
            try:
                item = next(work_iter)
            except StopIteration:
                break
            in_flight.append(pool.submit(extract_one, client, item))

        while in_flight:
            done_fut = next(as_completed(in_flight))
            in_flight.remove(done_fut)
            result = done_fut.result()
            fout.write(json.dumps(result, ensure_ascii=False) + "\n")
            fout.flush()
            total_processed += 1
            if "error" in result:
                n_errors += 1
            else:
                n_topics += len(result.get("topics", []))
            try:
                item = next(work_iter)
                in_flight.append(pool.submit(extract_one, client, item))
            except StopIteration:
                pass

            if total_processed % 50 == 0:
                elapsed = time.time() - t0
                rate = total_processed / max(elapsed, 0.01)
                print(
                    f"  processed={total_processed}  topics={n_topics}  "
                    f"errors={n_errors}  rate={rate:.1f}/s",
                    flush=True,
                )

    fout.close()
    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print(f"Done. processed={total_processed} in {elapsed/60:.1f} min")
    print(f"  total topics extracted: {n_topics}")
    print(f"  errors: {n_errors}")
    print(f"  output: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
