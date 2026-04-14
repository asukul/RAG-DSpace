"""
OAI-PMH harvester for DSpace@MIT (dspace.mit.edu, DSpace 6.3).

Walks the ListRecords verb with oai_dc metadata format, collects all items
including the CSAIL community (AI Memos 1959-2004, CSAIL Technical Reports
2003-present, which live under handle 1721.1/5458), and writes batches to
JSONL files under `backend/data/mit_dspace/oai_records/`.

This is a read-only metadata harvest — it does NOT download PDFs. PDF download
is a separate phase (`harvest_mit_pdfs.py`) that runs only for records we
actually want to embed.

Usage:
    python backend/scripts/harvest_mit_dspace.py --max 50000
    python backend/scripts/harvest_mit_dspace.py --set col_1721.1_5458   # CSAIL only
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

try:
    from curl_cffi import requests as http  # type: ignore
    _HTTP_BACKEND = "curl_cffi"
except ImportError:
    import requests as http  # type: ignore
    _HTTP_BACKEND = "requests"


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DATA_DIR = BACKEND / "data" / "mit_dspace"
OUT_DIR = DATA_DIR / "oai_records"
STATE_FILE = DATA_DIR / "oai_harvest_state.json"
LOG_FILE = DATA_DIR / "harvest.log"

OAI_ENDPOINT = "https://dspace.mit.edu/oai/request"
# CSAIL subtree in DSpace@MIT:
CSAIL_SET_SPEC = "col_1721.1_5458"  # discovered from the DSpace@MIT registry

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


def log(msg: str) -> None:
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def load_state() -> Dict[str, Any]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "batch_number": 0,
        "total_harvested": 0,
        "resumption_token": None,
        "completed": False,
    }


def save_state(state: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(STATE_FILE.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE_FILE)


def oai_fetch(
    verb: str,
    params: Optional[Dict[str, str]] = None,
    retries: int = 5,
) -> str:
    """One OAI-PMH request with exponential backoff on 5xx."""
    url_params = {"verb": verb}
    if params:
        url_params.update(params)
    last_err: Optional[str] = None
    for attempt in range(1, retries + 1):
        try:
            if _HTTP_BACKEND == "curl_cffi":
                r = http.get(
                    OAI_ENDPOINT,
                    params=url_params,
                    impersonate="chrome124",
                    timeout=60,
                )
            else:
                r = http.get(
                    OAI_ENDPOINT,
                    params=url_params,
                    timeout=60,
                    headers={"User-Agent": "Mozilla/5.0 RAG-DSpace/1.0 harvester"},
                )
            if r.status_code == 200:
                return r.text
            if 500 <= r.status_code < 600:
                wait = min(60 * attempt, 300)
                last_err = f"HTTP {r.status_code}"
                log(f"  [{last_err}] attempt {attempt}, waiting {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(f"OAI {verb}: HTTP {r.status_code}: {r.text[:200]}")
        except Exception as e:
            wait = min(30 * attempt, 300)
            last_err = f"{type(e).__name__}: {e}"
            log(f"  [{last_err}] attempt {attempt}, waiting {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"OAI {verb} failed after {retries} retries: {last_err}")


def parse_records(xml_text: str) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[int]]:
    """Parse a ListRecords response; return (records, resumption_token, total_list_size)."""
    root = ET.fromstring(xml_text)

    # Check for OAI error
    err = root.find("oai:error", NS)
    if err is not None:
        code = err.get("code", "unknown")
        raise RuntimeError(f"OAI error {code}: {err.text}")

    list_records = root.find("oai:ListRecords", NS)
    if list_records is None:
        return [], None, None

    records: List[Dict[str, Any]] = []
    for rec in list_records.findall("oai:record", NS):
        header = rec.find("oai:header", NS)
        if header is None:
            continue
        if header.get("status") == "deleted":
            continue
        identifier = header.findtext("oai:identifier", default="", namespaces=NS)
        datestamp = header.findtext("oai:datestamp", default="", namespaces=NS)
        set_specs = [s.text or "" for s in header.findall("oai:setSpec", NS)]

        meta = rec.find("oai:metadata", NS)
        dc_root = None
        if meta is not None:
            dc_root = meta.find("oai_dc:dc", NS)
        parsed: Dict[str, Any] = {
            "identifier": identifier,
            "datestamp": datestamp,
            "sets": set_specs,
        }
        if dc_root is not None:
            dc_fields = [
                "title", "creator", "contributor", "subject", "description",
                "publisher", "date", "type", "format", "identifier",
                "source", "language", "relation", "coverage", "rights",
            ]
            for field in dc_fields:
                values = [
                    (el.text or "").strip()
                    for el in dc_root.findall(f"dc:{field}", NS)
                    if el.text
                ]
                if values:
                    parsed[f"dc_{field}"] = values
        records.append(parsed)

    token_el = list_records.find("oai:resumptionToken", NS)
    token = (token_el.text or "").strip() if token_el is not None and token_el.text else None
    total = None
    if token_el is not None:
        try:
            total = int(token_el.get("completeListSize", "0")) or None
        except Exception:
            pass

    return records, token, total


def write_batch(batch_number: int, records: List[Dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_file = OUT_DIR / f"batch_{batch_number:05d}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=200_000,
                        help="Max records this run")
    parser.add_argument("--set", default=None,
                        help=f"OAI setSpec filter (e.g. {CSAIL_SET_SPEC} for CSAIL)")
    parser.add_argument("--rate", type=float, default=0.5,
                        help="Requests per second (default 0.5)")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()

    log("=" * 60)
    log("MIT DSpace OAI-PMH harvest")
    log(f"  http backend:   {_HTTP_BACKEND}")
    log(f"  endpoint:       {OAI_ENDPOINT}")
    log(f"  setSpec filter: {args.set or '(none — all sets)'}")
    log(f"  rate:           {args.rate} req/s")
    log(f"  output:         {OUT_DIR}")
    log(f"  resume:         batch {state['batch_number']}, "
        f"{state['total_harvested']:,} harvested so far, "
        f"token={'yes' if state.get('resumption_token') else 'no'}")
    log(f"  max this run:   {args.max}")
    log("=" * 60)

    sleep_between = 1.0 / max(args.rate, 0.01)
    remaining = args.max

    while remaining > 0 and not state.get("completed"):
        batch_num = state["batch_number"] + 1
        token = state.get("resumption_token")
        log(f"[batch {batch_num}] fetching...")
        if token:
            params = {"resumptionToken": token}
        else:
            params = {"metadataPrefix": "oai_dc"}
            if args.set:
                params["set"] = args.set

        try:
            xml_text = oai_fetch("ListRecords", params)
        except Exception as e:
            log(f"  fatal: {e}")
            return 1

        try:
            records, next_token, total = parse_records(xml_text)
        except Exception as e:
            log(f"  parse error: {e}")
            return 1

        if not records and not next_token:
            log("  no records returned — assuming complete")
            state["completed"] = True
            save_state(state)
            break

        write_batch(batch_num, records)
        state["batch_number"] = batch_num
        state["total_harvested"] += len(records)
        state["resumption_token"] = next_token
        if total and "complete_list_size" not in state:
            state["complete_list_size"] = total
        if next_token is None:
            state["completed"] = True
        save_state(state)

        log(
            f"  batch {batch_num}: {len(records)} records "
            f"(total {state['total_harvested']:,}"
            + (f"/{state.get('complete_list_size', 0):,}" if state.get("complete_list_size") else "")
            + f"), token={'yes' if next_token else 'END'}"
        )

        remaining -= len(records)
        if next_token is None or remaining <= 0:
            break
        time.sleep(sleep_between)

    log(
        f"Done. Harvested {state['total_harvested']:,} records total in "
        f"{state['batch_number']} batches. Completed={state.get('completed', False)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
