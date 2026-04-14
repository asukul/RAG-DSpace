# Cloud Run Deployment

End-to-end guide for deploying the ISU Research Search backend + frontend to Google Cloud Run via Cloud Build, against the **Vertex AI + Qdrant** RAG stack.

## Architecture

```
GCE: qdrant-vm (us-central1-a)
├── e2-standard-2, COS, qdrant/qdrant:1.17.1
├── 20 GB pd-ssd at /qdrant/storage  (persistent)
└── Collection: dspace_chunks  (39,255 vectors, dense=768d cosine)
              ↑
              │ http://35.188.64.146:6333
              │
gcr.io/rag-dspace/backend ──> Cloud Run "backend"  (FastAPI, 2GiB, scale-to-zero)
                                    │
                                    ├─→ Vertex AI: text-embedding-005 (query embed)
                                    └─→ Vertex AI: gemini-2.5-flash (generation)
                                          (auth via runtime SA, no API key)
              ↑
              │ baked at build time
              │
gcr.io/rag-dspace/frontend ─> Cloud Run "frontend" (nginx, 512MiB, scale-to-zero)
                                    └── React SPA, citations clickthrough to dr.lib.iastate.edu
```

The build is two-stage because the frontend image needs the backend's run.app URL baked in via `VITE_API_URL`. `cloudbuild.yaml` deploys the backend first, captures its URL with `gcloud run services describe`, and passes it as a `--build-arg` to the frontend image.

**Auth model:** the Cloud Run runtime service account (`PROJECT_NUMBER-compute@developer.gserviceaccount.com`) holds `roles/aiplatform.user`. The backend's `google-genai` client is built with `vertexai=True, project=rag-dspace, location=us-central1`, so it picks up ADC from the runtime SA. **No API key in Secret Manager.**

---

## One-time GCP setup (already done for `rag-dspace`)

```bash
# 1. Set the active project
gcloud config set project rag-dspace

# 2. Enable required APIs (already enabled in rag-dspace)
gcloud services enable \
  cloudbuild.googleapis.com \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  containerregistry.googleapis.com \
  aiplatform.googleapis.com \
  compute.googleapis.com

# 3. Grant Cloud Build SA the deploy roles
PROJECT_NUMBER=$(gcloud projects describe rag-dspace --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"
gcloud projects add-iam-policy-binding rag-dspace --member="serviceAccount:$CB_SA" --role="roles/run.admin"
gcloud projects add-iam-policy-binding rag-dspace --member="serviceAccount:$CB_SA" --role="roles/iam.serviceAccountUser"

# 4. Grant Cloud Run runtime SA aiplatform.user (so the backend can call Vertex)
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding rag-dspace --member="serviceAccount:$RUN_SA" --role="roles/aiplatform.user"
```

## One-time data setup (already done)

These were already executed against `rag-dspace` and don't need to be re-run unless the corpus changes:

1. **Provision Qdrant VM** — `qdrant-vm` in `us-central1-a` (e2-standard-2 + 20 GB pd-ssd, qdrant/qdrant:latest container). External IP `35.188.64.146`, port 6333 open from `0.0.0.0/0`. Internal IP `10.128.0.2` (for future VPC connector path).
2. **Embed faculty** via Vertex `text-embedding-005`: 1916 records in ~35s for ~$0.10. Cached at `backend/data/faculty_embeddings.json`.
3. **Embed document chunks** via Vertex batch: 39,255 chunks in ~140s for ~$1.14. Saved to `backend/data/chunk_embeddings.parquet` (137 MB).
4. **Upsert to Qdrant**: 39,255 points in ~60s into the `dspace_chunks` collection with payload indexes on `uuid/year/type/page`.

---

## Deploy

```bash
cd D:/Dropbox/RAG-DSpace/isu-research-search
gcloud builds submit --config=cloudbuild.yaml --project=rag-dspace .
```

This runs all four steps: backend build → push → deploy → (capture URL) → frontend build → push → deploy. Expect ~6–10 min total.

**Env vars set on the backend Cloud Run service** (via `cloudbuild.yaml`):
- `EMBEDDING_BACKEND=vertex`
- `GCP_PROJECT=rag-dspace`
- `GCP_LOCATION=us-central1`
- `QDRANT_URL=http://35.188.64.146:6333`
- `QDRANT_COLLECTION=dspace_chunks`
- `GEMINI_GEN_MODEL=gemini-2.5-flash`
- `VERTEX_EMBEDDING_MODEL=text-embedding-005`
- `DSPACE_BASE_URL=https://dr.lib.iastate.edu`

---

## Smoke test the live deployment

```bash
BACKEND=$(gcloud run services describe backend --region=us-central1 --project=rag-dspace --format='value(status.url)')

curl $BACKEND/health
# {"status":"healthy","gemini":true,"qdrant_chunks":39255,"rag_ready":true}

curl $BACKEND/api/stats
# {"indexed_documents":39255,"faculty_count":1916,...,"rag_ready":true}

curl -X POST $BACKEND/api/search \
  -H "Content-Type: application/json" \
  -d '{"query":"machine learning healthcare","limit":5}'
# Should return: { answer (with [N] markers), citations[] (with dspace_url), retrieved_chunks[], ... }
```

Open the **frontend URL** in a browser. Search for anything; the answer should include clickable `[N]` superscripts that open the cited DSpace item in a new tab.

---

## Cost notes

| Item | Cost |
|---|---|
| Cloud Run (backend, scale-to-zero) | ~$0–5/mo demo |
| Cloud Run (frontend, scale-to-zero) | ~$0–2/mo demo |
| **GCE qdrant-vm** (e2-standard-2 + 20 GB pd-ssd, 24/7) | **~$40–55/mo** |
| Vertex Gemini 2.5 Flash | ~$0.30/1M in, $2.50/1M out — ~$10–20/mo for demo traffic |
| Vertex text-embedding-005 (queries only) | ~$2–5/mo |
| Container Registry storage | <$1/mo |
| **Estimated total** | **~$55–85/mo on GCP credits** |

---

## Known follow-ups

1. **Qdrant firewall** — currently `0.0.0.0/0` on port 6333. Tighten to a Cloud Run egress IP range or, better, switch to a Serverless VPC Connector + private internal IP (`10.128.0.2`).
2. **Qdrant auth** — no API key set. Add `QDRANT__SERVICE__API_KEY` env var on the VM and set `QDRANT_API_KEY` on the backend service.
3. **Hybrid search** — collection has a `bm25` sparse vector slot but it's not populated yet. Compute BM25 sparse vectors via fastembed and partial-upsert to enable full hybrid retrieval.
4. **Reranker** — Cohere Rerank 3.5 was deferred per user decision. Slot it after the Qdrant top-k for precision boost if recall feels off.
5. **Document chunks in image** — `data/chunk_embeddings.parquet` is 137 MB and should NOT ship inside the backend container (it's only used for the one-time upsert script). `.dockerignore` excludes it.
6. **CORS** — `main.py` uses `allow_origins=["*"]`, fine for demo but tighten before public production.
7. **No CI trigger** — `cloudbuild.yaml` runs on manual `gcloud builds submit`. To auto-deploy on push, create a Cloud Build trigger pointing at the main branch.
