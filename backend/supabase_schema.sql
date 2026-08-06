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
-- service-role key (used by the backend) can reach these tables.
alter table public.documents enable row level security;
alter table public.patient_snapshots enable row level security;
