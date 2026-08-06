# MediMind — Anonymous Medical Document Intelligence

MediMind converts your private medical files into something you can actually navigate. Drop in prescriptions, lab reports, and discharge summaries and you get a structured timeline, automatic safety checks, lab trend analysis, and grounded question answering. All of it lives inside a **private anonymous workspace** — no signup, no password, just a `session_id` stored locally in your browser.

```
               Original file (PDF/JPG)
                        |
                   ┌────┴─────┐
                   │ Extraction│ ← Groq Llama 4 Scout (vision + structured JSON)
                   └────┬─────┘
                        |
        ┌───────────────┼────────────────┐
        │               │                │
   Supabase (JSON)  Cloudinary (file)   |
   documents +       mediscan/<user>/   |
   patient_snapshots                    |
        └───────┬───────────────────────┘
                |
            Timeline (visits, meds, labs, allergies)
                |
     ┌──────────┼──────────┐
     │          │          │
 Safety     Lab Trends   Chroma (chunks+embeddings)
 check      deterministic   |
     │          │           └──→ RAG Q&A / Conversations (query rewrite)
     └──────────┴──────────→ JSON answer with citations
```

One browser = one isolated patient view. Scoping uses the `user_id` issued via `POST /api/v1/anonymous/session`.

### Backend modules

| File | What it handles |
|---|---|
| `medical_extractor.py` | Vision / text extraction, patient grouping, timeline creation, safety LLM call plus deterministic duplicate detection, local CLI persistence |
| `document_filter.py` | Fast post-extraction filter for non-medical files (no extra LLM call, reuses `document_type` + clinical fields) |
| `lab_trends.py` | Pure Python trend engine — parses dates/values, computes direction, detects range crossings, flags approaching thresholds |
| `retrieval.py` | Chunks timeline into Medication / Lab / ClinicalNote / Allergy texts, embeds (OpenAI `text-embedding-3-small` if set else local ONNX MiniLM), indexes per-user Chroma collection, single-shot Q&A |
| `conversation.py` | In-memory conversation store, rewrites follow-ups like "was that safe?" into self-contained retrieval queries, summarizes older turns to keep context bounded |
| `api.py` | FastAPI wrapper — lifespan startup, CORS, all `/api/v1/` routes, multipart upload handling, merges new docs with old |
| `auth.py` | Validates `Authorization: Bearer <jwt>` + `X-User-Id`, plus issues anonymous JWTs via `issue_anonymous_token()` |
| `db.py` | Supabase Postgres persistence (documents append-only + patient snapshot upsert), fixed chained `.order("uploaded_at").order("id")` |
| `storage.py` | Uploads original file to Cloudinary `mediscan/<user_id>/...` |
| `supabase_schema.sql` | One-time table creation with RLS enabled/no policies (only service-role key can access) |
| `inspect_chroma.py` | Read-only CLI to list collections / inspect chunks |
| `requirements.txt` / `Procfile` | Railway Nixpacks deployment |

Deep dives live in `backend/docs/`.

### Setup

Prerequisite: Python 3.10+, Node 18+.

```bash
pip install openai pdfplumber pymupdf pillow chromadb python-dotenv python-dateutil fastapi "uvicorn[standard]" python-multipart supabase cloudinary pyjwt
```

Copy env template (gitignored — holds secrets):

```bash
cp backend/.env.example backend/.env
# edit backend/.env
```

Required vars:

```
GROQ_API_KEY=gsk_...    # free at console.groq.com/keys
CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
SUPABASE_URL=https://your-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...   # service_role, NOT anon
JWT_SECRET=some-long-random-string
# optional
OPENAI_API_KEY=sk-...   # only for embeddings, else local ONNX
CORS_ORIGINS=*          # or https://your-frontend
CHROMA_DIR=./chroma_db   # override to /data/chroma_db on Railway volume
```

Groq runs extraction + cross-check + Chat; it has no embeddings endpoint, so embeddings fallback chain:
1. OpenAI `text-embedding-3-small` if `OPENAI_API_KEY`
2. Chroma's local `ONNXMiniLM_L6_V2`

If you switch embedding backends, delete `./chroma_db` and re-upload.

#### Supabase one-time setup

1. Create project at supabase.com.
2. SQL Editor → paste `backend/supabase_schema.sql` → Run (creates `documents`, `patient_snapshots`, indexes, RLS).
3. Copy Project URL + service_role key into `.env`.

### Running backend

```bash
cd backend
uvicorn api:app --reload
# docs at http://127.0.0.1:8000/docs
```

Base URL `http://127.0.0.1:8000`, all routes under `/api/v1/`.

### Frontend — MediMind workspace

`frontend/` is React + TS + Vite + Tailwind. Zero-login anonymous model:

- **Landing** `/` — hero, anonymous session explanation, Start My Health Record → auto-creates workspace via `POST /anonymous/session` (token stored in `localStorage.medimind.session.v1`).
- **Overview / Dashboard** `/dashboard` — documents / medicines / labs / safety counts, latest safety warnings, recent history, pipeline hint.
- **Upload** `/upload` — drag-drop, dedup fixed (`name-size-lastModified`), shows `ProcessingStatus` steps: Upload → Reading → Extracting → Organizing → Safety → Indexing → Ready.
- **My Documents** `/documents` — list + `DocumentViewer` with Original (iframe/img via Cloudinary) vs Structured tabs.
- **My History** `/history` — year-grouped timeline (2026 → Jul 20 🧪 Blood Test etc.) + full `TimelineView`.
- **My Medicines** `/medicines` — current per ingredient (most recent) + historical log table, filterable, source file traceable.
- **Test Results / Lab Trends** `/labs` — per-test direction, flag sequence, crossing point, approaching-threshold badge, SVG sparkline with reference band (robust parsing for `70-99 mg/dL`).
- **Safety** `/safety` — allergy conflicts (danger), interactions with severity, dosage conflicts, duplicates, overall recommendation.
- **Ask** `/ask` — single-shot RAG, configurable `top_k`, confidence, sources, `recommend_professional_consult`.
- **Conversations** `/conversations` — multi-turn, query rewriting (`rewritten_query`), session resume by ID, 404 handling when in-memory session expired after restart.

States distinguished: loading, empty 404 (no record), 401 auth, 422 validation/non-medical, 502 ML pipeline, network/CORS.

#### Run frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api → http://127.0.0.1:8000
```

`vite.config.ts` proxy target overridable via `VITE_API_PROXY_TARGET`. For prod:

```bash
npm run build
npm run preview
```

### Anonymous session design

No Register → Login → Dashboard. Instead:

```
Open App → Create Anonymous Session (UUID) → Store in localStorage → Patient Workspace
  → Upload → Process → Timeline / Medicines / Safety / Ask
```

- Frontend never asks for JWT. It calls `POST /api/v1/anonymous/session` → `{user_id, token, session_id}`. Token minted server-side with `JWT_SECRET` from `.env`.
- Every further call sends `Authorization: Bearer <token>` + `X-User-Id: <user_id>`.
- Isolation: `Supabase user_id`, `Chroma collection sanitized name`, `Cloudinary mediscan/<user_id>/`.
- New workspace = clear localStorage. Old Supabase rows stay but become orphaned (acceptable for demo).

### Deploying to Railway

`requirements.txt` + `Procfile` (`web: uvicorn api:app --host 0.0.0.0 --port $PORT`) enable Nixpacks auto-detect.

1. Set env vars from `.env.example` in Railway Variables.
2. Persist vector store: attach Railway Volume mounted at `/data/chroma_db`, set `CHROMA_DIR=/data/chroma_db` (code reads env, falls back to `./chroma_db`).
3. Deploy — `$PORT` assigned automatically.

### Auth contract

- `GET /api/v1/health` + `POST /api/v1/anonymous/session` → public.
- Everything else requires:
```
Authorization: Bearer <jwt>
X-User-Id: <user_id>
```
- `user_id` claim may be under `user_id`, `userId`, `id`, `_id`, `sub` — must match header or 401.

### API quick reference

#### Anonymous session
`POST /api/v1/anonymous/session` → `201 {user_id, token, session_id}`

#### Documents
`POST /api/v1/documents` — multipart `files` field. Merges with prior uploads. Validates non-medical via `document_filter.py` (422 if `other` with no clinical content). Returns timeline + cross-check + lab_trends + indexed flag. If `indexed:false` includes `index_error`.

`GET /api/v1/timeline`, `/cross-check`, `/lab-trends` — 404 if no snapshot yet. Lab trends recomputed on-the-fly for old snapshots lacking field.

#### Single-shot Q&A
`POST /api/v1/qa {question, chat_history?, top_k}` → `{answer, confidence, sources[], recommend_professional_consult}`

#### Conversations
`POST /api/v1/sessions` → `{user_id, session_id}`  
`POST /api/v1/sessions/{id}/messages {question, top_k}` → same as Q&A + `rewritten_query`  
`GET /api/v1/sessions/{id}` → full transcript  
`DELETE /api/v1/sessions/{id}` → 204

Errors: 400 empty question, 401 auth, 404 unknown session/no record, 422 non-medical, 502 embedding/LLM failure.

### Inspecting vector store

```bash
python backend/inspect_chroma.py
python backend/inspect_chroma.py "anon_ab12cd34ef56" --limit 20
python backend/inspect_chroma.py "anon_ab12cd34ef56" --type medication
```

### Bugfixes in this release

- Fixed Supabase `order("uploaded_at, id")` invalid syntax → chained orders.
- Replaced deprecated `@app.on_event("startup")` with lifespan.
- Timeline sorting now parses dates via `dateutil.parser` (was lexicographic, broke for `05 Jan 2026`).
- `_parse_range` / sparkline regex now robust to units like `70-99 mg/dL` and avoids `70-99` → `70,-99` misread.
- Upload dedup fixed — previously random suffix prevented dedup.
- Added anonymous session flow so frontend no longer asks for JWT/UserId (secrets stay in `.env`).

### Limitations

- Conversations are in-memory per process — restart drops them (Supabase/Cloudinary data kept).
- Splitting storage: file → Cloudinary, structured → Supabase, embeddings → local Chroma. No raw bytes or tokens persisted in DB.
- CLI (`python medical_extractor.py`) still writes `patient_report_*.json` locally, unauthenticated, for dev.

See `backend/docs/` for pipeline, extraction, and retrieval internals.
