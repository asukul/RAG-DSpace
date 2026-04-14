"""
OAI-PMH harvester for ISU DSpace (dr.lib.iastate.edu).

Uses the standard OAI-PMH ListRecords verb with resumption tokens for
efficient bulk harvesting. Much faster and more reliable than the
Discovery API approach.

Features:
  - Resumable: saves resumption token to state file after each page
  - Incremental: supports --from date to harvest only new/updated records
  - Full metadata: extracts dc:title, dc:creator, dc:subject, dc:description,
    dc:date, dc:type, dc:identifier, dc:contributor, dc:source, dc:format
  - Outputs JSONL compatible with index_dspace_items.py

Usage:
    # Full harvest (all 120k+ items):
    python scripts/harvest_oai_pmh.py

    # Incremental (only items added/modified since date):
    python scripts/harvest_oai_pmh.py --from 2026-04-09

    # Resume interrupted harvest:
    python scripts/harvest_oai_pmh.py --resume

    # Dry run (first page only):
    python scripts/harvest_oai_pmh.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

OAI_BASE = "https://dr.lib.iastate.edu/server/oai/request"
METADATA_PREFIX = "oai_dc"
PAGE_SIZE = 100  # DSpace default, not configurable via OAI-PMH
SLEEP_BETWEEN_PAGES = 0.15  # 150ms politeness
REQUEST_TIMEOUT = 60
MAX_RETRIES = 5
BACKOFF_BASE = 2.0

SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
DATA_DIR = BACKEND_DIR / "data" / "dspace"
OUTPUT_FILE = DATA_DIR / "oai_harvest.jsonl"
STATE_FILE = DATA_DIR / "oai_harvest_state.json"

# OAI-PMH set spec -> our collection UUID mapping
SET_TO_UUID = {
    "col_20.500.12876_2": "ca9cf202-5b5b-4d43-b0d9-86df40a2d9dd",   # Conference Proceedings
    "col_20.500.12876_3": "76c07a07-0ef0-419f-a96a-1cadbca8fcb2",   # Publications
    "col_20.500.12876_4": "1c872b85-28f2-483c-8874-ac365af04218",   # Multimedia
    "col_20.500.12876_5": "0830d32e-14e1-4a4f-bb8f-271a75ed35af",   # Theses and Dissertations
    "col_20.500.12876_6": "71537944-3990-4d99-9351-64b7a4f83125",   # Creative Components
    "col_20.500.12876_8": "0f0575e3-4dc0-48d3-a64f-6e5039fbaf72",   # Series
    "col_20.500.12876_9": "91477f5a-e02a-44ba-9f76-5587ec907f19",   # Journals
    "col_20.500.12876_10": "0b90040b-44bb-486b-a5e3-7f477216ae37",  # Journal Volumes
    "col_20.500.12876_11": "1aa6c3ff-85e6-44a3-aad6-fc97a500cac5",  # Journal Issues
    "col_20.500.12876_13": "90ee9f70-f4eb-4b4d-87c7-97cc3dccff56",  # Admin Units
    "col_20.500.12876_14": "51e51f6d-6bca-492f-91ff-22c9e0936a8b",  # Admin Profiles
}

SET_TO_NAME = {
    "col_20.500.12876_2": "Conference Proceedings and Presentations",
    "col_20.500.12876_3": "Publications",
    "col_20.500.12876_4": "Multimedia",
    "col_20.500.12876_5": "Theses and Dissertations",
    "col_20.500.12876_6": "Creative Components",
    "col_20.500.12876_8": "Series",
    "col_20.500.12876_9": "Journals",
    "col_20.500.12876_10": "Journal Volumes",
    "col_20.500.12876_11": "Journal Issues",
    "col_20.500.12876_13": "Academic and Administrative Units",
    "col_20.500.12876_14": "Academic and Administrative Profiles",
}

HEADERS = {
    "User-Agent": "ISU-Research-RAG/1.0 (OAI-PMH harvester)",
    "Accept": "text/xml",
}

NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "oaidc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg: str) -> None:
    print(f"[{now_iso()}] {msg}", flush=True)


def extract_uuid_from_identifier(identifier: str) -> str:
    """Extract the handle/UUID from OAI identifier like oai:dr.lib.iastate.edu:20.500.12876/68760"""
    # The identifier contains the handle, not the UUID directly.
    # We'll use the handle as the unique key and the DSpace URL to link back.
    parts = identifier.split(":")
    if len(parts) >= 3:
        return parts[-1]  # e.g., "20.500.12876/68760"
    return identifier


def extract_year(dates: list[str]) -> str:
    """Extract the most likely publication year from dc:date values."""
    for d in dates:
        # Look for plain 4-digit year
        m = re.match(r"^(\d{4})$", d.strip())
        if m:
            return m.group(1)
    for d in dates:
        # Look for YYYY- at start
        m = re.match(r"(\d{4})-", d.strip())
        if m:
            yr = m.group(1)
            if 1800 <= int(yr) <= 2030:
                return yr
    for d in dates:
        # Look for "Mon Jan 01 ... UTC YYYY" pattern
        m = re.search(r"\b(\d{4})$", d.strip())
        if m:
            yr = m.group(1)
            if 1800 <= int(yr) <= 2030:
                return yr
    return ""


def extract_doi(identifiers: list[str]) -> str:
    """Extract DOI from dc:identifier values."""
    for ident in identifiers:
        if "doi.org/" in ident:
            return ident.strip()
        if ident.strip().startswith("10."):
            return f"https://doi.org/{ident.strip()}"
    return ""


def extract_dspace_url(identifiers: list[str]) -> str:
    """Extract the DSpace handle URL."""
    for ident in identifiers:
        if "dr.lib.iastate.edu/handle/" in ident:
            return ident.strip()
    return ""


def extract_bitstream_path(sources: list[str]) -> str:
    """Extract bitstream path from dc:source."""
    for src in sources:
        if "|||" in src:
            return src.split("|||")[0].strip()
        if src.strip().endswith(".pdf"):
            return src.strip()
    return ""


def parse_record(record_el: ET.Element) -> dict[str, Any] | None:
    """Parse a single OAI-PMH record into our JSONL format."""
    header = record_el.find("oai:header", NS)
    if header is None:
        return None

    # Check for deleted records
    status = header.get("status", "")
    if status == "deleted":
        return None

    identifier_el = header.find("oai:identifier", NS)
    datestamp_el = header.find("oai:datestamp", NS)
    set_specs = [s.text for s in header.findall("oai:setSpec", NS) if s.text]

    identifier = identifier_el.text if identifier_el is not None else ""
    datestamp = datestamp_el.text if datestamp_el is not None else ""
    handle = extract_uuid_from_identifier(identifier)

    # Find the collection (prefer col_ sets over com_ sets)
    collection_set = ""
    collection_uuid = ""
    collection_name = ""
    for s in set_specs:
        if s.startswith("col_"):
            collection_set = s
            collection_uuid = SET_TO_UUID.get(s, "")
            collection_name = SET_TO_NAME.get(s, s)
            break

    # Parse Dublin Core metadata
    md = record_el.find(".//oaidc:dc", NS)
    if md is None:
        return None

    def get_all(tag: str) -> list[str]:
        return [el.text for el in md.findall(f"dc:{tag}", NS) if el.text]

    titles = get_all("title")
    creators = get_all("creator")
    contributors = get_all("contributor")
    subjects = get_all("subject")
    descriptions = get_all("description")
    dates = get_all("date")
    types = get_all("type")
    identifiers = get_all("identifier")
    formats = get_all("format")
    sources = get_all("source")
    languages = get_all("language")

    title = titles[0] if titles else ""
    # Clean HTML from description
    abstract = descriptions[0] if descriptions else ""
    abstract = re.sub(r"<[^>]+>", " ", abstract)
    abstract = re.sub(r"\s+", " ", abstract).strip()

    year = extract_year(dates)
    item_type = types[0] if types else ""
    doi = extract_doi(identifiers)
    dspace_url = extract_dspace_url(identifiers)
    bitstream_path = extract_bitstream_path(sources)

    # Department from dc:contributor (usually department name)
    department = ""
    for c in contributors:
        if c and not any(name_part in c.lower() for name_part in ["committee", "advisor", "chair"]):
            department = c
            break

    # Build the record matching our existing JSONL schema
    return {
        "uuid": handle,  # Using handle as UUID (will reconcile later)
        "handle": handle,
        "oai_identifier": identifier,
        "oai_datestamp": datestamp,
        "collection_uuid": collection_uuid,
        "collection_name": collection_name,
        "collection_set": collection_set,
        "title": title,
        "authors": creators,
        "contributors": contributors,
        "department": department,
        "subjects": subjects,
        "abstract": abstract,
        "year": year,
        "issued": dates[0] if dates else "",
        "type": item_type,
        "doi": doi,
        "dspace_url": dspace_url,
        "has_bitstream": bool(bitstream_path) or "application/pdf" in " ".join(formats),
        "bitstream_path": bitstream_path,
        "language": languages[0] if languages else "",
        "oai_sets": set_specs,
    }


def fetch_page(resumption_token: str | None = None, from_date: str | None = None) -> tuple[list[dict], str | None, int, int]:
    """
    Fetch one page of OAI-PMH records.
    Returns: (records, next_resumption_token, complete_list_size, cursor)
    """
    if resumption_token:
        params = {"verb": "ListRecords", "resumptionToken": resumption_token}
    else:
        params = {"verb": "ListRecords", "metadataPrefix": METADATA_PREFIX}
        if from_date:
            params["from"] = from_date

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(OAI_BASE, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()

            # Clean surrogate characters that break XML parsing
            text = resp.content.decode("utf-8", errors="replace")
            root = ET.fromstring(text)

            # Check for OAI-PMH errors
            error = root.find(".//oai:error", NS)
            if error is not None:
                code = error.get("code", "")
                msg = error.text or ""
                if code == "noRecordsMatch":
                    return [], None, 0, 0
                raise RuntimeError(f"OAI-PMH error: {code} — {msg}")

            # Parse records
            record_els = root.findall(".//oai:record", NS)
            records = []
            for rel in record_els:
                rec = parse_record(rel)
                if rec:
                    records.append(rec)

            # Get resumption token
            rt_el = root.find(".//oai:resumptionToken", NS)
            next_token = None
            complete_size = 0
            cursor = 0
            if rt_el is not None:
                next_token = rt_el.text if rt_el.text else None
                complete_size = int(rt_el.get("completeListSize", "0") or "0")
                cursor = int(rt_el.get("cursor", "0") or "0")

            return records, next_token, complete_size, cursor

        except requests.exceptions.RequestException as e:
            wait = BACKOFF_BASE ** attempt
            log(f"  Request error (attempt {attempt+1}/{MAX_RETRIES}): {e}. Retrying in {wait:.0f}s...")
            time.sleep(wait)

    raise RuntimeError(f"Failed after {MAX_RETRIES} retries")


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(STATE_FILE)
    except PermissionError:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state() -> dict | None:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="OAI-PMH harvester for ISU DSpace")
    parser.add_argument("--from", dest="from_date", default=None,
                        help="Harvest only records modified since this date (YYYY-MM-DD)")
    parser.add_argument("--resume", action="store_true",
                        help="Resume from saved resumption token")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch first page only, print stats")
    parser.add_argument("--output", default=str(OUTPUT_FILE),
                        help="Output JSONL file path")
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    output_path = Path(args.output)

    log("=" * 60)
    log("ISU DSpace OAI-PMH Harvester")
    log(f"  Base URL:   {OAI_BASE}")
    log(f"  Format:     {METADATA_PREFIX}")
    log(f"  Output:     {output_path}")
    if args.from_date:
        log(f"  From date:  {args.from_date}")
    if args.resume:
        log(f"  Resuming from saved state")
    log("=" * 60)

    # Resume support
    resumption_token = None
    total_written = 0
    seen_handles = set()

    if args.resume:
        state = load_state()
        if state and state.get("resumption_token"):
            resumption_token = state["resumption_token"]
            total_written = state.get("total_written", 0)
            log(f"  Resuming from cursor {state.get('cursor', '?')}, {total_written} already written")
            # Load existing handles to avoid dupes
            if output_path.exists():
                with open(output_path, encoding="utf-8") as f:
                    for line in f:
                        try:
                            rec = json.loads(line)
                            seen_handles.add(rec.get("handle", ""))
                        except:
                            pass
                log(f"  Loaded {len(seen_handles)} existing handles for dedup")
        else:
            log("  No saved state found, starting fresh")

    # Open output file
    mode = "a" if args.resume and output_path.exists() else "w"
    outf = open(output_path, mode, encoding="utf-8")

    t0 = time.time()
    complete_size = 0
    page_num = 0
    errors = 0

    try:
        while True:
            page_num += 1
            records, next_token, cs, cursor = fetch_page(
                resumption_token=resumption_token,
                from_date=args.from_date if not resumption_token else None,
            )

            if cs > 0:
                complete_size = cs

            new_in_page = 0
            for rec in records:
                handle = rec.get("handle", "")
                if handle and handle not in seen_handles:
                    seen_handles.add(handle)
                    outf.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    total_written += 1
                    new_in_page += 1

            elapsed = time.time() - t0
            rate = total_written / max(elapsed, 0.01)
            pct = f" ({100*cursor/complete_size:.0f}%)" if complete_size else ""
            log(f"  page {page_num}: got {len(records)} records, {new_in_page} new | "
                f"total={total_written:,}{pct} | {rate:.0f}/s")

            # Save state
            save_state({
                "resumption_token": next_token,
                "total_written": total_written,
                "complete_list_size": complete_size,
                "cursor": cursor,
                "page": page_num,
                "last_updated": now_iso(),
                "from_date": args.from_date,
            })

            if args.dry_run:
                log("  [DRY RUN] Stopping after first page.")
                break

            if not next_token:
                log("  No more resumption tokens — harvest complete.")
                break

            resumption_token = next_token
            time.sleep(SLEEP_BETWEEN_PAGES)

    except KeyboardInterrupt:
        log("  Interrupted. State saved — use --resume to continue.")
    except Exception as e:
        log(f"  ERROR: {e}")
        errors = 1
    finally:
        outf.close()

    elapsed = time.time() - t0
    log("")
    log("=" * 60)
    log(f"Harvest {'complete' if not errors else 'stopped with errors'}")
    log(f"  Total records written: {total_written:,}")
    log(f"  Complete list size:    {complete_size:,}")
    log(f"  Duration:              {elapsed/60:.1f} min")
    log(f"  Rate:                  {total_written/max(elapsed,0.01):.0f} records/s")
    log(f"  Output:                {output_path}")
    log(f"  Output size:           {output_path.stat().st_size / 1024 / 1024:.1f} MB")

    return errors


if __name__ == "__main__":
    sys.exit(main())
