# Functional gap report

**Review date:** 2026-08-17  
**Compared against:** the current checked-out implementation  
**Labels:** Repository A and Repository B

## Scope and method

I inspected the source files, routes, persistence models, service classes, and tests in both comparison repositories and the current `backend/` implementation. README-only claims were excluded. A feature is listed below only when the comparison code contains an executable implementation and the current implementation does not provide the same capability in an equivalent form.

The comparison repositories are referred to only by the neutral labels **Repository A** and **Repository B**.

## Summary and core-function conclusion

**Core medical/AI conclusion: no major core-function gap was found.** The current implementation already covers the important functional areas represented by the two comparison repositories: medical extraction, OCR, grounded RAG/retrieval, lab trends, medication and prescription safety, allergy and interaction checks, identity protection, poisoning-reference knowledge graphs, triage, specialty/provider recommendation, and referral trails.

The differences identified below are **not competition-defining medical-intelligence gaps**. They are engineering, lifecycle, account/data architecture, or persistence-model differences. They are documented for completeness, but they should not be interpreted as evidence that the current implementation is behind on core medical or AI functionality.

- **Repository A:** No qualifying core or supporting functional gap was found. Its distinctive implemented capabilities—timeline-wide medication safety timing, identity mismatch holding, consult triage, antidote knowledge-graph ingestion, evidence grading, lab trends, language-risk handling, duplicate detection, and persistent conversations—are present in the current implementation, often with additional surrounding controls.
- **Repository B:** Four **non-core architectural/engineering differences** remain. Two are fully implemented engineering/lifecycle capabilities in Repository B; two are implemented but narrower data/account architecture capabilities and are marked **partial relative to the current system**.
- Repository B's Ask AI/RAG and provider-search surfaces were not counted: the relevant code is a shell or unconfigured path, while the current implementation has working grounded retrieval and live care-directory integration.

## Non-core differences fully implemented in a comparison repository and not currently equivalent

### 1. Injectable AI-provider interface with a deterministic mock

- **Feature:** A provider abstraction and offline mock provider for AI calls.
- **Which repository:** Repository B.
- **Implementation method / technology / logic:** `backend/app/services/ai/base_provider.py` defines `BaseAIProvider` with text and structured-generation methods. `gemini_provider.py` implements the live provider; `mock_provider.py` returns canned structured/text responses and records the last prompt. `factory.py` selects the provider and exposes `set_ai_provider()` for dependency injection. The test suite uses this to exercise extraction without API keys or network calls.
- **How it differs from the current implementation:** The current extraction and conversation paths use the OpenAI-compatible client directly (`backend/medical_extractor.py` and `backend/conversation.py`), with provider selection by environment variables and optional provider failover. That is provider configuration, not a substitutable `BaseAIProvider` contract, and there is no equivalent built-in mock provider. Current tests generally patch clients/functions or supply environment configuration rather than inject a standard mock service.
- **Status:** **Fully implemented in Repository B; missing as an equivalent capability currently.**

### 2. Delete-one-document lifecycle with storage/database consistency

- **Feature:** Authenticated deletion of one document, including its private storage object and database record.
- **Which repository:** Repository B.
- **Implementation method / technology / logic:** `backend/app/api/documents.py::delete_document()` verifies User → Patient → Document ownership, deletes from Supabase Storage first, aborts database deletion if storage deletion fails, then deletes the relational document row and commits. It returns explicit 404/403/500 errors. The route is `DELETE /documents/{document_id}`.
- **How it differs from the current implementation:** The current API has upload, listing, reprocessing, corrections, conflict handling, and session deletion, but no `DELETE /api/v1/documents/{document_id}` route and no equivalent storage-first single-document deletion workflow. The current snapshot/rebuild model also has no document-delete operation that removes the document from storage and safely rebuilds all derived state.
- **Status:** **Fully implemented in Repository B; absent currently.**

## Partially distinct capabilities (the current system has related functionality, but not the same operational form)

### 3. Explicit application User → Patient profile model and profile endpoints

- **Feature:** An application-level user record linked to a first-class Patient row, with idempotent registration/synchronization and a current-user profile endpoint.
- **Which repository:** Repository B.
- **Implementation method / technology / logic:** `backend/app/models/user.py` and `patient.py` define SQLAlchemy entities and relationships. `backend/app/api/auth.py::register_application_user()` creates or synchronizes the application User and a default Patient profile; `GET /auth/me` returns the authenticated application user. All document and clinical-record queries resolve the Patient through the authenticated User and enforce ownership with relational foreign keys.
- **How it differs from the current implementation:** The current implementation authenticates a JWT and scopes documents/snapshots by the `user_id` string, including an anonymous-session flow. It has strong document-identity protection in `backend/identity_guard.py`, but it does not expose an application User/Patient profile resource or registration/profile API, nor does it store a patient demographic profile as a first-class relational entity. Identity is inferred and checked from uploaded medical documents rather than managed as a user-owned profile.
- **Status:** **Partially implemented relative to the current system:** authentication, tenant isolation, and document identity checks exist; the explicit Patient/profile lifecycle does not.

### 4. Independently persisted, typed clinical records and safety findings

- **Feature:** Relational persistence of extracted clinical entities and separately addressable medication-safety findings, rather than keeping the latest derived clinical view primarily as one snapshot payload.
- **Which repository:** Repository B.
- **Implementation method / technology / logic:** `backend/app/models/medical_event.py`, `medication.py`, `prescription.py`, `lab_result.py`, `allergy.py`, `finding.py`, `ai_analysis.py`, and `question.py` provide typed SQLAlchemy tables. `medical_persistence_service.py` maps extraction output into those rows. `medication_safety_persistence_service.py` idempotently upserts findings by stable issue keys, removes stale findings owned by that safety engine, and retains finding IDs, risk, confidence, recommendation, and involved medication IDs. The records API exposes separate medication, finding, lab, allergy, timeline, and analysis views.
- **How it differs from the current implementation:** The current system does persist raw documents, durable `patient_snapshots`, conversation sessions, corrections/conflicts, referrals, audit records, and vector chunks. Its extracted medications, labs, allergies, and safety report are principally fields in the merged timeline/snapshot JSON; `/cross-check`, `/lab-trends`, and `/patient-snapshot` read that derived view. It does not have equivalent independently addressable relational rows and stable finding records for each clinical entity/safety issue.
- **Important qualification:** This is not a claim that the current system lacks structured clinical data or durable safety results. It has both. The gap is the independently queryable relational/resource-level persistence and finding lifecycle.
- **Status:** **Partially distinct in Repository B; related capability exists currently in snapshot form.**

## Deliberately excluded after code inspection

These were checked but are **not** missing capabilities:

- **RAG/retrieval:** the current implementation has vector indexing, patient-scoped retrieval, citation/evidence validation, grounding gates, follow-up focus carry-over, and self-healing/index diagnostics. Repository B's Ask AI surface is not an equivalent working RAG implementation.
- **Document extraction and OCR:** the current implementation supports text PDFs, scanned PDFs, images, vision extraction, an offline Tesseract pre-pass, confidence handling, and reprocessing. Repository B's PyMuPDF/Tesseract pipeline is not a missing capability.
- **Lab analysis:** the current `backend/lab_trends.py` performs deterministic trends, boundary/crossing analysis, and strict unknown handling for censored, approximate, ambiguous, multi-number, and scientific-notation values. Repository B's lab service does not add an absent capability.
- **Prescription safety:** the current system has deterministic interaction rules, deterministic allergy-class/name checks, duplicate detection, active/inactive medication windows, dosage ceilings/frequency/minimum checks, unit conversion, and consult triage. Repository B's corresponding services are not missing from the current implementation.
- **Antidote/poisoning references:** the current `backend/poisoning_kg.py`, `graph_db.py`, and API route implement deterministic PDF table extraction, Neo4j ingestion/lookup, and evidence enrichment. Repository A's implementation is therefore not a gap.
- **Triage/referral/provider discovery:** the current system has deterministic consult triage, specialty mapping, live provider sources, ranking explanations, and a persisted referral trail. Repository B's doctor-search implementation does not establish a missing current capability.
- **Identity and safety controls from Repository A:** identity mismatch holding, language-risk controls, evidence grading, risk timelines, and timeline-wide safety checks are already present in the current backend.

## Evidence locations inspected

### Current implementation

- `backend/api.py`
- `backend/auth.py`
- `backend/db.py`
- `backend/medical_extractor.py`
- `backend/retrieval.py`
- `backend/identity_guard.py`
- `backend/consult_triage.py`
- `backend/poisoning_kg.py`
- `backend/graph_db.py`
- `backend/lab_trends.py`
- `backend/ocr_service.py`
- `backend/dosage_rules.py`
- `backend/drug_interactions.py`
- `backend/drug_allergy_rules.py`
- `backend/medication_activity.py`
- `backend/referral_trail.py`
- `backend/supabase_schema.sql`
- `backend/tests/`

### Repository A

- `api.py`, `medical_extractor.py`, `identity_guard.py`, `risk_timeline.py`, `consult_triage.py`
- `poisoning_kg.py`, `graph_db.py`, `evidence_grading.py`
- `lab_trends.py`, `language_guard.py`, `document_dedup.py`, `conversation.py`, `db.py`

### Repository B

- `backend/app/api/auth.py`, `api/documents.py`, `api/records.py`
- `backend/app/models/`
- `backend/app/services/ai/`
- `backend/app/services/medical_persistence_service.py`
- `backend/app/services/medication_safety_service.py`
- `backend/app/services/medication_safety_persistence_service.py`
- `backend/app/services/ocr_service.py`, `document_processor.py`, `document_processing_service.py`
- `backend/app/services/lab_intelligence_service.py`
- `backend/tests/`
