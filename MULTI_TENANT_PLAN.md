# Multi-Tenant Refactor Plan — Summary

**Full plan:** See chat transcript 2026-04-12 for detailed research findings, folder structure, config schemas, and rollback procedures.

## Architecture

```
D:/Dropbox/RAG-DSpace/isu-research-search/
├── platform/                       # NEW — shared code (Python package: research_platform)
│   ├── research_platform/
│   │   ├── config/      (loader + Pydantic schema)
│   │   ├── services/    (embedding, qdrant, kg, auth, etc.)
│   │   ├── pipeline/    (pdf_extract, ollama_embed, bm25, etc.)
│   │   ├── scripts/     (harvest, embed, build_kg, etc.)
│   │   └── app/         (FastAPI)
│   └── i18n.py          (already created — UTF-8 + Thai support)
├── tenants/                        # NEW — per-tenant isolated data + config
│   ├── isu/
│   │   ├── config.yaml
│   │   ├── data/        (junction to backend/data during Phase 0-3)
│   │   ├── scripts/     (ISU-specific scrapers)
│   │   └── seed/        (faculty_seed.json, dspace_collection_map.json)
│   └── prt/
│       ├── config.yaml
│       ├── data/
│       ├── scripts/
│       └── seed/
├── backend/                        # KEPT untouched during Phase 0
│   ├── data/            (live pipeline data — DO NOT MOVE until Phase 4)
│   ├── scripts/
│   └── services/
└── frontend/                       # Phase 7
```

## Tenant Resolution (2 knobs)

1. `--tenant <id>` CLI flag (highest priority)
2. `TENANT` environment variable
3. Default from `platform/config/defaults.yaml`

## Phases — Non-Destructive Migration

| Phase | Risk | Duration | What |
|-------|------|----------|------|
| **0: Scaffolding** | None | Today | Create empty platform/ + tenants/, junction tenants/isu/data → backend/data |
| **1: Copy shared code** | Low | 1-2 days | Parallel copy to platform/ (originals keep running) |
| **2: Validate new path** | Low | 1 day | Smoke tests on throwaway Qdrant collection |
| **3: API cutover** | Medium | API restart | FastAPI imports from research_platform |
| **4: Data move** | High | ~10 min | Move backend/data → tenants/isu/data (when embedding idle) |
| **5: Scraper relocation** | Low | Hours | ISU scrapers → tenants/isu/scripts/ |
| **6: PRT integration** | Isolated | Days | Full PRT tenant with harvest + OCR + embed |
| **7: Frontend** | Low | Days | Theme + storage keys per tenant |

## Safety Rails

- **Junction during Phase 0-3**: `tenants/isu/data` is a Windows directory junction to `backend/data`. No bytes move. Live workers unaffected.
- **Copy, not move, in Phase 1**: Originals keep running. Rollback = delete new copies.
- **Cutover window**: Only Phase 4 touches live data. Requires `embed_state_nomic.json.finished_at` OR idle workers.
- **Qdrant snapshot**: Mandatory before Phase 4.
- **Backward-compat junction**: After Phase 4, `backend/data` becomes junction to `tenants/isu/data` for straggler scripts.

## Open Decisions (deferred)

1. Package naming: `research_platform/` (recommended, avoids stdlib collision)
2. Users DB location: per-tenant vs shared
3. Qdrant deployment: shared node or per-tenant
4. FastAPI: process-per-tenant vs multi-tenant path prefix
5. Frontend: single build with runtime theme vs two builds

## Current Running Processes (DO NOT BREAK)

- `launch_workers.py` + `worker_embed_v2.py` writing to Qdrant `dspace_fulltext_nomic`
- State files: `backend/data/embed_state/worker_*_progress.json`, `embed_state_nomic.json`
- Vertex extraction writing `backend/data/dspace/vertex_batch_chunks.jsonl`
- Hard-coded Windows path in `worker_embed_v2.py`: `r"D:\Dropbox\RAG-DSpace\isu-research-search\backend"`

**Rule:** No changes to `backend/data/` or `backend/scripts/` until the live Nomic run is paused.
