# Trust and isolation

One browser → one isolated patient workspace. No signup.

```text
Anonymous session
       │
       ▼
   anon_* user_id
       │
 ┌─────┼─────┬──────────┐
 ↓     ↓     ↓          ↓
DB   Files  Vectors   Sessions
 │     │      │          │
 └─────┴──────┴──────────┘
          │
          ▼
   Isolated workspace
```

Modules: `api.py`, `auth.py`, `db.py`, `storage.py`, `jobs.py`.

---

## How isolation actually works

Do **not** say “RLS protects the data.”

```text
Frontend
   ↓
JWT authentication
   ↓
user_id ↔ X-User-Id verification
   ↓
Backend authorization
   ↓
Service-role database access
   ↓
Every read and write filtered by that user_id
```

| Store | Scope |
|---|---|
| Postgres documents and snapshot | `user_id` |
| Files | folder `/<user_id>/` |
| Vectors | collection or `patient_key` = that user |
| Chat sessions | `(user_id, session_id)` in process memory |

The public session route issues an `anon_*` user and a signed token. Every other route requires the bearer token **and** a matching `X-User-Id`.

Supabase RLS is enabled with **no policies**. The backend uses the service-role key, which bypasses RLS. Isolation is therefore an **application** guarantee: scoped queries after auth. For production, add real RLS policies if the client key could ever reach these tables. It must not.

---

## What the workspace can do

| Action | Meaning |
|---|---|
| Start workspace | public; creates the anonymous user |
| Upload | files become the patient record |
| Dashboard | one snapshot: timeline + safety + labs |
| Ask / chat | grounded over that snapshot’s index |
| Reset workspace | new anonymous user in this browser |

Uploads can finish per file. One bad page does not discard the rest. The request only fails outright when nothing usable was kept.

Chat sessions live in memory for this process. Restarting the server drops conversations; the documents and snapshot remain.

---

## What this is not

- Not a login product.
- Not a multi-patient clinic chart.
- Not a claim that the database engine enforces tenancy by itself.
- Not a care-routing or map product on this branch.

---

## Engineering notes (not the main slide)

Routes live under `/api/v1/`. Health and anonymous session are public.

Uploads may return 202 and a job id; the UI polls per-file progress, then a batch finalization step (history → safety → search). A hard provider outage stops queued files from being sent into the same failure.

`CORS_ORIGINS=*` cannot send credentials. A concrete origin list can.

Missing schema → 503 with “run the SQL once.” Missing vector table → 502, not an empty-record lie.
