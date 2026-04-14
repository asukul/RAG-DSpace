"""
P4 Evaluation Sweep — compare multiple Qdrant collections on a golden query set
using Gemini-as-judge to score retrieval quality.

Produces nDCG@10 + P@10 + MRR for each collection on each query, plus an
aggregate table + per-query drill-down. Writes a structured JSON report to
`tests/results/p4_eval_report_<stamp>.json`.

Usage:
    # Default: local dense-only dspace_fulltext_vertex (fresh rebuild in progress)
    python tests/test_p4_eval_sweep.py

    # Compare multiple collections (local)
    python tests/test_p4_eval_sweep.py \\
        --qdrant http://localhost:6334 \\
        --collections dspace_fulltext_vertex,mit_dspace_vertex

    # Compare local vs remote (same collection name)
    python tests/test_p4_eval_sweep.py \\
        --specs local=http://localhost:6334:dspace_fulltext_vertex,remote=http://35.188.64.146:6333:dspace_fulltext_vertex

    # Use a different primary judge
    python tests/test_p4_eval_sweep.py --judge-model gemini-2.5-pro

    # Include a cross-family judge check (task C)
    python tests/test_p4_eval_sweep.py --cross-judge

The "spec" format for multi-collection comparison is:
    name=URL:collection[,name=URL:collection,...]
For example:
    dense=http://localhost:6334:dspace_fulltext_vertex,\\
    nomic=http://35.188.64.146:6333:dspace_fulltext_nomic,\\
    abstract=http://35.188.64.146:6333:dspace_chunks
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

HERE = Path(__file__).resolve().parent
RESULTS_DIR = HERE / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Golden query set. Queries span broad academic topics with known ISU strengths.
# Each query gets ONE expected topical keyword string which the judge uses as
# a soft relevance anchor; the judge ultimately decides 0-3 relevance on its
# own, so the "expected_topic" is just a hint in the judge prompt.
GOLDEN_QUERIES = [
    {"query": "K-12 computer science education outreach programs", "expected_topic": "K-12 CS education / outreach"},
    {"query": "colonoscopy polyp detection deep learning", "expected_topic": "medical imaging AI / colonoscopy"},
    {"query": "parallel algorithms for genome assembly", "expected_topic": "parallel bioinformatics / genome assembly"},
    {"query": "software engineering empirical study practitioners", "expected_topic": "empirical software engineering"},
    {"query": "machine learning for crop phenotyping plant stress", "expected_topic": "ML-based phenotyping / plant breeding"},
    {"query": "flood inundation prediction hydrology", "expected_topic": "flood modeling / water hydrology"},
    {"query": "distributed systems consensus protocols Byzantine", "expected_topic": "distributed systems / consensus"},
    {"query": "human-computer interaction accessibility users disability", "expected_topic": "HCI / accessibility"},
    {"query": "wireless sensor network energy efficiency", "expected_topic": "wireless sensor networks"},
    {"query": "formal verification model checking concurrent programs", "expected_topic": "formal verification / model checking"},
    {"query": "swine pig nutrition feed efficiency", "expected_topic": "animal science / swine nutrition"},
    {"query": "soybean genetic modification transgenic", "expected_topic": "plant genetics / soybean"},
    {"query": "bridge structural health monitoring sensors", "expected_topic": "civil engineering / SHM"},
    {"query": "wind turbine aerodynamic performance", "expected_topic": "wind energy / aerodynamics"},
    {"query": "thesis advisor adisak sukul data science", "expected_topic": "Sukul / data science theses"},
    {"query": "Tavanapong medical imaging video analysis", "expected_topic": "Tavanapong / video analysis"},
    {"query": "Hridesh Rajan boa software mining", "expected_topic": "Rajan / Boa / software repository mining"},
    {"query": "Srinivas Aluru parallel computing bioinformatics", "expected_topic": "Aluru / parallel bioinformatics"},
    {"query": "Iowa State agricultural extension service farmers", "expected_topic": "ISU Extension / agriculture outreach"},
    {"query": "quantum computing error correction", "expected_topic": "quantum computing"},
]


# ---------------------------------------------------------------------------
# Query-side embedding helper (Vertex text-embedding-005)
# ---------------------------------------------------------------------------


_embed_client = None


def get_embed_client():
    global _embed_client
    if _embed_client is None:
        from google import genai
        _embed_client = genai.Client(vertexai=True, project="rag-dspace", location="us-central1")
    return _embed_client


def embed_query_vertex(query: str) -> List[float]:
    """Vertex text-embedding-005 query-side embedding."""
    from google.genai import types
    client = get_embed_client()
    resp = client.models.embed_content(
        model="text-embedding-005",
        contents=[query],
        config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
    )
    return list(resp.embeddings[0].values)


# ---------------------------------------------------------------------------
# Collection specs
# ---------------------------------------------------------------------------


# --- BM25 query-side helper (loaded lazily, vocab path picked per collection)

_BM25_VOCAB_BY_COLLECTION = {
    "dspace_chunks": "bm25_vocab.json",
    "dspace_fulltext_vertex": "bm25_vocab_vertex.json",
}
_BM25_STOP = set(
    "a an the and or but if while with of to in on at by for from as is are was were "
    "be been being have has had do does did will would could should may might must shall "
    "can this that these those it its their our your we you they them he she his her "
    "i me my us".split()
)
_BM25_TOKEN_RE = __import__("re").compile(r"[A-Za-z][A-Za-z0-9]+")
_bm25_cache: Dict[str, Dict[str, Any]] = {}


def load_bm25_vocab(collection: str) -> Optional[Dict[str, Any]]:
    if collection in _bm25_cache:
        return _bm25_cache[collection]
    fname = _BM25_VOCAB_BY_COLLECTION.get(collection)
    if not fname:
        return None
    path = HERE.parent / "backend" / "data" / fname
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    vocab = {
        "n_docs": int(data.get("n_docs", 0)),
        "avgdl": float(data.get("avgdl", 1.0)),
        "k1": float(data.get("k1", 1.5)),
        "b": float(data.get("b", 0.75)),
        "df": data.get("df", {}),
        "token_to_id": data.get("token_to_id", {}),
    }
    _bm25_cache[collection] = vocab
    return vocab


def build_bm25_query(query: str, vocab: Dict[str, Any]) -> Optional[Tuple[List[int], List[float]]]:
    toks: List[str] = []
    for tok in _BM25_TOKEN_RE.findall(query or ""):
        t = tok.lower()
        if len(t) < 3 or t in _BM25_STOP:
            continue
        toks.append(t)
    if not toks:
        return None
    from collections import Counter
    tf = Counter(toks)
    dl = len(toks)
    k1, b, avgdl, n_docs = vocab["k1"], vocab["b"], vocab["avgdl"], vocab["n_docs"]
    df = vocab["df"]
    token_to_id = vocab["token_to_id"]
    indices: List[int] = []
    values: List[float] = []
    for term, freq in tf.items():
        d = df.get(term)
        if not d:
            continue
        idf = math.log(1 + (n_docs - d + 0.5) / (d + 0.5))
        score = idf * (freq * (k1 + 1)) / (freq + k1 * (1 - b + b * dl / avgdl))
        tid = token_to_id.get(term)
        if tid is None:
            continue
        indices.append(tid)
        values.append(round(score, 4))
    if not indices:
        return None
    return indices, values


@dataclass
class CollectionSpec:
    name: str            # display name (used in reports)
    url: str             # Qdrant URL
    collection: str      # Qdrant collection name
    uses_named_vector: Optional[str] = None   # "dense" for hybrid/named; None = unnamed
    hybrid_probe: Optional[str] = None        # set once at first query: "hybrid" / "dense" / "unnamed"


def parse_specs(spec_str: str) -> List[CollectionSpec]:
    out = []
    for entry in spec_str.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"spec must be name=URL:collection, got {entry}")
        name, rest = entry.split("=", 1)
        idx = rest.rfind(":")
        if idx == -1:
            raise ValueError(f"spec missing collection, got {entry}")
        url = rest[:idx]
        coll = rest[idx + 1:]
        out.append(CollectionSpec(name=name.strip(), url=url.strip(), collection=coll.strip()))
    return out


def _probe_collection(client: QdrantClient, spec: CollectionSpec) -> None:
    """Figure out whether the collection is hybrid / dense-named / unnamed."""
    try:
        info = client.get_collection(spec.collection)
        vectors = info.config.params.vectors
        if isinstance(vectors, dict):
            spec.uses_named_vector = next(iter(vectors.keys()), None)
        else:
            spec.uses_named_vector = ""
        sparse = getattr(info.config.params, "sparse_vectors", None) or {}
        if isinstance(sparse, dict) and "bm25" in sparse:
            spec.hybrid_probe = "hybrid"
        elif spec.uses_named_vector:
            spec.hybrid_probe = "dense"
        else:
            spec.hybrid_probe = "unnamed"
    except Exception:
        spec.uses_named_vector = ""
        spec.hybrid_probe = "unnamed"


def query_collection(
    spec: CollectionSpec, query_text: str, query_vector: List[float], top_k: int = 10
) -> List[Dict[str, Any]]:
    """Issue a query against the collection. Uses hybrid dense+bm25 with RRF
    fusion if the collection has a bm25 sparse vector AND the matching vocab
    file is available. Otherwise falls back to dense-only (named or unnamed).
    """
    client = QdrantClient(url=spec.url, timeout=60)
    if spec.hybrid_probe is None:
        _probe_collection(client, spec)

    if spec.hybrid_probe == "hybrid":
        vocab = load_bm25_vocab(spec.collection)
        sparse = build_bm25_query(query_text, vocab) if vocab else None
        if sparse is not None:
            ids, vals = sparse
            res = client.query_points(
                collection_name=spec.collection,
                prefetch=[
                    qm.Prefetch(query=query_vector, using="dense", limit=max(top_k * 4, 32)),
                    qm.Prefetch(
                        query=qm.SparseVector(indices=ids, values=vals),
                        using="bm25",
                        limit=max(top_k * 4, 32),
                    ),
                ],
                query=qm.FusionQuery(fusion=qm.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
            return _unpack_points(res)

    # Dense-only fallback
    kwargs = dict(
        collection_name=spec.collection,
        query=query_vector,
        limit=top_k,
        with_payload=True,
    )
    if spec.uses_named_vector:
        kwargs["using"] = spec.uses_named_vector
    res = client.query_points(**kwargs)
    return _unpack_points(res)


def _unpack_points(res) -> List[Dict[str, Any]]:
    out = []
    for p in res.points:
        payload = p.payload or {}
        out.append({
            "id": str(p.id),
            "score": float(p.score),
            "uuid": payload.get("uuid", ""),
            "doc_title": payload.get("doc_title", "") or payload.get("title", ""),
            "text": (payload.get("text") or "")[:800],
            "authors": payload.get("authors", []),
        })
    return out


# ---------------------------------------------------------------------------
# Gemini-as-judge
# ---------------------------------------------------------------------------


_judge_clients: Dict[str, Any] = {}


def get_judge(model: str):
    if model not in _judge_clients:
        from google import genai
        _judge_clients[model] = genai.Client(
            vertexai=True, project="rag-dspace", location="us-central1"
        )
    return _judge_clients[model]


JUDGE_PROMPT = """You are a relevance judge scoring a retrieved chunk against a user query.
Rate the chunk on a 0–3 scale:
  3 = highly relevant (directly answers the query or is about the exact topic)
  2 = relevant (shares topic / contains useful partial answer)
  1 = marginally relevant (tangential, mentions keywords without substance)
  0 = irrelevant (off-topic)

Query: {query}
Topic anchor (hint): {topic}

Retrieved chunk:
Title: {title}
Text: {text}

Respond with ONLY the integer (0, 1, 2, or 3). No explanation."""


def judge_chunk(model: str, query: str, topic: str, title: str, text: str) -> int:
    """Return a 0-3 relevance score via Gemini."""
    from google.genai import types
    client = get_judge(model)
    prompt = JUDGE_PROMPT.format(query=query, topic=topic, title=title[:200], text=(text or "")[:800])
    try:
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=16,
            ),
        )
        text_out = (getattr(resp, "text", "") or "").strip()
        # Accept "3", "3.", "3 — whatever"
        for ch in text_out:
            if ch in "0123":
                return int(ch)
        return 0
    except Exception as e:
        print(f"  judge error: {e}", file=sys.stderr)
        return -1


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def ndcg_at_k(relevances: List[int], k: int = 10) -> float:
    """Standard nDCG@k with exponential gain."""
    def dcg(rs):
        return sum((2 ** r - 1) / math.log2(i + 2) for i, r in enumerate(rs))

    rels = [r for r in relevances[:k] if r >= 0]
    if not rels:
        return 0.0
    ideal = sorted(rels, reverse=True)
    idcg = dcg(ideal)
    return dcg(rels) / idcg if idcg > 0 else 0.0


def precision_at_k(relevances: List[int], k: int = 10, threshold: int = 2) -> float:
    """Fraction of top-k items with relevance >= threshold."""
    rels = [r for r in relevances[:k] if r >= 0]
    if not rels:
        return 0.0
    return sum(1 for r in rels if r >= threshold) / len(rels)


def mrr(relevances: List[int], threshold: int = 2) -> float:
    """Reciprocal rank of the FIRST relevant (>= threshold) item."""
    for i, r in enumerate(relevances):
        if r >= threshold:
            return 1.0 / (i + 1)
    return 0.0


# ---------------------------------------------------------------------------
# Main sweep
# ---------------------------------------------------------------------------


def run_sweep(
    specs: List[CollectionSpec],
    queries: List[Dict[str, str]],
    judge_model: str,
    cross_judge_model: Optional[str],
    top_k: int = 10,
) -> Dict[str, Any]:
    # Shape: {spec_name: {query: {chunks:..., relevances:..., metrics:...}}}
    per_spec: Dict[str, Dict[str, Any]] = {s.name: {"queries": {}} for s in specs}

    for qi, q in enumerate(queries, 1):
        query = q["query"]
        topic = q.get("expected_topic", "")
        print(f"\n[{qi}/{len(queries)}] {query}")

        # Embed once (all collections share text-embedding-005 query space)
        qv = embed_query_vertex(query)

        for spec in specs:
            try:
                chunks = query_collection(spec, query, qv, top_k=top_k)
            except Exception as e:
                print(f"  [{spec.name}] query error: {e}")
                per_spec[spec.name]["queries"][query] = {"error": str(e)}
                continue

            # Judge each chunk
            rels: List[int] = []
            for ch in chunks:
                r = judge_chunk(judge_model, query, topic, ch["doc_title"], ch["text"])
                rels.append(r)

            # Optional cross-family (or cross-model) judge check
            cross_rels: Optional[List[int]] = None
            if cross_judge_model:
                cross_rels = []
                for ch in chunks:
                    r = judge_chunk(cross_judge_model, query, topic, ch["doc_title"], ch["text"])
                    cross_rels.append(r)

            entry = {
                "chunks": chunks,
                "relevances": rels,
                "ndcg_10": round(ndcg_at_k(rels, 10), 4),
                "p_10": round(precision_at_k(rels, 10, threshold=2), 4),
                "mrr": round(mrr(rels, threshold=2), 4),
            }
            if cross_rels is not None:
                entry["cross_relevances"] = cross_rels
                entry["cross_ndcg_10"] = round(ndcg_at_k(cross_rels, 10), 4)
                # Judge agreement: Cohen's kappa-ish — fraction of chunks where
                # both judges give the same bucket (0-3)
                if rels and cross_rels:
                    agree = sum(1 for a, b in zip(rels, cross_rels) if a == b) / len(rels)
                    near_agree = sum(1 for a, b in zip(rels, cross_rels) if abs(a - b) <= 1) / len(rels)
                    entry["judge_exact_agreement"] = round(agree, 4)
                    entry["judge_near_agreement"] = round(near_agree, 4)
            per_spec[spec.name]["queries"][query] = entry
            print(
                f"  [{spec.name:20s}] nDCG@10={entry['ndcg_10']:.3f} "
                f"P@10={entry['p_10']:.3f} MRR={entry['mrr']:.3f}"
            )

    # Aggregate per spec
    for name, data in per_spec.items():
        q_data = data["queries"]
        ndcgs = [v.get("ndcg_10", 0) for v in q_data.values() if "ndcg_10" in v]
        ps = [v.get("p_10", 0) for v in q_data.values() if "p_10" in v]
        mrrs = [v.get("mrr", 0) for v in q_data.values() if "mrr" in v]
        data["aggregate"] = {
            "n_queries": len(ndcgs),
            "mean_ndcg_10": round(sum(ndcgs) / len(ndcgs), 4) if ndcgs else 0.0,
            "mean_p_10": round(sum(ps) / len(ps), 4) if ps else 0.0,
            "mean_mrr": round(sum(mrrs) / len(mrrs), 4) if mrrs else 0.0,
        }
        if cross_judge_model:
            agrees = [v.get("judge_exact_agreement", 0) for v in q_data.values() if "judge_exact_agreement" in v]
            near_agrees = [v.get("judge_near_agreement", 0) for v in q_data.values() if "judge_near_agreement" in v]
            data["aggregate"]["mean_judge_exact_agreement"] = (
                round(sum(agrees) / len(agrees), 4) if agrees else 0.0
            )
            data["aggregate"]["mean_judge_near_agreement"] = (
                round(sum(near_agrees) / len(near_agrees), 4) if near_agrees else 0.0
            )

    return per_spec


def print_summary(results: Dict[str, Any]) -> None:
    print("\n========== AGGREGATE ==========")
    specs = list(results.keys())
    header = f"{'Collection':<25s}  {'nDCG@10':<10s}  {'P@10':<10s}  {'MRR':<10s}"
    print(header)
    print("-" * len(header))
    for name in specs:
        agg = results[name].get("aggregate", {})
        print(
            f"{name:<25s}  "
            f"{agg.get('mean_ndcg_10', 0):<10.4f}  "
            f"{agg.get('mean_p_10', 0):<10.4f}  "
            f"{agg.get('mean_mrr', 0):<10.4f}"
        )
    # Judge agreement if present
    for name in specs:
        agg = results[name].get("aggregate", {})
        if "mean_judge_exact_agreement" in agg:
            print(
                f"{name:<25s}  judge exact agree: {agg['mean_judge_exact_agreement']:.4f}, "
                f"near (±1): {agg['mean_judge_near_agreement']:.4f}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--qdrant", default="http://localhost:6334", help="Single Qdrant URL")
    parser.add_argument("--collections", default="dspace_fulltext_vertex",
                        help="Comma-separated collection names (with --qdrant)")
    parser.add_argument("--specs", default=None,
                        help="Full specs: name=URL:coll,name=URL:coll,...")
    parser.add_argument("--judge-model", default="gemini-2.5-flash-lite",
                        help="Primary LLM judge")
    parser.add_argument("--cross-judge", action="store_true",
                        help="Also run gemini-2.5-pro as cross-model judge (task C)")
    parser.add_argument("--cross-judge-model", default="gemini-2.5-pro")
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--limit", type=int, default=0,
                        help="Max queries (0 = all)")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.specs:
        specs = parse_specs(args.specs)
    else:
        colls = [c.strip() for c in args.collections.split(",") if c.strip()]
        specs = [CollectionSpec(name=c, url=args.qdrant, collection=c) for c in colls]

    queries = GOLDEN_QUERIES
    if args.limit and args.limit > 0:
        queries = queries[: args.limit]

    print(f"P4 Eval Sweep")
    print(f"  Collections: {[s.name for s in specs]}")
    print(f"  Queries: {len(queries)}")
    print(f"  Judge: {args.judge_model}")
    if args.cross_judge:
        print(f"  Cross-judge: {args.cross_judge_model}")
    print()

    start = time.time()
    results = run_sweep(
        specs=specs,
        queries=queries,
        judge_model=args.judge_model,
        cross_judge_model=args.cross_judge_model if args.cross_judge else None,
        top_k=args.top_k,
    )

    print_summary(results)

    out_path = args.out or str(
        RESULTS_DIR / f"p4_eval_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    )
    report = {
        "started_at": datetime.fromtimestamp(start).isoformat(timespec="seconds"),
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "specs": [asdict(s) for s in specs],
        "judge_model": args.judge_model,
        "cross_judge_model": args.cross_judge_model if args.cross_judge else None,
        "query_count": len(queries),
        "results": results,
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    print(f"\nSaved: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
