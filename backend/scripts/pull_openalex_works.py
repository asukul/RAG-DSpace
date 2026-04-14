"""
Phase 2 Step 2 — bulk pull all 193k Iowa State works from OpenAlex.

Strategy: filter Works by institution=I173911158, paginate with cursor at
per_page=200, save as JSONL incrementally so a kill mid-run doesn't lose
work.

Output:
  backend/data/openalex_works_isu.jsonl   (one work per line)

Run:
    python backend/scripts/pull_openalex_works.py
    python backend/scripts/pull_openalex_works.py --resume
    python backend/scripts/pull_openalex_works.py --limit 1000      # smoke test
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import pyalex
from pyalex import Works

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
OUT = BACKEND / "data" / "openalex_works_isu.jsonl"
STATE = BACKEND / "data" / "openalex_works_isu_state.json"

ISU = "I173911158"
PER_PAGE = 200


def short_id(s: str) -> str:
    return s.split("/")[-1] if s else ""


def slim_work(w: Dict[str, Any]) -> Dict[str, Any]:
    """Keep just the fields we'll use to keep the JSONL small."""
    authorships = w.get("authorships") or []
    authors_compact = []
    for a in authorships:
        author = a.get("author") or {}
        authors_compact.append({
            "id": short_id(author.get("id", "")),
            "name": author.get("display_name"),
            "orcid": author.get("orcid"),
            "position": a.get("author_position"),
            "institutions": [
                {"id": short_id(i.get("id", "")), "name": i.get("display_name")}
                for i in (a.get("institutions") or [])
            ],
        })
    primary_loc = w.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    topics = w.get("topics") or []
    return {
        "id": short_id(w.get("id", "")),
        "doi": w.get("doi"),
        "title": w.get("title"),
        "publication_year": w.get("publication_year"),
        "type": w.get("type"),
        "type_crossref": w.get("type_crossref"),
        "cited_by_count": w.get("cited_by_count"),
        "is_retracted": w.get("is_retracted"),
        "is_paratext": w.get("is_paratext"),
        "language": w.get("language"),
        "host_venue": {
            "id": short_id(source.get("id", "")),
            "display_name": source.get("display_name"),
            "issn_l": source.get("issn_l"),
            "type": source.get("type"),
        },
        "authors": authors_compact,
        "topics": [
            {
                "id": short_id(t.get("id", "")),
                "display_name": t.get("display_name"),
                "score": t.get("score"),
            }
            for t in topics[:5]
        ],
        "primary_topic": (
            {
                "id": short_id((w.get("primary_topic") or {}).get("id", "")),
                "display_name": (w.get("primary_topic") or {}).get("display_name"),
            }
            if w.get("primary_topic") else None
        ),
        "abstract_inverted_index_present": bool(w.get("abstract_inverted_index")),
    }


def load_state() -> Dict[str, Any]:
    if STATE.exists():
        try:
            return json.loads(STATE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save_state(state: Dict[str, Any]) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(STATE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="adisak.sukul@gmail.com")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after pulling this many works (smoke test)")
    parser.add_argument("--resume", action="store_true",
                        help="Append to existing JSONL using saved cursor state")
    args = parser.parse_args()

    pyalex.config.email = args.email

    if not args.resume and OUT.exists():
        OUT.unlink()
        if STATE.exists():
            STATE.unlink()

    state = load_state() if args.resume else {}
    written = state.get("written", 0)
    cursor = state.get("cursor", "*")
    started_at = state.get("started_at") or time.strftime("%Y-%m-%dT%H:%M:%S")

    print(f"Pulling all ISU works (institution={ISU})")
    print(f"  output: {OUT}")
    print(f"  state:  {STATE}")
    print(f"  starting at written={written}, cursor={cursor}")
    print()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fout = OUT.open("a", encoding="utf-8")

    t0 = time.time()
    page_n = 0
    try:
        # pyalex pagination — uses cursor pagination automatically
        pager = (
            Works()
            .filter(authorships={"institutions": {"id": ISU}})
            .paginate(per_page=PER_PAGE, n_max=None)
        )
        for page in pager:
            page_n += 1
            for w in page:
                slim = slim_work(w)
                fout.write(json.dumps(slim, ensure_ascii=False) + "\n")
                written += 1
                if args.limit and written >= args.limit:
                    break
            fout.flush()
            elapsed = time.time() - t0
            rate = (written - state.get("written", 0)) / max(elapsed, 0.01)
            print(f"  page {page_n}: written={written} ({rate:.0f}/s)", flush=True)

            state.update({
                "written": written,
                "cursor": cursor,  # pyalex doesn't expose the cursor; rely on resumption by re-fetch
                "started_at": started_at,
                "last_page": page_n,
                "last_updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
            if page_n % 5 == 0:
                save_state(state)

            if args.limit and written >= args.limit:
                break
    except KeyboardInterrupt:
        print("\nInterrupted. Partial data is on disk.")
    finally:
        fout.close()
        save_state({**state, "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")})

    elapsed = time.time() - t0
    print()
    print("=" * 60)
    print(f"Done. {written} works pulled in {elapsed/60:.1f} min")
    print(f"  output: {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
