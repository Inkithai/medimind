# Feature-Gap Analysis: Repository A & Repository B vs. MediMind

> Scope: backend, AI/ML logic, medical intelligence, safety, RAG/retrieval, document
> processing, lab analysis, prescription checking, patient/identity handling,
> triage/referral, and other functional capabilities. UI/design excluded.
>
> Method: the actual source code of all three codebases was inspected (modules, API
> routes, services, models, migrations, requirements), not just the READMEs.
> Fully-implemented features are separated from partial/experimental ones.

---

## 0. Headline findings

- **Repository A** is the *same code lineage* as MediMind. Its module set is a strict
  subset of MediMind's (`api`, `medical_extractor`, `retrieval`, `lab_trends`,
  `consult_triage`, `risk_timeline`, `evidence_grading`, `identity_guard`,
  `language_guard`, `eml_kg`/`poisoning_kg`/`guidance_kg`, `graph_db`, etc.). I diffed
  the three modules where A is *larger* than MediMind (`consult_triage`, `language_guard`,
  `identity_guard`) and confirmed they contain **functionally equivalent** logic, just
  reorganized — not new capability. A also uses an older stack (MongoDB persistence, no
  OCR, no vector store, no async jobs, no tests).
  ➡️ **Repository A implements nothing that MediMind lacks.** It is an earlier sibling.
  *(Note: the URL supplied for A as written returns 404; the canonical source was located
  and inspected.)*

- **Repository B** is a genuinely different architecture (FastAPI + **SQLAlchemy ORM +
  Alembic** + Supabase Auth + Next.js). Its *medical-intelligence* layer is **narrower**
  than MediMind's, but it introduces a different **identity/account** model and a different
  **persistence** architecture that MediMind does not have. Those are the only real gaps.

- Several headline features **advertised in Repository B's README are not implemented in
  code**: multi-document Q&A / "Ask AI", RAG, embeddings, `pgvector`, and Ollama. The
  frontend `askAi()` call is a stub that returns `unconfigured`, and there is no backend
  Q&A/embedding/vector code or dependency. These are listed in §3 as a warning, **not** as
  gaps to copy.

---

## 1. Features the comparison repos have that MediMind does NOT

All of the items below come from **Repository B**. (Repository A contributes none — see §0.)

### ✅ Fully implemented

#### 1. Managed account authentication (credential-based identity)
- **Which repo:** Repository B
- **Implementation:** Supabase Auth (GoTrue) is the identity provider. `core/security.py`
  validates access tokens through a **three-strategy pipeline**: (1) asymmetric **JWKS**
  verification (ES256/RS256) against Supabase's `.well-known/jwks.json`, (2) local
  symmetric **HS256** verification when `SUPABASE_JWT_SECRET` is set, (3) remote
  **GoTrue** verification as a fallback. Endpoints `POST /api/auth/register` (idempotently
  provisions the application `User` + default `Patient`) and `GET /api/auth/me`. The
  frontend has real sign-up / sign-in screens backed by Supabase Auth.
- **How it differs from MediMind:** MediMind is **anonymous-only by design** —
  `auth.issue_anonymous_token()` mints a self-signed JWT for a fresh `anon_*` workspace;
  there is no signup, password, email, or external identity provider. Repository B instead
  has persistent, recoverable, credential-based user identities.

#### 2. Normalized relational persistence + schema migrations (ORM layer)
- **Which repo:** Repository B
- **Implementation:** A full **SQLAlchemy 2.x ORM** with **Alembic** versioned migrations.
  Every clinical concept is its own indexed, queryable table: `users`, `patients`,
  `documents`, `medications`, `prescriptions`, `allergies`, `lab_results`,
  `medical_events`, `findings`, `questions`, `ai_analyses`, `doctor_searches`,
  `doctor_recommendations` — with foreign keys, `ondelete=CASCADE`, and dedicated indexes
  (e.g. `ix_findings_risk_level`, `ix_lab_results_test_name`, `ix_medications_normalized_name`).
- **How it differs from MediMind:** MediMind stores uploaded documents as **JSON blobs in
  Supabase** (`documents` + a `patient_snapshots` upsert) and **derives** timelines,
  medications, labs, allergies, and safety findings at request time. It has no ORM, no
  relational per-entity tables, and no migration framework (only a one-shot
  `supabase_schema.sql`). B's normalized model makes individual findings/results
  first-class rows you can index, join, and migrate.

#### 3. First-class persistence of safety findings & AI analyses
- **Which repo:** Repository B
- **Implementation:** Each medication-safety result is written as a `findings` row
  (`finding_type`, `risk_level`, severity, linked `medication_id`/`source_document_id`,
  indexed) and each AI extraction/result is written as an `ai_analyses` row — exposed via
  `GET /api/records/findings` and `GET /api/records/analyses`.
- **How it differs from MediMind:** MediMind recomputes the cross-check/safety report
  dynamically from the stored JSON timeline on each request (it intentionally does not
  persist transient analysis outputs as rows). B keeps a queryable, append-style history
  of detected findings and AI outputs.

#### 4. Persisted provider-search history with reproducible re-ranking
- **Which repo:** Repository B
- **Implementation:** `doctor_searches` + `doctor_recommendations` tables persist every
  provider search (location, radius, specialty, availability preference, linked finding)
  together with its ranked results. Endpoints `GET /api/doctor-search/history` and
  `GET /api/doctor-search/searches/{id}`; the latter **re-computes scores from stored
  fields** so a saved search reproduces its original ranking.
- **How it differs from MediMind:** MediMind's Find-Care (`care_finder` / `care/`) is a
  **stateless live search** — it returns ranked facilities on demand but never stores a
  search or its results. B keeps a per-patient provider-search history you can revisit.

### 🟡 Partial / experimental

#### 5. User → multi-Patient ownership model
- **Which repo:** Repository B
- **Implementation:** The ORM models a **one-to-many** `User → Patient` relationship
  (`patients = relationship("Patient", back_populates="user", cascade="all,
  delete-orphan")`). The schema therefore supports one account managing several patient
  records.
- **Why partial:** the `/auth/register` flow currently provisions only a **single default
  Patient** per user, and no endpoint actually creates or switches between multiple
  patients. The capability exists in the data model but is **not exercised end-to-end**.
- **How it differs from MediMind:** MediMind enforces a strict **one anonymous workspace =
  one patient** boundary; there is no concept of an owning account holding multiple
  patient profiles.

---

## 2. What was checked and found to be a *non-gap* (do not chase these)

To stay evidence-based, these were verified as **already present in MediMind** (often
richer), so they are **not** missing:

| Capability | Repository A | Repository B | MediMind |
|---|---|---|---|
| Consult/referral triage (pharmacist vs doctor, urgency, specialty) | ✅ | ❌ | ✅ (also adds extraction-quality referrals) |
| Risk timeline + concurrent-exposure windows | ✅ | ❌ | ✅ |
| Evidence grading (deterministic vs model-knowledge capping) | ✅ | ❌ | ✅ |
| Cross-patient identity guard / language-normalization guard | ✅ | ❌ | ✅ |
| Lab trend analysis (direction, crossings, recovery) | ✅ | ✅ (basic) | ✅ (richest — unit-clash, thousands parsing) |
| Deterministic drug interactions / dosage / allergy / duplicates | ⚠️ via cross-check only | ✅ | ✅ (dedicated rule modules) |
| WHO reference knowledge graphs (EML, antidotes, guidance) via Neo4j | ✅ | ❌ | ✅ |
| Care/provider navigation (facility search + ranking + map) | ❌ | ✅ (OSM-only) | ✅ (Google + Geoapify + OSM) |
| Vision+text extraction with provider abstraction | ✅ | ✅ (Gemini+Mock) | ✅ (Groq/Gemini/generic) |
| OCR (Tesseract) pre-pass | ❌ | ✅ | ✅ |
| Async upload jobs + per-file progress | ❌ | ⚠️ sync XHR upload | ✅ |

---

## 3. ⚠️ Warning — features Repository B *advertises* but has NOT implemented

These appear in B's README/stack list but are **absent from the code** (no service, no
endpoint, no dependency). They should not be treated as features MediMind is missing —
MediMind already has the real versions.

- **"Multi-document medical Q&A / Ask AI"** — no `/qa`, `/ask`, `/questions`, or
  `/sessions` route exists; the only AI call in the backend is document **extraction**.
  The frontend `askAi()` helper is literally `unconfigured("askAi")`. **MediMind has
  real grounded Q&A + conversational sessions.**
- **"RAG-based evidence retrieval"** — no retrieval/RAG code at all.
- **"Embeddings" / "pgvector"** — no embedding library in requirements, no `pgvector`
  usage, no vector column in any migration. **MediMind has a real vector store
  (Chroma or Supabase `chunks`).**
- **"Optional Ollama"** — appears only in a code comment; the provider factory supports
  `gemini` and `mock` only.

Repository B also has **none** of: knowledge graphs, identity/language guards, consult
triage, risk timeline, evidence grading, record integrity / change detection, follow-up,
appointment prep, document de-duplication, document filtering, export, or audit — all of
which MediMind implements.

---

## 4. Score table (0–10, based on actual implemented functionality)

| Factor | Repo A | Repo B | MediMind | Notes |
|---|:--:|:--:|:--:|---|
| Document processing & extraction (PDF / vision / OCR) | 6 | 8 | 9 | A has no OCR; B & MediMind do; MediMind adds async jobs |
| Structured patient timeline / record projection | 7 | 7 | 9 | B uses relational tables; MediMind derives richest timeline |
| Medication safety (interactions / dosage / allergy / duplicates) | 6 | 8 | 9 | A is LLM-cross-check only; B has deterministic rule engine; MediMind has dedicated rule modules + EML age checks |
| Lab trend / lab-value analysis | 8 | 6 | 9 | MediMind richest (crossings, recovery, unit-clash, thousands) |
| RAG / grounded multi-document Q&A | 6 | 0 | 9 | B has no Q&A at all; A has deterministic retrieval; MediMind has vector RAG |
| Reference knowledge graphs (WHO EML / antidotes / guidance) | 8 | 0 | 9 | A & MediMind share this lineage; B has none |
| Clinical triage / referral routing | 8 | 0 | 9 | B has none |
| Cross-document identity & language safety | 8 | 0 | 8 | B has none |
| Risk timeline / evidence grading / provenance | 8 | 0 | 9 | B has none |
| Longitudinal change detection / record integrity | 0 | 0 | 9 | Only MediMind |
| Care / provider navigation (search + ranking + map) | 0 | 7 | 9 | B is OSM-only; MediMind adds Google/Geoapify + recommendations |
| **Account-based identity management (Supabase Auth)** | 0 | **9** | 0† | **B only** |
| **Relational persistence + schema migrations (ORM/Alembic)** | 0 | **9** | 0† | **B only** |
| **Provider-search history persistence** | 0 | **8** | 0 | **B only** |
| Data export / audit trail | 0 | 0 | 8 | Only MediMind |
| Engineering rigor / automated test coverage | 3 | 8 | 9 | A ships no tests; B ~30 test files; MediMind ~70 |
| **Approximate total** | **76** | **79** | **122** | |

† MediMind's 0 here is a **deliberate design choice** (anonymous workspaces, JSON+vector
storage), not a defect — but it is an architectural capability B has that MediMind does
not.

---

## 5. Bottom line

- **If the goal is "medical intelligence" (safety, RAG/Q&A, labs, triage, KGs, identity
  safety, record integrity):** MediMind is the most complete of the three. Neither
  comparison repo has a capability MediMind lacks in this domain; B is materially behind,
  and A is MediMind's own earlier subset.
- **If the goal is "product/account/persistence architecture":** Repository B is the only
  one that brings things MediMind does not have today —
  1. managed **credential-based accounts** (Supabase Auth),
  2. a **normalized relational data model with Alembic migrations**,
  3. **persisted provider-search history**, and
  4. (partial) a **multi-patient-per-account** ownership model.
  
  These are the only items worth evaluating for adoption, and they are *architectural*
  (identity + storage), not clinical-intelligence, features.
