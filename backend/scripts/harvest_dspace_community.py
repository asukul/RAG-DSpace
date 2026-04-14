"""
harvest_dspace_community.py
---------------------------
Harvest items from the ISU DSpace "University Scholarship" community.

Stage A (default): metadata-only pass. One HTTP GET per page of 100, extracts
flat records into per-collection JSONL files. Resumable via per-collection
state files.

Stage B (future): bitstream downloads for items that have `dc.source.bitstream`.
Stub CLI option is provided but intentionally not implemented in this script
to keep Stage A runs fast and isolated.

Usage:
    # Full Stage A harvest, smallest collection first:
    python harvest_dspace_community.py

    # Single collection by UUID or by name substring:
    python harvest_dspace_community.py --only 91477f5a-e02a-44ba-9f76-5587ec907f19
    python harvest_dspace_community.py --only Journals

    # Force a re-harvest from page 0 (ignore existing state):
    python harvest_dspace_community.py --only Journals --restart

    # Dry run: hit page 0 only and print the first record per collection:
    python harvest_dspace_community.py --dry-run

Outputs (per collection_uuid):
    backend/data/dspace/dspace_items_<uuid>.jsonl
    backend/data/dspace/dspace_state_<uuid>.json

State file shape:
    {
        "collection_uuid": "...",
        "collection_name": "...",
        "total": 27,
        "written": 27,
        "next_page": 14,
        "total_pages": 14,
        "started_at": "2026-04-08T22:30:00+00:00",
        "finished_at": "2026-04-08T22:30:06+00:00",
        "last_error": null,
        "page_errors": []
    }
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = "https://dr.lib.iastate.edu/server/api/discover/search/objects"
ITEM_URL_TEMPLATE = "https://dr.lib.iastate.edu/items/{uuid}"
PAGE_SIZE = 100
SLEEP_BETWEEN_PAGES = 0.20  # politeness: 200ms (override with --sleep)
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_BASE = 2.0  # exponential backoff base for retries

# Adaptive sleep (AIMD-style congestion control) — see --adaptive flag.
ADAPTIVE_ENABLED = False
ADAPTIVE_MIN_SLEEP = 0.05    # never go below 50ms
ADAPTIVE_MAX_SLEEP = 8.0     # cap politeness backoff at 8s
ADAPTIVE_DECREMENT = 0.05    # additive decrease per successful page
ADAPTIVE_BACKOFF_MULT = 2.0  # multiplicative increase on timeout/5xx
ADAPTIVE_RECOVERY_FLOOR = 0.10  # snap-down floor right after a backoff
ADAPTIVE_STARTING_SLEEP = 0.50  # start value when --adaptive is on


class AdaptiveController:
    """
    Tracks the current sleep value and adjusts it after each fetch.

    Strategy:
      - On every successful page: subtract ADAPTIVE_DECREMENT (additive
        decrease) but never below ADAPTIVE_MIN_SLEEP. This probes for
        higher throughput.
      - On any timeout / 5xx / connection error: multiply by
        ADAPTIVE_BACKOFF_MULT (multiplicative increase) and clamp to
        ADAPTIVE_MAX_SLEEP. Also remember the value at the moment of
        failure as a "danger zone" floor for future probes.

    This is the standard TCP-style AIMD pattern: slow probe up, fast
    fall down on congestion. It converges to roughly the highest steady
    rate the server tolerates without errors.
    """

    def __init__(self, start: float = ADAPTIVE_STARTING_SLEEP) -> None:
        self.current = max(ADAPTIVE_MIN_SLEEP, start)
        self.danger_floor = 0.0
        self.successes_since_backoff = 0
        self.total_successes = 0
        self.total_backoffs = 0

    def on_success(self) -> None:
        self.total_successes += 1
        self.successes_since_backoff += 1
        new_val = self.current - ADAPTIVE_DECREMENT
        self.current = max(new_val, ADAPTIVE_MIN_SLEEP, self.danger_floor)

    def on_timeout(self) -> None:
        self.total_backoffs += 1
        self.successes_since_backoff = 0
        # Remember where we got hurt and back off from there
        self.danger_floor = max(self.danger_floor, self.current)
        new_sleep = self.current * ADAPTIVE_BACKOFF_MULT
        self.current = min(new_sleep, ADAPTIVE_MAX_SLEEP)
        # Forget the old danger floor a little so we can probe again later
        self.danger_floor *= 0.9

    def status(self) -> str:
        return (
            f"adaptive sleep={self.current:.2f}s "
            f"(succ={self.total_successes} bo={self.total_backoffs} "
            f"floor={self.danger_floor:.2f})"
        )

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Ordered smallest -> largest, so pipeline issues surface on cheap collections.
# Originally just the 7 collections of "University Scholarship" (496ab7dd-...).
# Extended to include the other two top-level communities of ISU DSpace:
#   - Student Research (7119442c-...)
#   - Departments and Author Profiles (66a66903-...)
WORKLIST: list[tuple[str, str, int, bool]] = [
    # University Scholarship community
    ("91477f5a-e02a-44ba-9f76-5587ec907f19", "Journals", 27, False),
    ("0f0575e3-4dc0-48d3-a64f-6e5039fbaf72", "Series", 101, False),
    ("1c872b85-28f2-483c-8874-ac365af04218", "Multimedia", 196, True),
    ("0b90040b-44bb-486b-a5e3-7f477216ae37", "Journal Volumes", 624, False),
    ("1aa6c3ff-85e6-44a3-aad6-fc97a500cac5", "Journal Issues", 3525, False),
    ("ca9cf202-5b5b-4d43-b0d9-86df40a2d9dd", "Conference Proceedings and Presentations", 14289, True),
    ("76c07a07-0ef0-419f-a96a-1cadbca8fcb2", "Publications", 63894, True),
    # Departments and Author Profiles community
    ("90ee9f70-f4eb-4b4d-87c7-97cc3dccff56", "Academic and Administrative Units", 195, False),
    ("51e51f6d-6bca-492f-91ff-22c9e0936a8b", "Academic and Administrative Profiles", 1290, False),
    # Student Research community
    ("71537944-3990-4d99-9351-64b7a4f83125", "Creative Components", 2087, True),
    ("0830d32e-14e1-4a4f-bb8f-271a75ed35af", "Theses and Dissertations", 34532, True),
]

# Output layout
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_DIR = BACKEND_DIR / "data" / "dspace"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def items_path(collection_uuid: str) -> Path:
    return DATA_DIR / f"dspace_items_{collection_uuid}.jsonl"


def state_path(collection_uuid: str) -> Path:
    return DATA_DIR / f"dspace_state_{collection_uuid}.json"


def load_state(collection_uuid: str) -> dict[str, Any] | None:
    p = state_path(collection_uuid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        log(f"WARN: could not parse state file {p.name}: {e}")
        return None


def save_state(state: dict[str, Any]) -> None:
    """Atomically write the state file.

    On Windows, `Path.replace()` can transiently fail with PermissionError
    (WinError 5) when another process (e.g. Dropbox, antivirus, file watcher)
    has a brief lock on the target. We retry a few times. If the atomic
    rename is still blocked, fall back to a direct write of the target file
    (non-atomic, but the in-memory state is authoritative anyway on the next
    save).
    """
    p = state_path(state["collection_uuid"])
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    tmp = p.with_suffix(".json.tmp")
    last_err: Exception | None = None
    for attempt in range(6):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(p)
            return
        except PermissionError as e:  # pragma: no cover - Windows/Dropbox flakiness
            last_err = e
            time.sleep(0.25 + 0.5 * attempt)
        except Exception as e:  # pragma: no cover - defensive
            last_err = e
            time.sleep(0.25 + 0.5 * attempt)
    # Fallback: direct write, non-atomic but better than losing state updates.
    try:
        p.write_text(payload, encoding="utf-8")
        log(f"  WARN: state save used non-atomic fallback (last error: {last_err})")
    except Exception as e:
        log(f"  ERROR: state save failed entirely: {e}")


def count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for _ in f:
            n += 1
    return n


# ---------------------------------------------------------------------------
# HTTP with retry
# ---------------------------------------------------------------------------


def fetch_page(
    session: requests.Session,
    collection_uuid: str,
    page: int,
    controller: AdaptiveController | None = None,
) -> dict[str, Any] | None:
    """Fetch one page of search results. Returns parsed JSON, or None on unrecoverable 404.

    If `controller` is provided, on transient failures (timeout / 5xx /
    connection error) it gets `on_timeout()` so the adaptive backoff
    grows. Successful return calls `on_success()`.
    """
    params = {
        "scope": collection_uuid,
        "dsoType": "item",
        "size": PAGE_SIZE,
        "page": page,
    }
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(BASE_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                log(f"  page {page}: HTTP 404, skipping page")
                if controller is not None:
                    controller.on_success()  # not really our fault, no backoff
                return None
            if r.status_code == 429:
                # Explicit rate-limit: definitely back off
                if controller is not None:
                    controller.on_timeout()
                raise requests.HTTPError(f"HTTP 429 (rate limited) from DSpace")
            if 500 <= r.status_code < 600:
                if controller is not None:
                    controller.on_timeout()
                raise requests.HTTPError(f"HTTP {r.status_code} from DSpace")
            r.raise_for_status()
            if controller is not None:
                controller.on_success()
            return r.json()
        except (requests.ConnectionError, requests.Timeout, requests.HTTPError, ValueError) as e:
            last_err = e
            # Connection / timeout errors should also trigger adaptive backoff
            if controller is not None and isinstance(e, (requests.ConnectionError, requests.Timeout)):
                controller.on_timeout()
            if attempt == MAX_RETRIES:
                break
            sleep_for = BACKOFF_BASE ** attempt  # 2s, 4s
            log(f"  page {page} attempt {attempt}/{MAX_RETRIES} failed: {e}; backoff {sleep_for:.1f}s")
            time.sleep(sleep_for)
    log(f"  page {page}: GAVE UP after {MAX_RETRIES} attempts: {last_err}")
    raise RuntimeError(f"Unrecoverable fetch failure on page {page}: {last_err}")


# ---------------------------------------------------------------------------
# Record flattening
# ---------------------------------------------------------------------------


def _md_values(metadata: dict[str, Any], key: str) -> list[str]:
    """Extract all `value` strings for a given DSpace metadata key."""
    entries = metadata.get(key) or []
    out: list[str] = []
    for e in entries:
        if isinstance(e, dict):
            v = e.get("value")
            if v is not None:
                out.append(str(v))
    return out


def _md_first(metadata: dict[str, Any], key: str, default: str = "") -> str:
    vals = _md_values(metadata, key)
    return vals[0] if vals else default


def _year_from_issued(issued: str) -> str:
    if not issued:
        return ""
    # Common shapes: "2023-05-01", "2023-05", "2023", "2023-05-01T00:00:00Z"
    s = issued.strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""


def _bitstream_path(metadata: dict[str, Any]) -> tuple[bool, str]:
    """Return (present, path). `dc.source.bitstream` format is e.g.
    'archive/.../Foo.pdf|||Sat Jan 15 00:43:08 UTC 2022'.
    """
    vals = _md_values(metadata, "dc.source.bitstream")
    if not vals:
        return (False, "")
    raw = vals[0]
    # Take the path before the first "|||" separator, if any.
    path = raw.split("|||", 1)[0].strip()
    return (bool(path), path)


def flatten_item(
    indexable: dict[str, Any],
    collection_uuid: str,
    collection_name: str,
) -> dict[str, Any]:
    md = indexable.get("metadata") or {}

    title = _md_first(md, "dc.title") or indexable.get("name", "") or ""
    authors = _md_values(md, "dc.contributor.author")
    # Fall back to dc.contributor.other for container entities (journals, series)
    if not authors:
        authors = _md_values(md, "dc.contributor.other")

    department = _md_first(md, "dc.contributor.department")
    issued = _md_first(md, "dc.date.issued")
    # Some items only have dc.date (legacy), not dc.date.issued
    if not issued:
        issued = _md_first(md, "dc.date")
    year = _year_from_issued(issued)

    abstract = _md_first(md, "dc.description.abstract")
    type_ = _md_first(md, "dc.type")
    subject = _md_values(md, "dc.subject.disciplines")
    # Also merge generic dc.subject if present
    subject_other = _md_values(md, "dc.subject")
    if subject_other:
        # Keep order, de-dupe
        seen = set(subject)
        for s in subject_other:
            if s not in seen:
                subject.append(s)
                seen.add(s)

    uuid = indexable.get("uuid") or indexable.get("id") or ""
    handle = indexable.get("handle", "")

    bit_present, bit_path = _bitstream_path(md)

    return {
        "uuid": uuid,
        "handle": handle,
        "collection_uuid": collection_uuid,
        "collection_name": collection_name,
        "title": title,
        "authors": authors,
        "department": department,
        "year": year,
        "issued": issued,
        "abstract": abstract,
        "type": type_,
        "subject": subject,
        "dspace_url": ITEM_URL_TEMPLATE.format(uuid=uuid),
        "bitstream_present": bit_present,
        "bitstream_path": bit_path,
        "entity_type": _md_first(md, "dspace.entity.type"),
    }


def iter_indexable(page_json: dict[str, Any]) -> Iterable[dict[str, Any]]:
    try:
        objs = page_json["_embedded"]["searchResult"]["_embedded"]["objects"]
    except (KeyError, TypeError):
        return []
    for wrap in objs or []:
        emb = wrap.get("_embedded") or {}
        io = emb.get("indexableObject")
        if io:
            yield io


def page_meta(page_json: dict[str, Any]) -> tuple[int, int]:
    page_info = page_json["_embedded"]["searchResult"]["page"]
    return int(page_info.get("totalElements", 0)), int(page_info.get("totalPages", 0))


# ---------------------------------------------------------------------------
# Per-collection harvest
# ---------------------------------------------------------------------------


@dataclass
class CollectionResult:
    collection_uuid: str
    collection_name: str
    total: int
    written: int
    elapsed_sec: float
    pages_fetched: int
    page_errors: list[int]
    error: str | None = None


def harvest_collection(
    session: requests.Session,
    collection_uuid: str,
    collection_name: str,
    expected_total: int,
    *,
    restart: bool,
    dry_run: bool,
    controller: AdaptiveController | None = None,
) -> CollectionResult:
    ensure_data_dir()
    items_file = items_path(collection_uuid)
    existing_state = None if restart else load_state(collection_uuid)

    # Reconcile state with on-disk JSONL line count. If the state file says we
    # wrote N items but the JSONL has fewer, trust the JSONL and rewind.
    on_disk_lines = count_jsonl_lines(items_file)
    if restart and items_file.exists():
        log(f"  --restart: removing existing {items_file.name}")
        items_file.unlink()
        on_disk_lines = 0

    if existing_state and existing_state.get("finished_at"):
        log(
            f"  already finished per state file: "
            f"{existing_state.get('written')}/{existing_state.get('total')} items"
        )
        return CollectionResult(
            collection_uuid=collection_uuid,
            collection_name=collection_name,
            total=int(existing_state.get("total", expected_total)),
            written=int(existing_state.get("written", on_disk_lines)),
            elapsed_sec=0.0,
            pages_fetched=0,
            page_errors=list(existing_state.get("page_errors", [])),
        )

    next_page = 0
    if existing_state and not restart:
        state_written = int(existing_state.get("written", 0))
        next_page = int(existing_state.get("next_page", 0))
        # Reconcile drift: if the JSONL file has more lines than the state
        # file claims, a previous run flushed items to disk but the
        # subsequent atomic state-save was interrupted (e.g. Windows
        # PermissionError on .replace). Advance the cursor so we don't
        # re-fetch those pages and introduce duplicates.
        if on_disk_lines > state_written:
            extra = on_disk_lines - state_written
            pages_to_skip = extra // PAGE_SIZE
            leftover = extra % PAGE_SIZE
            log(
                f"  disk/state drift: state.written={state_written} disk={on_disk_lines}; "
                f"advancing next_page by {pages_to_skip} (+{leftover} leftover)"
            )
            next_page += pages_to_skip
            # If leftover != 0, the JSONL ends mid-page. Truncation here is
            # risky on append-only files; the cleanest recovery is to just
            # accept the leftover as "already written" and keep going. We
            # note it in state so it surfaces in the report.
            existing_state["written"] = on_disk_lines
            existing_state["next_page"] = next_page
            if leftover:
                existing_state["drift_leftover"] = leftover
        log(
            f"  resuming at page {next_page} "
            f"(state.written={existing_state.get('written', 0)}, disk={on_disk_lines})"
        )

    started_at_iso = (
        existing_state.get("started_at")
        if existing_state and existing_state.get("started_at")
        else now_iso()
    )

    state: dict[str, Any] = {
        "collection_uuid": collection_uuid,
        "collection_name": collection_name,
        "total": expected_total,
        "written": on_disk_lines,
        "next_page": next_page,
        "total_pages": (existing_state or {}).get("total_pages"),
        "started_at": started_at_iso,
        "finished_at": None,
        "last_error": None,
        "page_errors": list((existing_state or {}).get("page_errors", [])),
    }
    save_state(state)

    t0 = time.monotonic()
    pages_fetched = 0
    total_pages: int | None = state.get("total_pages")

    # Open append-mode file for streaming writes.
    with items_file.open("a", encoding="utf-8") as fout:
        while True:
            if total_pages is not None and next_page >= total_pages:
                break

            try:
                page_json = fetch_page(session, collection_uuid, next_page, controller=controller)
            except RuntimeError as e:
                state["last_error"] = str(e)
                save_state(state)
                log(f"  aborting collection {collection_name} due to unrecoverable error: {e}")
                break

            if page_json is None:
                # 404 on this page. Log and skip, but keep going -- this is rare.
                state["page_errors"].append(next_page)
                next_page += 1
                state["next_page"] = next_page
                save_state(state)
                if controller is not None:
                    time.sleep(controller.current)
                else:
                    time.sleep(SLEEP_BETWEEN_PAGES)
                continue

            total_elements, total_pages_from_api = page_meta(page_json)
            if total_pages is None:
                total_pages = total_pages_from_api
                state["total_pages"] = total_pages
                state["total"] = total_elements
                log(f"  total items reported by API: {total_elements} ({total_pages} pages)")

            batch = list(iter_indexable(page_json))
            if not batch:
                # Empty page: likely past end. Advance and stop.
                log(f"  page {next_page}: empty; stopping")
                next_page += 1
                state["next_page"] = next_page
                save_state(state)
                break

            for io in batch:
                rec = flatten_item(io, collection_uuid, collection_name)
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                state["written"] += 1

            fout.flush()
            pages_fetched += 1
            next_page += 1
            state["next_page"] = next_page
            save_state(state)

            if pages_fetched == 1 or pages_fetched % 10 == 0 or next_page >= (total_pages or 0):
                tail = f" | {controller.status()}" if controller is not None else ""
                log(
                    f"  page {next_page - 1}/{total_pages}: "
                    f"wrote {len(batch)} items (cum {state['written']}/{total_elements})"
                    f"{tail}"
                )

            if dry_run:
                log("  dry-run: stopping after first page")
                break

            # Adaptive controller wins if present, otherwise the static value.
            if controller is not None:
                time.sleep(controller.current)
            else:
                time.sleep(SLEEP_BETWEEN_PAGES)

    elapsed = time.monotonic() - t0

    if total_pages is not None and next_page >= total_pages and not dry_run:
        state["finished_at"] = now_iso()
    save_state(state)

    log(
        f"  DONE {collection_name}: wrote {state['written']} items in {elapsed:.1f}s "
        f"({state['written'] / elapsed:.1f}/s)" if elapsed > 0 else f"  DONE {collection_name}"
    )

    return CollectionResult(
        collection_uuid=collection_uuid,
        collection_name=collection_name,
        total=int(state.get("total", expected_total)),
        written=int(state.get("written", 0)),
        elapsed_sec=elapsed,
        pages_fetched=pages_fetched,
        page_errors=list(state.get("page_errors", [])),
        error=state.get("last_error"),
    )


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------


def write_report(results: list[CollectionResult], report_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)

    total_written = sum(r.written for r in results)
    total_expected = sum(r.total for r in results)
    total_elapsed = sum(r.elapsed_sec for r in results)

    lines: list[str] = []
    lines.append("# DSpace Community Harvest Report")
    lines.append("")
    lines.append(f"- Generated: {now_iso()}")
    lines.append(f"- Root community: `University Scholarship` (496ab7dd-9f4b-45c9-9776-5da586722ec7)")
    lines.append(f"- Stage: **A (metadata only)**")
    lines.append(
        f"- Totals: **{total_written:,} items written** / {total_expected:,} expected "
        f"({total_written / total_expected * 100:.1f}%)"
        if total_expected
        else f"- Totals: {total_written:,} items written"
    )
    lines.append(f"- Total elapsed (this run, across collections): {total_elapsed / 60:.1f} min")
    lines.append("")
    lines.append("## Per-collection results")
    lines.append("")
    lines.append("| # | Collection | UUID | Expected | Written | % | Elapsed | Pages fetched (this run) | Errors |")
    lines.append("|---|---|---|---:|---:|---:|---:|---:|---|")
    for i, r in enumerate(results, 1):
        pct = f"{r.written / r.total * 100:.1f}%" if r.total else "n/a"
        elapsed = f"{r.elapsed_sec:.1f}s" if r.elapsed_sec < 120 else f"{r.elapsed_sec / 60:.1f}m"
        err_note = ""
        if r.error:
            err_note = f"ABORT: {r.error[:120]}"
        elif r.page_errors:
            err_note = f"skipped pages: {r.page_errors[:10]}{'...' if len(r.page_errors) > 10 else ''}"
        else:
            err_note = "none"
        lines.append(
            f"| {i} | {r.collection_name} | `{r.collection_uuid}` | "
            f"{r.total:,} | {r.written:,} | {pct} | {elapsed} | "
            f"{r.pages_fetched} | {err_note} |"
        )
    lines.append("")
    lines.append("## Notes")
    lines.append("")
    lines.append("- Stage A only: no bitstreams downloaded. `bitstream_present` and `bitstream_path` are captured in each JSONL record for Stage B.")
    lines.append("- Container collections (Journals, Journal Volumes, Journal Issues, Series) are relation wrappers and have no abstracts/authors; they are harvested for link graph purposes only.")
    lines.append("- RAG-embeddable subset = Multimedia + Conference Proceedings + Publications = 78,379 items.")
    lines.append("")
    lines.append("## Output files")
    lines.append("")
    for r in results:
        lines.append(
            f"- `backend/data/dspace/dspace_items_{r.collection_uuid}.jsonl` — {r.written:,} items"
        )
        lines.append(
            f"- `backend/data/dspace/dspace_state_{r.collection_uuid}.json` — state"
        )

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log(f"wrote report: {report_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def select_worklist(only: str | None) -> list[tuple[str, str, int, bool]]:
    if not only:
        return WORKLIST
    needle = only.strip().lower()
    matches = [
        row for row in WORKLIST
        if needle == row[0].lower() or needle in row[1].lower()
    ]
    if not matches:
        raise SystemExit(f"--only {only!r} matched nothing; valid choices: {[r[1] for r in WORKLIST]}")
    return matches


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Harvest ISU DSpace 'University Scholarship' community (Stage A: metadata).")
    parser.add_argument("--only", help="UUID or name substring to harvest only that collection")
    parser.add_argument("--restart", action="store_true", help="Ignore existing state and re-harvest from page 0 (deletes existing JSONL).")
    parser.add_argument("--dry-run", action="store_true", help="Fetch only the first page of each target collection.")
    parser.add_argument(
        "--report",
        default=str(BACKEND_DIR.parent / "tests" / "results" / "DSPACE_HARVEST_REPORT.md"),
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--stage",
        choices=("A", "B"),
        default="A",
        help="A = metadata (default). B = bitstream downloads (not implemented in this script).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="Override SLEEP_BETWEEN_PAGES (default 0.20s). E.g. --sleep 1.5 for very polite re-harvest.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Override output dir (default backend/data/dspace). Useful for parallel re-harvests.",
    )
    parser.add_argument(
        "--adaptive",
        action="store_true",
        help="Adaptive AIMD sleep: probe faster on success, back off on timeout/5xx. Overrides --sleep.",
    )
    parser.add_argument(
        "--adaptive-start",
        type=float,
        default=ADAPTIVE_STARTING_SLEEP,
        help=f"Starting sleep when --adaptive is on (default {ADAPTIVE_STARTING_SLEEP}s)",
    )
    args = parser.parse_args(argv)

    # Apply --sleep override
    if args.sleep is not None and args.sleep > 0:
        global SLEEP_BETWEEN_PAGES
        SLEEP_BETWEEN_PAGES = args.sleep
        log(f"SLEEP_BETWEEN_PAGES overridden to {SLEEP_BETWEEN_PAGES}s")

    # Apply --data-dir override
    if args.data_dir:
        global DATA_DIR
        DATA_DIR = Path(args.data_dir).resolve()
        log(f"DATA_DIR overridden to {DATA_DIR}")

    # Build the adaptive controller (or None for fixed-sleep mode)
    controller: AdaptiveController | None = None
    if args.adaptive:
        controller = AdaptiveController(start=args.adaptive_start)
        log(
            f"adaptive mode ON: start={controller.current}s "
            f"min={ADAPTIVE_MIN_SLEEP}s max={ADAPTIVE_MAX_SLEEP}s "
            f"decrement={ADAPTIVE_DECREMENT}s backoff_mult={ADAPTIVE_BACKOFF_MULT}"
        )

    if args.stage == "B":
        log("Stage B (bitstream downloads) is not implemented in this script. Exiting.")
        return 2

    worklist = select_worklist(args.only)
    ensure_data_dir()

    log(f"harvest starting; {len(worklist)} collection(s); data dir: {DATA_DIR}")
    log(f"restart={args.restart} dry_run={args.dry_run}")

    results: list[CollectionResult] = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for (uuid, name, expected, _embed) in worklist:
        log(f"=== {name} ({expected:,} expected) — {uuid} ===")
        try:
            res = harvest_collection(
                session=session,
                collection_uuid=uuid,
                collection_name=name,
                expected_total=expected,
                restart=args.restart,
                dry_run=args.dry_run,
                controller=controller,
            )
        except KeyboardInterrupt:
            log("KeyboardInterrupt: stopping. Partial data is safe on disk.")
            results.append(CollectionResult(
                collection_uuid=uuid,
                collection_name=name,
                total=expected,
                written=count_jsonl_lines(items_path(uuid)),
                elapsed_sec=0.0,
                pages_fetched=0,
                page_errors=[],
                error="KeyboardInterrupt",
            ))
            break
        except Exception as e:
            log(f"ERROR on {name}: {e}")
            results.append(CollectionResult(
                collection_uuid=uuid,
                collection_name=name,
                total=expected,
                written=count_jsonl_lines(items_path(uuid)),
                elapsed_sec=0.0,
                pages_fetched=0,
                page_errors=[],
                error=str(e),
            ))
            continue
        results.append(res)

    # Always write a report, even on partial runs.
    report_path = Path(args.report)
    write_report(results, report_path)

    total_written = sum(r.written for r in results)
    log(f"harvest finished; {total_written:,} total items written across {len(results)} collections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
