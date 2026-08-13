# ④ Protect — anonymous workspace isolation

Say: **one anonymous workspace → one isolated patient record.**

Do not say “one browser isolates the patient.” The browser only stores credentials. The backend enforces the boundary.

```text
Browser
   ↓
Anonymous session
   ↓
anon_* user_id
   ↓
JWT + X-User-Id verification
   ↓
user_id-scoped backend operations
```

---

## Isolation slide

Do **not** say “RLS protects the data.”

```text
                    Anonymous Session
                           │
                           ▼
                       anon_* ID
                           │
                           ▼
                     Signed JWT
                           │
                           ▼
                 Backend authentication
                           │
                    ┌──────┴──────┐
                    ▼             ▼
              JWT user_id    Header user_id
                    │             │
                    └──────┬──────┘
                           ▼
                       Must match
                           │
                           ▼
                  user_id-scoped queries
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Supabase         Cloudinary        Vectors
      user_id          mediscan/         patient key
                       <user_id>/
```

RLS is enabled with **no policies**. The service-role key bypasses RLS. Isolation is the authenticated `user_id` after the JWT and header match. For production, add real RLS if a client key could ever reach these tables. It must not.

---

## UI vs API

| UI | Backend |
|---|---|
| Start workspace | `POST /api/v1/anonymous/session` |
| `/upload` | `POST /api/v1/documents` |
| `/dashboard` | `GET /api/v1/patient-snapshot` |
| `/labs` | `GET /api/v1/lab-trends` |
| `/ask` | `POST /api/v1/qa` |
| `/conversations` | `POST /api/v1/sessions` · `POST /api/v1/sessions/{id}/messages` |

Health and anonymous session are public. Everything else requires the bearer token and a matching `X-User-Id`.

---

## What the workspace can do

Upload builds the record. Dashboard reads one snapshot (timeline + safety + labs). Ask / chat read the index of that record. Reset issues a new anonymous user in this browser.

One bad file does not discard the rest of an upload. Chat sessions live in process memory; documents and the snapshot survive a restart.

---

## Engineering notes (appendix)

Uploads may return 202 and a job id. The UI polls per-file progress, then a batch finalization step. A hard provider outage stops queued files.

`CORS_ORIGINS=*` cannot send credentials.

Missing schema → 503. Missing vector table → 502, not an empty-record lie.
