# End-to-end pipeline

Anonymous workspaces. No signup. One browser → one isolated patient record,
keyed by the `user_id` issued at `POST /api/v1/anonymous/session`.

```
Frontend (React + TS + Vite + Tailwind)
        │
        ▼
POST /api/v1/anonymous/session
  → { user_id: anon_*, token, session_id }
  → localStorage.medimind.session.v1
  → Authorization: Bearer <jwt>  +  X-User-Id: <user_id>
        │
        ▼
Dashboard  GET /api/v1/patient-snapshot   (one request, not three)
        │
   ┌────┴────────────────────────────┐
   ▼                                 ▼
Upload                         Ask / Conversations
POST /documents                  POST /qa
  [?async=true → 202]            POST /sessions/{id}/messages
        │                                 │
        ▼                                 ▼
Per-file job progress              conversation.py
queued → reading → extracting        rewrite follow-up
       → saving → ready/failed       (pronouns, keep risk framing)
        │                                 │
        ▼                                 ▼
Clinical pipeline                  retrieval.py
┌─────────────────────┐            chunks → embed → query
│ 1 Extract           │ ← LLM_PROVIDER
│   digital PDF text  │   Groq gpt-oss-120b + Qwen3.6 vision
│   or vision OCR     │   or Gemini 3.6 Flash multimodal
│ 2 Filter            │   document_filter (no extra LLM call)
│ 3 Timeline          │   dateutil sort, merge meds/labs/allergies
│ 4 Safety            │   LLM cross-check + exact-duplicate detector
│ 5 Lab trends        │   deterministic; no LLM
│ 6 Index for Q&A     │   vector_store: chroma | supabase
└──────────┬──────────┘
           │
     ┌─────┼──────────────┐
     ▼     ▼              ▼
 Supabase  Cloudinary   Vector store
 documents mediscan/    VECTOR_STORE=chroma  → CHROMA_DIR
 snapshots <user_id>/   VECTOR_STORE=supabase → chunks table
     └─────┬──────────────┘
           ▼
 Patient record { timeline, cross_check, lab_trends }
           │
  ┌────────┼──────────┬──────────┬──────────┐
  ▼        ▼          ▼          ▼          ▼
History  Medicines  Labs      Safety     Ask AI
chrono   traceable  trends    warnings   grounded
```

## Product surfaces (this branch)

| UI route | Reads | Notes |
|---|---|---|
| `/` | public | Landing. Start workspace → session. |
| `/dashboard` | `GET /patient-snapshot` | Counts, recent visits, safety preview. |
| `/upload` | `POST /documents?async=true` + job poll | Always async from the frontend. |
| `/documents` | snapshot + Cloudinary URLs | Original vs structured tabs. |
| `/history` (`/timeline`) | snapshot timeline | Year-grouped visits. |
| `/medicines` | snapshot timeline | Current + historical, source file. |
| `/labs` (`/lab-trends`) | snapshot / `GET /lab-trends` | Direction, crossing, recovery badge. |
| `/safety` (`/cross-check`) | snapshot safety report | Interactions, duplicates, allergies. |
| `/ask` (`/qa`) | `POST /qa` | Single-shot RAG. |
| `/conversations` (`/sessions`) | session routes | Multi-turn + rewritten query. |
| `/settings` | local only | Workspace reset. |

There is no `/care` or `/find-care` in this tree.

## Upload path (current)

1. Browser sends multipart `files`. Frontend always requests async (`?async=true` or `USE_BACKGROUND_JOBS=true`).
2. API returns `202 { job_id, status }`. Poll `GET /jobs/{id}`.
3. A shared pool (`UPLOAD_FILE_CONCURRENCY`, default 1) processes files independently.
   Progress is **per file** (`queued → reading → extracting → saving → ready/failed`), then a **batch** step (`organizing → safety → indexing → ready`).
4. Digital PDF: `pdfplumber` text → deterministic `looks_like_medical_text` (word-boundary filename check — `recovery.pdf` is not a CV) → text LLM.
   Scanned PDF / image: rasterize → JPEG (max 1600 px) → vision LLM. EXIF orientation applied.
5. After extraction: `assert_medical_document` (`document_filter.py`, no extra LLM). User-uploaded demo/template pages are **not** silently dropped (folder/CLI grouping still drops them).
6. One Cloudinary write per kept file (`mediscan/<user_id>/...`). `_source.file` is the **original filename**, not the temp `001_upload.pdf`.
7. Merge with existing Supabase `documents` → `build_patient_timeline` → `cross_check_prescriptions` → `track_lab_trends` → `index_patient_timeline` → snapshot upsert.
8. Partial success is allowed. Response includes `failed_files[]` with `kind`, `code`, `retryable`. The request only 422/502s when **nothing** was kept.

A hard provider quota (`limit: 0`, daily cap, retired model) trips a circuit breaker so queued files are not sent into the same failure.

## Read path

- Dashboard uses **one** `GET /patient-snapshot`.
- `GET /timeline`, `/cross-check`, `/lab-trends` remain for per-page use.
- `lab_trends` is recomputed when the stored report is missing or predates `returned_to_normal` (so a recovered series does not stay a red alarm).

## Isolation

| Layer | Scope |
|---|---|
| Auth | JWT `user_id` must match `X-User-Id` |
| Postgres | `documents.user_id`, `patient_snapshots.user_id` |
| Files | Cloudinary `mediscan/<user_id>/` |
| Vectors | Chroma collection = sanitized `user_id`, or `chunks.patient_key` |

RLS is on with **no policies**. Only the service-role key (backend) can read or write.

## What this is not

- Not a diagnosis engine.
- Not a validated drug-interaction database.
- Lab trends are arithmetic over extracted numbers, not clinical advice.
- Q&A answers only from indexed structured chunks, never from raw page pixels.
