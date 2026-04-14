"""
LLM-as-judge evaluation framework for RAG retrieval quality.

For each test query in a JSON file, this script:
  1. Embeds the query with the backend that matches the target Qdrant collection
     (Ollama for `dspace_fulltext_nomic`, Vertex for `dspace_fulltext_vertex` or
      `dspace_chunks`).
  2. Searches Qdrant for the top-K most similar chunks.
  3. Asks Claude to score each chunk's relevance on a 0-3 scale:
       0 = Not relevant
       1 = Marginally relevant
       2 = Relevant
       3 = Highly relevant
  4. Computes standard IR metrics — nDCG@5, nDCG@10, Precision@1/5/10, MRR —
     per-query and averaged across the test set.
  5. Saves a timestamped JSON report under backend/data/eval/.

The LLM judge supports two transports:
  A) Direct `anthropic` SDK using ANTHROPIC_API_KEY (fast, default when available)
  B) Fallback: shell out to the `claude` CLI (`claude -p "..."`) if no key is set

Supported collections (--collection):
  - dspace_chunks          (Vertex text-embedding-005, task=RETRIEVAL_QUERY)
  - dspace_fulltext_vertex (Vertex text-embedding-005, task=RETRIEVAL_QUERY)
  - dspace_fulltext_nomic  (Ollama nomic-embed-text, task=query)

Usage:
    # Minimal — will auto-create a sample test_queries.json on first run
    python scripts/eval_llm_judge.py \
        --collection dspace_fulltext_nomic \
        --queries data/eval/test_queries.json \
        --top-k 10

    # Compare models
    python scripts/eval_llm_judge.py --collection dspace_fulltext_nomic  --queries data/eval/test_queries.json
    python scripts/eval_llm_judge.py --collection dspace_fulltext_vertex --queries data/eval/test_queries.json
    python scripts/eval_llm_judge.py --collection dspace_chunks          --queries data/eval/test_queries.json

    # Use the Claude CLI instead of the SDK (no API key needed)
    python scripts/eval_llm_judge.py --judge-backend cli --collection dspace_fulltext_nomic
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# qdrant-client is a hard dependency of the backend, so importing at top is safe.
from qdrant_client import QdrantClient

# ----------------------------------------------------------------------
# Paths and defaults
# ----------------------------------------------------------------------

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parent
EVAL_DIR = BACKEND / "data" / "eval"
DEFAULT_QUERIES = EVAL_DIR / "test_queries.json"

DEFAULT_QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6334")
DEFAULT_TOP_K = 10
DEFAULT_CLAUDE_MODEL = os.getenv("CLAUDE_JUDGE_MODEL", "claude-opus-4-6")

# Per-collection embedding configuration. These mirror the scripts that built
# the collections (embed_pdfs_ollama.py, embed_vertex_batch_real.py,
# embed_abstracts_to_qdrant.py).
COLLECTION_CONFIGS: Dict[str, Dict[str, Any]] = {
    "dspace_chunks": {
        "embedder": "vertex",
        "model": "text-embedding-005",
        "dim": 768,
        "task_type": "RETRIEVAL_QUERY",
        "vector_name": None,  # uses the unnamed default vector
        "payload_text_fields": ("text", "text_preview", "snippet"),
        "payload_title_fields": ("doc_title", "title"),
    },
    "dspace_fulltext_vertex": {
        "embedder": "vertex",
        "model": "text-embedding-005",
        "dim": 768,
        "task_type": "RETRIEVAL_QUERY",
        "vector_name": None,
        "payload_text_fields": ("text", "text_preview", "snippet"),
        "payload_title_fields": ("title", "doc_title"),
    },
    "dspace_fulltext_nomic": {
        "embedder": "ollama",
        "model": os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text"),
        "dim": 768,
        "task_type": "query",  # nomic uses "search_query: " prefix
        "vector_name": None,
        "payload_text_fields": ("text", "text_preview", "snippet"),
        "payload_title_fields": ("title", "doc_title"),
    },
}

# Shared 5-query sample that gets written to disk if the queries file is absent.
# Chosen to cover the ISU DSpace corpus: agriculture, engineering, policy, CS, vet med.
SAMPLE_QUERIES: List[Dict[str, Any]] = [
    {
        "id": "q1_soybean_drought",
        "query": "How does drought stress affect soybean yield in Iowa farms?",
        "tags": ["agriculture", "plant_science"],
    },
    {
        "id": "q2_wind_turbine_fatigue",
        "query": "Fatigue analysis of wind turbine blades composite materials",
        "tags": ["engineering", "wind_energy"],
    },
    {
        "id": "q3_food_security_policy",
        "query": "Rural food insecurity policy interventions effectiveness",
        "tags": ["policy", "social_science"],
    },
    {
        "id": "q4_machine_learning_crops",
        "query": "Machine learning methods for crop disease detection",
        "tags": ["computer_science", "agriculture"],
    },
    {
        "id": "q5_veterinary_swine",
        "query": "Porcine reproductive and respiratory syndrome virus diagnostics",
        "tags": ["veterinary", "swine"],
    },
]


# ----------------------------------------------------------------------
# Utility
# ----------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def ensure_sample_queries(path: Path) -> None:
    """Write a 5-query placeholder file if `path` doesn't exist."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "description": (
            "Placeholder sample test queries for the LLM-judge RAG eval. "
            "Regenerate this file with the synthetic-query generator to replace with real data."
        ),
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "queries": SAMPLE_QUERIES,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Wrote sample queries to {path} ({len(SAMPLE_QUERIES)} queries)")


def load_queries(path: Path) -> List[Dict[str, Any]]:
    """Load a JSON queries file. Accepts either a top-level list or {queries: [...]}"""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        queries = data
    elif isinstance(data, dict):
        queries = data.get("queries") or data.get("items") or []
    else:
        queries = []
    # Normalise each entry to {id, query, tags}
    out = []
    for i, q in enumerate(queries):
        if isinstance(q, str):
            out.append({"id": f"q{i+1}", "query": q, "tags": []})
        elif isinstance(q, dict):
            out.append({
                "id": q.get("id") or f"q{i+1}",
                "query": q.get("query") or q.get("question") or q.get("text") or "",
                "tags": q.get("tags") or [],
            })
    # Drop blanks
    return [q for q in out if q["query"].strip()]


# ----------------------------------------------------------------------
# Embedders
# ----------------------------------------------------------------------

class OllamaEmbedder:
    """
    Minimal Ollama embedding client. Mirrors the logic in
    services/embedding_service.py — specifically the `search_query: ` prefix
    that nomic-embed-text requires for query-side embeddings.
    """

    def __init__(self, model: str, host: str = "http://localhost:11434"):
        self.model = model
        self.host = host.rstrip("/")

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=3) as resp:
                return resp.status == 200
        except Exception:
            return False

    def embed_query(self, text: str) -> Optional[List[float]]:
        if "nomic-embed" in self.model.lower():
            text = "search_query: " + text
        body = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.host}/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = json.loads(resp.read())
                emb = data.get("embedding")
                if not emb:
                    # Newer Ollama versions return under "embeddings"
                    embs = data.get("embeddings") or []
                    if embs:
                        return embs[0]
                return emb
        except Exception as e:
            log(f"  Ollama embed failed: {e}")
            return None


class VertexEmbedder:
    """
    Wraps google-genai Vertex client for query embeddings.
    Uses RETRIEVAL_QUERY task type and text-embedding-005 by default.
    """

    def __init__(self, model: str, dim: int = 768,
                 project: str = "rag-dspace", location: str = "us-central1"):
        self.model = model
        self.dim = dim
        self.project = project
        self.location = location
        self._client = None

    def _ensure_client(self) -> bool:
        if self._client is not None:
            return True
        try:
            from google import genai
            self._client = genai.Client(
                vertexai=True, project=self.project, location=self.location,
            )
            return True
        except Exception as e:
            log(f"  Vertex client init failed: {e}")
            return False

    def embed_query(self, text: str) -> Optional[List[float]]:
        if not self._ensure_client():
            return None
        try:
            from google.genai import types as genai_types
            result = self._client.models.embed_content(
                model=self.model,
                contents=[text],
                config=genai_types.EmbedContentConfig(
                    task_type="RETRIEVAL_QUERY",
                    output_dimensionality=self.dim,
                ),
            )
            if not result or not result.embeddings:
                return None
            return list(result.embeddings[0].values)
        except Exception as e:
            log(f"  Vertex embed failed: {e}")
            return None


def build_embedder(config: Dict[str, Any]):
    """Return an embedder instance keyed off the collection config."""
    if config["embedder"] == "ollama":
        return OllamaEmbedder(model=config["model"])
    if config["embedder"] == "vertex":
        return VertexEmbedder(model=config["model"], dim=config.get("dim", 768))
    raise ValueError(f"Unknown embedder type: {config['embedder']}")


# ----------------------------------------------------------------------
# Qdrant retrieval
# ----------------------------------------------------------------------

def retrieve(
    client: QdrantClient,
    collection: str,
    query_vector: List[float],
    top_k: int,
    vector_name: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Search a Qdrant collection and return normalized hits.

    Uses `query_points` which works with both named and default vectors.
    Falls back silently if the collection uses an unusual vector config.
    """
    try:
        if vector_name:
            res = client.query_points(
                collection_name=collection,
                query=query_vector,
                using=vector_name,
                limit=top_k,
                with_payload=True,
            )
        else:
            res = client.query_points(
                collection_name=collection,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
    except Exception as e:
        log(f"  Qdrant query failed on {collection}: {e}")
        return []

    out = []
    for hit in res.points:
        payload = hit.payload or {}
        out.append({
            "id": str(getattr(hit, "id", "")),
            "score": float(getattr(hit, "score", 0.0) or 0.0),
            "payload": payload,
        })
    return out


def extract_text_and_title(
    payload: Dict[str, Any],
    text_fields: Tuple[str, ...],
    title_fields: Tuple[str, ...],
) -> Tuple[str, str]:
    """Pull text + title from a payload using a fallback chain."""
    text = ""
    for f in text_fields:
        v = payload.get(f)
        if v:
            text = str(v)
            break
    title = ""
    for f in title_fields:
        v = payload.get(f)
        if v:
            title = str(v)
            break
    return text, title


# ----------------------------------------------------------------------
# LLM judge
# ----------------------------------------------------------------------

JUDGE_PROMPT_TEMPLATE = (
    "Query: {query}\n"
    "Document chunk: {text}\n"
    "Score (0-3) how relevant this chunk is to answering the query.\n"
    "0 = Not relevant, 1 = Marginally relevant, 2 = Relevant, 3 = Highly relevant.\n"
    "Output ONLY a single digit 0, 1, 2, or 3."
)

_DIGIT_RE = re.compile(r"[0-3]")


def parse_score(text: str) -> Optional[int]:
    """Extract the first 0-3 digit from a Claude response. None on failure."""
    if not text:
        return None
    m = _DIGIT_RE.search(text.strip())
    if not m:
        return None
    try:
        v = int(m.group(0))
        return v if 0 <= v <= 3 else None
    except Exception:
        return None


class LLMJudge:
    """
    Score relevance via Claude. Two backends:
      - 'sdk' : anthropic Python SDK (requires ANTHROPIC_API_KEY)
      - 'cli' : shell out to `claude -p "..."` (requires the Claude CLI on PATH)
    `auto` picks SDK when the key is set and falls back to CLI otherwise.
    """

    def __init__(
        self,
        backend: str = "auto",
        model: str = DEFAULT_CLAUDE_MODEL,
        max_chars: int = 500,
    ):
        self.model = model
        self.max_chars = max_chars
        self.backend = self._select_backend(backend)
        self._sdk_client = None
        if self.backend == "sdk":
            self._init_sdk()

    # -- backend selection -------------------------------------------------

    def _select_backend(self, requested: str) -> str:
        if requested == "sdk":
            if not os.getenv("ANTHROPIC_API_KEY"):
                raise RuntimeError(
                    "judge-backend=sdk requires ANTHROPIC_API_KEY to be set"
                )
            return "sdk"
        if requested == "cli":
            if not shutil.which("claude"):
                raise RuntimeError(
                    "judge-backend=cli requires the `claude` CLI to be on PATH"
                )
            return "cli"
        # auto
        if os.getenv("ANTHROPIC_API_KEY"):
            try:
                import anthropic  # noqa: F401
                return "sdk"
            except ImportError:
                pass
        if shutil.which("claude"):
            return "cli"
        raise RuntimeError(
            "No LLM judge backend available: set ANTHROPIC_API_KEY (with `anthropic` "
            "installed) or install the `claude` CLI and re-run."
        )

    def _init_sdk(self) -> None:
        import anthropic
        self._sdk_client = anthropic.Anthropic()
        log(f"LLMJudge: using Anthropic SDK (model={self.model})")

    # -- scoring -----------------------------------------------------------

    def _build_prompt(self, query: str, chunk_text: str) -> str:
        trimmed = (chunk_text or "").strip()[: self.max_chars]
        return JUDGE_PROMPT_TEMPLATE.format(query=query, text=trimmed)

    def _score_sdk(self, prompt: str) -> Optional[int]:
        try:
            resp = self._sdk_client.messages.create(
                model=self.model,
                max_tokens=4,  # a single digit plus whitespace
                messages=[{"role": "user", "content": prompt}],
            )
            text = ""
            for block in resp.content or []:
                t = getattr(block, "text", None)
                if t:
                    text += t
            return parse_score(text)
        except Exception as e:
            log(f"  judge sdk error: {e}")
            return None

    def _score_cli(self, prompt: str) -> Optional[int]:
        # `claude -p "prompt"` prints the assistant reply to stdout and exits.
        try:
            result = subprocess.run(
                ["claude", "-p", prompt],
                capture_output=True,
                text=True,
                timeout=60,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode != 0:
                log(f"  judge cli error: {result.stderr[:200]}")
                return None
            return parse_score(result.stdout)
        except subprocess.TimeoutExpired:
            log("  judge cli timeout")
            return None
        except Exception as e:
            log(f"  judge cli error: {e}")
            return None

    def score(self, query: str, chunk_text: str) -> Optional[int]:
        prompt = self._build_prompt(query, chunk_text)
        if self.backend == "sdk":
            return self._score_sdk(prompt)
        return self._score_cli(prompt)


# ----------------------------------------------------------------------
# Metrics
# ----------------------------------------------------------------------

def dcg(scores: List[int]) -> float:
    """Discounted cumulative gain (using 2^rel - 1 numerator)."""
    total = 0.0
    for i, s in enumerate(scores):
        if s <= 0:
            continue
        total += (2 ** s - 1) / math.log2(i + 2)
    return total


def ndcg_at_k(scores: List[int], k: int) -> float:
    if not scores:
        return 0.0
    actual = dcg(scores[:k])
    ideal = dcg(sorted(scores, reverse=True)[:k])
    if ideal == 0:
        return 0.0
    return actual / ideal


def precision_at_k(scores: List[int], k: int, threshold: int = 2) -> float:
    """
    Precision@k using `threshold` as the "relevant" cutoff. Defaults to 2 —
    treat scores 2-3 as relevant, 0-1 as non-relevant.
    """
    if not scores or k <= 0:
        return 0.0
    top = scores[:k]
    if not top:
        return 0.0
    hits = sum(1 for s in top if s >= threshold)
    return hits / min(k, len(top))


def reciprocal_rank(scores: List[int], threshold: int = 2) -> float:
    """First rank whose score >= threshold, as 1/rank. 0 if none qualify."""
    for i, s in enumerate(scores, start=1):
        if s >= threshold:
            return 1.0 / i
    return 0.0


def average(values: List[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


# ----------------------------------------------------------------------
# Evaluation loop
# ----------------------------------------------------------------------

@dataclass
class QueryResult:
    query_id: str
    query: str
    tags: List[str]
    retrieved: List[Dict[str, Any]] = field(default_factory=list)
    scores: List[Optional[int]] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


def evaluate_query(
    query: Dict[str, Any],
    qclient: QdrantClient,
    collection: str,
    config: Dict[str, Any],
    embedder,
    judge: LLMJudge,
    top_k: int,
) -> QueryResult:
    qid = query["id"]
    text = query["query"]

    qr = QueryResult(query_id=qid, query=text, tags=query.get("tags", []))

    log(f"  [{qid}] {text[:80]}")
    qv = embedder.embed_query(text)
    if not qv:
        log(f"    embedding failed — skipping")
        qr.metrics = {"error": 1.0}
        return qr

    hits = retrieve(qclient, collection, qv, top_k, config.get("vector_name"))
    if not hits:
        log(f"    no hits returned")
        qr.metrics = {"error": 1.0}
        return qr

    text_fields = config["payload_text_fields"]
    title_fields = config["payload_title_fields"]

    # Judge every hit sequentially — these calls are cheap in aggregate
    # (50 queries * 10 hits * 4 tokens each = cheap on opus).
    scores: List[Optional[int]] = []
    retrieved_log: List[Dict[str, Any]] = []
    for rank, hit in enumerate(hits, start=1):
        chunk_text, title = extract_text_and_title(hit["payload"], text_fields, title_fields)
        score = judge.score(text, chunk_text)
        scores.append(score)
        retrieved_log.append({
            "rank": rank,
            "qdrant_score": round(hit["score"], 4),
            "point_id": hit["id"],
            "title": title[:160],
            "text_preview": (chunk_text or "")[:240],
            "judge_score": score,
        })

    # Treat unscored (None) as 0 when computing metrics so nothing is NaN —
    # we still persist the raw None in retrieved_log so issues are visible.
    clean_scores = [s if s is not None else 0 for s in scores]
    qr.retrieved = retrieved_log
    qr.scores = scores
    qr.metrics = {
        "ndcg@5": round(ndcg_at_k(clean_scores, 5), 4),
        "ndcg@10": round(ndcg_at_k(clean_scores, 10), 4),
        "precision@1": round(precision_at_k(clean_scores, 1), 4),
        "precision@5": round(precision_at_k(clean_scores, 5), 4),
        "precision@10": round(precision_at_k(clean_scores, 10), 4),
        "mrr": round(reciprocal_rank(clean_scores), 4),
        "mean_judge_score": round(average([float(s) for s in clean_scores]), 4),
        "unscored": sum(1 for s in scores if s is None),
    }
    log(
        f"    nDCG@10={qr.metrics['ndcg@10']:.3f}  "
        f"P@5={qr.metrics['precision@5']:.3f}  "
        f"MRR={qr.metrics['mrr']:.3f}  "
        f"mean={qr.metrics['mean_judge_score']:.2f}"
    )
    return qr


def aggregate_metrics(results: List[QueryResult]) -> Dict[str, float]:
    keys = ["ndcg@5", "ndcg@10", "precision@1", "precision@5", "precision@10", "mrr",
            "mean_judge_score"]
    agg: Dict[str, float] = {}
    for k in keys:
        vals = [r.metrics[k] for r in results if k in r.metrics]
        agg[k] = round(average(vals), 4) if vals else 0.0
    agg["queries_evaluated"] = float(len(results))
    agg["queries_with_errors"] = float(sum(1 for r in results if r.metrics.get("error")))
    return agg


# ----------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collection",
        required=True,
        choices=sorted(COLLECTION_CONFIGS.keys()),
        help="Qdrant collection to evaluate",
    )
    parser.add_argument(
        "--queries",
        default=str(DEFAULT_QUERIES),
        help="Path to a JSON file with test queries",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=DEFAULT_TOP_K,
        help="Number of results to retrieve per query",
    )
    parser.add_argument(
        "--qdrant-url",
        default=DEFAULT_QDRANT_URL,
        help="Qdrant URL (default: http://localhost:6334)",
    )
    parser.add_argument(
        "--judge-backend",
        default="auto",
        choices=["auto", "sdk", "cli"],
        help="Which Claude transport to use for relevance judgments",
    )
    parser.add_argument(
        "--judge-model",
        default=DEFAULT_CLAUDE_MODEL,
        help="Claude model name (used by the SDK backend)",
    )
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=500,
        help="Truncate each chunk to this many characters before sending to the judge",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Override the output path (default auto-generated under backend/data/eval/)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Only evaluate the first N queries (0 = all)",
    )
    args = parser.parse_args()

    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    EVAL_DIR.mkdir(parents=True, exist_ok=True)

    queries_path = Path(args.queries)
    if not queries_path.is_absolute():
        queries_path = BACKEND / queries_path
    ensure_sample_queries(queries_path)
    queries = load_queries(queries_path)
    if args.limit and args.limit > 0:
        queries = queries[: args.limit]
    if not queries:
        log(f"No queries loaded from {queries_path}")
        return 1

    config = COLLECTION_CONFIGS[args.collection]
    log("=" * 70)
    log(f"LLM-as-judge RAG evaluation")
    log(f"  Collection  : {args.collection}")
    log(f"  Embedder    : {config['embedder']} ({config['model']})")
    log(f"  Qdrant URL  : {args.qdrant_url}")
    log(f"  Queries     : {queries_path} ({len(queries)} queries)")
    log(f"  Top-K       : {args.top_k}")
    log(f"  Judge model : {args.judge_model}")
    log("=" * 70)

    # Probe Qdrant and make sure the collection exists
    try:
        qclient = QdrantClient(url=args.qdrant_url, timeout=60)
        info = qclient.get_collection(args.collection)
        log(f"Qdrant OK: {args.collection} has {getattr(info, 'points_count', '?')} points")
    except Exception as e:
        log(f"ERROR: cannot reach Qdrant or collection {args.collection}: {e}")
        return 2

    embedder = build_embedder(config)
    if config["embedder"] == "ollama" and not embedder.available():
        log("ERROR: Ollama server is not reachable — start `ollama serve` and retry")
        return 3

    try:
        judge = LLMJudge(
            backend=args.judge_backend,
            model=args.judge_model,
            max_chars=args.max_chunk_chars,
        )
    except RuntimeError as e:
        log(f"ERROR: {e}")
        return 4
    log(f"LLMJudge backend: {judge.backend}")

    results: List[QueryResult] = []
    t0 = time.time()
    for q in queries:
        qr = evaluate_query(
            query=q,
            qclient=qclient,
            collection=args.collection,
            config=config,
            embedder=embedder,
            judge=judge,
            top_k=args.top_k,
        )
        results.append(qr)

    elapsed = time.time() - t0
    aggregate = aggregate_metrics(results)

    log("")
    log("=" * 70)
    log(f"Aggregate metrics over {len(results)} queries (elapsed {elapsed/60:.1f} min):")
    for k in ["ndcg@5", "ndcg@10", "precision@1", "precision@5", "precision@10",
              "mrr", "mean_judge_score"]:
        log(f"  {k:<16s} {aggregate[k]:.4f}")
    if aggregate["queries_with_errors"]:
        log(f"  (errors on {int(aggregate['queries_with_errors'])} queries)")
    log("=" * 70)

    # ----------------------- save report -----------------------
    ts = time.strftime("%Y%m%d_%H%M%S")
    if args.output:
        out_path = Path(args.output)
    else:
        out_path = EVAL_DIR / f"results_{args.collection}_{ts}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    report = {
        "config": {
            "collection": args.collection,
            "collection_config": {
                "embedder": config["embedder"],
                "model": config["model"],
                "dim": config.get("dim"),
            },
            "qdrant_url": args.qdrant_url,
            "top_k": args.top_k,
            "judge_backend": judge.backend,
            "judge_model": args.judge_model,
            "max_chunk_chars": args.max_chunk_chars,
            "queries_file": str(queries_path),
            "timestamp": ts,
            "elapsed_seconds": int(elapsed),
        },
        "aggregate": aggregate,
        "queries": [
            {
                "query_id": r.query_id,
                "query": r.query,
                "tags": r.tags,
                "metrics": r.metrics,
                "retrieved": r.retrieved,
            }
            for r in results
        ],
    }
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Saved report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
