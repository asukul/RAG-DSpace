"""OCR PRT documents via Typhoon-OCR baseline + Claude Opus post-correction.

v0.1 architecture: pre-compute Typhoon's output (or reuse the cached
papers_text_typhoon/ from the existing pipeline), then ask Claude Opus
to verify against the page images and correct errors.

This is the v0.1 of "Path B" — measure whether Claude correction can
exceed Typhoon-alone on PRT before investing in a full MCP server.

Bake-off recipe:
    # Smoke test on 3 docs (~$0.05, ~5 min)
    py -3 tenants/prt/scripts/ocr_prt_opus_typhoon_hybrid.py --max 3 --parallel 1

    # Full 50-doc bake-off (~$0.50-1.00, ~30 min)
    py -3 tenants/prt/scripts/ocr_prt_opus_typhoon_hybrid.py --max 50 --parallel 2

Output goes to vault/papers_text_opus_typhoon_hybrid/ (separate from
existing papers_text_opus/ and papers_text_typhoon/ so the 5-way
comparison harness can compare all three directly).
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parents[3]
PRT_DATA = REPO / "tenants" / "prt" / "data"
PRT_TRACKER = PRT_DATA / "prt_pdf_tracker.csv"
PRT_VAULT_PAPERS = PRT_DATA / "vault" / "papers"
PRT_PAPERS_TEXT_TYPHOON = PRT_DATA / "vault" / "papers_text_typhoon"
PRT_PAPERS_TEXT = PRT_DATA / "vault" / "papers_text_opus_typhoon_hybrid"   # NEW: separate output
LOGS_DIR = PRT_DATA / "ocr_opus_typhoon_hybrid_logs"
STATE_FILE = PRT_DATA / "ocr_opus_typhoon_hybrid_state.json"
STOP_FILE = PRT_DATA / "ocr_opus_typhoon_hybrid_stop.flag"
LOCK_FILE = PRT_DATA / "ocr_opus_typhoon_hybrid_run.lock"
SKILL_FILE = REPO / "tenants" / "prt" / "skills" / "opus-typhoon-hybrid-ocr" / "SKILL.md"

CLAUDE_MODEL = "claude-opus-4-7"
PER_PDF_TIMEOUT_S = 360
PNG_DPI_SCALE = 2.0
MAX_PAGES_PER_DOC = 6
MIN_OUTPUT_CHARS = 30
MAX_TYPHOON_TEXT_CHARS = 12_000   # cap to keep prompt sane; PRT pages rarely exceed this

RATE_LIMIT_PATTERNS = [
    "rate limit", "rate-limit", "rate_limit", "429", "too many requests",
    "ratelimit", "usage limit", "5-hour limit", "5 hour limit", "5-hour",
    "5 hour", "weekly limit", "monthly limit", "quota exceeded",
    "exceeded your quota", "approaching your usage limit",
    "approaching usage limit", "credit balance", "limit reached",
    "limit exceeded", "subscription limit", "session limit",
    "claude code limit", "claude usage", "try again later", "try again in",
    "please wait", "resets in", "resets at", "exceeded", "out of credits",
    "no credit", "insufficient",
]
SUSPICIOUS_SHORT_STDOUT_BYTES = 200
RATE_LIMIT_LONG_PAUSE_S = 30 * 60

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

LOG_FP = None
LOG_LOCK = threading.Lock()


def ts() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line, flush=True)
    if LOG_FP is not None:
        with LOG_LOCK:
            LOG_FP.write(line + "\n")
            LOG_FP.flush()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ----------------------------------------------------------------------
# Shard / state
# ----------------------------------------------------------------------

def shard_for(doc_id: str) -> str:
    return doc_id[-2:] if len(doc_id) >= 2 else "00"


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            log(f"WARN: failed to parse state file at {STATE_FILE}; starting fresh")
    return {"started_at": now_iso(), "docs": {}}


_STATE_LOCK = threading.Lock()


def save_state(state: dict) -> None:
    state["updated_at"] = now_iso()
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, STATE_FILE)


def update_doc_state(state: dict, doc_id: str, **fields) -> None:
    with _STATE_LOCK:
        entry = state["docs"].setdefault(doc_id, {})
        entry.update(fields)
        entry["ts"] = now_iso()


# ----------------------------------------------------------------------
# Tracker → pdf map (identical pattern)
# ----------------------------------------------------------------------

def load_pdf_path_map() -> dict[str, Path]:
    if not PRT_TRACKER.exists():
        log(f"FATAL: tracker CSV not found: {PRT_TRACKER}")
        sys.exit(1)
    out: dict[str, Path] = {}
    with PRT_TRACKER.open(encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for row in rdr:
            handle = (row.get("handle") or "").strip()
            pdf_path = (row.get("pdf_path") or "").strip()
            status = (row.get("status") or "").strip()
            if not handle or not pdf_path or status != "downloaded":
                continue
            suffix = handle.rsplit("/", 1)[-1]
            doc_id = f"prt-{suffix}"
            p = Path(pdf_path)
            if p.exists():
                out[doc_id] = p
    return out


# ----------------------------------------------------------------------
# Doc selection: only docs that have a Typhoon baseline AND aren't already done
# ----------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def parse_simple_frontmatter(text: str) -> dict:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}
    out: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith(" ") or line.startswith("-"):
            continue
        k, _, v = line.partition(":")
        k = k.strip()
        v = v.strip()
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        out[k] = v
    return out


def find_docs_needing_hybrid(state: dict) -> list[str]:
    """Image-only docs that:
      - HAVE a Typhoon output already (we read & post-correct it)
      - do NOT already have a hybrid output
      - aren't already terminal in state
    """
    needing: list[str] = []
    skip_done = 0
    skip_no_typhoon = 0
    skip_terminal = 0
    for md in PRT_VAULT_PAPERS.rglob("*.md"):
        try:
            head = md.read_text(encoding="utf-8", errors="replace")[:2048]
        except Exception:
            continue
        meta = parse_simple_frontmatter(head)
        if meta.get("content_source") != "metadata_only_image_pdf":
            continue
        doc_id = meta.get("doc_id") or md.stem
        out_path = PRT_PAPERS_TEXT / shard_for(doc_id) / f"{doc_id}.txt"
        if out_path.exists() and out_path.stat().st_size >= MIN_OUTPUT_CHARS:
            skip_done += 1
            continue
        # Typhoon baseline required
        typh_path = PRT_PAPERS_TEXT_TYPHOON / shard_for(doc_id) / f"{doc_id}.txt"
        if not (typh_path.exists() and typh_path.stat().st_size >= MIN_OUTPUT_CHARS):
            skip_no_typhoon += 1
            continue
        prev = state["docs"].get(doc_id)
        if prev and prev.get("status") in (
            "ok", "failed_no_pdf", "failed_render", "failed_too_short", "failed_no_typhoon"
        ):
            skip_terminal += 1
            continue
        needing.append(doc_id)
    log(f"  {skip_done:,} already have hybrid output")
    log(f"  {skip_no_typhoon:,} skipped (no Typhoon baseline yet)")
    log(f"  {skip_terminal:,} skipped (terminal state in state file)")
    return sorted(needing)


def read_typhoon_text(doc_id: str) -> Optional[str]:
    p = PRT_PAPERS_TEXT_TYPHOON / shard_for(doc_id) / f"{doc_id}.txt"
    if not p.exists():
        return None
    try:
        t = p.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if len(t) > MAX_TYPHOON_TEXT_CHARS:
        # Keep head + tail with a marker so Claude sees the truncation
        head = t[: MAX_TYPHOON_TEXT_CHARS // 2]
        tail = t[-(MAX_TYPHOON_TEXT_CHARS // 2):]
        t = f"{head}\n\n[...{len(t) - MAX_TYPHOON_TEXT_CHARS} chars truncated...]\n\n{tail}"
    return t


# ----------------------------------------------------------------------
# Rendering pages (identical to vanilla opus)
# ----------------------------------------------------------------------

def render_pdf_pages(pdf_path: Path, max_pages: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    try:
        doc = fitz.open(str(pdf_path))
    except Exception as e:
        log(f"  fitz.open FAILED for {pdf_path.name}: {e}")
        return []
    try:
        n = min(len(doc), max_pages)
        for i in range(n):
            try:
                pix = doc[i].get_pixmap(matrix=fitz.Matrix(PNG_DPI_SCALE, PNG_DPI_SCALE))
                p = out_dir / f"page-{i+1:03d}.png"
                pix.save(str(p))
                paths.append(p)
            except Exception as e:
                log(f"  render FAILED page {i+1} of {pdf_path.name}: {e}")
                continue
    finally:
        doc.close()
    return paths


# ----------------------------------------------------------------------
# Skill loading + prompt building
# ----------------------------------------------------------------------

_SKILL_BODY: Optional[str] = None


def load_skill_body() -> str:
    global _SKILL_BODY
    if _SKILL_BODY is not None:
        return _SKILL_BODY
    if not SKILL_FILE.exists():
        log(f"FATAL: skill file not found at {SKILL_FILE}")
        sys.exit(1)
    raw = SKILL_FILE.read_text(encoding="utf-8")
    m = re.match(r"^---\n.*?\n---\n", raw, re.DOTALL)
    body = raw[m.end():] if m else raw
    _SKILL_BODY = body.strip()
    return _SKILL_BODY


def build_hybrid_prompt(pages: list[Path], typhoon_text: str) -> str:
    skill = load_skill_body()
    pages_listing = "\n".join(f"  Page {i+1}: {p}" for i, p in enumerate(pages))
    return (
        f"{skill}\n\n"
        f"---\n\n"
        f"INPUTS FOR THIS DOCUMENT:\n\n"
        f"Page images (read each via the Read tool, in order):\n{pages_listing}\n\n"
        f"Typhoon-OCR baseline output (your starting point — verify and correct):\n"
        f"```\n{typhoon_text}\n```\n\n"
        f"Begin corrected OCR output now."
    )


# ----------------------------------------------------------------------
# Claude CLI invocation (identical retry/rate-limit pattern)
# ----------------------------------------------------------------------

def resolve_claude_exe() -> Optional[str]:
    return shutil.which("claude")


def call_claude_hybrid(pages: list[Path], typhoon_text: str, timeout: int = PER_PDF_TIMEOUT_S) -> dict:
    exe = resolve_claude_exe()
    if not exe:
        return {"returncode": -1, "stdout": "", "stderr": "claude CLI not found"}
    prompt = build_hybrid_prompt(pages, typhoon_text)
    t0 = time.time()
    try:
        r = subprocess.run(
            [
                exe, "-p",
                "--model", CLAUDE_MODEL,
                "--allowedTools", "Read",
                "--add-dir", str(REPO),
            ],
            input=prompt,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return {
            "returncode": r.returncode,
            "stdout": r.stdout or "",
            "stderr": (r.stderr or "")[:2000],
            "elapsed_sec": round(time.time() - t0, 2),
        }
    except subprocess.TimeoutExpired:
        return {"returncode": -1, "stdout": "", "stderr": "timeout", "elapsed_sec": timeout}
    except Exception as e:
        return {"returncode": -1, "stdout": "", "stderr": str(e)[:300],
                "elapsed_sec": round(time.time() - t0, 2)}


def is_rate_limit(stdout: str, stderr: str, returncode: int = 0) -> bool:
    s = (stdout + "\n" + stderr).lower()
    if any(p in s for p in RATE_LIMIT_PATTERNS):
        return True
    if returncode != 0 and 0 < len(stdout.strip()) <= SUSPICIOUS_SHORT_STDOUT_BYTES:
        return True
    return False


def call_with_retry(pages: list[Path], typhoon_text: str) -> dict:
    backoff = 5
    r = {"returncode": -1, "stdout": "", "stderr": ""}
    for attempt in range(6):
        r = call_claude_hybrid(pages, typhoon_text)
        if r["returncode"] == 0 and len(r.get("stdout", "")) >= MIN_OUTPUT_CHARS:
            return r
        if is_rate_limit(r.get("stdout", ""), r.get("stderr", ""), r.get("returncode", 0)):
            wait = min(120, backoff * (2 ** attempt))
            snippet = (r.get("stdout", "") or "").strip().replace("\n", " ")[:120]
            log(f"  rate-limit hit; sleeping {wait}s (quick {attempt+1}/6) | stdout='{snippet}'")
            time.sleep(wait)
            continue
        time.sleep(min(15, backoff + attempt * 3))

    if is_rate_limit(r.get("stdout", ""), r.get("stderr", ""), r.get("returncode", 0)):
        long_attempt = 0
        while True:
            if STOP_FILE.exists():
                log("  stop flag set during rate-limit wait; aborting this doc")
                return r
            log(
                f"  persistent usage-limit; sleeping {RATE_LIMIT_LONG_PAUSE_S//60}min "
                f"(long {long_attempt+1})"
            )
            slept = 0
            while slept < RATE_LIMIT_LONG_PAUSE_S:
                if STOP_FILE.exists():
                    log("  stop flag set during rate-limit wait; aborting this doc")
                    return r
                time.sleep(min(30, RATE_LIMIT_LONG_PAUSE_S - slept))
                slept += 30
            r = call_claude_hybrid(pages, typhoon_text)
            if r["returncode"] == 0 and len(r.get("stdout", "")) >= MIN_OUTPUT_CHARS:
                log(f"  usage-limit cleared after {long_attempt+1} long-pause retries")
                return r
            if not is_rate_limit(r.get("stdout", ""), r.get("stderr", ""), r.get("returncode", 0)):
                return r
            long_attempt += 1
    return r


# ----------------------------------------------------------------------
# Per-doc worker
# ----------------------------------------------------------------------

def hybrid_one_doc(doc_id: str, pdf_path: Path) -> dict:
    if not pdf_path.exists():
        return {"status": "failed_no_pdf", "chars": 0, "pages": 0, "elapsed_s": 0.0}

    typh_text = read_typhoon_text(doc_id)
    if not typh_text:
        return {"status": "failed_no_typhoon", "chars": 0, "pages": 0, "elapsed_s": 0.0}

    t0 = time.time()
    with tempfile.TemporaryDirectory(prefix=f"prthyb-{doc_id}-") as td:
        out_dir = Path(td)
        pages = render_pdf_pages(pdf_path, MAX_PAGES_PER_DOC, out_dir)
        if not pages:
            return {"status": "failed_render", "chars": 0, "pages": 0,
                    "elapsed_s": round(time.time() - t0, 2)}
        r = call_with_retry(pages, typh_text)
        text = (r.get("stdout") or "").strip()

    if r.get("returncode") != 0 or len(text) < MIN_OUTPUT_CHARS:
        return {
            "status": "failed_too_short" if r.get("returncode") == 0 else "failed_call",
            "chars": len(text),
            "pages": len(pages),
            "typhoon_chars": len(typh_text),
            "elapsed_s": round(time.time() - t0, 2),
            "returncode": r.get("returncode"),
            "stderr": r.get("stderr", "")[:200],
            "stdout": text[:400],
        }

    out_path = PRT_PAPERS_TEXT / shard_for(doc_id) / f"{doc_id}.txt"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    return {
        "status": "ok",
        "chars": len(text),
        "pages": len(pages),
        "typhoon_chars": len(typh_text),
        "elapsed_s": round(time.time() - t0, 2),
    }


# ----------------------------------------------------------------------
# Coordinator
# ----------------------------------------------------------------------

def acquire_lock() -> Optional[Path]:
    if LOCK_FILE.exists():
        try:
            age = time.time() - LOCK_FILE.stat().st_mtime
            if age < 86400:
                log(f"another hybrid run looks active (lock age {age:.0f}s) — exiting")
                return None
            log(f"stale lock (age {age:.0f}s) — overwriting")
        except Exception:
            pass
    LOCK_FILE.write_text(now_iso(), encoding="utf-8")
    return LOCK_FILE


def release_lock() -> None:
    try:
        LOCK_FILE.unlink()
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--max", type=int, default=0)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--loop-sleep", type=int, default=900)
    args = ap.parse_args()

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"ocr_opus_typhoon_hybrid_{time.strftime('%Y%m%dT%H%M%S')}.log"
    global LOG_FP
    LOG_FP = log_path.open("w", encoding="utf-8")

    log("=== PRT OCR via Typhoon baseline + Claude Opus correction (hybrid) ===")
    log(f"  vault.papers           : {PRT_VAULT_PAPERS}")
    log(f"  typhoon baseline       : {PRT_PAPERS_TEXT_TYPHOON}")
    log(f"  vault.out (hybrid)     : {PRT_PAPERS_TEXT}")
    log(f"  skill                  : {SKILL_FILE}")
    log(f"  pdf tracker            : {PRT_TRACKER}")
    log(f"  state                  : {STATE_FILE}")
    log(f"  log                    : {log_path}")
    log(f"  parallel workers       : {args.parallel}")
    log(f"  max pages per doc      : {MAX_PAGES_PER_DOC}")
    log(f"  max typhoon text chars : {MAX_TYPHOON_TEXT_CHARS:,}")
    log(f"  CLI                    : {resolve_claude_exe() or '(claude not found in PATH)'}")
    log(f"  model                  : {CLAUDE_MODEL}")

    if not resolve_claude_exe():
        log("FATAL: claude CLI not on PATH; cannot run.")
        sys.exit(1)

    try:
        _ = load_skill_body()
        log(f"  skill body             : {len(_SKILL_BODY):,} chars loaded")
    except SystemExit:
        raise
    except Exception as e:
        log(f"FATAL: failed to load skill: {e}")
        sys.exit(1)

    if not acquire_lock():
        sys.exit(0)

    try:
        pass_num = 0
        while True:
            pass_num += 1
            log(f"\n--- pass {pass_num} ---")
            state = load_state()
            log("Loading pdf-path map from tracker...")
            pdf_map = load_pdf_path_map()
            log(f"  {len(pdf_map):,} downloaded PDFs in tracker")

            log("Scanning vault for image-only docs with Typhoon baseline...")
            needing = find_docs_needing_hybrid(state)
            log(f"  {len(needing):,} docs queued this pass")

            if args.max:
                needing = needing[: args.max]
                log(f"  capped at {args.max}")

            if not needing:
                if args.loop:
                    log(f"nothing to do; sleeping {args.loop_sleep}s and rescanning...")
                    if STOP_FILE.exists():
                        log("stop flag set; exiting"); break
                    time.sleep(args.loop_sleep)
                    continue
                log("nothing to do; exiting")
                break

            t_start = time.time()
            ok = failed = no_pdf = 0
            done = 0
            total = len(needing)

            def submit(executor, doc_id):
                pdf = pdf_map.get(doc_id)
                if pdf is None:
                    update_doc_state(state, doc_id, status="failed_no_pdf",
                                     chars=0, pages=0, elapsed_s=0.0)
                    return None
                return executor.submit(hybrid_one_doc, doc_id, pdf)

            with concurrent.futures.ThreadPoolExecutor(max_workers=args.parallel) as ex:
                futures: dict[concurrent.futures.Future, str] = {}
                it = iter(needing)
                for _ in range(min(2 * args.parallel, total)):
                    try:
                        did = next(it)
                    except StopIteration:
                        break
                    f = submit(ex, did)
                    if f is None:
                        no_pdf += 1; done += 1; continue
                    futures[f] = did

                while futures:
                    if STOP_FILE.exists():
                        log("stop flag detected; cancelling remaining tasks ...")
                        for f in list(futures.keys()):
                            f.cancel()
                        break
                    done_set, _ = concurrent.futures.wait(
                        futures.keys(), timeout=5,
                        return_when=concurrent.futures.FIRST_COMPLETED,
                    )
                    for f in done_set:
                        did = futures.pop(f)
                        try:
                            res = f.result()
                        except Exception as e:
                            res = {"status": "failed_call", "chars": 0, "pages": 0,
                                   "elapsed_s": 0.0, "stderr": str(e)[:200]}
                        update_doc_state(state, did, **res)
                        done += 1
                        st = res.get("status")
                        if st == "ok": ok += 1
                        elif st == "failed_no_pdf": no_pdf += 1
                        else: failed += 1
                        if done % 5 == 0 or done <= 5:
                            elapsed = time.time() - t_start
                            rate = ok / elapsed if elapsed > 0 else 0
                            log(
                                f"  progress: {done:,}/{total:,}  ok={ok:,} failed={failed:,} "
                                f"no_pdf={no_pdf:,}  ({rate:.3f} ok/s)"
                            )
                            save_state(state)
                        try:
                            nxt = next(it)
                        except StopIteration:
                            continue
                        nf = submit(ex, nxt)
                        if nf is None:
                            no_pdf += 1; done += 1; continue
                        futures[nf] = nxt

            save_state(state)
            elapsed = time.time() - t_start
            log(
                f"pass {pass_num} done — ok={ok:,} failed={failed:,} no_pdf={no_pdf:,} "
                f"in {elapsed/60:.1f} min ({(ok/elapsed if elapsed>0 else 0):.3f} ok/s)"
            )

            if not args.loop:
                break
            if STOP_FILE.exists():
                log("stop flag set; exiting")
                break
            log(f"sleeping {args.loop_sleep}s before next pass ...")
            time.sleep(args.loop_sleep)
    finally:
        save_state(load_state())
        if LOG_FP:
            LOG_FP.close()
        release_lock()


if __name__ == "__main__":
    main()
