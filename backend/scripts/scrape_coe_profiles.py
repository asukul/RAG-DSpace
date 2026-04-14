"""Scrape ISU College of Engineering faculty profiles to enrich research signal.

Reads data/coe_faculty.json, fetches each profile_url politely, extracts
research interests / expertise / bio / extended title, and writes
data/enriched_coe.json incrementally.
"""
from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE = Path("D:/Dropbox/RAG-DSpace/isu-research-search/backend")
SRC = BASE / "data" / "coe_faculty.json"
OUT = BASE / "data" / "enriched_coe.json"

HEADERS = {"User-Agent": "ISU-RAG-Indexer/1.0 (academic research)"}
TIMEOUT = 15.0
MAX_WORKERS = 3
SAVE_EVERY = 25

# Section heading variants on the CoE WordPress site
INTEREST_HEADINGS = {"interests", "research interests", "areas of expertise", "expertise"}
BIO_HEADINGS = {"information", "biography", "bio", "about"}
SRA_HEADINGS = {"primary strategic research area", "strategic research area", "research area"}
TITLE_HEADINGS = {"title(s)", "title", "titles"}


def _norm(s: str) -> str:
    return " ".join(s.split()).strip().lower()


def _section_after(soup: BeautifulSoup, heading_set: set[str]):
    """Yield sibling tags following an h2/h3 whose text matches heading_set,
    stopping at the next h2/h3."""
    for h in soup.find_all(["h2", "h3"]):
        if _norm(h.get_text(" ", strip=True)).rstrip(":") in heading_set:
            sib = h.find_next_sibling()
            while sib and sib.name not in ("h2", "h3"):
                yield sib
                sib = sib.find_next_sibling()
            return


def extract(html: str, source_url: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup.find("article") or soup

    # Research interests: anchors under /people/interest/
    research_interests: list[str] = []
    for a in main.find_all("a", href=True):
        if "/people/interest/" in a["href"]:
            txt = a.get_text(" ", strip=True)
            if txt and txt not in research_interests:
                research_interests.append(txt)

    # Expertise: also collect Primary Strategic Research Area entries
    expertise: list[str] = []
    for tag in _section_after(main, SRA_HEADINGS):
        txt = tag.get_text(" ", strip=True)
        if txt:
            for piece in txt.split("\n"):
                p = piece.strip()
                if p and p not in expertise:
                    expertise.append(p)

    # Title: prefer the section under "Title(s):"
    title_text = ""
    for tag in _section_after(main, TITLE_HEADINGS):
        txt = tag.get_text(" ", strip=True)
        if txt:
            title_text = (title_text + " " + txt).strip()
        if len(title_text) > 400:
            break

    # Bio / Information section
    bio_parts: list[str] = []
    for tag in _section_after(main, BIO_HEADINGS):
        txt = tag.get_text(" ", strip=True)
        if txt and len(txt) > 20:
            bio_parts.append(txt)
    bio = "\n\n".join(bio_parts).strip()

    # Fallback: if no bio section, take first few substantive paragraphs
    if not bio:
        ps = []
        for p in main.find_all("p"):
            t = p.get_text(" ", strip=True)
            if not t or len(t) < 40:
                continue
            # Skip pure address / office / nav
            low = t.lower()
            if low.startswith(("phone", "email", "office", "fax")):
                continue
            ps.append(t)
            if len(ps) >= 3:
                break
        bio = "\n\n".join(ps).strip()

    # Truncate bio to keep file sizes sane
    if len(bio) > 4000:
        bio = bio[:4000].rsplit(" ", 1)[0] + "..."

    return {
        "research_interests": research_interests,
        "bio": bio,
        "expertise": expertise,
        "title": title_text,
        "source_url": source_url,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch(client: httpx.Client, url: str) -> str:
    last_err = None
    for attempt in range(2):
        try:
            r = client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(0.5)
    raise last_err  # type: ignore[misc]


def worker(fac: dict) -> tuple[str, dict | None, str | None]:
    fid = fac["id"]
    url = fac["profile_url"]
    try:
        with httpx.Client() as client:
            html = fetch(client, url)
        data = extract(html, url)
        # polite jitter inside worker
        time.sleep(0.2 + random.random() * 0.3)
        return fid, data, None
    except Exception as e:  # noqa: BLE001
        return fid, None, f"{type(e).__name__}: {e}"


def save(results: dict) -> None:
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(OUT)


def main() -> None:
    faculty = json.loads(SRC.read_text(encoding="utf-8"))
    results: dict = {}
    if OUT.exists():
        try:
            results = json.loads(OUT.read_text(encoding="utf-8"))
            print(f"Resuming with {len(results)} existing records")
        except Exception:
            results = {}

    todo = [f for f in faculty if f["id"] not in results]
    print(f"Total: {len(faculty)}; to fetch: {len(todo)}")

    failures: list[tuple[str, str]] = []
    done_since_save = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, f): f for f in todo}
        for i, fut in enumerate(as_completed(futures), 1):
            fid, data, err = fut.result()
            if err:
                failures.append((fid, err))
                print(f"[{i}/{len(todo)}] FAIL {fid}: {err}")
            else:
                results[fid] = data
                ri = len(data["research_interests"])
                bl = len(data["bio"])
                print(f"[{i}/{len(todo)}] ok   {fid}  interests={ri} bio={bl}")
            done_since_save += 1
            if done_since_save >= SAVE_EVERY:
                save(results)
                done_since_save = 0

    save(results)

    total = len(faculty)
    succ = len(results)
    with_ri = sum(1 for v in results.values() if v["research_interests"])
    print("\n===== SUMMARY =====")
    print(f"total           : {total}")
    print(f"successful      : {succ}")
    print(f"with interests  : {with_ri}")
    print(f"failed          : {len(failures)}")
    for fid, err in failures[:10]:
        print(" -", fid, err)


if __name__ == "__main__":
    main()
