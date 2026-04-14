# Implementation Plan — Redesign + Auth + Admin + Dev Mode

## Goals (from user)

1. **Test the search system** with a multi-faceted test harness, looping over CS faculty.
2. **Diagnose** why "Political Machine Learning" doesn't show Adisak Sukul publications.
3. **Redesign frontend** to match the dr.lib.iastate.edu visual language (less colorful, academic).
4. **Remove the "Gemini File search" copy** from the front page.
5. **Add Developer Mode toggle** that exposes technical details of the current session.
6. **Add admin account + dashboard** with system + per-user telemetry.
7. **Google Authentication** for user login.
8. **Bootstrap `adisak.sukul@gmail.com` as the first admin.**
9. **Deploy the whole thing to GCP** (Cloud Run, existing project `rag-dspace`).
10. **Re-run all tests against the deployed system**.

## Findings so far

- Backend `/api/search` for "Political Machine Learning" already returns Adisak Sukul in `found_faculty[1]` and his papers in `sources[0..2]`. The bug is **frontend display**:
  - The new RAG response includes `citations[]` (from Qdrant), and the frontend's logic is `!Array.isArray(results.citations)` to render the legacy `sources` panel — so when Qdrant works, the source panel is hidden entirely.
  - Citations show only `authors`, never `advisors`/`majorProfessor`. Adisak is the **major professor**, not the author, so his name never appears in the citation card.
  - `found_faculty` is polluted (~91 entries for "Political Machine Learning") because the matching logic falls back to bare last-name matching, so any researcher with surname `Li`, `Mitra`, `Qi`, etc. gets pulled in.

- The Adisak-only test passes 100%:
  - DSpace returned 11 papers, name search coverage 100%, in `found_faculty` at position #1, 5/5 topic searches correctly attributed back.

- Existing GCP services already deployed:
  - `backend`  → https://backend-623732207442.us-central1.run.app
  - `frontend` → https://frontend-623732207442.us-central1.run.app
  - Qdrant VM at `35.188.64.146:6333` (39 255 chunks)
  - Vertex AI text-embedding-005 + Gemini 2.5 Flash, project `rag-dspace`

## Architecture decisions

### Auth
- **Frontend**: Google Identity Services button (the new GIS, not the deprecated gapi). Returns an ID token (JWT signed by Google).
- **Backend**: `google-auth` library verifies the ID token against Google's public keys, then issues a backend session JWT (`PyJWT`) signed with a project secret.
- **User store**: SQLite at `backend/data/users.db`. Two tables:
  - `users(id, email, google_sub, name, picture, role, created_at, last_login)`
  - `search_log(id, user_id, query, mode, duration_ms, result_count, timestamp)`
- **Admin bootstrap**: On startup, ensure a row exists for `adisak.sukul@gmail.com` with `role='admin'`. Other users default to `role='user'`.
- **Public vs gated**: Search remains public for now (no login required). Only the `/api/admin/*` routes require an admin JWT. The frontend displays a "Sign in" button in the header and an "Admin" tab only when the logged-in user is an admin.

### Developer mode
- Pure frontend feature. A checkbox in the top right toggles `localStorage.dev_mode = true|false`. When on, the search results page reveals:
  - Search latency (`Date.now()` diff around fetch)
  - Backend `search_mode`, `files_searched`
  - Embedding backend, Qdrant collection, points count (from `/api/stats`)
  - Retrieved chunk scores
  - Raw JSON of the first source on demand
- No backend gating — devs can self-toggle.

### Admin dashboard
- New top-level route `/admin` (frontend tab). Hidden unless `user.role === 'admin'`.
- Backend endpoints (all require `Authorization: Bearer <jwt>` and admin role):
  - `GET /api/admin/system` — backend health, Qdrant points, embedding backend, faculty counts, uptime
  - `GET /api/admin/users` — paginated user list with last_login + search count
  - `GET /api/admin/searches?limit=50` — most recent search log entries
  - `GET /api/admin/users/{id}/searches` — searches by a single user
- Search logging: every `/api/search` call writes one row into `search_log` with the user_id (or NULL for anonymous).

### Visual redesign
- **Palette**:
  - White background `#ffffff`
  - Light surface `#f7f7f7`
  - ISU Cardinal Red `#C8102E` (primary)
  - ISU Gold `#F1BE48` (accent only)
  - Body text `#222222`
  - Muted text `#6c757d`
  - Border `#e3e3e3`
- **Typography**: System sans (`-apple-system, "Segoe UI", Roboto, Helvetica, Arial`). 16px base. Headings 1.5–2× with 600 weight. No serif.
- **Header**: White background, slim row. Left: "Iowa State University" wordmark + "Research Search" subtitle in cardinal red. Right: nav tabs (Search / Faculty / Topics / Network), then "Sign in with Google" or user avatar.
- **Search page**: Big quick search bar centered, gray placeholder, cardinal-red submit button. Below: AI answer card → citations list → people sidebar.
- **Cards**: White, 1px `#e3e3e3` border, no shadow, no gradients. Hover: faint cardinal-red top border.
- **Remove**: "Gemini File search" copy, the rainbow gradient hero banner, and any emoji-heavy chrome from the front page.
- Implementation: rewrite `App.css` from scratch as `App.css` v2; keep `App.jsx` structure, but replace class names where needed.

### Search bug fixes
1. **Frontend**: Always render an "Authors & Advisors" line in each citation card. Backend will enrich citations to include both fields.
2. **Backend**: In `main.py::search`, after Qdrant returns citations, look up each citation's `uuid` in the cached `dspace_sources` (which already has `advisors`/`contributors`) and merge those fields into the citation dict before returning.
3. **Backend**: Tighten `find_relevant_faculty` and the in-place faculty extraction so a bare surname match isn't enough — require either full-name match OR last name + first initial match. This eliminates the Yang Li / Sanjukta Mitra false positives.

### GCP deployment
- Reuse `cloudbuild.yaml`. Add new build args / env vars:
  - `GOOGLE_OAUTH_CLIENT_ID` (frontend build arg + backend env)
  - `JWT_SECRET` (backend env, from Secret Manager)
- Persist SQLite via a small bind to `/tmp` is fine for Cloud Run's ephemeral storage in v1. (Production-grade later: GCS or Cloud SQL.) For the demo and admin first-boot, SQLite at `/tmp/users.db` is acceptable, with the `adisak.sukul@gmail.com` admin row created on every cold start.
- Create the OAuth client ID via `gcloud iap oauth-clients create` or the Google Cloud Console. The user authorized me to act without permission asks, so I will create one via gcloud if not present.

## Implementation order

1. **Plan written** (this file). _← here_
2. **Backend search bug fix** (small, isolated, validates the rest of the test flow).
3. **Backend auth scaffolding** (SQLite + Google ID-token verify + JWT issue + admin bootstrap).
4. **Backend admin endpoints** (system, users, searches).
5. **Backend search logging** wired into `/api/search`.
6. **Frontend auth integration** (Google Sign-In button, JWT storage, user state).
7. **Frontend developer-mode toggle**.
8. **Frontend admin dashboard tab**.
9. **Frontend visual redesign** (App.css rewrite + remove "Gemini File search" copy + ISU palette).
10. **GCP OAuth client** (create or reuse).
11. **Deploy backend + frontend** via Cloud Build.
12. **Re-run test suite against deployed URLs**.
13. **Check background test results from step 1** and report.

## Risks & mitigations

- **Google OAuth client requires interactive Google Cloud Console click for some scopes.** Mitigation: use the simplest "OAuth client → Web application" type which `gcloud` can create headlessly.
- **SQLite ephemeral on Cloud Run.** Acceptable for demo; mitigation note added; production fix would be Cloud SQL.
- **Frontend redesign may break admin pages I don't fully visit.** Mitigation: keep class names backward-compatible where possible; only add new styles, then prune.
- **Background CS faculty test loop hits Vertex rate limits.** Mitigation: throttle to 1 request/sec; the test script already does sequential calls.
