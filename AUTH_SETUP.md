# One-time Google OAuth setup

The backend already creates the SQLite user store and bootstraps
`adisak.sukul@gmail.com` as the first admin on startup. The only thing left to
do is create a Google OAuth 2.0 Client ID and re-deploy the build with that
client ID injected.

This step requires the Google Cloud Console because personal-account projects
without an Organization can't create OAuth clients via `gcloud`.

## 1. Configure the OAuth consent screen (one-time)

1. Open https://console.cloud.google.com/apis/credentials/consent?project=rag-dspace
2. Pick **External**, click **Create**.
3. App name: `ISU Digital Repository Research Search`
4. User support email: `adisak.sukul@gmail.com`
5. Developer contact: `adisak.sukul@gmail.com`
6. Save and continue. You can leave scopes empty (we only use the default
   `openid`, `email`, `profile` scopes that GIS adds automatically).
7. Add `adisak.sukul@gmail.com` (and any teammates) as test users while the
   app is still in test mode.

## 2. Create the OAuth Client ID

1. Open https://console.cloud.google.com/apis/credentials?project=rag-dspace
2. Click **Create Credentials → OAuth client ID**.
3. Application type: **Web application**.
4. Name: `ISU Research Search Web`.
5. **Authorized JavaScript origins** — add both:
   - `https://frontend-623732207442.us-central1.run.app`
   - `http://localhost:3000` (for local dev)
6. **Authorized redirect URIs** — none required, GIS uses postMessage flow.
7. Click **Create**. Copy the **Client ID** (looks like
   `1234567890-abcd...apps.googleusercontent.com`).

## 3. Re-deploy with the client ID injected

```bash
cd D:/Dropbox/RAG-DSpace/isu-research-search
JWT_SECRET=$(cat .jwt_secret_local)
CLIENT_ID="1234567890-abcdefg.apps.googleusercontent.com"   # paste yours

gcloud builds submit \
  --config=cloudbuild.yaml \
  --project=rag-dspace \
  --substitutions=_GOOGLE_OAUTH_CLIENT_ID=$CLIENT_ID,_JWT_SECRET=$JWT_SECRET,_DEFAULT_ADMIN_EMAIL=adisak.sukul@gmail.com \
  --gcs-source-staging-dir=gs://rag-dspace_cloudbuild/source \
  .
```

The build:
- Re-builds the backend image with `GOOGLE_OAUTH_CLIENT_ID` and `JWT_SECRET`
  in its env.
- Re-builds the frontend image with the same client ID baked into the JS
  bundle (`VITE_GOOGLE_OAUTH_CLIENT_ID`).
- Deploys both to Cloud Run.

After the build, open the frontend URL. The header should show the standard
"Sign in with Google" button. Sign in with `adisak.sukul@gmail.com` and you'll
land in the system as the bootstrap admin (the row already exists in the
SQLite users table at `/tmp/users.db`).

## Local development

For local development, copy `.env.template` to `.env` and add:

```
GOOGLE_OAUTH_CLIENT_ID=<your client id>
JWT_SECRET=<long random string>
```

In `frontend/.env.development.local`:

```
VITE_API_URL=http://localhost:8010
VITE_GOOGLE_OAUTH_CLIENT_ID=<your client id>
```

## Notes

- SQLite at `/tmp/users.db` on Cloud Run is **ephemeral**. When the instance
  cold-starts, the file is recreated and the `adisak.sukul@gmail.com` admin
  row is re-bootstrapped automatically. User accounts created during a
  session are lost on cold start. For persistent user storage, switch
  `USERS_DB_PATH` to a Cloud SQL connection string and add `cloud-sql-python-connector`
  to `requirements.txt`.
- The session JWT TTL defaults to 24 hours. Override with `JWT_TTL_HOURS`.
- To promote another user to admin after first login, run as the admin:
  `POST /api/admin/users/role` with `{"email": "user@example.com", "role": "admin"}`.
