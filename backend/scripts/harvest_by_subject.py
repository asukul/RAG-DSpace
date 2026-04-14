"""
harvest_by_subject.py
---------------------
Harvest items from ISU DSpace by subject query (e.g. "Computer Science",
"Machine Learning"). Produces a single deduplicated JSONL file containing
items from all queried subjects.

Usage:
    # Harvest all priority subjects:
    python harvest_by_subject.py

    # Harvest only a specific subject:
    python harvest_by_subject.py --only "Machine Learning"

    # Restart a specific subject from scratch:
    python harvest_by_subject.py --only "Deep Learning" --restart

    # Dry run (one page per subject):
    python harvest_by_subject.py --dry-run

Outputs:
    backend/data/dspace/dspace_subject_harvest.jsonl  -- one JSON record per line, deduplicated by UUID
    backend/data/dspace/dspace_subject_state.json     -- tracks progress per subject
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
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
SLEEP_BETWEEN_PAGES = 0.20  # 200ms politeness
REQUEST_TIMEOUT = 60
MAX_RETRIES = 3
BACKOFF_BASE = 2.0

HEADERS = {
    "User-Agent": (
        "ISU-RAG-Harvester/1.0 (Research search project; "
        "contact: isu-rag-search@iastate.edu)"
    ),
    "Accept": "application/json",
}

# Priority subjects, in order
SUBJECTS: list[tuple[str, int]] = [
    ("Computer Science", 5061),
    ("Machine Learning", 3535),
    ("Artificial Intelligence", 2355),
    ("Deep Learning", 1471),
    ("Software Engineering", 1151),
    ("Data Science", 684),
    ("Natural Language Processing", 504),
    ("Cybersecurity", 316),
    ("Robotics", 2850),
    ("Neural Network", 3029),
    # --- Wave 2 subjects ---
    ("Algorithm", 15259),
    ("Database", 12971),
    ("Compiler", 10198),
    ("Bioinformatics", 3126),
    ("Distributed Systems", 1319),
    ("Operating Systems", 1801),
    ("Programming Language", 1680),
    ("Computer Vision", 1156),
    ("Human Computer Interaction", 1178),
    ("Big Data", 1118),
    ("Parallel Computing", 706),
    ("Internet of Things", 400),
    ("Information Security", 369),
    ("Cloud Computing", 348),
    ("Blockchain", 140),
]

# Output layout
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_DIR = BACKEND_DIR / "data" / "dspace"

HARVEST_FILE = DATA_DIR / "dspace_subject_harvest.jsonl"
STATE_FILE = DATA_DIR / "dspace_subject_state.json"


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------

def load_state() -> dict[str, Any]:
    """Load the global state file tracking all subjects."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"WARN: could not parse state file: {e}")
    return {
        "seen_uuids": [],
        "subjects": {},
        "total_unique": 0,
        "started_at": None,
    }


def save_state(state: dict[str, Any]) -> None:
    """Save state with atomic rename (with Windows fallback)."""
    payload = json.dumps(state, indent=2, ensure_ascii=False)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    for attempt in range(6):
        try:
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(STATE_FILE)
            return
        except PermissionError:
            time.sleep(0.25 + 0.5 * attempt)
        except Exception:
            time.sleep(0.25 + 0.5 * attempt)
    # Fallback: direct write
    try:
        STATE_FILE.write_text(payload, encoding="utf-8")
    except Exception as e:
        log(f"  ERROR: state save failed: {e}")


def load_seen_uuids() -> set[str]:
    """Load the set of already-harvested UUIDs from the JSONL file."""
    seen = set()
    if HARVEST_FILE.exists():
        with HARVEST_FILE.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    uid = rec.get("uuid")
                    if uid:
                        seen.add(uid)
                except json.JSONDecodeError:
                    pass
    return seen


# ---------------------------------------------------------------------------
# HTTP with retry
# ---------------------------------------------------------------------------

def fetch_page(
    session: requests.Session,
    subject: str,
    page: int,
) -> dict[str, Any] | None:
    """Fetch one page of subject search results. Returns parsed JSON or None on 404."""
    # Wrap subject in double quotes for exact-phrase matching in DSpace Solr
    quoted_subject = f'"{subject}"'
    params = {
        "query": quoted_subject,
        "dsoType": "ITEM",
        "size": PAGE_SIZE,
        "page": page,
    }
    last_err: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = session.get(
                BASE_URL, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT
            )
            if r.status_code == 404:
                log(f"  page {page}: HTTP 404, skipping")
                return None
            if r.status_code == 429:
                raise requests.HTTPError(f"HTTP 429 (rate limited)")
            if 500 <= r.status_code < 600:
                raise requests.HTTPError(f"HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except (
            requests.ConnectionError,
            requests.Timeout,
            requests.HTTPError,
            ValueError,
        ) as e:
            last_err = e
            if attempt == MAX_RETRIES:
                break
            sleep_for = BACKOFF_BASE ** attempt
            log(
                f"  page {page} attempt {attempt}/{MAX_RETRIES} failed: {e}; "
                f"backoff {sleep_for:.1f}s"
            )
            time.sleep(sleep_for)
    log(f"  page {page}: GAVE UP after {MAX_RETRIES} attempts: {last_err}")
    raise RuntimeError(f"Unrecoverable fetch failure on page {page}: {last_err}")


# ---------------------------------------------------------------------------
# Record extraction
# ---------------------------------------------------------------------------

def _md_values(metadata: dict[str, Any], key: str) -> list[str]:
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
    s = issued.strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return ""


def flatten_item(
    indexable: dict[str, Any],
    query_subject: str,
) -> dict[str, Any]:
    md = indexable.get("metadata") or {}

    title = _md_first(md, "dc.title") or indexable.get("name", "") or ""
    authors = _md_values(md, "dc.contributor.author")
    if not authors:
        authors = _md_values(md, "dc.contributor.other")

    department = _md_first(md, "dc.contributor.department")
    issued = _md_first(md, "dc.date.issued")
    if not issued:
        issued = _md_first(md, "dc.date")
    year = _year_from_issued(issued)

    abstract = _md_first(md, "dc.description.abstract")
    type_ = _md_first(md, "dc.type")

    # Merge dc.subject.disciplines and dc.subject
    subject = _md_values(md, "dc.subject.disciplines")
    subject_other = _md_values(md, "dc.subject")
    if subject_other:
        seen = set(subject)
        for s in subject_other:
            if s not in seen:
                subject.append(s)
                seen.add(s)

    uuid = indexable.get("uuid") or indexable.get("id") or ""
    handle = indexable.get("handle", "")

    # Try to get collection name from owningCollection
    collection_name = ""
    try:
        links = indexable.get("_links", {})
        # Not always present inline; we extract from metadata if available
    except Exception:
        pass
    collection_name = _md_first(md, "dspace.entity.type")

    return {
        "uuid": uuid,
        "handle": handle,
        "title": title,
        "authors": authors,
        "department": department,
        "year": year,
        "issued": issued,
        "abstract": abstract,
        "type": type_,
        "subject": subject,
        "query_subject": query_subject,
        "dspace_url": ITEM_URL_TEMPLATE.format(uuid=uuid),
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
# Per-subject harvest
# ---------------------------------------------------------------------------

def harvest_subject(
    session: requests.Session,
    subject: str,
    expected_count: int,
    seen_uuids: set[str],
    state: dict[str, Any],
    *,
    restart: bool,
    dry_run: bool,
) -> tuple[int, int, int]:
    """
    Harvest all pages for a single subject query.

    Returns (total_from_api, items_written, duplicates_skipped).
    """
    subj_key = subject  # key in state["subjects"]
    subj_state = state["subjects"].get(subj_key, {})

    if not restart and subj_state.get("finished"):
        log(f"  already finished: {subj_state.get('written', 0)} written, "
            f"{subj_state.get('duplicates', 0)} duplicates skipped")
        return (
            subj_state.get("total_from_api", expected_count),
            subj_state.get("written", 0),
            subj_state.get("duplicates", 0),
        )

    next_page = 0 if restart else subj_state.get("next_page", 0)
    written = 0 if restart else subj_state.get("written", 0)
    duplicates = 0 if restart else subj_state.get("duplicates", 0)
    page_errors: list[int] = [] if restart else subj_state.get("page_errors", [])
    total_pages: int | None = None if restart else subj_state.get("total_pages")
    total_from_api: int = expected_count

    if not restart and next_page > 0:
        log(f"  resuming at page {next_page} (written={written}, dupes={duplicates})")

    # Update state
    subj_state = {
        "subject": subject,
        "expected": expected_count,
        "total_from_api": total_from_api,
        "total_pages": total_pages,
        "next_page": next_page,
        "written": written,
        "duplicates": duplicates,
        "page_errors": page_errors,
        "finished": False,
        "started_at": subj_state.get("started_at") if not restart else now_iso(),
        "finished_at": None,
    }
    if not subj_state.get("started_at"):
        subj_state["started_at"] = now_iso()
    state["subjects"][subj_key] = subj_state

    t0 = time.monotonic()
    pages_fetched = 0

    with HARVEST_FILE.open("a", encoding="utf-8") as fout:
        while True:
            if total_pages is not None and next_page >= total_pages:
                break

            try:
                page_json = fetch_page(session, subject, next_page)
            except RuntimeError as e:
                subj_state["last_error"] = str(e)
                state["subjects"][subj_key] = subj_state
                save_state(state)
                log(f"  aborting subject '{subject}': {e}")
                break

            if page_json is None:
                page_errors.append(next_page)
                next_page += 1
                subj_state["next_page"] = next_page
                subj_state["page_errors"] = page_errors
                state["subjects"][subj_key] = subj_state
                save_state(state)
                time.sleep(SLEEP_BETWEEN_PAGES)
                continue

            api_total, api_pages = page_meta(page_json)
            if total_pages is None:
                total_pages = api_pages
                total_from_api = api_total
                subj_state["total_pages"] = total_pages
                subj_state["total_from_api"] = total_from_api
                log(f"  API reports {api_total:,} items across {api_pages} pages")

            batch = list(iter_indexable(page_json))
            if not batch:
                log(f"  page {next_page}: empty; stopping")
                next_page += 1
                break

            page_new = 0
            page_dup = 0
            for io in batch:
                uuid = io.get("uuid") or io.get("id") or ""
                if uuid in seen_uuids:
                    page_dup += 1
                    duplicates += 1
                    continue
                rec = flatten_item(io, subject)
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
                seen_uuids.add(uuid)
                written += 1
                page_new += 1

            fout.flush()
            pages_fetched += 1
            next_page += 1

            subj_state["next_page"] = next_page
            subj_state["written"] = written
            subj_state["duplicates"] = duplicates
            state["subjects"][subj_key] = subj_state

            # Save state every 5 pages to reduce disk I/O
            if pages_fetched % 5 == 0 or next_page >= (total_pages or 0):
                save_state(state)

            if pages_fetched == 1 or pages_fetched % 10 == 0 or next_page >= (total_pages or 0):
                log(
                    f"  page {next_page - 1}/{total_pages}: "
                    f"+{page_new} new, {page_dup} dupes "
                    f"(cum: {written} written, {duplicates} dupes)"
                )

            if dry_run:
                log("  dry-run: stopping after first page")
                break

            time.sleep(SLEEP_BETWEEN_PAGES)

    elapsed = time.monotonic() - t0

    if total_pages is not None and next_page >= total_pages and not dry_run:
        subj_state["finished"] = True
        subj_state["finished_at"] = now_iso()

    subj_state["next_page"] = next_page
    subj_state["written"] = written
    subj_state["duplicates"] = duplicates
    state["subjects"][subj_key] = subj_state
    save_state(state)

    rate = written / elapsed if elapsed > 0 else 0
    log(
        f"  DONE '{subject}': {written} new items written, "
        f"{duplicates} duplicates skipped in {elapsed:.1f}s "
        f"({rate:.1f} items/s)"
    )

    return total_from_api, written, duplicates


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Harvest ISU DSpace items by subject query."
    )
    parser.add_argument(
        "--only", help="Harvest only this subject (exact match from the priority list)"
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Restart the specified subject(s) from page 0.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch only the first page per subject.",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=None,
        help="Override sleep between pages (default 0.20s).",
    )
    args = parser.parse_args(argv)

    if args.sleep is not None and args.sleep > 0:
        global SLEEP_BETWEEN_PAGES
        SLEEP_BETWEEN_PAGES = args.sleep
        log(f"sleep overridden to {SLEEP_BETWEEN_PAGES}s")

    ensure_data_dir()

    # Select subjects
    if args.only:
        needle = args.only.strip()
        matches = [(s, c) for s, c in SUBJECTS if s.lower() == needle.lower()]
        if not matches:
            # Try substring match
            matches = [(s, c) for s, c in SUBJECTS if needle.lower() in s.lower()]
        if not matches:
            print(f"No subject matching '{needle}'. Available: {[s for s, _ in SUBJECTS]}")
            return 1
        subjects = matches
    else:
        subjects = SUBJECTS

    # Load state and seen UUIDs
    state = load_state()
    if state.get("started_at") is None:
        state["started_at"] = now_iso()

    log("Loading seen UUIDs from existing harvest file...")
    seen_uuids = load_seen_uuids()
    log(f"Loaded {len(seen_uuids):,} previously harvested UUIDs")

    log(f"Starting harvest: {len(subjects)} subject(s)")
    log(f"Output: {HARVEST_FILE}")
    log(f"State:  {STATE_FILE}")
    log(f"restart={args.restart} dry_run={args.dry_run}")
    log("")

    session = requests.Session()
    session.headers.update(HEADERS)

    grand_total_written = 0
    grand_total_dupes = 0

    for subject, expected in subjects:
        log(f"=== Subject: '{subject}' (expected ~{expected:,}) ===")
        try:
            api_total, written, dupes = harvest_subject(
                session=session,
                subject=subject,
                expected_count=expected,
                seen_uuids=seen_uuids,
                state=state,
                restart=args.restart,
                dry_run=args.dry_run,
            )
            grand_total_written += written
            grand_total_dupes += dupes
        except KeyboardInterrupt:
            log("KeyboardInterrupt -- partial data is safe on disk.")
            save_state(state)
            break
        except Exception as e:
            log(f"ERROR on '{subject}': {e}")
            import traceback
            traceback.print_exc()
            continue

        log("")

    # Final summary
    state["total_unique"] = len(seen_uuids)
    save_state(state)

    log("=" * 60)
    log("HARVEST SUMMARY")
    log(f"  Total unique UUIDs in file: {len(seen_uuids):,}")
    log(f"  This run: {grand_total_written:,} new + {grand_total_dupes:,} dupes")
    log("")
    for subject, expected in subjects:
        ss = state["subjects"].get(subject, {})
        status = "DONE" if ss.get("finished") else "PARTIAL"
        log(
            f"  [{status}] {subject}: "
            f"API={ss.get('total_from_api', '?'):,}  "
            f"written={ss.get('written', 0):,}  "
            f"dupes={ss.get('duplicates', 0):,}"
        )
    log("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
