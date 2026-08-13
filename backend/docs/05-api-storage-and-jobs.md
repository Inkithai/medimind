# API, storage, and jobs

Thin HTTP wrapper. Clinical logic stays in `medical_extractor.py`, `lab_trends.py`, `retrieval.py`, `conversation.py`.

Base path: `/api/v1/`. Interactive docs: `/docs`.

## Auth

| Route | Auth |
|---|---|
| `GET /health`, `GET /`, `POST /anonymous/session` | public |
| everything else | `Authorization: Bearer <jwt>` **and** `X-User-Id` |

`POST /anonymous/session` mints `{ user_id, token, session_id }` with `JWT_SECRET`. `user_id` looks like `anon_*`. The JWT claim may be under `user_id`, `userId`, `id`, `_id`, or `sub`, and **must match** the header.

Frontend never asks for a password. Token lives in `localStorage.medimind.session.v1`. `AuthContext` resets its StrictMode provision guard when the workspace is erased so a new session can be created.

## CORS

`CORS_ORIGINS` (default `*`).

`allow_origins=["*"]` **cannot** be paired with `allow_credentials=True` — browsers reject it. When origins is `*`, credentials are off. A concrete origin list turns credentials on.

## Persistence

| Store | Module | What |
|---|---|---|
| Supabase `documents` | `db.py` | append-only extracted pages, `user_id` + `uploaded_at` + `id` order |
| Supabase `patient_snapshots` | `db.py` | latest `{ timeline, cross_check, lab_trends, updated_at }` |
| Supabase `chunks` | `vector_store.py` | optional RAG store (`VECTOR_STORE=supabase`) |
| Supabase `jobs` | `jobs.py` | optional if `USE_SUPABASE_JOBS=true` |
| Cloudinary | `storage.py` | original file at `mediscan/<user_id>/…` |
| Chroma `CHROMA_DIR` | `vector_store.py` | default RAG store |
| process memory | `conversation.py`, `jobs.py` | sessions + jobs unless persisted |

Run `backend/supabase_schema.sql` once. RLS is enabled with **no policies**. Only the service-role key (backend) can access the tables. Missing tables raise `SchemaNotInitializedError` → HTTP 503 with the SQL-editor hint.

## Upload

`POST /api/v1/documents` multipart field `files`.

| Mode | How | Response |
|---|---|---|
| Sync | default (tests) | `201` full record |
| Async | `USE_BACKGROUND_JOBS=true` or `?async=true` or `Prefer: respond-async` | `202 { job_id, status }` |

Frontend always uses async. Poll `GET /jobs/{id}` (`progress.files[]` is per-file; `progress.step` is the batch finalizer). `GET /jobs` lists the last 20 for the user.

Shared worker pool: `UPLOAD_FILE_CONCURRENCY` (default 1). One file’s `queued` state is truthful — it does not claim to be reading while it waits for a slot.

Per-file outcomes do not fail the batch. `failed_files[]`:

```jsonc
{ "file", "file_id", "file_index", "error", "kind", "code", "retryable", "retry_after_seconds" }
```

`kind`: `not_medical` | `transient` | `invalid` | `unsupported` | `rate_limited` | `provider_unavailable`.

The whole request fails only when nothing was kept: 422 for content, 502 for provider/storage.

`indexed: false` + `index_error` when the timeline has no retrievable chunks. `_source.file` is the original filename.

## Read routes

| Method | Path | 404 if |
|---|---|---|
| GET | `/patient-snapshot` | no snapshot (first-run empty state) |
| GET | `/timeline` | no snapshot |
| GET | `/cross-check` | no snapshot |
| GET | `/lab-trends` | no snapshot; recomputes stale reports |

Stale = missing `lab_trends`, or any trend lacking `returned_to_normal`.

## Q&A routes

| Method | Path | Errors |
|---|---|---|
| POST | `/qa` | 400 empty, 502 embed/LLM/schema |
| POST | `/sessions` | 201 |
| POST | `/sessions/{id}/messages` | 404 unknown session, 400/502 as above |
| GET | `/sessions/{id}` | 404 |
| DELETE | `/sessions/{id}` | 204 / 404 |

## Jobs (`jobs.py`)

In-memory dict + optional Supabase `jobs` row. Each job has independent child file states. Expired jobs are cleaned on access. Restart drops in-memory jobs; Cloudinary / Supabase documents remain.

## Errors the client is meant to understand

| HTTP | When |
|---|---|
| 400 | empty question, unsupported extension (sync pre-check) |
| 401 | bad/missing JWT or user-id mismatch |
| 404 | no snapshot / unknown session / unknown job |
| 422 | nothing kept was medical |
| 502 | provider, embedding, safety, or storage interruption |
| 503 | Supabase schema not initialized |

Provider traces stay in server logs. Clients get a short sentence plus `code` / `retryable`.

## Frontend mapping

Same capabilities, patient-facing paths:

`/dashboard` `/upload` `/documents` `/history` `/medicines` `/labs` `/safety` `/ask` `/conversations` `/settings`

Legacy aliases still work: `/timeline`, `/cross-check`, `/lab-trends`, `/qa`, `/sessions`.
