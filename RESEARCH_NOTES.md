# Research Notes: Multi-Model Embedding Strategies for Academic RAG

## Project Context

**System:** ISU DSpace RAG Search — a comprehensive search system for Iowa State University's Digital Repository (dr.lib.iastate.edu), covering 120,780 academic publications including theses, dissertations, journal articles, and conference papers.

**Principal Investigator:** Dr. Adisak Sukul, Department of Computer Science, Iowa State University

**Date Started:** 2026-04-10

---

## 1. System Architecture

### Data Pipeline
```
DSpace Repository (120,780 items)
  → Harvest (REST API + OAI-PMH)
  → Index (SQLite FTS5, 497 MB)
  → Knowledge Graph (SQLite, 350 MB, 224k entities, 765k edges)
  → Embedding (Qdrant vector store)
  → RAG Search (Vertex AI Gemini 2.5 Flash)
  → React Frontend
```

### Infrastructure
- **Backend:** FastAPI on GCP Cloud Run
- **Frontend:** React 19 + Vite on GCP Cloud Run
- **Vector Store:** Qdrant on GCP VM (35.188.64.146:6333)
- **LLM:** Google Vertex AI Gemini 2.5 Flash Lite
- **Embedding (production):** Vertex text-embedding-005 (768d)
- **Embedding (local/research):** Ollama on RTX 4090 24GB
- **Local workstation:** 64-core CPU (128 threads), 256 GB RAM, NVIDIA RTX 4090 24GB

### Data Sources
- **DSpace REST API:** Discovery search endpoint, paginated (100/page)
- **DSpace OAI-PMH:** Standard bulk harvest protocol (27,991 records harvested, server cap)
- **OpenAlex:** 74,356 ISU authors, 174,128 ISU works
- **Faculty scraping:** 40+ ISU centers, 7 colleges, faculty.sites.iastate.edu
- **A-Z Index audit:** 1,085 ISU sites cataloged, 63 new gaps identified

---

## 2. Corpus Statistics

### DSpace Repository (Complete)
| Metric | Count |
|--------|-------|
| Total items | 120,780 |
| With PDF bitstream | 97,767 (80.9%) |
| With abstract | 97,309 (80.6%) |
| With subjects | 103,109 (85.4%) |
| With department | 110,788 (91.7%) |
| With authors | 113,623 (94.1%) |

### By Collection
| Collection | Items | PDFs |
|-----------|-------|------|
| Publications | 63,908 | 54,946 |
| Theses and Dissertations | 34,532 | 29,241 |
| Conference Proceedings | 14,295 | 12,337 |
| Creative Components | 2,087 | 1,047 |
| Journal Issues | 3,525 | 0 |
| Other (6 collections) | 2,433 | 196 |

### Document Types (with PDFs)
| Type | Count | Avg Size Est. |
|------|-------|---------------|
| Articles | 51,199 | ~1.5 MB |
| Dissertations | 18,841 | ~5 MB |
| Theses | 10,400 | ~5 MB |
| Conference papers | 9,503 | ~0.5 MB |
| Reports | 4,532 | ~2 MB |
| Creative components | 1,047 | ~3 MB |
| Other | 2,245 | ~1 MB |

### Estimated Full-Text Volume
- **Total PDFs:** 97,767
- **Total text:** ~1.5 billion tokens
- **Estimated chunks (500 tok, 100 overlap):** ~3,740,000
- **Total download size:** ~290+ GB

### Faculty Database
| Metric | Count |
|--------|-------|
| Faculty records | 4,322 |
| With center affiliations | 831 (40 unique centers) |
| Matched to OpenAlex | 2,071 (49%) |
| With h-index | 1,974 |
| With personal site URL | 380 |
| Total citations (OpenAlex) | 9,957,857 |

### Knowledge Graph
| Entity Type | Count |
|-------------|-------|
| Papers | 120,780 |
| Authors | 98,530 |
| Faculty | 4,322 |
| Topics | 831 |
| Departments | 143 |
| Colleges | 41 |
| **Total entities** | **224,647** |
| **Total edges** | **765,320** |

---

## 3. Department Enrichment Study

### Problem
28,764 items (23.8%) in the DSpace index had no department field. These are primarily older publications, graduate student theses, and works by external collaborators.

### Methods Applied (in sequence)

| Round | Method | Items Enriched | Coverage After |
|-------|--------|---------------|----------------|
| 0 | Original harvest data | 92,016 | 76.2% |
| 1 | Faculty name cross-reference | +5,804 | 81.0% |
| 2 | Author-based propagation (majority vote) | +6,022 | 86.0% |
| 3a | OpenAlex ISU author lookup + propagation | +4,614 | 89.8% |
| 3b | Thesis advisor matching (OAI contributors) | +1,011 | 90.6% |
| 3c | DSpace author profiles + co-authorship | +1,321 | 91.7% |
| **Total** | | **+18,772** | **91.7%** |

### Key Findings
- **Author-based propagation** was the most effective single method (+6,022 items)
- **OpenAlex cross-reference** recovered an additional 4,614 items by matching against 74,356 known ISU authors
- **Advisor matching** was modest (+1,011) because many advisors were already in the faculty database
- **Remaining 9,992 items** (8.3%) have authors who don't appear anywhere else in the system — likely graduated students, external collaborators, or very old publications

### Conflict Resolution
- 655 item-level conflicts (multiple possible departments)
- 352 faculty-level conflicts (faculty with department + center affiliations)
- Admin dashboard built for manual resolution (Dept Conflicts tab)

---

## 4. Embedding Model Comparison

### Phase 1 Benchmark Setup
- **Sample:** 200 PDFs → 1,000 chunks (500 words, 100 overlap)
- **Hardware:** NVIDIA RTX 4090 (24 GB VRAM), 128-thread CPU, 256 GB RAM
- **Measurement:** throughput, VRAM, pairwise similarity spread, cross-model similarity

### Results

| Model | Params | Dims | Speed (chunks/s) | VRAM (MB) | Avg Pairwise Sim | Est. Full Corpus |
|-------|--------|------|-------------------|-----------|-------------------|------------------|
| nomic-embed-text | 137M | 768 | 84.7 | 4,813 | 0.5153 | 12h |
| snowflake-arctic-embed2 | 568M | 1024 | 27.9 | 7,419 | 0.2275 | 37h |
| bge-m3 | 567M | 1024 | 27.9 | 7,973 | 0.4360 | 37h |
| qwen3-embedding:0.6b | 639M | 1024 | 20.0 | 8,063 | 0.1839 | 52h |
| qwen3-embedding:4b | 4B | 2560 | 10.2 | 10,171 | 0.2136 | 102h |
| qwen3-embedding:8b | 8B | 4096 | 7.8 | 9,805 | 0.2820 | 133h |

### Key Observations

**1. Discrimination ability (lower AvgSim = better):**
- qwen3:0.6b (0.18) — best discrimination between documents
- snowflake-arctic-embed2 (0.23) — very good
- qwen3:4b (0.21) — very good
- nomic (0.52) — weakest (everything looks similar)

**2. Cross-model similarity:**
- Models produce **completely different** embedding spaces (cosine ~0.00 between models)
- Exception: arctic2 and bge-m3 are moderately similar (0.46)
- **This validates ensemble/fusion approaches** — each model captures genuinely different information

**3. Matryoshka Dimension Sweep (qwen3:4b):**

| Dimensions | Quality Preservation | Storage Ratio |
|-----------|---------------------|---------------|
| 128d | 87.3% | 5% |
| 256d | 97.3% | 10% |
| 512d | 102.8% | 20% |
| 1024d | 103.5% | 40% |
| 2048d | 103.0% | 80% |

**Finding:** 256 dimensions retain 97% of quality at 10% storage. The "elbow" is at 512d where quality actually exceeds the full embedding (noise filtering effect).

---

## 5. Adaptive Embedding Pipeline

### Problem
Initial embedding pipeline used single-threaded processing, resulting in 1-4% CPU utilization on a 128-thread workstation. GPU (RTX 4090) was also underutilized at 2-15%.

### Solution: Two-Phase Adaptive Pipeline

**Architecture:**
```
Phase A: PDF Text Extraction (CPU-bound)
  → ProcessPoolExecutor with N workers (bypasses Python GIL)
  → pdfminer.six for text extraction
  → Chunking (500 words, 100 overlap)

Phase B: Embedding (GPU-bound)
  → Ollama API with OLLAMA_NUM_PARALLEL
  → Batch size configurable
  → Upsert to Qdrant
```

**Adaptive Controller (AIMD-style):**
```
Every 5 minutes:
  1. Measure: throughput (PDFs/s), CPU%, GPU%, RAM%
  2. If CPU < 80% AND throughput stable/up → increase workers +10%
  3. If throughput dropped OR CPU > 85%   → decrease workers -10%
  4. Restart embed process with new worker count
  5. Log history for analysis
```

### Tuning History
(To be populated as the adaptive controller runs)

---

## 6. Literature Review

### Key Papers (23 papers surveyed)

**Core Finding: "General retrieval-optimized models substantially outperform domain-specialized models like SciBERT for scientific RAG"** — Amiri & Bocklitz 2025

#### Retrieval Quality
1. **Amiri & Bocklitz (2025)** — "Chunk Twice, Embed Once: Chemistry-Aware RAG" — First large-scale eval of 48 embedding models + 25 chunking strategies for scientific RAG. General models (Nomic, E5) beat domain-specific (SciBERT). arXiv:2506.17277

2. **IRPAPERS (2026)** — Scientific retrieval benchmark. Text retrieval with Arctic 2.0 + BM25 hybrid achieved 91% Recall@20. Text-based RAG outperformed image-based (0.82 vs 0.71 alignment). arXiv:2602.17687

3. **Legal RAG Bench (2026)** — "Retrieval sets the ceiling for RAG system performance." Domain-specific embedding improved correctness by 17.5 points. arXiv:2603.01710

4. **Caspari et al. (2024)** — "Beyond Benchmarks" — Mistral exhibits highest similarity to OpenAI models; best open-source alternative. Top-k similarity has high variance at low k. arXiv:2407.08275

#### Ensemble / Fusion
5. **Hybrid BM25 + Dense (multiple sources, 2024-2025)** — Dense-only ~78% recall@10, sparse-only ~65%, hybrid ~91%. RRF standard merging: score = 1/(k + rank) with k=60.

6. **T2-RAGBench (2025)** — Hybrid BM25 most effective for text+table data. Corpus size significantly impacts retrieval. arXiv:2506.12071

#### Matryoshka / Dimension Reduction
7. **Kusupati et al. (2022)** — Original Matryoshka Representation Learning. Up to 14x smaller at same accuracy. NeurIPS. arXiv:2205.13147

8. **Starbucks (2024)** — 2D Matryoshka: both layer depth AND dimensions. arXiv:2410.13230

9. **CSR (2025)** — Contrastive Sparse Representation outperforms MRL in accuracy and speed. arXiv:2503.01776

#### Fine-tuning
10. **REFINE (2024)** — Synthetic data + model fusion for domain adaptation. +5.79-6.58% Recall@3 without labeled data. arXiv:2410.12890

11. **Tamber et al. (2025)** — WARNING: naive InfoNCE fine-tuning can DEGRADE performance. Use listwise distillation instead. arXiv:2502.19712

12. **Late Chunking (2024)** — Jina AI. Process entire documents through long-context model before chunking. Preserves cross-chunk context. arXiv:2409.04701

#### Domain-Specific
13. **MoE Embeddings (2024)** — Contrastive learning + Mixture of Experts for multi-domain scientific text. N experts match N individually trained models. arXiv:2401.15713

### MTEB Leaderboard (as of 2026)

| Rank | Model | Retrieval nDCG@10 | Dims | Type |
|------|-------|-------------------|------|------|
| 1 | Gemini Embedding 001 | 67.71 | 3072 | API |
| 2 | NV-Embed-v2 | 62.65 | 4096 | 7.85B (NC) |
| 3 | Qwen3-Embedding-8B | ~62.0 | 4096 | 8B (Apache) |
| 4 | text-embedding-3-large | ~62.0 | 3072 | API |
| 5 | BGE-M3 | ~60.0 | 1024 | 568M (Open) |
| 6 | Nomic embed-text-v1.5 | ~58.0 | 768 | 137M (Open) |

---

## 7. Research Angles (Publishable)

### Angle 1: Matryoshka Dimension Optimization at Scale
**RQ:** What is the optimal embedding dimension for academic paper retrieval when balancing quality, storage, and latency?
- Sweep qwen3-embedding at 128/256/512/1024/2048/4096 dims
- Measure retrieval quality (nDCG@10) vs storage cost vs query latency
- **Novel:** Real-world scale (97k docs, 3.74M chunks) vs synthetic benchmarks

### Angle 2: Dense + Sparse Hybrid for Institutional Repositories
**RQ:** How much does hybrid search (dense + BM25/sparse) improve retrieval over dense-only in academic repositories?
- bge-m3 dual vectors vs Qdrant BM25 hybrid
- Compare: dense-only, sparse-only, hybrid (sweep α weights)
- **Novel:** On institutional repository with mixed document types

### Angle 3: Multi-Model Ensemble Fusion
**RQ:** Can combining cheap models via Reciprocal Rank Fusion match or exceed expensive single models?
- Ensemble: nomic + mxbai + arctic2 (all <600M params)
- Compare against: qwen3:8b (8B params, single model)
- RRF vs linear combination vs learned weights
- **Novel:** Cost-quality Pareto analysis at scale

### Angle 4: Document-Type-Aware Chunking
**RQ:** Should chunking strategy vary by document type in academic repositories?
- Thesis (long, structured) vs article (medium) vs conference paper (short)
- Chunk sizes: 256/512/1024/2048 tokens
- Late chunking vs standard chunking
- **Novel:** Document-type routing with separate optimal configs

### Angle 5: Hierarchical Two-Stage Retrieval
**RQ:** Does abstract-first → full-text-rerank improve both quality and latency?
- Stage 1: Abstract embeddings (existing 160k in Qdrant) — fast coarse filter
- Stage 2: Full-text chunk embeddings — detailed re-ranking
- Compare: single-stage vs two-stage quality and latency
- **Novel:** Leveraging existing abstract index as first stage

### Angle 6: LMStudio Parameter Ablation
**RQ:** How do embedding parameters (pooling, quantization, batch size) affect retrieval quality?
- Pooling: mean vs cls vs max vs weighted-mean
- Quantization: f32 vs f16 vs q8_0 vs q4_0
- Batch size vs quality tradeoff
- **Novel:** Systematic ablation study with practical deployment guidance

### Angle 7: Adaptive Resource Optimization for Embedding Pipelines
**RQ:** Can AIMD-style adaptive control optimize GPU/CPU utilization for large-scale embedding?
- Auto-tuning workers based on throughput feedback
- Two-phase pipeline: CPU extraction → GPU embedding
- **Novel:** Applying network congestion control concepts to ML pipelines

---

## 8. Experiment Design

### Evaluation Framework

**Gold Standard:** 100 human-judged queries across domains
- 20 CS/AI queries
- 20 Engineering queries  
- 20 Agriculture/Life Sciences queries
- 20 Social Sciences/Humanities queries
- 20 Cross-disciplinary queries

**Automated Evaluation:**
- Faculty research interests as pseudo-queries (831 topics)
- Expected: papers by that faculty should rank high
- nDCG@5, nDCG@10, nDCG@20, MAP, MRR, Recall@K

**LLM-as-Judge (End-to-End RAG):**
- Feed top-5 chunks to Gemini with query
- Score: relevance, faithfulness, completeness

### Qdrant Collections (one per model)
```
dspace_chunks          — Vertex 005 (768d) — production baseline (160k abstracts)
dspace_fulltext_nomic  — nomic-embed-text (768d) — full-text chunks
dspace_fulltext_mxbai  — mxbai-embed-large (1024d) — planned
dspace_fulltext_arctic2— snowflake-arctic-embed2 (1024d) — planned
dspace_fulltext_bge_m3 — bge-m3 (1024d + sparse) — planned
dspace_fulltext_qwen3  — qwen3-embedding:4b (multiple dims) — planned
```

---

## 9. Cost Analysis

### Embedding Cost Comparison (97,767 PDFs → 3.74M chunks)

| Model | Cost | Time | Quality (nDCG@10) |
|-------|------|------|---------|
| Vertex BATCH (768d) | $1.50 | 8h | 66.1 (Excellent) |
| Vertex online (768d) | $187 | 5h | 66.1 (Excellent) |
| OpenAI 3-small (1536d) | $37 | 3.5h | 62.3 (Good) |
| OpenAI 3-large (3072d) | $243 | 5h | 68.2 (Best) |
| Ollama nomic (768d) | FREE | 12h | ~58 (Good) |
| Ollama qwen3:4b (2560d) | FREE | 102h | ~62 (Very Good) |

### Infrastructure Costs
| Component | One-time | Monthly |
|-----------|----------|---------|
| PDF download (290 GB) | Free | — |
| GCS storage (253 GB) | — | $5.80 |
| Qdrant VM expansion | — | $5/mo |
| Vertex BATCH embedding | $1.50 | — |
| Cloud Run (backend+frontend) | — | ~$10 |
| **Total** | **$1.50** | **~$21** |

---

## 10. Timeline & Progress

### Session 2026-04-10 (Day 1)

| Time | Milestone |
|------|-----------|
| Start | System had 120,760 items, 160k Qdrant points, 4,294 faculty |
| +1h | Frontend: affiliations display, centers filter, KG page fix |
| +2h | Faculty reconciliation (4,294→4,322), 8 centers scraped |
| +3h | DSpace re-harvest launched (3 parallel agents) |
| +4h | Subject harvest: 22,469 CS/AI items across 25 subjects |
| +5h | OAI-PMH harvester built, 27,991 records, 106k subjects merged |
| +6h | Department enrichment: 76.2%→91.7% coverage (+18,772 items) |
| +7h | PDF download pipeline launched (97,767 PDFs, ~290 GB) |
| +8h | Embedding benchmark: 7 models compared on RTX 4090 |
| +9h | Literature review: 23 papers surveyed |
| +10h | Adaptive embedding controller launched |
| Ongoing | PDF download at ~85%, embedding in progress |

---

## 11. Files & Scripts Reference

### Core Scripts (run order for full rebuild)
```bash
cd backend
# Harvest
python scripts/harvest_dspace_community.py        # DSpace REST API harvest
python scripts/harvest_oai_pmh.py                 # OAI-PMH harvest (subjects)
python scripts/harvest_by_subject.py              # Subject-specific harvest
python scripts/index_dspace_items.py              # Build SQLite FTS5 index
python scripts/merge_oai_into_index.py            # Merge OAI subjects

# Faculty
python scripts/merge_faculty_sources.py           # Merge all faculty sources
python scripts/reconcile_faculty_names.py         # Deduplicate names
python scripts/match_faculty_openalex.py          # OpenAlex matching
python scripts/scrape_faculty_sites.py            # Faculty sites directory

# Centers
python scripts/scrape_centers.py                  # Generic center scraper
python scripts/scrape_trac_experts.py             # TrAC faculty experts
python scripts/scrape_centers_batch2.py           # IBC, IPIC, PSI
python scripts/scrape_centers_batch3.py           # CEAH, Catt, CFSPH
python scripts/scrape_nanovaccine_fix.py          # Nanovaccine WP API

# Enrichment
python scripts/enrich_departments.py              # Faculty→department cross-ref
python scripts/enrich_dept_openalex.py            # OpenAlex author lookup
python scripts/enrich_dept_advisors.py            # Thesis advisor matching
python scripts/enrich_dept_profiles.py            # DSpace profiles

# Knowledge Graph
python scripts/build_kg.py                        # Build KG from index+faculty
python scripts/reconcile_papers.py                # DSpace+OpenAlex paper reconciliation
python scripts/link_topics_to_papers.py           # Topic→paper via embeddings

# Embedding
python scripts/embed_abstracts_to_qdrant.py       # Abstract embeddings (Vertex)
python scripts/download_pdfs.py                   # Download PDFs from DSpace
python scripts/embed_pdfs_ollama.py               # Full-text embedding (Ollama)
python scripts/benchmark_embeddings.py            # Model comparison benchmark
python scripts/adaptive_embed_controller.py       # Auto-tuning controller
```

### Key Data Files
```
backend/data/
  dspace/
    dspace_index.db          # 497 MB — SQLite FTS5 index (120,780 items)
    kg.db                    # 356 MB — Knowledge Graph (224k entities)
    papers.db                # 343 MB — Canonical papers (232k)
    oai_harvest.jsonl        # 53.5 MB — OAI-PMH harvest (27,991 records)
    dspace_subject_harvest.jsonl  # Subject harvest (22,469 items)
  faculty.json               # 4,322 faculty records
  faculty_openalex_match.json # OpenAlex mappings
  faculty_sites_directory.json # 415 faculty site URLs
  department_conflicts.json   # 655 item + 352 faculty conflicts
  pdfs/                      # ~290 GB of downloaded PDFs
    conference-proceedings-and-presentations/
    theses-and-dissertations/
    publications/
    ...
  embed_state/
    embed_state_nomic.json   # Embedding progress state
    adaptive_tuning.json     # Auto-tuning history
```

### Test Results
```
tests/results/
  embedding_benchmark_results.json  # Phase 1 benchmark data
  benchmark_chunks.json             # Reproducible test chunks
```

---

## 12. Ideas for Future Work

1. **Fine-tuning with synthetic queries** — Use REFINE method to generate queries from our 120k documents, fine-tune a base model without human labels
2. **Cross-encoder re-ranking** — Use ms-marco-MiniLM as re-ranker on top of embedding retrieval
3. **Multimodal embedding** — Some PDFs contain figures/tables; test Cohere Embed v4 or similar
4. **Citation-aware embeddings** — Use co-citation data from OpenAlex to improve similarity
5. **Temporal analysis** — Track how embedding quality changes across publication years
6. **Department routing** — Route queries to department-specific sub-indexes
7. **Real-time incremental updates** — OAI-PMH incremental harvest + live embedding pipeline
8. **Evaluation with ISU faculty** — Have actual researchers judge retrieval quality
9. **Compare with Google Scholar / Semantic Scholar** — How does our RAG compare?
10. **Open-source the pipeline** — Release as a toolkit for other institutional repositories

---

*This document will be updated as the research progresses.*

---

## 13. Claude Semantic Chunking Results (2026-04-11)

### Experiment Setup
- 20 academic PDFs (mix of theses, articles, conference papers, poems)
- Strategy A: Naive fixed 500-word chunks with 100-word overlap
- Strategy B: Claude Opus 4.6 semantic chunking (section identification + summaries)
- Used Claude Max subscription (no API key needed)

### Results

| Metric | Naive (fixed 500w) | Claude Semantic |
|--------|-------------------|-----------------|
| Total chunks | 226 | 72 (68% fewer) |
| Avg chunks/doc | 11.3 | 3.6 |
| Avg words/chunk | 474 | 249 |
| Section labels | Generic (chunk_0, chunk_1) | Meaningful (Introduction, Methods, Results) |
| Summaries | None | 1-2 sentences per chunk |

### Key Observations
1. Claude produces 3x fewer but more semantically coherent chunks
2. Section labels enable section-aware retrieval (e.g., "find methods sections about X")
3. Summaries provide additional retrieval signal
4. Shorter chunks (249w) are more precise but may miss cross-section context
5. OCR-degraded old theses challenge both approaches
6. Front matter/TOC content is correctly identified and separated by Claude

### Research Implications
- Semantic chunking could improve precision at cost of recall
- Combining naive (high recall) + semantic (high precision) via fusion may be optimal
- LLM chunking cost is significant for large corpora but could be applied selectively
- Section labels enable new retrieval patterns not possible with naive chunking

---

## 14. Multi-Core CPU Parallelization Lessons (2026-04-11)

### The Problem: Python GIL Limits Threading

Initial implementation used `ThreadPoolExecutor` with 32 threads on a 64-core/128-thread Threadripper PRO 5995WX. Despite high "100% CPU" readings at single sample points, **averaged CPU was only 8%** with **only 2 cores actually working**.

### Root Cause Analysis

Python's Global Interpreter Lock (GIL) ensures only ONE thread executes Python bytecode at a time, regardless of how many threads are spawned. This limits CPU-bound workloads like PDF text extraction (pdfminer is CPU-intensive Python code) to effectively a single core.

**ThreadPoolExecutor only helps with I/O-bound tasks** (network calls, disk reads where threads release the GIL). PDF extraction is mostly CPU-bound parsing, so threading provides minimal speedup.

### Misleading Monitoring

Single-point CPU sampling via `psutil.cpu_percent(interval=0.5)` gave wildly inconsistent readings (0-100%) because it captured momentary GIL states. The adaptive auto-tuner was making decisions based on noisy data.

**Lesson**: Always use averaged sampling over multiple seconds for CPU/GPU utilization in production monitoring:

```python
cpu_avg = psutil.cpu_percent(interval=3)  # 3-second average
cores_active = sum(1 for c in psutil.cpu_percent(percpu=True) if c > 10)
```

### The Solution: True Multi-Process Parallelism

Built `embed_multiprocess.py` that spawns N **independent Python subprocess** workers via `subprocess.Popen`. Each process:
- Has its own GIL
- Gets its own slice of PDF UUIDs
- Runs the full extraction → chunking → embedding → upsert pipeline
- Writes its own state file

```python
# Slice work across N processes
chunk_size = len(remaining) // num_processes + 1
for i in range(num_processes):
    slice_uuids = remaining[i*chunk_size:(i+1)*chunk_size]
    proc = subprocess.Popen([sys.executable, "worker.py", slice_file, ...])
```

### Results: Dramatic Improvement

| Metric | Threading (32 threads) | Multiprocess (16 procs) |
|---|---|---|
| CPU avg | 8% | **100%** |
| Active cores | 2 | **70-90** |
| Throughput | ~200 PDFs/5min | ~3,000 points/min |
| Qdrant points | +5k/cycle | **+30k/cycle** |
| Estimated speedup | 1x | **~10-15x** |

### Why ProcessPoolExecutor Failed

Initial attempt used `ProcessPoolExecutor` from `concurrent.futures`, but pdfminer objects don't pickle cleanly on Windows, causing crashes. The subprocess approach (writing slice files, spawning fresh `python.exe` processes) avoids pickling entirely — each process loads its own data.

### Local Qdrant: 10x Faster Writes

Switched from remote Qdrant on GCP VM (35.188.64.146:6333, 50-100ms latency per upsert) to **local Qdrant in Docker** (localhost:6334, <1ms latency). Combined with multiprocessing, this removed the network bottleneck.

```bash
docker run -d --name qdrant-local -p 6334:6333 \
  -v "D:/.../qdrant-local-data:/qdrant/storage" qdrant/qdrant
```

Sync to remote can happen later via `sync_qdrant.py`.

### Key Takeaways for the Paper

1. **Monitor what matters**: averaged metrics, not point-in-time
2. **Python GIL is real**: threading is for I/O, multiprocessing is for CPU
3. **Test parallelism**: spawn many cheap processes if pickling fails
4. **Local vector DB**: use during heavy ingestion, sync to cloud later
5. **Resource isolation**: separate CPU-bound (extraction) from GPU-bound (embedding) phases

### Architecture Evolution

```
v1: Single-threaded         → 1 PDF/s, 1 core
v2: ThreadPoolExecutor x32  → 1 PDF/s, 2 cores (GIL bottleneck)
v3: ProcessPoolExecutor     → CRASHED (pickling errors)
v4: subprocess.Popen x16    → 47 points/s, 70-90 cores ✓
```

### Future Optimization Ideas

1. **Adaptive scaling**: AIMD-style controller that increases process count based on AVERAGED CPU (not point-in-time)
2. **GPU pipeline**: dedicated GPU worker that accepts pre-extracted text via queue, eliminating CPU/GPU contention
3. **Cython for pdfminer**: replace pdfminer.six with PyMuPDF (10x faster)
4. **Streaming chunks**: write chunks as soon as one PDF completes instead of batching
5. **Memory-mapped Qdrant**: use Qdrant's mmap mode for even faster local writes
6. **Disk I/O optimization**: D: drive on Dropbox-synced folder may add latency vs pure local SSD


---

## 15. Claude Opus 4.6 Capabilities for the Research Pipeline

### What Claude Can Do (Beyond Traditional NLP)

#### High-Value Research Tasks (publishable)

1. **LLM-as-Judge Retrieval Evaluation**
   - Feed Claude (query + top-K retrieved chunks) → score relevance 0-3
   - Build automatic evaluation framework for 100+ queries × 6 models
   - Standard methodology in modern RAG papers (Ragas, ARES, etc.)
   - No human labeling needed for first-pass evaluation

2. **Synthetic Query Generation (REFINE method)**
   - Generate test queries from documents
   - 5-10 queries per representative document type
   - Creates ground truth eval set without manual labor
   - Can be cited: REFINE (arXiv:2410.12890), 2024

3. **Section-Aware Semantic Chunking**
   - Already demonstrated on 20 docs (Section 13)
   - Could expand to 500-1000 for full comparison study
   - 3 strategies: naive vs semantic vs enhanced
   - Compare retrieval quality across chunking strategies

4. **Cross-Encoder Re-ranking Simulation**
   - Use Claude as "free cross-encoder" 
   - Re-rank top-100 → top-10 from embedding retrieval
   - Compare against actual cross-encoders (ms-marco-MiniLM)
   - Measure quality lift vs latency cost

#### Data Quality Improvements

5. **Faculty Disambiguation** (for OpenAlex confidence=0.55 matches)
   - 1,603 ambiguous matches need resolution
   - Claude reads author name + paper title + co-authors
   - Decides which OpenAlex profile is correct
   - Result: cleaner faculty bibliometric data

6. **Department Conflict Resolution**
   - 655 item conflicts in admin dashboard
   - Claude reads paper title + authors + departments
   - Picks best department assignment
   - Reduces admin workload to zero

7. **Title/Abstract OCR Repair**
   - Older theses have mangled OCR
   - Claude can recognize garbled text and reconstruct
   - "Tcc hnoo logyy" → "Technology"
   - Improves search quality for historical documents

8. **Topic Clustering & Normalization**
   - 831 topics, many redundant ("ML" + "Machine Learning" + "machine learning")
   - Claude clusters semantically similar topics
   - Could reduce to ~400-500 canonical topics
   - Cleaner KG topic→paper edges

### Available Tools/Skills

| Tool | Use Case |
|------|----------|
| **Agent (sub-agents)** | Parallel batch processing — already used for chunking |
| **WebFetch / WebSearch** | DOI lookups, arXiv citations, metadata enrichment |
| **HuggingFace MCP** | Search competing benchmarks, find new models |
| **Browser automation (Playwright)** | Scrape JS-rendered sites |
| **Skills: claude-api, schedule, simplify, loop** | Build custom workflows |
| **Monitor** | Background watching (already used) |

### Architectural Insight: Hybrid LLM + Vector Search

The literature (especially Tamber et al. 2025, Caspari et al. 2024) shows pure dense retrieval has plateau quality. **Combining LLM-based reasoning with vector retrieval** is the next frontier:

- **Retrieve** with embedding model (fast, recall)
- **Re-rank** with LLM (slow, precision)  
- **Synthesize** with LLM (extract answer)

Claude can play 2 of these 3 roles. Current production uses Gemini for synthesis; Claude could be added for re-ranking.

### Research Paper Sections This Enables

1. **Methodology** — "We use Claude Opus 4.6 as an LLM-judge to evaluate retrieval quality across 100 synthetic queries..."
2. **Results** — Quantitative comparison of 6 embedding models with statistical significance
3. **Ablation** — Effect of LLM-based re-ranking on top-k precision
4. **Discussion** — Trade-offs of LLM-augmented retrieval (cost, latency, quality)
5. **Reproducibility** — Open-source the eval framework + synthetic queries

---

## 16. Production Issues & Recovery Journey (2026-04-11/12)

This section documents real-world operational issues encountered building a production-scale embedding pipeline, and the recovery approaches used. These are the kinds of issues rarely discussed in academic RAG papers but critical for reproducibility and practical deployments.

### Issue 1: Python GIL Masquerading as 100% CPU

**Symptom:** Task Manager showed 100% CPU on cores under ThreadPoolExecutor, but averaged utilization was only 8% with just 2 cores actually working.

**Root cause:** Single-point `psutil.cpu_percent(interval=0.5)` sampling captured momentary GIL holds. Python's GIL serializes bytecode execution, so even with 32 threads, only ~1 core runs Python code at a time.

**Lesson:** Always use multi-second averaged sampling for resource monitoring:
- `psutil.cpu_percent(interval=3)` — 3-second average
- `psutil.cpu_percent(percpu=True)` — per-core visibility
- Count cores with >10% as "active"

**Fix:** Switched from `ThreadPoolExecutor` to subprocess-based multiprocessing (spawning N independent Python processes via `subprocess.Popen`). Each process has its own GIL. Result: CPU went from 8% to 100% (70-90 active cores).

### Issue 2: Ollama Model Unloading Kills Workers

**Symptom:** After 20+ minutes of successful embedding, all 16 worker processes hung simultaneously. Qdrant writes stopped. 120 zombie Python processes.

**Root cause:** Ollama automatically unloads models after ~5 minutes of inactivity to free VRAM. When multi-process workers hit a slow extraction batch, Ollama unloaded nomic-embed-text. Subsequent embed requests triggered a model reload, but with 16 concurrent requests hitting during reload, Ollama deadlocked.

**Fix:** Pre-load the model with 24-hour keep_alive via POST to `/api/embed` with `"keep_alive":"24h"`. Also reduced workers from 16 to 8 — more conservative parallelism sustained by Ollama's request queue without overwhelming it.

### Issue 3: pdfminer Infinite Hangs on Corrupt PDFs

**Symptom:** Extraction progress stalled at ~12k PDFs with no errors — just stopped producing output. Workers appeared alive but idle.

**Root cause:** pdfminer.six has no built-in timeout. Corrupt or malformed PDFs (especially old scanned documents with broken font tables) could hang indefinitely in the parser.

**Fix:** Wrap extraction in a 30-second timeout using `concurrent.futures.ThreadPoolExecutor(1)` + `future.result(timeout=30)`. Combined with: skip files >50 MB, skip pages beyond 30, skip extractions with <50 chars returned.

### Issue 4: ProcessPoolExecutor Pickling Failures

**Symptom:** Attempted `concurrent.futures.ProcessPoolExecutor` to bypass GIL. Crashed immediately with pickling errors.

**Root cause:** pdfminer.six internal objects (PDFDocument, PSLiteral, etc.) contain references to file handles and C extensions that don't pickle cleanly on Windows.

**Fix:** Use subprocess-based parallelism instead:
1. Write slice files (JSON with UUIDs) for each worker
2. Spawn `python worker.py slice_file.json` as a fresh Python process
3. Worker loads its own data independently — no pickling needed
4. Communicate results via JSON state files

### Issue 5: Dropbox File Lock Race Conditions

**Symptom:** State file writes would occasionally fail with PermissionError when Dropbox was indexing the file.

**Root cause:** The working directory is inside a Dropbox folder. Dropbox has file watchers that can briefly lock files during sync.

**Fix:** Atomic writes with fallback — write to `.tmp`, then rename. Fall back to direct write on PermissionError.

### Issue 6: State File Out of Sync with Qdrant

**Symptom:** After restarting workers, Qdrant had 186,388 points but the state file showed only 46,873 processed PDFs. The multiprocess master was killed before collecting worker `_done.json` files.

**Root cause:** Workers wrote Qdrant points in real time but only updated state on completion. If the master process dies, worker completions aren't collected.

**Fix:** Rebuild state from Qdrant by scrolling all points and collecting unique UUIDs from payloads. Discovered that 186,388 points = 14,604 unique UUIDs × ~12.8 chunks per PDF (normal ratio for academic papers).

### Issue 7: Misleading Qdrant RED Status

**Symptom:** Qdrant reported `status: red` during high-throughput ingestion.

**Root cause:** Qdrant red status means `indexed_vectors_count < points_count` — HNSW index hasn't caught up with writes. Normal during bulk ingestion and resolves automatically.

**Lesson:** Check Qdrant health via `/readyz` endpoint, not the status field.

### Issue 8: Subprocess Stdout Buffering

**Symptom:** Worker processes appeared to hang — no progress messages for 2+ hours. But Qdrant was growing, proving they were working.

**Root cause:** subprocess.Popen with stdout=PIPE buffers output. Without flush=True in child and unbuffered stdin in parent, progress messages never arrive at monitor.

**Fix:** Set `PYTHONUNBUFFERED=1` in env, use `sys.stdout.flush()` after prints in workers.

### Issue 9: Docker Qdrant Local vs Remote Performance

**Observation:** Writing to remote Qdrant (GCP VM) was 50-100x slower than local Docker Qdrant. Network round-trip dominated.

**Measurements:**
- Remote Qdrant: ~100 ms per upsert, ~10 points/sec
- Local Qdrant: ~1 ms per upsert, ~1000 points/sec

**Architecture:** Use local Qdrant for ingestion, sync to remote periodically via `sync_qdrant.py`.

### Issue 10: Vertex Online API 125x More Expensive Than Batch

**Discovery:** Built Vertex online embedding script thinking it was cheap. Verified pricing and discovered:
- Online API: $0.025 per 1M characters
- Batch API: $0.0002 per 1M characters (125x cheaper)

For 7.5B characters (97k PDFs): $187 vs $1.50.

**Fix:** Built batch-mode script that:
1. Extracts all chunks to JSONL locally
2. Uploads JSONL to GCS
3. Submits BatchPredictionJob via `google.cloud.aiplatform`
4. Waits for async completion (~2-3 hours on Google's infrastructure)
5. Downloads result JSONL, ingests embeddings

**Lesson:** Always check batch API availability before using online for large jobs.

### Summary Table: Issues & Fixes

| # | Issue | Fix | Impact |
|---|-------|-----|--------|
| 1 | GIL limits threading | subprocess multiprocessing | 10x speedup |
| 2 | Ollama unloading models | keep_alive:24h preload | Eliminates hangs |
| 3 | pdfminer infinite hangs | 30s timeout per PDF | Eliminates stalls |
| 4 | ProcessPoolExecutor pickling | subprocess.Popen slices | Robust parallelism |
| 5 | Dropbox file locks | Atomic tmp-then-rename | No data loss |
| 6 | State out of sync | Rebuild from Qdrant scroll | Recovered 14k UUIDs |
| 7 | Qdrant red status | Ignore during ingestion | No panic needed |
| 8 | Subprocess buffering | PYTHONUNBUFFERED=1 | Real-time progress |
| 9 | Remote Qdrant latency | Local Docker + sync | 100x faster writes |
| 10 | Vertex online pricing | Batch API with GCS | 125x cheaper |

### Recovery Strategies Learned

1. **State should be reconstructable from primary data** (Qdrant), not the only source of truth
2. **Atomic writes** for state files protect against partial writes
3. **Preload models** instead of relying on auto-load (which can deadlock)
4. **Timeouts everywhere** — on HTTP, subprocess, file reads
5. **Monitor by averages**, not point-in-time samples
6. **Test at scale early** — these issues don't appear on 100-PDF test runs
7. **Design for restart** — every script should be able to pick up where it left off

### Research Paper Relevance

These are the gaps in current RAG literature:
- Most papers report metrics but not operational challenges
- "How we scaled it" sections are rare but critical for reproducibility
- Parallelism and resource utilization are treated as trivial but actually dominate performance
- Cost optimization (batch API vs online) is often missed entirely

Our contribution: a practical guide for institutional RAG deployments alongside the quantitative benchmarks. This is publishable as a systems paper or as an appendix to the main results paper.

### Chronological Journey (this session)

1. **Started**: single-thread embedding, 1 PDF/s, 1 core
2. **Threaded**: ThreadPoolExecutor x32, still 1 PDF/s, 2 cores (GIL bottleneck)
3. **ProcessPool attempt**: crashed (pickling errors)
4. **subprocess.Popen**: 16 workers, hit Ollama deadlock after 20 min
5. **Preloaded model + 8 workers**: stable, 70-90 cores active
6. **Added timeouts**: eliminated pdfminer hangs
7. **State rebuild from Qdrant**: recovered from master crash
8. **Local Qdrant**: 100x faster writes
9. **Vertex batch API discovery**: 125x cost reduction
10. **Current state**: 53% done, 222k local points, all pipelines healthy

---

## 17. UTF-8 / Internationalization Standard (2026-04-12)

As the platform expands from ISU (English) to PRT (Thai) and beyond, UTF-8 must be enforced everywhere. Documented as `backend/platform/i18n.py` — mandatory for all scripts.

### The Problem

Python on Windows defaults to `cp1252` for stdout/stderr, which can't print Thai characters:
```
UnicodeEncodeError: 'charmap' codec can't encode characters in position 15-34
```

Similarly, `json.dump()` defaults to `ensure_ascii=True`, which escapes Thai into `\u0e23\u0e30\u0e40...` sequences — bloats files and makes them unreadable.

### The Standard

Every script must call `setup_utf8()` at the top:
```python
from platform.i18n import setup_utf8
setup_utf8()
```

This sets:
- `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`
- `os.environ["PYTHONIOENCODING"] = "utf-8"`
- `os.environ["PYTHONUTF8"] = "1"`

### Required Practices

1. **File I/O**: Always `open(path, encoding="utf-8")`
2. **JSON**: Always `json.dump(data, f, ensure_ascii=False)` for writes
3. **Print**: Set stdout encoding once at startup, then just `print()`
4. **Normalize**: Use `normalize_text()` to strip control chars but preserve Unicode
5. **Chunk**: Use `chunk_text_multilingual()` with language detection

### Language Support

| Language | Code | Tokenizer | Status |
|----------|------|-----------|--------|
| English | eng | Simple split() | ✅ |
| Thai | tha | pythainlp (newmm) | ✅ |
| Chinese | zho | jieba (planned) | ⏳ |
| Vietnamese | vie | underthesea (planned) | ⏳ |
| Khmer | khm | khmer-nltk (planned) | ⏳ |

### Test: Thai Tokenization Works

```python
from pythainlp.tokenize import word_tokenize
word_tokenize('ระเบียบวาระการประชุมสภาผู้แทนราษฎร', engine='newmm')
# → ['ระเบียบวาระการประชุม', 'สภาผู้แทนราษฎร']
```

Two semantic units correctly identified despite no spaces.

### Buddhist Era Date Conversion

Thai documents use Buddhist Era (พุทธศักราช / พ.ศ. / BE):
- BE = CE + 543
- `buddhist_era_to_gregorian(2567)` → 2024
- `buddhist_era_to_gregorian(2477)` → 1934 (early PRT records)

---

## 18. OpenScribe — Research Paper Outline (2026-04-12)

**Working title:** *OpenScribe: Cost-Aware Adaptive Cascades for OCR on Degraded Multilingual Archives via LLM Rescue and Deep-Learning-Inspired Training Dynamics*

**Alternate titles under consideration:**
- *Rescuing the Long Tail: Adaptive Hybrid OCR for Low-Resource Archival Corpora*
- *Broken Glyphs, Golden Repairs: Bandit-Driven Vision-LM Escalation for Archival OCR*
- *Beyond the OCR Plateau: Learning When to Call the Expensive Model*

**Target venues (in priority order):**
1. EMNLP / NAACL (main, NLP systems track) — "adaptive cascade" framing
2. ACL Findings — safer target for hybrid pipeline paper
3. JCDL (Joint Conference on Digital Libraries) — archives angle
4. SIGIR demo track — MCP server + Claude Skills artifact

### 18.1 Core Claims

1. **Cost-quality Pareto:** OpenScribe dominates every static baseline on the cost-quality frontier for archival OCR.
2. **Long tail economics:** 90-95% of archival pages are solved by classical OCR; the remaining tail dominates total quality cost. A learned cascade captures 99%+ of LLM-only quality at ~3-8% of LLM-only cost.
3. **Downstream feedback:** Using retrieval quality and LLM-judge scores (not CER against a static gold set) as the training signal lets OpenScribe optimize for the actual downstream task, not a proxy.
4. **Transferable training dynamics:** Early stopping, dropout calibration, and curriculum learning — mechanisms developed for neural-network training — transfer cleanly to OCR cascade control.
5. **Packaging as primitives:** OpenScribe ships as a pip library, an MCP server, and Claude Skills, so any archive can deploy hybrid OCR without writing controller code.

### 18.2 Why This Is Novel

- First cascade that combines **classical OCR + vision LMs** with a **learned routing policy** and **downstream feedback**.
- First paper to treat **OCR engine selection as a contextual bandit** with cost constraints.
- First benchmark on **historical Thai parliamentary records** (1934–present, heavy scan degradation).
- First application of **DL-inspired training dynamics (early stopping, dropout, curriculum)** to OCR cascade control.
- First OCR framework published **as an MCP server + Claude Skills artifact**, targeting the agent ecosystem directly.

### 18.3 Dataset: Parliamentary Repository of Thailand

- 436,394 items, 59 communities, 482+ sets
- Date range: Buddhist Era 2477 (1934 CE) → present
- Languages: primarily Thai (`dc:language = tha`), some English mixed
- Document types: meeting agendas (ระเบียบวาระ), bill drafts (ร่างพระราชบัญญัติ), constitution drafts (ร่างรัฐธรรมนูญ), parliamentary questions (กระทู้ถาม), motions (ญัตติ)
- Scan quality distribution (estimated from samples):
  - 2010-present: modern born-digital PDFs, clean text layer (~40%)
  - 1990-2010: scans + OCR text layer of varying quality (~25%)
  - 1970-1990: typewriter-era scans, no text layer (~20%)
  - 1934-1970: ink-bleed, stamps, handwritten annotations, ceremonial text (~15%)
- Cultural significance: the only full public archive of Thai legislative history; currently unsearchable by content

### 18.4 Methodology

**Phase A — Baseline collection (weeks 1-2)**
- Run static cascade (Paddle → Claude via Vertex) on 10,000 pages stratified by decade
- Log everything: per-page confidence, cost, latency, escalation decision, downstream retrieval score

**Phase B — Gold labeling (week 3)**
- Manually label 200 pages with ground truth transcriptions (decade-stratified)
- Establishes CER ceiling for LLM-only and floor for classical-only

**Phase C — LLM-judge (week 4)**
- Run Claude Sonnet 4.6 as judge on a 2% random sample of extracted pages
- Score 0-3 on: readability, factual preservation, script fidelity, format preservation

**Phase D — Controller training (weeks 5-6)**
- ε-greedy, Thompson sampling, contextual bandit — three policy variants
- Train offline from Phase A logs + Phase C judge scores
- A/B test on held-out 5,000-page batch

**Phase E — Full ingest (weeks 7-10)**
- Run winning policy on remaining ~420k items
- Record total cost, final per-decade quality, policy convergence

**Phase F — Ablations + writeup (weeks 11-12)**
- Remove dropout, remove cost weight, remove contextual features, vary thresholds
- Generate Pareto plots

### 18.5 Expected Results (predictions)

These are the numbers the paper needs to hit to be publishable:

| Baseline | Quality (LLM-judge 0-3) | Cost ($ per 1M pages) |
|---|---|---|
| Paddle only | ~1.7 | ~$5 |
| Tesseract only | ~1.3 | ~$5 |
| Claude only | ~2.8 | ~$140,000 |
| Static cascade | ~2.5 | ~$7,000 |
| **OpenScribe (ε-greedy)** | ~2.6 | ~$4,000 |
| **OpenScribe (Thompson)** | ~2.65 | ~$3,500 |
| **OpenScribe (contextual bandit)** | ~2.75 | ~$3,000 |

Targets:
- **≥40× cost reduction** vs Claude-only at ≥95% of Claude-only quality
- **≥2× quality improvement** vs Paddle-only on pre-1990 documents
- **Sub-linear cost scaling** on larger corpora (learned policy gets cheaper per page as sample size grows)

### 18.6 Ablation Studies

1. **Dropout calibration ablation** — remove it; expect reward estimates for expensive engines to go stale after ~1000 pages
2. **Cost weight sweep** — λ ∈ {0, 1, 10, 100}; show Pareto curve
3. **Quality threshold sweep** — threshold ∈ {0.7, 0.85, 0.95}; show tradeoff
4. **Contextual features** — remove year / DPI / language features one at a time
5. **Number of engines** — 2 vs 3 vs 5 engines in cascade
6. **Cross-tenant transfer** — train on ISU, deploy to PRT; measure how much controller retraining helps
7. **Era curriculum** — train from easy (modern) to hard (pre-1970) vs random order

### 18.7 Related Work to Cite

**Classical OCR**
- Smith (2007) — Tesseract overview
- Du et al. (2020) — PP-OCR / PaddleOCR
- Jaided AI (2022) — EasyOCR

**LLM-as-OCR**
- Gemini 1.5 Technical Report (2024) — PDF understanding
- Anthropic (2024) — Claude vision capabilities
- Nougat (Blecher et al., 2023) — specialized OCR transformer

**Ensemble OCR**
- Wemhoener et al. (2013) — classical ensemble voting
- Lund et al. (2014) — confidence-weighted OCR merge

**Adaptive LLM routing (not OCR)**
- RouteLLM (Ong et al., 2024)
- FrugalGPT (Chen et al., 2023)
- HybridLLM (Ding et al., 2024)

**Contextual bandits**
- Li et al. (2010) — LinUCB
- Agarwal et al. (2014) — Thompson sampling in practice
- Russo & Van Roy (2018) — Tutorial on Thompson sampling

**Thai NLP / digital archives**
- pythainlp project overview
- Thai Computational Linguistics Laboratory papers
- (nothing substantial yet on Thai archival OCR — **gap that OpenScribe fills**)

### 18.8 Artifact / Open Source

- **GitHub:** `github.com/<user>/openscribe` (permissive license — MIT or Apache 2.0)
- **Pip:** `pip install openscribe`
- **MCP server:** `openscribe-mcp` — tools for `ocr_page`, `ocr_pdf`, `evaluate_ocr_quality`, `chunk_semantic`
- **Claude Skills:** `ocr-thai-archival`, `ocr-mixed-script`, `ocr-handwritten-english`, `ocr-tables-forms`
- **Benchmark release:** the PRT 200-page gold set, stratified by era and document type, published with CC BY 4.0

### 18.9 Risks to the Paper

- **PaddleOCR on Thai might already be good enough** — if the baseline is too high, cost savings shrink. Mitigation: the pre-1970 segment should still be terrible for Paddle, and that's where we win.
- **LLM-judge is correlated with the LLM doing extraction** — same-family bias. Mitigation: use GPT-4 or Gemini as independent judge on a subset; report agreement.
- **Thompson sampling might not beat ε-greedy on a short run** — bandit convergence requires sample size. Mitigation: evaluate at multiple batch sizes and show where each policy wins.
- **Dropout calibration might be a rounding error** — 5% of expensive escalations wasted. Mitigation: measure the reward variance reduction it produces; frame as regularization with a known cost.
- **GCS costs, Vertex rate limits, Claude quota** — real operational concerns. Mitigation: design experiments to use < $500 of Vertex credits; negotiate with Anthropic for research credits.

### 18.10 Related Research Papers to Spin Out

OpenScribe is big enough that it can generate multiple papers:

1. **OpenScribe main paper** — the framework + PRT benchmark
2. **"MCP Tools for Document Understanding"** — systems paper on exposing complex pipelines to agents
3. **"Downstream-Feedback OCR"** — just the feedback-loop idea, isolated and benchmarked
4. **"Thai Parliamentary Corpus"** — dataset paper for the corpus alone
5. **"Cost-Aware Cascades for Vision LMs"** — general formulation, not OCR-specific
6. **"Bandits for Engine Selection in ML Pipelines"** — controller alone as a library

### 18.11 Naming Rationale

**OpenScribe** — the name captures the two load-bearing ideas:

- **Open** — open-source, open-provider (any engine plugs in via the Engine interface), open to any document type or language. Matches the naming pattern of OpenAI, OpenCLIP, OpenResearch, etc., which signals "permissionless, extensible, community".
- **Scribe** — the ancient profession of copying texts. A scribe transcribes; OpenScribe automates that profession for corpora classical OCR has always left unreadable. Evocative without being literal: the framework doesn't need to be renamed if it later grows to handle handwriting, table extraction, or multimodal layout.

Chosen over earlier candidates (CHAKRA, ATHENA, ATRIUM) because:
1. **Easily remembered in American English** — no cultural/mythological translation required
2. **Low collision risk in OCR literature** (checked arXiv, Google Scholar, PyPI — no major existing paper or package)
3. **Matches agent-ecosystem product naming** — reads correctly next to `claude-mcp`, `openai-gym`, `huggingface-transformers`
4. **Future-proof** — works for any document-understanding extension without rebranding
5. **Maps cleanly to packaging artifacts** — `pip install openscribe`, `openscribe-mcp`, `openscribe.Pipeline`, skill `openscribe-thai-archival`


