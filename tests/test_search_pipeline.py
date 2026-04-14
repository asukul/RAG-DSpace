"""
End-to-end test harness for the ISU Research Search API.

Tests two flows for each Computer Science faculty member:

1) Name search:    POST /api/search {query: "<Faculty Name>"}
   - Verify the response sources include the publications DSpace knows about
     for that author/advisor.
   - Verify the faculty member appears in found_faculty.

2) Topic search:   POST /api/search {query: "<short topic from paper title>"}
   - For each publication of the faculty member, query the topic and
     verify the faculty member appears in found_faculty (or that their
     paper is in sources).

Outputs a structured JSON report under tests/results/.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

import requests

API_DEFAULT = os.environ.get("RAG_API_URL", "http://127.0.0.1:8009")
DSPACE_BASE = "https://dr.lib.iastate.edu"
DSPACE_API = f"{DSPACE_BASE}/server/api"

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)

# DSpace blocks the default python-requests UA. Use a real browser UA.
HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json",
}


# ---------------------------------------------------------------------------
# Data fetchers
# ---------------------------------------------------------------------------


def get_cs_faculty(api_url: str) -> List[Dict[str, Any]]:
    """Fetch Computer Science faculty from the running backend."""
    r = requests.get(f"{api_url}/api/faculty", timeout=30)
    r.raise_for_status()
    all_faculty = r.json()
    cs = [
        f
        for f in all_faculty
        if "computer science" in (f.get("department") or "").lower()
    ]
    # Stable order by name for repeatable runs.
    cs.sort(key=lambda f: (f.get("name") or "").lower())
    return cs


def dspace_search_by_person(name: str, size: int = 50) -> List[Dict[str, Any]]:
    """
    Search DSpace for items associated with a person (author OR advisor OR
    contributor). Returns a list of normalized paper dicts.
    """
    try:
        r = requests.get(
            f"{DSPACE_API}/discover/search/objects",
            params={"query": name, "dsoType": "item", "size": size, "sort": "score,desc"},
            headers=HTTP_HEADERS,
            timeout=30,
        )
        if r.status_code != 200:
            print(f"[dspace] {r.status_code} for {name!r}")
            return []
        data = r.json()
    except Exception as e:
        print(f"[dspace] error fetching for {name!r}: {e}")
        return []

    results: List[Dict[str, Any]] = []
    for obj in (
        data.get("_embedded", {})
        .get("searchResult", {})
        .get("_embedded", {})
        .get("objects", [])
    ):
        emb = obj.get("_embedded", {})
        item = emb.get("indexableObject")
        if not item:
            continue

        meta = item.get("metadata", {}) or {}

        def _vals(field: str) -> List[str]:
            return [
                x.get("value", "")
                for x in (meta.get(field) or [])
                if x.get("value")
            ]

        title_list = _vals("dc.title")
        if not title_list:
            continue

        authors = _vals("dc.contributor.author")
        advisors = _vals("dc.contributor.advisor") + _vals(
            "dc.contributor.majorProfessor"
        )
        contributors = (
            _vals("dc.contributor")
            + _vals("dc.contributor.committeeMember")
        )

        # Normalized check: does any of the people fields actually contain the
        # name we asked about? DSpace fuzzy matches a lot, and we only want
        # papers where this person is actually listed.
        all_people = authors + advisors + contributors
        if not _person_in_people(name, all_people):
            continue

        results.append(
            {
                "uuid": item.get("uuid", ""),
                "title": title_list[0],
                "authors": authors,
                "advisors": advisors,
                "contributors": contributors,
                "year": (_vals("dc.date.issued") or [""])[0],
                "type": (_vals("dc.type") or [""])[0],
                "url": f"{DSPACE_BASE}/items/{item.get('uuid','')}",
            }
        )
    return results


def _person_in_people(name: str, people: List[str]) -> bool:
    """
    Permissive name matching: 'Adisak Sukul' should match both
    'Adisak Sukul' and 'Sukul, Adisak'.
    """
    parts = name.lower().split()
    if not parts:
        return False
    last = parts[-1]
    first = parts[0]
    for p in people:
        pl = p.lower()
        if name.lower() in pl:
            return True
        # 'Sukul, Adisak' style
        if last in pl and first in pl:
            return True
    return False


def api_search(api_url: str, query: str, limit: int = 20) -> Dict[str, Any]:
    r = requests.post(
        f"{api_url}/api/search",
        json={"query": query, "limit": limit},
        timeout=120,
    )
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


@dataclass
class NameSearchResult:
    faculty_id: str
    faculty_name: str
    expected_paper_count: int
    sources_returned: int
    expected_uuids: List[str]
    matched_uuids: List[str]
    coverage_pct: float
    in_found_faculty: bool
    found_faculty_position: Optional[int]
    found_faculty_total: int
    related_faculty_total: int
    answer_mentions_name: bool
    duration_sec: float


@dataclass
class TopicSearchCase:
    paper_uuid: str
    paper_title: str
    query: str
    paper_in_sources: bool
    paper_in_citations: bool
    faculty_in_found: bool
    found_faculty_total: int
    answer_mentions_name: bool


@dataclass
class FacultyTestReport:
    faculty_id: str
    faculty_name: str
    name_search: NameSearchResult
    topic_searches: List[TopicSearchCase] = field(default_factory=list)
    topic_pass_count: int = 0
    topic_total: int = 0
    notes: List[str] = field(default_factory=list)


def _topic_query_from_title(title: str) -> str:
    """
    Pick a short topical phrase from a paper title to use as a query.
    Strip leading 'A '/'An '/'The ', cap to ~6 words, drop punctuation.
    """
    t = re.sub(r"^(a|an|the)\s+", "", title.strip(), flags=re.IGNORECASE)
    t = re.sub(r"[^\w\s\-]", " ", t)
    words = [w for w in t.split() if w]
    return " ".join(words[:6])


def _normalize_uuid_set(items: List[Dict[str, Any]]) -> Set[str]:
    return {x.get("uuid", "") for x in items if x.get("uuid")}


def test_name_search(
    api_url: str, faculty: Dict[str, Any], expected_papers: List[Dict[str, Any]]
) -> NameSearchResult:
    name = faculty["name"]
    fid = faculty["id"]
    t0 = time.time()
    resp = api_search(api_url, name)
    dt = round(time.time() - t0, 2)

    sources = resp.get("sources") or []
    found = resp.get("found_faculty") or []
    related = resp.get("related_faculty") or []
    answer = resp.get("answer") or ""

    expected_uuids = [p["uuid"] for p in expected_papers]
    expected_set = set(expected_uuids)
    source_uuids = _normalize_uuid_set(sources)
    matched = sorted(expected_set & source_uuids)

    coverage = (len(matched) / len(expected_uuids)) if expected_uuids else 0.0

    pos = None
    for i, f in enumerate(found):
        if f.get("id") == fid:
            pos = i
            break

    return NameSearchResult(
        faculty_id=fid,
        faculty_name=name,
        expected_paper_count=len(expected_uuids),
        sources_returned=len(sources),
        expected_uuids=expected_uuids,
        matched_uuids=matched,
        coverage_pct=round(coverage, 3),
        in_found_faculty=pos is not None,
        found_faculty_position=pos,
        found_faculty_total=len(found),
        related_faculty_total=len(related),
        answer_mentions_name=name.lower() in answer.lower()
        or name.split()[-1].lower() in answer.lower(),
        duration_sec=dt,
    )


def test_topic_search(
    api_url: str, faculty: Dict[str, Any], paper: Dict[str, Any]
) -> TopicSearchCase:
    name = faculty["name"]
    fid = faculty["id"]
    query = _topic_query_from_title(paper["title"])
    resp = api_search(api_url, query)

    sources = resp.get("sources") or []
    citations = resp.get("citations") or []
    found = resp.get("found_faculty") or []
    answer = resp.get("answer") or ""

    paper_uuid = paper["uuid"]
    paper_in_sources = any(s.get("uuid") == paper_uuid for s in sources)
    paper_in_citations = any(c.get("uuid") == paper_uuid for c in citations)
    faculty_in_found = any(f.get("id") == fid for f in found)

    return TopicSearchCase(
        paper_uuid=paper_uuid,
        paper_title=paper["title"],
        query=query,
        paper_in_sources=paper_in_sources,
        paper_in_citations=paper_in_citations,
        faculty_in_found=faculty_in_found,
        found_faculty_total=len(found),
        answer_mentions_name=name.lower() in answer.lower()
        or name.split()[-1].lower() in answer.lower(),
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def run_for_faculty(
    api_url: str,
    faculty: Dict[str, Any],
    max_topic_tests: int = 5,
) -> FacultyTestReport:
    print(f"\n=== {faculty['name']} ({faculty['id']}) ===")
    expected = dspace_search_by_person(faculty["name"], size=50)
    print(f"  DSpace returned {len(expected)} matching papers")

    name_res = test_name_search(api_url, faculty, expected)
    print(
        f"  Name search: coverage {name_res.coverage_pct*100:.0f}% "
        f"({len(name_res.matched_uuids)}/{name_res.expected_paper_count}); "
        f"in found_faculty={name_res.in_found_faculty} pos={name_res.found_faculty_position}"
    )

    report = FacultyTestReport(
        faculty_id=faculty["id"],
        faculty_name=faculty["name"],
        name_search=name_res,
    )
    if name_res.expected_paper_count == 0:
        report.notes.append("DSpace returned no papers for this faculty (may be teaching-only)")
        return report

    # Topic searches: pick the top N papers and search by their title topic
    sample = expected[:max_topic_tests]
    for paper in sample:
        try:
            tc = test_topic_search(api_url, faculty, paper)
        except Exception as e:
            report.notes.append(f"topic search failed for {paper['uuid']}: {e}")
            continue
        report.topic_searches.append(tc)
        report.topic_total += 1
        if tc.faculty_in_found or tc.paper_in_sources:
            report.topic_pass_count += 1

    print(
        f"  Topic searches: {report.topic_pass_count}/{report.topic_total} "
        f"papers correctly attributed back to faculty"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=API_DEFAULT)
    parser.add_argument("--limit", type=int, default=0,
                        help="Max faculty to test (0 = all CS)")
    parser.add_argument("--only", default=None,
                        help="Only test the faculty whose id (or name substring) matches")
    parser.add_argument("--max-topic-tests", type=int, default=5)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    api_url = args.api.rstrip("/")
    print(f"API: {api_url}")

    # Health check
    try:
        h = requests.get(f"{api_url}/health", timeout=10).json()
        print(f"Health: {h}")
    except Exception as e:
        print(f"Backend health check failed: {e}")
        return 2

    cs = get_cs_faculty(api_url)
    print(f"Loaded {len(cs)} CS faculty")

    if args.only:
        needle = args.only.lower()
        cs = [f for f in cs if needle in (f.get("id") or "").lower()
              or needle in (f.get("name") or "").lower()]
        print(f"Filtered to {len(cs)} matching '{args.only}'")

    if args.limit and args.limit > 0:
        cs = cs[: args.limit]

    reports: List[FacultyTestReport] = []
    incremental_path = (
        args.out
        or os.path.join(
            RESULTS_DIR, f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
    )
    for i, faculty in enumerate(cs, 1):
        print(f"\n[{i}/{len(cs)}]", end="")
        try:
            r = run_for_faculty(api_url, faculty,
                                max_topic_tests=args.max_topic_tests)
        except Exception as e:
            print(f"  EXCEPTION: {e}")
            continue
        reports.append(r)
        # Incremental save every 5 faculty so we don't lose work on a kill
        if i % 5 == 0:
            try:
                with open(incremental_path, "w", encoding="utf-8") as f:
                    json.dump(
                        {
                            "summary": {"in_progress": True, "count": len(reports)},
                            "reports": [
                                {
                                    **{k: v for k, v in asdict(r).items() if k != "name_search"},
                                    "name_search": asdict(r.name_search),
                                }
                                for r in reports
                            ],
                        },
                        f,
                        indent=2,
                    )
            except Exception:
                pass

    # Aggregate
    total_with_pubs = [r for r in reports if r.name_search.expected_paper_count > 0]
    avg_coverage = (
        sum(r.name_search.coverage_pct for r in total_with_pubs) / len(total_with_pubs)
        if total_with_pubs
        else 0
    )
    in_found = sum(1 for r in reports if r.name_search.in_found_faculty)
    topic_total = sum(r.topic_total for r in reports)
    topic_pass = sum(r.topic_pass_count for r in reports)

    summary = {
        "api_url": api_url,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "faculty_tested": len(reports),
        "faculty_with_dspace_papers": len(total_with_pubs),
        "name_search_avg_coverage": round(avg_coverage, 3),
        "name_search_in_found_faculty": in_found,
        "topic_searches_total": topic_total,
        "topic_searches_pass": topic_pass,
        "topic_searches_pct": round(topic_pass / topic_total, 3) if topic_total else 0,
    }

    print("\n========== SUMMARY ==========")
    for k, v in summary.items():
        print(f"{k}: {v}")

    out_path = incremental_path
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "summary": summary,
                "reports": [
                    {
                        **{k: v for k, v in asdict(r).items() if k != "name_search"},
                        "name_search": asdict(r.name_search),
                    }
                    for r in reports
                ],
            },
            f,
            indent=2,
        )
    print(f"\nSaved report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
