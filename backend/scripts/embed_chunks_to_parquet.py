"""
Embed all DSpace document chunks via Vertex AI text-embedding-005 and write
them to a single parquet file ready for bulk upsert into Qdrant.

Inputs:
  data/document_chunks/{uuid}.json — list of chunk dicts per document
  data/indexed_documents.json      — document metadata lookup

Output:
  data/chunk_embeddings.parquet           — one row per chunk (768-dim float vectors)
  data/chunk_embeddings_failed.json       — chunk_ids that failed with reasons

Resume:
  If chunk_embeddings.parquet already exists, its chunk_ids are loaded into a
  skip set so the script can be re-run safely after a partial failure.

Run:
  python scripts/embed_chunks_to_parquet.py
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pyarrow as pa
import pyarrow.parquet as pq

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"
CHUNKS_DIR = DATA_DIR / "document_chunks"
DOCS_FILE = DATA_DIR / "indexed_documents.json"
OUT_PARQUET = DATA_DIR / "chunk_embeddings.parquet"
FAILED_FILE = DATA_DIR / "chunk_embeddings_failed.json"

GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
VERTEX_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-005")
EMBED_DIM = 768

BATCH_SIZE = 25                  # inputs per Vertex request
MAX_WORKERS = 4                  # parallel batch requests
FLUSH_EVERY = 1000               # rows between parquet flushes
PROGRESS_EVERY = 1000            # progress print cadence

VERTEX_PRICE_PER_M_CHARS = 0.025  # text-embedding-005 list price (USD / 1M chars)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("embed_chunks")


# ----------------------------------------------------------------------
# Schema
# ----------------------------------------------------------------------

PARQUET_SCHEMA = pa.schema(
    [
        pa.field("chunk_id", pa.string()),
        pa.field("uuid", pa.string()),
        pa.field("chunk_idx", pa.int32()),
        pa.field("doc_title", pa.string()),
        pa.field("authors", pa.string()),
        pa.field("year", pa.string()),
        pa.field("type", pa.string()),
        pa.field("dspace_url", pa.string()),
        pa.field("heading", pa.string()),
        pa.field("page", pa.int32()),
        pa.field("text", pa.string()),
        pa.field("embedding", pa.list_(pa.float32(), EMBED_DIM)),
    ]
)


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------

def parse_year(date_str: Optional[str]) -> str:
    """Parse a 4-digit year out of a date string ('2024', '2024-08', '2024-08-15')."""
    if not date_str:
        return ""
    s = str(date_str).strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""


def build_embed_text(doc_title: str, heading: str, text: str) -> str:
    """The exact text format that gets sent to Vertex (per task spec)."""
    if heading:
        return f"{doc_title}\n\nSection: {heading}\n\n{text}"
    return f"{doc_title}\n\n{text}"


def categorize_error(exc: BaseException) -> str:
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg:
        return "quota_error"
    if (
        "503" in msg
        or "504" in msg
        or "deadline" in msg
        or "timeout" in msg
        or "connection" in msg
        or "unavailable" in msg
        or "transport" in msg
    ):
        return "transport_error"
    if "400" in msg and ("token count" in msg or "invalid_argument" in msg):
        return "token_limit_error"
    return "other_error"


# ----------------------------------------------------------------------
# Vertex client
# ----------------------------------------------------------------------

def make_client():
    from google import genai
    return genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION)


def _embed_call(client, texts: List[str]) -> List[List[float]]:
    """Single Vertex API call. Raises on error."""
    from google.genai import types as genai_types
    result = client.models.embed_content(
        model=VERTEX_MODEL,
        contents=texts,
        config=genai_types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=EMBED_DIM,
        ),
    )
    return [list(e.values) for e in result.embeddings]


def embed_batch(
    client,
    texts: List[str],
    max_attempts: int = 4,
) -> Tuple[Optional[List[List[float]]], Optional[str]]:
    """
    Embed up to BATCH_SIZE texts. Returns (embeddings, error_category).
    On success: (list_of_vectors, None). On failure: (None, category).

    Behavior:
      - Exponential backoff on quota errors (5s/10s/20s).
      - Linear backoff on transport errors.
      - Token-limit (400) errors trigger automatic batch splitting:
        the batch is recursively halved and re-submitted, so a single
        oversized batch never loses its rows.
    """
    last_err: Optional[BaseException] = None
    last_cat: Optional[str] = None

    for attempt in range(max_attempts):
        try:
            return _embed_call(client, texts), None
        except Exception as exc:
            last_err = exc
            last_cat = categorize_error(exc)

            if last_cat == "token_limit_error":
                # Split-and-retry. If the batch is already a single item and
                # still over the limit, give up — that one chunk is too big.
                if len(texts) <= 1:
                    log.error(f"single chunk exceeds token limit: {exc}")
                    return None, last_cat
                mid = len(texts) // 2
                log.warning(
                    f"token_limit_error on batch of {len(texts)} — "
                    f"splitting into {mid} + {len(texts) - mid}"
                )
                left, lcat = embed_batch(client, texts[:mid], max_attempts=max_attempts)
                right, rcat = embed_batch(client, texts[mid:], max_attempts=max_attempts)
                if left is None or right is None:
                    return None, lcat or rcat or "token_limit_error"
                return left + right, None

            if last_cat == "quota_error" and attempt < max_attempts - 1:
                wait = 5 * (2 ** attempt)  # 5s, 10s, 20s
                log.warning(f"quota_error (attempt {attempt + 1}/{max_attempts}) — sleeping {wait}s")
                time.sleep(wait)
                continue
            if last_cat == "transport_error" and attempt < max_attempts - 1:
                wait = 2 * (attempt + 1)
                log.warning(f"transport_error (attempt {attempt + 1}/{max_attempts}) — sleeping {wait}s")
                time.sleep(wait)
                continue
            break

    log.error(f"batch failed permanently ({last_cat}): {last_err}")
    return None, last_cat or "other_error"


# ----------------------------------------------------------------------
# Data loading
# ----------------------------------------------------------------------

def load_doc_lookup() -> Dict[str, Dict[str, Any]]:
    log.info(f"Loading document metadata from {DOCS_FILE}")
    with open(DOCS_FILE, "r", encoding="utf-8") as f:
        docs = json.load(f)
    lookup = {d["uuid"]: d for d in docs if d.get("uuid")}
    log.info(f"Loaded {len(lookup)} documents")
    return lookup


def load_already_embedded() -> set:
    """Return set of chunk_ids already in the parquet output (for resume)."""
    if not OUT_PARQUET.exists():
        return set()
    try:
        log.info(f"Resuming — reading existing chunk_ids from {OUT_PARQUET}")
        existing = pq.read_table(OUT_PARQUET, columns=["chunk_id"])
        ids = set(existing.column("chunk_id").to_pylist())
        log.info(f"Found {len(ids)} already-embedded chunks — they will be skipped")
        return ids
    except Exception as e:
        log.warning(f"Could not read existing parquet for resume: {e}")
        return set()


def iter_chunk_records(
    doc_lookup: Dict[str, Dict[str, Any]],
    skip_ids: set,
) -> Tuple[List[Dict[str, Any]], int, int]:
    """
    Walk all chunk JSON files. Returns (records, total_seen, total_skipped_empty).
    Each record is a dict with the row metadata + a precomputed `embed_text`.
    """
    records: List[Dict[str, Any]] = []
    total_seen = 0
    skipped_empty = 0
    skipped_no_doc = 0
    skipped_resume = 0

    chunk_files = sorted(CHUNKS_DIR.glob("*.json"))
    log.info(f"Found {len(chunk_files)} chunk files in {CHUNKS_DIR}")

    for cf in chunk_files:
        uuid = cf.stem
        try:
            with open(cf, "r", encoding="utf-8") as f:
                chunks = json.load(f)
        except Exception as e:
            log.warning(f"could not read {cf.name}: {e}")
            continue

        doc = doc_lookup.get(uuid)
        if not doc:
            skipped_no_doc += len(chunks)
            continue

        doc_title = doc.get("title") or ""
        authors_list = doc.get("authors") or []
        if isinstance(authors_list, list):
            authors_str = "; ".join(str(a) for a in authors_list if a)
        else:
            authors_str = str(authors_list)
        year = parse_year(doc.get("date"))
        doc_type = doc.get("type") or ""
        dspace_url = doc.get("url") or ""

        for idx, chunk in enumerate(chunks):
            total_seen += 1
            text = (chunk.get("text") or "").strip()
            if not text:
                skipped_empty += 1
                continue

            chunk_id = f"{uuid}#{idx}"
            if chunk_id in skip_ids:
                skipped_resume += 1
                continue

            heading = (chunk.get("heading") or "").strip()
            page_raw = chunk.get("page", 0)
            try:
                page = int(page_raw) if page_raw is not None else 0
            except (TypeError, ValueError):
                page = 0

            records.append(
                {
                    "chunk_id": chunk_id,
                    "uuid": uuid,
                    "chunk_idx": idx,
                    "doc_title": doc_title,
                    "authors": authors_str,
                    "year": year,
                    "type": doc_type,
                    "dspace_url": dspace_url,
                    "heading": heading,
                    "page": page,
                    "text": text,
                    "embed_text": build_embed_text(doc_title, heading, text),
                }
            )

    log.info(
        f"Indexed {len(records)} chunks pending embedding "
        f"(total seen={total_seen}, empty={skipped_empty}, no_doc={skipped_no_doc}, "
        f"resume_skip={skipped_resume})"
    )
    return records, total_seen, skipped_empty


# ----------------------------------------------------------------------
# Worker
# ----------------------------------------------------------------------

def worker_embed(
    client,
    batch: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]], int]:
    """
    Embed a batch of records.

    Returns:
      (successful_rows, failed_rows, char_count)
        successful_rows — same dicts with `embedding` filled in (and `embed_text` removed)
        failed_rows     — list of (chunk_id, error_category)
        char_count      — total chars sent in this batch (for cost estimation)
    """
    texts = [r["embed_text"] for r in batch]
    char_count = sum(len(t) for t in texts)

    embeddings, err_cat = embed_batch(client, texts)

    if embeddings is None:
        return [], [(r["chunk_id"], err_cat or "other_error") for r in batch], char_count

    success: List[Dict[str, Any]] = []
    for r, emb in zip(batch, embeddings):
        if not emb or len(emb) != EMBED_DIM:
            success_row = None
        else:
            r2 = dict(r)
            r2.pop("embed_text", None)
            r2["embedding"] = emb
            success.append(r2)
    return success, [], char_count


# ----------------------------------------------------------------------
# Parquet writer
# ----------------------------------------------------------------------

class StreamingParquetWriter:
    """
    Streams rows to parquet via batched RecordBatch flushes.

    If the output file already exists (resume), we read it once and write
    everything (old + new) to a temp file, then atomically replace at the end.
    This keeps the writer simple while preserving previously embedded data.
    """

    def __init__(self, path: Path, schema: pa.Schema, flush_every: int = 1000):
        self.path = path
        self.tmp_path = path.with_suffix(".parquet.tmp")
        self.schema = schema
        self.flush_every = flush_every
        self._buffer: List[Dict[str, Any]] = []
        self._writer: Optional[pq.ParquetWriter] = None
        self._rows_written = 0
        self._opened = False

    def _open(self):
        if self._opened:
            return
        self.tmp_path.parent.mkdir(parents=True, exist_ok=True)
        # Use SNAPPY compression — fast and well supported.
        self._writer = pq.ParquetWriter(self.tmp_path, self.schema, compression="snappy")
        self._opened = True

        # Carry over previously-embedded rows from a partial run.
        if self.path.exists():
            try:
                existing = pq.read_table(self.path, schema=self.schema)
                if existing.num_rows > 0:
                    self._writer.write_table(existing)
                    self._rows_written += existing.num_rows
                    log.info(f"Carried over {existing.num_rows} rows from previous parquet")
            except Exception as e:
                log.warning(f"Could not carry over previous parquet rows: {e}")

    def add_rows(self, rows: List[Dict[str, Any]]):
        if not rows:
            return
        self._buffer.extend(rows)
        if len(self._buffer) >= self.flush_every:
            self.flush()

    def flush(self):
        if not self._buffer:
            return
        self._open()
        table = pa.Table.from_pylist(self._buffer, schema=self.schema)
        self._writer.write_table(table)
        self._rows_written += len(self._buffer)
        self._buffer.clear()

    def close(self):
        self.flush()
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        if self.tmp_path.exists():
            # Atomic-ish replace.
            os.replace(self.tmp_path, self.path)

    @property
    def rows_written(self) -> int:
        return self._rows_written


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def chunked(seq: List[Any], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def main() -> int:
    t_start = time.time()

    doc_lookup = load_doc_lookup()
    skip_ids = load_already_embedded()
    pending, total_seen, skipped_empty = iter_chunk_records(doc_lookup, skip_ids)

    if not pending:
        log.info("Nothing to embed — all chunks already in parquet.")
        return 0

    log.info(
        f"Embedding {len(pending)} chunks via Vertex AI {VERTEX_MODEL} "
        f"(batch={BATCH_SIZE}, workers={MAX_WORKERS})"
    )

    client = make_client()
    writer = StreamingParquetWriter(OUT_PARQUET, PARQUET_SCHEMA, flush_every=FLUSH_EVERY)

    failures: List[Dict[str, str]] = []
    err_counts = {
        "quota_error": 0,
        "transport_error": 0,
        "token_limit_error": 0,
        "other_error": 0,
    }
    api_calls = 0
    total_chars = 0
    embedded_count = 0
    last_progress = 0

    batches = list(chunked(pending, BATCH_SIZE))
    log.info(f"Total batches: {len(batches)}")

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            future_to_batch = {ex.submit(worker_embed, client, b): b for b in batches}
            for fut in as_completed(future_to_batch):
                api_calls += 1
                batch = future_to_batch[fut]
                try:
                    success, failed, char_count = fut.result()
                except Exception as e:
                    log.error(f"worker crashed: {e}")
                    failed = [(r["chunk_id"], "other_error") for r in batch]
                    success, char_count = [], 0

                total_chars += char_count

                if success:
                    writer.add_rows(success)
                    embedded_count += len(success)

                for cid, cat in failed:
                    err_counts[cat] = err_counts.get(cat, 0) + 1
                    failures.append({"chunk_id": cid, "error": cat})

                if embedded_count - last_progress >= PROGRESS_EVERY:
                    elapsed = time.time() - t_start
                    rate = embedded_count / elapsed if elapsed > 0 else 0
                    log.info(
                        f"progress: {embedded_count}/{len(pending)} "
                        f"({rate:.1f} chunks/s) "
                        f"failed={len(failures)} api_calls={api_calls}"
                    )
                    last_progress = embedded_count
                    # Periodic flush so a crash loses at most ~1000 rows.
                    writer.flush()

    finally:
        writer.close()
        if failures:
            with open(FAILED_FILE, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "counts": err_counts,
                        "failures": failures,
                    },
                    f,
                    indent=2,
                )
            log.warning(f"Wrote {len(failures)} failed chunk_ids to {FAILED_FILE}")

    elapsed = time.time() - t_start

    # ------------------------------------------------------------------
    # Verification
    # ------------------------------------------------------------------
    log.info("Verifying parquet output...")
    table = pq.read_table(OUT_PARQUET)
    n_rows = table.num_rows
    file_size_mb = OUT_PARQUET.stat().st_size / 1024 / 1024

    # Validate embedding lengths via the schema (fixed_size_list guarantees length).
    embed_field = table.schema.field("embedding")
    embed_dim_ok = embed_field.type == pa.list_(pa.float32(), EMBED_DIM)

    # Sample 3 rows for sanity print.
    sample_indices = [0, n_rows // 2, max(0, n_rows - 1)] if n_rows >= 3 else list(range(n_rows))
    sample_rows = []
    for idx in sample_indices:
        row = {col: table.column(col)[idx].as_py() for col in [
            "chunk_id", "doc_title", "page", "heading", "embedding"
        ]}
        # Truncate embedding to first 3 floats for printing.
        emb = row["embedding"][:3] if row["embedding"] else []
        sample_rows.append(
            {
                "chunk_id": row["chunk_id"],
                "doc_title": (row["doc_title"] or "")[:80],
                "page": row["page"],
                "heading": (row["heading"] or "")[:60],
                "embedding[0:3]": emb,
            }
        )

    estimated_cost = (total_chars / 1_000_000) * VERTEX_PRICE_PER_M_CHARS

    rate = n_rows / elapsed if elapsed > 0 else 0

    print()
    print("=" * 72)
    print("EMBEDDING RUN SUMMARY")
    print("=" * 72)
    print(f"Total chunks in parquet:    {n_rows}")
    print(f"Newly embedded this run:    {embedded_count}")
    print(f"Total seen in chunk files:  {total_seen}")
    print(f"Skipped (empty text):       {skipped_empty}")
    print(f"Wall time:                  {elapsed:.1f}s")
    print(f"Throughput:                 {rate:.1f} chunks/sec")
    print(f"Vertex API calls (this run):{api_calls}")
    print(f"Total chars embedded (run): {total_chars:,}")
    print(f"Estimated Vertex cost (run):${estimated_cost:.4f}")
    print(f"Embedding dim ok (768):     {embed_dim_ok}")
    print(f"Parquet file:               {OUT_PARQUET}")
    print(f"Parquet size (MB):          {file_size_mb:.2f}")
    print(f"Failures:                   {len(failures)}  {err_counts}")
    print()
    print("Sample rows:")
    for i, sr in enumerate(sample_rows):
        print(f"  [{i}] chunk_id={sr['chunk_id']}")
        print(f"      doc_title={sr['doc_title']}")
        print(f"      page={sr['page']} heading={sr['heading']}")
        print(f"      embedding[0:3]={sr['embedding[0:3]']}")
    print("=" * 72)

    if n_rows >= 38000 and embed_dim_ok and not failures:
        print("EMBEDDINGS DONE — ready for Qdrant upsert")
        return 0
    if n_rows >= 38000 and embed_dim_ok:
        print(f"EMBEDDINGS DONE (with {len(failures)} failures logged) — ready for Qdrant upsert")
        return 0
    print("BLOCKED — verification failed (check row count / embedding dim / failures)")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        log.warning("Interrupted")
        sys.exit(130)
    except Exception:
        traceback.print_exc()
        sys.exit(2)
