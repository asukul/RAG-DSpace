"""
Collaboration Network Service.

Builds two graphs from indexed_documents.json:
  1. Co-authorship graph  — nodes = canonical author names, edges = shared papers
  2. Advisor-student graph — directed edges advisor -> student, from theses/dissertations/CCs

Author/advisor strings come in many forms ("Townsend, Anthony" / "Anthony Townsend" /
"Townsend, Anthony M") so a normalizer collapses them to a canonical "Lastname, Firstname"
key, then a faculty matcher links them to faculty.json records when possible.
"""

import json
import logging
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DOCS_FILE = os.path.join(DATA_DIR, "indexed_documents.json")
FACULTY_FILE = os.path.join(DATA_DIR, "faculty.json")


# ---------------------------------------------------------------------------
# Name normalization
# ---------------------------------------------------------------------------

_INITIAL_RE = re.compile(r"\b([A-Z])\.?\s*$")
_PUNCT_RE = re.compile(r"[^\w\s,'-]")


def normalize_name(raw: str) -> Optional[str]:
    """
    Collapse a name string to canonical form: "lastname|firstinitial".

    Examples:
      "Townsend, Anthony"      -> "townsend|a"
      "Anthony Townsend"       -> "townsend|a"
      "Townsend, Anthony M"    -> "townsend|a"
      "Sukul, Adisak"          -> "sukul|a"

    Returns None if unparseable.
    """
    if not raw:
        return None
    s = _PUNCT_RE.sub(" ", raw).strip()
    s = re.sub(r"\s+", " ", s)
    if not s:
        return None

    if "," in raw:
        # "Lastname, Firstname Middle"
        last, _, rest = raw.partition(",")
        last = _PUNCT_RE.sub("", last).strip().lower()
        first = _PUNCT_RE.sub(" ", rest).strip()
        first_initial = first[0].lower() if first else ""
    else:
        # "Firstname Middle Lastname"
        parts = s.split()
        if len(parts) == 1:
            return f"{parts[0].lower()}|"
        last = parts[-1].lower()
        first_initial = parts[0][0].lower()

    if not last:
        return None
    return f"{last}|{first_initial}"


def display_name(raw: str) -> str:
    """Pick a clean display form for a raw author string."""
    if "," in raw:
        last, _, first = raw.partition(",")
        return f"{first.strip()} {last.strip()}".strip()
    return raw.strip()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class CollaborationService:
    def __init__(self):
        self.documents: List[Dict] = []
        self.faculty_lookup: Dict[str, Dict] = {}  # normalized key -> faculty record
        self.coauthor_edges: Dict[Tuple[str, str], int] = {}  # (a,b) sorted -> weight
        self.author_papers: Dict[str, List[str]] = defaultdict(list)  # key -> [doc_uuid]
        self.author_display: Dict[str, str] = {}  # canonical key -> nicest display name
        self.advisor_edges: Dict[Tuple[str, str], int] = defaultdict(int)  # (advisor, student) -> weight
        self.advisor_students: Dict[str, Set[str]] = defaultdict(set)
        self.student_advisors: Dict[str, Set[str]] = defaultdict(set)
        self.initialized = False

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Load documents + faculty and compute both graphs."""
        try:
            with open(DOCS_FILE, "r", encoding="utf-8") as f:
                self.documents = json.load(f)
        except FileNotFoundError:
            logger.warning(f"CollaborationService: {DOCS_FILE} not found")
            return

        try:
            with open(FACULTY_FILE, "r", encoding="utf-8") as f:
                faculty = json.load(f)
        except FileNotFoundError:
            faculty = []

        # Build faculty lookup keyed by normalized name
        for fac in faculty:
            key = normalize_name(fac.get("name", ""))
            if key:
                # First write wins; CS faculty are listed first so they take priority
                self.faculty_lookup.setdefault(key, fac)

        # Walk documents
        for doc in self.documents:
            uuid = doc.get("uuid") or doc.get("url", "")
            authors_raw = doc.get("authors", []) or []
            advisors_raw = doc.get("advisors", []) or []

            author_keys: List[str] = []
            for a in authors_raw:
                k = normalize_name(a)
                if not k:
                    continue
                author_keys.append(k)
                self.author_papers[k].append(uuid)
                # Prefer the longest seen display form (more info)
                disp = display_name(a)
                if len(disp) > len(self.author_display.get(k, "")):
                    self.author_display[k] = disp

            # Co-author edges (every unordered pair)
            unique_authors = list(dict.fromkeys(author_keys))
            for i in range(len(unique_authors)):
                for j in range(i + 1, len(unique_authors)):
                    edge = tuple(sorted((unique_authors[i], unique_authors[j])))
                    self.coauthor_edges[edge] = self.coauthor_edges.get(edge, 0) + 1

            # Advisor edges (advisor -> each author/student)
            advisor_keys: List[str] = []
            for a in advisors_raw:
                k = normalize_name(a)
                if not k:
                    continue
                advisor_keys.append(k)
                disp = display_name(a)
                if len(disp) > len(self.author_display.get(k, "")):
                    self.author_display[k] = disp

            for adv in advisor_keys:
                for stu in unique_authors:
                    if adv == stu:
                        continue
                    self.advisor_edges[(adv, stu)] += 1
                    self.advisor_students[adv].add(stu)
                    self.student_advisors[stu].add(adv)

        self.initialized = True
        logger.info(
            f"CollaborationService: built graph — "
            f"{len(self.author_display)} people, "
            f"{len(self.coauthor_edges)} co-author edges, "
            f"{len(self.advisor_edges)} advisor edges"
        )

    # ------------------------------------------------------------------
    # Query helpers
    # ------------------------------------------------------------------

    def _resolve(self, name_or_id: str) -> Optional[str]:
        """Resolve a query string (name or faculty id) to a canonical key."""
        if not name_or_id:
            return None
        # Try direct normalize
        key = normalize_name(name_or_id)
        if key and (key in self.author_display or key in self.faculty_lookup):
            return key
        # Try faculty id lookup
        for k, fac in self.faculty_lookup.items():
            if fac.get("id") == name_or_id:
                return k
        return key  # may not exist in graph but normalized

    def _person(self, key: str) -> Dict:
        fac = self.faculty_lookup.get(key)
        return {
            "key": key,
            "name": self.author_display.get(key) or (fac.get("name") if fac else key),
            "faculty_id": fac.get("id") if fac else None,
            "department": (fac.get("department") if fac else None),
            "paper_count": len(set(self.author_papers.get(key, []))),
        }

    def coauthors_of(self, name_or_id: str, top_k: int = 20) -> Dict:
        """Return co-authors of a researcher with edge weights."""
        key = self._resolve(name_or_id)
        if not key:
            return {"researcher": None, "coauthors": []}
        results = []
        for (a, b), weight in self.coauthor_edges.items():
            if a == key:
                results.append((b, weight))
            elif b == key:
                results.append((a, weight))
        results.sort(key=lambda x: x[1], reverse=True)
        return {
            "researcher": self._person(key),
            "coauthors": [
                {**self._person(k), "shared_papers": w} for k, w in results[:top_k]
            ],
        }

    def students_of(self, name_or_id: str) -> Dict:
        """Return students an advisor has supervised."""
        key = self._resolve(name_or_id)
        if not key:
            return {"advisor": None, "students": []}
        students = sorted(
            self.advisor_students.get(key, set()),
            key=lambda k: self.advisor_edges.get((key, k), 0),
            reverse=True,
        )
        return {
            "advisor": self._person(key),
            "students": [
                {**self._person(s), "shared_papers": self.advisor_edges.get((key, s), 0)}
                for s in students
            ],
        }

    def advisors_of(self, name_or_id: str) -> Dict:
        """Return advisors of a student."""
        key = self._resolve(name_or_id)
        if not key:
            return {"student": None, "advisors": []}
        advisors = sorted(
            self.student_advisors.get(key, set()),
            key=lambda k: self.advisor_edges.get((k, key), 0),
            reverse=True,
        )
        return {
            "student": self._person(key),
            "advisors": [
                {**self._person(a), "shared_papers": self.advisor_edges.get((a, key), 0)}
                for a in advisors
            ],
        }

    def graph(
        self,
        researcher: Optional[str] = None,
        max_nodes: int = 75,
        min_weight: int = 1,
    ) -> Dict:
        """
        Return a graph payload (nodes + edges) for visualization.

        If `researcher` is given: subgraph centered on that person (1-hop neighbors).
        Otherwise: top `max_nodes` most-connected authors and their edges.
        """
        if researcher:
            key = self._resolve(researcher)
            if not key:
                return {"nodes": [], "edges": [], "center": None}
            neighbors: Set[str] = {key}
            edges_out = []
            for (a, b), w in self.coauthor_edges.items():
                if w < min_weight:
                    continue
                if a == key or b == key:
                    neighbors.add(a)
                    neighbors.add(b)
                    edges_out.append({"source": a, "target": b, "weight": w, "kind": "coauthor"})
            # Add advisor edges touching key
            for (adv, stu), w in self.advisor_edges.items():
                if w < min_weight:
                    continue
                if adv == key or stu == key:
                    neighbors.add(adv)
                    neighbors.add(stu)
                    edges_out.append({"source": adv, "target": stu, "weight": w, "kind": "advisor"})
            nodes = [self._person(k) for k in neighbors]
            return {"center": self._person(key), "nodes": nodes, "edges": edges_out}

        # Global view: top connected
        degree: Dict[str, int] = defaultdict(int)
        for (a, b), w in self.coauthor_edges.items():
            degree[a] += w
            degree[b] += w
        for (a, b), w in self.advisor_edges.items():
            degree[a] += w
            degree[b] += w
        top_keys = set(
            k for k, _ in sorted(degree.items(), key=lambda x: x[1], reverse=True)[:max_nodes]
        )
        nodes = [self._person(k) for k in top_keys]
        edges_out = []
        for (a, b), w in self.coauthor_edges.items():
            if w >= min_weight and a in top_keys and b in top_keys:
                edges_out.append({"source": a, "target": b, "weight": w, "kind": "coauthor"})
        for (a, b), w in self.advisor_edges.items():
            if w >= min_weight and a in top_keys and b in top_keys:
                edges_out.append({"source": a, "target": b, "weight": w, "kind": "advisor"})
        return {"center": None, "nodes": nodes, "edges": edges_out}

    def stats(self) -> Dict:
        return {
            "documents": len(self.documents),
            "people": len(self.author_display),
            "faculty_matched": sum(1 for k in self.author_display if k in self.faculty_lookup),
            "coauthor_edges": len(self.coauthor_edges),
            "advisor_edges": len(self.advisor_edges),
        }


collaboration_service = CollaborationService()
