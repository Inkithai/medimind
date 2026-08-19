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

-- One row per extracted document (structured JSON from medical_extractor).
-- Rows are append-only except for explicit authenticated document/workspace
-- deletion and full-file replacement during reprocessing.
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
grant select, insert, delete on table public.audit_log to service_role;
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
grant select, insert, delete on table public.extraction_corrections to service_role;
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
grant select, insert, update, delete on table public.record_conflicts to service_role;
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
grant select, insert, delete on table public.conflict_resolution_events to service_role;
alter table public.conflict_resolution_events enable row level security;

-- Append-only referral trail: one row per local-care provider search a user
-- ran from a clinical flag (finding -> specialty -> search -> ranked
-- providers with the referral reason and per-provider ranking breakdowns).
-- The JSON is historical record OF A SEARCH (see referral_trail.py), not a
-- live provider directory.
create table if not exists public.referral_searches (
    id          bigint generated always as identity primary key,
    user_id     text        not null,
    created_at  timestamptz not null default now(),
    search      jsonb       not null
);
create index if not exists referral_searches_user_idx
    on public.referral_searches (user_id, created_at desc);
grant select, insert, delete on table public.referral_searches to service_role;
grant usage, select on sequence public.referral_searches_id_seq to service_role;
alter table public.referral_searches enable row level security;

-- --------------------------------------------------------------------------
-- Rebuildable normalized clinical projection
-- --------------------------------------------------------------------------
-- Immutable document JSON remains the source of truth. These tables provide
-- independently queryable rows and stable identities for reconciliation.
create table if not exists public.clinical_medications (
    id text primary key, user_id text not null, document_id text,
    event_date date, data jsonb not null, updated_at timestamptz not null default now()
);
create table if not exists public.clinical_prescriptions (
    id text primary key, user_id text not null, document_id text,
    medication_id text not null references public.clinical_medications(id) on delete cascade,
    event_date date, data jsonb not null, updated_at timestamptz not null default now()
);
create table if not exists public.clinical_allergies (
    id text primary key, user_id text not null, document_id text,
    event_date date, data jsonb not null, updated_at timestamptz not null default now()
);
create table if not exists public.clinical_lab_results (
    id text primary key, user_id text not null, document_id text,
    event_date date, data jsonb not null, updated_at timestamptz not null default now()
);
create table if not exists public.clinical_events (
    id text primary key, user_id text not null, document_id text,
    event_date date, data jsonb not null, updated_at timestamptz not null default now()
);
create table if not exists public.safety_findings (
    id text primary key, issue_key text not null unique, user_id text not null,
    document_id text, event_date date, finding_type text not null,
    status text not null check (status in ('active', 'resolved')),
    data jsonb not null, updated_at timestamptz not null default now()
);

create index if not exists clinical_medications_user_idx on public.clinical_medications (user_id);
create index if not exists clinical_prescriptions_user_date_idx on public.clinical_prescriptions (user_id, event_date desc);
create index if not exists clinical_allergies_user_idx on public.clinical_allergies (user_id);
create index if not exists clinical_lab_results_user_date_idx on public.clinical_lab_results (user_id, event_date desc);
create index if not exists clinical_events_user_date_idx on public.clinical_events (user_id, event_date desc);
create index if not exists safety_findings_user_status_idx on public.safety_findings (user_id, status, updated_at desc);

grant select, insert, update, delete on table
    public.clinical_medications, public.clinical_prescriptions,
    public.clinical_allergies, public.clinical_lab_results,
    public.clinical_events, public.safety_findings to service_role;
alter table public.clinical_medications enable row level security;
alter table public.clinical_prescriptions enable row level security;
alter table public.clinical_allergies enable row level security;
alter table public.clinical_lab_results enable row level security;
alter table public.clinical_events enable row level security;
alter table public.safety_findings enable row level security;

-- Patient-entered profile data is an additional identity signal. It never
-- silently overrides identity extracted from source documents.
create table if not exists public.patient_profiles (
    user_id text primary key,
    legal_name text,
    preferred_name text,
    date_of_birth date,
    phone text,
    emergency_contact text,
    preferred_language text,
    updated_at timestamptz not null default now()
);
grant select, insert, update, delete on table public.patient_profiles to service_role;
alter table public.patient_profiles enable row level security;

-- User-chosen workspace display name. Anonymous by default; names are
-- globally unique (case-insensitive) so a name is a stable, human-recognisable
-- label. name_key is the lowercased comparison key the unique index enforces.
create table if not exists public.workspace_names (
    user_id    text        primary key,
    name       text        not null,
    name_key   text        not null,
    updated_at timestamptz not null default now()
);
create unique index if not exists workspace_names_name_key_idx
    on public.workspace_names (name_key);
grant select, insert, update, delete on table public.workspace_names to service_role;
alter table public.workspace_names enable row level security;

-- Reviewer feedback on individual safety findings (clinician feedback loop +
-- alert-fatigue / override capture). In-memory-first; this table is a
-- best-effort mirror and is optional — the API records feedback in memory even
-- when the table is absent.
create table if not exists public.finding_feedback (
    id bigint generated always as identity primary key,
    user_id text not null,
    finding_key text not null,
    finding_kind text,
    rule text,
    verdict text not null check (verdict in ('confirmed','false_positive','needs_change','overridden')),
    reason text,
    note text,
    reviewer text,
    created_at timestamptz not null default now()
);
create index if not exists ix_finding_feedback_user on public.finding_feedback (user_id);
create index if not exists ix_finding_feedback_key on public.finding_feedback (user_id, finding_key);
grant select, insert, update, delete on table public.finding_feedback to service_role;
alter table public.finding_feedback enable row level security;

-- Per-run snapshots of which clinical findings existed, for the finding-history
-- audit trail (new / resolved / persisted across re-analyses). In-memory-first;
-- best-effort mirror.
create table if not exists public.finding_history (
    id bigint generated always as identity primary key,
    user_id text not null,
    run_id text not null,
    captured_at timestamptz not null,
    finding_key text not null,
    finding_kind text,
    list text,
    severity text,
    rule text
);
create index if not exists ix_finding_history_user on public.finding_history (user_id);
create index if not exists ix_finding_history_run on public.finding_history (user_id, run_id);
grant select, insert, update, delete on table public.finding_history to service_role;
alter table public.finding_history enable row level security;
