# Design note: Two-panel search for ISU-scoped + general answers

_Status: DRAFT (awaiting approval) — 2026-04-13_
_Related: `backend/services/qdrant_rag_service.py` prompt Fix 1 already shipped_

## Problem

The current `/api/search` endpoint returns one answer, grounded in retrieved ISU DSpace chunks. When the user asks a broad question like **"Who works on AI?"**, two things go wrong:

1. **Cross-institution contamination.** ISU DSpace holds reports and publications for multi-institution NSF AI Institutes (AIIRA, AIFARMS, AIFS, AgAID, AI-LEAF). Those documents mention co-PIs from UIUC, UC Davis, UMN, OSU, WSU — and the LLM faithfully includes them in the answer, even though most of the named people are *not* ISU.
2. **No clear separation** between _"what ISU's corpus says"_ and _"what the LLM knows in general"_. A user asking a broad AI question might also want the general-knowledge answer (e.g., "what is the state of AI research across NSF institutes?"), but we currently provide neither cleanly.

Fix 1 (prompt tuning, already shipped) partially addresses (1) by instructing the LLM to lead with ISU content and label non-ISU collaborators clearly. It does not address (2).

## Goals

1. **Default ISU focus**: users searching the ISU RAG tool see ISU content first, clearly labeled, without ambiguity about which researchers work at ISU vs elsewhere.
2. **Optional general-knowledge panel**: users who want the LLM's broader perspective (training-data knowledge + any cross-institution context) can see it in a separate, clearly-labeled section.
3. **Single search box, one query**: no UX change to how users search. The two panels render from the same query.
4. **Transparent costs**: the general-knowledge panel is opt-in (expandable) or off by default if we decide the extra LLM call isn't worth the cost.

## Non-goals

- Building a meta-search across multiple repositories (that's the "sovereign RAG" expansion plan — different project).
- Auto-classifying queries as "ISU-specific" vs "general" — too much surface area; keep it user-controlled.
- Competing with Semantic Scholar / Elicit / general-purpose academic search on the general-knowledge side.

## Proposed response shape

Extend `/api/search` response:

```jsonc
{
  "isu_answer": "Adisak Sukul [1] and Wallapak Tavanapong [2] lead AI-for-education and medical-imaging research at ISU. ...",
  "isu_citations": [ { "uuid": "...", "title": "...", "authors": [...] } ],
  "isu_retrieved_chunks": [ ... ],        // existing "retrieved_chunks", renamed
  "isu_found_faculty": [ ... ],           // existing "found_faculty", renamed
  "isu_sources": [ ... ],                 // existing "sources", renamed

  // Optional second panel — only populated when include_general=true
  "general_answer": "Iowa State is part of the AIIRA NSF AI Institute led by Baskar Ganapathysubramanian, with partners including UIUC, UC Davis, OSU, WSU, and UMN. Other NSF AI Institutes focused on agriculture include AIFARMS (UIUC-led) and AI-LEAF (UMN-led)...",
  "general_source": "gemini-2.5-flash-lite training data",
  "general_disclaimer": "This section is from the LLM's general knowledge, NOT from the ISU repository. Information may be outdated or inaccurate.",

  "mode": "rag-hybrid",  // vs existing "rag-only", "rag-empty"
  "query": "Who works on AI?",
  "duration_ms": 1820
}
```

Backward compatibility: the old field names (`answer`, `citations`, `sources`, `found_faculty`, `retrieved_chunks`) stay as aliases on the ISU panel, so existing frontend code doesn't break during the rollout.

## Request shape

`POST /api/search`:

```jsonc
{
  "query": "Who works on AI?",
  "limit": 20,
  "include_general": false   // NEW: default false; user opts in via UI toggle
}
```

- `include_general: false` (default) → only the ISU panel is computed. Same cost as today. Same latency.
- `include_general: true` → both panels are computed in parallel (`asyncio.gather`). Adds ~1-2s latency and one extra Gemini-flash-lite call (~$0.0001/query).

## Frontend UX

**Default state (no opt-in):**

```
┌─────────────────────────────────────────────┐
│  Search the ISU Digital Repository          │
│  [_________________________________] [Go]   │
│                                              │
│  ☐ Also show general knowledge (opt-in)     │
└─────────────────────────────────────────────┘
```

Users who search without opting in see exactly what they see today, minus the cross-institution pollution (because of Fix 1 prompt tuning).

**Opt-in state:**

```
┌─────────────────────────────────────────────┐
│ 🏛 Iowa State University results            │
│ ─────────────────────────────────────────── │
│ [AI-focused answer grounded in ISU corpus]  │
│ Cited papers: [1] [2] [3]                   │
│ ISU faculty found: Sukul · Tavanapong · ... │
├─────────────────────────────────────────────┤
│ 🧠 General knowledge (LLM, not ISU corpus)  │
│ ─────────────────────────────────────────── │
│ [LLM-knowledge answer, clearly labeled]     │
│ ⚠ Not from ISU repository. May be outdated. │
└─────────────────────────────────────────────┘
```

Key UX rules:
- Top panel always shown, always ISU.
- Bottom panel only shown when user toggled include_general.
- Bottom panel uses a different visual treatment (different background, emoji, warning banner) so the distinction is obvious.
- Both panels load in parallel; the top panel renders first if ready first.

## Backend implementation

In `backend/services/qdrant_rag_service.py`, add a second method `_generate_general()`:

```python
async def _generate_general(self, query: str) -> str:
    """Answer `query` using only the LLM's training knowledge, no RAG context."""
    prompt = f"""You are a helpful research-assistant answering a general-knowledge question.
This answer is NOT from any specific institutional repository — it comes from your own training data.

Your response MUST:
- Be accurate and cite sources by name (e.g., 'Stanford HAI', 'AIIRA NSF AI Institute').
- Be clearly hedged when you are uncertain or when your training data may be outdated.
- Stay concise (3-6 sentences).

QUESTION: {query}

GENERAL-KNOWLEDGE ANSWER:"""
    # Call gemini with the same client; reduce max tokens for brevity.
    ...
```

And a driver method that composes both:

```python
async def search(self, query, top_k=8, include_general=False):
    isu_task = asyncio.create_task(self._search_isu(query, top_k))
    gen_task = asyncio.create_task(self._generate_general(query)) if include_general else None

    isu_result = await isu_task
    response = {
        "isu_answer": isu_result["answer"],
        "isu_citations": isu_result["citations"],
        # ... plus backward-compat aliases ...
    }
    if gen_task is not None:
        general = await gen_task
        response["general_answer"] = general
        response["general_source"] = f"{GEMINI_GEN_MODEL} training data"
        response["general_disclaimer"] = (
            "This section is from the LLM's general knowledge, NOT from the ISU repository. "
            "Information may be outdated or inaccurate."
        )
    return response
```

## Cost analysis

Per query today (`include_general=false`):
- 1 query embedding (Vertex text-embedding-005 online): negligible
- 1 Qdrant search: free (local or remote VM, already running)
- 1 Gemini 2.5 Flash Lite call: ~$0.0001

Per query with `include_general=true`:
- Same embedding + Qdrant search
- **2 Gemini 2.5 Flash Lite calls in parallel**: ~$0.0002

For a typical demo load (~500 queries/day), the extra cost is **$0.05/day = $1.50/month**. Negligible.

## Phased rollout

**Phase A — backend** (1 day work):
1. Implement `_generate_general()` + parallel driver in `qdrant_rag_service.py`
2. Add `include_general` query param on `/api/search`
3. Add new response fields (with backward-compat aliases)
4. Unit test that `include_general=false` response shape matches current

**Phase B — frontend** (1 day work):
1. Add opt-in checkbox above the search box
2. Add second panel card with visual differentiation
3. Handle `general_answer` being absent gracefully
4. Verify existing code still parses the old-shape fields from the ISU panel

**Phase C — evaluation** (half day):
1. Run `test_search_accuracy.py` against the new backend with and without `include_general`
2. Compare golden-query results against the current baseline
3. Eyeball 10 sample queries to sanity-check the general-knowledge panel

**Phase D — optional enhancements** (future):
- Stream both panels (SSE) for faster time-to-first-byte
- Remember user's `include_general` preference in localStorage
- Add a "Send this query to arXiv/MIT/Thai collections too" multi-collection toggle (connects to the expansion plan)

## Open questions

1. **Default on or off?** My recommendation is **off** — keeps the ISU identity clean and costs predictable. Users who want both can click one checkbox.
2. **Should the general-knowledge call be made against the same Gemini model** (2.5-flash-lite) or a smarter one (2.5-pro)? Lite is fine for 80% of queries and 4× cheaper.
3. **How do we want to label cross-institution content that IS actually in the ISU corpus?** E.g., a USDA report co-authored by ISU faculty + UIUC faculty should legitimately appear in the ISU panel, just with "(UIUC collaborator)" tags. Fix 1's prompt partially handles this, but we may want a follow-up iteration where we detect institution names and auto-tag them at the frontend.
4. **Telemetry** — should we track how often users opt into general-knowledge? Helpful for deciding whether to flip the default.

## What I need from you to proceed

- [ ] Approve the response shape above (or ask for edits)
- [ ] Confirm "off by default" opt-in model
- [ ] Approve the ~$1.50/month extra cost
- [ ] Decide if we ship this in the same deploy as Fix 1 + the new collection, or as a separate follow-up

Once approved, Phase A + B land in a single deploy (~1 day of focused work). Phase C is the existing accuracy test harness + a handful of spot checks.
