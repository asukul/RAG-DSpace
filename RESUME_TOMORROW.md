# Resume Point — 2026-04-12 Session End

Session ended at ~23:10 UTC on 2026-04-12 for a workstation restart.

## What was accomplished in this session

1. ✅ **Phase 0 multi-tenant scaffold**: `platform/research_platform/` + `tenants/{isu,prt}/` + Windows junction
2. ✅ **Phase 1 shared-code copy**: 14 services + 30 pipeline scripts + i18n + app layer into `platform/research_platform/`
3. ✅ **OpenScribe OCR framework** (renamed from CHAKRA): engines (fitz, paddle, claude, tesseract), cascade, controller, metrics, pipeline, 25-assertion smoke test
4. ✅ **OpenScribe MCP server + Claude Skill** (`ocr-thai-archival`)
5. ✅ **Claude Vertex wiring** (4 subtests passing, no $ spent)
6. ✅ **PRT OAI-PMH harvester + PDF downloader** with curl_cffi Chrome fingerprint
7. ✅ **End-to-end OpenScribe smoke test** on a real ISU PDF → 49 assertions, 17 KB JSONL output
8. ✅ **Nomic resume to 100%** — 6 workers succeeded, W6+W7 killed (their image-only slices → OpenScribe benchmark)
9. ✅ **Vertex extraction rewrite** (PyMuPDF + 16 subprocess workers, **127× speedup**, full 1.15M chunks in 4.9 min)
10. ✅ **Vertex batch job submitted** (Phase 2 upload + Phase 3 submit, running on Google)
11. ✅ **Research paper portfolio plan** (8 papers targeted at specific venues)
12. ✅ **Three paper drafts** (P2 Scaling RAG, P4 LLM-as-Judge, P8 OpenScribe-MCP Demo)
13. ✅ **Bibliography verified** — 20 citations manually checked against arXiv/DOI/official URLs

## Files to check tomorrow

All of these are in `D:/Dropbox/RAG-DSpace/isu-research-search/` and survive the restart:

- `RESEARCH_PAPERS_PLAN.md` — 8-paper portfolio strategy with venue targets
- `RESEARCH_NOTES.md` — §16 incidents, §17 UTF-8 standard, §18 OpenScribe paper outline
- `MULTI_TENANT_PLAN.md` — 7-phase refactor plan (Phases 0-1 done)
- `papers/references.md` — 20 verified bibliography entries
- `papers/P2_scaling_rag_engineering/draft.md` — ~9 pages, USENIX ATC target
- `papers/P4_llm_as_judge/draft.md` — ~12 pages, SIGIR target
- `papers/P8_openscribe_mcp_demo/draft.md` — ~5 pages, ACL/EMNLP demo target
- `backend/data/embed_state/embed_state_nomic.json` — Nomic baseline state (63,353 PDFs)
- `tenants/prt/data/oai_harvest_state.json` — PRT harvester resume state
- `tenants/isu/data/openscribe_benchmark/` — 8,516 image-only PDFs for CHAKRA/OpenScribe eval

## State that survives restart

**Qdrant collections** (persisted to disk at `D:/Dropbox/RAG-DSpace/qdrant-local-data/` with Dropbox ignore applied):
- `dspace_fulltext_nomic`: **823,745 points** (63,353 PDFs, frozen 65% research baseline)
- `dspace_fulltext_nomic_full`: **1,069,013 points** (~84,600 PDFs, 100% Nomic production collection)
- `dspace_fulltext_vertex`: 631 points (legacy; will grow to ~1.15M after Vertex batch ingest)

Qdrant will auto-start via Docker restart policy — no action needed.

**Vertex batch job** (running remotely on Google, unaffected by workstation restart):
- Job ID: `projects/623732207442/locations/us-central1/batchPredictionJobs/2822568789428666368`
- State as of session end: **5 (RUNNING)** at 23:51 UTC
- Expected completion: within ~1-2 hours from session end (could already be done by morning)
- Dashboard: https://console.cloud.google.com/ai/platform/locations/us-central1/batch-predictions/2822568789428666368?project=623732207442

**State files persisted**:
- Nomic resume: `embed_state_nomic.json` + `worker_*_done.json` (all 6 workers done)
- Vertex batch pipeline: `backend/data/embed_state/vertex_batch_state.json` (job ID saved)
- PRT harvester: `tenants/prt/data/oai_harvest_state.json` (cursor unchanged, still 0 — PRT origin is still 521)

## What does NOT survive restart (needs relaunch tomorrow)

**PRT harvester background process** (PID 76976): will die on restart. To resume:

```bash
cd /d/Dropbox/RAG-DSpace/isu-research-search
python tenants/prt/scripts/harvest_prt.py --max 1000 --wait-for-server &
```

It will check `oai_harvest_state.json`, resume from the saved cursor (currently 0, first attempt), and retry the PRT origin with 15-min max backoff. If PRT is back up, it will start harvesting immediately.

## Recommended commands for tomorrow's first steps

### 1. Verify Qdrant restarted cleanly (30 seconds)
```bash
docker ps | grep qdrant-local
curl -s http://localhost:6334/readyz                        # should return "all shards are ready"
curl -s http://localhost:6334/collections | python -m json.tool
```
Expected: 3 collections (`dspace_fulltext_nomic`, `dspace_fulltext_nomic_full`, `dspace_fulltext_vertex`)

### 2. Confirm point counts survived (30 seconds)
```bash
python -c "
import requests
for name in ['dspace_fulltext_nomic', 'dspace_fulltext_nomic_full', 'dspace_fulltext_vertex']:
    r = requests.post(f'http://localhost:6334/collections/{name}/points/count', json={'exact': True}, timeout=60)
    print(f'{name}: {r.json()[\"result\"][\"count\"]:,}')
"
```
Expected:
```
dspace_fulltext_nomic:      823,745
dspace_fulltext_nomic_full: 1,069,013
dspace_fulltext_vertex:     631  (will be ~1.15M after Phase 5 ingest)
```

### 3. Check Vertex batch job status (15 seconds)
```bash
cd /d/Dropbox/RAG-DSpace/isu-research-search/backend
python scripts/embed_vertex_batch_real.py --phase check
```
If the output says **State: 7** (SUCCEEDED), fire Phase 5 next. If state 5 (still running), just wait.

### 4. If Vertex succeeded → ingest to Qdrant (~30 min)
```bash
cd /d/Dropbox/RAG-DSpace/isu-research-search/backend
python scripts/embed_vertex_batch_real.py --phase ingest
```
Downloads output JSONL from GCS, parses embeddings, upserts to `dspace_fulltext_vertex`. Expected final count: ~1,150,000 points.

### 5. Restart PRT harvester in background
```bash
cd /d/Dropbox/RAG-DSpace/isu-research-search
python tenants/prt/scripts/harvest_prt.py --max 1000 --wait-for-server > /tmp/prt_harvest.log 2>&1 &
```
Check `/tmp/prt_harvest.log` to see if PRT origin has returned (`punsarn.cloud` was 521 all day).

### 6. Check harvester's first attempt
```bash
sleep 5 && tail -20 /tmp/prt_harvest.log
```
If it's still 521 → keep waiting. If it's 200 → data should be flowing into `tenants/prt/data/oai_records/batch_*.jsonl`.

## Next substantive work after restart

In priority order once the pipelines are healthy:

1. **Finish P2 Scaling RAG draft**: add the remaining real numbers from Nomic 100% run (final point count, per-worker stats, error rate) into §5.1 Speedups Measured table
2. **Run P4's 57×5×10 evaluation sweep** on both Nomic collections (baseline vs full) + Vertex once it finishes — this gives the real Pareto curves
3. **Build P4's cross-family judge validation** (Gemini 2.5 Pro or GPT-4 on the 20% sample) to measure judge agreement
4. **When PRT comes back**: run `tenants/prt/scripts/download_prt_pdfs.py --max 100` → run OpenScribe pipeline on the first 100 PRT PDFs → collect baseline for OpenScribe main paper (P1)
5. **Extend OpenScribe to actually wire PaddleOCR + Claude rescue on the 8,516-PDF OpenScribe benchmark workload** (tenants/isu/data/openscribe_benchmark/) — this becomes the ISU half of P1's experimental section

## Open tasks (for TaskList tomorrow)

From current session (pending or in-progress):
- Task #17 — Autonomous pipeline: finish embed, next models, deploy, upload to GCS (mostly done — just need Phase 5 ingest)
- Task #22 — PRT multi-tenant project (waiting on PRT origin)
- Task #34 — Build PRT OAI-PMH harvester + start harvest (harvester built; waiting on origin)

## Session vibe check

**Most impactful wins of the day**:
1. 127× Vertex extraction speedup via PyMuPDF + subprocess (from 6-8 hour estimate → 4.9 min actual)
2. Qdrant recovery from a self-inflicted Dropbox snapshot spiral (container restart loop → clean restart via ignore attribute + manual tmp cleanup)
3. Three paper drafts from zero to ~25 pages total with 20 verified citations
4. Full OpenScribe framework + MCP server + Claude Skill shipped in one session

**Carry-forward concerns**:
1. PRT origin outage is now >6 hours old — may need to contact support@punsarn.com if not back by morning
2. Vertex batch job is currently the longest outstanding work — it's either finished or will be very soon
3. PRT harvester needs manual relaunch after reboot

Sleep well. Tomorrow's me has a straightforward resume path.
