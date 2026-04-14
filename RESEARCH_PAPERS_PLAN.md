# Research Paper Portfolio Plan

**Date:** 2026-04-12
**Status:** Draft v1
**Goal:** Group the research assets produced by this project into a focused set of papers, each targeted at a specific top venue (IEEE, ACM, AAAI families preferred).

---

## Assets Available

From the ISU DSpace RAG project we now have these research-grade assets:

1. **OpenScribe framework** — adaptive OCR cascade (PaddleOCR + Claude + fitz) with bandit routing, DL-inspired training dynamics (early stopping, dropout, cost budgets)
2. **PRT corpus** — 436k-item Thai parliamentary archive, 1934-present, Buddhist-Era dates, mixed scripts (harvest in progress)
3. **Vertex batch pipeline** — 125× cost reduction vs online API, shipped + validated
4. **Local Nomic pipeline** — 8 subprocess workers, 128× speedup after GIL fix
5. **LLM-as-Judge evaluation framework** — 57 synthetic queries, REFINE generation, Claude Sonnet scoring 0-3
6. **Knowledge graph** — 224k entities, 765k edges built from 120k DSpace items + OpenAlex linking
7. **Faculty disambiguation pipeline** — 4,322 ISU faculty reconciled across centers and OpenAlex
8. **Multi-tenant SaaS architecture** — tenants/isu + tenants/prt config-driven, Pydantic schema
9. **Production war stories** — 10 recovery incidents documented in RESEARCH_NOTES §16
10. **OpenScribe as MCP server + Claude Skills** — first agent-ecosystem OCR tool
11. **OpenScribe benchmark workload** — 8,516 image-only ISU PDFs naturally partitioned for OCR testing
12. **Thai NLP pipeline** — pythainlp tokenization, BE→CE conversion, cross-lingual UTF-8 standard

---

## Paper Portfolio — 8 Papers Clustered by Topic

| # | Working Title | Lead Contribution | Primary Venue | Status |
|---|---|---|---|---|
| P1 | **OpenScribe**: Adaptive Hybrid OCR for Degraded Multilingual Archives | Cost-aware cascade with DL-inspired routing + PRT benchmark | ACL / EMNLP / NAACL main | Core ready, waiting on PRT data |
| P2 | **Scaling Institutional RAG**: Engineering Lessons from a 100k-Document Deployment | Operational war stories + quantitative metrics | ACM CACM / USENIX ATC / IEEE Software | Data complete, writing phase |
| P3 | **Cost-Quality Cascades** for Hybrid Classical-LLM Pipelines | General theory of contextual bandits for engine selection | NeurIPS / ICML / AAAI | Empirical work in progress |
| P4 | **LLM-as-Judge** with Synthetic Queries for Academic RAG Evaluation | REFINE query synthesis + Claude Sonnet judge framework | ACM SIGIR / CIKM / TOIS | Framework shipped, ready to write |
| P5 | **Institutional Knowledge Graphs** from Academic Repositories | 224k entity KG construction + OpenAlex linking + faculty disambiguation | ISWC / ACM TOIS / IEEE TKDE | Data complete, analysis pending |
| P6 | **PRT-Corpus**: A 436k-Item Archive of Historical Thai Parliamentary Documents | Dataset paper — benchmark tasks, splits, baselines | LREC-COLING 2028 / Scientific Data | Awaiting harvest completion |
| P7 | **Multi-Tenant RAG-as-a-Service**: A Reference Architecture for Academic Libraries | Config-driven tenant isolation + cost-aware pipelines | JCDL / IEEE Software / D-Lib | Architecture mature |
| P8 | **Document Understanding as Agent Tools**: An MCP-based Architecture | openscribe-mcp + Claude Skills as reusable agent primitives | ACL/EMNLP demo track / ACM IUI / UIST | Prototype shipped |

---

## Per-Paper Details

### P1. OpenScribe — The Flagship Technical Paper

**Working title:** *OpenScribe: Cost-Aware Adaptive Cascades for OCR on Degraded Multilingual Archives via LLM Rescue and Deep-Learning-Inspired Training Dynamics*

**Main claims:**
1. Adaptive engine routing via contextual bandits beats static thresholds on the cost-quality Pareto frontier
2. DL-inspired training dynamics (early stopping, dropout, cost budgets) transfer cleanly from neural net training to OCR cascade control
3. Downstream task feedback (retrieval quality, LLM-judge) is a better training signal than CER against static gold
4. 30-50× cost reduction vs LLM-only OCR at ≥95% of LLM-only quality on the PRT benchmark

**Target venues** (rank-ordered by fit):

| Venue | Type | CORE / IF | Fit |
|---|---|---|---|
| **EMNLP** | A* conf | H5:152, CORE A* | Strong — NLP systems + multilingual + real benchmark |
| **ACL** | A* conf | H5:174, CORE A* | Strong — same scope, slightly more prestigious |
| **NAACL** | A* conf | H5:110, CORE A* | Good — smaller field, higher acceptance rate |
| **IEEE/ACM TASLP** | Journal | IF ~4.8 (2024) | Good — if extended to 25+ pages |
| **ACM SIGIR** | A* conf | H5:102, CORE A* | Moderate — if we emphasize the retrieval-feedback contribution |
| **ACL Findings** | A* | Acceptance cushion | Safety net — same venue but lower bar |

**Length target:** 12 pages (ACL main) or 8 pages (findings)

**Still needed:**
- PRT PDFs (waiting on origin to return)
- 200-page manually-labeled gold set for CER comparison
- LLM-judge sample of 2% across baselines
- Ablation runs on dropout rate, cost weight, quality threshold
- Full PRT ingest results

**Realistic timeline:** Submission Dec 2026 → EMNLP 2027

---

### P2. Scaling Institutional RAG — The Engineering Experience Paper

**Working title:** *Scaling Retrieval-Augmented Generation: Engineering Lessons from a 100k-Document Institutional Deployment*

**Main claims:**
1. Python GIL dominates embedding pipelines more than model size — subprocess.Popen fix = 10× speedup, matters even more at multi-tenant scale
2. Vertex Batch API is 125× cheaper than online for the same embedding quality — a cost discovery that changes deployment economics
3. Hybrid local+cloud vector DB architectures (local Qdrant + periodic sync) outperform pure cloud on ingestion latency by 100×
4. Adaptive resource controllers (AIMD from networking) work for GPU/CPU utilization on ML workloads
5. 10 distinct production incidents and their root causes — grounded taxonomy for institutional RAG practitioners

**Target venues:**

| Venue | Type | IF / Rank | Fit |
|---|---|---|---|
| **ACM CACM** (Communications of the ACM) | Magazine | IF ~11 | Ideal — practitioner audience, experience reports welcome |
| **USENIX ATC** | A* conf | CORE A* | Experience paper track accepts real deployments |
| **IEEE Software** | Journal | IF ~3.6 | Practitioner magazine, good for lessons-learned |
| **ACM SoCC** (Symposium on Cloud Computing) | A conf | CORE A | Systems + ML hybrid papers |
| **IEEE BigData** (Industrial track) | Conf | CORE B | Industrial deployments welcome |
| **ACM Queue** | Magazine | N/A | Practitioner magazine, shorter form |

**Length target:** 15-20 pages (CACM) or 12 pages (conference)

**Already have:** §16 RESEARCH_NOTES (10 incidents), §18.5 predicted numbers, quantitative speedup data

**Realistic timeline:** Can draft in 2-4 weeks of focused writing. Submission Oct 2026 → review cycle ~3 months.

---

### P3. Cost-Quality Cascades — General ML Theory Paper

**Working title:** *Learning to Route: Contextual Bandits for Cost-Aware Cascades in Hybrid Classical-LLM Pipelines*

**Main claims:**
1. General formulation: engine selection as a cost-constrained contextual bandit with hierarchical actions
2. Thompson sampling + page features (era, DPI, script ratio) outperforms epsilon-greedy by X% at same cost
3. Reward shaping from downstream task quality (not just intrinsic metrics) improves sample efficiency
4. Cross-domain transfer: policy trained on one archive generalizes to another with Y% fine-tuning

**Target venues:**

| Venue | Type | CORE | Fit |
|---|---|---|---|
| **NeurIPS** | A* conf | H5:261 | Strong if we nail theory + empirical |
| **ICML** | A* conf | H5:178 | Same |
| **ICLR** | A* conf | H5:228 | Good — open-science culture, adaptive algorithms welcome |
| **AAAI** | A* conf | H5:144 | **Great fit** — applied AI systems, feedback loops |
| **IJCAI** | A* conf | CORE A* | Similar to AAAI |
| **AISTATS** | A conf | CORE A | If we have the theory |
| **JMLR** | Journal | IF ~4.3 | Long-form journal version |
| **Machine Learning Journal (Springer)** | Journal | IF ~4.3 | Same |

**Length target:** 9 pages (NeurIPS) / 9 pages (AAAI)

**Still needed:** Rigorous bandit-regret analysis, cross-domain transfer experiments, more baselines

**Realistic timeline:** Submission Sep 2026 → NeurIPS 2027 or AAAI 2027

---

### P4. LLM-as-Judge for Academic RAG — IR/Evaluation Paper

**Working title:** *Synthetic Queries and LLM-as-Judge Evaluation for Institutional Retrieval-Augmented Generation*

**Main claims:**
1. REFINE query synthesis produces query sets that correlate with human judgments at r ≥ 0.85
2. Claude Sonnet 4.6 as judge agrees with human graders at κ ≥ 0.75 on 0-3 retrieval relevance
3. Per-embedding-model Pareto curves (nDCG@10 vs cost) for Nomic, Vertex, Gemini, Ollama
4. A minimal, open-source evaluation harness (eval_llm_judge.py + synthetic_queries.json) reproduces at ≤$5/run

**Target venues:**

| Venue | Type | IF / Rank | Fit |
|---|---|---|---|
| **ACM SIGIR** | A* conf | CORE A* | **Perfect fit** — flagship IR venue |
| **ACM CIKM** | A conf | CORE A | Same area, easier target |
| **ACM TOIS** (Transactions on IS) | Journal | **IF 9.1** (2024, +70%) | Top-tier IR journal |
| **IEEE TKDE** | Journal | **IF 11.60** (2024) | Top data engineering journal |
| **ACM WSDM** | A conf | CORE A | Web search + data mining |
| **ECIR** | B/A- conf | CORE B | European IR, good acceptance |
| **SIGIR Short Paper / Demo** | A* | A* short | Faster path |

**Length target:** 12 pages (SIGIR full) or 4 pages (SIGIR short)

**Already have:** eval_llm_judge.py, 57 synthetic queries across 20 docs, first baseline run (nDCG@10 = 0.8987 on Nomic)

**Still needed:** Second judge (Gemini or GPT-4 for cross-family validation), human-vs-LLM κ measurement on a subset, more models benchmarked

**Realistic timeline:** Can draft in 4-6 weeks. SIGIR 2027 submission Jan 2027.

---

### P5. Institutional Knowledge Graphs — KG Construction Paper

**Working title:** *Building Institutional Knowledge Graphs at Scale: Entity Disambiguation and OpenAlex Linking from 120k Repository Items*

**Main claims:**
1. End-to-end pipeline for transforming DSpace/OAI repositories into queryable KGs
2. Faculty disambiguation across multi-source names (DSpace authors, center directories, OpenAlex) with precision ≥ 0.95
3. Topic clustering deduplication at paper level using Matryoshka embeddings
4. Open-sourced KG builder (`build_kg.py`) reusable for any DSpace-7 deployment

**Target venues:**

| Venue | Type | CORE / IF | Fit |
|---|---|---|---|
| **ISWC** (Intl Semantic Web Conference) | A conf | CORE A | Strong — KG construction is their canonical topic |
| **ACM TOIS** | Journal | **IF 9.1** | Info systems angle |
| **IEEE TKDE** | Journal | **IF 11.60** | Data engineering focus |
| **Semantic Web Journal** | Journal | IF ~3.4 | Specialized KG venue |
| **JCDL** | A conf | CORE A | Digital libraries angle |
| **ESWC** | B conf | CORE B | European counterpart to ISWC |

**Length target:** 16 pages (ISWC) or 12 pages (JCDL)

**Already have:** kg.db (224k entities, 765k edges), faculty_seed.json (4,294 faculty), papers.db canonical reconciliation, topic clustering pipeline

**Still needed:** Human-in-the-loop disambiguation evaluation, comparison against generic NER+linking baselines

**Realistic timeline:** Submission Jun 2026 → ISWC 2027 (Nov).

---

### P6. PRT-Corpus — Dataset Paper

**Working title:** *PRT-Corpus: A 436k-Item Archive of Historical Thai Parliamentary Documents for Low-Resource NLP Research*

**Main claims:**
1. First public corpus of Thai parliamentary documents 1934-present (Buddhist Era 2477-present)
2. Document categories: agendas, bill drafts, constitutions, parliamentary questions, royal ceremonies
3. Six benchmark tasks: OCR quality, retrieval, timeline inference, act classification, cross-lingual search, entity linking
4. Baselines: PaddleOCR, OpenScribe, mBERT, XLM-R, bge-m3

**Target venues:**

| Venue | Type | CORE / IF | Fit |
|---|---|---|---|
| **LREC-COLING 2028** | Main | A conf | **Canonical dataset venue** (LREC 2026 closed) |
| **Scientific Data** (Nature Research) | Journal | IF ~5.8 | Data-descriptor format |
| **ACM Journal of Data and Information Quality (JDIQ)** | Journal | IF ~2.1 | Open to curated corpora |
| **PACLIC** (Pacific Asia CL) | Conf | B | Asian languages focus |
| **LREC-COLING workshops** | Workshop | - | Faster path, still indexed |
| **Language Resources and Evaluation** (journal) | Journal | IF ~2.9 | Same community as LREC |

**Length target:** 12 pages (LREC) or journal descriptor 15-25 pages

**Still needed:**
- Full PRT harvest (waiting on origin)
- Cleaned + deduplicated metadata dump
- Canonical splits for benchmark tasks
- Gold annotations on a subset

**Realistic timeline:** LREC 2028 window opens late 2027. Submit Scientific Data earlier (rolling review, IF 5.8).

---

### P7. Multi-Tenant RAG-as-a-Service — Architecture Paper

**Working title:** *Retrieval-Augmented Search as a Service: A Reference Architecture for Multi-Tenant Academic Library Deployments*

**Main claims:**
1. Tenant isolation via config+directory structure (tenants/<id>/) scales linearly in operator cost
2. A Pydantic-schema-driven tenant config unifies DSpace endpoint, language, OCR, LLM provider, embedding model into one file
3. Cost optimizations (Vertex batch, local Qdrant, shared embedding models) stack to <$0.01/document
4. Real-world deployment: ISU (English, 120k) + PRT (Thai, 436k) running from one codebase

**Target venues:**

| Venue | Type | CORE / IF | Fit |
|---|---|---|---|
| **JCDL** (ACM/IEEE Joint) | A conf | CORE A | **Perfect fit** — digital library systems |
| **IEEE Software** | Journal | IF ~3.6 | Practitioner-oriented reference architecture |
| **ACM JDIQ** | Journal | IF ~2.1 | Infrastructure focus |
| **D-Lib Magazine** | Magazine | OA, IF N/A | Digital library community |
| **TPDL** (Theory and Practice of DL) | B conf | CORE B | European DL venue |
| **Program (Emerald)** | Journal | IF ~1.5 | Library automation |

**Length target:** 12 pages (JCDL) / 15 pages (IEEE Software)

**Already have:** tenants/ scaffolding, TenantConfig Pydantic schema, smoke tests, shared platform code

**Still needed:** Production deployment metrics from at least 2 tenants (ISU complete; PRT pending)

**Realistic timeline:** JCDL 2027 submission ~Mar 2027.

---

### P8. Document Understanding as Agent Tools — MCP/Skills Demo Paper

**Working title:** *OpenScribe-MCP: Document Understanding Primitives as Composable Agent Tools via Model Context Protocol*

**Main claims:**
1. First OCR framework exposed as MCP server → callable from any agent with one config line
2. Claude Skills as tuned prompt-templates-plus-config packages (e.g., `ocr-thai-archival`) dramatically lower adoption barrier
3. Lazy engine loading pattern: metadata tools (detect_language, chunk_semantic, evaluate_quality) are always available; heavy OCR engines load on first use
4. Demonstrates how complex pipelines can be decomposed into primitives agents orchestrate

**Target venues:**

| Venue | Type | CORE | Fit |
|---|---|---|---|
| **ACL / EMNLP System Demonstrations** | A* (demo) | Demo track | Standard path for agent tooling demos |
| **NeurIPS Workshops on Agents** | Workshop | - | Fast-track for LLM agent topics |
| **ICLR Workshops** | Workshop | - | Same |
| **ACM IUI** (Intelligent User Interfaces) | A conf | CORE A | Human-agent interfaces welcome |
| **ACM UIST** (User Interface Software) | A* conf | CORE A* | Demo-friendly systems venue |
| **CHI** (Human Factors Late-Breaking) | A* | CORE A* | LBW for prototypes |

**Length target:** 4-6 pages (demo paper) or 2-page short

**Already have:** `openscribe-mcp/` (server), `skills/ocr-thai-archival/` (first skill), README with install instructions

**Realistic timeline:** Submission Aug 2026 → ACL/EMNLP 2027 demo track.

---

## Suggested Writing Priority

| Order | Paper | Why First | ETA draft | ETA submission |
|---|---|---|---|---|
| 1 | **P2: Scaling RAG engineering** | Data complete, war stories ready, fastest to write | 2-4 weeks | ACM CACM rolling, or USENIX ATC Jan 2027 |
| 2 | **P4: LLM-as-Judge evaluation** | Framework already built, core results in hand | 4-6 weeks | SIGIR Jan 2027 / CIKM Jun 2027 |
| 3 | **P8: OpenScribe-MCP demo** | 4-page demo, leverages work already shipped | 2 weeks | ACL/EMNLP demo Aug 2026 |
| 4 | **P5: Institutional KG construction** | kg.db and disambiguation data complete | 6-8 weeks | ISWC May 2027 |
| 5 | **P7: Multi-tenant architecture** | Architecture mature, needs 2 tenants running | 6-8 weeks | JCDL Mar 2027 |
| 6 | **P1: OpenScribe main paper** | Needs PRT data, Claude-on-Vertex enabled | 3-4 months | EMNLP May 2027 |
| 7 | **P3: Cost-quality cascades theory** | Needs deeper bandit analysis | 4-6 months | AAAI Aug 2027 / NeurIPS May 2027 |
| 8 | **P6: PRT-Corpus dataset paper** | Needs full harvest + gold annotations | 6+ months | LREC-COLING 2028 |

---

## Venue Shortlist (Preferred, By Type)

Based on user preference for IEEE, ACM, AAAI families:

### Conferences (IEEE/ACM/AAAI preferred)

| Venue | Society | CORE | Area | CSRankings link |
|---|---|---|---|---|
| **EMNLP / ACL / NAACL** | ACL* | A* | NLP | NLP track |
| **SIGIR** | ACM | A* | IR | IR track |
| **CIKM / WSDM** | ACM | A | IR + DM | IR track |
| **NeurIPS / ICML / ICLR** | NeurIPS Foundation / IMLS / ICLR | A* | ML | AI track |
| **AAAI / IJCAI** | AAAI / IJCAI | A* | AI | AI track |
| **ISWC** | ACM/IEEE | A | Semantic Web | N/A |
| **JCDL** | ACM/IEEE | A | Digital Libraries | N/A |
| **IUI / UIST** | ACM | A / A* | Human-AI | HCI track |
| **USENIX ATC / OSDI** | USENIX | A / A* | Systems | Systems track |

\* ACL isn't IEEE/ACM/AAAI but is the canonical NLP venue. ACM hosts many of its proceedings (ACM DL). EMNLP specifically has heavy ACM involvement.

### Journals (by verified impact factor)

| Journal | Society | 2024 IF | Notes |
|---|---|---|---|
| **IEEE TPAMI** | IEEE | **18.6** | Top AI journal (7-year #1) |
| **IEEE TKDE** | IEEE | **11.60** | Top data engineering, +37% YoY |
| **ACM CACM** | ACM | ~11 | Practitioner magazine |
| **ACM TOIS** | ACM | **9.1** (+70%) | Top IR journal |
| **Scientific Data** (Nature) | Nature Research | ~5.8 | Dataset venue |
| **IEEE/ACM TASLP** | IEEE/ACM | ~4.8 | Speech + language |
| **IEEE Software** | IEEE | ~3.6 | Practitioner reference |
| **Semantic Web Journal** | IOS Press | ~3.4 | KG-specific |
| **JMLR** | MIT Press | ~4.3 | Open-access ML journal |
| **Language Resources and Eval.** | Springer | ~2.9 | LREC community |
| **ACM JDIQ** | ACM | ~2.1 | Data quality |

---

## Open Questions Before Writing

1. **Authorship order** — who are co-authors on each paper? (PI, students, collaborators)
2. **IRB / ethics approval** — PRT dataset redistribution may need Thai Parliament's explicit license
3. **Claude usage disclosure** — many venues now require AI-assistance disclosure; both generating synthetic queries and chunking with Opus should be disclosed
4. **Artifact evaluation** — several venues (EMNLP, SIGIR) now require reproducibility artifacts; we should plan to release code + data with each paper
5. **Timing conflicts** — can't submit the same core contribution to two venues simultaneously; need to stage releases carefully (e.g., P1 EMNLP before TASLP journal extension)

---

## Sources Verified

- EMNLP/ACL/NAACL scale & citation data: Dec 2025 analysis paper on arxiv
- ACM TOIS 2024 IF = 9.1 (+70%): ACM press release July 2025
- IEEE TKDE 2024 IF = 11.60: ooir.org / BioxBio aggregator, Resurchify
- IEEE TPAMI 2024 IF = 18.6: IEEE Computer Society press release 2025
- LREC-COLING 2026: closed for main papers, workshops open; LREC 2028 is next main window
- JCDL 2025: ACM/IEEE joint, Dec 15-19 2025 virtual
