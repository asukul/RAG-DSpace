# Expansion Plan — Sovereign Thai-Academic RAG

_Decided 2026-04-13 after parallel feasibility + business research._

## Thesis

> **Be the Hugging Face of sovereign academic RAG.**
> Open-source the core. Sell deployments and Thai-language data expertise.
> ISU stays as the US lighthouse reference. TDRI / MHESI / ThaiLLM pays the bills.

This plan plays to every asset we already have (ISU KG working, OpenScribe, PRT harvester, Thai-language relationships, strong solo engineering, no VC pressure) and avoids every weakness (no US enterprise sales team, no marketing budget, no appetite to raise a round).

---

## 0. Why this call — where the two reports reinforce each other

The alignment between the technical-feasibility and business-strategy research is almost suspiciously clean:

- **Technically**, the Thai option is the cheapest by 100×+ (arXiv $36k vs Thai $330) and has natural multilingual requirements already built into the existing pipeline.
- **Strategically**, Thai is the only segment with no serious AI-native competitor, an active government funding vehicle, and local relationships that can actually be sold into.
- **Existing assets all ladder into a Thai play:** OpenScribe (Thai OCR), PRT harvester (Hansard corpus), ISU KG (reference deployment proving scale), multilingual embedding pipeline (already running).
- **Current weaknesses** (no VC, no US enterprise sales team, no marketing budget) don't hurt in grant/institutional sales.

arXiv and MIT are **additive** — worth doing eventually for breadth, but they don't change the business.

### Why OSS-core + consulting beats the alternatives

- **Pure OSS with managed hosting** (Supabase model) hit $70M ARR only with $80M+ VC and a multi-year sprint. Solo ceiling is ~$200k ARR, and per PostHog's own public words, *"hosting is not very defensible."*
- **Pure non-profit** (OpenAlex / AI2 model) needs a backer. Thai DEF funds are that backer, which is exactly what the OSS + grants hybrid delivers.
- **Pure commercial closed SaaS** makes us an Elicit competitor in a commoditized feature race. We lose — Elicit has VC, marketing, and a team, we have none of that.
- **OSS-core + consulting** moats on proprietary data, relationships, and sovereign trust — not on code, which is exactly what the vibe-coding era commoditized.

---

## 1. Why not compete with Elicit / Consensus

The English-language individual-researcher RAG space is already crowded and commoditized:

| Tool | What it does best | Gap we could fill |
|---|---|---|
| Google Scholar | Universal recall, free | No LLM synthesis, no API |
| Semantic Scholar (AI2) | 200M+ papers, open corpus | Data-only, no reasoning layer |
| Elicit ($12–79/seat/mo, ~$18–22M ARR 2025) | Extract-from-PDF, systematic review | Weak on non-English + grey literature |
| Consensus ($12/mo indiv, FTE site licenses) | Claim-level synthesis | Shallow per-paper depth |
| ResearchRabbit (free + $10/mo) | Citation graph, Zotero | No LLM Q&A |
| Scite ($12–20/mo) | Supporting/contradicting citations | Citation lens, not search engine |
| Undermind (YC, enterprise) | Agentic deep search | Slow (~10 min/query), expensive |
| Scopus / Web of Science ($140–212k/yr/institution) | Canonical bibliometrics | No AI layer, legacy UX |
| CORE (nonprofit) | 300M+ OA full-texts | Quality-control issues |
| OpenAlex (nonprofit, $1/1k calls) | Open metadata of record | Data only |

The solo-built closed-SaaS ceiling without VC and marketing spend is roughly **$500k–$1M ARR**. That's a dead end for a one-person team.

**The one real gap:** every tool treats the paper as the atom. Almost no one indexes **people and labs** the way the ISU knowledge graph does, and almost no one handles non-English (especially Thai) full-text at all.

---

## 2. Feasibility of the four expansion sources

| Source | Items | Chunks | Embed cost* | Strategic value |
|---|---|---|---|---|
| **arXiv full** | ~3.0M | ~48M | ~$36k | Too expensive for solo |
| **arXiv CS-only** | ~150k/yr new | ~2.4M | **~$1.8k** | Supplementary; adds US research credibility |
| **DSpace@MIT** (all, incl CSAIL) | ~137k | ~2.2M | **~$165** | Cheap; OAI-PMH trivial; run once |
| **Thai top-10 DSpace** | ~300–400k | ~4–5M | **~$330** | **Primary target — cheap, strategic, defensible** |

*Conservative estimate using published text-embedding-005 online rate of ~$25/1B chars. Actual Vertex Batch cost is currently unverified — user memory says 125× discount (→ ~$0.65 for 3.16B chars), while typical batch discount is 50% (→ ~$40). **Verify against the currently-running 2-part job before any arXiv-scale spend.**

### Critical technical findings

- **No separate CSAIL DSpace.** CSAIL lives inside `dspace.mit.edu` under handle `1721.1/5458` (AI Memos 1959–2004 + CSAIL Tech Reports 2003–present). One OAI-PMH pipeline covers all of MIT.
- **arXiv S3 is requester-pays** (~$250–350 one-time for 6 TB). License allows indexing + snippets, prohibits full-PDF redistribution.
- **DSpace 7+ REST has no bulk-export endpoint** — still paginate or use OAI-PMH. Only 16–48 instances globally on 7+. MIT is still on 6.3. So DSpace 7+ is a capability to adopt when a target repo upgrades, not an expansion lever.
- **Thai repos need multilingual embedder** — Nomic multilingual or Vertex `text-multilingual-embedding-002`. `text-embedding-005` is English-tuned.

### Top Thai DSpace repositories

| Rank | Repository | ~Items | Language |
|---|---|---|---|
| 1 | Chulalongkorn CUIR / DigiVerse | ~70k | TH-primary, bilingual |
| 2 | Thammasat TU Digital Collections | ~60k | TH-primary |
| 3 | Kasetsart KUKR | ~30–40k | TH/EN mixed |
| 4 | Mahidol IR | ~25–35k | EN-heavy (med/sci) |
| 5 | Prince of Songkla Knowledge Bank | ~25–30k | Bilingual |
| 6 | Chiang Mai CMUIR | ~20–30k | TH-primary |
| 7 | Silpakorn U. Repository | ~15–20k | TH |
| 8 | Khon Kaen KKU | ~15–20k | TH |
| 9 | KMUTT / KMITL | ~10–15k each | TH/EN |
| 10 | NIDA / Burapha / Naresuan | ~5–10k each | TH |
| Umbrella | **ThaiLIS TDC** | ~137,249 records | TH-primary (custom, not DSpace) |

---

## 3. Monetization ranked by fit for a solo builder in Thailand

| Segment | Deal size | Ease-of-sale | Verdict |
|---|---|---|---|
| Individual researchers | ~$120/yr | Easy acquisition, terrible economics | **Skip as primary** — free tier for funnel only |
| US university libraries | $10–100k | Very slow, NDA, RFP | **Skip unless anchor** — ISU IS our anchor, use as reference |
| Thai universities + ministries | $5–50k | Slow but uncrowded; local advantage | **Strong candidate** |
| Corporate R&D (biotech/pharma/law) | $50–500k | Hard cold-sell, relationship-driven | **Best dollars, hardest door** — defer |
| Consultancies (McKinsey/BCG/Bain policy arms) | $20–100k pilots | Medium; pay for speed | **Realistic pilot target** |
| Thai government (MHESI, NRCT, TDRI) | $10–200k grants | Local advantage, procurement overhead | **Best grant fit — primary funding source** |

### Thai opportunity specifics

- **ThaiLIS/TDC** (137k+ Thai theses/full-texts) — legacy keyword search, no semantic/LLM layer.
- **TNRR** (National Research Repository, NRCT) — aggregates Thai research projects, keyword-only.
- **ThaiLLM** (NECTEC/MHESI, 2026) — sovereign LLM initiative backed by DEF funding, explicitly wants Thai-language AI applications.
- **depa grants** — THB 100k (mini) / THB 1M (midi) / larger for full projects. Fit exactly.
- **No competitor is running LLM-native Thai academic search.** Elicit/Consensus don't index ThaiLIS and handle Thai-language queries poorly.
- **Cross-leverage asset:** OpenScribe Thai OCR framework is already built and tested. ThaiLIS + TNRR + Thai Parliament Hansard = a defensible multilingual full-text dataset no competitor has.

---

## 4. OSS vs commercial vs non-profit — what a solo builder can actually do

| Model | Realistic solo outcome (2026 vibe-coding era) | Defensibility |
|---|---|---|
| **Closed SaaS** (Elicit / Consensus model) | Ceiling ~$500k–1M ARR without team + VC | Low-medium — LLMs commoditize |
| **OSS + managed hosting** (Supabase / PostHog) | Supabase took $80M+ VC to hit $70M ARR. Solo ceiling ~$200k ARR from hosting. | Low — forks proliferate. PostHog's own public words: *"hosted model is not very defensible"* |
| **Non-profit / public-benefit** (OpenAlex / AI2) | Needs a backer (Arcadia, Sloan, EU Horizon, Thai DEF). Slow, bureaucratic. | Medium — data moat |
| **OSS-core + institutional consulting** (early HuggingFace) | **Most realistic for one person** — open code, charge for deployment, customization, training data curation, sovereign hosting | **Medium-high** — moat is expertise + relationships + trust, not code |

**In the vibe-coding era, code is commodity. The only durable moats are: proprietary data, domain relationships, operational expertise, and regulatory / sovereign trust.** We have all four in Thai academic data, none in US academic search.

---

## 5. 90-day execution plan

### Weeks 1–2 — Posture change
- Rebrand the ISU codebase repo as a generic "Sovereign Research RAG" platform.
- License: **AGPL-3.0** (prevents cloud giants from hosting the free tier against us) with a commercial carveout for paid deployments. Alternative: BSL-1.1.
- Drop ISU-only framing from READMEs. ISU becomes *one* reference deployment, not *the* product.

### Weeks 3–6 — Thai corpus v1
- Harvest ThaiLIS/TDC (~137k records) + Chulalongkorn CUIR (~70k) + Thammasat TU DC (~60k) via OAI-PMH. Total ~267k items, estimated ~$100–200 of embeddings at worst-case batch rates.
- Re-use existing harvest code with source tagging.
- Use Nomic multilingual or Vertex `text-multilingual-embedding-002` for Thai content. Keep `text-embedding-005` for English-only subsets.

### Weeks 4–8 — Grant application
- Draft and submit a depa midi-grant (THB 1M ≈ $28k) for a "Thai National Research RAG" demo on top of OpenScribe + the harvested corpus.
- Name TDRI as a collaborator if achievable.
- If the midi lands, it funds the next 6–9 months. If not, re-try with the mini-grant + pivot to a private-sector pilot.

### Weeks 6–10 — Reference customer
- Cold-pitch TDRI for a free pilot deployment of the ISU/Thai hybrid stack. Their researchers publish constantly → best proof-of-value testimonial in Bangkok.
- Follow with a paid pilot at one Thai private university. Sasin @ Chula or CMMU are the fastest decision cycles; both English-medium, research-intensive.

### Weeks 8–12 — Credentialing content
- Publish the OpenScribe paper (P1 from the existing paper plan) using the ISU + PRT experimental data.
- Follow with a "sovereign academic RAG" technical blog / HN post to pull the right circles (Thai academia, sovereign-AI community, librarian world).

### Deferred (do when anchor closes)
- ~~arXiv CS ingest (~$1.8k)~~ — **revised to ~$13 at the real batch rate**; greenlight anytime.
- ~~MIT DSpace (~$165)~~ — **revised to ~$0.60**; one-afternoon job for ISU-vs-MIT comparison numbers.
- arXiv full (~$262 at real rate) — feasible but exceeds current credit headroom.
- Full DSpace 7+ REST integration.
- Any US university sales motion.
- Language expansion beyond Thai + English.

### Never (explicit anti-goals)
- Another Elicit clone.
- Another English-language individual-researcher $20/mo tool.
- A pure arXiv/MIT expansion as primary product focus.
- Chasing 10k users. Year-one target is **3 paying institutions + 1 government grant = $60–150k cash**.

---

## 6. Gating decision: Vertex cost — CORRECTED 2026-04-13 PM

**⚠ The morning reading ($6.26 / $1.95 per 1B chars) was partial billing data. The real rate is ~8× higher.**

**Real billed cost for 2026-04-13:** $60.45 gross (100% absorbed by the `ComS1130 USD100` course credit, so $0 out-of-pocket — but the credit runway shrank significantly).

- Total chars embedded today across all batch jobs: **3.85 B** (ISU 3.215 B + MIT 0.186 B + arXiv CS 0.225 B + duplicate arXiv 0.225 B)
- Effective batch rate: **~$15.70 per 1 billion chars**
- That's roughly **1.6× cheaper than Vertex online** ($25/1B) — about a 37% discount, not the 92% we initially thought
- The morning's "$1.95/1B" reading and the "125× cheaper" folk wisdom were both wrong — see `memory/vertex_batch_rate.md` for the reconciliation

### Corrected source cost table (2026-04-13 PM)

| Source | Est. chars | Real cost (@ $15.70/1B) | Morning estimate (wrong) | Status |
|---|---|---|---|---|
| MIT DSpace abstracts (150k) | ~0.19 B | **~$3** | $0.60 | ✅ Done |
| arXiv CS abstracts (200k) | ~0.22 B | **~$3.50** | $13 | ✅ Done |
| ISU full corpus (measured) | 3.215 B | **$50.49** (~83% of today's bill) | $6.26 | ✅ Done |
| MIT DSpace fulltext (PDFs) | ~0.3 B | **~$5** | $0.60 | Feasible |
| Thai top-10 DSpace fulltext | ~13 B | **~$204** | $25 | ⚠ Exceeds credit |
| arXiv CS fulltext | ~6.7 B | **~$105** | $13 | Deliberate spend |
| **arXiv full corpus (all cats)** | ~134 B | **~$2,100** | $262 | 🛑 **ON HOLD** (user decision 2026-04-13) |

### Credit runway (corrected)

Gross spend April 1-13 across all services: **$71.87** (Vertex $60.45 + Compute Engine $8.08 + Cloud Build $2.07 + Cloud Storage $0.86 + Networking $0.36 + Cloud Run $0.06 + Artifact Registry $0.05). Of the $100 course credit:
- **~$28 remaining**, expiring 2026-07-29
- Ongoing ops burn (Cloud Run + Compute Engine) ≈ $10-15/month → ~$30-45 over remaining 3 months
- **Running just baseline ops will exhaust the credit right around the 2026-07-29 expiration date** — no headroom for big new embedding runs

### Lessons learned (added to `memory/vertex_batch_rate.md`)

1. **Always wait 24h for billing to settle** before trusting Cloud Billing totals. Mid-day snapshots for fresh runs are partial.
2. **The folk wisdom "batch is 125× cheaper" is wrong** for `text-embedding-005` — it's more like 1.6× cheaper. Modest, not dramatic.
3. **Check the Vertex BatchPredictionJob list** before resubmitting a "stuck" job. One submission got silently duplicated today due to a buffered-stdout hang in the shell wrapper (not a real API hang), costing an extra ~$3.50.
4. **Update `embed_vertex_batch_real.py`**'s `est_cost` calculation to use `$15.70/B` when next touched (currently wildly optimistic).

### What this unlocks — corrected 2026-04-13 PM

1. **MIT + arXiv abstract collections are done** — ~$7 total, within budget, no regrets. Collections `mit_dspace_vertex` (148k points) and `arxiv_cs_vertex` (200k points) are live on LOCAL Qdrant.
2. **Thai v1 harvest at the abstract level (~$3-5)** is still cheap and a great first step. Fulltext (~$204) is a deliberate-spend decision that should wait for a depa grant or equivalent.
3. **🛑 arXiv full corpus (~$2,100) is ON HOLD** per the 2026-04-13 user decision. Revisit only after a grant or explicit budget allocation.
4. **Any future Vertex spend >$20** should be pre-approved before launching — the remaining credit buffer is thin.

---

## Sources

**Business / market:**
- Elicit, Consensus, ResearchRabbit, Scite, Undermind pricing pages
- Semantic Scholar, OpenAlex, CORE
- Scopus / Web of Science library pricing (UMass Medical 2018–2024 dataset)
- Supabase / PostHog revenue disclosures
- ThaiLIS TDC, TNRR (MHESI), TDRI, NSTDA ThaiLLM, depa grant program docs

**Technical:**
- arXiv bulk-data S3 (info.arxiv.org)
- arXiv monthly submissions + CS list
- DSpace@MIT (homepage meta generator, collections page)
- DSpace 7.x REST API + OAI-PMH (LYRASIS Wiki)
- DSpace 7 benefits/adoption (Formanek, ITAL)
- Chulalongkorn CUIR, Thammasat TU, PSU Knowledge Bank
