"""
arXiv CS-only metadata harvester.

Uses the official arXiv OAI-PMH endpoint at http://export.arxiv.org/oai2 to
walk the `cs` set with the `arXiv` metadata prefix (arXiv's own richer schema,
not oai_dc). Writes batched JSONL records under
`backend/data/arxiv_cs/oai_records/`.

Metadata-only harvest — PDFs are NOT downloaded here. arXiv's AWS S3 bulk
bucket `arxiv` (requester-pays) is the canonical source for full PDFs; the
download phase is a separate script and requires explicit cost approval
(~$250-350 one-time for the full 6 TB pull).

Rate limit: arXiv's OAI-PMH service caps at ~1 request per 3 seconds. Some
requests will return HTTP 503 with a `Retry-After: 600` header when the
rolling window is exceeded — the harvester honors that.

Usage:
    python backend/scripts/harvest_arxiv_cs.py --max 100000
    python backend/scripts/harvest_arxiv_cs.py --from 2024-01-01
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
from typing import Any, Dict, List, Optional, Tuple

import requests


HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
DATA_DIR = BACKEND / "data" / "arxiv_cs"
OUT_DIR = DATA_DIR / "oai_records"
STATE_FILE = DATA_DIR / "oai_harvest_state.json"
LOG_FILE = DATA_DIR / "harvest.log"

OAI_ENDPOINT = "http://export.arxiv.org/oai2"
SET_SPEC = "cs"  # all CS subcategories
METADATA_PREFIX = "arXiv"  # arXiv-native schema (richer than oai_dc)

# arXiv namespaces
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "arxiv": "http://arxiv.org/OAI/arXiv/",
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
    retries: int = 8,
) -> str:
    """Honors arXiv's Retry-After on 503s."""
    url_params = {"verb": verb}
    if params:
        url_params.update(params)
    headers = {"User-Agent": "RAG-DSpace/1.0 harvester (research use)"}
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(OAI_ENDPOINT, params=url_params, headers=headers, timeout=120)
        except Exception as e:
            wait = min(30 * attempt, 600)
            log(f"  transport error {type(e).__name__}: {e}; retry {attempt}/{retries} in {wait}s")
            time.sleep(wait)
            continue

        if r.status_code == 200:
            return r.text
        if r.status_code == 503:
            retry_after = int(r.headers.get("Retry-After", "300") or "300")
            log(f"  HTTP 503 (rate-limited); waiting {retry_after}s per Retry-After header")
            time.sleep(retry_after)
            continue
        if 500 <= r.status_code < 600:
            wait = min(60 * attempt, 600)
            log(f"  HTTP {r.status_code}; retry {attempt}/{retries} in {wait}s")
            time.sleep(wait)
            continue
        raise RuntimeError(f"OAI {verb}: HTTP {r.status_code}: {r.text[:200]}")
    raise RuntimeError(f"OAI {verb} failed after {retries} retries")


def parse_records(xml_text: str) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[int]]:
    root = ET.fromstring(xml_text)

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
        arxiv_root = meta.find("arxiv:arXiv", NS) if meta is not None else None

        parsed: Dict[str, Any] = {
            "identifier": identifier,
            "datestamp": datestamp,
            "sets": set_specs,
        }
        if arxiv_root is not None:
            for field in ("id", "created", "updated", "categories", "title",
                          "abstract", "comments", "journal-ref", "doi",
                          "license", "proxy"):
                el = arxiv_root.find(f"arxiv:{field}", NS)
                if el is not None and (el.text or "").strip():
                    parsed[field] = el.text.strip()
            authors_el = arxiv_root.find("arxiv:authors", NS)
            if authors_el is not None:
                authors = []
                for au in authors_el.findall("arxiv:author", NS):
                    keyname = au.findtext("arxiv:keyname", default="", namespaces=NS)
                    forenames = au.findtext("arxiv:forenames", default="", namespaces=NS)
                    affiliation = au.findtext("arxiv:affiliation", default="", namespaces=NS)
                    authors.append({
                        "keyname": keyname,
                        "forenames": forenames,
                        "affiliation": affiliation,
                    })
                if authors:
                    parsed["authors"] = authors
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
    parser.add_argument("--from", dest="from_date", default=None,
                        help="Only harvest records with datestamp >= YYYY-MM-DD")
    parser.add_argument("--rate-sleep", type=float, default=3.5,
                        help="Seconds to sleep between successful requests (arXiv asks ~3s)")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()

    log("=" * 60)
    log("arXiv CS OAI-PMH harvest")
    log(f"  endpoint:      {OAI_ENDPOINT}")
    log(f"  setSpec:       {SET_SPEC}")
    log(f"  metadataPrefix:{METADATA_PREFIX}")
    log(f"  from:          {args.from_date or '(none)'}")
    log(f"  rate sleep:    {args.rate_sleep}s")
    log(f"  output:        {OUT_DIR}")
    log(f"  resume:        batch {state['batch_number']}, "
        f"{state['total_harvested']:,} harvested, "
        f"token={'yes' if state.get('resumption_token') else 'no'}")
    log(f"  max this run:  {args.max}")
    log("=" * 60)

    remaining = args.max

    while remaining > 0 and not state.get("completed"):
        batch_num = state["batch_number"] + 1
        token = state.get("resumption_token")
        log(f"[batch {batch_num}] fetching...")
        if token:
            params = {"resumptionToken": token}
        else:
            params = {
                "set": SET_SPEC,
                "metadataPrefix": METADATA_PREFIX,
            }
            if args.from_date:
                params["from"] = args.from_date

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
        time.sleep(args.rate_sleep)

    log(
        f"Done. Harvested {state['total_harvested']:,} records in "
        f"{state['batch_number']} batches. Completed={state.get('completed', False)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
