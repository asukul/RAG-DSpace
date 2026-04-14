"""Enrich LAS non-science faculty (CS, Econ, Music, facultystaff) profile pages.

Writes to data/enriched_las_other.json keyed by faculty id.
"""
from __future__ import annotations

import json
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "las_faculty.json"
OUT = ROOT / "data" / "enriched_las_other.json"

TARGET_NETLOCS = {
    "www.cs.iastate.edu",
    "www.econ.iastate.edu",
    "www.music.iastate.edu",
    "facultystaff.info.iastate.edu",
}

HEADERS = {"User-Agent": "ISU-RAG-Indexer/1.0 (academic research)"}
TIMEOUT = 15.0
MAX_WORKERS = 4
SAVE_EVERY = 50


def _list_items(container) -> list[str]:
    if not container:
        return []
    items = [li.get_text(" ", strip=True) for li in container.find_all("li")]
    items = [i for i in items if i]
    if items:
        return items
    # No <li>; strip the label heading and split lines
    txt = container.get_text("\n", strip=True)
    lines = [ln.strip() for ln in txt.split("\n") if ln.strip()]
    # drop a leading label like "Research Area" / "Area of Expertise"
    if lines and len(lines[0].split()) <= 4 and lines[0].lower().startswith(
        ("research", "area", "areas")
    ):
        lines = lines[1:]
    return lines


def _clean_text(s: str) -> str:
    return " ".join(s.split())


def extract_isu_drupal(soup: BeautifulSoup) -> dict:
    """Shared extractor for cs/econ/music ISU Drupal template."""
    research = _list_items(soup.find("div", class_="isu-people_research"))
    expertise = _list_items(soup.find("div", class_="isu-people_expertise"))

    bio_parts: list[str] = []
    bs = soup.find("div", class_="isu-people_bio-sketch")
    if bs:
        bio_parts.append(_clean_text(bs.get_text(" ", strip=True)))
    main = soup.find("div", class_="isu-people-full_main")
    if main:
        # Strip nav/script noise
        for tag in main.find_all(["script", "style"]):
            tag.decompose()
        main_text = _clean_text(main.get_text(" ", strip=True))
        if main_text:
            bio_parts.append(main_text)

    bio = "\n\n".join(p for p in bio_parts if p)

    # Fallback: first 1-3 paragraphs of article body
    if not bio:
        article = soup.find("article")
        if article:
            paras = [
                _clean_text(p.get_text(" ", strip=True))
                for p in article.find_all("p")
            ]
            paras = [p for p in paras if len(p) > 40]
            bio = " ".join(paras[:3])

    # Truncate excessively long bios
    if len(bio) > 4000:
        bio = bio[:4000]

    return {
        "research_interests": research,
        "expertise": expertise,
        "bio": bio,
    }


def extract_facultystaff(soup: BeautifulSoup) -> dict:
    # Homepage stub — no per-faculty data available
    return {"research_interests": [], "expertise": [], "bio": ""}


EXTRACTORS = {
    "www.cs.iastate.edu": extract_isu_drupal,
    "www.econ.iastate.edu": extract_isu_drupal,
    "www.music.iastate.edu": extract_isu_drupal,
    "facultystaff.info.iastate.edu": extract_facultystaff,
}


def fetch(client: httpx.Client, url: str) -> str | None:
    for attempt in range(2):
        try:
            r = client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            if 500 <= r.status_code < 600 and attempt == 0:
                time.sleep(0.5)
                continue
            return None
        except (httpx.HTTPError, httpx.TimeoutException):
            if attempt == 0:
                time.sleep(0.6)
                continue
            return None
    return None


def process_record(rec: dict) -> tuple[str, dict | None]:
    url = rec.get("profile_url") or ""
    netloc = urlparse(url).netloc
    extractor = EXTRACTORS.get(netloc)
    if not extractor:
        return rec["id"], None

    time.sleep(random.uniform(0.2, 0.5))
    with httpx.Client() as client:
        html = fetch(client, url)
    if not html:
        return rec["id"], None

    try:
        soup = BeautifulSoup(html, "lxml")
        data = extractor(soup)
    except Exception:
        return rec["id"], None

    data.update(
        {
            "title": rec.get("title", ""),
            "department": rec.get("department", ""),
            "source_url": url,
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return rec["id"], data


def save(out: dict) -> None:
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(OUT)


def main() -> None:
    data = json.loads(SRC.read_text(encoding="utf-8"))
    targets = [
        r
        for r in data
        if r.get("profile_url")
        and urlparse(r["profile_url"]).netloc in TARGET_NETLOCS
    ]
    print(f"Total target records: {len(targets)}")

    out: dict = {}
    if OUT.exists():
        try:
            out = json.loads(OUT.read_text(encoding="utf-8"))
            print(f"Resuming with {len(out)} existing records")
        except Exception:
            out = {}

    pending = [r for r in targets if r["id"] not in out]
    print(f"Pending: {len(pending)}")

    done_since_save = 0
    completed = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(process_record, r): r for r in pending}
        for fut in as_completed(futures):
            rec = futures[fut]
            try:
                fid, payload = fut.result()
            except Exception:
                fid, payload = rec["id"], None
            if payload is None:
                failed += 1
                out[rec["id"]] = {
                    "research_interests": [],
                    "expertise": [],
                    "bio": "",
                    "title": rec.get("title", ""),
                    "department": rec.get("department", ""),
                    "source_url": rec.get("profile_url", ""),
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                    "error": "fetch_or_parse_failed",
                }
            else:
                out[fid] = payload
            completed += 1
            done_since_save += 1
            if done_since_save >= SAVE_EVERY:
                save(out)
                done_since_save = 0
                print(f"  saved progress: {completed}/{len(pending)} (failed={failed})")
    save(out)
    print(f"Done. completed={completed} failed={failed} total_out={len(out)}")


if __name__ == "__main__":
    main()
