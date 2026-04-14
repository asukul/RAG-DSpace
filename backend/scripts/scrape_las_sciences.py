"""Scrape ISU LAS hard-sciences faculty profile pages and enrich with research/bio."""
import json
import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "data", "las_faculty.json")
OUT = os.path.join(ROOT, "data", "enriched_las_sciences.json")

DOMAINS = {
    "www.physastro.iastate.edu",
    "www.chem.iastate.edu",
    "www.bbmb.iastate.edu",
    "www.gdcb.iastate.edu",
    "www.eeob.iastate.edu",
    "www.stat.iastate.edu",
}

HEADERS = {"User-Agent": "ISU-RAG-Indexer/1.0 (academic research)"}
TIMEOUT = 15
MAX_WORKERS = 4
SAVE_EVERY = 50


def text_of(el, sep=" "):
    if el is None:
        return ""
    return el.get_text(sep, strip=True)


def list_items(el):
    if el is None:
        return []
    out = []
    # Try li first
    lis = el.find_all("li")
    if lis:
        for li in lis:
            t = li.get_text(" ", strip=True)
            if t:
                out.append(t)
        return out
    # Fallback: split text
    t = el.get_text("\n", strip=True)
    if t:
        out = [s.strip(" \t-•·") for s in t.split("\n") if s.strip()]
    return out


def extract(html, url):
    soup = BeautifulSoup(html, "lxml")
    main = soup.find("main") or soup

    bio_el = main.find(class_="isu-people_bio-sketch")
    bio = text_of(bio_el)

    research = list_items(main.find(class_="isu-people_research-list"))
    expertise = list_items(main.find(class_="isu-people_expertise-list"))

    # Education sometimes useful too
    education = list_items(main.find(class_="isu-people_education-list"))

    title = text_of(main.find(class_="isu-people_position-list"))
    affiliations = text_of(main.find(class_="isu-people_affiliations"))

    # Fallback bio: first paragraph in main content if bio is empty
    if not bio:
        info = main.find(class_="isu-people-full_main") or main
        paras = []
        for p in info.find_all("p"):
            t = p.get_text(" ", strip=True)
            if len(t) > 40:
                paras.append(t)
            if len(paras) >= 3:
                break
        bio = "\n\n".join(paras)

    return {
        "research_interests": research,
        "expertise": expertise,
        "bio": bio,
        "education": education,
        "title": title,
        "affiliations": affiliations,
    }


def fetch(client, url):
    last_exc = None
    for attempt in range(2):
        try:
            r = client.get(url, timeout=TIMEOUT, follow_redirects=True)
            if r.status_code == 200:
                return r.text
            if r.status_code in (404, 410):
                return None
            last_exc = f"HTTP {r.status_code}"
        except Exception as e:
            last_exc = str(e)
        time.sleep(0.5 + random.random())
    raise RuntimeError(last_exc or "fetch failed")


def worker(rec):
    url = rec["profile_url"]
    time.sleep(0.2 + random.random() * 0.3)
    with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as client:
        try:
            html = fetch(client, url)
            if html is None:
                return rec["id"], {"error": "not_found", "source_url": url}
            data = extract(html, url)
            data["source_url"] = url
            data["department"] = rec.get("department", "")
            if not data.get("title"):
                data["title"] = rec.get("title", "")
            data["name"] = rec.get("name", "")
            data["extracted_at"] = datetime.now(timezone.utc).isoformat()
            return rec["id"], data
        except Exception as e:
            return rec["id"], {"error": str(e), "source_url": url}


def load_existing():
    if os.path.exists(OUT):
        try:
            return json.load(open(OUT, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def save(results):
    tmp = OUT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    os.replace(tmp, OUT)


def main():
    data = json.load(open(SRC, encoding="utf-8"))
    targets = [
        d for d in data
        if urlparse(d.get("profile_url") or "").netloc in DOMAINS
    ]
    print(f"Target faculty: {len(targets)}")

    results = load_existing()
    todo = [r for r in targets if r["id"] not in results or "error" in results.get(r["id"], {})]
    print(f"Already done: {len(targets) - len(todo)}; remaining: {len(todo)}")

    done = 0
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(worker, r): r for r in todo}
        for fut in as_completed(futures):
            fid, data_out = fut.result()
            results[fid] = data_out
            done += 1
            if done % 10 == 0:
                print(f"  {done}/{len(todo)}  last={fid}")
            if done % SAVE_EVERY == 0:
                save(results)
                print(f"  [saved checkpoint @ {done}]")

    save(results)
    print("DONE.")

    # report
    succ = sum(1 for v in results.values() if "error" not in v)
    failed = sum(1 for v in results.values() if "error" in v)
    with_ri = sum(1 for v in results.values() if v.get("research_interests"))
    with_bio = sum(1 for v in results.values() if v.get("bio"))
    print(f"successful={succ} failed={failed} with_research_interests={with_ri} with_bio={with_bio}")

    by_dom = {}
    for r in targets:
        nl = urlparse(r["profile_url"]).netloc
        rec = results.get(r["id"], {})
        s = by_dom.setdefault(nl, {"total": 0, "succ": 0, "ri": 0, "bio": 0})
        s["total"] += 1
        if "error" not in rec:
            s["succ"] += 1
        if rec.get("research_interests"):
            s["ri"] += 1
        if rec.get("bio"):
            s["bio"] += 1
    for d, s in by_dom.items():
        print(f"  {d}: {s}")


if __name__ == "__main__":
    main()
