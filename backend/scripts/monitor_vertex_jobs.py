"""Long-running watcher for the current 2-part Vertex batch embedding run.

Polls both parts (job names read from vertex_batch_state.json), logs state
transitions to vertex_monitor.log, and writes vertex_monitor_done.json with
completion stats + cost estimates as soon as both parts reach a terminal state
(SUCCEEDED / FAILED / CANCELLED / EXPIRED).

Back-off schedule: 60s for first 10 min, 120s for 10-30 min, 300s after.
Hard cap: 4 hours — the watcher aborts and writes a timeout record if neither
part has settled by then.

Usage:
    python backend/scripts/monitor_vertex_jobs.py
"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from google.cloud import aiplatform

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
STATE_FILE = BACKEND / "data" / "embed_state" / "vertex_batch_state.json"
LOG_FILE = BACKEND / "data" / "embed_state" / "vertex_monitor.log"
DONE_FILE = BACKEND / "data" / "embed_state" / "vertex_monitor_done.json"
SPLIT_DIR = BACKEND / "data" / "dspace" / "vertex_batch_split"

PROJECT = "rag-dspace"
LOCATION = "us-central1"

STATE_NAMES = {
    0: "UNSPECIFIED", 1: "QUEUED", 2: "PENDING", 3: "RUNNING",
    4: "SUCCEEDED", 5: "FAILED", 6: "CANCELLING", 7: "CANCELLED",
    8: "PAUSED", 9: "EXPIRED",
}
TERMINAL_STATES = {4, 5, 7, 9}
MAX_WAIT_SECONDS = 4 * 3600


def log(msg: str) -> None:
    line = f"[{datetime.now(timezone.utc).isoformat()}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def coerce_state(js) -> int:
    try:
        return int(js)
    except Exception:
        v = getattr(js, "value", None)
        if v is not None:
            return int(v)
        return -1


def count_chars_in_part(part_idx: int) -> int:
    path = SPLIT_DIR / f"chunks_part{part_idx}.jsonl"
    if not path.exists():
        return 0
    total = 0
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            try:
                d = json.loads(line)
                total += len(d.get("content", ""))
            except Exception:
                pass
    return total


def snapshot_job(job_name: str) -> dict:
    job = aiplatform.BatchPredictionJob(job_name)
    si = coerce_state(job.state)
    info = {
        "job_name": job_name,
        "state": si,
        "state_name": STATE_NAMES.get(si, f"UNK({si})"),
        "create_time": str(job.create_time) if getattr(job, "create_time", None) else None,
        "start_time": str(job.start_time) if getattr(job, "start_time", None) else None,
        "end_time": str(job.end_time) if getattr(job, "end_time", None) else None,
    }
    if si == 4:
        try:
            info["output_dir"] = job.output_info.gcs_output_directory
        except Exception:
            pass
    if si == 5:
        info["error"] = getattr(job.error, "message", None) or str(job.error)
    stats = getattr(job, "completion_stats", None)
    if stats:
        for k in ("successful_count", "failed_count", "incomplete_count"):
            v = getattr(stats, k, None)
            if v is not None:
                try:
                    info[k] = int(v)
                except Exception:
                    info[k] = str(v)
    return info


def main() -> int:
    if not STATE_FILE.exists():
        log(f"ERROR: state file missing at {STATE_FILE}")
        return 1

    state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    parts = state.get("parts", [])
    if not parts:
        log("ERROR: no parts found in state file")
        return 1

    job_names = []
    for i, part in enumerate(parts):
        jn = part.get("submit", {}).get("job_name")
        if not jn:
            log(f"ERROR: part {i} has no submit.job_name")
            return 1
        job_names.append(jn)

    aiplatform.init(project=PROJECT, location=LOCATION)

    log(f"Monitor started. Tracking {len(job_names)} Vertex batch jobs.")
    for i, n in enumerate(job_names):
        log(f"  part {i}: {n}")

    log("Counting input chars in each split file...")
    part_chars = [count_chars_in_part(i) for i in range(len(job_names))]
    total_chars = sum(part_chars)
    for i, c in enumerate(part_chars):
        log(f"  part {i}: {c:,} chars ({c / 1e9:.3f} B chars)")
    log(f"  total:  {total_chars:,} chars ({total_chars / 1e9:.3f} B chars)")

    start = time.time()
    poll_interval = 60

    while True:
        elapsed = int(time.time() - start)
        snaps = []
        all_terminal = True
        for i, n in enumerate(job_names):
            try:
                snap = snapshot_job(n)
            except Exception as e:
                log(f"  [part {i}] poll error: {type(e).__name__}: {e}")
                all_terminal = False
                snaps.append({"job_name": n, "state": -1, "state_name": "POLL_ERROR"})
                continue
            snaps.append(snap)
            if snap["state"] not in TERMINAL_STATES:
                all_terminal = False

        status_line = "  ".join(
            f"p{i}={s['state_name']}" + (
                f" ok={s.get('successful_count',0):,}"
                if s.get("successful_count") is not None else ""
            )
            for i, s in enumerate(snaps)
        )
        log(f"  t+{elapsed:>5}s  {status_line}")

        if all_terminal:
            log("All parts in terminal state.")
            break

        if elapsed > MAX_WAIT_SECONDS:
            log(f"WARNING: exceeded {MAX_WAIT_SECONDS}s hard cap; exiting")
            break

        if elapsed < 600:
            poll_interval = 60
        elif elapsed < 1800:
            poll_interval = 120
        else:
            poll_interval = 300
        time.sleep(poll_interval)

    summary = {
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "monitor_elapsed_s": int(time.time() - start),
        "total_input_chars": total_chars,
        "parts": [],
        "pricing_notes": {
            "vertex_online_rate": "$25 per 1B chars (text-embedding-005 per published rate)",
            "batch_rate_optimistic": "$0.20 per 1B chars (125x batch discount per prior user memory)",
            "batch_rate_typical": "$12.50 per 1B chars (~50% batch discount, typical industry default)",
            "verification": "Actual invoice appears in Cloud Billing within ~24h. Dashboard: https://console.cloud.google.com/billing",
        },
    }
    for i, n in enumerate(job_names):
        snap = snapshot_job(n)
        snap["part"] = i
        snap["input_chars"] = part_chars[i]
        summary["parts"].append(snap)

    b = total_chars / 1e9
    summary["estimated_cost_usd"] = {
        "if_online_rate": round(b * 25, 2),
        "if_batch_typical": round(b * 12.50, 2),
        "if_batch_optimistic": round(b * 0.20, 2),
    }

    all_success = all(p["state"] == 4 for p in summary["parts"])
    any_failed = any(p["state"] == 5 for p in summary["parts"])
    summary["outcome"] = (
        "ALL_SUCCEEDED" if all_success
        else "ANY_FAILED" if any_failed
        else "MIXED_OR_TIMEOUT"
    )

    DONE_FILE.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log(f"Wrote final summary to {DONE_FILE}")

    # Also write the output_dir back into vertex_batch_state.json so that
    # `embed_vertex_batch_real.py --phase ingest` can be run directly without
    # having to re-run `--phase check` first. Fixes the monitor/check state
    # sharing race (tracked as task #8, 2026-04-13).
    try:
        batch_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        batch_state = {}
    parts_in_state = batch_state.get("parts", [])
    for part_info in summary["parts"]:
        idx = part_info["part"]
        if idx >= len(parts_in_state):
            continue
        if part_info["state"] == 4 and part_info.get("output_dir"):
            parts_in_state[idx].setdefault("check", {})
            parts_in_state[idx]["check"]["state"] = "SUCCEEDED"
            parts_in_state[idx]["check"]["output_dir"] = part_info["output_dir"]
        elif part_info["state"] == 5:
            parts_in_state[idx].setdefault("check", {})
            parts_in_state[idx]["check"]["state"] = "FAILED"
            parts_in_state[idx]["check"]["error"] = part_info.get("error", "")
    batch_state["parts"] = parts_in_state
    STATE_FILE.write_text(json.dumps(batch_state, indent=2), encoding="utf-8")
    log(f"Updated {STATE_FILE.name} with per-part check.output_dir")
    log(f"Outcome: {summary['outcome']}")
    log(f"Estimated cost (batch typical):    ${summary['estimated_cost_usd']['if_batch_typical']}")
    log(f"Estimated cost (batch optimistic): ${summary['estimated_cost_usd']['if_batch_optimistic']}")
    log(f"Estimated cost (online rate):      ${summary['estimated_cost_usd']['if_online_rate']}")

    return 0 if all_success else (2 if any_failed else 3)


if __name__ == "__main__":
    sys.exit(main())
