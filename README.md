# MediMind — Anonymous Medical Document Intelligence

MediMind converts your private medical files into something you can actually navigate. Drop in prescriptions, lab reports, and discharge summaries and you get a structured timeline, automatic safety checks, lab trend analysis, and grounded question answering. All of it lives inside a **private anonymous workspace** — no signup, no password, just a `session_id` stored locally in your browser.

**YGC Final Round: 19 / 19 requirements complete.** Official brief: [`docs/YGC_FINAL_ROUND_RULES.md`](docs/YGC_FINAL_ROUND_RULES.md). Evidence: [`docs/YGC_FINAL_ROUND_CHECKLIST.md`](docs/YGC_FINAL_ROUND_CHECKLIST.md). Feature inventory: [`docs/FEATURES.md`](docs/FEATURES.md).

### YGC Final Round — Competition Checklist

#### ROUND 1 BASELINE

- [x] **R1** — Extract data from multiple medical documents (lab reports, prescriptions, notes, discharge summaries)
- [x] **R2** — Merge extracted data into one unified patient timeline
- [x] **R3** — Cross-check prescriptions for interactions, duplicates, or conflicting dosages
- [x] **R4** — Track lab result trends over time
- [x] **R5** — Explain lab trends in plain language
- [x] **R6** — Answer follow-up questions across multiple documents
- [x] **R7** — Give a confidence score for flagged issues
- [x] **R8** — Recommend consulting a doctor for high-risk or low-confidence cases

#### FINAL ROUND NEW FEATURE

- [x] **R9** — Identify the right type of doctor based on the flagged issue (specialty matching)
- [x] **R10** — Ask the user for their location (city/area)
- [x] **R11** — Ask the user for their availability for consultation
- [x] **R12** — Search real, publicly available data using Google Maps Places API or a free alternative (OpenStreetMap/Nominatim)
- [x] **R13** — Display a result list showing: doctor/clinic name, specialty, address, distance, and rating/contact number
- [x] **R14** — Handle no-results gracefully: clear message + suggest widening the search area (no fake results)

#### DATA RULES

- [x] **R15** — All doctor/clinic data must come from a real public source (no synthetic or fabricated data)
- [x] **R16** — App must never present itself as making a diagnosis

#### DELIVERABLES

- [x] **R17** — Working application demonstrating the full end-to-end flow: upload → flag → location asked → doctor list shown
- [x] **R18** — Working web app link with a README explaining which API was used and how
- [x] **R19** — A short demo (5 minutes) covering the full flow — [`docs/DEMO_RUNBOOK.md`](docs/DEMO_RUNBOOK.md)

**Directory APIs used (R12 / R18).** Find Local Care (`/care`) searches **live public listings only** — nothing is seeded or mocked.

| Source | When it is used | How |
|---|---|---|
| **Google Places API (New)** | `PROVIDER_DIRECTORY_SOURCE=google_places` + `GOOGLE_PLACES_API_KEY`, or `CARE_PROVIDER=google` + `GOOGLE_MAPS_API_KEY` | Backend geocodes the city/area, then Nearby Search (coordinates) or Text Search (city text). Key stays server-side. |
| **OpenStreetMap / Nominatim + Overpass** | Default, and automatic fallback | Nominatim geocodes the city/area; Overpass returns nearby doctors/clinics/hospitals. No API key. |

Zero matches return an empty list plus a “widen the search area” message. Missing rating or phone is shown as “Not available”, never invented. Full contract: [`backend/docs/care_recommendations.md`](backend/docs/care_recommendations.md). Deploy: [`docs/DEPLOYMENT_GUIDE.md`](docs/DEPLOYMENT_GUIDE.md).

```
               Original file (PDF/JPG)
                        |
                   ┌────┴─────┐
                   │ Extraction│ ← LLM_PROVIDER (Groq GPT-OSS 120B + Qwen3.6 27B vision
                   │           │   or Gemini 3.6 Flash multimodal, structured JSON)
                   └────┬─────┘
                        |
        ┌───────────────┼────────────────┐
        │               │                │
   Supabase (JSON)  Cloudinary (file)   │
   documents +       mediscan/<user>/   │
   patient_snapshots                    │
        └───────┬───────────────────────┘
                |
            Timeline (visits, diagnoses, symptoms, procedures,
                      vitals, imaging, meds, labs, allergies)
                |
     ┌──────────┼──────────┐
     │          │          │
 Medication  Lab Trends   Vector Store (Chroma or Supabase `chunks`)
 Safety      deterministic   |  ← VECTOR_STORE=chroma (local) or supabase (no volume)
 service                    └──→ RAG Q&A / Conversations (query rewrite)
 (medication_safety.py —
  interactions / duplicates /
  dosage / allergy; not extraction)
     │          │
     └──────────┴──────────→ JSON answer with citations
```

One browser = one isolated patient view. Scoping uses the `user_id` issued via `POST /api/v1/anonymous/session`.

### LLM Provider — Groq or Gemini

All LLM calls go through the OpenAI SDK — only `base_url` / `api_key` / `model` differ. Select with `LLM_PROVIDER` (default `groq` for backward compat):

| Provider | Env key | Base URL | Text model | Vision model | Notes |
|----------|---------|----------|------------|--------------|-------|
| **groq** (default) | `GROQ_API_KEY` (`gsk_...`) | `https://api.groq.com/openai/v1` | `openai/gpt-oss-120b` | `qwen/qwen3.6-27b` | Strict `json_schema` on gpt-oss family; check the provider console for the project's current quota |
| **gemini** (recommended) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` (`AIza...`) | `https://generativelanguage.googleapis.com/v1beta/openai/` | `gemini-3.6-flash` | `gemini-3.6-flash` (multimodal) | Current stable replacement for Gemini 2.0 Flash, which was shut down on 2026-06-01 |
| **generic** | `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` | any OpenAI-compatible | `LLM_MODEL` | `LLM_VISION_MODEL` | Covers Cerebras, OpenRouter, OpenAI, and custom endpoints |

Vision+text use the same Gemini model; Groq needs two. All three are OpenAI-compatible, so the retry ladder (`strict json_schema → json_object → plain text`), `<think>` stripping, and tolerant parser work unchanged. Token budgets / rate-limit caps are provider-aware (`GEMINI_MAX_TOKENS`, `LLM_MAX_TOKENS`, `GEMINI_MAX_RATE_LIMIT_RETRIES`, etc. override `GROQ_*`).

### Backend modules

| File | What it handles |
|---|---|
| `medical_extractor.py` | `LLM_PROVIDER` layer, vision / text extraction, patient grouping, timeline creation, local CLI persistence. Does **not** own medication safety. |
| `medication_safety.py` | Dedicated medication-safety service. Reads the timeline and writes analyses: deterministic interaction KB, allergy KB, duplicates, dosage, drug–lab / renal-hepatic / condition engines, numeric confidence grading. HTTP: `GET /api/v1/medication-safety`. |
| `document_filter.py` | Fast post-extraction filter for non-medical files (no extra LLM call, reuses `document_type` + clinical fields) |
| `lab_trends.py` | Pure Python trend engine — direction, crossings, recovery (`returned_to_normal`), unit-clash decline, and thousands-aware parsing |
| `change_detection.py` / `record_integrity.py` | Deterministic longitudinal change detection and source-linked cross-document discrepancy checks |
| `appointment_prep.py` / `follow_up.py` | Printable clinician handoff plus a stable, grounded follow-up queue without inferred clinical deadlines |
| `record_trust.py` | Immutable correction replay, deterministic conflict detection, authoritative-source state merge, and fail-closed fact/document quarantine |
| `clinical_events.py` | Shared contracts for diagnoses, symptoms, procedures, vital signs, and imaging rollups, correction fields, dates, and evidence-search fallbacks |
| `evidence.py` | Normalizes page/quote/box provenance, remaps vision coordinates, preserves stable evidence IDs, and uses deterministic PyMuPDF search for exact digital-PDF rectangles |
| `retrieval.py` | Chunks only trusted timelines into source-linked medication, lab, diagnosis, note, and allergy evidence; carries source regions through `vector_store`; then runs intent-routed Q&A with injection resistance, evidence-sufficiency gates, stale-index repair, exact citation validation, and confidence caps. Richer response contract (`cross_document`, `low_confidence`, `consult_reason`, sources enriched with `document_type` + `document_url`) plus a deterministic guard that forces `recommend_professional_consult=true` on risk/allergy/dosage questions |
| `vector_store.py` | Abstraction over Chroma (`VECTOR_STORE=chroma`, local `CHROMA_DIR`) and Supabase `chunks` table (`VECTOR_STORE=supabase`, no volume, brute-force cosine) |
| `jobs.py` | Thread-safe parent jobs with independent per-file progress (`queued → reading → extracting → saving → ready/failed`) and optional Supabase persistence |
| `conversation.py` | In-memory conversation store, rewrites follow-ups like “was that safe?” into self-contained retrieval queries, summarizes older turns to keep context bounded, and keeps a deterministic **entity focus** (medications/labs/documents under discussion) matched against the patient's own record vocabulary — so a follow-up's subject survives even if the LLM rewrite fails |
| `document_dedup.py` | Same-prescription detection: tags re-uploads / scan+photo copies of one prescription with a shared `prescription_group` so duplicate detection counts prescriptions, not files (nothing is ever deleted) |
| `evidence_grading.py` | Grades every safety finding by what backs it (`deterministic` vs `model_knowledge`), caps ungrounded model confidence at 0.6, keeps the model's original claim visible |
| `risk_timeline.py` | Places every safety finding in time using prescription dates/durations (`concurrent` / `possible` / `not_concurrent` / `unknown`), computes double-dosing exposure windows and a chronological risk calendar |
| `api.py` | FastAPI wrapper — lifespan startup, CORS (fixed `*` + credentials handling), all `/api/v1/` routes, multipart upload handling (sync 201 or async 202 via `USE_BACKGROUND_JOBS`/`?async=true`), merges new docs with old, fixes `_source.file` to original filename. Re-uploads are detected before extraction: byte-for-byte identical files (`CBC_Report.pdf` / `CBC_Report (1).pdf`) are skipped via `content_sha256` and reported in `duplicate_files_skipped`. Also serves `GET /api/v1/risk-timeline` (chronological risk view + evidence grades) |
| `care_finder.py` | Find Care — specialty suggestion from the record; Geoapify geocode + Places primary, OpenStreetMap Nominatim + Overpass fallback; opening-hours match, ranking. Leaflet map |
| `auth.py` | Validates `Authorization: Bearer <jwt>` + `X-User-Id`, plus issues anonymous JWTs via `issue_anonymous_token()` |
| `care/` | Provider-neutral `Facility` model/factory plus the server-side Google Places API (New) adapter for Find Care |
| `db.py` | Supabase Postgres persistence (documents append-only + patient snapshot upsert), chained `.order("uploaded_at").order("id")` |
| `storage.py` | Uploads original file to Cloudinary `mediscan/<user_id>/...` |
| `supabase_schema.sql` | One-time table creation with RLS enabled/no policies (only service_role key can access) |
| `care/` | Optional Care Navigation: provider-agnostic facility search. Does not read the patient record. |
| `inspect_chroma.py` | Read-only CLI to list collections / inspect chunks |
| `requirements.txt` / `Procfile` | Railway Nixpacks deployment |

Deep dives live in [`backend/docs/`](backend/docs/README.md). Freeze [01-end-to-end-pipeline.md](backend/docs/01-end-to-end-pipeline.md) for the deck: Understand → Detect → Explain → Protect. No `/care` on this branch.

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

**Required vars:**

```ini
# LLM — pick one (Gemini recommended for multimodal document reading)
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...          # create/manage at aistudio.google.com/app/apikey
# or: LLM_PROVIDER=groq + GROQ_API_KEY=gsk_...

CLOUDINARY_CLOUD_NAME=...
CLOUDINARY_API_KEY=...
CLOUDINARY_API_SECRET=...
SUPABASE_URL=https://your-ref.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJ...   # service_role, NOT anon
JWT_SECRET=some-long-random-string  # openssl rand -hex 32

# optional
OPENAI_API_KEY=sk-...   # only for embeddings, else local ONNX
VECTOR_STORE=supabase   # or chroma — supabase uses Supabase `chunks` table (no volume, recommended for Railway)
CHROMA_DIR=./chroma_db   # only for VECTOR_STORE=chroma, override to /data/chroma_db on Railway volume
USE_BACKGROUND_JOBS=true # async 202 + polling for uploads
UPLOAD_FILE_CONCURRENCY=1 # shared worker limit; raise only if provider quota supports it
CORS_ORIGINS=*          # or https://your-frontend

# optional provider overrides
# GEMINI_MODEL=gemini-3.6-flash
# GROQ_MODEL=openai/gpt-oss-120b
# LLM_MODEL=gpt-4o-mini            # generic OpenAI-compatible
# GEMINI_MAX_TOKENS=4096
# GEMINI_MAX_COMPLETION_TOKENS=16384  # ceiling when escalating a truncated (finish_reason=length) generation
# LLM_MAX_RATE_LIMIT_RETRIES=5
```

Full options see `backend/.env.example` (Groq, Gemini, Cerebras, OpenRouter examples with free-tier notes).

Embeddings fallback chain (Groq/Gemini have no embeddings API):
1. OpenAI `text-embedding-3-small` if `OPENAI_API_KEY`
2. Chroma's local `ONNXMiniLM_L6_V2`

If you switch embedding backends, delete `./chroma_db` and re-upload.
If you switch `LLM_PROVIDER`, no code change needed — just env + restart.

#### Supabase one-time setup

1. Create project at supabase.com.
2. SQL Editor → paste `backend/supabase_schema.sql` → Run. Re-run the idempotent file after upgrades; it creates `documents`, `patient_snapshots`, `chunks`, `extraction_corrections`, `record_conflicts`, `conflict_resolution_events`, indexes, grants, and RLS.
3. Copy Project URL + service_role key into `.env`.

### Running backend

```bash
cd backend
uvicorn api:app --reload
# docs at http://127.0.0.1:8000/docs
```

Base URL `http://127.0.0.1:8000`, all routes under `/api/v1/`.

### Frontend — MediMind workspace

`frontend/` is React + TS + Vite + Tailwind. It includes a reusable translation provider and catalogs for English, Sinhala, and Tamil; browser/saved language detection; locale-aware formatting; and WCAG-oriented landmarks, keyboard interaction, live regions, focus handling, reduced-motion support, and semantic medical-data views. See [`frontend/ACCESSIBILITY_I18N.md`](frontend/ACCESSIBILITY_I18N.md).

Zero-login anonymous model:

- **Landing** `/` — hero, anonymous session explanation, Start My Health Record → auto-creates workspace via `POST /anonymous/session` (token stored in `localStorage.medimind.session.v1`).
- **Overview / Dashboard** `/dashboard` — documents / clinical events / medicines / labs / safety counts, latest safety warnings, recent history, pipeline hint.
- **Upload** `/upload` — drag-drop and dedup (`name-size-lastModified`); shows each document's independent queue/read/extract/save state, then clearly separates the one-time record finalization steps (history → safety → search).
- **My Documents** `/documents` — original and structured extraction plus **Correct & Audit**. “View evidence” beside dates, identities, medicines, labs, allergies, and notes opens the cited page and draws the saved region when exact geometry exists. Corrections are append-only and preserve every original/before/after value.
- **Trust Review** `/review` — quarantines conflicting evidence, records an authoritative source decision, supports reopening, and rebuilds all derived views.
- **My History** `/history` — event-date-specific longitudinal diagnoses, symptoms, procedures, vital signs, and imaging with evidence deep links, plus the year-grouped source-document timeline and full `TimelineView`.
- **My Medicines** `/medicines` — current per ingredient (most recent) + historical log table, filterable, source file traceable (now fixed to original filename, not temp sanitized path).
- **Test Results / Lab Trends** `/labs` — per-test direction, flag sequence, crossing / recovery badge (green when the latest reading is back to normal), approaching-threshold, SVG sparkline with reference band. Thousands-aware values; mixed units (`mg/dL` vs `mmol/L`) are declined rather than trended.
- **Safety** `/safety` — allergy conflicts (danger), interactions with severity, dosage conflicts, duplicates, overall recommendation.
- **What Changed** `/changes` — deterministic consecutive-record comparisons with before/after source evidence.
- **Appointment Prep** `/appointment-prep` — printable handoff and prioritized record-grounded clinician questions.
- **Action Center** `/follow-up` — combined follow-up queue with browser-only completion state, user-selected reminder dates, and `.ics` calendar export.
- **Record Check** `/record-integrity` — side-by-side identity, allergy, same-date lab, and medication-instruction discrepancies.
- **Ask** `/ask` — intent-routed RAG with evidence sufficiency, verbatim source quotes, exact-highlight deep links, injection resistance, citation validation, and confidence caps.

##### Ask AI groundedness

For a medical RAG product a confidently wrong answer is worse than no answer, so the answer path is defended at three layers rather than by prompt wording alone:

| Layer | Where | Guarantee |
| --- | --- | --- |
| Instruction | `QA_SYSTEM_PROMPT` | Refuses to diagnose, to advise starting/stopping/changing a dose, or to supply a value absent from the records |
| Isolation | `_neutralize_injection()` + `<patient_records>` fencing | Retrieved documents are untrusted **data**; instruction-shaped text is defanged and the boundary is restated after the block, so an injected line can't pose as the final instruction |
| Verification | `_validate_answer()` | Citations the model invents are **dropped** before reaching the UI, dates are corrected to what was retrieved, pages come from chunk metadata, and an answer with no verifiable source is capped at 0.5 confidence |

The UI completes the chain: every citation is a button that opens the exact source document (and page) behind the claim — `Ask AI → citation → source document → page evidence`. When nothing supported an answer the card says so explicitly instead of looking equally authoritative.

Citations resolve to documents by **exact** filename match (`frontend/src/utils/sources.ts`); a near-miss returns nothing rather than opening the wrong record.
- **Conversations** `/conversations` — multi-turn, query rewriting (`rewritten_query`), session resume by ID, 404 handling when in-memory session expired after restart.
- **Find Local Care** `/care` — evidence-to-care pathway: clinical flags → specialty → live directory (**Geoapify** primary, **OpenStreetMap** fallback) → ranked provider cards → consultation pack.
- **Find Care** `/find-care` — search-as-you-type or current location → map confirmation → provider-neutral hospitals, clinics, pharmacies, laboratories, and doctors within the selected radius.
- **About MediMind** `/about` — current capabilities, hybrid architecture, safety/data boundaries, and an honest prioritized roadmap.

States distinguished: loading, empty 404 (no record), 401 auth, 422 validation/non-medical, 502 ML pipeline, network/CORS.

#### Source evidence contract

Every supported extracted fact carries one or more evidence regions with a stable `evidence_id`, 1-based source `page`, verbatim `quote` when established, confidence, locator method, and optional `bbox`. Boxes use `[left, top, right, bottom]` coordinates normalized to `0..1`, so the UI can overlay them at any rendered size.

- Digital PDFs: the model supplies the quote/page, then PyMuPDF searches the original PDF and replaces model geometry with a deterministic text rectangle.
- Scanned PDFs and images: the vision model supplies a tight `0..1000` box, which the backend normalizes to `0..1`; scanned page-local coordinates are remapped to the original PDF page.
- Unmatched or legacy records: MediMind keeps an honest page/quote or page-only link and does **not** fabricate a rectangle or claim an extracted legacy value is verbatim.
- Corrections and conflict decisions annotate the linked source region while preserving original extraction provenance. Retrieval metadata and Q&A citations carry the same evidence ID, quote, page, and box.

Cloudinary PDF page conversion is used for in-app overlays when available. If transformed preview delivery is unavailable, the viewer falls back to the original PDF page and saved quote without pretending that an exact overlay was rendered.

#### Longitudinal clinical events

The extraction contract also returns separate `diagnoses`, `symptoms`, `procedures`, `vital_signs`, and `imaging_results` arrays. Every item has its own confidence and evidence, plus an event-specific date where the source prints one. The timeline exposes corresponding chronological rollups (`diagnoses_timeline`, `symptoms_timeline`, `procedures_timeline`, `vital_signs_timeline`, and `imaging_results_timeline`) with document date, event date, source page, document ID, and correction path.

These fields remain documentary: MediMind does not infer a diagnosis from medication, symptoms, labs, vitals, or imaging. Values and units are retained as printed until a separately validated terminology/unit-normalization layer is available. Explicitly conflicting vital measurements at the same recorded time are quarantined for source review, while undated serial observations are not treated as contradictions.

#### Run frontend

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173, proxies /api → http://127.0.0.1:8000
npm run lint      # TypeScript verification
npm run test      # auth, i18n, axe accessibility, keyboard, geolocation, and care regressions
npm run build     # production bundle
```

#### Find nearby care and reusable location picker

Open `/find-care` to select an area and find hospitals, clinics, pharmacies, laboratories, and doctors within 5 km. The page uses the search → map → confirm `LocationPicker`, which is exported from `src/components/location` and emits a normalized `ConfirmedLocation` containing `latitude`, `longitude`, place labels, optional address details, and `confirmedAt`:

```tsx
import { LocationPicker, type ConfirmedLocation } from "./components/location";

<LocationPicker
  onConfirm={(location: ConfirmedLocation) => saveServiceLocation(location)}
  countryCodes={["lk"]} // optional; omit for worldwide search
/>;
```

**"Use my current location" accuracy.** The picker calls `getAccuratePosition()` (`src/services/geolocation.ts`) rather than a bare `getCurrentPosition()`. It requests `enableHighAccuracy` with `maximumAge: 0`, then *watches* the position and keeps the most precise reading, resolving as soon as the fix is within 30 m (or returning the best reading at the 15 s deadline). This avoids locking onto the coarse Wi-Fi/IP estimate that arrives first, which is often off by hundreds of metres. Reverse geocoding only supplies the place *name*: the device's own latitude/longitude are preserved, so a nearby street or suburb centroid can never move the pin. The confirm step shows the GPS accuracy radius as a badge and a map circle, and prompts the user to drag the pin when the fix is coarser than 150 m. Run `npm run test:geolocation` for the 9 regression tests covering this.

The location picker combines Photon/OpenStreetMap landmark search with Open-Meteo/GeoNames city prefix matching and Leaflet/OpenStreetMap tiles. Confirmed coordinates are sent to the authenticated backend, which normalizes every provider's response to `Facility[]`. By default the backend queries OpenStreetMap/Overpass, which needs no API key. Optionally set `CARE_PROVIDER=google` to prefer Google Places API (New) Nearby Search (city/area-only requests use Places Text Search), with OpenStreetMap as an automatic fallback. Configure `GOOGLE_MAPS_API_KEY` only on the backend—never as a `VITE_*` variable—and enable **Places API (New)** plus billing for the key's Google Cloud project.

The location picker combines Photon/OpenStreetMap landmark search with Open-Meteo/GeoNames city prefix matching and Leaflet/OpenStreetMap tiles. Confirmed coordinates are sent to the authenticated backend, where `CARE_PROVIDER=google` uses Google Places API (New) Nearby Search and normalizes results to `Facility[]`; city/area-only legacy requests fall back to Places Text Search. Configure `GOOGLE_MAPS_API_KEY` only on the backend—never as a `VITE_*` variable. Enable **Places API (New)** and billing for the key's Google Cloud project.

#### Discovery vs. navigation layers

The two mapping stacks have distinct jobs, and neither replaces the other:

| Layer | Provider | Responsibility |
| --- | --- | --- |
| Place search / geocoding | Photon + Open-Meteo (OpenStreetMap data) | Turn the user's typing or GPS fix into a name + coordinates |
| Map tiles / pin picking | Leaflet + OpenStreetMap tiles | Show and adjust the search pin, and plot results — no browser-side API key |
| Facility directory | Google Places API (New), server-side | Facility identity, address, rating, reviews, phone, opening hours |
| Navigation | Google Maps deep links | "Open in Google Maps" from every result card |

Every result card's map action resolves through `googleMapsUrl()` in `frontend/src/utils/facilities.ts`, which prefers Google's canonical `googleMapsUri` and otherwise builds a `https://www.google.com/maps/search/` link from the facility's real name + address (coordinates as a last resort). OpenStreetMap is never used as a navigation target.

#### Category normalization (one source of truth)

Google place types are collapsed to exactly one of `hospital`, `clinic`, `pharmacy`, `laboratory`, `doctor`, or `other` by `normalize_kind()` (`backend/care/providers/google.py`), mirrored client-side by `normalizeFacilityKind()`. The filter chips, their counts, and the rendered cards are all derived from that single normalized array through the same predicate, so the category totals can never disagree with what is on screen. Unclassifiable healthcare listings fall into `other` rather than disappearing.

#### No fabricated data

Rating, review count, phone, address, and opening hours are emitted only when the directory published them. Missing values stay `null` end-to-end and the card renders an explicit "Not available"; an unnamed listing is dropped rather than labelled with a generic category name.

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
- `AuthContext` now correctly resets `provisioningStarted` on `clearCredentials`/`createNewWorkspace` — erasing workspace no longer stalls auto-provision (fixed StrictMode double-invoke guard).
- New workspace = clear localStorage. Old Supabase rows stay but become orphaned (acceptable for demo).

### Deploying to Railway

`requirements.txt` + `Procfile` (`web: uvicorn api:app --host 0.0.0.0 --port $PORT`) enable Nixpacks auto-detect.

1. Set env vars from `.env.example` in Railway Variables (`LLM_PROVIDER` + provider key, plus `SUPABASE_*`, `CLOUDINARY_*`, `JWT_SECRET`, `VECTOR_STORE=supabase` recommended).
2. **No volume needed if `VECTOR_STORE=supabase`** (uses Supabase `chunks` table). For `VECTOR_STORE=chroma`, attach Railway Volume mounted at `/data/chroma_db`, set `CHROMA_DIR=/data/chroma_db`.
3. Set `USE_BACKGROUND_JOBS=true` and keep `UPLOAD_FILE_CONCURRENCY=1` for constrained quotas. Uploads return 202 immediately, while a shared bounded worker pool load-balances files and the frontend polls per-file progress.
4. Deploy — `$PORT` assigned automatically.

### Live local care recommendations (Round 2)

`/care` activates only when the saved Round 1 snapshot contains an existing high-risk medication-safety signal or a low-confidence extraction/trend/safety result. The user selects the flagged evidence, enters a city/area and consultation preference, and the backend searches a **live provider directory**. Provider data is never seeded, mocked, hard-coded, or sent from the frontend.

- `GET /api/v1/care-recommendations` returns the authenticated user’s qualifying flags and transparent specialty rationale. It does not call a directory.
- `POST /api/v1/care-recommendations/search` accepts `{flag_id, location, availability}` and returns only source-provided provider fields, calculated distance, and explainable ranking.
- Set `PROVIDER_DIRECTORY_SOURCE=google_places` + `GOOGLE_PLACES_API_KEY` for Google Places, or `PROVIDER_DIRECTORY_SOURCE=openstreetmap` + the required identifying `OSM_NOMINATIM_USER_AGENT` for the public Nominatim/Overpass alternative. Full source, ranking, and failure contract: [`backend/docs/care_recommendations.md`](backend/docs/care_recommendations.md).
- Results visibly state `Live provider data — <source>`. A zero-result response is an empty list with a widening-search suggestion, never fabricated clinicians.
- MediMind does not diagnose. This navigation aid helps find an appropriate professional to review existing potential issues or uncertain extractions.

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
`POST /api/v1/documents` — multipart `files` field. Merges with prior uploads. Validates non-medical via `document_filter.py` (422 if `other` with no clinical content). Fixes `_source.file` to original filename (not temp path). Returns timeline + cross-check + lab_trends + indexed flag. If `indexed:false` includes `index_error`. Failures are per-file: one unreadable/non-medical file no longer fails the whole batch — kept files are merged normally and response includes `failed_files: [{file, file_id, file_index, error, kind, code, retryable, retry_after_seconds}]`. Provider traces are logged server-side; clients receive short, actionable messages. The request only fails outright when nothing was kept: 422 for content problems, 502 for a provider/storage interruption.

`GET /api/v1/timeline`, `/cross-check`, `/lab-trends` — 404 if no snapshot yet. Reads replay current corrections and quarantine policy so an older snapshot cannot leak conflicting facts.

#### Corrections and source conflicts

- `GET /api/v1/documents/{document_id}/corrections` returns immutable original/effective extraction and audit events.
- `POST /api/v1/documents/{document_id}/corrections` appends allowlisted field changes and rebuilds timeline, safety, trends, snapshots, and vectors.
- `GET /api/v1/conflicts?include_inactive=true` returns active and superseded conflict state plus resolution history.
- `POST /api/v1/conflicts/{id}/resolve` selects an authoritative source; `POST /api/v1/conflicts/{id}/reopen` quarantines it again.

#### Intelligence and action layer
- `GET /api/v1/changes` — consecutive-record changes with both sources.
- `GET /api/v1/record-integrity` — cross-document discrepancies requiring verification.
- `GET /api/v1/appointment-prep` — printable clinician handoff and question agenda.
- `GET /api/v1/follow-up` — stable action queue; reminder dates/completion stay browser-side and are never clinically inferred.

#### Single-shot Q&A
`POST /api/v1/qa {question, chat_history?, top_k}` → `{answer, confidence, sources[], recommend_professional_consult}`. Each current source may include `{date, source_file, page, document_id, evidence_id, quote, bbox, verification_status, evidence_tier}`; the server normalizes these fields back to retrieved metadata so the model cannot invent a source location.

Q&A classifies each question as medication, medication safety, lab result, lab trend, allergy, timeline, record change, or general. Vector candidates are filtered to compatible structured evidence; trend/change questions require at least two distinct dated source entries. With no matching evidence, MediMind responds without calling the answer model. Returned citations are validated against retrieved metadata, and limited/uncited answers have confidence capped.

Q&A self-heals when the vector index is empty, stale after a correction/source decision, or incomplete. The current trusted timeline fingerprint and chunk count are checked before retrieval; unresolved and non-authoritative evidence never enters the prompt. If `VECTOR_STORE=supabase` and the `chunks` table is missing entirely, Q&A returns 502 with instructions to run `supabase_schema.sql` rather than a misleading empty answer.

#### Conversations
`POST /api/v1/sessions` → `{user_id, session_id}`
`POST /api/v1/sessions/{id}/messages {question, top_k}` → same as Q&A + `rewritten_query`
`GET /api/v1/sessions/{id}` → full transcript
`DELETE /api/v1/sessions/{id}` → 204

#### Jobs (async uploads)
- `POST /api/v1/documents?async=true` (or `Prefer: respond-async` or `USE_BACKGROUND_JOBS=true`) → `202 {job_id, status}`. A shared pool (`UPLOAD_FILE_CONCURRENCY`, default 1) load-balances extraction work.
- `GET /api/v1/jobs/{job_id}` → `{job_id, status, progress, result, error}` where `progress.files[]` contains each file's independent state/counters and `progress.step` is the batch-wide finalization state.
- `GET /api/v1/jobs` → `{jobs: [...]}` (recent 20, per-user).

Frontend `UploadPage` always uses async jobs so even a small file has truthful progress; it uses the legacy sync path only when a server explicitly returns 404/405 for job routes.

#### Care navigation
`GET /api/v1/care/facilities?location=Jaffna&kind=hospital&radius_km=8` returns normalized public `Facility[]` listings. Map-confirmed clients should also send `latitude` and `longitude` to use distance-ranked Nearby Search. Supported kinds: `any`, `hospital`, `clinic`, `pharmacy`, `laboratory`, and `doctor`.

It works with **no configuration and no API key**. Unset `CARE_PROVIDER` (or `CARE_PROVIDER=osm`) uses OpenStreetMap via the Overpass API — no key, no billing, no Google Cloud project:

```ini
# Nothing required. Optionally, prefer Google and keep OSM as a safety net:
CARE_PROVIDER=google
GOOGLE_MAPS_API_KEY=AIza...  # Places API (New) enabled; billing attached
CARE_FALLBACK=on             # default; set "off" to disable the OSM fallback
```

Keys stay server-side. With `CARE_PROVIDER=google`, a Google rejection (invalid/truncated key, Places API (New) not enabled, billing not attached, restrictive key rules) or an empty Google result set transparently falls back to OpenStreetMap, so the page keeps working; the specific provider reason is logged for operators only. A 503 now means every provider failed — typically blocked outbound network egress; point `OVERPASS_API_URL` at a reachable mirror if needed.

#### Vector Store
`VECTOR_STORE=chroma` (default, local `CHROMA_DIR`) or `supabase` (Supabase `chunks` table, no volume). `inspect_chroma.py` works with both (`VECTOR_STORE=supabase python inspect_chroma.py`). After switching backends, delete `chroma_db` or clear `chunks` table and re-upload.

#### Find care
`DELETE /api/v1/documents/{document_id}` — permanently deletes the selected physical upload (all extracted pages), removes its stored original and corrections, then rebuilds the timeline, labs, conflicts, derived reports, and Q&A index from the remaining records.

`DELETE /api/v1/workspace` — permanently deletes the authenticated workspace's originals, documents, snapshots, vector chunks, corrections, conflict/referral history, conversations, jobs, and audit metadata. The Settings screen keeps this separate from “Remove from this browser,” which only forgets the local anonymous access key.

`GET /api/v1/care/suggestion` — specialty suggestion from the caller's saved records (general practice if none).
`GET /api/v1/care/specialties` — same payload (catalogue + suggestion).
`POST /api/v1/care/search {city, specialty?, days?, time_of_day?, radius_km?}` — **Geoapify** geocodes and lists nearby clinics/doctors/hospitals when `GEOAPIFY_API_KEY` is set; **OpenStreetMap** (Nominatim + Overpass) is the automatic fallback. Ranked by specialty match + opening hours + distance. The frontend map is **Leaflet**. Response `source.name` is `Geoapify` or `OpenStreetMap` — the UI never says a provider failed. 422 `city_not_found` if the city is unknown; 502 `directory_unavailable` (retryable) if both directories are down.

Errors: 400 empty question, 401 auth, 404 unknown session/no record, 422 non-medical / unknown city, 502 embedding/LLM / directory failure (provider-aware: `Provider 'gemini' ...` / `Provider 'groq' ...`).

### Inspecting vector store

```bash
# Chroma (default)
python backend/inspect_chroma.py
python backend/inspect_chroma.py "anon_ab12cd34ef56" --limit 20
python backend/inspect_chroma.py "anon_ab12cd34ef56" --type medication
# Supabase (no volume)
VECTOR_STORE=supabase python backend/inspect_chroma.py "anon_ab12cd34ef56"
```

### What changed

- **Sticky sidebar** — the desktop sidebar is now `lg:sticky lg:top-0 lg:h-screen lg:self-start` instead of a flex child stretched by its sibling, so it stays fixed in the viewport on long pages rather than scrolling away and growing to the content height.
- **Accurate current location** — "Use my current location" now refines the GPS fix instead of accepting the first coarse estimate, never lets reverse geocoding move the confirmed coordinates, and surfaces the accuracy radius so the user can correct a poor fix.
- **Find Care no longer needs an API key** — the directory defaults to a keyless OpenStreetMap/Overpass adapter, and `CARE_PROVIDER=google` now falls back to it whenever Google is unconfigured, rejects the call (e.g. `PERMISSION_DENIED` from a project without Places API (New)/billing), or returns nothing. This removes the "Nearby search didn't load" 503 that a missing/invalid Google key used to cause. Set `CARE_FALLBACK=off` to restore strict Google-only behaviour.
- **Google care-directory adapter** — `CARE_PROVIDER=google` calls Places API (New) instead of returning a stubbed empty list. Coordinate searches use Nearby Search; legacy city/area searches use Text Search. Responses are normalized and API keys remain backend-only.
- **Find care** — `/care` searches real clinics with **Geoapify first** (geocoding + Places, free key, no card) and **OpenStreetMap / Overpass as fallback**. Leaflet draws the map. The UI labels the provider source (`Geoapify` or `OpenStreetMap`) without saying a directory failed. Specialty is suggested from the record; results rank by specialty match, opening hours vs the requested window, and distance.
- **Google care-directory adapter** — `CARE_PROVIDER=google` now calls Places API (New) instead of returning a stubbed empty list. Coordinate searches use Nearby Search; legacy city/area searches use Text Search. Responses are normalized and API keys remain backend-only.
- **Current Gemini model** — the Gemini default is `gemini-3.6-flash` for text and vision, with `gemini-3.5-flash-lite` fallback. The retired `gemini-2.0-flash` default (shut down 2026-06-01) was the source of misleading HTTP 429 `limit: 0` failures.
- **Vector store abstraction** — `vector_store.py` with `VECTOR_STORE=chroma` (local `CHROMA_DIR`, needs volume) or `supabase` (Supabase `chunks` table, no volume, brute-force cosine). `retrieval.py` now delegates, `inspect_chroma.py` supports both, `supabase_schema.sql` adds `chunks` table. Recommended for Railway: `VECTOR_STORE=supabase`.
- **Per-file jobs + load control** — one parent job exposes independent child states for every document, while a shared bounded executor (`UPLOAD_FILE_CONCURRENCY`) queues work safely across uploads. The UI shows per-file phases separately from batch finalization, and a terminal provider quota opens a circuit breaker so queued files are not sent into the same failure repeatedly.
- **CORS** — `CORS_ORIGINS="*"` now correctly sets `allow_credentials=False` (previously `True` with `*` is rejected by browsers).
- **Upload `_source.file`** — now stores original filename, not temp sanitized path (`001_upload.pdf` → real name), so timeline/medicines correctly trace sources.
- **`GROQ_API_KEY` placeholder handling** — legacy var now treats `your-groq-api-key` / `your-*` as missing, not valid.
- **AuthContext** — `clearCredentials`/`createNewWorkspace` reset `provisioningStarted` so erasing workspace no longer stalls auto-provision after StrictMode guard.
- **DocumentViewer** — PDF detection now strips query params (`split("?")[0]`) so Cloudinary `...pdf?dl=0` renders as iframe, not broken image.
- **Docs** — project docs live in `docs/` (competition checklist, features, deploy, demo). `backend/docs/` is the architecture source of truth: Understand → Detect → Explain → Protect, plus the live-directory contract in `care_recommendations.md`.
- Earlier: Supabase chained `.order("uploaded_at").order("id")`, lifespan, dateutil sorting, `_parse_range` robust to `70-99 mg/dL`, upload dedup fix, anonymous session flow.

### Limitations

- Conversations and background jobs are in-memory per process (with optional Supabase `jobs` table if `USE_SUPABASE_JOBS=true`) — restart drops in-memory (Supabase/Cloudinary data kept). For prod, move to Supabase `jobs` + `chunks` fully.
- Splitting storage: file → Cloudinary, structured → Supabase, embeddings → Chroma or Supabase `chunks` (via `VECTOR_STORE`). No raw bytes or tokens persisted in DB.
- CLI (`python medical_extractor.py`) still writes `patient_report_*.json` locally, unauthenticated, for dev.

See `backend/docs/` for pipeline, extraction, and retrieval internals.
