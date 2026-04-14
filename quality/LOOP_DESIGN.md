# Self-Improving Quality Loop — Design Doc

_Status: DRAFT, awaiting approval 2026-04-14_
_Goal: a continuously running QA system that catches RAG accuracy bugs in the ISU DSpace backend, investigates them with Claude Code, applies automated fixes when safe, and accumulates reusable lessons so each round gets smarter._

## Why

On 2026-04-14 a user search for "Adisak Sukul" returned citations to papers he never authored (curcumin photochemistry, sulfamethazine bioavailability), and the LLM hallucinated him into the author list. Nothing in the existing test harness caught it — `test_search_accuracy.py` only asserted structural things (found_faculty present, name variants resolve), never that the cited papers were actually authored by the target. The root cause was that the BM25 vocab had `adisak` missing entirely and `sukul` with doc_freq=1, so name queries fell through to dense-only retrieval which is terrible at exact name match. A different prompt / different collection / different user would have produced a different bug in the same class. We need a system that keeps finding these faster than a human manually testing.

## Four-layer architecture

```
┌─────────────────────────────────────────────────────────────┐
│  LAYER 1 — SCHEDULER                                        │
│    Claude Code scheduled trigger (cron, daily 03:00 UTC)    │
│    Fires a remote agent that runs the sweep and investigates│
└────────────────────────┬────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────┐
│  LAYER 2 — SWEEP (catches bugs)                             │
│    quality/sweep.py                                         │
│    - random 20-50 faculty, or all 355 CS faculty            │
│    - queries /api/search with each name                     │
│    - applies hard assertions:                               │
│        * every cited paper has target as author             │
│        * retrieved_chunks include real target papers        │
│        * found_faculty contains target                      │
│        * answer doesn't fabricate paper titles              │
│    - writes structured bug reports to quality/bug_log.jsonl │
└────────────────────────┬────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────┐
│  LAYER 3 — TRIAGE (classifies + routes)                     │
│    quality/triage.py                                        │
│    - reads new bugs from bug_log.jsonl (since last run)     │
│    - groups by bug_type + details.error_signature           │
│    - matches against quality/lessons.md patterns            │
│    - if KNOWN pattern: apply the recorded fix recipe        │
│      automatically (no investigation needed)                │
│    - if UNKNOWN: spawn an INVESTIGATION agent               │
│    - writes triage decisions to quality/triage_log.jsonl    │
└────────────────────────┬────────────────────────────────────┘
                         │
                         v
┌─────────────────────────────────────────────────────────────┐
│  LAYER 4 — INVESTIGATION (fixes)                            │
│    Claude Code subagent prompt in quality/investigate.md    │
│    - reads the unknown bug cluster                          │
│    - reads lessons.md (current known patterns)              │
│    - reads the relevant code paths (main.py, qdrant_rag)    │
│    - hypothesizes root cause                                │
│    - proposes + applies a fix                               │
│    - runs a targeted test (single faculty sweep) to verify  │
│    - if test passes:                                        │
│        * commit the code change (if in a git repo)          │
│        * ADD a new entry to lessons.md                      │
│        * mark bug as fixed in bug_log.jsonl                 │
│    - if test fails or fix is risky:                         │
│        * leave bug open                                     │
│        * write a "fix attempt" note in bug_log.jsonl        │
│        * flag for human review                              │
└─────────────────────────────────────────────────────────────┘
```

## File layout

```
quality/
├── sweep.py            # [BUILT] random-faculty hallucination detector
├── triage.py           # [TODO] reads bug log, matches patterns, routes
├── investigate.md      # [TODO] Claude Code agent prompt for unknown bugs
├── bug_log.jsonl       # append-only bug reports from sweep.py
├── runs.jsonl          # append-only per-run summaries
├── triage_log.jsonl    # append-only triage decisions (which fix recipe applied)
├── fixes_log.jsonl     # append-only code change history
├── lessons.md          # [BUILT, seeded w/ 8 initial lessons]
└── LOOP_DESIGN.md      # this file
```

## Key design decisions

### 1. Runs against the LIVE deployed backend, not local Qdrant

The whole point is to catch bugs that users would hit. Local Qdrant state might be ahead of or behind production. Sweep.py already takes `--api` and defaults to the Cloud Run URL.

### 2. Only tests production-visible behavior

Sweep only asserts on `/api/search` responses. Not on internal Qdrant structure. A bug is something a user would notice.

### 3. Bug classification drives auto-fix vs human escalation

| Severity | Auto-fix | Human escalation |
|---|---|---|
| **high** (hallucinated author, fabricated paper) | Only if pattern matches a known lesson recipe | Always log to triage_log |
| **medium** (missing found_faculty, retrieval quality gap) | Yes, after test-passes-locally check | Log to triage_log |
| **low** (LLM answer is awkward but factually OK) | No | Human only |

### 4. Memory has TWO layers

- **lessons.md**: durable pattern recipes (e.g., "BM25 vocab built from prefix → rebuild from full text"). Human-readable, long-lived. Each lesson has a detection heuristic and a fix recipe.
- **bug_log.jsonl + fixes_log.jsonl**: raw event log, append-only. The triage agent reads this to decide what's new.

Both are just files in the git repo. No database, no API server.

### 5. Investigation agent boundaries

- Can read any file, run Python, hit the live backend
- Can edit code under `backend/` and `quality/`
- CANNOT deploy (that's a human step — triage just flags "needs deploy" in the bug log)
- CANNOT change .gcloudignore, cloudbuild.yaml, or DB schema without human approval

### 6. Scheduling

Use `/schedule` skill to create a daily Claude Code remote trigger (cron). The trigger's prompt is:

> Read `quality/bug_log.jsonl` for bugs since the last run. For each new bug, match against `quality/lessons.md`. If known pattern, apply the recipe. If unknown, investigate and propose a fix. Commit any successful fixes to the repo. Do NOT deploy. Leave a summary in `quality/run_summary_<date>.md` for the human to review.

Runs once a day at 03:00 UTC (9pm Chicago / 10am Bangkok). Fast (~15 min on a small bug set).

### 7. Bootstrap problem

The loop needs an initial bug log to triage. Solution:
1. First run: sweep.py on 50 random CS faculty → produces the initial bug log
2. Human reviews the first batch to calibrate the triage rules
3. After the first round, the loop runs autonomously

## Open questions for user approval

1. **Is the project in a git repo?** Currently not per Bash tool. If not, the remote trigger can't commit fixes and we need a different persistence mechanism (GCS bucket? GitHub issue? email report?).

2. **What's the auto-fix appetite?** Proposed: auto-fix only for bugs that match a `lessons.md` recipe verbatim. Unknown bugs go to human review. Alternative: let Claude try anything and commit if tests pass. Riskier but more autonomous.

3. **Budget**: each scheduled run consumes ~20 min of Claude Code remote agent time + a small number of Gemini / OpenRouter judge calls. Expected cost: ~$1-3 per daily run = ~$30-90/month. Should we cap at $50/month?

4. **Alerting**: when a high-severity bug is caught, should the user get an email / Slack / nothing? Proposed: nothing — they check `quality/run_summary_*.md` on their own cadence. Alternative: use SendGrid or Slack webhook.

5. **Where should the lessons memory live?** Proposed: `quality/lessons.md` in the repo. Alternative: `~/.claude/projects/.../memory/quality_lessons.md` to survive repo changes.

6. **Should the investigation agent have WRITE access to the deployed backend?** Absolutely not. It only commits code — humans deploy.

## Incremental rollout

**Phase 1** (done or in progress):
- [x] `quality/sweep.py` — sweep runner
- [x] `quality/lessons.md` — seeded with 8 known lessons from this session
- [x] `quality/LOOP_DESIGN.md` — this doc
- [x] Initial run against live backend to catch current bugs

**Phase 2** (next, waiting on user approval):
- [ ] `quality/triage.py` — classifies bugs + applies known fix recipes
- [ ] `quality/investigate.md` — Claude Code agent prompt for unknown bugs
- [ ] Scheduled cron trigger (daily 03:00 UTC)
- [ ] First autonomous run, human review, calibrate

**Phase 3** (after Phase 2 proves stable):
- [ ] Extend sweep to cross-collection queries (query against dspace_chunks, dspace_fulltext_vertex, mit_dspace_vertex, arxiv_cs_vertex and cross-check)
- [ ] Add "golden query" regression set (hand-picked queries with known-correct answers)
- [ ] Add cross-judge (Gemini + Claude + GPT-5) voting for answer quality
- [ ] Integrate with the P4 eval sweep so accuracy drift is tracked over time

**Phase 4** (ambitious):
- [ ] Auto-generated test cases: use an LLM to generate adversarial queries based on the corpus
- [ ] Feedback loop: when a human fixes a bug that the loop missed, the fix gets added to lessons.md as a new detection heuristic
- [ ] Drift alerts: if accuracy drops week-over-week, triage escalates automatically
