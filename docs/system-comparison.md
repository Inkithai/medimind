# Backend & Architecture Comparison — 3 Systems

**Scope:** Backend, business logic, architecture, workflows, modules, features only. Frontend/UI/UX explicitly excluded. Analysis is based **strictly on the three attached Mermaid diagrams** — nothing is inferred from the repos themselves or from what "such a system would normally have."

| ID | System | Source diagram |
|----|--------|----------------|
| **A** | **System A** | Diagram 1 (FastAPI + Chroma + OpenAI, local JSON state) |
| **B** | **System B** | Diagram 2 (FastAPI + Supabase, auth + medication safety) |
| **C** | **System C (yours)** | Diagram 3 (FastAPI + Supabase, jobs + Q&A + lab trends) |

Legend: ✅ = clearly present in diagram · ❌ = not represented · ⚠️ = **Unclear from diagram**

---

## 1. Feature comparison table

### 1.1 API layer & request handling

| Feature / Capability | System A | System B | System C | Notes |
|---|---|---|---|---|
| HTTP REST API (FastAPI) | ✅ single `api.py`, `/api/v1` | ✅ `main.py` entry | ✅ `api.py` | Shared by all three. |
| Modular API routers (auth / documents / records / safety split) | ❌ monolithic orchestration file | ✅ 4 dedicated routers | ⚠️ single `api.py` node; internal modularity not shown | B is the only one that *demonstrates* router-level decomposition. |
| Authentication / identity | ❌ none shown — client hits API directly | ✅ dedicated Authentication API router | ✅ auth middleware (`auth.py`), JWT + user-ID scoping | A has **no auth at all** in the diagram. B and C differ: B exposes an auth *API*; C shows request-level *identity scoping middleware*. Whether B scopes all downstream data per user is ⚠️ unclear. |
| Multi-tenancy / per-user data scoping | ⚠️ "store vectors by patient" implies patient partitioning, but no identity enforcement | ⚠️ auth exists; scoping of models/queries not shown | ✅ "identity scoping" + "patient-scoped retrieval" explicitly labeled | C is the only diagram that explicitly ties identity to retrieval scope. |

### 1.2 Ingestion & processing workflow

| Feature / Capability | System A | System B | System C | Notes |
|---|---|---|---|---|
| Document upload (PDF) | ✅ | ✅ | ✅ | Shared. |
| Image upload / OCR | ✅ "PDF/image upload" (parse path shown); OCR engine not named | ✅ explicit "PDF and OCR extraction" | ⚠️ extraction is "LLM pipeline"; image/OCR support not represented | B is most explicit about OCR; A accepts images; C's diagram never mentions images or OCR. |
| Asynchronous job orchestration (worker pool, background processing) | ❌ synchronous flow; reindex is only "attempt … after upload" (best-effort) | ❌ ingestion orchestrator shown, but no jobs/queue/workers | ✅ `jobs.py` worker pool, "create/process document jobs", job polling | **Unique to C.** |
| Job progress tracking / pollable job status | ❌ | ❌ | ✅ ("poll jobs" edge into the API) | Unique to C. |
| Medical relevance filter (reject non-medical documents pre-persistence) | ❌ | ❌ | ✅ `document_filter.py` gate between extraction and record assembly | **Unique to C.** |
| LLM-based structured clinical extraction | ✅ clinical extractor | ✅ medical extraction / clinical normalization via LLM | ✅ clinical extraction LLM pipeline | Shared by all three. |
| Merge with prior documents / longitudinal consolidation | ✅ "merge prior documents" → "consolidated timeline" | ⚠️ "clinical normalization" persists data; cross-document merging not shown | ✅ patient record assembly + snapshot | A and C clearly build a consolidated patient record; B may, but the diagram shows only per-document persistence. |
| Patient record snapshots (versioned assembled state) | ❌ (persists documents/reports, no snapshot concept) | ❌ | ✅ "records & snapshots" persisted | Unique to C as drawn. |
| Storage of original source files (object storage) | ❌ (only extracted JSON persists) | ✅ Supabase Storage | ✅ Cloudinary | A never retains originals per the diagram. |

### 1.3 Safety & clinical analytics

| Feature / Capability | System A | System B | System C | Notes |
|---|---|---|---|---|
| Safety cross-check over consolidated timeline (clinical rules) | ✅ dedicated safety module; persists a safety report | ❌ | ❌ | Unique to A. Rule-based check on the *whole* timeline. |
| Medication safety evaluation service (dedicated API + orchestrator) | ❌ (A's safety is generic rules, not medication-specific per the diagram) | ✅ Medication safety API + safety service; "reads medications and writes analyses" | ❌ | Unique to B. A and B's safety features are **similarly named but not equivalent**: A = timeline-wide rule cross-check; B = medication-focused evaluation with persisted analyses. |
| External drug-interaction / clinical knowledge base | ❌ | ❌ (safety service only reads its own models) | ❌ | **None of the three.** All safety logic is internal. |
| Deterministic lab trend analysis (non-LLM analytics, derived insights persisted) | ❌ | ❌ | ✅ `lab_trends.py` | **Unique to C.** Only deterministic (non-LLM) clinical analytics in any diagram. |
| Healthcare provider discovery (external geodata APIs) | ❌ | ✅ Records API → provider data sources | ❌ | Unique to B. Only external real-world data integration in any system. |

### 1.4 Retrieval, Q&A & conversation

| Feature / Capability | System A | System B | System C | Notes |
|---|---|---|---|---|
| Embedding/indexing pipeline | ✅ typed chunk builder → embeddings → Chroma | ⚠️ pgvector exists in the DB, but **no embedding or indexing flow is drawn** | ✅ retrieval indexing pipeline → vector store | B has vector *infrastructure* with no visible pipeline feeding it. |
| Grounded Q&A / RAG service | ✅ `/qa` RAG service | ❌ no Q&A node or edge anywhere | ✅ grounded Q&A conversation service | **B has no question-answering capability in its diagram.** |
| Multi-turn conversation service | ✅ session endpoints, transcripts, "standalone follow-up query" rewriting | ❌ | ✅ "Q&A and conversation endpoints" | A shows the most explicit conversation mechanics (transcript + follow-up rewriting). C shows a conversation service but transcript storage / follow-up handling is ⚠️ unclear. |
| Conversation state durability | ❌ **process memory only** (lost on restart) | — n/a | ⚠️ not shown where/if transcripts persist | A explicitly volatile; C unclear. |
| Answer citations | ⚠️ "grounded" answers; citations not stated | — n/a | ⚠️ "Cited Q&A" appears only on a UI node; backend citation generation not drawn | Unclear for both A and C. |
| Index rebuild from durable records (recoverable index) | ⚠️ only "attempt reindex after upload" (dotted/best-effort); no rebuild-from-store path | — n/a | ✅ "rebuild from persisted records" edge | C's index is explicitly reconstructable from the database; A's is not shown to be. |
| Typed/structured chunking strategy | ✅ "typed chunk builder" explicitly | ❌ | ⚠️ "index patient chunks" — chunk typing not specified | Likely minor implementation difference, but only A names it. |

### 1.5 Persistence & infrastructure

| Feature / Capability | System A | System B | System C | Notes |
|---|---|---|---|---|
| Durable relational database | ❌ local JSON files | ✅ Supabase PostgreSQL (+pgvector), SQLAlchemy ORM models | ✅ Supabase Postgres | A's durability = flat files on local disk. |
| Explicit domain model layer (ORM entities) | ❌ | ✅ SQLAlchemy clinical domain entities | ⚠️ `db.py` shown; model layer not drawn as a separate module | B is the only one that surfaces a formal domain-entity layer. |
| Vector store | ✅ Chroma (persistent, per-patient collections) | ⚠️ pgvector present but unused in drawn flows | ✅ **pluggable** vector store abstraction | C is the only one with a swappable vector-store interface. |
| LLM provider abstraction / multi-provider | ❌ hard edge to OpenAI only | ✅ AI provider factory (LLM abstraction) | ✅ Groq / Gemini / OpenAI-compatible | A is single-vendor locked. |
| Embedding provider flexibility (incl. local/offline) | ❌ OpenAI only | ⚠️ not shown | ✅ OpenAI **or local ONNX** | Unique to C — only system that can embed without an external API. |
| Ops / admin tooling (index inspection CLI) | ✅ read-only Chroma inspector CLI | ❌ | ❌ | Unique to A. |

### 1.6 Capabilities none of the three systems has (from the diagrams)

| Missing capability | Why it matters |
|---|---|
| External clinical knowledge integration for safety (drug-interaction DB, RxNorm-like sources) | All safety logic is self-contained; no system validates against authoritative references. |
| Audit logging / access trails | None drawn — significant for medical data. |
| Interoperability / export (FHIR, HL7, or any EHR integration) | No system exchanges data with clinical systems. |
| Notifications / alerting (e.g., on dangerous findings) | Safety outputs are only persisted, never pushed anywhere. |
| Human-in-the-loop review / correction of LLM extractions | All three trust extraction output straight into persistence. |
| Retry / dead-letter handling for failed processing | Not shown even in C's job system (⚠️ cannot be ruled out — unclear). |
| Rate limiting, caching, evaluation/monitoring of LLM output quality | Absent from all three diagrams (⚠️ may exist but undrawn). |
| Multi-user sharing / roles (e.g., caregiver or clinician access to a patient record) | All three are single-actor per record as drawn. |

> Items marked ⚠️ in this last table are "cannot be determined from diagrams" rather than confirmed absent.

---

## 2. Uniqueness analysis

### What System A has that the others don't
1. **Timeline-wide safety cross-check with clinical rules.** The only system that runs a safety pass over the *consolidated* patient timeline (not just medications) and persists a safety report. Genuinely unique capability — C has nothing comparable, and B's medication safety is narrower in scope.
2. **Explicit multi-turn conversation mechanics** — session transcripts plus rewriting follow-ups into standalone queries before retrieval. C has a conversation service, but only A demonstrates *how* follow-ups are handled. Partially an implementation-detail difference, but the query-rewriting step is a real RAG-quality capability.
3. **Index inspection CLI** (read-only ops tooling for the vector store). Minor but genuinely unique — neither B nor C shows any operational tooling.
4. **Typed chunk builder.** Probably a minor implementation difference vs. C's chunking, not a distinct capability.

Caveats that offset A's uniqueness: local JSON state, in-process session memory, no auth, no object storage of originals, single-vendor OpenAI lock-in — architecturally the least production-ready of the three.

### What System B has that the others don't
1. **Dedicated medication safety module** (API router + orchestrator that reads medications and writes persisted analyses). The clearest productized safety feature of the three. Matters because it's a user-facing clinical value proposition, not just a pipeline step.
2. **Provider discovery via external geodata APIs.** The only outward-facing real-world data integration in any diagram. Real differentiator: extends the product from "understand my records" to "act on them (find care)."
3. **Formal domain-entity layer (SQLAlchemy models) + modular routers.** More architectural discipline than capability, but it signals a maintainable, schema-driven backend.
4. **Explicit OCR extraction.** A accepts images too, so this is a shared-ish capability; but B names OCR explicitly while C shows no image path at all.

Caveats: B's diagram contains **no Q&A, no RAG, no conversation, no embedding pipeline** — pgvector sits in the database with nothing drawn feeding or querying it. As drawn, B ingests, normalizes, evaluates medication safety, and finds providers — it cannot answer questions about the record.

### What System C (yours) has that the others don't
1. **Asynchronous job orchestration with pollable progress** (worker pool, document jobs). The only system built for non-blocking processing of slow LLM pipelines. Directly affects scalability and reliability — genuinely unique here.
2. **Medical relevance filter.** The only quality gate rejecting non-medical documents before they pollute the patient record and the index. Improves data integrity and downstream answer quality.
3. **Deterministic lab trend analysis** with derived insights persisted to the DB. The only non-LLM clinical analytics anywhere — cheap, reproducible, auditable insights. Real business value and genuinely unique.
4. **Patient record snapshots.** Versioned assembled state — the others persist only documents/reports.
5. **Index rebuild from persisted records.** The vector index is explicitly disposable/recoverable; A only has a best-effort "attempt reindex after upload."
6. **Pluggable vector store + multi-LLM providers (Groq/Gemini/OpenAI-compatible) + local ONNX embedding option.** The strongest vendor-independence of the three, including an offline embedding path no other system has.

### What is shared
- **Upload → LLM extraction → persistence pipeline**: all three; broadly equivalent in purpose, differing in robustness (C async + filtered; B orchestrated + OCR-explicit; A synchronous).
- **Grounded Q&A/RAG + conversation**: **A and C only.** Roughly equivalent capability; A is more explicit about conversation mechanics but volatile; C is durable and patient-scoped but less detailed in the diagram.
- **Auth**: **B and C only** — different mechanisms (auth API vs. JWT scoping middleware), similar intent.
- **Managed Postgres (Supabase) + object storage of originals**: **B and C only.** Near-equivalent; storage vendor differs (Supabase Storage vs. Cloudinary) — superficial difference.
- **LLM provider abstraction**: **B and C only** (factory vs. multi-provider config) — equivalent in intent.
- **Safety analysis exists in A and B but is *not* the same feature** (timeline rule cross-check vs. medication evaluation). C has neither.

### What none of them has
See table 1.6. Confirmed absent from all diagrams: external clinical knowledge bases for safety, audit trails, interoperability/export, notifications, human review of extractions, cross-user sharing. Undeterminable (not drawn, may exist): retries/error handling, citations in answers (A, C), monitoring, rate limiting, encryption specifics.

---

## 3. Most important differences (ranked)

| # | Difference | Who has it | Why it matters | Real advantage? |
|---|---|---|---|---|
| 1 | **Grounded Q&A / RAG + conversation** | A ✅ C ✅ **B ❌** | This is the core "intelligence" of a medical-records AI product. B, as drawn, cannot answer a single question about a patient's records despite having pgvector provisioned. | **Major.** Decisive gap for B. |
| 2 | **Async job orchestration + progress polling** | **C only** | LLM extraction is slow; synchronous pipelines (A, B) block requests, can't scale, and fail opaquely. C's worker pool is the only architecture that handles this. | **Major** technical advantage for C. |
| 3 | **Safety analysis (any kind)** | A ✅ (timeline rules) B ✅ (medication) **C ❌** | Safety checking is high clinical and product value. C is the only system with *no* safety module — its single biggest functional gap. | **Major** gap for C. |
| 4 | **Authentication / identity scoping** | B ✅ C ✅ **A ❌** | Without identity, A cannot be multi-user and has no access control over medical data. | **Major** gap for A; table stakes, not a differentiator between B and C. |
| 5 | **Durable, managed persistence** (Postgres + object storage) vs. local JSON + process memory | B ✅ C ✅ **A ❌** | A loses conversations on restart, keeps records in flat files, and discards originals. Production-readiness divide. | **Major** for A vs. B/C; equivalent between B and C. |
| 6 | **Deterministic lab trend analytics** | **C only** | Persisted, reproducible clinical insights without LLM cost or hallucination risk. | **Moderate–major** product differentiator for C. |
| 7 | **Provider discovery (external geodata)** | **B only** | Only real-world actionability feature in any system. | **Moderate** product differentiator for B. |
| 8 | **Medical relevance filter** | **C only** | Data-quality gate protecting the record and index from junk input; improves RAG accuracy. | **Moderate** technical advantage for C. |
| 9 | **Vendor independence** (multi-LLM, pluggable vectors, local ONNX embeddings) | C strongest; B partial (factory); A none | Cost control, resilience, offline/privacy option. A is fully OpenAI-locked. | **Moderate**, compounding over time. |
| 10 | **Index recoverability** ("rebuild from persisted records") vs. best-effort reindex; plus A's inspection CLI | C ✅ rebuild; A ✅ CLI | Operational resilience: C can regenerate its index; A can only inspect its (non-rebuildable-as-drawn) index. | **Minor–moderate.** |

---

## 4. Final assessment

**Most feature-complete backend:** **System C** — it is the only system with the full chain: auth → async ingestion → relevance filtering → record assembly + snapshots → deterministic analytics → durable storage → recoverable retrieval → grounded conversational Q&A. B has the most disciplined structure (routers, ORM, auth) but is missing the entire intelligence layer (no Q&A/RAG drawn). A has the intelligence layer but the weakest foundations (no auth, local files, volatile sessions, single vendor).

**Most genuinely unique capabilities:** **C** (jobs/progress, relevance filter, lab trends, snapshots, rebuildable index, local embeddings — six items), then B (medication safety, provider discovery, ORM layer — three), then A (timeline safety cross-check, conversation mechanics, ops CLI — two to three, on a fragile base).

**Where A clearly outperforms C:** the timeline-wide **safety cross-check** and explicit **follow-up query rewriting** in conversation. Nothing else — everywhere else A trails on architecture.

**Where B clearly outperforms C:** **medication safety** as a dedicated persisted-analysis module, **provider discovery**, explicit **OCR**, and (structurally) the visible domain-model/router decomposition.

**Where C clearly outperforms both:** processing architecture (async jobs), input quality control (relevance filter), non-LLM analytics (lab trends), state management (snapshots + rebuildable index), and vendor independence (multi-LLM + local embeddings).

**Important vs. superficial differences:**
- *Important:* presence/absence of Q&A (B's gap), safety analysis (C's gap), auth (A's gap), async processing (only C), durable persistence (A's gap), lab trends, provider discovery.
- *Superficial:* Supabase Storage vs. Cloudinary; Chroma vs. pgvector vs. pluggable store (vendor choice, though C's pluggability has some value); "typed" chunking vs. generic chunking; monolithic `api.py` vs. routers (code organization, not capability); auth-API vs. auth-middleware.

### Recommended additions for System C, by priority — implementation status

> Status audit performed against the actual System C codebase (`backend/`), then the remaining
> gaps were implemented. Two categories below:
> **✅ DONE (implemented now)** = built in this pass, with offline tests.
> **✅ DONE (already existed)** = present in the codebase all along; the architecture diagram
> simply did not show it, so the comparison had flagged it as a gap.

**Highest value**
1. ✅ **DONE — Safety analysis module.**
   - *Already existed:* a full LLM safety cross-check (`cross_check_prescriptions` in `medical_extractor.py`) covering drug interactions, duplicates, dosage conflicts, and allergy conflicts over the whole timeline — i.e., System C already combined A's timeline-wide check with B's medication focus, persisted per-user in the `patient_snapshots` table and served at `GET /api/v1/cross-check`. A deterministic exact-duplicate detector already ran alongside it.
   - *Implemented now:* the piece **no system had** — a deterministic, curated **drug-interaction knowledge base** (`drug_interactions.py`): ~19 textbook-level interaction rules (anticoagulant+NSAID, nitrate+PDE5, SSRI+tramadol, macrolide+statin, ACE-inhibitor+K-sparing diuretic, …) matched on normalized ingredients in code and merged into the cross-check report with `source: "curated_knowledge_base"`, so catching well-established interactions never depends on the LLM noticing on a given run. Tests: `tests/test_drug_interactions.py` (8 passing).
2. ✅ **DONE (already existed) — OCR / image ingestion.** `SUPPORTED_EXTENSIONS = (.pdf, .png, .jpg, .jpeg, .webp)`; `medical_extractor.py` handles digital PDFs via direct text extraction, scanned PDFs via page-to-image rendering, and images via multimodal vision models, including a vision-repair retry path. The diagram's "LLM pipeline" label hid all of this. No work needed.

**Intermediate priority**
3. ✅ **DONE — Conversation robustness.**
   - *Already existed:* standalone follow-up query rewriting (`rewrite_query_with_context`) with safety-framing preservation, plus bounded-cost history summarization — System C already matched A's conversation mechanics.
   - *Implemented now:* **durable transcripts** — sessions are now mirrored to a Supabase `conversation_sessions` table after every turn and transparently rehydrated on a memory miss, so conversations survive process restarts (leapfrogging A's volatile in-process sessions). Best-effort by design: a persistence outage can never block Q&A. Tests: `tests/test_session_persistence.py` (6 passing).
4. ✅ **DONE (already existed) — Answer citations.** The QA answer schema (`retrieval.py`) enforces a `sources` array of `{date, source_file}` on every answer via strict JSON-schema output — the "Cited Q&A" promise was already a backend contract, not just a UI label. No work needed.
5. ✅ **DONE (already existed) — Provider discovery.** A full care-navigation module (`care/`) with a provider abstraction, Google Places geodata provider, and records-derived specialty recommendations already serves `GET /api/v1/care/recommendations` and `GET /api/v1/care/facilities` — matching (and exceeding, via records-driven specialty ranking) System B's differentiator. No work needed.

**Lower priority**
6. ✅ **DONE (already existed) — Ops/admin tooling.** `inspect_chroma.py` is a read-only vector-store inspection CLI supporting both the Chroma and Supabase backends — equivalent to A's inspector. No work needed.
7. ✅ **DONE (already existed) — Job retry / failure-handling visibility.** The job system already tracks per-file `retryable`, `retry_after_seconds`, and machine-readable `error_code`s, classifies provider capacity failures, blocks doomed retries batch-wide, and surfaces `Retry-After` headers. No work needed.
8. ✅ **DONE — Audit logging and export/interoperability.** *Implemented now*, closing capabilities absent from **all three** systems:
   - **Audit logging** (`audit.py` + `audit_log` table): append-only who/what/when trail on every data-touching action (uploads, upload results, QA questions, session create/message/delete, exports). Metadata only — no clinical payloads in the trail. Best-effort: degrades to structured app-log lines, never fails the audited request.
   - **Record export / interoperability** (`export.py` + `GET /api/v1/export`): lossless native-JSON export, and a **FHIR R4 collection Bundle** (Patient, MedicationStatement, Observation with valueQuantity/valueString honesty, AllergyIntolerance, Provenance) mapping only fields the extractor actually produced. Deterministic, no LLM calls. Tests: `tests/test_export.py` + `tests/test_audit_and_export_endpoint.py` (15 passing).

**Verification:** full backend suite passes — **78 tests, 0 failures** (`python -m pytest backend/tests/`). New schema objects (`conversation_sessions`, `audit_log`) are additive in `supabase_schema.sql`; every new capability degrades gracefully when its table is absent, so existing deployments keep working unchanged.
