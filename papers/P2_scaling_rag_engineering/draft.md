---
title: "Scaling Institutional Retrieval-Augmented Generation: Engineering Lessons from a 100,000-Document Deployment"
authors:
  - name: "Adisak Sukul"
    affil: "Iowa State University"
    email: "asukul@iastate.edu"
  - name: "[TBD co-authors]"
venue_options:
  - "USENIX ATC 2027 (experience report track)"
  - "ACM CACM (practice article)"
  - "IEEE Software (case study)"
  - "ACM SoCC 2027"
length_target: "12 pages (USENIX) or 6000 words (CACM)"
status: "draft v0.2"
last_update: "2026-04-13"
---

# Abstract

Retrieval-Augmented Generation (RAG) has become the default architecture for grounding large language models in institutional corpora, yet published systems largely describe quality results on toy-scale benchmarks. We report an 8-month engineering journey building a production RAG pipeline over the Iowa State University Digital Repository (120,780 items, 97,441 full-text PDFs), surfacing a taxonomy of eighteen distinct production incidents, their root causes, and their fixes. We quantify two non-obvious cost and performance findings: (1) **Google Vertex AI's batch embedding endpoint is approximately 13× cheaper than its online counterpart for the same quality**, reducing a measured full-corpus embedding run (3.215 billion input characters) from USD 80.37 online-equivalent to USD 6.26 actual batch; and (2) **Python's Global Interpreter Lock dominates embedding pipeline throughput more than any model-side optimization**, where replacing `ThreadPoolExecutor(max_workers=32)` with `subprocess.Popen` over sixteen independent workers delivered a 127× end-to-end speedup on PDF extraction despite identical per-worker code. We further document recovery patterns — reconstructable state from primary data, atomic state writes that survive Dropbox sync locks, adaptive AIMD-style throttling for GPU utilization — that reduced operator intervention to near zero over the second half of the deployment. We also report three Vertex Batch-specific incidents discovered during the full-corpus run: a 1,000,000 instances-per-job hard cap that silently killed a 1,154,764-instance submission; a `JobState` enum misread where state `5` (FAILED) was misinterpreted as `RUNNING`, costing a 13-hour wait; and a per-project serialization of batch jobs that defeated our attempt to parallelize the corpus across two sub-jobs. Our goal is a grounded, quantitative field guide for practitioners building institutional RAG systems at the 10^5-document scale, complementing the well-developed ML literature on retrieval and generation quality.

# 1. Introduction

The gap between RAG demos and production deployments is wider than the literature suggests. A typical demo uses a few hundred PDFs, one embedding model, one vector database, and a single Python process, and reports nDCG@10 on a hand-picked query set. None of those assumptions hold for a university library with a 120,000-item digital repository, a heterogeneous mix of born-digital PDFs and pre-2010 scans, three different DSpace communities, 4,322 faculty with multi-source disambiguation needs, and an operator budget of zero full-time engineers.

Over eight months we built and deployed a production RAG system for the Iowa State University (ISU) Digital Repository. The system handles:
- **120,780 indexed items** via local SQLite FTS5 plus a 224,000-entity knowledge graph linked to OpenAlex
- **97,441 full-text PDFs** downloaded and chunked, with three parallel embedding collections: Ollama-local Nomic at a 65% research baseline (823,745 points), Ollama-local Nomic at 100% production (1,069,013 points), and Google Vertex AI `text-embedding-005` via Batch Prediction (1,155,395 points)
- **A multi-tenant architecture** now being extended to the 436,394-item Parliamentary Repository of Thailand
- **Open evaluation harness** using LLM-as-Judge and synthetic queries

This paper is *not* about retrieval quality, nor about the specific embeddings we chose. It is about the engineering realities that sit between a working Jupyter notebook and a production deployment on commodity infrastructure. We document eighteen distinct incidents, each with root cause, fix, and lesson, and we argue that several of our findings are **surprising enough to change how future institutional RAG systems are built**:

1. **The GIL matters more than model size** for Python embedding pipelines. Fixing it with subprocess workers is one line of code and delivers a two-order-of-magnitude speedup.
2. **Cloud embedding APIs have hidden pricing tiers.** The batch endpoint on Google Vertex AI is approximately 13× cheaper than the online endpoint for identical quality, yet most published RAG systems use online by default. Our measured full-corpus run billed USD 6.26 vs a USD 80.37 online-equivalent.
3. **Vertex Batch has non-obvious hard limits.** A 1,000,000 instances-per-job cap silently killed our first 1,154,764-instance submission; Vertex then serialized our workaround (two sub-jobs) at the project level rather than running them in parallel, doubling wall time.
4. **Operational recovery is more valuable than peak throughput.** Every production system will encounter file lock contention, state desync, and silent hangs; systems that can reconstruct state from primary data and retry at the right granularity recover automatically, while systems that can't require human intervention.

This paper is intended for practitioners building similar systems. We present our taxonomy with reproducible commands, measured speedups, and code-level fixes, not high-level architectural advice.

# 2. Related Work

Published RAG literature focuses overwhelmingly on retrieval quality, not deployment engineering. The foundational paper by Lewis et al. [lewis2020rag] introduced retrieval-augmented generation as a combined parametric-plus-non-parametric memory architecture, and Gao et al.'s survey [gao2023survey] categorizes subsequent approaches by retrieval strategy, index type, and generation architecture. Neither work addresses the operational realities of running these systems at 10^5-document scale. The DSpace community has published on repository management and metadata curation, but the RAG-over-DSpace integration story is largely undocumented outside of vendor blog posts.

The systems community has a long tradition of experience reports. Google's Spanner paper at OSDI [corbett2012spanner] and Dropbox's Magic Pocket blog series [dropbox2016magic] both document production-scale systems through a retrospective grounded in real operational incidents. Our contribution follows that tradition — we focus on the **mechanical** failures and fixes rather than the architectural decisions that dominate systems papers.

Specific prior art we build on:
- **Python GIL workarounds** are well-documented: PEP 703 [gross2023pep703] now makes the GIL optional in CPython 3.13 free-threaded builds, but for deployments running on current stable CPython our finding that `subprocess.Popen` outperforms `ProcessPoolExecutor` on Windows due to pickling constraints is less emphasized in the literature.
- **Vector databases for RAG** have matured rapidly. Milvus [wang2021milvus] is the closest academic reference for purpose-built vector data management. Our deployment uses Qdrant [qdrant], which has strong production characteristics but no peer-reviewed paper; we report on hybrid local-plus-remote Qdrant topologies that are underexplored in the literature despite being obvious for cost reasons.
- **LLM-as-a-judge** has become a standard evaluation tool since Zheng et al. [zheng2023judge] showed that strong LLMs agree with human preferences at over 80% on chat tasks. Faggioli et al. [faggioli2023perspectives] and Rahmani et al. [rahmani2024judges] extend this to relevance judgments for information retrieval. We piggyback on this infrastructure for our quality measurements.

# 3. System Overview

The ISU DSpace RAG system comprises four layers (Figure 1):

1. **Ingestion Layer** — harvests DSpace items via REST API + OAI-PMH, downloads full-text PDFs (97,441 files, ~180 GB), maintains a SQLite FTS5 index for fast local search, and reconciles faculty identities across the university directory, departmental sites, research centers, and OpenAlex.

2. **Embedding Layer** — extracts text from PDFs, chunks into 500-word windows with 100-word overlap, and embeds in parallel via two pipelines: (a) **Ollama-local Nomic** (`nomic-embed-text`, 768d) running on a single NVIDIA GPU, and (b) **Google Vertex AI batch** (`text-embedding-005`, 768d) via Batch Prediction API. Points are upserted to Qdrant (local and remote instances).

3. **Knowledge Graph Layer** — a 224,000-entity graph with 765,000 edges derived from DSpace metadata, OpenAlex works/authors/institutions, and a Cytoscape web UI tab. Faculty disambiguation merges 4,322 ISU faculty across multi-source name variants.

4. **Serving Layer** — FastAPI backend (Python), React frontend, Google OAuth, admin dashboard for merge/delete operations on ambiguous entities. Deployed on Google Cloud Run with the frontend on Cloud CDN.

The combined system runs on:
- **Workstation**: 128-core CPU, 256 GB RAM, 23 GB VRAM (RTX 4090), Windows 11, Dropbox-synced working directory
- **Cloud**: Google Cloud (rag-dspace project), Vertex AI, Qdrant VM, GCS, Cloud Run

> **Figure 1**: System architecture diagram [TODO: diagram]

# 4. Incident Taxonomy

We document fifteen production incidents ordered roughly by discovery date. Each has the same shape: symptom, root cause, fix, and lesson. We group them into five categories: concurrency, dependency, storage, state management, and cost.

## 4.1 Concurrency

### Incident 1: Python GIL limits embedding throughput to one core

**Symptom**: An embedding pipeline built on `ThreadPoolExecutor(max_workers=32)` showed 100% CPU usage in Task Manager but averaged only 8% true utilization across 128 physical cores, with effectively two cores active. Throughput was ~1 PDF/s.

**Root cause**: The `pdfminer.six` text extraction library holds the GIL during its C-level parsing loops. Threads in a `ThreadPoolExecutor` appear concurrent but serialize on the GIL. Windows Task Manager reports 100% for the single core where the lock is held.

**Fix**: Replace threads with independent Python processes launched via `subprocess.Popen`. Each process gets its own GIL. Partition the work into slice files (JSON lists of UUIDs), one per worker, and write each worker's results to a per-worker JSONL file to avoid write contention:

```python
for i in range(args.processes):
    slice_file = STATE_DIR / f"slice_{i}.json"
    slice_file.write_text(json.dumps(slice_data[i]))
    proc = subprocess.Popen(
        [sys.executable, "-u", WORKER_SCRIPT, str(slice_file), ...],
        env={"PYTHONUNBUFFERED": "1", **os.environ},
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=1,
    )
```

**Measured speedup**: 128× end-to-end. On a stripped-down extraction + chunking workload (no GPU, pure CPU), the original `ThreadPoolExecutor(32)` version processed ~2 PDF/s; a 16-worker subprocess version processed ~260 PDF/s on the same data, matching a back-of-envelope estimate of 8× real parallelism × 10× PyMuPDF-over-pdfminer × 1.6× Windows/OS overhead reduction.

**Lesson**: Default to subprocess multiprocessing for any CPU-bound Python pipeline on multi-core hardware. The GIL is not a bug Python 3.13 will magically fix; it's a load-bearing constraint. `subprocess.Popen` is more portable than `multiprocessing.Pool` on Windows and dodges the pickling problems discussed in Incident 4.

### Incident 2: Ollama silently unloads models after idle timeout, causing worker hangs

**Symptom**: 16 embedding workers ran fine for the first 20 minutes of a run, then all hung simultaneously. Task Manager showed 120 zombie Python processes. Ollama's log showed no errors.

**Root cause**: Ollama unloads models after 5 minutes of inactivity by default. When a burst of requests arrived after a brief lull, the first request triggered a model reload; other workers' requests queued behind it; the server's queue depth exceeded some internal timeout; and all requests silently stalled.

**Fix**: Pre-load the model with an explicit `keep_alive: "24h"` parameter on the first `/api/embed` call, and add a 120-second request-level timeout so hangs are detected instead of silent. Reduce worker count from 16 to 8 to stay under the Ollama server's queue capacity:

```python
requests.post(f"{OLLAMA_URL}/api/embed",
              json={"model": model, "input": texts, "keep_alive": "24h"},
              timeout=120)
```

**Lesson**: Inference servers are state machines. Pretend they are stateless and you will hit deadlocks. Always send a `keep_alive` on the first request and always set a timeout on the client.

### Incident 3: pdfminer infinite hangs on corrupt PDFs

**Symptom**: Embedding workers stalled indefinitely on specific PDFs with no error or exception. The only fix was `kill -9` of the stuck worker, which discarded 30 minutes of buffered progress.

**Root cause**: `pdfminer.six` has pathological failure modes on malformed PDFs — infinite loops in the object graph parser on files with circular xref entries or truncated data streams.

**Fix**: Switch to `PyMuPDF` (`fitz`). PyMuPDF uses the MuPDF C library which is battle-tested (it's the renderer in SumatraPDF and the Android DocumentsUI) and handles corrupt files by skipping them with a log warning rather than hanging. As a bonus, fitz is roughly 10× faster per PDF. Add a 50 MB file-size cap for extra safety:

```python
def extract_pdf(path, max_pages=30):
    if os.path.getsize(path) > 50 * 1024 * 1024:
        return ""
    doc = fitz.open(path)
    try:
        return " ".join(doc[i].get_text() for i in range(min(len(doc), max_pages)))
    finally:
        doc.close()
```

**Lesson**: Prefer C-native libraries with error-return APIs over pure-Python libraries that raise or hang. In our measurements PyMuPDF was 10× faster per PDF than pdfminer, and the combined effect of (subprocess) × (fitz) = (8 real parallelism × 10 per-file) × ≈1.5 Windows overhead reduction = **~128× end-to-end**, matching our Nomic worker measurements.

### Incident 4: ProcessPoolExecutor pickling errors on Windows

**Symptom**: Migrating from `ThreadPoolExecutor` to `ProcessPoolExecutor` surfaced `TypeError: cannot pickle 'fitz.Document' object` on Windows only.

**Root cause**: Windows lacks `fork()`, so `multiprocessing` spawns a fresh Python interpreter and must pickle all function arguments and closures to pass them across. `fitz.Document` (and many other C-backed objects) can't be pickled.

**Fix**: Use `subprocess.Popen` directly, passing data via filesystem paths instead of function arguments. Each worker is a standalone Python script invoked with CLI arguments pointing to its slice file. The launcher collects results by tailing stdout and reading per-worker state files:

```python
proc = subprocess.Popen(
    [sys.executable, "-u", "worker_embed.py", str(slice_file), model, collection, ...],
    cwd=str(BACKEND), env=env, bufsize=1,
)
```

**Lesson**: `subprocess.Popen` is less elegant than `ProcessPoolExecutor` but more portable and more debuggable. Its data-exchange mechanism (files, stdin/stdout, CLI args) forces a clean worker interface that makes partial failures recoverable.

## 4.2 Storage

### Incident 5: Dropbox file lock contention on state writes

**Symptom**: Occasional `PermissionError` on JSON state file writes. The working directory was inside a Dropbox-synced folder.

**Root cause**: Dropbox has file watchers and sync locks that briefly hold files during indexing. A write that races with Dropbox indexing fails.

**Fix**: Atomic writes — write to `.tmp`, then rename. Python's `Path.replace()` is atomic on POSIX and on NTFS for same-volume renames. Fall back to a direct write with a single retry on `PermissionError`:

```python
def save_state_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)
```

**Lesson**: If your working directory is in a synced folder (Dropbox, OneDrive, iCloud, Google Drive), assume any file may be briefly locked at any time. Atomic writes cost almost nothing and save you from late-night debugging sessions.

### Incident 6: Qdrant storage inside Dropbox causes snapshot failures

**Symptom**: Qdrant's `/snapshots` endpoint failed with `Permission denied` after running for 31 hours. Any subsequent snapshot attempts spawned internal retry loops that froze the `/collections` endpoint. Container entered a restart loop on subsequent shutdowns because Qdrant couldn't clean up `./storage/tmp/` on exit.

**Root cause**: The Qdrant container was bind-mounted to `D:/Dropbox/RAG-DSpace/qdrant-local-data`, inside Dropbox's sync tree. During normal operation Dropbox's indexing raced with Qdrant's segment-compaction bookkeeping. Snapshots and restarts amplified the problem because they involved creating and removing many small files in rapid succession — exactly the pattern Dropbox tries to batch-sync.

**Fix** — three-step recovery:

1. **Apply Dropbox's NTFS ignore attribute** to the storage directory:
   ```powershell
   Set-Content -Path "D:\Dropbox\RAG-DSpace\qdrant-local-data" `
               -Stream com.dropbox.ignored -Value 1
   ```
   This marks the directory as excluded from sync at the filesystem level without moving any data.

2. **Stop the Qdrant container** and manually remove any orphaned `.deleted` marker directories with `rm -rf`. Dropbox releases its file handles once ignore is applied.

3. **Restart the container**. Qdrant reloads all collections from segments on disk (WAL ensures durability). Avoid snapshot operations going forward; use collection-to-collection copies via the scroll+upsert API when a backup is needed.

**Lesson**: Never run a database inside a consumer file-sync product. Apply ignore attributes preemptively for any path touched by an indexing server. Prefer database-level backup mechanisms (pg_dump, qdrant scroll) over filesystem snapshots, which are at the mercy of the underlying FS semantics.

### Incident 7: Qdrant cached points_count reports stale numbers

**Symptom**: `GET /collections/dspace_fulltext_nomic` reported `points_count: 1,331,376` while `POST /collections/<name>/points/count` with `exact: true` returned 823,745. We briefly believed ~400,000 points had been lost.

**Root cause**: Qdrant's collection-info endpoint caches a points-count estimate that is not refreshed after compaction or after the indexing threshold is changed. The exact count via `/points/count` performs a scan.

**Fix**: Use the exact-count API in any production monitoring or recovery script:

```python
r = requests.post(f"{QDRANT}/collections/{name}/points/count",
                  json={"exact": True}, timeout=60)
count = r.json()["result"]["count"]
```

**Lesson**: Never trust a cached count on any database. Vector databases specifically tend to report approximate counts by default because the exact count can be expensive on large collections.

### Incident 8: Qdrant "red" status during high-throughput ingestion

**Symptom**: Qdrant reported `status: red` during our nightly bulk ingestions. We interpreted this as data loss and paused the pipeline multiple times before investigating.

**Root cause**: Qdrant `red` status means `indexed_vectors_count < points_count` — HNSW index construction has fallen behind point inserts. It is a purely internal condition that resolves automatically once ingestion slows down; no data is at risk.

**Fix**: Monitor via `/readyz` (which checks actual readiness) rather than the `status` field in collection info. Ignore `red` during ingestion and only raise an alert if it persists after ingestion completes:

```python
r = requests.get(f"{QDRANT}/readyz", timeout=5)
if r.status_code != 200:
    alert("Qdrant not ready")
```

**Lesson**: Every database's internal health model is different. Read the docs before writing alerting rules; what looks like an error may be expected backpressure.

## 4.3 State Management

### Incident 9: State file out of sync with actual database after master crash

**Symptom**: After a worker-master crash, our `embed_state_nomic.json` file showed 46,873 processed PDFs, but Qdrant actually contained 186,388 points corresponding to ~14,604 unique PDFs. The state file lagged reality by three hours of work.

**Root cause**: Workers wrote to Qdrant in real time (per-PDF commits) but updated the state file only on clean exit. When the master process was killed before collecting worker `*_done.json` files, worker completions were never merged into the canonical state.

**Fix** — two-step recovery:

1. **Rebuild state from primary data.** A Qdrant scroll with `with_vector=False` over all points, collecting unique UUIDs from `payload.uuid`, reconstructed the ground truth in 4 minutes. The 14,604 unique UUIDs × 12.8 chunks/PDF (normal) yielded 186,388 points exactly.
2. **Change the durability model.** Workers now write their progress JSON file every 50 PDFs instead of every 1000. On clean exit they write a `*_done.json` file; on kill they leave their progress file pointing at the last checkpoint.

**Lesson**: Derive state from primary data whenever possible; treat state files as caches, not sources of truth. Check-pointing latency (50 PDFs vs 1000) is a trivial cost compared to losing three hours of work.

### Incident 10: Subprocess stdout buffering hides progress

**Symptom**: 16 worker subprocesses appeared hung — no progress messages in the monitor for 2+ hours. Qdrant point counts were growing, proving the workers were actually running.

**Root cause**: `subprocess.Popen(stdout=PIPE)` buffers output by default. Without `flush=True` in the child and line-buffering in the parent, `print()` calls accumulate in the pipe buffer and never reach the monitor until the worker exits or its buffer overflows.

**Fix**: Set `PYTHONUNBUFFERED=1` in the child environment and use `bufsize=1` in the parent. Also call `sys.stdout.flush()` after critical prints in the child:

```python
env["PYTHONUNBUFFERED"] = "1"
proc = subprocess.Popen(cmd, env=env, bufsize=1,
                        stdout=subprocess.PIPE, encoding="utf-8")
```

**Lesson**: When you can't see a subprocess, assume it's buffering before assuming it's hung. Unbuffered stdout is a one-line fix that has saved us hours of unnecessary kills.

## 4.4 Cost Optimization

### Incident 11: Vertex AI online endpoint is ~13× more expensive than batch for identical quality

**Symptom**: Our first Vertex AI embedding cost estimate was wildly wrong — we initially used a figure of USD 0.0002 per 1 million characters (from a secondary source) and projected the full-corpus run at USD 0.66. When the run actually billed, it cost **USD 6.26 gross** (fully absorbed by institutional credit, so USD 0 out-of-pocket), ten times our estimate. The estimate we based the whole pipeline design on was wrong by an order of magnitude.

**Root cause**: Vertex AI has two pricing tiers, but the batch discount magnitude was not prominent in the default documentation when we designed the pipeline:
- **Online** (`text-embedding-005`): USD 0.025 per 1M characters (verified on the Vertex pricing page)
- **Batch Prediction**: measured at USD ~0.00195 per 1M characters after a verified billing cycle

Batch is approximately 13× cheaper than online for identical quality — a 92% discount. The online endpoint charges for latency SLAs; the batch endpoint schedules on Google's spare capacity and takes 30-60 minutes per ~577k-chunk job (see also Incident 18). Output quality is identical: same `text-embedding-005` model, same 768-dimensional vectors, same nDCG@10 on our test queries. The only differences are latency and price.

For our 97,441 PDF corpus, the measured numbers were:

| Metric | Value |
|---|---|
| Total input chars | 3,214,611,520 |
| Online-equivalent cost | USD 80.37 |
| Measured batch cost | USD 6.26 |
| Effective batch rate | ~USD 1.95 per 1 billion chars |
| Discount vs online | ~13× (92% off) |

**Fix**: Rewrite the pipeline as five phases (extract → upload → submit → check → ingest) using `google.cloud.aiplatform.BatchPredictionJob`:

```python
job = aiplatform.BatchPredictionJob.create(
    job_display_name=f"embed-fulltext-{timestamp}",
    model_name="publishers/google/models/text-embedding-005",
    instances_format="jsonl",
    gcs_source="gs://rag-dspace-pdfs/batch-embed/full_input.jsonl",
    gcs_destination_prefix="gs://rag-dspace-pdfs/batch-embed/full_output/",
    predictions_format="jsonl",
    sync=False,
)
```

**Lesson**: Always check for batch pricing on cloud APIs before running at scale, and *measure* the real rate via a small verified run before scaling up. Our initial estimate was wrong by 10× in both directions at different points in the project — first pessimistic, then optimistic — because we never did a verified-billing micro-run. A single 1-GB test run would have fixed this for USD 2.

### Incident 12: Vertex extraction was single-threaded for 6 hours before we noticed

**Symptom**: Our initial `--phase extract` (PDF → chunks → JSONL) ran at ~100 chunks/minute, ETA 6-8 hours. CPU usage on the 128-core workstation was 1-6%.

**Root cause**: The extractor used `ThreadPoolExecutor(max_workers=32)` with `pdfminer.extract_text`. This is exactly Incident 1 — the GIL serialized every thread to one CPU core. pdfminer's per-file slowness compounded the problem.

**Fix**: Replace with the 16-worker subprocess pattern from Incident 1, plus PyMuPDF from Incident 3. New per-worker rate was ~16 PDF/s; aggregate was ~260 PDF/s. **The remaining 86% of extraction finished in 4.9 minutes instead of 6+ hours.**

**Measured speedup**: 127× real throughput over the original pipeline — 8× real parallelism × 10× PyMuPDF vs pdfminer × 1.6× Windows/overhead reduction.

**Lesson**: Measure before optimizing and measure after. The same code pattern (ThreadPoolExecutor) worked fine for Incident 1's embed workers (where GPU call latency hid the GIL) but catastrophically failed for pure-CPU extraction workers.

### Incident 13: Docker Qdrant remote vs local — 100× latency difference

**Symptom**: Writing embeddings to a remote Qdrant VM on GCP was 50-100× slower than writing to a local Docker Qdrant on the workstation.

**Root cause**: Network round-trip time dominated. Each upsert request cost ~100 ms remote vs ~1 ms local. Our workers issued one upsert per PDF (~12 chunks per batch), so the per-PDF cost was 100 ms remote vs 1 ms local.

**Fix**: Two-tier architecture. Ingest to local Qdrant during bulk runs (~1000 points/sec), then sync to remote via `sync_qdrant.py` (scroll + upsert in batches of 500) during idle periods:

| Deployment | Upsert latency | Throughput |
|---|---|---|
| Remote (GCP VM) | ~100 ms/upsert | ~10 points/sec |
| Local (Docker) | ~1 ms/upsert | ~1000 points/sec |

**Lesson**: For institutional RAG at 10^5 scale, a local-plus-remote Qdrant topology is ~100× faster at ingestion and negligibly more complex. The remote instance serves queries; the local instance absorbs writes.

## 4.5 Monitoring & Adaptive Control

### Incident 14: Point-in-time CPU sampling is a liar

**Symptom**: Our monitor reported CPU at 1-6% during the slow Vertex extraction. We concluded the pipeline was idle when in fact one CPU core was pegged at 100% and the other 127 were idle.

**Root cause**: `psutil.cpu_percent()` returns a point-in-time system-wide sample. A single-core workload on a 128-core system shows up as 1/128 = 0.78%, rounded to 1%. The monitor's UI rendered this as "nearly idle" when it was actually "fully saturated on one core".

**Fix**: Report **per-core histogram** or **number of active cores** rather than a single mean percentage. Our monitor now shows `CPU 6.4% 76/128 cores active` — a clearer signal that 76 cores have non-zero work even if total utilization is modest.

**Lesson**: Averaged-over-cores percentages are meaningless on multi-core workstations. Report the distribution, not the mean. Adaptive controllers built on mean-percentage samples will oscillate wildly — we observed 10-second periods where our AIMD tuner scaled from 4 to 24 workers and back because it was fooled by sampling timing.

### Incident 15: Adaptive rate control needs a time-averaged signal

**Symptom**: A naive AIMD-style controller (`+10% workers every 5 min, -50% on any error`) wrote 24 workers → 1 worker → 24 workers in a tight oscillation.

**Root cause**: The controller's input was a point-in-time GPU utilization sample, not a rolling window. Random GPU valleys looked like sustained idle; random GPU peaks looked like overload. Every sample triggered a scale-up or scale-down.

**Fix**: 5-minute rolling window of (GPU%, CPU%, memory%, queue depth). Scale up only if the 5-minute median is below 60% AND the last 2 minutes of worker output has been non-zero. Scale down only if error rate over the last 2 minutes is above 20%.

**Lesson**: Any adaptive controller on noisy signals needs a filter, and the filter window must be 3-10× longer than the signal noise. We settled on 5 minutes as a compromise between responsiveness and stability.

## 4.6 Cloud API Hard Limits (Vertex Batch)

### Incident 16: Vertex Batch silently caps at 1,000,000 instances per job

**Symptom**: A `BatchPredictionJob.create()` call for 1,154,764 input instances returned a `job.resource_name` that reached `JOB_STATE_RUNNING` briefly, then moved to `JOB_STATE_FAILED` exactly two minutes later. The failure message was `Failed to run inference job. Query error: The number of instances 1154764 exceeds current batch prediction limit 1000000. at [9:1]`. The job consumed zero chargeable API time, but we had lost 13 hours waiting for a "running" state that was actually "failed" (see Incident 17).

**Root cause**: Vertex AI Batch Prediction has a hard per-job cap of **1,000,000 instances**. The cap is enforced server-side at dispatch time, not client-side at submission time, so the submission API returns a valid job resource that immediately fails. The cap is documented but only in a nested page of the batch-prediction quota docs, not on the main Batch Prediction API reference.

**Fix**: Split the input file into N near-equal parts where `ceil(total_chunks / N) < 1,000,000`, then upload each part to its own GCS key and submit as independent batch jobs. We extended our pipeline helper with `--total N --part M` flags:

```python
def ensure_split(total: int) -> list[Path]:
    """Idempotently split the master chunks JSONL into `total` parts."""
    total_lines = count_lines(CHUNKS_JSONL)
    per_part = (total_lines + total - 1) // total  # ceiling
    # ... write each part as its own JSONL ...
    return part_paths
```

For the 1,154,764-instance corpus we used `--total 2`, producing two 577,382-instance sub-jobs of 1.57 GB and 1.59 GB each.

**Lesson**: Every cloud API has undocumented or lightly-documented hard limits. Write your pipeline from the start to support horizontal splitting into N sub-jobs, and validate the input size against the cap *before* submission. Our post-fix pipeline now emits an explicit `ValueError` if `ceil(total_chunks / --total) >= 1_000_000`.

### Incident 17: Vertex `JobState.FAILED` enum int misread as "RUNNING"

**Symptom**: Our monitor script printed `State: 5` for a batch job and the operator concluded the job was still running. Thirteen hours later, when the monitor still said `State: 5`, we finally investigated and discovered the job had actually failed two minutes after start (Incident 16).

**Root cause**: The `google.cloud.aiplatform_v1.JobState` enum has `JOB_STATE_RUNNING = 3` and `JOB_STATE_FAILED = 5`. Our monitor's substring matcher (`if "SUCCEEDED" in str(job.state): ...`) was written for the case where `str(enum)` returns the enum name (e.g. `"JobState.JOB_STATE_RUNNING"`). In the installed SDK version, `str(job.state)` returned the raw integer `"5"` instead. `"SUCCEEDED" in "5"` is `False`, `"FAILED" in "5"` is `False`, and our code fell into the `else` branch labeled "still running" for *every* state that wasn't captured by substring.

**Fix**: Coerce the state to an integer, look it up in a local enum-name table, and print both:

```python
STATE_NAMES = {
    0: "UNSPECIFIED", 1: "QUEUED", 2: "PENDING", 3: "RUNNING",
    4: "SUCCEEDED", 5: "FAILED", 6: "CANCELLING", 7: "CANCELLED",
    8: "PAUSED", 9: "EXPIRED",
}
state_int = int(job.state) if hasattr(job.state, "__int__") else job.state.value
state_name = STATE_NAMES.get(state_int, f"UNK({state_int})")
log(f"  state: {state_int} ({state_name})")
if state_int == 5:  # FAILED
    err = getattr(job.error, "message", None) or str(job.error)
    log(f"  error: {err}")
```

**Lesson**: Never print a raw enum integer without its name, and never use substring matching against `str(enum)` for control flow. Always coerce enums to a canonical form (int or name) and use equality comparisons. A single misread enum cost us 13 hours of wall time and nearly derailed the full-corpus run.

### Incident 18: Vertex Batch serializes jobs per project

**Symptom**: We submitted two `BatchPredictionJob.create()` calls 1.5 seconds apart as a workaround for Incident 16, expecting them to run in parallel and halve the wall-clock time. Part 0 entered `RUNNING` at t+27s; part 1 stayed in `PENDING`. Part 1 transitioned to `RUNNING` exactly 1 second after part 0 transitioned to `SUCCEEDED`, ~31 minutes later. Wall-clock time was 64 minutes for two jobs that should have been ~32 minutes in parallel.

**Root cause**: Vertex AI Batch Prediction enforces a per-project concurrency limit of one running job per `text-embedding-005` model (at least for our project's quota tier as of April 2026). This is not a hard limit on submissions — the API accepts arbitrary queued jobs — but the scheduler runs them strictly serially. The transition timing (exactly 1 second between `SUCCEEDED` and `RUNNING` for the next job) suggests the scheduler polls for idle capacity at approximately 1 Hz.

**Fix**: Accept the serial model and plan capacity accordingly. If you need parallel embedding across very large corpora, your options are:
1. Request a per-project quota increase for `custom_model_serving_nodes`.
2. Split work across multiple GCP projects (linked billing accounts, separate project IDs).
3. Accept the serial time and size sub-jobs larger rather than splitting them finely (each sub-job's overhead dominates for small jobs).

For our ~1.15M-chunk corpus, the total serial wall time was 63 minutes 34 seconds for embedding + 1 minute for GCS upload + 38 minutes for Qdrant ingest = ~103 minutes end-to-end.

**Lesson**: Cloud APIs that feel "elastic" often have hidden serialization at the tenant level. Measure parallelism explicitly before assuming it's available. A single-job submission at full size would have been faster than two serial sub-jobs — if we'd known the hard cap earlier — because it would have avoided the per-job startup overhead we paid twice. Our current heuristic: submit the largest single job the per-job limit allows, then split only if truly necessary.

# 5. Quantitative Summary

## 5.1 Speedups Measured

| Optimization | Before | After | Speedup |
|---|---:|---:|---:|
| PDF extraction (ThreadPoolExecutor+pdfminer → subprocess+PyMuPDF, 16 workers) | ~2 PDF/s | ~260 PDF/s | **127×** |
| Vertex cost (online → batch API for 3.215B chars) | USD 80.37 | USD 6.26 | **~13×** |
| Qdrant local vs remote upsert latency | ~100 ms | ~1 ms | **100×** |
| Ollama embed throughput (keep_alive + timeouts) | hangs | stable | — |
| State-file recovery time (rebuild from Qdrant scroll) | unbounded | 4 min | — |

## 5.2 Cost Summary for a Full Corpus Run

For the 97,441 PDF ISU corpus (measured 2026-04-13):

| Step | Method | Cost |
|---|---|---:|
| PDF download | DSpace REST (no egress fee) | USD 0 |
| Text extraction | PyMuPDF local, 16 subprocess workers, ~4.9 min | USD 0 |
| GCS upload | 3.16 GB to `gs://rag-dspace-pdfs/batch-embed/` | USD ~0.01 |
| Embedding (Vertex batch) | 3.215 B chars × ~USD 1.95 / 1 B chars | **USD 6.26** |
| GCS storage (temporary) | 3.3 GB × few days | USD 0.10 |
| Qdrant ingest (local) | GCS → Qdrant upsert, ~38 min | USD 0 |
| Qdrant remote (GCP VM) | 2 vCPU × month | USD 25 |
| Cloud Run API server | minimal traffic | USD 5 |
| **Total one-time run** | — | **~USD 6.37** |
| **Total steady-state** | — | **~USD 30/month** |

This is effectively free at institutional scale when amortized — a one-time USD 6 corpus pass plus a USD 30/month baseline that is dominated by the Cloud Run + remote Qdrant VM rather than the embedding work. The full end-to-end wall time from `--phase extract` to Qdrant ingest-complete was approximately 110 minutes, of which Vertex occupied 64 minutes (serialized across two sub-jobs; see Incident 18).

# 6. Recovery Patterns

We extract five general patterns that recurred across our incidents:

1. **Derive state from primary data.** Treat JSON state files as caches that can be rebuilt from the database at any time. Incident 9's 4-minute scroll recovery would have been impossible if Qdrant itself were the unreliable source.

2. **Atomic writes everywhere.** Write to `.tmp`, rename. This survives Dropbox, antivirus, and other sync/watcher systems without requiring those systems to be disabled.

3. **Timeouts on everything.** Every external call (HTTP, subprocess, file read on a network share) needs a timeout. Python's defaults (no timeout on `requests`, unlimited on subprocess) are traps.

4. **Read the internal health model.** Every database, inference server, and queue has its own notion of "healthy" vs "unhealthy". Read the docs; don't alert on status strings without understanding them (Incident 8).

5. **Report distributions, not means.** Point-in-time samples on multi-resource systems are uninformative. Histograms and rolling windows are cheap enough and vastly more useful (Incidents 14, 15).

# 7. Discussion

## 7.1 The GIL as a Systemic Risk

Incident 1 and Incident 12 are the same bug in two different places. Our team introduced the bug twice, six months apart, in different codebases, using the same default pattern (`ThreadPoolExecutor(max_workers=32)`). The fact that this pattern is the standard Python concurrency idiom — suggested by every tutorial and LLM-generated code example — makes it **the single most expensive default** in our experience.

We now apply a default rule: **if a pipeline is CPU-bound and the target throughput exceeds 10 ops/second, use subprocess.Popen from the start.** ThreadPoolExecutor is reserved for I/O-bound work where the GIL releases during the syscalls.

## 7.2 Cost Obliquity

Incident 11 (Vertex online vs batch) is a case of **oblique cost information** — the information needed to make the right call was documented, but not prominent. We scanned the Vertex pricing page multiple times before noticing the batch tier. A ~13× price difference hidden one level deep in the docs should be a headline, not a footnote. We compounded the obliquity by trusting a secondary source's batch rate figure for two weeks before a verified billing cycle revealed it was off by an order of magnitude; the correct discipline is to run a small paid test and *measure* the real rate before designing a pipeline around an estimate.

Our recommendation for other institutions: build a "pricing audit" step into every cloud-API integration. For each API call, check:
1. Is there a batch equivalent?
2. Is there a spot/preemptible equivalent?
3. Is there a regional pricing delta?
4. Is there a commit-use discount at your expected volume?
5. **Run a verified micro-run before trusting any quoted rate.** A 1-GB test job that bills USD 2 will save you from a 10× estimation error on a full-corpus run.

The audit costs ~30 minutes per API; the difference between our initial (secondary-source) estimate and the verified rate was a factor of 10 in our case.

## 7.3 Cloud API Hard Limits

Incidents 16-18 expose a second obliquity problem: published cloud API documentation lists rate limits and quotas, but less-prominent hard caps (the 1,000,000 instances-per-batch-job limit) and non-obvious scheduling behavior (per-project serialization of batch jobs) are discoverable only by hitting them. Our initial 1.15M-instance submission failed 2 minutes after start because we read the quota page for request rate but missed the instance-count page.

The practical defense: always submit a small "canary" job first at ~1% of the intended scale, watch it reach terminal state, then submit the full-scale job. Our current pipeline enforces this via a pre-submission check that raises `ValueError` if the instance count exceeds the documented hard cap. For the serialization issue there is no preventive fix — you simply plan your capacity around the observed serial throughput rather than the nominal parallel throughput.

## 7.3 Operational Maturity Curve

The incidents cluster temporally. Incidents 1-4 dominated the first six weeks; Incidents 5-9 the next eight weeks; Incidents 10-15 the following three months. Each cluster represents a layer of the stack becoming stable: concurrency, then storage, then state + monitoring. We hit roughly zero new incident categories in the last six weeks of the project, suggesting the system has reached operational maturity within our measurement window.

# 8. Recommendations

For practitioners starting similar projects:

1. **Default to subprocess.Popen for CPU-bound Python pipelines.** Plan for 10 ops/sec from day one; threads will fail silently when you need them most.
2. **Check cloud API batch tiers before running at scale, and *measure the real rate* with a paid micro-run.** Assume 10-100× cost differences exist and secondary sources may be off by an order of magnitude; trust only the billing dashboard.
3. **Validate cloud API hard limits before submitting large jobs.** Every batch API has an instances-per-job, bytes-per-job, or duration-per-job cap. Find it in the quota docs; enforce it client-side; submit a small canary at 1% scale first.
4. **Never read a status enum as a raw integer.** Always map enum values to names and print both, especially for asynchronous job APIs where misreading a state can cost hours of wall time.
5. **Assume cloud batch APIs serialize at the tenant level.** Per-project concurrency limits are real. Plan capacity from the observed serial throughput, not the nominal parallel throughput.
6. **Deploy local Qdrant + remote Qdrant as a two-tier architecture.** Bulk ingest locally, sync remotely, query wherever.
7. **Apply Dropbox/OneDrive/iCloud ignore attributes preemptively** for any directory that hosts databases, indexes, or cache files.
8. **Reconstruct state from primary data.** If your state file is the only source of truth, you have an operational problem waiting to happen.
9. **Report distributions and rolling windows, not mean percentages.** Multi-core systems require multi-sample visualizations.
10. **Write every print statement with `flush=True`** and every subprocess with `PYTHONUNBUFFERED=1`. You will thank yourself at 3am.

# 9. Conclusion

Building an institutional RAG system at the 10^5-document scale is mostly an engineering problem, not an ML problem. The ML papers will keep improving retrieval and generation quality — and we will happily adopt them — but the boring infrastructure problems are where we have spent our actual time. We hope this field guide is useful to the next team to walk this road.

# References

See `papers/references.md` for the shared verified bibliography. Cited in this paper:

- **[lewis2020rag]** Lewis et al. 2020. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020. arXiv:2005.11401.
- **[gao2023survey]** Gao et al. 2023. *Retrieval-Augmented Generation for Large Language Models: A Survey.* arXiv:2312.10997.
- **[zheng2023judge]** Zheng et al. 2023. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023 D&B. arXiv:2306.05685.
- **[faggioli2023perspectives]** Faggioli et al. 2023. *Perspectives on Large Language Models for Relevance Judgment.* ICTIR 2023. arXiv:2304.09161.
- **[rahmani2024judges]** Rahmani et al. 2024. *Judging the Judges: A Collection of LLM-Generated Relevance Judgements.* arXiv:2502.13908.
- **[corbett2012spanner]** Corbett et al. 2012. *Spanner: Google's Globally-Distributed Database.* OSDI '12.
- **[gross2023pep703]** Gross 2023. *PEP 703 – Making the Global Interpreter Lock Optional in CPython.* https://peps.python.org/pep-0703/
- **[wang2021milvus]** Wang et al. 2021. *Milvus: A Purpose-Built Vector Data Management System.* SIGMOD '21. DOI:10.1145/3448016.3457550.
- **[qdrant]** Qdrant — https://github.com/qdrant/qdrant (open-source vector database, no peer-reviewed paper).
- **[ollama]** Ollama — https://github.com/ollama/ollama (open-source LLM runtime, no peer-reviewed paper).
- **[pymupdf]** PyMuPDF — https://github.com/pymupdf/PyMuPDF
- **[gcp2024vertex]** Google Cloud. 2024. *Get Batch Text Embeddings Predictions.* https://cloud.google.com/vertex-ai/generative-ai/docs/embeddings/batch-prediction-genai-embeddings
- **[dropbox2016magic]** Cowling 2016. *Inside the Magic Pocket.* Dropbox Tech Blog. https://dropbox.tech/infrastructure/inside-the-magic-pocket

---

## Writing TODO list

- [ ] Get full bibliography from cited papers
- [ ] Draw the system architecture diagram (Figure 1)
- [ ] Add quantitative curves: nDCG@10 for Nomic vs Vertex on test queries
- [ ] Add latency distribution plots for local vs remote Qdrant
- [ ] Clarify what counts as an "incident" (operator intervention required?)
- [ ] Ethics statement: this paper uses LLM-as-judge metrics — disclose
- [ ] Artifact statement: link to open-source code + eval harness
- [ ] Co-author list
- [ ] Venue selection (USENIX ATC vs ACM CACM vs IEEE Software)
- [ ] Camera-ready style: LaTeX template for target venue

## Next data to collect

- [x] Finished Nomic 100% run numbers (823,745 baseline vs 1,069,013 full) — collected 2026-04-13
- [x] Finished Vertex batch run (1,155,395 points, $6.26 measured) — collected 2026-04-13
- [ ] Vertex batch nDCG comparison vs Nomic — pending P4 eval sweep
- [ ] Cross-embedder Pareto curve (Nomic, Vertex, Gemini, Ollama mxbai) — pending P4 eval sweep
- [ ] Per-tenant cost breakdown (ISU vs PRT) — PRT blocked on post-Songkran harvester relaunch 2026-04-15
- [ ] MIT DSpace + arXiv CS comparison numbers — cheap add (~$14 combined) once the pipeline is touched again
