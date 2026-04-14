"""
QdrantRAGService — replaces the legacy GeminiRAGService.

Pipeline per query:
  1. Embed the query via Vertex text-embedding-005 (RETRIEVAL_QUERY task)
  2. Hybrid retrieve top-k from the dspace_chunks Qdrant collection
     (currently dense-only; sparse BM25 hook ready when sparse vectors are populated)
  3. Format the retrieved chunks into a citation-anchored context block
  4. Generate an answer via Gemini 2.5 Flash on Vertex with [N] citation markers
  5. Return { answer, citations[], retrieved_chunks[] } in the shape the
     frontend already consumes
"""

import asyncio
import json
import logging
import math
import os
import re
from collections import Counter, OrderedDict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from services.embedding_service import embedding_service

# BM25 query-side helper — loads the vocabulary built by either
# `backend/scripts/add_bm25_to_qdrant.py` (legacy dspace_chunks abstract
# collection) or `backend/scripts/embed_vertex_hybrid_ingest.py` (new
# fulltext vertex collection). The vocab file path is selected at runtime
# based on the active QDRANT_COLLECTION env var so the backend can swap
# collections without a restart. Load is lazy — the service starts up even
# if the vocab file is missing; in that case hybrid retrieval auto-disables
# and the code path falls back to dense-only.
_BM25_VOCAB_BY_COLLECTION = {
    "dspace_chunks": "bm25_vocab.json",
    "dspace_fulltext_vertex": "bm25_vocab_vertex.json",
}
_BM25_VOCAB_PATH = Path(__file__).parent.parent / "data" / _BM25_VOCAB_BY_COLLECTION.get(
    os.environ.get("QDRANT_COLLECTION", "dspace_chunks"),
    os.environ.get("BM25_VOCAB_FILE", "bm25_vocab.json"),
)
_BM25_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_BM25_STOP = {
    "a", "an", "the", "and", "or", "but", "if", "while", "with", "of", "to",
    "in", "on", "at", "by", "for", "from", "as", "is", "are", "was", "were",
    "be", "been", "being", "have", "has", "had", "do", "does", "did", "will",
    "would", "could", "should", "may", "might", "must", "shall", "can", "this",
    "that", "these", "those", "it", "its", "i", "you", "he", "she", "we", "they",
    "them", "their", "his", "her", "our", "your", "my", "me", "us",
}
_bm25_state: Optional[Dict[str, Any]] = None


def _bm25_load() -> Optional[Dict[str, Any]]:
    """Lazy-load the BM25 vocab once. Returns None if file missing."""
    global _bm25_state
    if _bm25_state is not None:
        return _bm25_state
    if not _BM25_VOCAB_PATH.exists():
        logger.info(f"QdrantRAGService: BM25 vocab not found at {_BM25_VOCAB_PATH} — hybrid disabled")
        return None
    try:
        with _BM25_VOCAB_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        _bm25_state = {
            "n_docs": int(data.get("n_docs", 0)),
            "avgdl": float(data.get("avgdl", 1.0)),
            "k1": float(data.get("k1", 1.5)),
            "b": float(data.get("b", 0.75)),
            "df": data.get("df", {}),
            "token_to_id": data.get("token_to_id", {}),
        }
        logger.info(
            f"QdrantRAGService: BM25 vocab loaded "
            f"(n_docs={_bm25_state['n_docs']}, vocab={len(_bm25_state['token_to_id'])})"
        )
        return _bm25_state
    except Exception as e:
        logger.error(f"QdrantRAGService: BM25 vocab load failed: {e}")
        return None


def _bm25_query_vector(query: str) -> Optional[Tuple[List[int], List[float]]]:
    """
    Build a BM25-weighted sparse vector for a query string using the
    pre-built corpus vocabulary. Returns (indices, values) or None if
    the vocab isn't available or the query has no in-vocab tokens.
    """
    state = _bm25_load()
    if state is None:
        return None
    df = state["df"]
    token_to_id = state["token_to_id"]
    n_docs = state["n_docs"]
    avgdl = state["avgdl"] or 1.0
    k1 = state["k1"]
    b = state["b"]

    # Tokenize the query the same way the indexer did
    toks = []
    for tok in _BM25_TOKEN_RE.findall(query or ""):
        t = tok.lower()
        if len(t) >= 3 and t not in _BM25_STOP:
            toks.append(t)
    if not toks:
        return None
    tf = Counter(toks)
    dl = len(toks)
    indices: List[int] = []
    values: List[float] = []
    for term, freq in tf.items():
        d = df.get(term, 0)
        if d == 0:
            continue
        idf = math.log(1 + (n_docs - d + 0.5) / (d + 0.5))
        score = idf * (freq * (k1 + 1)) / (
            freq + k1 * (1 - b + b * dl / avgdl)
        )
        indices.append(token_to_id[term])
        values.append(round(score, 4))
    if not indices:
        return None
    return indices, values

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://35.188.64.146:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "dspace_chunks")
GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
# gemini-2.5-flash-lite is ~3-4× faster than gemini-2.5-flash and good
# enough for short, citation-anchored answers. Override via env if needed.
GEMINI_GEN_MODEL = os.getenv("GEMINI_GEN_MODEL", "gemini-2.5-flash-lite")

DEFAULT_TOP_K = 8           # was 12 — smaller prompt = faster generation
MAX_CONTEXT_CHARS = 9000    # was 16000 — tighter bound for lower latency

# In-process LRU cache for the (query, top_k) → answer pipeline.
# Keeps the demo snappy when the same query is hit twice in a row, e.g. by
# a user pressing search again or following a suggestion chip.
_RESULT_CACHE: "OrderedDict[str, Dict[str, Any]]" = None  # set lazily
_RESULT_CACHE_MAX = 64


def _build_context(chunks: List[Dict[str, Any]]) -> str:
    """Format retrieved chunks as a numbered context block for the LLM."""
    out = []
    used = 0
    for i, c in enumerate(chunks, start=1):
        title = c.get("doc_title", "") or "Untitled"
        heading = c.get("heading", "") or ""
        page = c.get("page", "") or ""
        text = (c.get("text") or "").strip()
        prefix = f"[{i}] {title}"
        if heading:
            prefix += f" — {heading}"
        if page:
            prefix += f" (p. {page})"
        block = f"{prefix}\n{text}\n"
        if used + len(block) > MAX_CONTEXT_CHARS:
            break
        out.append(block)
        used += len(block)
    return "\n".join(out)


def _build_prompt(query: str, context: str) -> str:
    return f"""You are a research assistant for the Iowa State University (ISU) Digital Repository.
Every numbered passage below comes from ISU's DSpace repository (dr.lib.iastate.edu) — every passage is ALREADY from ISU research, even when the text itself doesn't say "Iowa State University" by name.

Your job is to answer the user's question using the numbered passages below.

RULES (read carefully — these matter for correctness):

1. **Treat every passage as ISU research** — the repository only contains ISU-affiliated publications, theses, and reports. A passage about "plant science outreach" or "CS education" or "genomics" IS ISU work; you don't need an explicit "Iowa State" mention to know this.

2. **NEVER claim a person is an author of a paper unless their name appears in that passage's `Authors:` metadata.** If the user asks "what has Dr. X written?" and a passage doesn't list X in its authors, DO NOT say X wrote it — even if the passage mentions X elsewhere (in acknowledgments, citations, student stories, or news articles). Authorship is a hard fact, not an inference.

3. **If a passage MENTIONS a person without them being an author, say so explicitly.** Example: "The Iowa State Daily article [3] mentions Adisak Sukul as a computer science instructor but he is not an author of that piece." Do not conflate "mentioned in the text" with "wrote the paper".

4. **If the passages do NOT contain any papers authored by the person in the query**, say so plainly: "I did not find publications authored by [NAME] in the returned passages. The passages either are about other topics or only mention [NAME] in passing." Do not fabricate a publication list to satisfy the user's question.

5. **Lead with ISU people and content.** Some passages describe multi-institution collaborations (AIIRA, AIFARMS, AgAID, AIFS, AI-LEAF) that include researchers from UIUC, UC Davis, OSU, WSU, UMN. List ISU-affiliated researchers first. If you mention non-ISU collaborators, label them with their home institution.

6. **Cite every factual claim inline** with markers like [1], [2], [3] matching the passage numbers.

7. **Prefer concrete names, departments, and paper titles** over vague summaries.

8. **Keep the answer concise** — typically 3–8 sentences. Longer only if the question genuinely requires it.

PASSAGES:
{context}

QUESTION: {query}

ANSWER (with inline [N] citations, and STRICT on authorship claims):"""


class QdrantRAGService:
    def __init__(self):
        self._client: Optional[QdrantClient] = None
        self._gen_client = None  # google.genai.Client (Vertex)
        self.initialized = False
        # Set at configure() time based on live collection schema. Some
        # collections (dspace_chunks) have a "bm25" sparse vector populated by
        # add_bm25_to_qdrant.py; newer fulltext collections (dspace_fulltext_*)
        # ship without sparse vectors and need dense-only retrieval.
        self._has_bm25_sparse: bool = False

    def configure(self, gen_client=None) -> None:
        try:
            self._client = QdrantClient(url=QDRANT_URL, timeout=60)
            # Ping
            self._client.get_collections()
        except Exception as e:
            logger.error(f"QdrantRAGService: cannot reach Qdrant at {QDRANT_URL}: {e}")
            self._client = None

        # Detect whether the active collection has a "bm25" sparse vector. If
        # not, we must skip the hybrid prefetch path and stay dense-only —
        # otherwise `using="bm25"` raises at query time.
        self._has_bm25_sparse = False
        if self._client is not None:
            try:
                info = self._client.get_collection(QDRANT_COLLECTION)
                sparse = getattr(info.config.params, "sparse_vectors", None) or {}
                if isinstance(sparse, dict) and "bm25" in sparse:
                    self._has_bm25_sparse = True
            except Exception as e:
                logger.warning(
                    f"QdrantRAGService: could not inspect sparse vectors on "
                    f"{QDRANT_COLLECTION}: {e}"
                )

        if gen_client is None:
            try:
                from google import genai as _google_genai
                gen_client = _google_genai.Client(
                    vertexai=True, project=GCP_PROJECT, location=GCP_LOCATION
                )
            except Exception as e:
                logger.error(f"QdrantRAGService: cannot build Vertex client: {e}")
                gen_client = None

        self._gen_client = gen_client

        if not embedding_service.initialized:
            embedding_service.configure()

        self.initialized = self._client is not None and self._gen_client is not None
        if self.initialized:
            logger.info(
                f"QdrantRAGService: ready (collection={QDRANT_COLLECTION}, "
                f"gen_model={GEMINI_GEN_MODEL}, "
                f"bm25_sparse={'yes' if self._has_bm25_sparse else 'no'})"
            )
        else:
            logger.warning("QdrantRAGService: degraded — Qdrant or Vertex unavailable")

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def _retrieve(self, query: str, top_k: int) -> List[Dict[str, Any]]:
        if self._client is None:
            return []
        qv = embedding_service._embed_one(query, task_type="RETRIEVAL_QUERY")
        if not qv:
            logger.warning("QdrantRAGService: query embedding failed")
            return []

        # Build the BM25 sparse query vector if the vocab is loaded AND the
        # active collection actually has a "bm25" sparse vector. For
        # fulltext-chunk collections (no sparse vectors), we stay dense-only.
        sparse = _bm25_query_vector(query) if self._has_bm25_sparse else None

        try:
            if sparse is not None:
                # Hybrid retrieval: prefetch dense and sparse separately,
                # then fuse with reciprocal rank fusion.
                ids, vals = sparse
                results = self._client.query_points(
                    collection_name=QDRANT_COLLECTION,
                    prefetch=[
                        qm.Prefetch(query=qv, using="dense", limit=max(top_k * 4, 32)),
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
            else:
                results = self._client.query_points(
                    collection_name=QDRANT_COLLECTION,
                    query=qv,
                    using="dense",
                    limit=top_k,
                    with_payload=True,
                )
        except Exception as e:
            logger.error(f"QdrantRAGService: Qdrant query failed: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for hit in results.points:
            p = hit.payload or {}
            out.append({
                "score": float(hit.score),
                "uuid": p.get("uuid", ""),
                "chunk_id": p.get("chunk_id", ""),
                "doc_title": p.get("doc_title", ""),
                "authors": p.get("authors", ""),
                "year": p.get("year", ""),
                "type": p.get("type", ""),
                "dspace_url": p.get("dspace_url", ""),
                "heading": p.get("heading", ""),
                "page": p.get("page", 0),
                "text": p.get("text", ""),
                "snippet": (p.get("text", "") or "")[:240],
            })
        return out

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    async def _generate(self, query: str, context: str) -> str:
        if self._gen_client is None:
            return "Generation backend unavailable."
        prompt = _build_prompt(query, context)
        try:
            from google.genai import types as _genai_types
            # Tighter generation knobs to reduce latency:
            #   - cap max_output_tokens (the model would otherwise stream
            #     500-700 tokens which is the slowest part of the round trip)
            #   - low temperature for short, factual answers
            cfg = _genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=512,
            )
            response = await asyncio.to_thread(
                self._gen_client.models.generate_content,
                model=GEMINI_GEN_MODEL,
                contents=prompt,
                config=cfg,
            )
            return (getattr(response, "text", "") or "").strip()
        except Exception as e:
            logger.error(f"QdrantRAGService: generation failed: {e}")
            return f"Generation error: {e}"

    def _generate_stream(self, query: str, context: str):
        """
        Synchronous generator that yields the answer token by token.

        Wrapped in `asyncio.to_thread` from the FastAPI route so we don't
        block the event loop. Each yielded value is a partial text chunk
        as Gemini streams it. Caller is responsible for piping these to SSE.
        """
        if self._gen_client is None:
            yield "Generation backend unavailable."
            return
        prompt = _build_prompt(query, context)
        try:
            from google.genai import types as _genai_types
            cfg = _genai_types.GenerateContentConfig(
                temperature=0.2,
                max_output_tokens=512,
            )
            stream = self._gen_client.models.generate_content_stream(
                model=GEMINI_GEN_MODEL,
                contents=prompt,
                config=cfg,
            )
            for chunk in stream:
                text = getattr(chunk, "text", None)
                if text:
                    yield text
        except Exception as e:
            logger.error(f"QdrantRAGService: stream generation failed: {e}")
            yield f"\n[generation error: {e}]"

    async def search_meta_only(self, query: str, top_k: int = DEFAULT_TOP_K) -> Dict[str, Any]:
        """
        Same as `search()` but skips the LLM call. Returns just citations +
        retrieved chunks. Used by the streaming endpoint to fetch metadata
        first, then stream the answer separately.
        """
        retrieved = self._retrieve(query, top_k)
        if not retrieved:
            return {
                "citations": [],
                "retrieved_chunks": [],
                "files_searched": 0,
                "mode": "rag-empty",
            }
        citations = []
        for i, c in enumerate(retrieved, start=1):
            citations.append({
                "marker": str(i),
                "uuid": c["uuid"],
                "doc_title": c["doc_title"],
                "authors": c["authors"],
                "year": c["year"],
                "type": c["type"],
                "heading": c["heading"],
                "page": c["page"],
                "snippet": c["snippet"],
                "dspace_url": c["dspace_url"],
                "score": round(c["score"], 4),
            })
        return {
            "citations": citations,
            "retrieved_chunks": citations,
            "files_searched": len(retrieved),
            "mode": "rag",
            "_raw_chunks": retrieved,  # internal — used by stream caller for context
        }

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    async def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> Dict[str, Any]:
        global _RESULT_CACHE
        if _RESULT_CACHE is None:
            _RESULT_CACHE = OrderedDict()

        cache_key = f"{query.strip().lower()}::{top_k}"
        cached = _RESULT_CACHE.get(cache_key)
        if cached is not None:
            # Promote to MRU
            _RESULT_CACHE.move_to_end(cache_key)
            # Return a shallow copy so the caller can mutate without trashing the cache
            return {**cached, "mode": cached.get("mode", "rag") + "-cached"}

        retrieved = self._retrieve(query, top_k)
        if not retrieved:
            return {
                "answer": "No relevant passages were found in the indexed corpus.",
                "citations": [],
                "retrieved_chunks": [],
                "mode": "rag-empty",
            }

        context = _build_context(retrieved)
        answer = await self._generate(query, context)

        # Citations are the same retrieved chunks, with marker numbers added.
        # The frontend renders [N] markers in the answer as clickable links to dspace_url.
        citations = []
        for i, c in enumerate(retrieved, start=1):
            citations.append({
                "marker": str(i),
                "uuid": c["uuid"],
                "doc_title": c["doc_title"],
                "authors": c["authors"],
                "year": c["year"],
                "type": c["type"],
                "heading": c["heading"],
                "page": c["page"],
                "snippet": c["snippet"],
                "dspace_url": c["dspace_url"],
                "score": round(c["score"], 4),
            })

        result = {
            "answer": answer,
            "citations": citations,
            "retrieved_chunks": citations,  # same shape; frontend renders both panels
            "mode": "rag",
            "files_searched": len(retrieved),
        }
        # Cache for fast repeat hits
        _RESULT_CACHE[cache_key] = result
        if len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)
        return result


qdrant_rag_service = QdrantRAGService()
