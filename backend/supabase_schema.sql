-- ============================================================================
-- Supabase schema for the Medical Records Q&A API
-- ============================================================================
-- Run this ONCE in the Supabase SQL editor (Dashboard -> SQL Editor ->
-- New query -> paste -> Run). Creates the two tables db.py uses, with the
-- indexes and row-level security the app expects.
--
-- Security model: the backend talks to Supabase with the service-role key
-- (which bypasses RLS). RLS is ENABLED below with no policies, so the
-- browser-facing anon key can neither read nor write these tables — only
-- this backend can. Never point a frontend at these tables directly.
-- ============================================================================

-- One row per extracted document (structured JSON from medical_extractor),
-- append-only per user.
create table if not exists public.documents (
    id          bigint generated always as identity primary key,
    user_id     text        not null,
    uploaded_at timestamptz not null default now(),
    data        jsonb       not null
);

-- user_id is the access-control boundary and the merge query always
-- filters + orders on (user_id, uploaded_at).
create index if not exists documents_user_id_idx
    on public.documents (user_id, uploaded_at);

-- One row per user: the last-built timeline + cross-check (+ lab trends).
create table if not exists public.patient_snapshots (
    user_id            text        primary key,
    patient_timeline   jsonb       not null,
    cross_check_report jsonb       not null,
    lab_trends         jsonb,
    updated_at         timestamptz not null default now()
);

-- Deny all access through the anon/authenticated keys; only the
-- service-role key (used by the backend) can reach these tables. Explicit
-- grants are needed because tables created in the SQL editor are owned by
-- postgres and service_role may not otherwise have table privileges.
grant select, insert, update, delete on table public.documents to service_role;
grant select, insert, update, delete on table public.patient_snapshots to service_role;
grant usage, select on sequence public.documents_id_seq to service_role;

alter table public.documents enable row level security;
alter table public.patient_snapshots enable row level security;

-- Vector store chunks (when VECTOR_STORE=supabase — no Railway volume needed).
-- Stores per-user chunks + embeddings as jsonb; brute-force cosine in Python
-- is fine for 10-30 chunks/user. If you enable pgvector, you can add a
-- vector column and replace the Python loop with an rpc.
create table if not exists public.chunks (
    id          text        primary key,
    patient_key text        not null,
    text        text        not null,
    embedding   jsonb       not null,
    metadata    jsonb       not null,
    created_at  timestamptz not null default now()
);
create index if not exists chunks_patient_key_idx on public.chunks (patient_key);
grant select, insert, update, delete on table public.chunks to service_role;
alter table public.chunks enable row level security;

-- Background jobs for async uploads (optional, in-memory fallback if table missing).
-- Lets POST /api/v1/documents return 202 immediately and poll GET /api/v1/jobs/{id}.
create table if not exists public.jobs (
    job_id     text        primary key,
    user_id    text        not null,
    status     text        not null, -- pending | processing | completed | failed
    progress   jsonb,
    result     jsonb,
    error      text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);
create index if not exists jobs_user_id_idx on public.jobs (user_id, created_at);
grant select, insert, update, delete on table public.jobs to service_role;
alter table public.jobs enable row level security;
