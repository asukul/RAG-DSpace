# Quality Loop — Lessons Learned

Append-only. Each lesson is a pattern the system has caught (and ideally fixed) at least once. The triage/investigation agent reads this file before spawning a new investigation, so known patterns get fast-path auto-fixes instead of re-investigating from scratch.

Format: one heading per lesson, with Pattern / Symptom / Root cause / Fix recipe / First-caught date.

---

## 1. BM25 vocab built from content_prefix misses author names

**First caught**: 2026-04-14 (Adisak Sukul search returned curcumin papers).

**Pattern**: When a user searches a person's name (e.g., "Adisak Sukul"), retrieval pulls semantically-noisy papers that don't mention the person at all, and the LLM hallucinates the target as an author of those papers.

**Symptom**:
- `citations[N].authors` does NOT contain the target name
- The LLM answer says the target "wrote" or "authored" paper N anyway
- Multiple citations with score 0.5 (RRF rank-1 in only one list)
- `no_real_authorship_in_retrieval` bug type: none of the top-10 citations have the target in authors

**Root cause**: The BM25 vocabulary was built from `chunk_hash_index.content_prefix` (first 200 chars of each chunk) rather than from the full chunk text. Academic papers typically have title + author list + affiliations within the first ~500-1500 chars, so first-200-char prefix misses most authors. Names like "adisak" end up with `token_id=None` (not in vocab) and "sukul" ends up with `doc_freq=1`. BM25 returns zero hits for name queries, the system falls back to dense-only retrieval, dense embeddings are bad at exact name match, and noisy papers get surfaced.

**Fix recipe**:
1. Run `backend/scripts/rebuild_bm25_vocab_fulltext.py` to rebuild vocab from `instance.content` in the Vertex output files (full chunk text).
2. Verify `sukul` / `adisak` / `tavanapong` / other name tokens have realistic `doc_freq` values in the new vocab.
3. Re-run `backend/scripts/embed_vertex_hybrid_ingest.py --skip-vocab` to re-upsert sparse vectors using the new vocab.
4. Sync to remote via `backend/scripts/sync_qdrant.py`.
5. Redeploy backend (the vocab file is baked into the Docker image).

**How to detect from logs**: run `quality/sweep.py` and look for `hallucinated_author` or `no_real_authorship_in_retrieval` bug types at >5% rate on a sample of faculty name queries.

---

## 2. Qdrant data dir inside Dropbox silently corrupts vectors

**First caught**: 2026-04-13 (several ingests produced all-zero vectors).

**Pattern**: Ingests complete cleanly (no exceptions), payloads are written correctly, but the dense vector on every point comes back as 768 dimensions of 0.0. Queries return score=0.0 for every result. Qdrant logs show `Optimization error: Permission denied (os error 13)`.

**Root cause**: Dropbox's file watcher holds handles on Qdrant segment files during indexing/compaction. When Qdrant's optimizer thread tries to rename or remove segment files mid-compaction, it hits `EACCES` and panics. Points written after the panic land in the WAL but never fully flush — the payload writes succeed but the named-vector storage gets zeroed.

**Fix recipe**: Move the Qdrant data directory OUTSIDE any sync-folder tree. Preferred: `D:/qdrant-data` instead of `D:/Dropbox/RAG-DSpace/qdrant-local-data`. Also upgrade to the latest Qdrant image. Full recipe in `memory/qdrant_dropbox_corruption.md`.

**How to detect from logs**: any `score=0.0` in query_points responses, or a scroll with `with_vectors=True` returning all zeros.

---

## 3. Async upsert (wait=False) silently drops vector writes under load

**First caught**: 2026-04-13 (45/50 points had zero vectors after wait=False bulk ingest).

**Pattern**: Same symptom as #2 (zero vectors) but a different root cause — happens even with Qdrant outside Dropbox.

**Root cause**: `qdrant_client.upsert(wait=False)` is the default and returns immediately. Under high upsert rate (100 points/batch × thousands of batches), the server can drop some vector writes between the WAL commit and the segment flush.

**Fix recipe**: Always pass `wait=True` to `upsert()` in bulk-ingest scripts. Confirmed in `embed_vertex_batch_real.py`, `embed_mit_abstracts.py`, `embed_arxiv_abstracts.py`, `embed_vertex_hybrid_ingest.py`.

**How to detect from logs**: same as #2, but with Qdrant data dir already outside Dropbox.

---

## 4. `.gcloudignore` bare paths match nested directories

**First caught**: 2026-04-13 (deployed backend had 42 faculty instead of 4,322).

**Pattern**: Deploy succeeds, `/health` returns `qdrant_chunks` correctly, but `/api/faculty` returns a tiny hardcoded fallback instead of the real 4k+ entries.

**Root cause**: `.gcloudignore` has a bare line `data` intended to exclude the root-level `./data/` directory. But gcloudignore uses gitignore syntax, where `data` matches ANY directory named `data` at any depth — including `backend/data/`. Result: the Docker build context has no `backend/data/faculty.json`, and the backend's `load_or_seed_faculty_data()` falls back to `verified_faculty_data.py` which only has ~42 hardcoded CS faculty.

**Fix recipe**: Anchor root-level exclusions with a leading `/` — `/data`, `/tenants`, `/platform`, `/docs`, `/papers`. Verify with `gcloud meta list-files-for-upload . | grep backend/data/faculty.json` before deploying.

---

## 5. Sync script doesn't copy sparse_vectors_config

**First caught**: 2026-04-13 (hybrid collection sync failed with "Not existing vector name error: bm25").

**Pattern**: Sync creates the destination collection and starts upserting, then fails on the first batch with `400 Bad Request: Not existing vector name error: bm25`.

**Root cause**: `sync_qdrant.py`'s `create_collection` call only copied `vectors_config`, not `sparse_vectors_config`. Hybrid source collections have both; destination got only the dense slot.

**Fix recipe**: Also pass `sparse_vectors_config=src_info.config.params.sparse_vectors` to `create_collection` when the source has sparse vectors. Already applied in `backend/scripts/sync_qdrant.py`.

---

## 6. Vertex JobState enum: 5 = FAILED, not RUNNING

**First caught**: 2026-04-12 (13-hour wait on a "running" job that had actually failed).

**Pattern**: Batch job status script reports `state: 5` and operator interprets as "still running" because humans mentally map `3 = running` and go with the integer. Job is actually failed.

**Root cause**: JobState enum in `google.cloud.aiplatform_v1` uses `3 = JOB_STATE_RUNNING`, `4 = JOB_STATE_SUCCEEDED`, `5 = JOB_STATE_FAILED`. Reading raw integers is error-prone.

**Fix recipe**: Always print both the integer AND the enum name, and always check `job.error.message` when the state is terminal. Already in `embed_vertex_batch_real.py phase_check`.

---

## 7. Vertex Batch has per-job instance limit of 1,000,000

**First caught**: 2026-04-12 (1,154,764-instance submission failed silently).

**Pattern**: Job submitted successfully, reaches RUNNING briefly, then transitions to FAILED 2 minutes later.

**Root cause**: Vertex AI BatchPredictionJob has a hard cap of 1M instances per job, enforced at dispatch time rather than submission time. Documented but not prominent.

**Fix recipe**: Split inputs into N parts such that `ceil(total_instances / N) < 1_000_000`. Use the `--total N --part M` flags we added to `embed_vertex_batch_real.py`. Note that Vertex also serializes batch jobs per project, so splitting doesn't reduce wall time.

---

## 8. Real Vertex Batch rate is ~$15.70/1B chars, not $1.95

**First caught**: 2026-04-13 PM (morning billing report showed $6.26, evening showed $60.45 for same workload).

**Pattern**: First billing snapshot shows surprisingly low cost. Hours later the figure climbs ~10x.

**Root cause**: Google Cloud Billing is partial for 12-24h after usage. Trusting early reports leads to planning errors.

**Fix recipe**: Wait 24h before trusting Cloud Billing totals. Use `$15.70 / 1B chars` as the planning number for `text-embedding-005` batch.
