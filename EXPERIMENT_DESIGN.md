# Experiment Design: Multi-Model Embedding Strategies for Academic RAG

## Research Question
**How do different embedding models, dimension configurations, and ensemble strategies affect retrieval quality in a domain-specific academic RAG system?**

## Unique Contributions
1. **Real-world scale**: 97,767 academic PDFs (~3.74M chunks) from a live institutional repository
2. **Multi-model comparison**: Local open-source vs. commercial API models on identical corpus
3. **Ensemble/fusion strategies**: Novel approaches to combining multiple embedding spaces
4. **Domain-specific evaluation**: Academic paper retrieval (theses, articles, conference papers)
5. **Practical deployment insights**: Cost, latency, storage tradeoffs at scale

---

## Corpus

| Asset | Count |
|-------|-------|
| Total PDFs | 97,767 |
| Theses/Dissertations | 29,241 |
| Journal Articles | 51,199 |
| Conference Papers | 12,337 |
| Creative Components | 1,047 |
| Estimated chunks (500 tok, 100 overlap) | ~3,740,000 |
| Total text | ~1.5B tokens |

---

## Embedding Models Under Study

### Tier 1: Local Models (Ollama / LMStudio on RTX 4090)

| Model | Params | Dims | Max Ctx | MTEB Avg | Notes |
|-------|--------|------|---------|----------|-------|
| nomic-embed-text v1.5 | 137M | 768 | 8192 | 62.3 | Baseline local, already deployed |
| mxbai-embed-large | 335M | 1024 | 512 | 64.7 | High quality, short context |
| bge-m3 | 567M | 1024 | 8192 | 68.3 | Dense+sparse+multi-vector |
| snowflake-arctic-embed2 | 568M | 1024 | 8192 | 67.2 | Matryoshka, multilingual |
| qwen3-embedding:0.6b | 639M | 1-4096 | 32K | 65.8 | Variable dims, long context |
| qwen3-embedding:4b | 4B | 1-4096 | 40K | 69.1 | Best quality local, heavy |
| qwen3-embedding:8b | 8B | 1-4096 | 40K | 70.6 | SOTA local, very heavy |

### Tier 2: Cloud API Models

| Model | Dims | Max Ctx | MTEB Avg | Cost/1M chars |
|-------|------|---------|----------|---------------|
| Vertex text-embedding-005 | 768 | 3072 | 66.1 | $0.025 (online) / $0.0002 (batch) |
| OpenAI text-embedding-3-small | 1536 | 8191 | 62.3 | $0.02/1M tok |
| OpenAI text-embedding-3-large | 3072 | 8191 | 68.2 | $0.13/1M tok |

---

## Experiment Variables

### Independent Variables

1. **Embedding Model** (9 models above)
2. **Chunk Size**: 256, 512, 1024, 2048 tokens
3. **Chunk Overlap**: 0%, 10%, 20%, 50% of chunk size
4. **Embedding Dimensions** (for Matryoshka models): 128, 256, 512, 768, 1024, 2048, 4096
5. **Pooling Strategy** (LMStudio tuning): mean, cls, max, weighted-mean
6. **Query Instruction Prefix**: with/without task-specific prefix
7. **Document Type**: thesis vs article vs conference paper
8. **Ensemble Strategy**: single model vs fusion (see below)

### Dependent Variables (Metrics)

1. **Retrieval Quality**:
   - nDCG@5, nDCG@10, nDCG@20
   - MAP (Mean Average Precision)
   - MRR (Mean Reciprocal Rank)
   - Recall@K (K = 5, 10, 20, 50, 100)

2. **RAG Answer Quality** (end-to-end):
   - Answer relevance (LLM-as-judge)
   - Faithfulness (grounded in retrieved context)
   - Completeness (covers all aspects of query)

3. **Efficiency**:
   - Embedding throughput (chunks/sec)
   - Query latency (ms)
   - Storage per point (bytes)
   - Total cost ($)

---

## Ensemble / Fusion Strategies to Investigate

### Strategy A: Late Fusion (Score Combination)
Query each model's index separately, combine scores:
- **Linear combination**: α·score_model1 + (1-α)·score_model2
- **Reciprocal Rank Fusion (RRF)**: 1/(k + rank_model_i), sum across models
- **Learned weights**: Train α weights on validation set

### Strategy B: Early Fusion (Concatenated Embeddings)
- Concatenate embeddings from 2+ models into single vector
- Apply PCA/dimensionality reduction to combined space
- Example: nomic(768) + mxbai(1024) → concat(1792) → PCA(768)

### Strategy C: Matryoshka Dimension Sweeps
- Use qwen3-embedding with dims: 128, 256, 512, 1024, 2048, 4096
- Plot quality vs. storage/speed tradeoff curve
- Find the "elbow" — minimum dims for 95% of full quality

### Strategy D: Dense + Sparse Hybrid
- bge-m3 provides both dense AND sparse vectors
- Combine dense retrieval (semantic) with sparse retrieval (keyword/BM25)
- Weight: α·dense_score + (1-α)·sparse_score
- Compare against Qdrant's built-in hybrid search

### Strategy E: Document-Type-Specific Models
- Train/select different models per document type:
  - Model A for theses (long, detailed)
  - Model B for articles (medium, structured)
  - Model C for conference papers (short, focused)
- Route queries to appropriate model based on detected intent

### Strategy F: Hierarchical Retrieval
- Level 1: Abstract embeddings (already have 160K in Qdrant) — fast coarse filter
- Level 2: Full-text chunk embeddings — detailed re-ranking
- Compare: single-stage vs two-stage retrieval quality and latency

### Strategy G: Cross-Encoder Re-ranking
- Use embedding models for initial retrieval (top-100)
- Re-rank with cross-encoder model (e.g., ms-marco-MiniLM)
- Measure quality lift vs. latency cost

---

## Evaluation Framework

### Gold Standard: Human-Judged Query Set
Create 100 evaluation queries across domains:
- 20 CS/AI queries (e.g., "machine learning for crop yield prediction")
- 20 Engineering queries
- 20 Agriculture/Life Sciences queries
- 20 Social Sciences/Humanities queries
- 20 Cross-disciplinary queries

For each query:
1. Run through each model configuration
2. Collect top-20 results
3. Human judges rate relevance (0-3 scale)
4. Compute nDCG, MAP, MRR

### Automated Evaluation
- Use existing faculty research interests as "pseudo-queries"
- Expected results: papers by that faculty member should rank high
- 831 topics × models = automated benchmark

### LLM-as-Judge (End-to-End RAG)
- Feed top-5 chunks to Gemini/GPT-4 with query
- LLM judges: relevance, faithfulness, completeness
- Compare answer quality across embedding configurations

---

## LMStudio-Specific Experiments

### Parameter Tuning (not available in Ollama)
1. **Pooling strategy comparison**: mean vs cls vs max pooling
2. **Quantization impact**: f32 vs f16 vs q8_0 vs q4_0 on retrieval quality
3. **Batch size optimization**: throughput vs VRAM tradeoff
4. **Context window**: truncation vs sliding window for long documents

### Custom Model Configuration
- Load GGUF models with custom rope_scaling for extended context
- Test different attention implementations (flash attention, etc.)
- Profile VRAM usage across model sizes

---

## Execution Plan

### Phase 1: Baseline Embeddings (Days 1-3)
Run each of the 9 models on a representative sample (10,000 chunks):
- Measure throughput, quality, VRAM usage
- Eliminate clearly inferior models
- Select top 4-5 for full corpus

### Phase 2: Full Corpus Embedding (Days 4-7)
Run selected models on all 3.74M chunks:
- Ollama models: run sequentially on RTX 4090 (~1-2 days each)
- Vertex batch: submit one job ($1.50)
- Store each model's vectors in separate Qdrant collections

### Phase 3: Evaluation & Analysis (Days 8-14)
- Run 100-query evaluation across all configurations
- Compute metrics, generate comparison charts
- Test ensemble strategies
- Identify optimal single-model and ensemble configurations

### Phase 4: Paper Writing (Days 15-30)
- Write up methodology, results, analysis
- Create visualizations (quality vs cost Pareto frontier, etc.)
- Position contributions against related work

---

## Expected Outputs

1. **Qdrant Collections** (one per model):
   - `dspace_chunks_vertex005` (768d) — production baseline
   - `dspace_chunks_nomic` (768d)
   - `dspace_chunks_mxbai` (1024d)
   - `dspace_chunks_bge_m3` (1024d + sparse)
   - `dspace_chunks_qwen3_4b` (1024d)
   - `dspace_chunks_arctic2` (1024d)

2. **Evaluation Dataset**: 100 human-judged queries with relevance labels

3. **Research Paper**: "Multi-Model Embedding Strategies for Academic Repository RAG: A Comparative Study at Scale"

4. **Open-Source Toolkit**: Scripts for running the full experiment pipeline

---

## Related Work (to be expanded by research agents)

- MTEB Benchmark (Muennighoff et al., 2023)
- BEIR: A Heterogeneous Benchmark for Zero-Shot Evaluation (Thakur et al., 2021)
- Matryoshka Representation Learning (Kusupati et al., 2022)
- BGE M3-Embedding: Multi-Lingual, Multi-Functionality, Multi-Granularity (Chen et al., 2024)
- ColBERT: Efficient and Effective Passage Search (Khattab & Zaharia, 2020)
- RAG for Scientific Question Answering (various, 2024-2025)
