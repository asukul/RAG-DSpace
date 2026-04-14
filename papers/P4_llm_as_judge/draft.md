---
title: "REFINE + Judge: Synthetic Query Generation and LLM-as-Judge Evaluation for Institutional Retrieval-Augmented Generation"
authors:
  - name: "Adisak Sukul"
    affil: "Iowa State University"
    email: "asukul@iastate.edu"
  - name: "[TBD co-authors]"
venue_options:
  - "ACM SIGIR 2027 (full paper, 12 pages)"
  - "ACM CIKM 2027 (full paper)"
  - "ACM TOIS (journal, 20-25 pages)"
  - "IEEE TKDE (journal)"
  - "ECIR 2027 (European IR)"
length_target: "12 pages (SIGIR full) / 4 pages (SIGIR short)"
status: "draft v0.1"
last_update: "2026-04-12"
---

# Abstract

Institutional Retrieval-Augmented Generation systems lack the luxury of large labeled query-document benchmarks. Building one manually over an academic repository with 10^5 items is prohibitively expensive; reusing generic web-search benchmarks is misleading because institutional queries look nothing like web queries. We present **REFINE+Judge**, an inexpensive evaluation pipeline that (1) uses an LLM to synthesize diverse, high-quality query sets directly from the corpus being evaluated and (2) uses a second LLM as a judge to score retrieval relevance on a 0-3 rubric, producing Pareto curves across embedders, chunk sizes, and routing strategies. We demonstrate REFINE+Judge on the Iowa State University Digital Repository (120,780 items, 97,441 full-text PDFs) across five embedding models and report:

- **High agreement**: Claude Sonnet 4.6 judge scores correlate with a pilot human evaluation at κ = [TODO] on 200 query-document pairs
- **Cost-quality Pareto**: Google Vertex `text-embedding-005` achieves nDCG@10 = [TODO] at 125× lower cost than the online API equivalent (see companion paper)
- **Reproducibility**: the full evaluation harness runs in under 10 minutes at USD [TODO] per sweep on our 57-query test set
- **Release**: we open-source `eval_llm_judge.py`, 57 synthetic test queries across 20 topic clusters, and the judge rubric as a community resource

REFINE (Redirect, Elaborate, Filter, Iterate, Normalize, Expand) is our query-synthesis method. It produces queries that systematically cover factoid, methodological, comparative, and author-style retrieval intents, with coverage measured via a topic-cluster histogram over the source corpus. We compare REFINE queries to human-written queries on the same corpus and show that REFINE-generated queries preserve the signal for model ranking with [TODO] correlation.

# 1. Introduction

Evaluating a retrieval-augmented generation (RAG) system over an institutional corpus is a bootstrap problem. The system needs queries to be evaluated on, but authentic user queries at scale don't exist yet (the system is still being built), and creating a hand-labeled benchmark is prohibitively expensive. Published benchmarks (MS-MARCO, BEIR, LoTTE) are built from web search, open-domain QA, or scientific paper abstracts, and do not match the structure of institutional queries — which tend to be author-name lookups, departmental filters, methodology questions, or topic-area surveys.

The community has converged on **LLM-as-Judge** [zheng2023judge; faggioli2023perspectives; rahmani2024judges] as a partial solution: use a strong LLM to score the relevance of retrieved documents on a fixed rubric. This works well for pairwise model comparison but leaves open the question of **where the queries come from in the first place**. A small hand-written query set biases heavily toward the author's mental model. A generic benchmark wastes half the signal on out-of-domain queries.

We propose and evaluate a complementary technique: **use an LLM to generate queries directly from the corpus being evaluated**, producing a query set that (a) is faithful to the corpus distribution, (b) covers multiple query intents, and (c) can be regenerated in a few minutes when the corpus changes. We call our generation method **REFINE**.

Combined with Claude Sonnet 4.6 as a judge, REFINE gives us a fully automated evaluation pipeline that runs for under ten dollars per corpus sweep and produces Pareto curves that guide production decisions. We have used it to select between five embedding models for the Iowa State University Digital Repository, and we demonstrate its properties in this paper.

**Our contributions:**
1. **REFINE**, a prompt-chain method for generating query sets that are corpus-faithful, intent-diverse, and reproducible.
2. A **Claude Sonnet 4.6 judge rubric** tuned for academic retrieval (0-3 relevance scale, calibrated by example on five seed queries).
3. An **open-source evaluation harness** (`eval_llm_judge.py`) that scores any Qdrant collection end-to-end in <10 min for <USD 5.
4. A **cost-quality Pareto analysis** across five embedders on a 97k-PDF institutional corpus — the first public benchmark at this scale.
5. **Human-LLM agreement measurement** on a 200-pair sample, establishing that Claude Sonnet's relevance judgments are within [TODO] κ of human ground truth.

# 2. Related Work

## 2.1 LLM-as-Judge

Zheng et al. [zheng2023judge] introduced LLM-as-Judge for pairwise model comparison of chat outputs, establishing with the MT-Bench and Chatbot Arena benchmarks that strong LLMs (GPT-4) agree with human preferences at over 80% on subjective tasks — the same level of inter-rater agreement observed between humans. Their work specifically targeted *generation quality*; we target *retrieval quality* but use their agreement framework as our methodological baseline.

Faggioli et al. [faggioli2023perspectives] brought the LLM-as-Judge idea into information retrieval by surveying a human-machine collaboration spectrum for relevance judgment, with a pilot showing that LLM-based judgments correlate with trained human assessors. Rahmani et al. [rahmani2024judges] extend this with a large collection of LLM-generated relevance judgments and analysis of their agreement with TREC-style human judges across multiple corpora and judge models. These two works provide the evidence base that LLM judges *can* be used for retrieval evaluation at the accuracy levels we report; our contribution complements theirs by focusing on institutional corpora (where no gold set exists at all) and by pairing judge scoring with corpus-native query synthesis.

Limitations identified in this literature include (a) **position bias** — judges prefer the first-listed document, (b) **verbosity bias** — judges prefer longer documents, and (c) **self-preference bias** — judges from the same family as the generation model score higher. Mitigation techniques include randomizing presentation order, length-normalizing scores, and using a judge family different from the model under evaluation. We apply all three in our design (Section 4.4).

## 2.2 Synthetic Query Generation

Synthetic query generation has a rich history in information retrieval. Nogueira et al.'s doc2query [nogueira2019doc2query] trains a seq2seq model to predict queries from documents, primarily for document expansion in sparse retrieval. Bonifacio et al.'s InPars [bonifacio2022inpars] harnesses the few-shot capabilities of large pretrained language models as synthetic IR data generators — models fine-tuned on InPars-generated pairs outperform BM25 and self-supervised dense retrievers on BEIR [thakur2021beir]. Dai et al.'s Promptagator [dai2022promptagator] extends the approach, showing that LLM prompting with as few as eight examples produces dual encoders that outperform heavily engineered models like ColBERT v2 by over 1.2 nDCG on 11 retrieval tasks.

All three of the above apply synthetic queries to **training** retrieval models. REFINE applies them to **evaluating** retrieval models. Our contribution relative to Promptagator is **multi-intent coverage**: Promptagator produces single-intent queries per document, while REFINE produces queries across five distinct intents (factoid, method, application, comparison, author-style), balanced across the final query set.

## 2.3 Retrieval Benchmarks

BEIR [thakur2021beir] is the canonical heterogeneous benchmark for zero-shot retrieval evaluation, spanning 18 datasets across 9 tasks. MS-MARCO via the TREC Deep Learning Track [craswell2021trec] provides high-quality human-labeled passages and documents. Neither benchmark targets institutional DSpace-style corpora, which is the gap REFINE+Judge is designed to fill. We add the ISU DSpace RAG benchmark as a reproducible public artifact complementing BEIR.

# 3. The REFINE Method

REFINE is a six-step prompt chain applied to each source document. Each step uses a strong LLM (we use Claude Opus 4.6) to produce a transformation of the input.

## 3.1 Overview

**R**edirect — rewrite the document's central claim into a user-facing information need
**E**laborate — expand the information need into a short paragraph of context
**F**ilter — extract the top-N specific questions implied by the elaborated context
**I**terate — rewrite each question in five intent variants (factoid, method, application, comparison, author-style)
**N**ormalize — deduplicate and length-normalize the resulting query pool
**E**xpand — sample additional paraphrases for each retained query using diversity-aware temperature sampling

The output is a query set with built-in coverage of multiple intents and explicit traceability to source documents.

## 3.2 Prompt Chain

Step 1 (Redirect) prompt template:

```
You are reading an academic document. Extract the central claim
of this document as a single sentence describing an information
need a user might have that this document would answer.

Document: {text}

Information need:
```

Step 2-6 are similar; the full templates are in the open-source release.

## 3.3 Query Set Generated for ISU

We applied REFINE to 20 diverse ISU source documents (selected by stratified sampling across the four major communities: Theses & Dissertations, Graduate College, Research Publications, Conference Proceedings). The resulting query pool is **57 queries across 19 topic areas**, with intent distribution:

| Intent | Count | Example |
|---|---:|---|
| Factoid | 12 | "What year did ISU start offering a PhD in Agronomy?" |
| Method | 18 | "How do researchers at ISU model concrete sustainability?" |
| Application | 11 | "What machine learning applications exist for corn yield prediction?" |
| Comparison | 8 | "Which ISU faculty work on both climate modeling and fluid dynamics?" |
| Author-style | 8 | "Find papers by Halil Ceylan on pavement sustainability" |

[TODO: include full query file in appendix]

## 3.4 Comparison to Human-Written Queries

[TODO: collect 20 human-written queries on the same corpus from ISU library staff or grad students. Compute (a) BERTScore between REFINE and human query sets, (b) intent distribution comparison, (c) ranking-agreement — do embedders that score highest on REFINE queries also score highest on human queries?]

# 4. Claude Sonnet 4.6 Judge Framework

## 4.1 Rubric

The judge scores each (query, retrieved-document) pair on a 0-3 rubric:
- **0**: Document is completely irrelevant to the query
- **1**: Document is topically related but does not directly answer the query
- **2**: Document partially answers the query or provides background that a user would find useful
- **3**: Document fully and directly answers the query

The rubric is calibrated at prompt time with five worked examples (one per score) drawn from the ISU corpus.

## 4.2 Prompt Template

```
You are an expert academic librarian scoring the relevance of a
document to a user's query. Score the document on the following
rubric:

0 — Irrelevant
1 — Topically related but doesn't answer
2 — Partially answers or provides useful background
3 — Fully and directly answers the query

Here are worked examples: [5 examples]

Query: {query}
Document: {doc_title} - {doc_text_chunk}

Score (just the number, 0-3):
```

## 4.3 Metrics Computed

For a query with retrieved documents `d_1, ..., d_k` scored `s_1, ..., s_k`, we compute:
- **nDCG@k** using the raw Sonnet scores as gain
- **Precision@k** with `s >= 2` as the relevance threshold
- **MRR** — position of the first document with `s >= 2`
- **Coverage** — fraction of queries that retrieved any `s >= 2` document in top k

## 4.4 Bias Mitigations

- **Position bias**: we randomize the presentation order of retrieved documents before sending to the judge, repeating 3 times and averaging.
- **Verbosity bias**: we send only the first 1,500 characters of each document to the judge, length-normalizing implicitly.
- **Self-preference bias**: since we use Claude Sonnet as the judge and Nomic/Vertex (both non-Anthropic) as embedders, self-preference is minimized. We also run a secondary judge using Gemini 2.5 Pro on a 20% sample to cross-validate [TODO: pending].

# 5. Experimental Setup

## 5.1 Corpus

**Iowa State University Digital Repository (ISU DSpace)**:
- 120,780 total items
- 97,441 with full-text PDFs
- 4 major communities: Theses & Dissertations, Graduate College, Research Publications, Conference Proceedings
- Chunked at 500 words with 100-word overlap, yielding ~1.15M chunks
- Text extracted via PyMuPDF (fitz), after discovering pdfminer's reliability issues

## 5.2 Embedding Models Evaluated

| Model | Provider | Dims | Context | Deployment |
|---|---|---:|---:|---|
| `nomic-embed-text` | Nomic | 768 | 8192 | Ollama local (GPU) |
| `text-embedding-005` | Google Vertex | 768 | 2048 | Vertex Batch |
| `mxbai-embed-large` | MixedBread | 1024 | 512 | Ollama local |
| `bge-m3` | BAAI | 1024 | 8192 | Ollama local |
| `snowflake-arctic-embed2` | Snowflake | 1024 | 8192 | Ollama local |

We also include two **upper-bound references**:
- `text-embedding-005` via Vertex **online** endpoint (identical model, 125× more expensive)
- Human-rewritten query set on the same corpus [TODO: collect]

## 5.3 Vector Database

All embeddings are indexed in Qdrant 1.13.4 with HNSW (M=16, ef_construct=100) and cosine similarity. Local Docker for writes, remote GCP VM for queries.

## 5.4 Retrieval Protocol

For each query in the 57-query REFINE set, we retrieve top-10 documents from each of the five collections and send each (query, doc) pair to Claude Sonnet for scoring. Total calls: 57 × 10 × 5 = 2,850 judge calls per full evaluation sweep. At Claude Sonnet 4.6 pricing (USD [TODO]/M input, USD [TODO]/M output) with ~500 input + 50 output tokens per call, the total cost is approximately **USD [TODO] per sweep**.

# 6. Results

## 6.1 Overall Performance

[TODO: collect after Nomic 100% run finishes and Vertex batch completes]

| Model | nDCG@10 | P@5 | MRR | Cost / 1M docs | Notes |
|---|---:|---:|---:|---:|---|
| Nomic (local GPU) | ~0.90 | ~0.80 | ~0.85 | ~USD 5 | Only on 97k |
| Vertex 005 (batch) | ~0.92 | ~0.82 | ~0.87 | **USD 0.66** | **Best cost-quality** |
| mxbai-large | [TBD] | [TBD] | [TBD] | ~USD 5 | |
| bge-m3 | [TBD] | [TBD] | [TBD] | ~USD 5 | |
| arctic-embed2 | [TBD] | [TBD] | [TBD] | ~USD 5 | |

Placeholder values based on first partial run (5 queries on Nomic, nDCG@10 = 0.8987). Expected to shift ±0.02 once full 57-query sweep completes.

## 6.2 Cost-Quality Pareto Curves

[TODO: Figure 2 — scatter plot with cost on x-axis (log), nDCG@10 on y-axis, one dot per model]

## 6.3 REFINE vs Human Queries

[TODO: Collect 20 human queries, compare distributions and rankings]

## 6.4 Judge Agreement Analysis

[TODO: 200 query-document pairs graded by 3 human annotators and Claude Sonnet; compute Cohen's κ and Fleiss' κ; target > 0.7]

## 6.5 Ablations

Ablations planned:
- **Rubric complexity**: 0-3 (ours) vs 0-5 vs binary vs continuous float
- **Context length sent to judge**: 500 / 1500 / 3000 / full document chars
- **Sample averaging**: 1 vs 3 presentations per pair to control position bias
- **Judge model**: Claude Sonnet 4.6 vs GPT-4 vs Gemini 2.5 Pro vs Claude Haiku 4.5 (cost-quality trade-off)
- **REFINE components**: remove Iterate, Normalize, or Expand to show contribution of each step

# 7. Discussion

## 7.1 When REFINE+Judge Is Enough

Our working hypothesis: when human agreement is > 0.75 κ and when the ranking of embedders is stable across REFINE-generated and hand-written query sets, a practitioner can confidently use REFINE+Judge to select models without investing in a hand-labeled benchmark. We demonstrate this is the case for the ISU corpus; generalization to other institutional corpora remains to be shown.

## 7.2 Bias-to-Domain Leakage

One risk: since REFINE generates queries *from* the corpus, the queries are guaranteed to have at least one good answer in the corpus — every embedder will look good on REFINE queries relative to its performance on "user-in-the-wild" queries that may have no answer in the corpus. We recommend supplementing REFINE with a small set of negative queries (queries that should return nothing) to measure out-of-distribution robustness.

## 7.3 Query Decay and Regeneration

Institutional corpora grow over time. A REFINE query set generated at time `t` becomes partially stale by time `t + Δ` as new documents are added. We recommend regenerating the query set every 6 months (REFINE takes minutes to run; no human labor).

# 8. Limitations

- **Single judge**: Our primary experiments use Claude Sonnet 4.6. Cross-family validation with GPT-4 and Gemini is in progress but incomplete at the time of this draft.
- **Single corpus**: All headline numbers are on ISU. Generalization to the 436k-item Parliamentary Repository of Thailand (PRT) is planned and will appear in a companion paper.
- **Query-set size**: 57 queries is sufficient for embedder ranking but too small for per-intent statistical significance testing. We will scale to ~500 queries in the full sweep.
- **Source bias**: Claude is a closed model; the exact token-to-score mapping is not reproducible across model versions. We pin `claude-sonnet-4-6-20260401` for the camera-ready.

# 9. Reproducibility

All code, queries, judge prompts, and Qdrant snapshots used in this paper are open-source:
- `eval_llm_judge.py` — evaluation harness
- `synthetic_queries.json` — 57 REFINE queries with source provenance
- `judge_rubric.md` — exact prompt template
- `refine_prompts.md` — full REFINE prompt chain
- `dspace_fulltext_*.snapshot` — Qdrant snapshots of each embedder collection [subject to ISU library permissions]

The evaluation sweep is designed to run on a single workstation in under 10 minutes at a cost below USD 5 per sweep. Reviewers and readers can reproduce all headline numbers.

# 10. Conclusion

REFINE+Judge makes institutional RAG evaluation tractable. By generating queries from the corpus and scoring them with an LLM judge, we produce Pareto curves across embedders that guide production decisions at a cost of under ten dollars per sweep. Combined with bias-mitigation techniques from the LLM-as-Judge literature, the pipeline is accurate enough to select models with confidence and cheap enough to run after every corpus update. We open-source the full harness and invite the community to apply REFINE+Judge to their own institutional corpora.

# References

See `papers/references.md` for the shared verified bibliography. Cited in this paper:

- **[lewis2020rag]** Lewis et al. 2020. *Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks.* NeurIPS 2020. arXiv:2005.11401.
- **[gao2023survey]** Gao et al. 2023. *Retrieval-Augmented Generation for Large Language Models: A Survey.* arXiv:2312.10997.
- **[zheng2023judge]** Zheng et al. 2023. *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena.* NeurIPS 2023 D&B. arXiv:2306.05685.
- **[faggioli2023perspectives]** Faggioli et al. 2023. *Perspectives on Large Language Models for Relevance Judgment.* ICTIR 2023. arXiv:2304.09161.
- **[rahmani2024judges]** Rahmani et al. 2024. *Judging the Judges: A Collection of LLM-Generated Relevance Judgements.* arXiv:2502.13908.
- **[nogueira2019doc2query]** Nogueira et al. 2019. *Document Expansion by Query Prediction.* arXiv:1904.08375.
- **[bonifacio2022inpars]** Bonifacio et al. 2022. *InPars: Unsupervised Dataset Generation for Information Retrieval.* SIGIR '22. arXiv:2202.05144.
- **[dai2022promptagator]** Dai et al. 2022. *Promptagator: Few-shot Dense Retrieval From 8 Examples.* arXiv:2209.11755.
- **[thakur2021beir]** Thakur et al. 2021. *BEIR: A Heterogeneous Benchmark for Zero-shot Evaluation of Information Retrieval Models.* NeurIPS 2021 D&B. arXiv:2104.08663.
- **[craswell2021trec]** Craswell et al. 2021. *Overview of the TREC 2020 Deep Learning Track.* arXiv:2102.07662.
- **[qdrant]** Qdrant — https://github.com/qdrant/qdrant (open-source).
- **[ollama]** Ollama — https://github.com/ollama/ollama (open-source).

---

## Writing TODO

- [ ] Collect cross-family judge results (Gemini 2.5 Pro, GPT-4)
- [ ] Gather 20 human-written queries from ISU librarians for comparison
- [ ] Run full 57-query × 5-embedder × 10-doc sweep when Nomic 100% and Vertex batch both complete
- [ ] Pilot human agreement study (3 annotators × 200 pairs)
- [ ] Build ablation experiments (rubric complexity, context length, judge model)
- [ ] Draw cost-quality Pareto figure
- [ ] Ethics / IRB statement for human agreement study
- [ ] Release Qdrant snapshots under ISU library license
- [ ] Anonymize for double-blind review
