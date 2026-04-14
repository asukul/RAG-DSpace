"""
One-shot harvester to expand indexed_documents.json past 200.

Paginates DSpace `discover/search/objects` across a broad topic set, dedupes
by UUID against the existing index, and appends new docs.
"""

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import httpx

DSPACE_BASE_URL = "https://dr.lib.iastate.edu"
DSPACE_API_URL = f"{DSPACE_BASE_URL}/server/api"
DATA_FILE = Path(__file__).parent / "data" / "indexed_documents.json"

TOPICS = [
    # CS / AI / data
    "machine learning", "deep learning", "neural network", "computer vision",
    "natural language processing", "reinforcement learning", "data mining",
    "computer science", "software engineering", "human-computer interaction",
    "database", "distributed systems", "cybersecurity", "cryptography",
    "algorithms", "theoretical computer science", "graph theory",
    # ECE / engineering
    "renewable energy", "power systems", "smart grid", "electrical engineering",
    "signal processing", "robotics", "autonomous systems", "VLSI",
    # Bio / life sciences
    "bioinformatics", "genomics", "computational biology", "protein structure",
    "ecology", "plant genetics", "biochemistry", "agronomy",
    # Stats / math
    "statistics", "machine learning theory", "optimization", "operations research",
    # Social / humanities
    "political science", "economics", "education technology",
]

PAGE_SIZE = 100
MAX_PAGES_PER_TOPIC = 3  # 300 results per topic max


def _get(metadata, field):
    return [v.get("value", "") for v in metadata.get(field, []) if v.get("value")]


async def fetch_page(client, topic: str, page: int):
    try:
        r = await client.get(
            f"{DSPACE_API_URL}/discover/search/objects",
            params={
                "query": topic,
                "dsoType": "item",
                "size": PAGE_SIZE,
                "page": page,
                "sort": "dc.date.accessioned,desc",
            },
        )
        if r.status_code != 200:
            return []
        data = r.json()
        return (
            data.get("_embedded", {})
            .get("searchResult", {})
            .get("_embedded", {})
            .get("objects", [])
        )
    except Exception as e:
        print(f"  ! {topic} p{page}: {e}")
        return []


def to_doc(item, topic):
    metadata = item.get("metadata", {})
    return {
        "uuid": item.get("uuid"),
        "title": (_get(metadata, "dc.title") or [""])[0],
        "authors": _get(metadata, "dc.contributor.author"),
        "advisors": _get(metadata, "dc.contributor.advisor"),
        "contributors": _get(metadata, "dc.contributor"),
        "abstract": (_get(metadata, "dc.description.abstract") or [""])[0][:1500],
        "date": (_get(metadata, "dc.date.issued") or [""])[0],
        "type": (_get(metadata, "dc.type") or ["publication"])[0],
        "subjects": _get(metadata, "dc.subject"),
        "url": f"{DSPACE_BASE_URL}/items/{item.get('uuid')}",
        "source": "dspace",
        "cache_indexed_at": datetime.now().isoformat(),
        "indexed_via": topic,
    }


async def main():
    # Load existing
    if DATA_FILE.exists():
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = []
    seen = {d.get("uuid") for d in existing if d.get("uuid")}
    print(f"Starting with {len(existing)} existing docs ({len(seen)} unique)")

    new_docs = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for topic in TOPICS:
            topic_added = 0
            for page in range(MAX_PAGES_PER_TOPIC):
                objs = await fetch_page(client, topic, page)
                if not objs:
                    break
                for obj in objs:
                    item = obj.get("_embedded", {}).get("indexableObject")
                    if not item:
                        continue
                    uuid = item.get("uuid")
                    if not uuid or uuid in seen:
                        continue
                    doc = to_doc(item, topic)
                    new_docs.append(doc)
                    seen.add(uuid)
                    topic_added += 1
                if len(objs) < PAGE_SIZE:
                    break
            print(f"  + {topic}: {topic_added} new")

    if new_docs:
        existing.extend(new_docs)
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2, ensure_ascii=False)
    print(f"\nTotal: {len(existing)} docs (+{len(new_docs)} new)")


if __name__ == "__main__":
    asyncio.run(main())
