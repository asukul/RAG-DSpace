"""
Topic Clustering Service.

Embeds indexed document abstracts via Ollama, clusters them with a pure-Python
k-means (cosine), and labels each cluster by tf-idf top terms from the titles.

Used by /api/topics to surface research topic clusters across the indexed corpus.
"""

import json
import logging
import math
import os
import random
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple

from services.embedding_service import embedding_service

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DOCS_FILE = os.path.join(DATA_DIR, "indexed_documents.json")
DOC_EMB_FILE = os.path.join(DATA_DIR, "document_embeddings.json")
TOPICS_FILE = os.path.join(DATA_DIR, "topic_clusters.json")

DEFAULT_K = 10
MAX_ITER = 30

_STOPWORDS = set("""
a an the and or but if then with from of for to in on at by as is are was were be been being
this that these those it its their our your we you they them he she his her i me my mine
not no nor so such than too very can will just don should now using use used uses based via
study research analysis effect role new approach novel paper method methods system systems
results model models towards toward across over under between among into out up down off
""".split())


def _cosine(a: List[float], b: List[float]) -> float:
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na == 0 or nb == 0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _normalize(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v))
    if n == 0:
        return v
    return [x / n for x in v]


def _mean(vectors: List[List[float]]) -> List[float]:
    if not vectors:
        return []
    dim = len(vectors[0])
    out = [0.0] * dim
    for v in vectors:
        for i, x in enumerate(v):
            out[i] += x
    n = len(vectors)
    return [x / n for x in out]


def _tokenize(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s-]", " ", text)
    return [t for t in text.split() if len(t) > 2 and t not in _STOPWORDS]


# ---------------------------------------------------------------------------


class TopicService:
    def __init__(self):
        self.documents: List[Dict] = []
        self.doc_embeddings: Dict[str, List[float]] = {}
        self.clusters: List[Dict] = []  # [{id, label, keywords, doc_uuids, size, centroid}]
        self.doc_to_cluster: Dict[str, int] = {}
        self.initialized = False

    # -----------------------------------------------------------------
    # Embeddings
    # -----------------------------------------------------------------

    def _doc_text(self, doc: Dict) -> str:
        title = doc.get("title", "") or ""
        abstract = doc.get("abstract", "") or ""
        return f"{title}. {abstract}"[:3000]

    def _load_doc_cache(self) -> None:
        if os.path.exists(DOC_EMB_FILE):
            try:
                with open(DOC_EMB_FILE, "r", encoding="utf-8") as f:
                    self.doc_embeddings = json.load(f)
                logger.info(f"TopicService: loaded {len(self.doc_embeddings)} cached doc embeddings")
            except Exception as e:
                logger.warning(f"TopicService: doc cache load failed: {e}")

    def _save_doc_cache(self) -> None:
        try:
            with open(DOC_EMB_FILE, "w", encoding="utf-8") as f:
                json.dump(self.doc_embeddings, f)
        except Exception as e:
            logger.warning(f"TopicService: doc cache save failed: {e}")

    def _embed_documents(self) -> None:
        if not embedding_service.initialized:
            logger.warning("TopicService: embedding_service not initialized")
            return
        pending = [d for d in self.documents if d.get("uuid") and d["uuid"] not in self.doc_embeddings]
        if not pending:
            return
        logger.info(f"TopicService: embedding {len(pending)} documents")
        for i, doc in enumerate(pending):
            text = self._doc_text(doc)
            if not text.strip():
                continue
            emb = embedding_service._embed_one(text, task_type="RETRIEVAL_DOCUMENT")
            if emb is not None:
                self.doc_embeddings[doc["uuid"]] = emb
            if (i + 1) % 25 == 0:
                logger.info(f"TopicService: embedded {i + 1}/{len(pending)}")
                self._save_doc_cache()
        self._save_doc_cache()

    # -----------------------------------------------------------------
    # K-means (cosine = euclidean on normalized vectors)
    # -----------------------------------------------------------------

    def _kmeans(self, vectors: List[List[float]], k: int, seed: int = 42) -> List[int]:
        rng = random.Random(seed)
        n = len(vectors)
        if n == 0:
            return []
        if k >= n:
            return list(range(n))

        # Normalize vectors so euclidean distance ~ 1 - cosine
        normed = [_normalize(v) for v in vectors]

        # k-means++ seeding
        centroids = [normed[rng.randrange(n)]]
        while len(centroids) < k:
            dists = []
            for v in normed:
                d_min = min(1 - _cosine(v, c) for c in centroids)
                dists.append(max(d_min, 0.0))
            total = sum(dists) or 1.0
            r = rng.random() * total
            acc = 0.0
            for i, d in enumerate(dists):
                acc += d
                if acc >= r:
                    centroids.append(normed[i])
                    break
            else:
                centroids.append(normed[-1])

        assignments = [0] * n
        for it in range(MAX_ITER):
            new_assign = []
            for v in normed:
                best_i = 0
                best_sim = -1.0
                for i, c in enumerate(centroids):
                    s = _cosine(v, c)
                    if s > best_sim:
                        best_sim = s
                        best_i = i
                new_assign.append(best_i)
            if new_assign == assignments and it > 0:
                break
            assignments = new_assign
            # Recompute centroids
            buckets: Dict[int, List[List[float]]] = defaultdict(list)
            for i, a in enumerate(assignments):
                buckets[a].append(normed[i])
            centroids = [
                _normalize(_mean(buckets[i])) if buckets[i] else centroids[i]
                for i in range(k)
            ]
        return assignments

    # -----------------------------------------------------------------
    # Labeling
    # -----------------------------------------------------------------

    def _label_clusters(self, doc_groups: Dict[int, List[Dict]]) -> Dict[int, Dict]:
        # tf-idf-ish keyword extraction across cluster title corpora
        cluster_docs: Dict[int, List[str]] = {
            cid: [d.get("title", "") for d in docs] for cid, docs in doc_groups.items()
        }
        # Term -> set of clusters that contain it
        term_clusters: Dict[str, set] = defaultdict(set)
        cluster_term_counts: Dict[int, Counter] = {}
        for cid, titles in cluster_docs.items():
            counter: Counter = Counter()
            for t in titles:
                for tok in _tokenize(t):
                    counter[tok] += 1
                    term_clusters[tok].add(cid)
            cluster_term_counts[cid] = counter

        n_clusters = len(cluster_docs)
        labels = {}
        for cid, counter in cluster_term_counts.items():
            scored = []
            for term, cnt in counter.items():
                if cnt < 2 and len(cluster_docs[cid]) > 3:
                    continue
                # idf-ish: prefer terms specific to this cluster
                idf = math.log(1 + n_clusters / len(term_clusters[term]))
                scored.append((term, cnt * idf))
            scored.sort(key=lambda x: x[1], reverse=True)
            keywords = [t for t, _ in scored[:8]]
            label = ", ".join(keywords[:3]) if keywords else f"Topic {cid}"
            labels[cid] = {"label": label, "keywords": keywords}
        return labels

    # -----------------------------------------------------------------
    # Build
    # -----------------------------------------------------------------

    def build(self, k: int = DEFAULT_K) -> None:
        try:
            with open(DOCS_FILE, "r", encoding="utf-8") as f:
                self.documents = json.load(f)
        except FileNotFoundError:
            logger.warning(f"TopicService: {DOCS_FILE} not found")
            return

        self._load_doc_cache()
        self._embed_documents()

        # Filter to docs that have an embedding
        valid_docs = [d for d in self.documents if d.get("uuid") in self.doc_embeddings]
        vectors = [self.doc_embeddings[d["uuid"]] for d in valid_docs]
        if not vectors:
            logger.warning("TopicService: no document vectors")
            return

        k_eff = min(k, len(vectors))
        assignments = self._kmeans(vectors, k_eff)

        # Group docs per cluster
        doc_groups: Dict[int, List[Dict]] = defaultdict(list)
        for doc, cid in zip(valid_docs, assignments):
            doc_groups[cid].append(doc)
            self.doc_to_cluster[doc["uuid"]] = cid

        labels = self._label_clusters(doc_groups)

        self.clusters = []
        for cid, docs in sorted(doc_groups.items()):
            info = labels.get(cid, {"label": f"Topic {cid}", "keywords": []})
            self.clusters.append({
                "id": cid,
                "label": info["label"],
                "keywords": info["keywords"],
                "size": len(docs),
                "doc_uuids": [d.get("uuid") for d in docs],
                "sample_titles": [d.get("title", "") for d in docs[:5]],
            })

        # Persist
        try:
            with open(TOPICS_FILE, "w", encoding="utf-8") as f:
                json.dump({"k": k_eff, "clusters": self.clusters}, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"TopicService: topic file save failed: {e}")

        self.initialized = True
        logger.info(f"TopicService: built {len(self.clusters)} clusters from {len(valid_docs)} docs")

    # -----------------------------------------------------------------
    # Query
    # -----------------------------------------------------------------

    def list_topics(self) -> List[Dict]:
        return [
            {k: v for k, v in c.items() if k != "doc_uuids"}
            for c in self.clusters
        ]

    def topic_documents(self, topic_id: int) -> Dict:
        for c in self.clusters:
            if c["id"] == topic_id:
                docs = [d for d in self.documents if d.get("uuid") in c["doc_uuids"]]
                return {
                    "id": c["id"],
                    "label": c["label"],
                    "keywords": c["keywords"],
                    "documents": docs,
                }
        return {"id": topic_id, "label": None, "keywords": [], "documents": []}

    def stats(self) -> Dict:
        return {
            "total_documents": len(self.documents),
            "embedded_documents": len(self.doc_embeddings),
            "clusters": len(self.clusters),
            "labels": [c["label"] for c in self.clusters],
        }


topic_service = TopicService()
