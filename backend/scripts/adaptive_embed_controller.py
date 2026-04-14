"""
Adaptive controller for PDF embedding pipeline.
Monitors throughput every 15 minutes and adjusts workers/batch size
to maximize CPU/GPU utilization toward 80%.

Algorithm (AIMD-style):
  - If throughput increased or stayed same AND CPU < 80%:
      increase workers by 10%
  - If throughput dropped OR CPU > 85%:
      decrease workers to previous setting
  - Track history for analysis

Prints one status line per cycle (for Monitor integration).
"""

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
STATE_FILE = BACKEND / "data" / "embed_state" / "embed_state_nomic.json"
TUNING_FILE = BACKEND / "data" / "embed_state" / "adaptive_tuning.json"
SCRIPT = BACKEND / "scripts" / "embed_pdfs_ollama.py"

MODEL = "nomic-embed-text"
COLLECTION = "dspace_fulltext_nomic"
BATCH_SIZE = 128
CHECK_INTERVAL = 300  # 5 minutes

# Limits
MIN_WORKERS = 8
MAX_WORKERS = 32  # ThreadPoolExecutor cap (GIL-bound, beyond 32 threads causes contention)
TARGET_CPU = 80
TARGET_GPU = 80
CPU_CEILING = 85
RAMP_FACTOR = 1.10  # increase by 10%
DECREASE_FACTOR = 0.90  # decrease by 10%


def get_system_stats():
    import psutil
    cpu = psutil.cpu_percent(interval=1)
    ram = psutil.virtual_memory()

    gpu_util = 0
    gpu_mem = 0
    gpu_total = 0
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split(",")
        gpu_mem = int(parts[0].strip())
        gpu_total = int(parts[1].strip())
        gpu_util = int(parts[2].strip())
    except Exception:
        pass

    return {
        "cpu_pct": cpu,
        "ram_used_gb": ram.used / 1024 / 1024 / 1024,
        "ram_total_gb": ram.total / 1024 / 1024 / 1024,
        "ram_pct": ram.percent,
        "gpu_util": gpu_util,
        "gpu_mem_mb": gpu_mem,
        "gpu_total_mb": gpu_total,
    }


def get_embed_stats():
    try:
        s = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        done = len(s.get("processed_uuids", []))
        pts = s.get("total_points", 0)
        err = s.get("errors", 0)
        elapsed = s.get("elapsed_seconds", 0)
        return {"done": done, "points": pts, "errors": err, "elapsed": elapsed}
    except Exception:
        return {"done": 0, "points": 0, "errors": 0, "elapsed": 0}


def load_tuning():
    if TUNING_FILE.exists():
        try:
            return json.loads(TUNING_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "current_workers": 48,
        "current_batch": BATCH_SIZE,
        "history": [],
        "best_throughput": 0,
        "best_workers": 48,
    }


def save_tuning(t):
    TUNING_FILE.write_text(json.dumps(t, indent=2), encoding="utf-8")


def start_embed_process(workers, batch_size):
    env = os.environ.copy()
    env["OLLAMA_NUM_PARALLEL"] = str(min(workers // 3, 16))
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT),
         "--model", MODEL,
         "--collection", COLLECTION,
         "--batch-size", str(batch_size),
         "--workers", str(workers),
         "--resume"],
        cwd=str(BACKEND),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tuning = load_tuning()
    workers = tuning["current_workers"]
    batch_size = tuning["current_batch"]

    # Start initial process
    proc = start_embed_process(workers, batch_size)
    prev_done = get_embed_stats()["done"]
    prev_throughput = 0

    while True:
        time.sleep(CHECK_INTERVAL)

        # Collect stats
        stats = get_system_stats()
        embed = get_embed_stats()
        total = 97767

        # Calculate throughput for this interval
        interval_done = embed["done"] - prev_done
        throughput = interval_done / CHECK_INTERVAL  # PDFs/sec in this interval
        prev_done = embed["done"]

        pct = 100 * embed["done"] / total
        eta_h = (total - embed["done"]) / max(throughput, 0.001) / 3600

        # Decision
        action = "hold"
        new_workers = workers

        if stats["cpu_pct"] > CPU_CEILING or stats["ram_pct"] > 90:
            # Overloaded — decrease
            new_workers = max(MIN_WORKERS, int(workers * DECREASE_FACTOR))
            action = "decrease (CPU/RAM high)"
        elif throughput < prev_throughput * 0.85 and prev_throughput > 0:
            # Throughput dropped — decrease
            new_workers = max(MIN_WORKERS, int(workers * DECREASE_FACTOR))
            action = f"decrease (throughput dropped {prev_throughput:.1f}->{throughput:.1f})"
        elif stats["cpu_pct"] < TARGET_CPU and stats["gpu_util"] < TARGET_GPU:
            # Room to grow — increase
            new_workers = min(MAX_WORKERS, int(workers * RAMP_FACTOR))
            if new_workers == workers:
                new_workers = min(MAX_WORKERS, workers + 4)
            action = f"increase (CPU {stats['cpu_pct']:.0f}%<{TARGET_CPU}%)"
        else:
            action = "hold (near target)"

        # Record history
        tuning["history"].append({
            "time": time.strftime("%H:%M:%S"),
            "workers": workers,
            "batch": batch_size,
            "throughput": round(throughput, 2),
            "interval_pdfs": interval_done,
            "total_done": embed["done"],
            "points": embed["points"],
            "errors": embed["errors"],
            "cpu_pct": round(stats["cpu_pct"]),
            "gpu_util": stats["gpu_util"],
            "gpu_mem_mb": stats["gpu_mem_mb"],
            "ram_pct": round(stats["ram_pct"]),
            "action": action,
        })

        # Keep last 50 entries
        tuning["history"] = tuning["history"][-50:]

        if throughput > tuning["best_throughput"]:
            tuning["best_throughput"] = throughput
            tuning["best_workers"] = workers

        # Print status line (picked up by Monitor)
        print(
            f"Embed: {embed['done']:,}/{total:,} ({pct:.1f}%) | "
            f"{embed['points']:,}pts {embed['errors']}err {throughput:.1f}/s ETA{eta_h:.1f}h | "
            f"CPU {stats['cpu_pct']:.0f}% GPU {stats['gpu_util']}% "
            f"RAM {stats['ram_pct']:.0f}% VRAM {stats['gpu_mem_mb']}MB | "
            f"w={workers} -> {action}",
            flush=True,
        )

        prev_throughput = throughput

        # Apply change if needed
        if new_workers != workers:
            workers = new_workers
            tuning["current_workers"] = workers
            save_tuning(tuning)

            # Restart embed process with new workers
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                time.sleep(2)

            proc = start_embed_process(workers, batch_size)
        else:
            save_tuning(tuning)

            # Check if process died and restart
            if proc and proc.poll() is not None:
                proc = start_embed_process(workers, batch_size)

        # Stop if done
        if embed["done"] >= total - 100:
            print(f"Embed: COMPLETE — {embed['done']:,} PDFs, {embed['points']:,} points", flush=True)
            break


if __name__ == "__main__":
    main()
