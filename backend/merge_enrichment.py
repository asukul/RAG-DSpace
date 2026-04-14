"""Merge enriched_*.json overlays into faculty.json (with backup)."""
import json
import shutil
from datetime import datetime
from pathlib import Path

DATA = Path(__file__).parent / "data"
FACULTY = DATA / "faculty.json"
ENRICHED_FILES = [
    DATA / "enriched_coe.json",
    DATA / "enriched_ivy.json",
    DATA / "enriched_las_sciences.json",
    DATA / "enriched_las_other.json",
]


def merge():
    # Backup
    backup = FACULTY.with_suffix(f".json.bak.{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(FACULTY, backup)
    print(f"Backup: {backup.name}")

    faculty = json.loads(FACULTY.read_text(encoding="utf-8"))

    # Build single overlay dict (later files win on duplicate ids)
    overlay = {}
    for path in ENRICHED_FILES:
        data = json.loads(path.read_text(encoding="utf-8"))
        overlay.update(data)
        print(f"  loaded {path.name}: {len(data)} records")
    print(f"  overlay total: {len(overlay)} unique ids")

    enriched_count = 0
    ri_added = 0
    bio_added = 0
    exp_added = 0
    title_upgraded = 0

    for f in faculty:
        fid = f.get("id")
        if not fid or fid not in overlay:
            continue
        e = overlay[fid]

        # research_interests: only fill if currently empty
        if not f.get("research_interests") and e.get("research_interests"):
            f["research_interests"] = e["research_interests"]
            ri_added += 1

        # expertise: new field
        if e.get("expertise"):
            f["expertise"] = e["expertise"]
            exp_added += 1

        # bio: new field
        if e.get("bio"):
            f["bio"] = e["bio"]
            bio_added += 1

        # title: upgrade if scraped one is longer/richer
        scraped_title = (e.get("title") or "").strip()
        cur_title = (f.get("title") or "").strip()
        if scraped_title and len(scraped_title) > len(cur_title):
            f["title"] = scraped_title
            title_upgraded += 1

        enriched_count += 1

    FACULTY.write_text(json.dumps(faculty, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"Faculty enriched:        {enriched_count}/{len(faculty)}")
    print(f"  research_interests:    +{ri_added}")
    print(f"  expertise (new field): +{exp_added}")
    print(f"  bio (new field):       +{bio_added}")
    print(f"  title upgraded:        +{title_upgraded}")


if __name__ == "__main__":
    merge()
