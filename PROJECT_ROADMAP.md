# DSpace AI RAG Search Platform — Strategic Roadmap

**Principal Investigator:** Dr. Adisak Sukul
**Institution:** Iowa State University, Department of Computer Science
**Document version:** 1.0 (2026-04-12)

---

## Vision

Build the first integrated **AI-native knowledge search platform for academic institutional repositories**, combining:
1. Full-text RAG search on institutional documents
2. Faculty / Expert finder with bibliometric context
3. Knowledge Graph navigation (papers → authors → topics → departments)
4. LLM chat interface grounded in the institutional corpus
5. Citation-network integration (OpenAlex, DBLP, arXiv, Semantic Scholar, Scite.ai)
6. Multilingual support (English + Thai, extensible)

Current DSpace providers offer basic search. Commercial competitors offer RAG OR expert finders. **Nobody offers all three merged into one unified interface with the depth we've built.**

---

## Three Goals

### Goal 1: ISU Pilot Deployment (Production)
Complete and ship the Iowa State University digital repository RAG search as a flagship reference implementation.

### Goal 2: Research Publications
Extract publishable research from the development journey across multiple papers.

### Goal 3: SaaS Platform for DSpace Users
Productize as a subscription service for academic libraries globally.

---

## Goal 1: ISU Pilot — Production Deployment Checklist

### Current Status (as of 2026-04-12)
- ✅ 120,780 items indexed from DSpace (100% coverage)
- ✅ 97,441 PDFs downloaded (359 GB)
- ✅ 4,322 faculty with bibliometric data
- ✅ Knowledge Graph: 224k entities, 765k edges
- ✅ Department coverage: 91.7%
- ✅ Frontend deployed to GCP Cloud Run
- ✅ Backend deployed to GCP Cloud Run
- ✅ Qdrant vector store (GCP VM + local)
- 🔄 Full-text embedding in progress (53% Nomic, Vertex batch pending)
- ✅ Admin dashboard with conflict resolution
- ✅ Google OAuth authentication
- ✅ LLM-as-judge eval framework
- ✅ 57 synthetic test queries

### Pilot Completion Tasks
1. **Finish embeddings** (all models): Nomic, Vertex, bge-m3, mxbai, qwen3
2. **Run eval framework** on all model/chunking combinations
3. **Select winning embedding strategy** based on results
4. **Deploy production RAG** with chosen model
5. **User acceptance testing** with ISU researchers (5-10 faculty volunteers)
6. **Documentation** — user guide, admin guide, API docs
7. **Performance SLA** — p95 latency <2s, uptime >99%
8. **Launch announcement** — coordinate with Parks Library + CS dept
9. **Feedback loop** — monthly surveys, usage analytics
10. **Iterate** — based on real user queries

### Success Metrics for Pilot
- 100+ active users in month 1
- NDCG@10 > 0.85 on gold standard queries
- Admin dashboard adoption by librarians
- Positive feedback from 80%+ of surveyed users
- Citation in ISU news / library newsletter

### Pilot Timeline
| Phase | Duration | Milestone |
|-------|----------|-----------|
| Embedding completion | 1-2 weeks | All models trained |
| Evaluation | 1 week | Model selection |
| Production deploy | 3 days | SLA monitoring live |
| UAT | 2 weeks | User feedback collected |
| Public launch | Week 7 | ISU-wide announcement |

---

## Goal 2: Research Publications Plan

### Paper 1: "Multi-Model Embedding Strategies for Academic Repository RAG"
**Venue:** SIGIR, EMNLP, or NAACL 2026-2027
**Core contribution:** First at-scale (100k+ docs) comparison of embedding models on academic retrieval with LLM-as-judge evaluation.

Sections:
1. Related work (23 papers already reviewed — see RESEARCH_NOTES Section 6)
2. Dataset (120k DSpace items, 97k PDFs, 57 eval queries)
3. Methodology (7 embedding models × 3 chunking strategies)
4. Results (nDCG@10, P@K, MRR, cost-quality Pareto)
5. Discussion (Matryoshka tradeoffs, ensemble gains)
6. Reproducibility (open-source toolkit)

### Paper 2: "LLM-Assisted Chunking for Academic RAG"
**Venue:** ACL, EMNLP, or workshop on LLM+IR
**Core contribution:** Comparing naive vs Claude semantic chunking at scale, showing section-aware chunks improve retrieval precision.

Based on: Section 13 of RESEARCH_NOTES.md (already have preliminary data on 20 docs, 72 semantic chunks vs 226 naive)

### Paper 3: "Systems Challenges in Building Institutional RAG at Scale"
**Venue:** VLDB, NSDI, or systems-focused workshop
**Core contribution:** Operational guide covering GIL, pickling, Ollama deadlocks, Qdrant ingestion, cost optimization.

Based on: Section 16 of RESEARCH_NOTES.md (10 issues + fixes documented)

### Paper 4: "Faculty-Paper Disambiguation via Contextual Signals"
**Venue:** JCDL, iConference, or bibliometrics venue
**Core contribution:** Novel disambiguation approach using department, rank, works_count, institution signals to resolve OpenAlex ambiguous matches.

Based on: Section 4 + the disambiguation script (1,544/1,603 resolved, 0.55 → 0.888 confidence)

### Paper 5: "Knowledge Graph Augmentation for Institutional Search"
**Venue:** ISWC, ESWC, JCDL
**Core contribution:** Building a 224k-entity KG from DSpace + OpenAlex + faculty scraping, with ABOUT edge generation via embedding similarity.

### Paper 6: "Multilingual Academic RAG with OCR Integration"
**Venue:** SIGIR, CIKM (future, after Thai implementation)
**Core contribution:** Extending RAG to Thai academic corpora with PaddleOCR + multilingual embeddings.

### Research Strategy
- **Publish in parallel** — don't wait for all models to finish
- **Start with Paper 3** (systems) — data already exists
- **Paper 1** becomes the flagship
- **Paper 2** can be submitted as a short paper first
- **Conference presentations** before journal versions
- **Open-source everything** — maximize citations

---

## Goal 3: SaaS Platform for DSpace Users

### Product Name Candidates
- **RepoAI** — short, clear
- **DSpace IQ** — leverages brand recognition
- **InstituteSearch** — institutional focus
- **ScholarRAG** — academic feel
- **Curiositas** — Latin for curiosity

### Value Proposition (unique vs competitors)

| Feature | DSpace+Add-ons | Commercial RAG | **Our Platform** |
|---------|---------------|---------------|----|
| Full-text search | ✅ Basic | ✅ | ✅ |
| AI chat with citations | ❌ | ✅ | ✅ |
| Faculty/expert finder | ❌ | ❌ | **✅** |
| Knowledge Graph | ❌ | ❌ | **✅** |
| Citation networks (OpenAlex+arXiv+DBLP) | ❌ | Partial | **✅** |
| Open source core | ❌ | ❌ | **✅** |
| Thai language support | ❌ | ❌ | **✅** |
| Self-hosted option | ✅ | Rare | **✅** |

### Pricing Tiers

#### Starter — $500/month
- Up to 10,000 documents
- Monthly incremental harvest
- English only
- Shared infrastructure on GCP
- Email support
- Basic dashboard

#### Academic — $2,000/month
- Up to 100,000 documents
- Daily incremental harvest
- Full-text PDF indexing (with OCR for scanned)
- Multi-language (EN + 1 other)
- OpenAlex + DBLP + arXiv integration
- Dedicated Qdrant instance
- Knowledge Graph
- Faculty/expert finder
- Admin dashboard
- Priority support

#### Enterprise — $5,000-$15,000/month
- Unlimited documents
- Real-time harvest
- All citation networks (Semantic Scholar, Scite.ai, CrossRef)
- Full multilingual (EN + Thai + Spanish + Chinese)
- Custom embedding model fine-tuning
- On-premise deployment option
- SLA guarantees
- SSO integration (SAML, OAuth, Shibboleth)
- White-label branding
- Dedicated account manager
- Quarterly consultations

#### Pilot/POC — $0 for 90 days
- 1 institution trial
- Full feature access
- Data stays on their GCP project
- Case study agreement

### Target Markets (in order of rollout)

**Phase 1: US Academic (pilot → launch)**
- Iowa State University (pilot — flagship)
- Other Big 12 / AAU members
- ~40 DSpace-based US universities (per DSpace registry)
- Primary contacts: library deans, scholarly communication offices

**Phase 2: Thailand (Year 2)**
- Leverage existing consulting relationships
- Key contacts: Thai Library Association, TRF, NECTEC
- ~60+ Thai universities using DSpace
- **Critical:** Thai OCR + Thai embedding models
- Potentially partner with Thailand Research Fund

**Phase 3: Rest of Asia / Global**
- Philippines, Vietnam (DSpace is popular)
- Europe (many institutional repositories)
- Latin America (SciELO-adjacent)
- ~2,000+ DSpace instances worldwide

### Customer Acquisition Strategy
1. **Flagship case study** — ISU with impact metrics
2. **DSpace user conferences** — Open Repositories, IOA annual
3. **Academic library consortiums** — Big Ten Academic Alliance, CNI, SPARC
4. **Thought leadership** — publications, blog, workshops
5. **Free POCs** — 90-day no-commitment trials for first 10 institutions
6. **Partnerships** — DuraSpace (DSpace maintainer), Atmire, 4Science (commercial DSpace consultants)
7. **Direct outreach** — targeted email to library deans via AAU

### Technical Architecture (Multi-Tenant)

```
┌─────────────────────────────────────────────────────┐
│  Shared Control Plane (GCP)                         │
│  - Admin dashboard                                   │
│  - Billing & metering                                │
│  - Customer onboarding                              │
│  - Usage analytics                                   │
└─────────────────────────────────────────────────────┘
                       │
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  Tenant A    │ │  Tenant B    │ │  Tenant C    │
│  (ISU)       │ │  (Univ X)    │ │  (Thai Univ) │
├──────────────┤ ├──────────────┤ ├──────────────┤
│ Own Qdrant   │ │ Own Qdrant   │ │ Own Qdrant   │
│ Own DB       │ │ Own DB       │ │ Own DB       │
│ Own Storage  │ │ Own Storage  │ │ Own Storage  │
│ Own Cloud Run│ │ Own Cloud Run│ │ Own Cloud Run│
│ English      │ │ English      │ │ Thai+English │
└──────────────┘ └──────────────┘ └──────────────┘
```

**Key design principles:**
- Each tenant gets isolated data (GDPR/FERPA compliance)
- Shared services: auth, billing, admin UI
- Customer-specific: vector DB, SQLite indexes, GCS buckets
- Harvest pipeline: shared code, per-tenant scheduling
- Embedding: shared Ollama pool OR customer-dedicated

### Subscription Revenue Model
**Year 1:** 5 pilots → 3 convert to Starter → $18k ARR
**Year 2:** 15 customers average Academic tier → $360k ARR
**Year 3:** 40 customers, mix of tiers → $1.2M ARR
**Year 5:** 150 customers globally → $5M+ ARR

---

## OCR Integration Plan

### Why OCR?
Current pdfminer extraction fails on:
- Old scanned theses (pre-2000 digitization)
- Image-only PDFs
- Poor-quality scans
- **Estimate: 20-30% of our 97k PDFs would benefit from OCR**
- **100% of Thai corpora will need OCR** (mostly scanned)

### OCR Technology Options

| Tool | Quality | Speed | Cost | Thai Support | Notes |
|------|---------|-------|------|-------------|-------|
| **PaddleOCR** | Very Good | Fast (GPU) | Free | **Yes** | Best Thai support |
| **Tesseract** | Good | Medium | Free | Yes (with data) | Oldest, well-tested |
| **Google Vision API** | Excellent | Fast | $1.50/1k pages | Yes | Expensive at scale |
| **Azure Document Intel** | Excellent | Fast | $1.50/1k pages | Yes | Good for tables |
| **AWS Textract** | Very Good | Fast | $1.50/1k pages | Limited | Structured data focus |
| **Docling (IBM)** | Excellent | Medium | Free | Limited | New, PDF-focused |

### Recommended Stack

**Primary:** PaddleOCR (free, GPU-accelerated, best Thai support)
**Fallback:** Google Vision API (for difficult PDFs)
**Detection:** pdfminer first → if <50 chars extracted, mark as "needs OCR"

### OCR Pipeline Design

```
PDF File
  │
  ▼
┌─────────────────┐
│ pdfminer.six    │ — fast text extraction
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Text < 50 chars?│
└────┬────────┬───┘
     │ No     │ Yes
     ▼        ▼
  Keep text   ┌─────────────────┐
              │ PaddleOCR       │ — scan each page
              │ (GPU, parallel) │
              └────────┬────────┘
                       │
                       ▼
                ┌─────────────────┐
                │ Language detect │ — EN / Thai / ...
                └────────┬────────┘
                         │
                         ▼
                ┌─────────────────┐
                │ Language-specific│
                │ chunker          │
                └─────────────────┘
```

### OCR Integration Phases

**Phase 1 (ISU):** Detect + flag scanned PDFs, skip in current pipeline
**Phase 2 (Month 1):** Add PaddleOCR, re-process flagged English PDFs
**Phase 3 (Month 2):** Thai OCR support for pilot Thai customer
**Phase 4 (Month 3):** Production OCR as a microservice

---

## Multilingual Support Plan (Thai Focus)

### Why Thai First?
1. Existing consulting relationships in Thailand
2. Huge unmet need (Thai academic search is weak)
3. 60+ Thai universities using DSpace
4. Differentiator (no competitor offers Thai academic RAG)
5. Pipeline to expand to Lao, Khmer, Vietnamese

### Thai-Specific Challenges
1. **No spaces between words** — need Thai tokenizer
2. **Mixed Thai+English** — most papers cite English work
3. **Scanned PDFs** — most Thai repository content needs OCR
4. **Unique characters** — Thai script, tone marks, special unicode

### Recommended Thai Stack

| Component | Tool |
|-----------|------|
| **Tokenizer** | pythainlp (newmm algorithm) |
| **Language detection** | langdetect or fastText |
| **OCR** | PaddleOCR with Thai model |
| **Embedding model** | jina-embeddings-v3 (multilingual, 100+ languages) |
| **Alternative embedding** | intfloat/multilingual-e5-large |
| **LLM for chat** | Gemini 2.5 Flash (supports Thai well) |
| **Alternative LLM** | Claude Opus (very good Thai support) |

### Thai Integration Phases

**Phase 1:** Build Thai corpus ingestion module (separate pipeline)
**Phase 2:** Thai OCR + language-aware chunking
**Phase 3:** Thai-specific embedding model selection (benchmark)
**Phase 4:** Thai query interpretation (code-switching support)
**Phase 5:** Pilot with 1 Thai university (e.g., Chulalongkorn, Mahidol, KMUTT)

---

## Citation Service Integration Plan

### Current Integration
- ✅ **OpenAlex** — 174k ISU works, faculty matching, bibliometric data

### Planned Integrations

#### 1. DBLP (Computer Science focus)
- Free XML + JSON API
- Perfect for CS-heavy repositories
- Author normalization (DBLP has strong disambiguation)
- Paper metadata with venue, year, co-authors
- API: `https://dblp.org/search/publ/api?q=...`

**Use case:** Enrich CS papers with venue info, proceedings context

#### 2. arXiv
- Free OAI-PMH + Atom API
- Pre-prints often have richer metadata
- Cross-reference for preprint→published paper
- API: `http://export.arxiv.org/api/query?search_query=...`

**Use case:** Add arXiv preprint versions, access more recent work

#### 3. Semantic Scholar
- Free API (rate-limited)
- Citation context (not just count)
- TLDR summaries (AI-generated)
- Influential citations
- API: `https://api.semanticscholar.org/graph/v1/paper/...`

**Use case:** "Papers that cite this" with context, influence metrics

#### 4. Scite.ai
- Paid API (~$500-2000/year academic)
- "Smart citations" — supporting, contrasting, mentioning
- Unique value: citation sentiment
- API requires auth

**Use case:** Show how other papers reference ISU work (supporting vs contrasting)

#### 5. CrossRef (free)
- Already in many DOI lookups
- DOI → metadata resolution
- Funder information
- Reference lists (when publishers share)

#### 6. ORCID (free)
- Already partial support via OpenAlex
- Direct ORCID API for author details
- Institutional affiliations with dates

### Unified Citation Layer Architecture

```
┌──────────────────────────────────────────────────┐
│  Unified Citation Service (UCS)                   │
│  - Normalizes metadata from 6+ sources            │
│  - Deduplicates by DOI / title+year               │
│  - Caches aggressively (7-day TTL)                │
│  - Rate limits per-tenant                         │
└──────────────────────────────────────────────────┘
         ▲         ▲         ▲         ▲         ▲
         │         │         │         │         │
     OpenAlex    DBLP     arXiv  SemScholar  Scite
```

**Design principles:**
- Each source is a plugin (can enable/disable per tenant)
- Rate-limit respected per source
- Enterprise tier gets Scite integration (paid)
- Starter/Academic get free sources only

---

## Implementation Roadmap

### Q2 2026 (Apr-Jun) — ISU Pilot
- ✅ Data pipeline complete (in progress)
- ✅ All embeddings computed
- ✅ Eval framework complete
- 🎯 Select winning model configuration
- 🎯 Launch ISU pilot to 50 test users
- 🎯 First publication submission (Paper 3: Systems)

### Q3 2026 (Jul-Sep) — Polish + Documentation
- 🎯 ISU public launch
- 🎯 OCR integration (English first)
- 🎯 arXiv + Semantic Scholar integration
- 🎯 Paper 1 submission (Embedding comparison)
- 🎯 Open-source core toolkit on GitHub
- 🎯 Create marketing website

### Q4 2026 (Oct-Dec) — First External Customers
- 🎯 3 US academic pilots
- 🎯 DSpace conference presentation
- 🎯 Paper 2 submission (LLM chunking)
- 🎯 Multi-tenant architecture refactor
- 🎯 Billing & metering system

### Q1 2027 (Jan-Mar) — Thai Expansion
- 🎯 PaddleOCR Thai integration
- 🎯 Thai embedding benchmarking
- 🎯 First Thai pilot (1 university)
- 🎯 Thai language UI translation
- 🎯 Paper 4 submission (Disambiguation)

### Q2-Q4 2027 — Scale
- 🎯 10+ customers in Starter/Academic tiers
- 🎯 Enterprise customer acquisition
- 🎯 Consortium negotiations
- 🎯 Thai user base expansion
- 🎯 Additional language: Spanish (LATAM)

### 2028+ — Platform Maturity
- 🎯 50+ customers globally
- 🎯 SOC 2 certification
- 🎯 FERPA compliance documentation
- 🎯 Marketplace of embedding models (customer choice)
- 🎯 LLM model choice (Gemini/Claude/GPT)
- 🎯 Custom fine-tuning for enterprise

---

## Competitive Analysis

### Direct Competitors

1. **Atmire (Belgium)** — Commercial DSpace add-ons
   - Strength: Existing DSpace relationships
   - Weakness: No RAG, traditional search only
   - Our advantage: AI-native, lower cost

2. **4Science (Italy)** — Commercial DSpace services
   - Strength: European customer base
   - Weakness: Traditional library tools
   - Our advantage: Modern AI stack

3. **EBSCO / Elsevier** — Commercial library databases
   - Strength: Content licensing
   - Weakness: Closed ecosystem, expensive, not institutional repo focused
   - Our advantage: Works with YOUR repository

4. **Perplexity / You.com** — AI search engines
   - Strength: Brand recognition
   - Weakness: General web, not institutional
   - Our advantage: Focused on scholarly content, KG integration

### Indirect Competitors
- Google Scholar (free but no API for repositories)
- BASE (search engine, no AI)
- OpenAIRE (EU focus, no chat)
- Consensus.app (AI research assistant, no institutional)

### Moat
1. **Institutional data access** — we're IN the repository
2. **Knowledge Graph depth** — years of KG research
3. **Multi-source citation integration** — unique
4. **Thai language support** — no competitor has this
5. **Faculty/expert finder** — combines scholarly search with expertise discovery
6. **Open source core** — trust for institutions
7. **Academic pricing** — sustainable for libraries

---

## Risks & Mitigations

| Risk | Mitigation |
|------|-----------|
| DSpace community may build in-house | Move fast, establish brand, offer best UX |
| Commercial LLM prices rise | Multi-provider strategy, local LLM fallback |
| FERPA/GDPR compliance | SOC 2 early, per-tenant data isolation |
| Thai market acceptance | Existing consulting relationships |
| Single-person team initially | Automate everything, minimize ops burden |
| Customer customization demands | Clear tier boundaries, professional services |
| DSpace 8 migration | Stay on top of DSpace releases |
| Embedding model deprecation | Model-agnostic architecture |

---

## Team & Hiring Plan

### Year 1 (Solo + Contractors)
- **You (Adisak):** Product, tech lead, customer acquisition
- **Contract:** UI/UX designer (10 hours/week)
- **Contract:** Technical writer (5 hours/week)
- **Student workers:** ISU CS students for specific tasks

### Year 2 (Small Team)
- **Product/Eng Lead** (you)
- **Senior Engineer** — backend/infra (hire)
- **ML Engineer** — embedding research (hire)
- **Customer Success** — onboarding, support (part-time hire)

### Year 3 (Growth)
- Add: DevOps, sales, second ML engineer
- ~5-8 people total

---

## Next Immediate Actions (This Week)

1. ✅ Finish Nomic embedding (ongoing, 53%)
2. 🎯 Complete Vertex batch embedding ($1.50)
3. 🎯 Run eval framework on all collections
4. 🎯 Pick winning config for ISU pilot
5. 🎯 Draft Paper 3 (Systems) outline
6. 🎯 Set up GitHub org for open-source core
7. 🎯 Test PaddleOCR on 10 scanned PDFs
8. 🎯 Email 3 ISU librarians for UAT scheduling
9. 🎯 Domain name acquisition (if SaaS name chosen)
10. 🎯 Create investor / grant pitch deck skeleton

---

## Funding Opportunities

### Research Grants
- **NSF CAREER** — Adisak as PI, research tied to platform
- **IMLS** — Institute of Museum and Library Services
- **Mellon Foundation** — digital scholarship
- **ISU Presidential Initiative** — internal funding
- **Sloan Foundation** — research tools
- **NIH** — if we focus on health sciences repositories
- **DOE** — lab/research facility repositories

### Product Development
- **SBIR / STTR** — small business innovation research
- **Google for Startups** — GCP credits ($100k)
- **Microsoft for Startups** — Azure credits
- **Gemini for Education** — credits via ISU
- **NVIDIA Inception** — GPU credits

### Commercial
- **Open Technology Fund** — open source libraries
- **MacArthur Foundation** — research tools
- **ISU tech transfer office** — licensing agreements
- **Academic Innovation Fund** (ISU) — startup grants

---

## References to Existing Work

This roadmap builds on work documented in:
- `RESEARCH_NOTES.md` — technical research notes (16 sections, 860+ lines)
- `EXPERIMENT_DESIGN.md` — embedding comparison experiment plan
- `CONTINUATION_PROMPT.md` — original project context
- `backend/scripts/` — 60+ pipeline scripts
- Memory files in `~/.claude/projects/D--Dropbox-RAG-DSpace/memory/`

---

*This document is a living strategy document. Update quarterly as priorities shift and market feedback arrives.*
