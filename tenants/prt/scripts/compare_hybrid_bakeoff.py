"""Focused bake-off scorer: Opus+Typhoon hybrid vs Typhoon-alone vs Opus-alone.

All three are scored by Jaccard 3-gram vs Gemini-Vertex oracle, using the same
tokenizer and shingle function as `compare_ocr_5way.py` (deliberately identical
so the new pipeline's numbers are directly comparable to the canonical
1,008-doc 5-way ranking).

Universe: docs that have ALL FOUR pipelines' output (hybrid, typhoon, opus, gemini).
This is the population on which the hybrid-vs-baselines question is well-defined.

Usage:
    py -3 tenants/prt/scripts/compare_hybrid_bakeoff.py
    py -3 tenants/prt/scripts/compare_hybrid_bakeoff.py --report-md tenants/prt/analysis/hybrid_bakeoff_<TS>.md
"""
from __future__ import annotations

import argparse
import re
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

REPO = Path(__file__).resolve().parents[3]
VAULT = REPO / "tenants" / "prt" / "data" / "vault"

DIRS = {
    "gemini":  VAULT / "papers_text_gemini",                  # oracle
    "typhoon": VAULT / "papers_text_typhoon",                 # baseline 1
    "opus":    VAULT / "papers_text_opus",                    # baseline 2
    "hybrid":  VAULT / "papers_text_opus_typhoon_hybrid",     # the candidate
}

# Tokenizer / shingle: byte-for-byte identical to compare_ocr_5way.py
_word_re = re.compile(r"[a-zA-Z0-9฀-๿]+", re.UNICODE)


def shard_for(doc_id: str) -> str:
    return doc_id[-2:] if len(doc_id) >= 2 else "00"


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def word_tokens(text: str) -> list[str]:
    return [t.lower() for t in _word_re.findall(text) if t.strip()]


def shingle_3grams(tokens: list[str]) -> set[tuple[str, str, str]]:
    if len(tokens) < 3:
        return set()
    return set(zip(tokens, tokens[1:], tokens[2:]))


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def collect_doc_ids(out_dir: Path, min_bytes: int = 50) -> set[str]:
    ids = set()
    for p in out_dir.rglob("*.txt"):
        if p.is_file() and p.stat().st_size > min_bytes:
            ids.add(p.stem)
    return ids


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--report-md", type=str, default=None,
                    help="If set, write a markdown report to this path.")
    args = ap.parse_args()

    out_lines: list[str] = []
    def w(s: str = "") -> None:
        out_lines.append(s)
        print(s)

    print(f"[{time.strftime('%H:%M:%S')}] Collecting doc_ids from each pipeline ...")
    pipeline_ids: dict[str, set[str]] = {}
    for name, d in DIRS.items():
        ids = collect_doc_ids(d)
        pipeline_ids[name] = ids
        print(f"  {name:<8} {len(ids):>7,} docs in {d.name}")

    # The candidate (hybrid) is the smallest set. Limit to 4-way intersection.
    universe = (
        pipeline_ids["hybrid"]
        & pipeline_ids["typhoon"]
        & pipeline_ids["opus"]
        & pipeline_ids["gemini"]
    )
    print(f"\n  4-way intersection (hybrid universe): {len(universe):,} docs")
    if not universe:
        print("FATAL: empty universe; nothing to score.")
        sys.exit(1)

    # Per-doc Jaccard table: (hybrid vs gemini, typhoon vs gemini, opus vs gemini)
    per_doc: list[dict] = []
    print(f"[{time.strftime('%H:%M:%S')}] Computing per-doc Jaccards ...")
    for did in sorted(universe):
        sh = shard_for(did)
        texts = {n: read_text(DIRS[n] / sh / f"{did}.txt") for n in DIRS}
        toks = {n: word_tokens(texts[n]) for n in DIRS}
        sh3 = {n: shingle_3grams(toks[n]) for n in DIRS}
        per_doc.append({
            "doc_id": did,
            "hybrid_vs_gemini":  jaccard(sh3["hybrid"],  sh3["gemini"]),
            "typhoon_vs_gemini": jaccard(sh3["typhoon"], sh3["gemini"]),
            "opus_vs_gemini":    jaccard(sh3["opus"],    sh3["gemini"]),
            "hybrid_chars":  len(texts["hybrid"]),
            "typhoon_chars": len(texts["typhoon"]),
            "opus_chars":    len(texts["opus"]),
            "gemini_chars":  len(texts["gemini"]),
        })

    # ---- Aggregates ----
    def stats(key: str) -> tuple[float, float, float, float]:
        vals = [r[key] for r in per_doc]
        return (
            statistics.mean(vals),
            statistics.median(vals),
            min(vals),
            max(vals),
        )

    hyb_mean, hyb_med, hyb_min, hyb_max = stats("hybrid_vs_gemini")
    typ_mean, typ_med, typ_min, typ_max = stats("typhoon_vs_gemini")
    opu_mean, opu_med, opu_min, opu_max = stats("opus_vs_gemini")

    # Per-doc delta: hybrid vs typhoon (the headline ablation)
    deltas = [r["hybrid_vs_gemini"] - r["typhoon_vs_gemini"] for r in per_doc]
    wins  = sum(1 for d in deltas if d > 0.005)
    losses = sum(1 for d in deltas if d < -0.005)
    ties = sum(1 for d in deltas if -0.005 <= d <= 0.005)
    delta_mean = statistics.mean(deltas)
    delta_med = statistics.median(deltas)

    # ---- Report ----
    w(f"# Hybrid OCR Bake-off — Opus+Typhoon vs Typhoon-alone vs Opus-alone")
    w(f"_Generated {time.strftime('%Y-%m-%d %H:%M:%S')} on n = {len(per_doc):,} docs (4-way intersection)_")
    w()
    w("## Headline")
    w()
    w("| Pipeline | Mean Jaccard vs Gemini | Median | Min | Max |")
    w("|---|---|---|---|---|")
    w(f"| **opus_typhoon_hybrid** | **{hyb_mean:.4f}** | {hyb_med:.4f} | {hyb_min:.4f} | {hyb_max:.4f} |")
    w(f"| typhoon (existing baseline) | {typ_mean:.4f} | {typ_med:.4f} | {typ_min:.4f} | {typ_max:.4f} |")
    w(f"| opus (existing baseline)    | {opu_mean:.4f} | {opu_med:.4f} | {opu_min:.4f} | {opu_max:.4f} |")
    w()

    w("## Headline ablation: hybrid - typhoon (per doc)")
    w()
    w(f"- Mean delta: **{delta_mean:+.4f}** | Median delta: **{delta_med:+.4f}**")
    w(f"- Wins (delta > +0.005):  **{wins:>3}/{len(per_doc)}** ({100.0*wins/len(per_doc):.0f}%)")
    w(f"- Losses (delta < -0.005): **{losses:>3}/{len(per_doc)}** ({100.0*losses/len(per_doc):.0f}%)")
    w(f"- Ties (|delta| <= 0.005): **{ties:>3}/{len(per_doc)}** ({100.0*ties/len(per_doc):.0f}%)")
    w()

    # Verdict
    if delta_mean > 0.01 and wins > losses * 1.5:
        verdict = "✅ **Hybrid materially beats Typhoon-alone.** Recommend production deployment for born-image PRT corpus."
    elif delta_mean > 0:
        verdict = "🟡 **Hybrid marginally beats Typhoon-alone.** Worth deploying if the cost is acceptable; gain is small."
    elif abs(delta_mean) < 0.01:
        verdict = "⚪ **Hybrid ties Typhoon-alone.** Not worth the Claude cost for this corpus."
    else:
        verdict = "❌ **Hybrid loses to Typhoon-alone.** Claude correction is introducing more errors than it catches. Revisit the skill or abandon."
    w(f"## Verdict")
    w()
    w(verdict)
    w()

    # Per-doc table for transparency
    w("## Per-doc Jaccard breakdown")
    w()
    w("| doc_id | hybrid | typhoon | opus | hybrid - typhoon | sign |")
    w("|---|---|---|---|---|---|")
    for r in sorted(per_doc, key=lambda x: -(x["hybrid_vs_gemini"] - x["typhoon_vs_gemini"])):
        d = r["hybrid_vs_gemini"] - r["typhoon_vs_gemini"]
        sign = "🟢 win" if d > 0.005 else ("🔴 loss" if d < -0.005 else "⚪ tie")
        w(f"| {r['doc_id']} | {r['hybrid_vs_gemini']:.4f} | {r['typhoon_vs_gemini']:.4f} | {r['opus_vs_gemini']:.4f} | {d:+.4f} | {sign} |")
    w()

    # Length comparison (sanity check)
    w("## Length (mean chars per doc)")
    w()
    w("| Pipeline | mean chars | median chars |")
    w("|---|---|---|")
    for n in ["gemini", "hybrid", "typhoon", "opus"]:
        ch = [r[f"{n}_chars"] for r in per_doc]
        w(f"| {n} | {int(statistics.mean(ch)):,} | {int(statistics.median(ch)):,} |")
    w()

    if args.report_md:
        out_path = Path(args.report_md)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("\n".join(out_lines), encoding="utf-8")
        print(f"\n[{time.strftime('%H:%M:%S')}] Wrote markdown report -> {out_path}")


if __name__ == "__main__":
    main()
