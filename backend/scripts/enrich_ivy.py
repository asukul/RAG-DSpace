"""Scrape Ivy College of Business faculty profile pages and extract
research interests / bio / expertise / title / department into
data/enriched_ivy.json.

Usage:  python scripts/enrich_ivy.py
"""
from __future__ import annotations

import json
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup, Tag

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "ivy_faculty.json"
OUT = ROOT / "data" / "enriched_ivy.json"

UA = "ISU-RAG-Indexer/1.0 (academic research)"
HEADERS = {"User-Agent": UA}
TIMEOUT = 15.0
MAX_WORKERS = 3
SAVE_EVERY = 25

SECTION_HEADINGS = {
    "bio", "biography", "about",
    "expertise", "areas of expertise",
    "research", "research interests", "research areas",
    "academic history", "education",
    "selected publications", "publications",
    "teaching", "courses", "courses taught",
    "awards", "honors", "service",
}

BIO_KEYS = {"bio", "biography", "about"}
EXPERTISE_KEYS = {"expertise", "areas of expertise"}
RESEARCH_KEYS = {"research", "research interests", "research areas"}


def fetch(url: str, client: httpx.Client) -> str | None:
    for attempt in range(2):
        try:
            r = client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code in (404, 410):
                return None
        except (httpx.TransportError, httpx.TimeoutException):
            if attempt == 0:
                time.sleep(0.5)
                continue
            return None
    return None


def _get_field(soup: BeautifulSoup, label: str) -> str:
    """Extract text after a <strong>Label:</strong> marker."""
    strong = soup.find("strong", string=lambda s: s and label.lower() in s.lower())
    if not strong:
        return ""
    parent = strong.parent
    if not parent:
        return ""
    txt = parent.get_text(" ", strip=True)
    # strip "Label:" prefix
    for sep in (":",):
        if sep in txt:
            txt = txt.split(sep, 1)[1].strip()
            break
    return txt


def _list_items_from_siblings(nodes: list[Tag]) -> list[str]:
    items: list[str] = []
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        if n.name == "ul" or n.name == "ol":
            for li in n.find_all("li", recursive=False):
                t = li.get_text(" ", strip=True)
                if t:
                    items.append(t)
        elif n.name == "p":
            t = n.get_text(" ", strip=True)
            # split on newlines/semicolons if it looks like a list
            if t and "\n" in t:
                for part in t.split("\n"):
                    part = part.strip(" \u2022-*")
                    if part:
                        items.append(part)
            elif t:
                items.append(t)
    return items


def _paragraph_text_from_siblings(nodes: list[Tag], max_paras: int = 3) -> str:
    paras: list[str] = []
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        if n.name == "p":
            t = n.get_text(" ", strip=True)
            if t:
                paras.append(t)
        elif n.name in ("ul", "ol"):
            for li in n.find_all("li", recursive=False):
                t = li.get_text(" ", strip=True)
                if t:
                    paras.append(t)
        if len(paras) >= max_paras:
            break
    return "\n".join(paras[:max_paras])


def parse_profile(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()

    title = _get_field(soup, "Title")
    department = _get_field(soup, "Department")

    # Ivy templates sometimes split sections across multiple parent <div>s
    # (e.g., Bio+AcademicHistory in one div, Expertise+Publications in another).
    # Collect every parent div that contains at least one h3 we recognize,
    # then walk each in document order and bucket siblings by h3.
    sections: dict[str, list[Tag]] = {}
    seen_containers: list[Tag] = []
    for h3 in soup.find_all("h3"):
        label = h3.get_text(" ", strip=True).lower()
        if label not in SECTION_HEADINGS:
            continue
        parent = h3.parent
        if parent is None or parent in seen_containers:
            continue
        seen_containers.append(parent)

    bio_container: Tag | None = seen_containers[0] if seen_containers else None

    for container in seen_containers:
        current_key: str | None = None
        for child in container.children:
            if not isinstance(child, Tag):
                continue
            if child.name == "h3":
                lbl = child.get_text(" ", strip=True).lower()
                if lbl in SECTION_HEADINGS:
                    current_key = lbl
                    sections.setdefault(current_key, [])
                else:
                    current_key = None
                continue
            if current_key is not None:
                sections[current_key].append(child)

    # Bio text
    bio_text = ""
    for k in BIO_KEYS:
        if k in sections:
            bio_text = _paragraph_text_from_siblings(sections[k], max_paras=5)
            if bio_text:
                break

    # Expertise list
    expertise: list[str] = []
    for k in EXPERTISE_KEYS:
        if k in sections:
            expertise = _list_items_from_siblings(sections[k])
            if expertise:
                break

    # Research interests list
    research: list[str] = []
    for k in RESEARCH_KEYS:
        if k in sections:
            research = _list_items_from_siblings(sections[k])
            if research:
                break

    # Fallback: if no research/expertise, use expertise as research signal
    if not research and expertise:
        research = list(expertise)

    # Fallback bio: concatenate any non-bio section text we captured
    # (e.g., academic history) only if it's short-ish and looks meaningful.
    # We intentionally do NOT fall back to page-wide <p> scraping because the
    # Ivy template wraps the page footer in the same outer div.
    if not bio_text:
        fallback_parts: list[str] = []
        if expertise:
            fallback_parts.append("Expertise: " + "; ".join(expertise))
        if research and research != expertise:
            fallback_parts.append("Research: " + "; ".join(research))
        bio_text = "\n".join(fallback_parts)

    return {
        "title": title,
        "department": department,
        "bio": bio_text,
        "expertise": expertise,
        "research_interests": research,
    }


def load_existing() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(data: dict) -> None:
    # Dropbox on Windows occasionally holds a short lock on files during sync,
    # which breaks atomic rename. Retry a few times, then fall back to direct write.
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(payload, encoding="utf-8")
    last_err: Exception | None = None
    for _ in range(5):
        try:
            tmp.replace(OUT)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(0.5)
    # Fallback: write directly to OUT.
    try:
        OUT.write_text(payload, encoding="utf-8")
        try:
            tmp.unlink()
        except OSError:
            pass
        return
    except PermissionError:
        if last_err:
            raise last_err
        raise


def worker(fac: dict, client: httpx.Client) -> tuple[str, dict | None]:
    time.sleep(random.uniform(0.2, 0.5))
    html = fetch(fac["profile_url"], client)
    if html is None:
        return fac["id"], None
    try:
        parsed = parse_profile(html)
    except Exception as e:
        return fac["id"], {"error": f"parse_error: {e}"}
    parsed["source_url"] = fac["profile_url"]
    parsed["extracted_at"] = datetime.now(timezone.utc).isoformat()
    return fac["id"], parsed


def main() -> int:
    faculty = json.loads(SRC.read_text(encoding="utf-8"))
    enriched = load_existing()

    todo = [f for f in faculty if f["id"] not in enriched]
    print(f"Total faculty: {len(faculty)}  already done: {len(enriched)}  todo: {len(todo)}", flush=True)

    successes = 0
    failures = 0
    processed_since_save = 0

    with httpx.Client(http2=False) as client:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futs = {ex.submit(worker, f, client): f for f in todo}
            for i, fut in enumerate(as_completed(futs), 1):
                fac = futs[fut]
                try:
                    fid, result = fut.result()
                except Exception as e:
                    fid = fac["id"]
                    result = None
                    print(f"[{i}] {fid} exception: {e}", flush=True)

                if result is None:
                    failures += 1
                    enriched[fid] = {
                        "title": "",
                        "department": "",
                        "bio": "",
                        "expertise": [],
                        "research_interests": [],
                        "source_url": fac["profile_url"],
                        "extracted_at": datetime.now(timezone.utc).isoformat(),
                        "error": "fetch_failed",
                    }
                else:
                    successes += 1
                    enriched[fid] = result

                processed_since_save += 1
                if i % 25 == 0:
                    print(f"[{i}/{len(todo)}] ok={successes} fail={failures} last={fid}", flush=True)
                if processed_since_save >= SAVE_EVERY:
                    save(enriched)
                    processed_since_save = 0

    save(enriched)

    # Final summary
    total = len(enriched)
    non_empty_research = sum(
        1 for v in enriched.values() if v.get("research_interests")
    )
    with_bio = sum(1 for v in enriched.values() if v.get("bio"))
    failed = sum(1 for v in enriched.values() if v.get("error"))
    ok = total - failed
    print("=" * 60)
    print(f"Total: {total}")
    print(f"Successful: {ok}")
    print(f"Failed: {failed}")
    print(f"Non-empty research_interests: {non_empty_research}")
    print(f"With bio text: {with_bio}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
