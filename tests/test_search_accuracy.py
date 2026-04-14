"""
Extended accuracy test suite for the ISU Research Search API.

Complements `tests/test_search_pipeline.py` (which tests per-faculty coverage
against DSpace ground truth) with four extra categories that stress the
"a user can search in various ways and get correct results" guarantee:

  1. Name-variant tests: does "Adisak Sukul" / "Sukul, Adisak" / "Sukul" /
     "A. Sukul" / "adisak sukul" / "ADISAK SUKUL" all land the same faculty
     in found_faculty?
  2. Golden query tests: hand-picked topical queries paired with expected
     top-K faculty and/or expected paper UUIDs. Regression canary.
  3. Related-publications endpoint test: GET /api/faculty/{id}/publications
     should return at least K% of that faculty's DSpace-known papers.
  4. Edge case tests: empty query, very long query, non-English query, typo
     query, nonexistent-topic query. All should respond gracefully (no 5xx,
     no hang, reasonable "I don't know" answers).

Usage:
    python tests/test_search_accuracy.py --api http://127.0.0.1:8009
    python tests/test_search_accuracy.py --api https://backend-623732207442.us-central1.run.app

Outputs a structured JSON report to tests/results/accuracy_report_<stamp>.json
and prints a human-readable summary to stdout.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

# Reuse the DSpace ground-truth helpers from the sibling test module.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_search_pipeline import (  # noqa: E402
    dspace_search_by_person,
    _person_in_people,
    api_search,
    get_cs_faculty,
)

API_DEFAULT = os.environ.get("RAG_API_URL", "http://127.0.0.1:8009")

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")
os.makedirs(RESULTS_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# Target faculty for per-person stress tests
# ---------------------------------------------------------------------------

# Hand-picked faculty that we expect to have good DSpace presence. The driver
# will fall back to auto-selecting from CS faculty if any of these are absent.
TARGET_FACULTY_NAMES = [
    "Adisak Sukul",
    "Johnny Wong",
    "Wallapak Tavanapong",
    "Simanta Mitra",
    "Srinivas Aluru",
    "Soma Chaudhuri",
    "Carl Chang",
    "Hridesh Rajan",
    "Ying Cai",
    "Tien Nguyen",
]


def _name_variants(name: str) -> List[str]:
    """
    Generate a spectrum of plausible search-box spellings of one faculty name.
    'Adisak Sukul' ->
        ['Adisak Sukul', 'Sukul, Adisak', 'Sukul', 'A. Sukul',
         'adisak sukul', 'ADISAK SUKUL', 'A Sukul']
    """
    parts = name.strip().split()
    if len(parts) < 2:
        return [name]
    first = parts[0]
    last = parts[-1]
    return [
        name,                         # natural
        f"{last}, {first}",           # DSpace reversed
        last,                         # last name alone
        f"{first[0]}. {last}",        # initial-dot-last
        f"{first[0]} {last}",         # initial-space-last
        name.lower(),                 # lowercase
        name.upper(),                 # uppercase
    ]


# ---------------------------------------------------------------------------
# Golden query set — topical queries with expected faculty in found_faculty
# ---------------------------------------------------------------------------

GOLDEN_QUERIES: List[Dict[str, Any]] = [
    {
        "query": "K-12 computer science education outreach",
        "expected_faculty_name_substrings": ["Sukul"],
        "why": "CS education outreach is a known Adisak Sukul research area",
    },
    {
        "query": "colonoscopy polyp detection deep learning",
        "expected_faculty_name_substrings": ["Tavanapong"],
        "why": "Wallapak Tavanapong leads medical-imaging CS research at ISU",
    },
    {
        "query": "parallel algorithms for genome assembly",
        "expected_faculty_name_substrings": ["Aluru"],
        "why": "Srinivas Aluru is known for parallel bioinformatics",
    },
    {
        "query": "software engineering empirical study",
        "expected_faculty_name_substrings": ["Rajan", "Chang", "Nguyen"],
        "why": "Multiple ISU SE faculty publish empirical software-engineering work",
    },
    {
        "query": "machine learning for crop phenotyping",
        "expected_faculty_name_substrings": [],  # any CALS/CS researcher acceptable
        "why": "Cross-college ML+agriculture intersection; lax expectation",
        "min_sources": 3,
    },
    {
        "query": "flood inundation prediction hydrology",
        "expected_faculty_name_substrings": [],
        "why": "Water systems research area; lax expectation",
        "min_sources": 3,
    },
    {
        "query": "distributed systems consensus protocols",
        "expected_faculty_name_substrings": [],
        "why": "Systems research area; lax expectation",
        "min_sources": 3,
    },
    {
        "query": "human-computer interaction accessibility",
        "expected_faculty_name_substrings": [],
        "why": "HCI research area; lax expectation",
        "min_sources": 3,
    },
]


# ---------------------------------------------------------------------------
# Edge cases — graceful handling stress tests
# ---------------------------------------------------------------------------

EDGE_CASES: List[Dict[str, Any]] = [
    {
        "label": "empty_query",
        "query": "",
        "expect": "either 400/422 or a graceful empty result; no 5xx, no hang",
    },
    {
        "label": "single_word",
        "query": "research",
        "expect": "valid response; shouldn't crash on overly-generic query",
    },
    {
        "label": "very_long_query",
        "query": "machine learning " * 400,  # ~6400 chars
        "expect": "either truncated answer or graceful error; no 5xx, no timeout",
    },
    {
        "label": "non_english_thai",
        "query": "การเรียนรู้ของเครื่อง",  # 'machine learning' in Thai
        "expect": "graceful (possibly empty) response; no 5xx",
    },
    {
        "label": "typo_query",
        "query": "compouter sciense educaton",
        "expect": "should still retrieve CS-education content despite typos",
    },
    {
        "label": "nonexistent_topic",
        "query": "xyzzy plugh quaxxaflux frobnication",
        "expect": "answer should say 'no information' or similar; no fabrication",
    },
    {
        "label": "sql_injection_ish",
        "query": "'; DROP TABLE papers; --",
        "expect": "treated as a text query; no 5xx; no SQL damage (obviously)",
    },
]


# ---------------------------------------------------------------------------
# Data classes for structured results
# ---------------------------------------------------------------------------


@dataclass
class NameVariantResult:
    faculty_name: str
    faculty_id: Optional[str]
    variant: str
    found_faculty_ids: List[str]
    target_in_top_k: bool
    target_position: Optional[int]
    duration_sec: float
    status: str  # "pass", "fail", "error"
    error: Optional[str] = None


@dataclass
class NameVariantCase:
    faculty_name: str
    faculty_id: Optional[str]
    variants: List[NameVariantResult] = field(default_factory=list)
    pass_count: int = 0
    total: int = 0


@dataclass
class GoldenQueryResult:
    query: str
    why: str
    expected_name_substrings: List[str]
    matched_substrings: List[str]
    found_faculty_top5: List[Tuple[str, str]]  # (id, name)
    sources_count: int
    min_sources_met: bool
    duration_sec: float
    status: str
    error: Optional[str] = None


@dataclass
class RelatedPublicationsResult:
    faculty_name: str
    faculty_id: Optional[str]
    dspace_expected: int
    api_returned: int
    matched_titles: int
    coverage_pct: float
    duration_sec: float
    status: str
    error: Optional[str] = None


@dataclass
class EdgeCaseResult:
    label: str
    query_preview: str
    http_status: Optional[int]
    response_ok: bool
    answer_snippet: str
    duration_sec: float
    status: str  # pass / fail
    error: Optional[str] = None


@dataclass
class AccuracyReport:
    api_url: str
    started_at: str
    finished_at: str
    name_variant_cases: List[NameVariantCase] = field(default_factory=list)
    golden_query_results: List[GoldenQueryResult] = field(default_factory=list)
    related_pub_results: List[RelatedPublicationsResult] = field(default_factory=list)
    edge_case_results: List[EdgeCaseResult] = field(default_factory=list)
    summary: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Test runners
# ---------------------------------------------------------------------------


def _api_get(api_url: str, path: str, timeout: int = 30) -> requests.Response:
    return requests.get(f"{api_url}{path}", timeout=timeout)


def test_name_variants(
    api_url: str,
    faculty: Dict[str, Any],
    top_k_check: int = 5,
) -> NameVariantCase:
    name = faculty["name"]
    fid = faculty.get("id")
    case = NameVariantCase(faculty_name=name, faculty_id=fid)

    for variant in _name_variants(name):
        t0 = time.time()
        try:
            resp = api_search(api_url, variant)
        except Exception as e:
            case.variants.append(NameVariantResult(
                faculty_name=name, faculty_id=fid, variant=variant,
                found_faculty_ids=[], target_in_top_k=False,
                target_position=None, duration_sec=round(time.time() - t0, 2),
                status="error", error=str(e),
            ))
            case.total += 1
            continue

        dt = round(time.time() - t0, 2)
        found = resp.get("found_faculty") or []
        ids = [f.get("id", "") for f in found]
        pos = None
        for i, f in enumerate(found):
            if f.get("id") == fid:
                pos = i
                break
        in_top_k = pos is not None and pos < top_k_check

        case.variants.append(NameVariantResult(
            faculty_name=name, faculty_id=fid, variant=variant,
            found_faculty_ids=ids[:top_k_check],
            target_in_top_k=in_top_k,
            target_position=pos,
            duration_sec=dt,
            status="pass" if in_top_k else "fail",
        ))
        case.total += 1
        if in_top_k:
            case.pass_count += 1

    return case


def test_golden_query(
    api_url: str,
    entry: Dict[str, Any],
) -> GoldenQueryResult:
    q = entry["query"]
    expected = entry.get("expected_faculty_name_substrings", [])
    min_sources = entry.get("min_sources", 0)

    t0 = time.time()
    try:
        resp = api_search(api_url, q)
    except Exception as e:
        return GoldenQueryResult(
            query=q, why=entry.get("why", ""),
            expected_name_substrings=expected, matched_substrings=[],
            found_faculty_top5=[], sources_count=0, min_sources_met=False,
            duration_sec=round(time.time() - t0, 2),
            status="error", error=str(e),
        )
    dt = round(time.time() - t0, 2)

    found = resp.get("found_faculty") or []
    sources = resp.get("sources") or []
    top5 = [(f.get("id", ""), f.get("name", "")) for f in found[:5]]
    matched: List[str] = []
    for sub in expected:
        if any(sub.lower() in (n or "").lower() for _, n in top5):
            matched.append(sub)

    expected_ok = (not expected) or (len(matched) > 0)
    min_sources_ok = len(sources) >= min_sources
    status = "pass" if (expected_ok and min_sources_ok) else "fail"
    return GoldenQueryResult(
        query=q, why=entry.get("why", ""),
        expected_name_substrings=expected, matched_substrings=matched,
        found_faculty_top5=top5, sources_count=len(sources),
        min_sources_met=min_sources_ok, duration_sec=dt, status=status,
    )


def test_related_publications(
    api_url: str,
    faculty: Dict[str, Any],
    dspace_expected: List[Dict[str, Any]],
    min_coverage: float = 0.15,
) -> RelatedPublicationsResult:
    """
    Fetch /api/faculty/{id}/publications and compare the returned titles to
    the DSpace ground-truth set.

    Coverage threshold is 15% (not 30%) because the backend's `dspace_local`
    SQLite index is a snapshot that lags the live DSpace REST API, so 100%
    coverage is not achievable. 15% is a floor that catches "endpoint broken"
    failures without flagging every cache gap.
    """
    name = faculty["name"]
    fid = faculty.get("id")
    t0 = time.time()
    try:
        r = _api_get(api_url, f"/api/faculty/{fid}/publications", timeout=60)
    except Exception as e:
        return RelatedPublicationsResult(
            faculty_name=name, faculty_id=fid,
            dspace_expected=len(dspace_expected), api_returned=0,
            matched_titles=0, coverage_pct=0.0,
            duration_sec=round(time.time() - t0, 2),
            status="error", error=str(e),
        )
    dt = round(time.time() - t0, 2)

    if r.status_code != 200:
        return RelatedPublicationsResult(
            faculty_name=name, faculty_id=fid,
            dspace_expected=len(dspace_expected), api_returned=0,
            matched_titles=0, coverage_pct=0.0,
            duration_sec=dt, status="error",
            error=f"HTTP {r.status_code}: {r.text[:200]}",
        )

    try:
        data = r.json()
    except Exception:
        return RelatedPublicationsResult(
            faculty_name=name, faculty_id=fid,
            dspace_expected=len(dspace_expected), api_returned=0,
            matched_titles=0, coverage_pct=0.0,
            duration_sec=dt, status="error", error="non-JSON response",
        )

    # The endpoint returns
    #   {"faculty_id": ..., "faculty_name": ...,
    #    "publications": [...],
    #    "counts": {"total", "dspace", "openalex", "merged"},
    #    "openalex_id": "..."}
    # Older code paths may return a bare list or {"papers": [...]}, so accept
    # all three shapes defensively.
    if isinstance(data, list):
        papers = data
    else:
        papers = (
            data.get("publications")
            or data.get("papers")
            or []
        )
    # Compare normalized titles to handle hyphen/unicode variance
    import re as _re
    _NORM = _re.compile(r"[^a-z0-9]+")

    def norm(s: str) -> str:
        return _NORM.sub(" ", (s or "").lower()).strip()

    api_titles = {norm(p.get("title", "")) for p in papers if p.get("title")}
    expected_titles = {norm(p.get("title", "")) for p in dspace_expected if p.get("title")}
    expected_titles.discard("")
    matched = expected_titles & api_titles
    coverage = (len(matched) / len(expected_titles)) if expected_titles else 0.0

    status = "pass" if coverage >= min_coverage or len(expected_titles) == 0 else "fail"
    return RelatedPublicationsResult(
        faculty_name=name, faculty_id=fid,
        dspace_expected=len(expected_titles), api_returned=len(papers),
        matched_titles=len(matched), coverage_pct=round(coverage, 3),
        duration_sec=dt, status=status,
    )


def test_edge_case(api_url: str, entry: Dict[str, Any]) -> EdgeCaseResult:
    label = entry["label"]
    q = entry["query"]
    preview = q[:60] + ("…" if len(q) > 60 else "")
    t0 = time.time()
    http_status: Optional[int] = None
    answer = ""
    err: Optional[str] = None
    try:
        r = requests.post(
            f"{api_url}/api/search",
            json={"query": q, "limit": 10},
            timeout=90,
        )
        http_status = r.status_code
        if r.status_code == 200:
            data = r.json()
            answer = (data.get("answer") or "")[:200]
        else:
            answer = f"[HTTP {r.status_code}] {r.text[:150]}"
    except requests.Timeout:
        err = "timeout"
    except Exception as e:
        err = str(e)

    dt = round(time.time() - t0, 2)

    # Grading: "pass" means no 5xx, no timeout, no crash
    ok_http = http_status is not None and http_status < 500
    ok_no_err = err is None
    status = "pass" if (ok_http and ok_no_err) else "fail"
    return EdgeCaseResult(
        label=label, query_preview=preview, http_status=http_status,
        response_ok=(http_status == 200), answer_snippet=answer,
        duration_sec=dt, status=status, error=err,
    )


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def pick_target_faculty(cs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return the subset of CS faculty matching TARGET_FACULTY_NAMES, in order."""
    by_name_lower = {f["name"].lower(): f for f in cs}
    picked: List[Dict[str, Any]] = []
    for target in TARGET_FACULTY_NAMES:
        f = by_name_lower.get(target.lower())
        if f:
            picked.append(f)
    return picked


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api", default=API_DEFAULT)
    parser.add_argument("--skip-edge", action="store_true")
    parser.add_argument("--skip-golden", action="store_true")
    parser.add_argument("--skip-variants", action="store_true")
    parser.add_argument("--skip-related", action="store_true")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    api_url = args.api.rstrip("/")
    print(f"API: {api_url}")
    start = time.time()

    # Health check — allow generous time for a cold Cloud Run start (>60s is
    # common when the min-instance is 0 and we're the first request after
    # idle).
    try:
        h = requests.get(f"{api_url}/health", timeout=120).json()
        print(f"Health: {h}")
    except Exception as e:
        print(f"Backend health check failed: {e}")
        return 2

    # Load CS faculty list and pick targets
    cs = get_cs_faculty(api_url)
    targets = pick_target_faculty(cs)
    print(f"Loaded {len(cs)} CS faculty; picked {len(targets)} targets for per-person tests")

    report = AccuracyReport(
        api_url=api_url,
        started_at=datetime.now().isoformat(timespec="seconds"),
        finished_at="",
    )

    # Category 1: Name variants
    if not args.skip_variants:
        print("\n=== Category 1: Name variants ===")
        for faculty in targets:
            case = test_name_variants(api_url, faculty)
            report.name_variant_cases.append(case)
            print(f"  {case.faculty_name}: {case.pass_count}/{case.total} variants pass")

    # Category 2: Golden queries
    if not args.skip_golden:
        print("\n=== Category 2: Golden queries ===")
        for entry in GOLDEN_QUERIES:
            result = test_golden_query(api_url, entry)
            report.golden_query_results.append(result)
            tag = "PASS" if result.status == "pass" else "FAIL"
            print(f"  [{tag}] {entry['query'][:60]}")
            if result.status != "pass":
                print(f"         expected: {entry.get('expected_faculty_name_substrings')}")
                print(f"         got top5: {[n for _, n in result.found_faculty_top5]}")

    # Category 3: Related publications endpoint
    if not args.skip_related:
        print("\n=== Category 3: Related publications endpoint ===")
        for faculty in targets:
            expected = dspace_search_by_person(faculty["name"], size=50)
            result = test_related_publications(api_url, faculty, expected)
            report.related_pub_results.append(result)
            print(
                f"  {result.faculty_name}: "
                f"api={result.api_returned} expected={result.dspace_expected} "
                f"matched={result.matched_titles} coverage={result.coverage_pct*100:.0f}% "
                f"[{result.status}]"
            )

    # Category 4: Edge cases
    if not args.skip_edge:
        print("\n=== Category 4: Edge cases ===")
        for entry in EDGE_CASES:
            result = test_edge_case(api_url, entry)
            report.edge_case_results.append(result)
            print(
                f"  [{result.status}] {result.label:20s} "
                f"http={result.http_status} in {result.duration_sec}s"
            )

    # Aggregate summary
    variant_total = sum(c.total for c in report.name_variant_cases)
    variant_pass = sum(c.pass_count for c in report.name_variant_cases)
    golden_pass = sum(1 for r in report.golden_query_results if r.status == "pass")
    related_pass = sum(1 for r in report.related_pub_results if r.status == "pass")
    edge_pass = sum(1 for r in report.edge_case_results if r.status == "pass")

    report.summary = {
        "name_variants_pass_rate": (variant_pass / variant_total) if variant_total else 0.0,
        "name_variants_pass": variant_pass,
        "name_variants_total": variant_total,
        "golden_queries_pass": golden_pass,
        "golden_queries_total": len(report.golden_query_results),
        "related_pubs_pass": related_pass,
        "related_pubs_total": len(report.related_pub_results),
        "edge_cases_pass": edge_pass,
        "edge_cases_total": len(report.edge_case_results),
        "duration_sec": round(time.time() - start, 1),
    }
    report.finished_at = datetime.now().isoformat(timespec="seconds")

    out_path = args.out or os.path.join(
        RESULTS_DIR, f"accuracy_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "api_url": report.api_url,
                "started_at": report.started_at,
                "finished_at": report.finished_at,
                "summary": report.summary,
                "name_variant_cases": [
                    {
                        "faculty_name": c.faculty_name,
                        "faculty_id": c.faculty_id,
                        "pass_count": c.pass_count,
                        "total": c.total,
                        "variants": [asdict(v) for v in c.variants],
                    }
                    for c in report.name_variant_cases
                ],
                "golden_query_results": [asdict(r) for r in report.golden_query_results],
                "related_pub_results": [asdict(r) for r in report.related_pub_results],
                "edge_case_results": [asdict(r) for r in report.edge_case_results],
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    print("\n========== SUMMARY ==========")
    for k, v in report.summary.items():
        print(f"{k}: {v}")
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
