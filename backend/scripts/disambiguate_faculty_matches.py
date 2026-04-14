"""
Disambiguate faculty-OpenAlex matches that have low confidence (0.55).

Uses the local openalex_isu_authors.json dump to rebuild candidate lists
for each faculty, then scores candidates using faculty context
(department, rank, research_interests, institution, works_count).

Processes the FIRST 100 ambiguous entries as a proof of concept. Writes
decisions to backend/data/faculty_disambiguated.json.

Run:
    python backend/scripts/disambiguate_faculty_matches.py
    python backend/scripts/disambiguate_faculty_matches.py --limit 100
    python backend/scripts/disambiguate_faculty_matches.py --limit 0   # all
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
FACULTY_JSON = BACKEND / "data" / "faculty.json"
AUTHORS_DUMP = BACKEND / "data" / "openalex_isu_authors.json"
MATCH_IN = BACKEND / "data" / "faculty_openalex_match.json"
OUT = BACKEND / "data" / "faculty_disambiguated.json"

# Expected works_count ranges by academic rank
# These are coarse, used only as a tie-breaking signal, never a hard filter.
RANK_WORKS_RANGE: Dict[str, Tuple[int, int]] = {
    "distinguished professor": (60, 10000),
    "university professor": (60, 10000),
    "professor": (40, 10000),
    "associate professor": (20, 400),
    "assistant professor": (5, 150),
    "assistant teaching professor": (0, 60),
    "teaching professor": (0, 80),
    "associate teaching professor": (0, 70),
    "lecturer": (0, 50),
    "adjunct": (0, 100),
    "instructor": (0, 40),
    "postdoc": (0, 30),
    "postdoctoral": (0, 30),
    "research scientist": (5, 500),
    "senior scientist": (10, 500),
    "graduate student": (0, 20),
    "phd student": (0, 15),
}


def normalize_name(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    if "," in n:
        parts = [p.strip() for p in n.split(",", 1)]
        if len(parts) == 2:
            n = f"{parts[1]} {parts[0]}"
    n = re.sub(r"[^A-Za-z\s\-]", "", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n.lower()


def rank_bucket(rank: Optional[str]) -> Optional[Tuple[int, int]]:
    if not rank:
        return None
    r = rank.lower().strip()
    # Try longest-matching key first to avoid "professor" capturing
    # "assistant teaching professor".
    for key in sorted(RANK_WORKS_RANGE.keys(), key=len, reverse=True):
        if key in r:
            return RANK_WORKS_RANGE[key]
    return None


def is_iowa_state(inst_list: List[str]) -> bool:
    if not inst_list:
        return False
    for i in inst_list:
        if not i:
            continue
        low = i.lower()
        if "iowa state" in low:
            return True
    return False


def build_candidate_index(authors: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Map normalized name -> list of UNIQUE author records (dedup by id)."""
    idx: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    seen_per_key: Dict[str, set] = defaultdict(set)

    def add(key: str, author: Dict[str, Any]) -> None:
        aid = author.get("id")
        if not aid:
            return
        if aid in seen_per_key[key]:
            return
        seen_per_key[key].add(aid)
        idx[key].append(author)

    for a in authors:
        name = a.get("display_name") or ""
        add(normalize_name(name), a)
        for alt in a.get("display_name_alternatives") or []:
            add(normalize_name(alt), a)

    return idx


def score_candidate(
    candidate: Dict[str, Any],
    faculty_name: str,
    faculty_rank: Optional[str],
    faculty_dept: Optional[str],
) -> Tuple[float, List[str]]:
    """Return (score, reasons[]). Higher is better. Range roughly 0..12."""
    score = 0.0
    reasons: List[str] = []

    # Signal 1: Exact display_name match (after stripping middle initials)
    cand_name = (candidate.get("display_name") or "").strip()
    if cand_name.lower() == faculty_name.lower():
        score += 1.5
        reasons.append("exact display_name match")

    # Signal 2: Iowa State in last_known_institutions -> STRONG but not dominant
    insts = candidate.get("last_known_institutions") or []
    if is_iowa_state(insts):
        score += 3.0
        reasons.append("last_known_institutions includes Iowa State")
    elif insts:
        # Candidate has a known institution and it's NOT Iowa State → penalty
        score -= 1.0
        reasons.append(f"last_known_institutions={insts[:2]} (not Iowa State)")
    else:
        # No last-known-institution — neutral (common case)
        reasons.append("no last_known_institutions")

    # Signal 3: Works count in rank-appropriate range — WEIGHTED heavily
    # because rank mismatch is a strong signal the profile is wrong person.
    works = candidate.get("works_count") or 0
    bucket = rank_bucket(faculty_rank)
    if bucket:
        lo, hi = bucket
        if lo <= works <= hi:
            score += 2.0
            reasons.append(f"works_count={works} matches rank '{faculty_rank}' range {lo}-{hi}")
        elif works < lo:
            # Way fewer works than expected -> almost certainly wrong person
            # (e.g., Professor with only 2 works)
            shortfall = (lo - works) / max(lo, 1)
            penalty = 2.0 * min(shortfall, 1.0) + 0.5
            score -= penalty
            reasons.append(
                f"works_count={works} BELOW rank '{faculty_rank}' range {lo}-{hi} "
                f"(penalty {penalty:.1f})"
            )
        else:
            score -= 0.3
            reasons.append(f"works_count={works} above rank '{faculty_rank}' range {lo}-{hi}")
    else:
        # No rank info — use coarse "profile looks substantive" heuristic
        if works >= 30:
            score += 0.5
        elif works < 5:
            score -= 0.5
        reasons.append(f"works_count={works}, no rank info")

    # Signal 4: h-index reasonableness
    h = candidate.get("h_index") or 0
    if h >= 10:
        score += 0.7
        reasons.append(f"h_index={h}")
    elif h >= 5:
        score += 0.3
        reasons.append(f"h_index={h}")
    elif h == 0 and works > 0:
        score -= 0.3
        reasons.append(f"h_index=0 despite works={works}")

    # Signal 5: ORCID present -> real identity
    if candidate.get("orcid"):
        score += 0.3
        reasons.append("has ORCID")

    # Signal 6: Non-trivial cited_by_count (not a phantom profile)
    cited = candidate.get("cited_by_count") or 0
    if cited >= 500:
        score += 0.5
    elif cited >= 50:
        score += 0.3
    elif cited == 0:
        score -= 0.5
        reasons.append("cited_by_count=0")

    return score, reasons


def disambiguate(
    entry: Dict[str, Any],
    faculty_record: Dict[str, Any],
    idx: Dict[str, List[Dict[str, Any]]],
) -> Dict[str, Any]:
    name = entry["name"]
    norm = normalize_name(name)
    candidates = idx.get(norm, [])

    faculty_rank = faculty_record.get("rank")
    faculty_dept = faculty_record.get("department")

    result: Dict[str, Any] = {
        "faculty_id": entry["faculty_id"],
        "faculty_name": name,
        "department": faculty_dept,
        "rank": faculty_rank,
        "unique_candidates": len(candidates),
        "chosen_openalex_id": None,
        "chosen_display_name": None,
        "rationale": "",
        "confidence_after": 0.0,
        "status": "unresolved",
        "candidate_scores": [],
    }

    if not candidates:
        result["rationale"] = "No candidates found in OpenAlex ISU authors dump"
        result["status"] = "no_candidates"
        return result

    # If only 1 unique candidate (dedup collapsed alt-name duplicates)
    if len(candidates) == 1:
        c = candidates[0]
        result["chosen_openalex_id"] = c["id"]
        result["chosen_display_name"] = c.get("display_name")
        iowa = is_iowa_state(c.get("last_known_institutions") or [])
        result["confidence_after"] = 0.92 if iowa else 0.85
        result["rationale"] = (
            "Only 1 unique OpenAlex profile matches this name after dedup "
            "(original 'candidates' count was inflated by alternative-name indexing)."
        )
        if iowa:
            result["rationale"] += " Last known institution is Iowa State."
        result["status"] = "resolved_trivial"
        result["candidate_scores"] = [
            {"openalex_id": c["id"], "display_name": c.get("display_name"), "score": 999.0}
        ]
        return result

    # Truly ambiguous: score each candidate
    scored = []
    for c in candidates:
        score, reasons = score_candidate(c, name, faculty_rank, faculty_dept)
        scored.append({
            "openalex_id": c["id"],
            "display_name": c.get("display_name"),
            "works_count": c.get("works_count") or 0,
            "h_index": c.get("h_index") or 0,
            "last_known_institutions": c.get("last_known_institutions") or [],
            "score": round(score, 2),
            "reasons": reasons,
        })
    # Sort: primary by score (desc), secondary by works_count (desc) so that
    # ties from "both Iowa State, both exact name" are broken by profile size.
    scored.sort(key=lambda x: (-x["score"], -x["works_count"]))
    result["candidate_scores"] = scored

    top = scored[0]
    second = scored[1] if len(scored) > 1 else None
    gap = (top["score"] - second["score"]) if second else top["score"]

    # Decision thresholds
    if top["score"] < 0:
        result["rationale"] = (
            f"Top candidate score {top['score']} is negative — "
            "no candidate looks like a good ISU match."
        )
        result["status"] = "unresolved_no_good_match"
        return result

    if gap < 0.5:
        # Very close by score, but works_count may still disambiguate.
        top_works = top.get("works_count") or 0
        second_works = second.get("works_count") or 0
        top_iowa = is_iowa_state(top["last_known_institutions"])
        second_iowa = is_iowa_state(second["last_known_institutions"]) if second else False

        result["rationale"] = (
            f"Top 2 candidates close by score (gap={gap:.2f}): "
            f"'{top['display_name']}' ({top['score']}, {top_works} works) vs "
            f"'{second['display_name']}' ({second['score']}, {second_works} works)"
        )

        # Tiebreaker 1: Both Iowa State (or both not) AND top has dramatically
        # more works → top is the "main" identity.
        if top_iowa == second_iowa and top_works >= 3 * max(second_works, 1):
            result["chosen_openalex_id"] = top["openalex_id"]
            result["chosen_display_name"] = top["display_name"]
            result["rationale"] += f" Tiebreaker: top has {top_works} vs {second_works} works."
            # If neither has Iowa State, the whole resolution is weaker because
            # all candidates came from the ISU dump via publication-collaborator
            # link only, not current affiliation.
            result["confidence_after"] = 0.7 if top_iowa else 0.6
            result["status"] = "resolved_tiebreak_works"
            return result

        # Tiebreaker 2: Top has Iowa State and second doesn't → Iowa State wins
        # BUT only if top has a credible profile (not 0-2 works when expecting many)
        if top_iowa and not second_iowa:
            # Guard: if top works_count looks like a phantom (<= 3) and the
            # second candidate has substantially more works that still fit
            # the rank range, prefer the second one (likely correct identity
            # with missing ISU affiliation label in OpenAlex).
            bucket = rank_bucket(faculty_rank)
            if (
                top_works <= 3
                and second_works >= 10
                and (bucket is None or bucket[0] <= second_works <= bucket[1])
            ):
                result["chosen_openalex_id"] = second["openalex_id"]
                result["chosen_display_name"] = second["display_name"]
                result["rationale"] += (
                    f" Tiebreaker: top ISU profile is too small ({top_works} works); "
                    f"runner-up has {second_works} works matching expected rank."
                )
                result["confidence_after"] = 0.65
                result["status"] = "resolved_tiebreak_runner_substantive"
                return result
            result["chosen_openalex_id"] = top["openalex_id"]
            result["chosen_display_name"] = top["display_name"]
            result["rationale"] += " Tiebreaker: top has Iowa State affiliation."
            result["confidence_after"] = 0.7
            result["status"] = "resolved_tiebreak_iowa"
            return result

        # Tiebreaker 3: Second has Iowa State and top doesn't — flip to second
        if second_iowa and not top_iowa:
            bucket = rank_bucket(faculty_rank)
            second_fits = bucket is None or (bucket[0] <= second_works <= bucket[1])
            if second_fits:
                result["chosen_openalex_id"] = second["openalex_id"]
                result["chosen_display_name"] = second["display_name"]
                result["rationale"] += " Tiebreaker: runner-up has Iowa State affiliation."
                result["confidence_after"] = 0.7
                result["status"] = "resolved_tiebreak_iowa_flip"
                return result

        result["status"] = "unresolved_ambiguous"
        return result

    # Clear winner
    result["chosen_openalex_id"] = top["openalex_id"]
    result["chosen_display_name"] = top["display_name"]
    result["rationale"] = (
        f"Winner '{top['display_name']}' scored {top['score']} "
        f"(vs runner-up {second['score'] if second else 'n/a'}). "
        + "; ".join(top["reasons"][:3])
    )

    # Confidence based on signal strength
    top_iowa = is_iowa_state(top["last_known_institutions"])
    if top_iowa and gap >= 2.0:
        result["confidence_after"] = 0.92
        result["status"] = "resolved_strong"
    elif top_iowa:
        result["confidence_after"] = 0.85
        result["status"] = "resolved_iowa"
    elif gap >= 2.0:
        result["confidence_after"] = 0.75
        result["status"] = "resolved_gap"
    else:
        result["confidence_after"] = 0.65
        result["status"] = "resolved_weak"

    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Number of ambiguous entries to process. 0 = all (default: 100)",
    )
    args = parser.parse_args()

    # Load inputs
    print(f"Loading {FACULTY_JSON}")
    with FACULTY_JSON.open(encoding="utf-8") as f:
        faculty_records = json.load(f)
    fac_by_id: Dict[str, Dict[str, Any]] = {f["id"]: f for f in faculty_records}

    print(f"Loading {AUTHORS_DUMP}")
    with AUTHORS_DUMP.open(encoding="utf-8") as f:
        authors = json.load(f)
    print(f"  {len(authors)} ISU authors loaded")

    print(f"Loading {MATCH_IN}")
    with MATCH_IN.open(encoding="utf-8") as f:
        matches = json.load(f)

    ambiguous = [
        m for m in matches
        if round(m.get("confidence", 0), 2) == 0.55 and m.get("candidates", 0) > 1
    ]
    print(f"  {len(ambiguous)} ambiguous entries (conf=0.55, candidates>1)")

    target = ambiguous if args.limit == 0 else ambiguous[: args.limit]
    print(f"  processing {len(target)}")

    print("Building candidate index from ISU authors dump...")
    idx = build_candidate_index(authors)
    print(f"  {len(idx)} unique normalized names")

    # Process
    print()
    print("Disambiguating...")
    decisions: List[Dict[str, Any]] = []
    for i, entry in enumerate(target):
        fac = fac_by_id.get(entry["faculty_id"], {})
        result = disambiguate(entry, fac, idx)
        decisions.append(result)
        if (i + 1) % 20 == 0:
            print(f"  {i+1}/{len(target)}")

    # Tally stats
    stats = {
        "processed": len(decisions),
        "resolved": sum(1 for d in decisions if d["chosen_openalex_id"]),
        "unresolved": sum(1 for d in decisions if not d["chosen_openalex_id"]),
    }
    status_breakdown: Dict[str, int] = defaultdict(int)
    for d in decisions:
        status_breakdown[d["status"]] += 1
    stats["status_breakdown"] = dict(status_breakdown)

    avg_conf_after = 0.0
    resolved_confs = [d["confidence_after"] for d in decisions if d["chosen_openalex_id"]]
    if resolved_confs:
        avg_conf_after = round(sum(resolved_confs) / len(resolved_confs), 3)
    stats["avg_confidence_after_resolved"] = avg_conf_after

    # Output: trim candidate_scores to keep file size reasonable
    trimmed = []
    for d in decisions:
        t = dict(d)
        # Keep only top 3 candidates with full reasons
        t["candidate_scores"] = d["candidate_scores"][:3]
        trimmed.append(t)

    out_payload = {"decisions": trimmed, "stats": stats}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as f:
        json.dump(out_payload, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"Wrote {OUT}")
    print(f"Stats: {json.dumps(stats, indent=2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
