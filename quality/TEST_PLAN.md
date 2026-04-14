# Daily RAG Test Plan — Self-Improving

_Status: DRAFT 2026-04-14 — awaiting first approved run._
_Owner: daily Claude Code scheduled trigger (Opus 4.6)._
_Architecture: see `LOOP_DESIGN.md`._

## 0. What this doc is

This is the **live test specification** for the self-improving RAG quality loop running against the ISU DSpace backend. The daily Claude Code scheduled trigger reads this file at the start of every run and is authorized to edit the sections marked **MUTABLE**. Immutable sections (the ranked metric list, the run protocol, the safety bounds) change only via human review.

The file exists because the loop must "remember what it already learned" across runs. Three files form the agent's persistent memory:

| File | Role | Who edits it |
|---|---|---|
| `TEST_PLAN.md` (this file) | WHAT to test, WHAT to aim for, evolving golden set, evolving baselines | Agent (mutable sections only) + human |
| `lessons.md` | HOW to fix each known class of bug (pattern → recipe) | Agent appends; human can edit |
| `bug_log.jsonl` | Raw event log of every failing assertion | Append-only, by `sweep.py` |

Before every run, the agent reads all three. After the run, the agent appends to `bug_log.jsonl` + `lessons.md` and may propose edits to the mutable sections here.

---

## 1. The ten things that matter (IMMUTABLE)

These are the ten measurements that correlate most strongly with user-visible correctness for an academic-paper RAG. Ranked by severity of failure and grounded in the 2024-2025 literature (FACTUM citation-hallucination study, MultiHop-RAG, SciQA, Anthropic eval guide).

| # | Metric | Failure looks like | Source |
|---|---|---|---|
| 1 | **Author-attribution accuracy** | LLM says "X wrote paper Y" when X is not in Y's author list | Hit 2026-04-14 (Adisak/curcumin) |
| 2 | **Faithfulness / groundedness** | LLM asserts a fact not supported by any retrieved chunk | RAGAS, DeepEval |
| 3 | **Context Entities Recall on name queries** | For query "papers by X", retrieved chunks do NOT mention X | RAGAS ContextEntitiesRecall |
| 4 | **Temporal correctness** | "Recent work" returns 2014 papers; year in answer ≠ year in source | arXiv 2507.22917 |
| 5 | **Null-query handling** | System hallucinates an answer for a faculty / topic that does not exist | MultiHop-RAG null category |
| 6 | **Citation integrity** | DOI, paper title, venue in the answer ≠ what the retrieved chunk says | FACTUM 2601.05866 |
| 7 | **Context Precision @ k** | Top-k retrieval is noise, not relevant papers | Classical IR + eRAG |
| 8 | **Cross-author attribution** | Multi-author paper's claim attributed to wrong coauthor / PI | Hit 2026-04-14 |
| 9 | **Thesis-vs-paper disambiguation** | Returns the thesis and attributes it to the advisor instead of the student | Lit. confirmed pattern |
| 10 | **Name-variant robustness** | "Adisak Sukul" / "A. Sukul" / "Sukul A" don't resolve to the same author | Name-disambiguation lit. |

The agent may not remove or reorder this list. The agent MAY add new metrics to §3.2 as it discovers new failure classes, but the top-10 list stays fixed.

---

## 2. Test suites (IMMUTABLE structure, MUTABLE content)

Three parallel suites run every day. Together they cover regression, discovery, and adversarial stress.

### 2.1 `sweep` — random-faculty production mirror
- **Runner**: `quality/sweep.py --limit 30 --seed <today's date>`
- **Purpose**: catch bugs that would surface for real users. Samples 30 random faculty per run (different sample each day via date-based seed).
- **Assertions**: the four hard checks already in `sweep.py` §4 — hallucinated_author, no_real_authorship_in_retrieval, missing_found_faculty, fabricated_citation_marker.
- **Output**: appends to `bug_log.jsonl`, writes run record to `runs.jsonl`.
- **Ownership**: the agent may add new assertions by editing `sweep.py` ONLY if the change is additive (new `bug_type` values, new checks). Removing existing assertions requires human review.

### 2.2 `golden` — fixed regression set
- **Runner**: `quality/run_goldens.py` (to build)
- **Source**: `quality/golden_queries.jsonl` — see §6 below.
- **Purpose**: the same 15-30 curated queries run every day, against the same backend. This is the "did we regress?" signal — if yesterday's goldens passed and today's don't, something changed.
- **Per-query fields**: `id`, `query`, `category`, `expected_authors[]`, `expected_year_range`, `expected_doc_uuids[]`, `refuse_if_empty` (bool), `known_good_answer` (reference), `added_on`, `last_verified`.
- **Grading**: two-layer — deterministic (author membership, year bounds, refuse-or-not) + LLM judge (RAGAS Faithfulness + DeepEval custom `AuthorAttributionCorrectness`). Both must pass.

### 2.3 `adversarial` — generated from failures
- **Runner**: `quality/run_adversarial.py` (to build)
- **Source**: `quality/adversarial_queries.jsonl` — grows automatically.
- **Purpose**: every confirmed bug gets 5 paraphrases auto-generated ("what if the user phrases it slightly differently?"). A fix that only works for the exact reported wording is not a fix. Pattern borrowed from Giskard RAGET + Anthropic's alignment-auditing loop.
- **Seeding rule**: when the investigation agent closes a bug with a working fix, it MUST append ≥5 paraphrases of the original query to this file.

---

## 3. Metrics and thresholds

### 3.1 Per-query metrics (IMMUTABLE — these are how we compute)

Each golden / sweep query produces a metric record with:

```json
{
  "query_id": "...",
  "deterministic": {
    "author_attribution_ok": true,
    "temporal_ok": true,
    "null_handled_ok": true,
    "citation_integrity_ok": true
  },
  "ragas": {
    "faithfulness": 0.92,
    "context_precision": 0.81,
    "context_entities_recall": 0.88,
    "answer_relevancy": 0.79
  },
  "deepeval": {
    "author_attribution_g_eval": 0.95,
    "hallucination_score": 0.03
  }
}
```

Deterministic metrics come from `sweep.py`-style assertions on response payloads — run in Python, zero LLM cost. LLM-judge metrics are computed **in-session by the Opus 4.6 trigger agent**, not via RAGAS/DeepEval libraries. The agent reads each query's `{query, retrieved_chunks, answer}` tuple and scores faithfulness, context-entities-recall, author-attribution, etc. using the RAGAS metric definitions as prompt rubrics. Scores are written to `metrics_<date>.json`. This keeps the full run within the Max 20x subscription (zero external API spend) and produces a unified conversation audit trail. Judge reliability mitigation: the agent scores each metric twice and flags any query where the two scores diverge by >0.15 for human review.

### 3.2 Run-level aggregates and thresholds (MUTABLE — agent may update targets, never relax below minimum)

| Metric | Current baseline | Target (soft) | Minimum (hard) | Last changed |
|---|---|---|---|---|
| Author-attribution accuracy | _TBD, first run_ | 95% | 85% | 2026-04-14 (initial) |
| Faithfulness (RAGAS) | _TBD_ | 0.90 | 0.75 | 2026-04-14 |
| Context Entities Recall (name queries only) | _TBD_ | 0.85 | 0.70 | 2026-04-14 |
| Temporal correctness | _TBD_ | 0.95 | 0.85 | 2026-04-14 |
| Null-query refusal rate | _TBD_ | 0.95 | 0.85 | 2026-04-14 |
| Citation integrity | _TBD_ | 0.98 | 0.90 | 2026-04-14 |
| Context Precision @ 10 | _TBD_ | 0.80 | 0.65 | 2026-04-14 |
| Cross-author attribution correctness | _TBD_ | 0.90 | 0.75 | 2026-04-14 |
| NDCG @ 10 (informational — not a gate) | _TBD_ | 0.75 | — | 2026-04-14 |

The agent may update "Current baseline" every run, update "Last changed" with its date, and may RAISE the soft target if three consecutive runs exceed the current target by >5pp. The agent may NOT lower the soft target or the minimum without human approval.

### 3.3 Regression detection (IMMUTABLE)

A regression is declared when ANY of:
- Any metric drops >5pp vs. the previous run,
- Any metric falls below its hard minimum,
- A golden query that passed yesterday fails today.

Regressions automatically open an investigation.

---

## 4. The daily run (IMMUTABLE protocol)

Order of operations for the scheduled trigger. Each step's outputs feed the next.

```
1.  git pull origin main
2.  RUN sweep.py --limit 30 --seed <YYYYMMDD>
       → appends to bug_log.jsonl, runs.jsonl
3.  RUN run_goldens.py
       → golden_results_<date>.jsonl + metrics_<date>.json
4.  RUN run_adversarial.py (if file non-empty)
       → adversarial_results_<date>.jsonl
5.  COMPUTE aggregates → run_metrics_<date>.json
6.  COMPARE vs previous run → regression_flags_<date>.json
7.  TRIAGE new bugs:
       - match each against lessons.md pattern index
       - KNOWN pattern → apply fix recipe automatically, verify with single-faculty sweep, log outcome
       - UNKNOWN pattern → spawn investigation subagent
8.  INVESTIGATION SUBAGENT (only for unknown bugs):
       - read lessons.md, TEST_PLAN.md, the failing query, the relevant backend code
       - hypothesize root cause
       - propose + apply a fix
       - re-run the failing query; if it now passes, re-run sweep.py on the single faculty to check for collateral damage
       - if all green: commit the fix (user name only, NO Claude co-author), append new entry to lessons.md, generate 5 paraphrases into adversarial_queries.jsonl
       - if any fail OR fix touches a protected file: leave bug OPEN, write a fix-attempt note to bug_log.jsonl, flag for human review
9.  AGENT PROPOSES PLAN UPDATES:
       - new baselines → §3.2 of this file
       - new golden queries → §6 of this file
       - new bug classes → new entry in lessons.md
       - append to §9 Change log
10. COMMIT all changes to github.com/asukul/RAG-DSpace (branch quality-loop-<date>):
       - author: Adisak Sukul <email> — MUST NOT include Claude co-author footer
       - do NOT push to main; open a PR instead so human can review
11. WRITE quality/run_summary_<date>.md with:
       - headline: pass/fail counts, regression flags
       - new bugs found
       - fixes applied (auto)
       - bugs left open for human
       - metric deltas vs. previous run
       - proposed plan edits
12. EXIT.  Do NOT deploy.
```

---

## 5. Self-improvement mechanisms (MUTABLE activation flags, IMMUTABLE mechanism definitions)

Five mechanisms make the loop smarter over time. Each has an ACTIVATION flag the human can flip.

### 5.1 Failure-cluster mining  _ACTIVE_
- After every run, embed all failing queries from the past 7 days (via the backend's dense embedder).
- HDBSCAN cluster (sklearn).
- Any cluster with ≥3 members becomes a named failure class → new entry in `lessons.md` with Pattern/Symptom/Root cause/Fix recipe fields, Root cause = "TBD — next investigation pass".
- Precedent: Anthropic's "source realistic tasks from the failures you see" principle.

### 5.2 Golden-query promotion  _ACTIVE_
- Every 7 days: the agent samples 100 queries from `sweep.py`'s own random-faculty output (later: from production search logs when available).
- Clusters them; surfaces any cluster that is not covered by the current golden set.
- Writes proposed new goldens to `quality/pending_goldens.jsonl` for human review.
- After 3 days of human silence (no comment, no edit, no rejection), the top 5 are auto-promoted to `golden_queries.jsonl`.
- Rejected goldens go to `quality/rejected_goldens.jsonl` (kept for provenance).

### 5.3 Judge calibration  _INACTIVE (enable after 30 days of data)_
- Monthly: sample 50 LLM-judge decisions from the past month, mixing high-confidence and low-confidence scores.
- Agent writes a judge-review batch to `quality/judge_review_queue.jsonl` and surfaces it in the run summary.
- Human labels (batch editable in an hour).
- Once labels exist: compute Cohen's κ between human and judge. If κ < 0.6, auto-append the disagreeing examples as few-shot exemplars to the judge prompt.
- Precedent: position-bias paper (arXiv 2406.07791) + Rating Roulette (arXiv 2510.27106).

### 5.4 Reference-solution drift detection  _ACTIVE_
- Every golden query has a `known_good_answer` reference.
- Before running the real eval, the agent runs all graders against the reference answer. The reference must pass all graders.
- If a grader fails on its own reference, **the grader is broken** — the agent writes a broken-grader alert to `run_summary`, skips the eval for that metric, does not "fix" the agent based on false signal.
- Precedent: Anthropic's "the reference answer catches grader bugs" — avoided the 42% vs 95% misread on Opus 4.5 CORE-Bench scoring.

### 5.5 Adversarial paraphrase generation  _ACTIVE_
- Every time the investigation agent closes a bug with a confirmed fix, it MUST generate ≥5 paraphrases of the failing query and append them to `adversarial_queries.jsonl`.
- Future runs test these automatically — a fix that doesn't generalize to paraphrases is detected within 24h.
- The investigation agent generates paraphrases via a short internal LLM call (no external tooling).

---

## 6. Current golden query set (MUTABLE — agent appends only)

Seed set of 15 queries spanning the six categories from §2.2. The agent may add to this list but may not delete existing entries. All entries live in the structured file `quality/golden_queries.jsonl`; this section is a human-readable summary only.

### 6.1 Faculty-name queries
- G001 "Show me papers by Adisak Sukul on machine learning" — BM25 name vocab + topic filter
- G002 "What is Hridesh Rajan's most recent publication?" — name + temporal-recent
- G003 "Papers co-authored by Sukul and Tavanapong" — intersection of two authors

### 6.2 Topic queries
- G004 "ISU dissertations on precision agriculture 2020-2024" — topic + genre (thesis) + date range
- G005 "Iowa State research on transformer models for crop disease" — deep topic match

### 6.3 Cross-reference queries
- G006 "Which ISU faculty have published on quantum computing with experimental validation?" — multi-hop
- G007 "Compare ISU's two most-cited papers on soil carbon sequestration" — multi-doc reasoning

### 6.4 Temporal queries
- G008 "First ISU thesis to use deep learning for crop disease detection" — first-of-kind
- G009 "ISU research on COVID-19 diagnostics published in 2021" — strict year filter
- G010 "Who at ISU was working on bioinformatics before 2010?" — pre-date filter

### 6.5 Author-disambiguation queries
- G011 "Papers by J. Smith in the College of Engineering" — homonym within ISU
- G012 "Wang's work on grain storage" — surname-only + topic

### 6.6 Null / negative queries
- G013 "ISU research on lunar regolith processing" — must return "no results", NEVER hallucinate
- G014 "Papers authored by Alice Nonexistent" — must refuse, not fabricate

### 6.7 Citation integrity
- G015 "Give me the full citation for 'Distributed Consensus for Smart Grids' including DOI and year" — every field must match the retrieved chunk exactly

Each entry has a `known_good_answer` captured during human review, so reference-drift detection (§5.4) can run against them.

---

## 7. Known bug patterns

See `quality/lessons.md`. As of 2026-04-14 it has 8 seeded lessons. The triage step (§4 step 7) reads it before spawning any investigation. New lessons are appended by the investigation agent after each confirmed fix.

---

## 8. Metric baseline snapshot (MUTABLE — updated every run)

This table is rewritten at every run. The agent pastes the latest aggregates here AND appends a new row to `quality/metric_history.jsonl`.

| Run date | Run ID | Author-attr | Faithfulness | CER (names) | Temporal | Null-refusal | Citation | CP@10 | NDCG@10 | Bugs found | Bugs fixed | Open |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-04-14 | _pending_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ | _TBD_ |

---

## 9. Change log (MUTABLE — agent appends)

- **2026-04-14** (human draft, by Adisak Sukul): initial plan based on 2024-2025 RAG eval research. Top-10 metric list frozen. Five self-improvement mechanisms defined; three active at start, judge-calibration off until 30 days of data exists. Seed golden set = 15 queries. No runs yet.
- **2026-04-14** (human decision): §11 Q2 resolved — commit workflow is PR-per-run on branch `quality-loop-<date>`. Human merges.
- **2026-04-14** (human decision): §11 Q6 resolved — Contextual Retrieval A/B active from Day 1. Target collection + contextualizer model pending.
- **2026-04-14** (human decision): §11 Q5 resolved — alerting is Option C (GitHub issue + PR ALERT header, only on hard-minimum breach or new severity:high bug, max 1 issue/run).
- **2026-04-14** (human decision): §11 Q6 sub-decision (a) resolved — CR target is ISU 50-faculty subset (~20k chunks, ~$10) into parallel `dspace_fulltext_vertex_ctx` collection. Graduates to full corpus on confirmed lift.
- **2026-04-14** (human decision): §11 Q1 resolved — Opus 4.6 in-session judge. No external RAGAS. All tokens under subscription. Drops the RAGAS/DeepEval Python dependency.
- **2026-04-14** (human decision): §11 Q6 sub-decision (b) resolved — CR contextualizer is Sonnet 4.6 with prompt caching. All Day-1 blockers now cleared.

---


- **2026-04-14** (local run `20260414T225042`): goldens=0, backend_errors=0, divergences=0, regressions=0, hard_min_breaches=0.
- **2026-04-14** (local run `20260414T225519`): goldens=15, backend_errors=0, divergences=4, regressions=0, hard_min_breaches=2.
## 10. Safety bounds (IMMUTABLE)

The daily agent operates with these hard limits. Violating any of them requires explicit human override in this doc.

- **No deploys.** The agent never runs `gcloud run deploy` or `gcloud builds submit`. Deployments are human-only.
- **No destructive git.** The agent never force-pushes, never amends published commits, never resets branches. All work lands on a fresh branch `quality-loop-<date>` and opens a PR for human review.
- **Commit authorship.** All commits use Adisak Sukul's name and email. The commit trailer MUST NOT include `Co-Authored-By: Claude` or any model attribution. (User directive, 2026-04-13.)
- **No secret edits.** The agent never edits `.env`, `cloudbuild.yaml`, `.gcloudignore`, `service-account-*.json`, or any file containing an API key.
- **No schema edits.** The agent never touches SQLite schema migrations, Qdrant collection creation/deletion, or OpenAlex import scripts.
- **No backend/ edits without a matching lessons.md recipe.** If the fix is not covered by an existing pattern, the investigation agent may PROPOSE the fix in a comment on the PR but may not apply it without human review. This prevents speculative code changes from landing silently.
- **No golden query deletions.** §6 entries are append-only. To retire a golden, a human edits the file.
- **3-attempt cap per unknown bug.** If the investigation agent cannot close a bug in 3 tries, it marks the bug as `status: escalated_to_human` in `bug_log.jsonl` and moves on.
- **Cost cap.** No more than 2M Opus tokens per daily run. If exhausted, write partial summary and exit.

---

## 11. Open questions for the first run (human decisions)

These need answers before the first autonomous run. They are tracked here so the first-run summary can reference the outcome.

1. **Judge model architecture?** **DECIDED 2026-04-14: Opus 4.6 in-session, no external RAGAS.** The daily Claude Code scheduled trigger runs Opus 4.6 end-to-end. Instead of calling RAGAS/DeepEval as external Python libraries (which would bill per-token against the Anthropic API), the trigger agent reads each test payload (query + retrieved chunks + answer) and scores every metric in its own reasoning — writing structured JSON output to `metrics_<date>.json`. All tokens count against the Max 20x subscription; zero external API spend. Quality: Opus > Sonnet on complex reasoning. Audit trail: single conversation log. Future Task C multi-judge extension can add OpenRouter if cross-family validation is needed later.
2. **Where to store metric history?** `quality/metric_history.jsonl` in the repo. Alternative: Google Cloud Storage bucket. Default: in-repo.
3. **How often does §5.2 promote pending goldens?** Default: weekly. Could be daily if signal-to-noise is high.
4. **Does the agent open PRs or push directly to a branch?** **DECIDED 2026-04-14: PR-per-run.** Every daily run creates branch `quality-loop-<date>` and opens a PR against `main` on `github.com/asukul/RAG-DSpace`. Human merges after review. No direct-to-main pushes ever.
5. **Alerting on high-severity bugs?** **DECIDED 2026-04-14: Option C — GitHub issue + PR description header.** Silent for normal runs. When any §3.2 metric drops below its **hard minimum** OR a new `severity: high` bug is found, the agent (a) opens a single GitHub issue on `asukul/RAG-DSpace` titled `[quality-loop] Hard-minimum breach YYYY-MM-DD` with the bug payload attached and (b) prepends an `## ⚠ ALERT` header block to that day's PR description. Soft-target breaches get logged in `run_summary` only, no issue. Max 1 issue per run.
6. **Contextual Retrieval A/B test?** **DECIDED 2026-04-14**:
   - Active from Day 1.
   - **Target: ISU 50-faculty subset** (~20k chunks, ~$10). Pick 50 random ISU faculty, find every chunk authored by them in `dspace_fulltext_vertex`, generate contextualized versions, re-embed, ingest into a parallel collection `dspace_fulltext_vertex_ctx`. The daily sweep A/Bs the 30-faculty random sample against both collections side-by-side. If the lift is clear, graduate to full ISU corpus (~$450). If not, we saved $440.
   - Contextualizer model: **DECIDED — Sonnet 4.6** with prompt caching (~$1/M tokens, Anthropic cookbook default). Opus is overkill for "summarize where this chunk sits in the doc."

---

## 12. Relationship to other docs

- `LOOP_DESIGN.md` — the 4-layer architecture. Read once to understand the system shape.
- `lessons.md` — the fix library. Read every run.
- `TEST_PLAN.md` (this file) — what to test and how. Read every run.
- `bug_log.jsonl` — the event log. Appended by `sweep.py`, read by triage.
- `runs.jsonl` — per-run summaries. Appended at run end.
- `run_summary_<date>.md` — human-readable run report. Written at run end.

When in conflict, human-edited content wins. The agent may propose edits to mutable sections, but every edit must show up as a diff in the run's commit and must be reviewable.