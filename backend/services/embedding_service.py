"""
Embedding Service for semantic faculty matching.

Supports three backends:
- Vertex AI text-embedding-005 (cloud, ADC/service-account, set EMBEDDING_BACKEND=vertex)
- Ollama (local, e.g. nomic-embed-text — unlimited, set EMBEDDING_BACKEND=ollama)
- Gemini Developer API (legacy fallback, kept only if explicitly requested)

Builds vector embeddings of faculty research profiles, then finds
semantically similar faculty for any query via cosine similarity.
"""

import json
import hashlib
import math
import logging
import os
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

EMBEDDING_BACKEND = os.getenv("EMBEDDING_BACKEND", "vertex").lower()  # "vertex" | "ollama" | "gemini"
VERTEX_EMBEDDING_MODEL = os.getenv("VERTEX_EMBEDDING_MODEL", "text-embedding-005")
VERTEX_EMBEDDING_DIM = int(os.getenv("VERTEX_EMBEDDING_DIM", "768"))
GCP_PROJECT = os.getenv("GCP_PROJECT", "rag-dspace")
GCP_LOCATION = os.getenv("GCP_LOCATION", "us-central1")
GEMINI_EMBEDDING_MODEL = "models/gemini-embedding-001"
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "faculty_embeddings.json")


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _faculty_to_text(faculty: Dict) -> str:
    """Build a rich text representation of a faculty member for embedding."""
    parts = [faculty.get("name", "")]

    title = faculty.get("title", "")
    if title:
        parts.append(title)

    rank = faculty.get("rank", "")
    if rank and rank != title:
        parts.append(rank)

    group = faculty.get("group", "")
    if group:
        parts.append(f"Research group: {group}")

    interests = faculty.get("research_interests", [])
    if interests:
        parts.append(f"Research interests: {', '.join(interests)}")

    expertise = faculty.get("expertise", [])
    if expertise:
        extra = [e for e in expertise if e not in interests]
        if extra:
            parts.append(f"Expertise: {', '.join(extra)}")

    areas = faculty.get("research_areas", [])
    if areas:
        extra = [a for a in areas if a not in interests]
        if extra:
            parts.append(f"Research areas: {', '.join(extra)}")

    dept = faculty.get("department", "")
    if dept:
        parts.append(dept)

    college = faculty.get("college", "")
    if college and college not in dept:
        parts.append(college)

    courses = faculty.get("courses_taught", [])
    if courses:
        parts.append(f"Teaches: {', '.join(courses)}")

    bio = faculty.get("bio", "")
    if bio:
        # Cap bio length to keep embedding text bounded
        bio_text = bio[:1500].strip()
        parts.append(f"Biography: {bio_text}")

    return ". ".join(parts)


def _compute_faculty_hash(faculty_data: List[Dict]) -> str:
    """Hash the full embedding text per faculty so any field change invalidates."""
    sig = []
    for f in sorted(faculty_data, key=lambda x: x.get("id", "")):
        sig.append(f"{f.get('id', '')}::{_faculty_to_text(f)}")
    return hashlib.md5("|".join(sig).encode()).hexdigest()


def _ollama_embed(text: str, model: str = OLLAMA_EMBEDDING_MODEL, task: str = "document") -> Optional[List[float]]:
    """
    Call local Ollama embeddings endpoint. Returns None on failure.

    nomic-embed-text v1 requires task-specific prefixes:
    - "search_document: <text>" for indexing
    - "search_query: <text>" for queries
    """
    if "nomic-embed" in model.lower():
        prefix = "search_query: " if task == "query" else "search_document: "
        text = prefix + text
    try:
        body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/embeddings",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return data.get("embedding")
    except Exception as e:
        logger.debug(f"Ollama embed failed: {e}")
        return None


def _ollama_available() -> bool:
    """Check if Ollama server is reachable."""
    try:
        with urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


class EmbeddingService:
    """Manages faculty embeddings and semantic similarity search."""

    def __init__(self):
        self.genai = None  # legacy google.generativeai module (if used)
        self.vertex_client = None  # google.genai.Client configured for Vertex
        self.initialized = False
        self.backend = "none"  # "vertex" | "ollama" | "gemini" | "none"
        self.faculty_embeddings: Dict[str, List[float]] = {}
        self.faculty_lookup: Dict[str, Dict] = {}
        self._cache_hash: Optional[str] = None

    def configure(self, genai_module=None, api_key: Optional[str] = None, vertex_client=None) -> None:
        """
        Configure embedding backend.

        Backwards-compatible signature: callers may pass (genai_module, api_key)
        for the legacy Gemini Developer API path. New callers should pass
        vertex_client (a google.genai.Client configured with vertexai=True),
        or just rely on EMBEDDING_BACKEND=vertex which will lazily build one.
        """
        # 1. Explicit Ollama
        if EMBEDDING_BACKEND == "ollama" or (EMBEDDING_BACKEND == "auto" and _ollama_available()):
            if _ollama_available():
                self.backend = "ollama"
                self.initialized = True
                logger.info(f"EmbeddingService: Using Ollama at {OLLAMA_HOST} (model: {OLLAMA_EMBEDDING_MODEL})")
                return
            logger.warning("EmbeddingService: Ollama requested but not reachable")

        # 2. Vertex AI (new default)
        if EMBEDDING_BACKEND == "vertex":
            client = vertex_client
            if client is None:
                try:
                    from google import genai as _google_genai
                    client = _google_genai.Client(
                        vertexai=True,
                        project=GCP_PROJECT,
                        location=GCP_LOCATION,
                    )
                except Exception as e:
                    logger.error(f"EmbeddingService: Failed to build Vertex client: {e}")
                    client = None
            if client is not None:
                self.vertex_client = client
                self.backend = "vertex"
                self.initialized = True
                logger.info(
                    f"EmbeddingService: Using Vertex AI ({VERTEX_EMBEDDING_MODEL}) "
                    f"project={GCP_PROJECT} location={GCP_LOCATION}"
                )
                return
            logger.warning("EmbeddingService: Vertex backend requested but client unavailable")

        # 3. Legacy Gemini Developer API (fallback only)
        if EMBEDDING_BACKEND == "gemini" and genai_module and api_key:
            self.genai = genai_module
            self.backend = "gemini"
            self.initialized = True
            logger.info("EmbeddingService: Using legacy Gemini Developer API")
            return

        logger.warning("EmbeddingService: No backend available, semantic matching disabled")

    def _vertex_embed(self, texts: List[str], task_type: str) -> Optional[List[List[float]]]:
        """Call Vertex AI text-embedding-005 via the google-genai client."""
        if self.vertex_client is None:
            return None
        try:
            from google.genai import types as _genai_types
            result = self.vertex_client.models.embed_content(
                model=VERTEX_EMBEDDING_MODEL,
                contents=texts,
                config=_genai_types.EmbedContentConfig(
                    task_type=task_type,
                    output_dimensionality=VERTEX_EMBEDDING_DIM,
                ),
            )
            return [list(e.values) for e in result.embeddings]
        except Exception as e:
            logger.debug(f"Vertex embed failed: {e}")
            return None

    def _embed_one(self, text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[float]]:
        """Embed a single text with the active backend."""
        ollama_task = "query" if task_type == "RETRIEVAL_QUERY" else "document"
        if self.backend == "ollama":
            return _ollama_embed(text, task=ollama_task)
        if self.backend == "vertex":
            embs = self._vertex_embed([text], task_type)
            return embs[0] if embs else None
        if self.backend == "gemini" and self.genai:
            try:
                result = self.genai.embed_content(
                    model=GEMINI_EMBEDDING_MODEL,
                    content=text,
                    task_type=task_type,
                )
                return result["embedding"]
            except Exception as e:
                logger.debug(f"Gemini embed failed: {e}")
                return None
        return None

    def _embed_batch(self, texts: List[str], task_type: str = "RETRIEVAL_DOCUMENT") -> Optional[List[List[float]]]:
        """Embed a batch of texts with the active backend."""
        ollama_task = "query" if task_type == "RETRIEVAL_QUERY" else "document"
        if self.backend == "ollama":
            # Ollama has no batch endpoint — call sequentially
            results = []
            for t in texts:
                emb = _ollama_embed(t, task=ollama_task)
                if emb is None:
                    return None
                results.append(emb)
            return results
        if self.backend == "vertex":
            return self._vertex_embed(texts, task_type)
        if self.backend == "gemini" and self.genai:
            try:
                result = self.genai.embed_content(
                    model=GEMINI_EMBEDDING_MODEL,
                    content=texts,
                    task_type=task_type,
                )
                return result["embedding"]
            except Exception:
                return None
        return None

    def _load_cache(self, expected_hash: str) -> bool:
        """Load cached embeddings. Returns True if fully fresh (no rebuild needed)."""
        try:
            if not os.path.exists(CACHE_FILE):
                return False
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            cached_embeddings = cache.get("embeddings", {})
            self.faculty_embeddings = cached_embeddings
            if cache.get("hash") != expected_hash:
                logger.info(f"EmbeddingService: Loaded {len(cached_embeddings)} cached embeddings (incremental — will fill gaps)")
                return False
            self._cache_hash = expected_hash
            logger.info(f"EmbeddingService: Loaded {len(self.faculty_embeddings)} cached embeddings (full match)")
            return True
        except Exception as e:
            logger.warning(f"EmbeddingService: Cache load failed: {e}")
            return False

    def _save_cache(self, data_hash: str) -> None:
        """Save embeddings to disk."""
        try:
            os.makedirs(os.path.dirname(CACHE_FILE), exist_ok=True)
            cache = {"hash": data_hash, "embeddings": self.faculty_embeddings}
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache, f)
            logger.info(f"EmbeddingService: Saved {len(self.faculty_embeddings)} embeddings to cache")
        except Exception as e:
            logger.error(f"EmbeddingService: Cache save failed: {e}")

    def build_index(self, faculty_data: List[Dict]) -> None:
        """
        Build or reload the faculty embedding index.
        Uses cached embeddings if faculty data hasn't changed.
        """
        if not self.initialized:
            logger.warning("EmbeddingService: Not initialized, skipping index build")
            return

        self.faculty_lookup = {f["id"]: f for f in faculty_data}
        data_hash = _compute_faculty_hash(faculty_data)

        if self._load_cache(data_hash):
            # Remove stale entries for faculty no longer present
            current_ids = set(self.faculty_lookup.keys())
            stale = [k for k in self.faculty_embeddings if k not in current_ids]
            for k in stale:
                del self.faculty_embeddings[k]
            return

        logger.info(f"EmbeddingService: Computing embeddings for {len(faculty_data)} faculty members")

        # Build texts for all faculty
        texts = []
        ids = []
        for f in faculty_data:
            texts.append(_faculty_to_text(f))
            ids.append(f["id"])

        # Skip already-cached entries (incremental builds)
        pending = [(fid, t) for fid, t in zip(ids, texts) if fid not in self.faculty_embeddings]
        if not pending:
            logger.info("EmbeddingService: All faculty already embedded")
            self._save_cache(data_hash)
            return
        logger.info(f"EmbeddingService: {len(pending)} faculty need embedding ({len(self.faculty_embeddings)} already cached)")

        # Choose batch size based on backend
        # - Ollama: 1 (sequential, no rate limit)
        # - Vertex: 25 (text-embedding-005 allows up to 250 per request)
        # - Gemini (legacy): 5 (small batches to stay within free-tier rate limits)
        if self.backend == "ollama":
            batch_size = 1
        elif self.backend == "vertex":
            batch_size = 25
        else:
            batch_size = 5
        total_batches = (len(pending) + batch_size - 1) // batch_size
        for batch_num, i in enumerate(range(0, len(pending), batch_size)):
            batch = pending[i : i + batch_size]
            batch_ids = [b[0] for b in batch]
            batch_texts = [b[1] for b in batch]
            success = False
            for attempt in range(4):
                embeddings = self._embed_batch(batch_texts)
                if embeddings is not None:
                    for fid, emb in zip(batch_ids, embeddings):
                        self.faculty_embeddings[fid] = emb
                    if (batch_num + 1) % 10 == 0 or batch_num == 0:
                        logger.info(f"EmbeddingService: Batch {batch_num + 1}/{total_batches} done")
                    success = True
                    break
                # Backoff before retry (longer for rate-limited backends)
                wait = (2 ** (attempt + 1)) if self.backend == "gemini" else 2
                time.sleep(wait)
            if not success:
                logger.error(f"EmbeddingService: Batch {batch_num + 1} failed after retries")
            # Save progress every 10 batches
            if (batch_num + 1) % 10 == 0:
                self._save_cache(data_hash)
            # Rate limit pause between batches (only for legacy Gemini Dev API)
            if self.backend == "gemini" and batch_num < total_batches - 1:
                time.sleep(1.5)

        self._save_cache(data_hash)
        logger.info(f"EmbeddingService: Index built with {len(self.faculty_embeddings)} embeddings")

    def search(self, query: str, top_k: int = 8, threshold: float = 0.3) -> List[Tuple[Dict, float]]:
        """
        Find faculty semantically similar to a query.

        Returns list of (faculty_dict, similarity_score) tuples,
        sorted by descending similarity, filtered by threshold.
        """
        if not self.initialized or not self.faculty_embeddings:
            return []

        query_embedding = self._embed_one(query, task_type="RETRIEVAL_QUERY")
        if query_embedding is None:
            return []

        scored = []
        for fid, emb in self.faculty_embeddings.items():
            sim = _cosine_similarity(query_embedding, emb)
            if sim >= threshold:
                faculty = self.faculty_lookup.get(fid)
                if faculty:
                    scored.append((faculty, round(sim, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def refresh(self, faculty_data: List[Dict]) -> None:
        """Re-build the index (e.g. after admin changes to faculty)."""
        self.faculty_lookup = {f["id"]: f for f in faculty_data}
        self._cache_hash = None  # Force re-embed
        self.faculty_embeddings.clear()
        self.build_index(faculty_data)


# Singleton instance
embedding_service = EmbeddingService()
