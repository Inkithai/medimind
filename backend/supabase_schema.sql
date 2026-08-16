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

-- One row per user: the last-built timeline + cross-check (+ lab trends,
-- and derived_reports holding {dosage_report, consult_triage}).
create table if not exists public.patient_snapshots (
    user_id            text        primary key,
    patient_timeline   jsonb       not null,
    cross_check_report jsonb       not null,
    lab_trends         jsonb,
    derived_reports    jsonb,
    updated_at         timestamptz not null default now()
);
-- Existing deployments: add the column if the table predates it.
alter table public.patient_snapshots add column if not exists derived_reports jsonb;

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

-- Durable conversation transcripts (optional; conversation.py falls back to
-- in-memory sessions when this table is missing). One row per
-- (user_id, session_id); `turns` is the full untrimmed transcript.
create table if not exists public.conversation_sessions (
    user_id    text        not null,
    session_id text        not null,
    turns      jsonb       not null default '[]'::jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (user_id, session_id)
);
grant select, insert, update, delete on table public.conversation_sessions to service_role;
alter table public.conversation_sessions enable row level security;

-- Append-only audit log of data-touching API actions (optional; audit.py
-- degrades to structured app-log lines when this table is missing).
create table if not exists public.audit_log (
    id         bigint generated always as identity primary key,
    user_id    text        not null,
    action     text        not null,
    detail     jsonb,
    created_at timestamptz not null default now()
);
create index if not exists audit_log_user_id_idx on public.audit_log (user_id, created_at);
grant select, insert on table public.audit_log to service_role;
grant usage, select on sequence public.audit_log_id_seq to service_role;
alter table public.audit_log enable row level security;
-- Immutable user correction events. The source extraction in documents.data
-- is never updated; the backend replays these rows to create the effective
-- record. original_value and previous_value make every edit auditable and
-- allow a later event to restore any earlier value.
create table if not exists public.extraction_corrections (
    id                  text        primary key,
    correction_batch_id text        not null,
    user_id             text        not null,
    document_id         text        not null,
    field_path          text        not null,
    original_value      jsonb,
    previous_value      jsonb,
    corrected_value     jsonb,
    reason              text        not null,
    created_at          timestamptz not null default now()
);
create index if not exists extraction_corrections_user_doc_idx
    on public.extraction_corrections (user_id, document_id, created_at);
grant select, insert on table public.extraction_corrections to service_role;
alter table public.extraction_corrections enable row level security;

-- Current conflict state. The original competing facts live in data.items;
-- resolving a conflict selects one authoritative source but never deletes the
-- alternatives. A composite key is required because deterministic conflict
-- IDs intentionally have the same fact-key shape in different workspaces.
create table if not exists public.record_conflicts (
    user_id                      text        not null,
    conflict_id                  text        not null,
    status                       text        not null default 'unresolved'
                                             check (status in ('unresolved', 'resolved', 'superseded')),
    authoritative_document_id    text,
    resolution_note              text,
    data                         jsonb       not null,
    detected_at                  timestamptz not null default now(),
    updated_at                   timestamptz not null default now(),
    resolved_at                  timestamptz,
    primary key (user_id, conflict_id)
);
create index if not exists record_conflicts_user_status_idx
    on public.record_conflicts (user_id, status, updated_at);
grant select, insert, update on table public.record_conflicts to service_role;
alter table public.record_conflicts enable row level security;

-- Append-only audit trail for resolve/reopen decisions.
create table if not exists public.conflict_resolution_events (
    id                          text        primary key,
    user_id                     text        not null,
    conflict_id                 text        not null,
    old_status                  text        not null,
    new_status                  text        not null,
    authoritative_document_id   text,
    note                        text,
    created_at                  timestamptz not null default now()
);
create index if not exists conflict_resolution_events_user_idx
    on public.conflict_resolution_events (user_id, conflict_id, created_at);
grant select, insert on table public.conflict_resolution_events to service_role;
alter table public.conflict_resolution_events enable row level security;
