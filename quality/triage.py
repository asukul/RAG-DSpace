"""
Triage — reads bug_log.jsonl, clusters new bugs since the last run, matches
each cluster against lessons.md, and routes to either a known-pattern recipe
(auto-fix) or a fresh investigation.

Runs as a pure-Python script, no external deps beyond stdlib. Called by the
daily quality-loop trigger after sweep.py produces the bug log.

Inputs:
    quality/bug_log.jsonl      append-only bug events from sweep.py
    quality/lessons.md         pattern library, append-only
    quality/triage_log.jsonl   prior triage decisions (used for --since default)

Outputs:
    quality/triage_log.jsonl                append-only, one line per cluster
    quality/pending_investigations.jsonl    rewritten every run; only unknown
                                            clusters for the investigation agent

Usage:
    python quality/triage.py
    python quality/triage.py --since 2026-04-14T00:00:00
    python quality/triage.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
BUG_LOG = HERE / "bug_log.jsonl"
TRIAGE_LOG = HERE / "triage_log.jsonl"
LESSONS_FILE = HERE / "lessons.md"
PENDING_INVESTIGATIONS = HERE / "pending_investigations.jsonl"


# ---------------------------------------------------------------------------
# Clustering
# ---------------------------------------------------------------------------


def cluster_signature(bug: Dict[str, Any]) -> str:
    """Stable identifier for de-duplicating bug events into clusters.

    Two bugs share a signature iff they look like the same underlying problem.
    For hallucinated-author bugs we include the cited paper UUID so that two
    different hallucinations about the same faculty land in separate clusters.
    """
    bt = bug.get("bug_type", "")
    target = bug.get("target_faculty_id") or bug.get("target_faculty") or ""
    details = bug.get("details", {}) or {}
    if bt == "hallucinated_author":
        return f"{bt}::{target}::{details.get('claimed_paper_uuid', '')}"
    if bt == "fabricated_citation_marker":
        return f"{bt}::{target}::{details.get('cited_index', '')}"
    return f"{bt}::{target}"


# ---------------------------------------------------------------------------
# Log readers
# ---------------------------------------------------------------------------


def load_bugs_since(path: Path, since: Optional[str]) -> List[Dict[str, Any]]:
    """Return unfixed bugs whose caught_at timestamp is >= since (or all)."""
    if not path.exists():
        return []
    out: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                b = json.loads(line)
            except Exception:
                continue
            if b.get("fixed"):
                continue
            if since and b.get("caught_at", "") < since:
                continue
            out.append(b)
    return out


def last_triage_run(path: Path) -> Optional[str]:
    """Return the most recent run_at from triage_log.jsonl, or None."""
    if not path.exists():
        return None
    latest: Optional[str] = None
    with path.open(encoding="utf-8") as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            ts = r.get("run_at", "")
            if ts and (latest is None or ts > latest):
                latest = ts
    return latest


def parse_lessons(path: Path) -> List[Dict[str, Any]]:
    """Parse lessons.md into a list of structured entries.

    Each lesson starts with a `## N. Title` heading and is separated by `---`.
    We capture heading, number, title, full body, and any explicit detection
    phrase on `**How to detect from logs**:` so triage can match bug_types.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    lessons: List[Dict[str, Any]] = []
    sections = re.split(r"\n---\n", text)
    for sec in sections:
        m = re.search(r"^\s*##\s*(\d+)\.\s*(.+)", sec, flags=re.MULTILINE)
        if not m:
            continue
        try:
            num = int(m.group(1))
        except ValueError:
            continue
        title = m.group(2).strip()
        det_match = re.search(
            r"\*\*How to detect from logs\*\*:\s*(.+?)(?=\n\n|\n\*\*|\Z)",
            sec,
            flags=re.DOTALL,
        )
        detection = det_match.group(1).strip() if det_match else ""
        lessons.append({
            "number": num,
            "title": title,
            "body": sec.strip(),
            "detection": detection,
        })
    return lessons


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def match_lesson(
    bug: Dict[str, Any],
    lessons: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Return the first lesson whose body mentions the bug_type.

    Simple seed rule: if a lesson's detection phrase or body mentions the
    bug_type string exactly, the lesson applies. Agents append new lessons
    over time; as long as a new lesson says "look for `<bug_type>`" the match
    works without us editing this script.
    """
    bt = bug.get("bug_type", "")
    if not bt:
        return None
    for lesson in lessons:
        if bt in lesson.get("detection", "") or bt in lesson.get("body", ""):
            return lesson
    return None


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--since",
        help="Only triage bugs caught_at >= this ISO date. "
             "Default: most recent run_at in triage_log.jsonl, or 'forever'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write triage_log or pending_investigations.",
    )
    args = parser.parse_args()
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    since = args.since or last_triage_run(TRIAGE_LOG)
    print(f"[triage] reading bugs since {since or 'forever'}")

    bugs = load_bugs_since(BUG_LOG, since)
    if not bugs:
        print("[triage] no new bugs -- exiting clean")
        return 0
    print(f"[triage] {len(bugs)} new bugs")

    lessons = parse_lessons(LESSONS_FILE)
    print(f"[triage] {len(lessons)} lessons loaded")

    clusters: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for b in bugs:
        clusters[cluster_signature(b)].append(b)
    print(f"[triage] {len(clusters)} distinct clusters")

    run_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    decisions: List[Dict[str, Any]] = []
    known_count = 0
    unknown_count = 0
    for sig, cluster_bugs in clusters.items():
        first = cluster_bugs[0]
        lesson = match_lesson(first, lessons)
        base = {
            "run_at": run_at,
            "signature": sig,
            "bug_type": first.get("bug_type"),
            "bug_count": len(cluster_bugs),
            "sample_query": first.get("query"),
            "sample_target": first.get("target_faculty"),
            "sample_severity": first.get("severity"),
        }
        if lesson:
            decisions.append({
                **base,
                "action": "known_pattern",
                "matched_lesson": {
                    "number": lesson["number"],
                    "title": lesson["title"],
                },
            })
            known_count += 1
        else:
            decisions.append({
                **base,
                "action": "investigate",
                "matched_lesson": None,
                "sample_details": first.get("details", {}),
            })
            unknown_count += 1

    print()
    print(f"[triage] {known_count} known-pattern clusters (auto-fix recipe available)")
    print(f"[triage] {unknown_count} unknown clusters (investigation needed)")

    if args.dry_run:
        print("[triage] --dry-run: not writing any files")
        return 0

    with TRIAGE_LOG.open("a", encoding="utf-8") as f:
        for d in decisions:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"[triage] wrote {len(decisions)} decisions to {TRIAGE_LOG.name}")

    unknowns = [d for d in decisions if d["action"] == "investigate"]
    with PENDING_INVESTIGATIONS.open("w", encoding="utf-8") as f:
        for d in unknowns:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"[triage] wrote {len(unknowns)} unknowns to {PENDING_INVESTIGATIONS.name}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
