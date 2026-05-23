"""List PRT docs that still need Typhoon OCR, with their local PDF paths, so we
can stage just those PDFs to Nova and run the OCR there (instead of all 407 GB).

Writes tenants/prt/data/nova_typhoon_queue.csv: doc_id,pdf_path,shard,size_bytes
"""
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PRT_DATA = REPO / "tenants" / "prt" / "data"
VAULT_PAPERS = PRT_DATA / "vault" / "papers"
TYPHOON_OUT = PRT_DATA / "vault" / "papers_text_typhoon"
TRACKER = PRT_DATA / "prt_pdf_tracker.csv"
OUT = PRT_DATA / "nova_typhoon_queue.csv"

FM = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)


def shard(d: str) -> str:
    return d[-2:] if len(d) >= 2 else "00"


def fm_parse(t: str) -> dict:
    m = FM.match(t)
    if not m:
        return {}
    o = {}
    for line in m.group(1).splitlines():
        if ":" not in line or line.startswith((" ", "-")):
            continue
        k, _, v = line.partition(":")
        o[k.strip()] = v.strip().strip('"').strip("'")
    return o


def pdf_map() -> dict:
    m = {}
    with TRACKER.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            h = (row.get("handle") or "").strip()
            p = (row.get("pdf_path") or "").strip()
            s = (row.get("status") or "").strip()
            if not h or not p or s != "downloaded":
                continue
            m[f"prt-{h.rsplit('/', 1)[-1]}"] = Path(p)
    return m


def main() -> None:
    pm = pdf_map()
    img = done = need = havepdf = 0
    total = 0
    rows = []
    for md in VAULT_PAPERS.rglob("*.md"):
        try:
            head = md.read_text(encoding="utf-8", errors="replace")[:2048]
        except Exception:
            continue
        meta = fm_parse(head)
        if meta.get("content_source") != "metadata_only_image_pdf":
            continue
        img += 1
        did = meta.get("doc_id") or md.stem
        op = TYPHOON_OUT / shard(did) / f"{did}.txt"
        if op.exists() and op.stat().st_size >= 30:
            done += 1
            continue
        need += 1
        pdf = pm.get(did)
        if pdf and pdf.exists():
            havepdf += 1
            sz = pdf.stat().st_size
            total += sz
            rows.append((did, str(pdf), shard(did), sz))
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["doc_id", "pdf_path", "shard", "size_bytes"])
        w.writerows(rows)
    print(f"image-only docs (content_source=metadata_only_image_pdf): {img:,}")
    print(f"  already have typhoon txt: {done:,}")
    print(f"  still NEED typhoon OCR:    {need:,}")
    print(f"  of those, PDF present:     {havepdf:,}")
    print(f"  total PDF size to stage:   {total/1e9:.2f} GB")
    print(f"manifest -> {OUT}  ({len(rows):,} rows)")


if __name__ == "__main__":
    main()
