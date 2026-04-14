"""One-off DSpace community walker. Research-only, no harvesting."""
import json
import time
import urllib.request
import urllib.parse

ROOT = "496ab7dd-9f4b-45c9-9776-5da586722ec7"
BASE = "https://dr.lib.iastate.edu/server/api"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
SLEEP = 0.2


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8"))
    time.sleep(SLEEP)
    return data


def list_subcommunities(uuid):
    out = []
    page = 0
    while True:
        url = f"{BASE}/core/communities/{uuid}/subcommunities?size=100&page={page}"
        d = get_json(url)
        for c in d.get("_embedded", {}).get("subcommunities", []) or []:
            out.append({"uuid": c["uuid"], "name": c["name"]})
        pg = d.get("page", {})
        if page + 1 >= pg.get("totalPages", 1) or pg.get("totalElements", 0) == 0:
            break
        page += 1
    return out


def list_collections(uuid):
    out = []
    page = 0
    while True:
        url = f"{BASE}/core/communities/{uuid}/collections?size=100&page={page}"
        d = get_json(url)
        for c in d.get("_embedded", {}).get("collections", []) or []:
            out.append({"uuid": c["uuid"], "name": c["name"], "handle": c.get("handle", "")})
        pg = d.get("page", {})
        if page + 1 >= pg.get("totalPages", 1) or pg.get("totalElements", 0) == 0:
            break
        page += 1
    return out


def count_items(collection_uuid):
    url = f"{BASE}/discover/search/objects?scope={collection_uuid}&dsoType=item&size=1"
    d = get_json(url)
    obj = d.get("_embedded", {}).get("searchResult", {})
    return obj.get("page", {}).get("totalElements", 0)


def sample_metadata_keys(collection_uuid, n=2):
    """Fetch n items, return list of dicts with title + metadata key set."""
    url = f"{BASE}/discover/search/objects?scope={collection_uuid}&dsoType=item&size={n}"
    d = get_json(url)
    out = []
    results = (d.get("_embedded", {})
                .get("searchResult", {})
                .get("_embedded", {})
                .get("objects", [])) or []
    for obj in results:
        ind = obj.get("_embedded", {}).get("indexableObject", {})
        md = ind.get("metadata", {}) or {}
        title_arr = md.get("dc.title", [{}])
        title = title_arr[0].get("value", "") if title_arr else ""
        out.append({
            "uuid": ind.get("uuid", ""),
            "title": title[:90],
            "keys": sorted(md.keys()),
        })
    return out


def walk_community(uuid, name, depth=0):
    node = {"type": "community", "uuid": uuid, "name": name, "children": []}
    subs = list_subcommunities(uuid)
    cols = list_collections(uuid)
    for s in subs:
        node["children"].append(walk_community(s["uuid"], s["name"], depth + 1))
    for c in cols:
        cnt = count_items(c["uuid"])
        samples = sample_metadata_keys(c["uuid"], n=2)
        node["children"].append({
            "type": "collection",
            "uuid": c["uuid"],
            "name": c["name"],
            "handle": c.get("handle", ""),
            "count": cnt,
            "samples": samples,
        })
    return node


if __name__ == "__main__":
    root = get_json(f"{BASE}/core/communities/{ROOT}")
    tree = walk_community(ROOT, root["name"])
    with open(r"D:\Dropbox\RAG-DSpace\isu-research-search\tests\results\_dspace_tree.json", "w", encoding="utf-8") as f:
        json.dump(tree, f, indent=2, ensure_ascii=False)
    print("DONE")
