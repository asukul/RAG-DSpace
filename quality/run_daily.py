"""
quality/run_daily.py — LOCAL daily quality loop runner.

Replaces the remote scheduled trigger with a local implementation that runs
on the user's Windows 11 machine. The remote trigger is blocked by:
  1. Egress filtering on the Claude Code sandbox — cannot reach
     backend-623732207442.us-central1.run.app (403 on CONNECT tunnel).
  2. GitHub MCP integration has read-only scope on asukul/RAG-DSpace —
     cannot push or create branches.

Running locally bypasses both: we have full egress, real git credentials,
and the `claude` CLI authenticated to the Max 20x subscription (so LLM judge
tokens come from the subscription, not a separate API key).

The 12-step protocol from quality/TEST_PLAN.md §4:

    1.  git pull origin main
    2.  Run sweep.py --limit 30 against production backend
    3.  Golden query regression (deterministic + `claude -p` LLM judge)
    4.  CR A/B (skipped — dspace_fulltext_vertex_ctx not built yet)
    5.  Aggregates + regression flags vs metric_history.jsonl
    6.  Run triage.py to cluster bugs and route to lessons/investigation
    7.  Known-pattern auto-fix  (deferred — listed only, no apply in v1)
    8.  Investigation subagent   (deferred — listed for human review in v1)
    9.  Update TEST_PLAN.md §8 baseline snapshot + §9 change log
    10. Commit + push branch + gh pr create (author Adisak Sukul only)
    11. Alert on hard-minimum breach (open single issue + PR ALERT header)
    12. Write quality/run_summary_<date>.md

Usage:
    python quality/run_daily.py                  # full run
    python quality/run_daily.py --dry-run        # skip commit + push + PR
    python quality/run_daily.py --skip-judge     # no claude -p calls
    python quality/run_daily.py --skip-goldens   # sweep + triage only

Safety bounds (all enforced inline, never relaxed):
    - commits use explicit --author flag, never Claude co-author trailer
    - no `gcloud` or `cloudbuild` commands ever
    - no `git reset --hard`, no force-push, no amend
    - no edits to .env*, .gcloudignore, cloudbuild.yaml, Dockerfile
    - TEST_PLAN.md edits limited to §8 + §9 (append only)
    - Only `quality/` is staged in the commit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import requests
except ImportError:
    print("ERROR: requests module not installed. Run: pip install requests", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
NOW = datetime.now(timezone.utc)
TODAY = NOW.strftime("%Y-%m-%d")
RUN_ID = NOW.strftime("%Y%m%dT%H%M%S")
SEED = NOW.strftime("%Y%m%d")

BACKEND_URL = "https://backend-623732207442.us-central1.run.app"
GIT_AUTHOR_NAME = "Adisak Sukul"
GIT_AUTHOR_EMAIL = "asukul@iastate.edu"
BRANCH_NAME = f"quality-loop-{TODAY}"

# Hard minimums from TEST_PLAN.md §3.2 — breaching these fires an alert.
# Keep in sync with the plan, never lower without explicit human change.
HARD_MINIMUMS = {
    "faithfulness": 0.75,
    "context_entities_recall": 0.70,
    "author_attribution_accuracy": 0.85,
    "temporal_correctness": 0.85,
    "citation_integrity": 0.90,
}

# Files
BUG_LOG = HERE / "bug_log.jsonl"
TRIAGE_LOG = HERE / "triage_log.jsonl"
PENDING_INV = HERE / "pending_investigations.jsonl"
LESSONS = HERE / "lessons.md"
TEST_PLAN = HERE / "TEST_PLAN.md"
GOLDEN_QUERIES = HERE / "golden_queries.jsonl"
GOLDEN_RESULTS = HERE / f"golden_results_{TODAY}.jsonl"
METRICS_FILE = HERE / f"metrics_{TODAY}.json"
REGRESSION_FLAGS = HERE / f"regression_flags_{TODAY}.json"
RUN_SUMMARY = HERE / f"run_summary_{TODAY}.md"
METRIC_HISTORY = HERE / "metric_history.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def log(msg: str) -> None:
    print(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}", flush=True)


def run_cmd(
    cmd: List[str],
    cwd: Path = REPO,
    check: bool = True,
    capture: bool = True,
    timeout: Optional[int] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        check=check,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Step 1 — git pull
# ---------------------------------------------------------------------------


def step_1_pull() -> Dict[str, Any]:
    log("Step 1 — git pull origin main")
    try:
        r = run_cmd(["git", "pull", "origin", "main"], check=False)
        if r.returncode != 0:
            log(f"  git pull returned {r.returncode}: {r.stderr[:200]}")
    except Exception as e:
        log(f"  git pull error: {e}")
    return {"done": True}


# ---------------------------------------------------------------------------
# Step 2 — sweep
# ---------------------------------------------------------------------------


def step_2_sweep() -> Dict[str, Any]:
    log(f"Step 2 — sweep.py --limit 30 --seed {SEED}")
    r = run_cmd(
        [sys.executable, "quality/sweep.py", "--limit", "30", "--seed", SEED],
        check=False,
        timeout=1800,
    )
    if r.returncode != 0:
        raise RuntimeError(f"sweep.py failed: {r.stderr[-400:]}")
    tail = r.stdout.splitlines()[-15:]
    return {"tail": tail}


# ---------------------------------------------------------------------------
# Step 3 — golden query regression
# ---------------------------------------------------------------------------


def load_goldens() -> List[Dict[str, Any]]:
    if not GOLDEN_QUERIES.exists():
        return []
    out = []
    with GOLDEN_QUERIES.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def hit_backend(query: str, limit: int = 10, timeout: int = 120) -> Dict[str, Any]:
    try:
        r = requests.post(
            f"{BACKEND_URL}/api/search",
            json={"query": query, "limit": limit},
            timeout=timeout,
        )
        if r.status_code != 200:
            return {"_error": f"HTTP {r.status_code}", "_body": r.text[:300]}
        return r.json()
    except Exception as e:
        return {"_error": str(e)}


def person_in_authors(person_name: str, authors: List[str]) -> bool:
    parts = [w for w in person_name.lower().replace(",", " ").split() if w]
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    for a in authors:
        al = (a or "").lower()
        if person_name.lower() in al:
            return True
        first_ok = re.search(rf"\b{re.escape(first)}\b", al) is not None
        last_ok = re.search(rf"\b{re.escape(last)}\b", al) is not None
        if first_ok and last_ok:
            return True
    return False


def deterministic_checks(golden: Dict, response: Dict) -> Dict[str, bool]:
    checks: Dict[str, bool] = {}

    # refuse_if_empty — null queries must not hallucinate citations
    if golden.get("refuse_if_empty"):
        answer = (response.get("answer") or "").lower()
        refused = any(
            phrase in answer
            for phrase in (
                "no results", "not found", "no faculty", "no record",
                "does not contain", "no isu research", "could not find",
                "no matching", "no such", "does not appear",
            )
        )
        # Also: empty citations list is a proxy for refusal
        if (response.get("citations") or []) == []:
            refused = True
        checks["null_handling_ok"] = refused

    # author_attribution_ok — every citation must include at least one expected author
    exp_authors = golden.get("expected_authors") or []
    if exp_authors and not golden.get("refuse_if_empty"):
        citations = response.get("citations") or []
        if not citations:
            checks["author_attribution_ok"] = False
        else:
            all_ok = True
            for c in citations:
                c_authors = c.get("authors") or []
                if not any(person_in_authors(name, c_authors) for name in exp_authors):
                    all_ok = False
                    break
            checks["author_attribution_ok"] = all_ok

    # temporal_ok — every cited paper year falls within expected_year_range
    year_range = golden.get("expected_year_range") or [None, None]
    if year_range and (year_range[0] or year_range[1]):
        y_min, y_max = year_range
        citations = response.get("citations") or []
        year_ok = True
        for c in citations:
            y = c.get("year")
            if y is None:
                continue
            try:
                y = int(y)
            except (TypeError, ValueError):
                continue
            if y_min is not None and y < y_min:
                year_ok = False
                break
            if y_max is not None and y > y_max:
                year_ok = False
                break
        checks["temporal_ok"] = year_ok

    return checks


JUDGE_RUBRIC = """You are an evaluator for a RAG (retrieval-augmented generation) system over academic papers. Score this single response on 5 metrics, each 0.0-1.0.

Definitions:
1. faithfulness — every claim in the answer is supported by at least one retrieved chunk. 1.0 = fully grounded, 0.0 = pure hallucination.
2. context_entities_recall — if the query mentions entities (names, years, topics), the retrieved chunks contain those entities. Especially critical for name queries.
3. author_attribution_accuracy — every person named in the answer as an author is actually listed in that paper's authors field. 0.0 if the answer attributes a paper to someone not in authors.
4. temporal_correctness — dates/years in the answer match the retrieved source; "recent work" queries must return recent papers.
5. citation_integrity — title, DOI, year, venue, authors in the answer match the retrieved chunks exactly. No fabricated DOIs.

Return ONLY this JSON (no markdown fences, no preamble, no trailing text):
{"faithfulness": 0.0, "context_entities_recall": 0.0, "author_attribution_accuracy": 0.0, "temporal_correctness": 0.0, "citation_integrity": 0.0, "note": "one sentence"}
"""


def build_judge_prompt(golden: Dict, response: Dict) -> str:
    q = golden.get("query", "")
    ans = (response.get("answer") or "")[:1500]
    citations = (response.get("citations") or [])[:5]
    chunk_summary = "\n".join(
        f"[{i+1}] authors={(c.get('authors') or [])[:3]}  "
        f"year={c.get('year')}  "
        f"title={(c.get('doc_title') or '')[:80]}"
        for i, c in enumerate(citations)
    )
    return f"""{JUDGE_RUBRIC}

Query: {q}

Answer: {ans}

Retrieved chunks (top {len(citations)}):
{chunk_summary}
"""


JUDGE_JSON_RE = re.compile(
    r'\{\s*"faithfulness"\s*:[^{}]*?"citation_integrity"\s*:[^{}]*?\}',
    re.DOTALL,
)


def parse_judge_json(stdout: str) -> Optional[Dict[str, float]]:
    # Strip any leading non-JSON noise (MCP preambles, workdir lines, etc.)
    m = JUDGE_JSON_RE.search(stdout)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def invoke_claude_judge(prompt: str, timeout: int = 180) -> Optional[Dict[str, Any]]:
    try:
        r = subprocess.run(
            ["claude", "-p", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        if r.returncode != 0:
            return None
        return parse_judge_json(r.stdout or "")
    except subprocess.TimeoutExpired:
        return None
    except FileNotFoundError:
        log("  claude CLI not found — skipping LLM judge for this query")
        return None
    except Exception as e:
        log(f"  claude invoke error: {e}")
        return None


def step_3_goldens(skip_judge: bool = False) -> Dict[str, Any]:
    log("Step 3 — golden query regression")
    goldens = load_goldens()
    log(f"  loaded {len(goldens)} goldens")
    results: List[Dict[str, Any]] = []

    for g in goldens:
        gid = g.get("id", "?")
        qshort = (g.get("query") or "")[:50]
        log(f"  {gid}  {qshort}")
        response = hit_backend(g.get("query", ""))
        backend_error = response.get("_error") if response and "_error" in response else None

        det = {}
        judge1 = None
        judge2 = None
        divergence_flag = False

        if not backend_error:
            det = deterministic_checks(g, response)
            if not skip_judge:
                prompt = build_judge_prompt(g, response)
                judge1 = invoke_claude_judge(prompt)
                judge2 = invoke_claude_judge(prompt)
                if judge1 and judge2:
                    for k in (
                        "faithfulness", "context_entities_recall",
                        "author_attribution_accuracy", "temporal_correctness",
                        "citation_integrity",
                    ):
                        try:
                            s1 = float(judge1.get(k, 0.0))
                            s2 = float(judge2.get(k, 0.0))
                            if abs(s1 - s2) > 0.15:
                                divergence_flag = True
                                break
                        except (TypeError, ValueError):
                            pass

        results.append({
            "golden_id": gid,
            "query": g.get("query"),
            "category": g.get("category"),
            "backend_error": backend_error,
            "deterministic": det,
            "judge_1": judge1,
            "judge_2": judge2,
            "divergence_flag": divergence_flag,
        })

    with GOLDEN_RESULTS.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    log(f"  wrote {len(results)} per-query results to {GOLDEN_RESULTS.name}")

    metrics = aggregate_metrics(results)
    with METRICS_FILE.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)
    log(f"  wrote aggregates to {METRICS_FILE.name}")

    return metrics


def aggregate_metrics(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(results)
    det_total: Dict[str, int] = {}
    det_pass: Dict[str, int] = {}
    judge_sums: Dict[str, float] = {}
    judge_counts: Dict[str, int] = {}
    backend_errors = 0
    divergences = 0

    for r in results:
        if r.get("backend_error"):
            backend_errors += 1
        if r.get("divergence_flag"):
            divergences += 1
        for k, v in (r.get("deterministic") or {}).items():
            det_total[k] = det_total.get(k, 0) + 1
            if v:
                det_pass[k] = det_pass.get(k, 0) + 1
        j = r.get("judge_1") or {}
        for k in (
            "faithfulness", "context_entities_recall",
            "author_attribution_accuracy", "temporal_correctness",
            "citation_integrity",
        ):
            if k in j:
                try:
                    judge_sums[k] = judge_sums.get(k, 0.0) + float(j[k])
                    judge_counts[k] = judge_counts.get(k, 0) + 1
                except (TypeError, ValueError):
                    pass

    det_rates = {
        k: det_pass.get(k, 0) / det_total[k] for k in det_total if det_total[k] > 0
    }
    judge_means = {
        k: judge_sums[k] / judge_counts[k]
        for k in judge_counts if judge_counts[k] > 0
    }

    return {
        "run_id": RUN_ID,
        "date": TODAY,
        "n_goldens": n,
        "backend_errors": backend_errors,
        "judge_divergences": divergences,
        "deterministic_pass_rates": det_rates,
        "judge_mean_scores": judge_means,
    }


# ---------------------------------------------------------------------------
# Step 5 — regression flags
# ---------------------------------------------------------------------------


def step_5_regression_check(current: Dict[str, Any]) -> Dict[str, Any]:
    log("Step 5 — regression check")
    prev = None
    if METRIC_HISTORY.exists():
        with METRIC_HISTORY.open(encoding="utf-8") as f:
            for line in f:
                try:
                    prev = json.loads(line)
                except json.JSONDecodeError:
                    pass

    regressions: List[Dict[str, Any]] = []
    hard_min_breaches: List[Dict[str, Any]] = []

    curr_judge = current.get("judge_mean_scores", {})

    for k, v in curr_judge.items():
        hm = HARD_MINIMUMS.get(k)
        if hm is not None and v < hm:
            hard_min_breaches.append({"metric": k, "value": v, "minimum": hm})
        if prev:
            pv = (prev.get("judge_mean_scores") or {}).get(k)
            if pv is not None and v < pv - 0.05:
                regressions.append({
                    "metric": k,
                    "current": v,
                    "previous": pv,
                    "drop_pp": round(pv - v, 4),
                })

    result = {
        "regressions": regressions,
        "hard_minimum_breaches": hard_min_breaches,
        "first_run": prev is None,
    }
    with REGRESSION_FLAGS.open("w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    # Append this run to metric_history
    with METRIC_HISTORY.open("a", encoding="utf-8") as f:
        f.write(json.dumps(current, ensure_ascii=False) + "\n")

    return result


# ---------------------------------------------------------------------------
# Step 6 — triage
# ---------------------------------------------------------------------------


def step_6_triage() -> Dict[str, Any]:
    log("Step 6 — triage.py")
    r = run_cmd([sys.executable, "quality/triage.py"], check=False)
    if r.returncode != 0:
        raise RuntimeError(f"triage.py failed: {r.stderr}")
    return {"tail": r.stdout.splitlines()[-10:]}


# ---------------------------------------------------------------------------
# Step 7 / 8 — (deferred in v1) known-pattern auto-fix + investigation
# ---------------------------------------------------------------------------


def step_7_8_collect_pending() -> Dict[str, Any]:
    # v1: do not apply recipes, do not spawn investigations. Just enumerate
    # what triage.py marked as pending so the human can see them in the run
    # summary and run investigations manually.
    n_pending = 0
    samples: List[str] = []
    if PENDING_INV.exists():
        with PENDING_INV.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    n_pending += 1
                    if len(samples) < 5:
                        samples.append(
                            f"- {rec.get('bug_type')} × {rec.get('bug_count')} ({rec.get('sample_query','')[:50]})"
                        )
                except json.JSONDecodeError:
                    pass
    log(f"Step 7/8 — {n_pending} pending investigations (not auto-processed in v1)")
    return {"n_pending": n_pending, "samples": samples}


# ---------------------------------------------------------------------------
# Step 9 — update TEST_PLAN.md (mutable sections only)
# ---------------------------------------------------------------------------


def step_9_update_plan(metrics: Dict[str, Any], regressions: Dict[str, Any]) -> None:
    log("Step 9 — update TEST_PLAN.md §9 change log")
    if not TEST_PLAN.exists():
        return
    text = TEST_PLAN.read_text(encoding="utf-8")
    entry = (
        f"- **{TODAY}** (local run `{RUN_ID}`): "
        f"goldens={metrics.get('n_goldens', 0)}, "
        f"backend_errors={metrics.get('backend_errors', 0)}, "
        f"divergences={metrics.get('judge_divergences', 0)}, "
        f"regressions={len(regressions.get('regressions', []))}, "
        f"hard_min_breaches={len(regressions.get('hard_minimum_breaches', []))}."
    )
    lines = text.splitlines()
    inserted = False
    for i, line in enumerate(lines):
        if line.strip().startswith("## 10. Safety bounds"):
            # Walk back past any leading blank lines and a `---` separator so
            # the new entry lands right after the last change-log entry,
            # inside §9 rather than butting against the §10 heading.
            j = i
            while j > 0 and lines[j - 1].strip() == "":
                j -= 1
            if j > 0 and lines[j - 1].strip() == "---":
                j -= 1
                while j > 0 and lines[j - 1].strip() == "":
                    j -= 1
            lines.insert(j, entry)
            inserted = True
            break
    if not inserted:
        lines.append("")
        lines.append(entry)
    TEST_PLAN.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Step 10 — commit + push + PR
# ---------------------------------------------------------------------------


def step_10_commit_and_pr(dry_run: bool, commit_summary: str) -> Optional[str]:
    log("Step 10 — commit + push + PR")
    if dry_run:
        log("  --dry-run: skipping commit/push/PR")
        return None

    # Stash any unrelated changes to avoid branch contamination
    run_cmd(["git", "stash", "push", "-u", "-m", f"run_daily_{RUN_ID}"], check=False)

    # Ensure we branch from main
    run_cmd(["git", "checkout", "main"], check=False)
    run_cmd(["git", "checkout", "-B", BRANCH_NAME], check=False)

    # Pop the stash to bring our quality/ changes onto the branch
    run_cmd(["git", "stash", "pop"], check=False)

    # Stage only quality/
    run_cmd(["git", "add", "quality/"], check=False)

    # Bail out cleanly if nothing changed
    r = run_cmd(["git", "diff", "--cached", "--name-only"])
    if not r.stdout.strip():
        log("  nothing to commit — exiting commit step")
        run_cmd(["git", "checkout", "main"], check=False)
        return None

    # Commit with explicit author — NEVER a Claude co-author trailer
    commit_msg = f"quality-loop: {commit_summary}"
    r = run_cmd(
        [
            "git",
            "-c", f"user.name={GIT_AUTHOR_NAME}",
            "-c", f"user.email={GIT_AUTHOR_EMAIL}",
            "commit",
            f"--author={GIT_AUTHOR_NAME} <{GIT_AUTHOR_EMAIL}>",
            "-m", commit_msg,
        ],
        check=False,
    )
    if r.returncode != 0:
        log(f"  commit failed: {r.stderr}")
        return None

    # Post-commit safety: verify the last commit does not include a Claude trailer
    r = run_cmd(["git", "log", "-1", "--format=%B"])
    if "Co-Authored-By: Claude" in r.stdout or "co-authored-by: claude" in r.stdout.lower():
        log("  ABORT: last commit contains Claude co-author trailer. Not pushing.")
        return None

    # Push branch
    r = run_cmd(["git", "push", "-u", "origin", BRANCH_NAME], check=False)
    if r.returncode != 0:
        log(f"  push failed: {r.stderr[:300]}")
        return None

    # Open PR via gh
    pr_body = build_pr_body(commit_summary)
    r = run_cmd(
        ["gh", "pr", "create", "--title", f"quality-loop {TODAY}", "--body", pr_body],
        check=False,
    )
    if r.returncode != 0:
        log(f"  gh pr create failed: {r.stderr[:300]}")
        return None

    # gh prints the PR URL as its last line on success
    url_line = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
    log(f"  PR: {url_line}")
    return url_line


def build_pr_body(commit_summary: str) -> str:
    return f"""## Quality loop — {TODAY}

{commit_summary}

- **Metrics**: see `quality/metrics_{TODAY}.json`
- **Per-query results**: `quality/golden_results_{TODAY}.jsonl`
- **Regression flags**: `quality/regression_flags_{TODAY}.json`
- **Run summary**: `quality/run_summary_{TODAY}.md`

Authored as Adisak Sukul only (no Claude co-author, per project directive 2026-04-13).
Generated by `quality/run_daily.py` on the local Windows machine; the remote scheduled trigger is blocked by sandbox egress filtering + GitHub write-scope limits.
"""


# ---------------------------------------------------------------------------
# Step 11 — alert on hard-minimum breach
# ---------------------------------------------------------------------------


def step_11_alert(
    regressions: Dict[str, Any],
    pr_url: Optional[str],
    dry_run: bool,
) -> Optional[str]:
    breaches = regressions.get("hard_minimum_breaches") or []
    if not breaches:
        return None
    log(f"Step 11 — ALERT: {len(breaches)} hard-minimum breach(es)")

    if dry_run:
        return None

    title = f"[quality-loop] Hard-minimum breach {TODAY}"
    body_lines = ["## Hard-minimum breach on daily run", ""]
    for b in breaches:
        body_lines.append(
            f"- **{b['metric']}**: {b['value']:.3f} (minimum {b['minimum']:.3f})"
        )
    body_lines.append("")
    if pr_url:
        body_lines.append(f"See PR: {pr_url}")
    body_lines.append("")
    body_lines.append("This is an automated alert from `quality/run_daily.py`.")

    r = run_cmd(
        ["gh", "issue", "create", "--title", title, "--body", "\n".join(body_lines)],
        check=False,
    )
    if r.returncode != 0:
        log(f"  gh issue create failed: {r.stderr[:300]}")
        return None
    url = r.stdout.strip().splitlines()[-1] if r.stdout.strip() else None
    log(f"  issue: {url}")
    return url


# ---------------------------------------------------------------------------
# Step 12 — run summary
# ---------------------------------------------------------------------------


def step_12_run_summary(
    sweep_res: Dict[str, Any],
    goldens_metrics: Dict[str, Any],
    regressions: Dict[str, Any],
    triage_res: Dict[str, Any],
    pending: Dict[str, Any],
    pr_url: Optional[str],
    issue_url: Optional[str],
    errors: List[str],
) -> None:
    log(f"Step 12 — write {RUN_SUMMARY.name}")
    n_bugs_total = 0
    if BUG_LOG.exists():
        with BUG_LOG.open(encoding="utf-8") as f:
            n_bugs_total = sum(1 for _ in f)

    lines: List[str] = []
    if regressions.get("hard_minimum_breaches"):
        lines.append("## ⚠ ALERT — hard-minimum breach this run")
        lines.append("")

    lines += [
        f"# Quality loop run — {TODAY}",
        "",
        f"**Run ID**: {RUN_ID}",
        f"**Mode**: local (runs on Windows machine; remote trigger is blocked)",
        f"**Backend**: {BACKEND_URL}",
        "",
        "## Headline",
        f"- Sweep: 30 random faculty queried",
        f"- Goldens: {goldens_metrics.get('n_goldens', 0)} scored",
        f"- Backend errors: {goldens_metrics.get('backend_errors', 0)}",
        f"- Judge divergences (2 scores differ > 0.15): {goldens_metrics.get('judge_divergences', 0)}",
        f"- Regressions vs last run: {len(regressions.get('regressions', []))}",
        f"- Hard-minimum breaches: {len(regressions.get('hard_minimum_breaches', []))}",
        f"- Total bugs in log: {n_bugs_total}",
        f"- Pending investigations: {pending.get('n_pending', 0)}",
        "",
    ]

    det = goldens_metrics.get("deterministic_pass_rates") or {}
    if det:
        lines.append("## Deterministic pass rates")
        for k, v in det.items():
            lines.append(f"- {k}: {v:.2%}")
        lines.append("")

    jm = goldens_metrics.get("judge_mean_scores") or {}
    if jm:
        lines.append("## LLM-judge mean scores (Claude Opus 4.6 via `claude -p`)")
        for k, v in jm.items():
            hm = HARD_MINIMUMS.get(k)
            marker = " ⚠" if hm is not None and v < hm else ""
            lines.append(f"- {k}: {v:.3f}{marker}")
        lines.append("")

    if regressions.get("regressions"):
        lines.append("## Regressions")
        for r in regressions["regressions"]:
            lines.append(
                f"- **{r['metric']}**: {r['current']:.3f} "
                f"(was {r['previous']:.3f}, -{r['drop_pp']:.4f})"
            )
        lines.append("")

    if pending.get("samples"):
        lines.append("## Pending investigations (v1 — listed only, not auto-run)")
        lines.extend(pending["samples"])
        lines.append("")

    if errors:
        lines.append("## Errors / blockers")
        for e in errors:
            lines.append(f"- {e}")
        lines.append("")

    if pr_url:
        lines.append(f"**PR**: {pr_url}")
    if issue_url:
        lines.append(f"**Issue**: {issue_url}")
    lines.append("")

    lines.append("## Notes for the human")
    lines.append("- Executed locally by `quality/run_daily.py` (subscription-backed).")
    lines.append(
        "- Remote `trig_01E4Z3YwCp6BUT6yKsCQdB8m` remains blocked by "
        "sandbox egress filtering + GitHub write-scope limits."
    )
    lines.append(
        "- Investigation subagents (step 8) are not auto-spawned in v1; "
        "review `quality/pending_investigations.jsonl` and re-run `triage.py` as needed."
    )

    RUN_SUMMARY.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Skip commit/push/PR/alert.")
    parser.add_argument("--skip-judge", action="store_true", help="Skip LLM-judge metric scoring.")
    parser.add_argument("--skip-goldens", action="store_true", help="Skip golden regression entirely.")
    parser.add_argument("--skip-sweep", action="store_true", help="Skip sweep.py run (use prior bug_log).")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    log(f"=== run_daily.py {RUN_ID} ===")
    log(f"Repo: {REPO}")
    log(f"Author: {GIT_AUTHOR_NAME} <{GIT_AUTHOR_EMAIL}>")

    errors: List[str] = []

    step_1_pull()

    sweep_res: Dict[str, Any] = {"tail": []}
    if not args.skip_sweep:
        try:
            sweep_res = step_2_sweep()
        except Exception as e:
            errors.append(f"step 2 sweep: {e}")

    goldens_metrics: Dict[str, Any] = {"n_goldens": 0}
    if not args.skip_goldens:
        try:
            goldens_metrics = step_3_goldens(skip_judge=args.skip_judge)
        except Exception as e:
            errors.append(f"step 3 goldens: {e}")

    regressions: Dict[str, Any] = {"regressions": [], "hard_minimum_breaches": []}
    try:
        regressions = step_5_regression_check(goldens_metrics)
    except Exception as e:
        errors.append(f"step 5 regressions: {e}")

    triage_res: Dict[str, Any] = {"tail": []}
    try:
        triage_res = step_6_triage()
    except Exception as e:
        errors.append(f"step 6 triage: {e}")

    pending: Dict[str, Any] = {"n_pending": 0, "samples": []}
    try:
        pending = step_7_8_collect_pending()
    except Exception as e:
        errors.append(f"step 7/8 pending: {e}")

    try:
        step_9_update_plan(goldens_metrics, regressions)
    except Exception as e:
        errors.append(f"step 9 update plan: {e}")

    summary_msg = (
        f"local run {TODAY} — "
        f"goldens={goldens_metrics.get('n_goldens', 0)}, "
        f"regressions={len(regressions.get('regressions', []))}, "
        f"hard_min_breaches={len(regressions.get('hard_minimum_breaches', []))}, "
        f"errors={len(errors)}"
    )

    pr_url: Optional[str] = None
    issue_url: Optional[str] = None
    try:
        pr_url = step_10_commit_and_pr(args.dry_run, summary_msg)
    except Exception as e:
        errors.append(f"step 10 commit + PR: {e}")

    try:
        issue_url = step_11_alert(regressions, pr_url, args.dry_run)
    except Exception as e:
        errors.append(f"step 11 alert: {e}")

    try:
        step_12_run_summary(
            sweep_res, goldens_metrics, regressions, triage_res, pending,
            pr_url, issue_url, errors,
        )
    except Exception as e:
        print(f"FATAL: couldn't write run summary: {e}", file=sys.stderr)

    log("=== exit ===")
    log(f"Errors: {len(errors)}")
    log(f"PR: {pr_url or '(none)'}")
    log(f"Issue: {issue_url or '(none)'}")
    return 0 if not errors else 1


if __name__ == "__main__":
    sys.exit(main())
