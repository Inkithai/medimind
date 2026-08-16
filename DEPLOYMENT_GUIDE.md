# MediMind — Deployment Guide
## SnapDeploy (Backend) + Vercel (Frontend)

This guide takes you from localhost to a live deployment in ~30 minutes.

```
┌──────────────────────────────────────────────────┐
│  Frontend:  Vercel (free, static hosting)         │
│  Backend:   SnapDeploy (free, Docker container)   │
│  Database:  Supabase (already set up)              │
│  Files:     Cloudinary (already set up)            │
│  LLM:       Gemini API (already set up)            │
│  Vectors:   Supabase chunks table (no volume)      │
└──────────────────────────────────────────────────┘
```

---

## Prerequisites

Before you start, make sure you have:
- [ ] A **GitHub** account with this repo pushed
- [ ] Your current `.env` values from `backend/.env` (you'll copy them)
- [ ] A **Gemini API key** (or Groq key)
- [ ] **Supabase** project URL + service role key
- [ ] **Cloudinary** credentials (cloud name, API key, API secret)

> **Note on chromadb:** The `chromadb` package is included in `requirements.txt` because it provides the local ONNX MiniLM embedding model (free, no API key needed). Even though vector **storage** uses Supabase (`VECTOR_STORE=supabase`), vector **generation** still uses chromadb's local model. This adds ~120MB to the Docker image. If you later add an `OPENAI_API_KEY` for embeddings, you can remove chromadb from `requirements.txt` to save space.

---

## Step 1 — Prepare Supabase (One-Time)

If you haven't already, run the schema migration:

1. Go to your Supabase Dashboard → **SQL Editor**
2. Click **New Query**
3. Paste the entire contents of `backend/supabase_schema.sql`
4. Click **Run**

This creates 4 tables: `documents`, `patient_snapshots`, `chunks`, and `jobs`.

> **Verify:** Go to Table Editor — you should see all 4 tables listed.

---

## Step 2 — Deploy Backend to SnapDeploy

### 2a. Create SnapDeploy Account

1. Go to [snapdeploy.dev](https://snapdeploy.dev)
2. Sign up with your **GitHub account** (no credit card needed)

### 2b. Connect Your Repository

1. Click **New Deployment**
2. Connect your GitHub repository (`Inkithai/medimind`)
3. SnapDeploy will auto-detect the `Dockerfile` at the repo root

### 2c. Set Environment Variables

In the SnapDeploy dashboard, find **Environment Variables** for your deployment and add ALL of these:

```ini
# ── LLM Provider (REQUIRED) ──────────────────────────
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...your-actual-key...

# ── Supabase (REQUIRED) ──────────────────────────────
SUPABASE_URL=https://your-project-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...your-actual-service-role-key...

# ── Cloudinary (REQUIRED) ────────────────────────────
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret

# ── Auth (REQUIRED) ──────────────────────────────────
JWT_SECRET=generate-a-long-random-string-here

# ── Deployment Config (REQUIRED) ─────────────────────
VECTOR_STORE=supabase
USE_BACKGROUND_JOBS=true
UPLOAD_FILE_CONCURRENCY=1
CORS_ORIGINS=https://your-project.vercel.app

# ── Find Care directory ──────────────────────────────
# Nothing to set: it defaults to keyless OpenStreetMap.
# Only set these to prefer Google Places API (New)
# (needs Places API (New) + billing on the key's project;
# OpenStreetMap covers Google failures automatically):
# CARE_PROVIDER=google
# GOOGLE_MAPS_API_KEY=AIza...your-server-key...
```

#### How to generate JWT_SECRET:
Open a terminal and run:
```bash
openssl rand -hex 32
```
Copy the output — that's your secret.

#### How to find your CORS_ORIGINS value:
You'll get this after deploying the frontend to Vercel in Step 3. For now, use `*` and update it later:
```ini
CORS_ORIGINS=*
```

### 2d. Deploy

1. Click **Deploy**
2. Wait for the build to complete (~2-3 minutes)
3. SnapDeploy gives you a URL like: `https://medimind-xxxxx.snapdeploy.dev`
4. **Copy this URL** — you need it for the frontend

### 2e. Verify Backend

Open in your browser:
```
https://your-snapdeploy-url.snapdeploy.dev/api/v1/health
```
You should see: `{"status":"ok","service":"MediMind"}`

---

## Step 3 — Deploy Frontend to Vercel

### 3a. Connect to Vercel

1. Go to [vercel.com](https://vercel.com) → **Add New Project**
2. Import your GitHub repository
3. Vercel auto-detects Vite

### 3b. Configure Build Settings

In the Vercel project settings:

| Setting | Value |
|---|---|
| **Root Directory** | `frontend` |
| **Framework Preset** | `Vite` |
| **Build Command** | `npm run build` |
| **Output Directory** | `dist` |

### 3c. Set Environment Variable

In Vercel → **Settings** → **Environment Variables**, add:

| Key | Value | Environment |
|---|---|---|
| `VITE_API_URL` | `https://your-snapdeploy-url.snapdeploy.dev` | Production |

> ⚠️ **Important:** The `VITE_` prefix is required — Vite only exposes env vars starting with `VITE_` to the browser.

### 3d. Deploy

1. Click **Deploy**
2. Wait ~1 minute
3. You'll get a URL like: `https://medimind.vercel.app`

### 3e. Verify Frontend

Open your Vercel URL — you should see the MediMind landing page.

---

## Step 4 — Update CORS (After Both Are Deployed)

Now that you have both URLs, go back to SnapDeploy environment variables and update:

```ini
CORS_ORIGINS=https://medimind.vercel.app
```

Then **redeploy** the backend (SnapDeploy usually auto-redeploys on env var change).

---

## Step 5 — End-to-End Test

1. Open your Vercel URL
2. Click **"Start My Health Record"** — anonymous session should be created
3. Upload a medical document (PDF or image)
4. Watch the progress bars — extraction should complete
5. Check Timeline, Lab Trends, Cross-Check pages
6. Try the Ask page with a question about your uploaded document

---

## Environment Variables — Complete Reference

### Backend (SnapDeploy)

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | ✅ | `gemini` | Which LLM to use |
| `GEMINI_API_KEY` | ✅ | `AIza...` | Gemini API key |
| `SUPABASE_URL` | ✅ | `https://xxx.supabase.co` | Database URL |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅ | `eyJ...` | Supabase secret key |
| `CLOUDINARY_CLOUD_NAME` | ✅ | `mycloud` | Cloudinary cloud name |
| `CLOUDINARY_API_KEY` | ✅ | `1234567890` | Cloudinary API key |
| `CLOUDINARY_API_SECRET` | ✅ | `abc...xyz` | Cloudinary API secret |
| `JWT_SECRET` | ✅ | `random-hex-string` | Signs anonymous session tokens |
| `VECTOR_STORE` | ✅ | `supabase` | Must be `supabase` (no volume on free tier) |
| `USE_BACKGROUND_JOBS` | ✅ | `true` | Async uploads for cold-start resilience |
| `UPLOAD_FILE_CONCURRENCY` | ✅ | `1` | Max simultaneous LLM calls |
| `CORS_ORIGINS` | ✅ | `https://xxx.vercel.app` | Your frontend URL |
| `OPENAI_API_KEY` | ❌ | `sk-...` | Only for better embeddings (optional) |
| `CARE_PROVIDER` | ❌ | `osm` (default) or `google` | Find Care directory source. Unset = keyless OpenStreetMap |
| `GOOGLE_MAPS_API_KEY` | ❌ | `AIza...` | Only for `CARE_PROVIDER=google`. Server-only key with Places API (New) enabled and billing attached |
| `CARE_FALLBACK` | ❌ | `on` (default) | Keep `on` so Google failures fall back to OpenStreetMap instead of 503 |

### Frontend (Vercel)

| Variable | Required | Example | Purpose |
|---|---|---|---|
| `VITE_API_URL` | ✅ | `https://xxx.snapdeploy.dev` | Backend API base URL |

---

## How `.env` Files Work in Deployment

### Local Development (what you've been doing):
```
backend/.env  →  python-dotenv loads it  →  os.environ.get("KEY")
```

### Production Deployment:
```
SnapDeploy dashboard env vars  →  injected into container  →  os.environ.get("KEY")
```

**You do NOT upload your `.env` file to SnapDeploy or Vercel.** Instead, you copy the VALUES from your local `.env` into the platform's environment variable settings. The `load_dotenv()` call in the code is harmless — it just finds no `.env` file and does nothing.

### What's in `.gitignore` (already safe):
```
.env          ← never committed to GitHub ✅
```

---

## Troubleshooting

### Backend won't start
- Check SnapDeploy logs for missing env vars
- Verify `VECTOR_STORE=supabase` (not `chroma`)
- Make sure `supabase_schema.sql` was run in Supabase

### Frontend shows "Could not reach the API"
- Check `VITE_API_URL` is set correctly (no trailing slash)
- Verify backend `/api/v1/health` responds
- Check CORS_ORIGINS matches your Vercel URL exactly

### Upload hangs or times out
- Verify `USE_BACKGROUND_JOBS=true`
- Check Gemini API key is valid
- Free tier SnapDeploy may have cold starts (~30s)

### Find Care says "Nearby search didn't load" / "facility directory is temporarily unavailable" (503)

Since the keyless-directory change this should no longer happen from missing Google configuration — Find Care falls back to OpenStreetMap automatically. If you still see it:

- **Fastest fix:** remove `CARE_PROVIDER` and `GOOGLE_MAPS_API_KEY` from the backend service entirely, then redeploy. Startup logs `Care directory ready: provider=openstreetmap` and search works with no key and no billing.
- If you *want* Google results, set the variables on the **backend service** (not Vercel/frontend): `CARE_PROVIDER=google` and a complete `GOOGLE_MAPS_API_KEY=AIza...` value. `AI` by itself is not a valid key.
  - In the key's Google Cloud project, enable **Places API (New)** and attach an active billing account, otherwise Google answers `PERMISSION_DENIED: The caller does not have permission`.
  - Use API restrictions that allow **Places API (New)**. Browser HTTP-referrer restrictions do not work for backend requests from Render/SnapDeploy; use a server-side restriction strategy.
  - With `CARE_FALLBACK=on` (the default) a rejected Google call is logged as `care directory: google failed (...); falling back to openstreetmap` and the user still gets results.
- A 503 now means *both* providers failed — usually outbound network egress is blocked from the host. Check that the backend can reach `overpass-api.de`, or point `OVERPASS_API_URL` at a reachable mirror.
- Provider errors are logged with HTTP status and message for operators; the browser only ever receives a neutral message with no key details.

### "No timeline found" (404)
- This is normal before first upload — the page handles it gracefully

### Q&A always says "no indexed records were found for this patient yet"
- This message used to appear even when documents were uploaded. It means the **vector index** is empty for that patient while the documents themselves exist in Supabase Postgres. Two common causes:
  1. `VECTOR_STORE` is unset (defaults to `chroma`), so the index lives in the container's local `./chroma_db` and is wiped on every redeploy/restart — there is no persistent volume on the free tier. Fix: set `VECTOR_STORE=supabase` and re-deploy.
  2. `VECTOR_STORE=supabase` but the `chunks` table was never created (`supabase_schema.sql` not run, or run before the `chunks` table was added). Fix: run `supabase_schema.sql` once in the Supabase SQL editor.
- Since the self-healing fix, Q&A rebuilds the index from the patient's saved documents on the next question, so no re-upload is needed — just ask again. If the `chunks` table itself is missing, Q&A now returns a 502 pointing at the migration instead of silently claiming there are no records.
- Verify what's in the vector store: `VECTOR_STORE=supabase python backend/inspect_chroma.py "<user_id>"`

---

## Making Updates After Deployment

### Update backend code:
```bash
git add .
git commit -m "fix: something"
git push origin main
```
SnapDeploy auto-redeploys from GitHub.

### Update frontend code:
```bash
git add .
git commit -m "feat: new page"
git push origin main
```
Vercel auto-redeploys from GitHub.

### Change environment variables:
- **Backend:** SnapDeploy dashboard → Environment Variables → Save → Redeploy
- **Frontend:** Vercel → Settings → Environment Variables → Save → Redeploy

---

## Pre-Deploy Verification Checklist

Run these checks locally BEFORE pushing to GitHub:

```bash
# 1. Frontend builds without errors
cd frontend && npm run build
# Expected: "✓ built in X.XXs"

# 2. Backend starts without import errors
cd backend && python -c "
import openai, pdfplumber, pymupdf, chromadb
import fastapi, uvicorn, supabase, cloudinary, jwt
print('✅ All dependencies OK')
"

# 3. Supabase tables exist (check in Supabase Dashboard → Table Editor)
# You should see: documents, patient_snapshots, chunks, jobs

# 4. No .env file is committed to git
git ls-files | grep -E '\.env$'
# Expected: (empty output — no .env files tracked)

# 5. Docker image builds locally (optional, if you have Docker installed)
docker build -t medimind-test .
docker run -p 8000:8000 --env-file backend/.env medimind-test
# Then open http://localhost:8000/api/v1/health
```

### Deployment files inventory:

| File | Purpose |
|---|---|
| `Dockerfile` | Backend container definition (Python 3.10 + FastAPI) |
| `.dockerignore` | Excludes frontend, tests, local data from Docker build |
| `backend/requirements.txt` | Python dependencies (13 packages) |
| `frontend/vercel.json` | Vercel build config + SPA routing |
| `frontend/src/vite-env.d.ts` | TypeScript types for `VITE_API_URL` |
| `.gitignore` | Excludes `.env`, `node_modules`, `chroma_db`, build output |

### Expected Docker image size: ~750MB

| Component | Size |
|---|---|
| Python 3.10-slim base | ~150 MB |
| pymupdf (PDF processing) | ~65 MB |
| onnxruntime (embeddings) | ~58 MB |
| chromadb (embeddings) | ~64 MB |
| All other packages | ~250 MB |
| Backend source code | ~1 MB |
| **Total** | **~750 MB** |

---

## Free Tier Limits to Watch

| Service | Free Limit | Your Usage |
|---|---|---|
| **SnapDeploy** | 10 deploys/day, auto-sleep | Well within limits |
| **Vercel** | 100 GB bandwidth/month | Static site = tiny |
| **Supabase** | 500 MB database, 50K rows | ~1-5 MB per patient |
| **Cloudinary** | 25 GB bandwidth/month | Medical PDFs are small |
| **Gemini API** | 15 RPM, 1M TPM | 3-5 calls per upload |
