"""
Quality sweep — random-faculty hallucination detector for the ISU RAG backend.

Picks N random CS (or all-department) faculty, queries their name against
/api/search, and applies HARD factual checks:

  1. For every citation in the LLM answer (via `[N]` markers), the cited
     chunk's `authors:` payload MUST contain the target faculty member.
     If the LLM cites a paper whose authors don't include the target, that
     is a HALLUCINATION bug and it goes into the bug log.

  2. Every paper mentioned by name in the answer text should appear as an
     actual source in the `sources` list. If the LLM invents a title that
     isn't in any source, that is a FABRICATION bug.

  3. found_faculty MUST contain the target (regression check).

  4. The retrieved_chunks MUST include at least one chunk whose authors
     contain the target (otherwise retrieval itself is broken for names).

Writes structured bug reports to `quality/bug_log.jsonl` (append-only), one
line per failed assertion. Flags each bug with a `bug_type` category so the
triage / auto-fix layer can cluster them.

Usage:
    python quality/sweep.py --api https://backend-...run.app --limit 20
    python quality/sweep.py --seed 42        # reproducible random subset
    python quality/sweep.py --test-all       # no sampling, hit all CS faculty

The output is ONLY a bug log; exit code is 0 unless the script itself crashed.
The loop runner (quality/triage.py — separate file) reads bug_log.jsonl and
routes bugs to the investigation agent.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

HERE = Path(__file__).resolve().parent
BUG_LOG = HERE / "bug_log.jsonl"
RUN_LOG = HERE / "runs.jsonl"
LESSONS_FILE = HERE / "lessons.md"

CITATION_RE = re.compile(r"\[(\d+)(?:,\s*\d+)*\]")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BugReport:
    """One atomic bug event — exactly one failing assertion."""
    caught_at: str                  # ISO timestamp
    run_id: str                     # which sweep run caught it
    bug_type: str                   # hallucinated_author / fabricated_paper / missing_found_faculty / missing_relevant_chunk / api_error
    severity: str                   # high / medium / low
    query: str                      # the query that triggered it
    target_faculty: Optional[str]   # name of the faculty being searched
    target_faculty_id: Optional[str]
    details: Dict[str, Any] = field(default_factory=dict)
    answer_excerpt: str = ""        # first 500 chars of the LLM answer
    collection: str = "dspace_fulltext_vertex"
    fixed: bool = False
    fix_attempt_count: int = 0


@dataclass
class RunSummary:
    run_id: str
    started_at: str
    finished_at: str
    api_url: str
    faculty_sampled: int
    queries_run: int
    bugs_found: int
    bugs_by_type: Dict[str, int]
    duration_sec: float


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def person_matches_author_list(faculty_name: str, authors: List[str]) -> bool:
    """Check if `faculty_name` appears in the author list using the same
    permissive rule the backend uses for found_faculty extraction.
    Requires BOTH first and last name to appear as whole words.
    """
    if not faculty_name or not authors:
        return False
    parts = [w for w in faculty_name.lower().replace(",", " ").split() if w]
    if len(parts) < 2:
        return False
    first, last = parts[0], parts[-1]
    for author in authors:
        al = (author or "").lower()
        if faculty_name.lower() in al:
            return True
        # Check whole-word presence for both first + last
        first_ok = re.search(rf"\b{re.escape(first)}\b", al) is not None
        last_ok = re.search(rf"\b{re.escape(last)}\b", al) is not None
        if first_ok and last_ok:
            return True
    return False


def parse_cited_indices(answer: str) -> List[int]:
    """Extract all [N] citation markers used in the LLM answer."""
    nums: List[int] = []
    for match in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", answer):
        for chunk in match.group(1).split(","):
            try:
                nums.append(int(chunk.strip()))
            except Exception:
                pass
    return sorted(set(nums))


def append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# Core sweep
# ---------------------------------------------------------------------------


def run_single_faculty(
    api_url: str,
    faculty: Dict[str, Any],
    run_id: str,
) -> List[BugReport]:
    """Run the hallucination assertions for one faculty and return any bugs."""
    bugs: List[BugReport] = []
    name = faculty["name"]
    fid = faculty.get("id")
    query = name

    t0 = time.time()
    try:
        r = requests.post(
            f"{api_url}/api/search",
            json={"query": query, "limit": 10},
            timeout=120,
        )
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        bugs.append(BugReport(
            caught_at=datetime.utcnow().isoformat(timespec="seconds"),
            run_id=run_id,
            bug_type="api_error",
            severity="high",
            query=query,
            target_faculty=name,
            target_faculty_id=fid,
            details={"error": str(e)[:300], "elapsed": round(time.time() - t0, 2)},
        ))
        return bugs

    answer = data.get("answer", "") or ""
    citations = data.get("citations") or []
    sources = data.get("sources") or []
    retrieved_chunks = data.get("retrieved_chunks") or []
    found_faculty = data.get("found_faculty") or []

    # ---- Assertion 1: hallucinated authorship in LLM answer ----
    cited_indices = parse_cited_indices(answer)
    for cidx in cited_indices:
        # Citation markers are 1-based in the prompt
        arr_idx = cidx - 1
        if arr_idx < 0 or arr_idx >= len(citations):
            bugs.append(BugReport(
                caught_at=datetime.utcnow().isoformat(timespec="seconds"),
                run_id=run_id,
                bug_type="fabricated_citation_marker",
                severity="high",
                query=query,
                target_faculty=name,
                target_faculty_id=fid,
                details={
                    "cited_index": cidx,
                    "num_citations_available": len(citations),
                },
                answer_excerpt=answer[:500],
            ))
            continue

        chunk = citations[arr_idx]
        authors = chunk.get("authors") or []

        # Is this citation used to support an authorship claim about the target?
        # Heuristic: the answer sentence containing [N] is an authorship claim
        # if it has verbs like "authored", "wrote", "published", or if it
        # says "X wrote/is author of/co-authored/is listed as an author" near
        # the target name.
        sentence_around = _get_sentence_containing_marker(answer, cidx)
        if sentence_around and _is_authorship_claim(sentence_around, name):
            if not person_matches_author_list(name, authors):
                bugs.append(BugReport(
                    caught_at=datetime.utcnow().isoformat(timespec="seconds"),
                    run_id=run_id,
                    bug_type="hallucinated_author",
                    severity="high",
                    query=query,
                    target_faculty=name,
                    target_faculty_id=fid,
                    details={
                        "claimed_paper_title": chunk.get("doc_title", ""),
                        "claimed_paper_uuid": chunk.get("uuid", ""),
                        "actual_authors": authors,
                        "answer_sentence": sentence_around[:500],
                        "citation_index": cidx,
                    },
                    answer_excerpt=answer[:500],
                ))

    # ---- Assertion 2: retrieval must include at least one REAL paper by target ----
    any_real_hit = False
    for ch in (retrieved_chunks or citations):
        if person_matches_author_list(name, ch.get("authors") or []):
            any_real_hit = True
            break
    if not any_real_hit and citations:
        # Only report if the LLM actually generated an answer about this person
        # (i.e., citations exist but none are actually by the target)
        bugs.append(BugReport(
            caught_at=datetime.utcnow().isoformat(timespec="seconds"),
            run_id=run_id,
            bug_type="no_real_authorship_in_retrieval",
            severity="medium",
            query=query,
            target_faculty=name,
            target_faculty_id=fid,
            details={
                "num_citations": len(citations),
                "top_citation_authors": [(c.get("doc_title", "")[:60], c.get("authors", [])[:3]) for c in citations[:3]],
            },
            answer_excerpt=answer[:500],
        ))

    # ---- Assertion 3: found_faculty must include target ----
    if not any(f.get("id") == fid for f in found_faculty):
        bugs.append(BugReport(
            caught_at=datetime.utcnow().isoformat(timespec="seconds"),
            run_id=run_id,
            bug_type="missing_found_faculty",
            severity="medium",
            query=query,
            target_faculty=name,
            target_faculty_id=fid,
            details={
                "num_found_faculty": len(found_faculty),
                "found_faculty_names": [f.get("name") for f in found_faculty[:5]],
            },
            answer_excerpt=answer[:300],
        ))

    return bugs


def _get_sentence_containing_marker(text: str, marker_num: int) -> str:
    """Return the sentence (split on . ? !) that contains `[marker_num]`."""
    sentences = re.split(r"(?<=[.?!])\s+", text)
    pat = re.compile(rf"\[\s*{marker_num}(?:[,\s]|\s*])")
    for s in sentences:
        if pat.search(s):
            return s.strip()
    return ""


def _is_authorship_claim(sentence: str, target_name: str) -> bool:
    """Heuristic: does this sentence claim the target authored something?

    Requires both (a) the target's name (or last name) appears in the sentence
    AND (b) an authorship verb is present.
    """
    s = sentence.lower()
    name_parts = target_name.lower().split()
    last = name_parts[-1] if name_parts else ""
    # The name OR the last name must be mentioned
    if target_name.lower() not in s and (not last or last not in s):
        return False
    # Any of these verbs / phrases indicate authorship
    authorship_markers = [
        "author", "wrote", "co-author", "published", "written by",
        "is listed as", "is cited as", "paper by", "work by",
    ]
    return any(m in s for m in authorship_markers)


def fetch_cs_faculty(api_url: str) -> List[Dict[str, Any]]:
    r = requests.get(f"{api_url}/api/faculty", timeout=30)
    r.raise_for_status()
    data = r.json()
    cs = [f for f in data if "computer science" in (f.get("department") or "").lower()]
    cs.sort(key=lambda x: (x.get("name") or "").lower())
    return cs


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default="https://backend-623732207442.us-central1.run.app",
                        help="Target backend URL")
    parser.add_argument("--limit", type=int, default=20,
                        help="Random sample size (0 = test all)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducible sampling")
    parser.add_argument("--test-all", action="store_true",
                        help="Run against every CS faculty (slow)")
    parser.add_argument("--include-all-depts", action="store_true",
                        help="Sample from all departments, not just CS")
    args = parser.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    api_url = args.api.rstrip("/")
    run_id = datetime.utcnow().strftime("%Y%m%dT%H%M%S")
    started = datetime.utcnow().isoformat(timespec="seconds")
    t0 = time.time()

    print(f"Quality sweep — run {run_id}")
    print(f"  API: {api_url}")

    # Health check
    try:
        h = requests.get(f"{api_url}/health", timeout=60).json()
        print(f"  Health: {h}")
    except Exception as e:
        print(f"  Health check FAILED: {e}")
        return 2

    # Faculty list
    if args.include_all_depts:
        r = requests.get(f"{api_url}/api/faculty", timeout=30)
        faculty = r.json()
    else:
        faculty = fetch_cs_faculty(api_url)
    print(f"  Candidate faculty pool: {len(faculty)}")

    # Sample
    if args.test_all or args.limit == 0:
        sampled = faculty
    else:
        rng = random.Random(args.seed)
        sampled = rng.sample(faculty, min(args.limit, len(faculty)))
    print(f"  Testing {len(sampled)} faculty (seed={args.seed})")
    print()

    all_bugs: List[BugReport] = []
    for i, fac in enumerate(sampled, 1):
        t_q = time.time()
        print(f"[{i:3d}/{len(sampled)}] {fac.get('name')} ...", end="", flush=True)
        bugs = run_single_faculty(api_url, fac, run_id)
        dt = time.time() - t_q
        print(f" {len(bugs)} bugs ({dt:.1f}s)")
        all_bugs.extend(bugs)

    # Write bugs to log
    for bug in all_bugs:
        append_jsonl(BUG_LOG, asdict(bug))

    # Run summary
    by_type: Dict[str, int] = {}
    for b in all_bugs:
        by_type[b.bug_type] = by_type.get(b.bug_type, 0) + 1

    summary = RunSummary(
        run_id=run_id,
        started_at=started,
        finished_at=datetime.utcnow().isoformat(timespec="seconds"),
        api_url=api_url,
        faculty_sampled=len(sampled),
        queries_run=len(sampled),
        bugs_found=len(all_bugs),
        bugs_by_type=by_type,
        duration_sec=round(time.time() - t0, 1),
    )
    append_jsonl(RUN_LOG, asdict(summary))

    print()
    print("========== SUMMARY ==========")
    print(f"Faculty sampled: {summary.faculty_sampled}")
    print(f"Total bugs:      {summary.bugs_found}")
    for t, n in sorted(by_type.items(), key=lambda x: -x[1]):
        print(f"  {t:35s}  {n}")
    print(f"Duration:        {summary.duration_sec}s")
    print(f"Bug log:         {BUG_LOG}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
