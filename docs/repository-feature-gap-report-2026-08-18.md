# Evidence-based functional gap report

**Date inspected:** 2026-08-18  
**Current implementation:** commit `a39f32f80aeb84edb1cba2606eb2592384132efe`  
**Repository A:** commit `e5353530a0d5176269616ce6baff39b895ccf082`  
**Repository B:** commit `edc5ce058b9a6881974a2f113825bed1682f7573`

## Scope and method

This report is based on source-code inspection, not README claims. It lists **only capabilities present in Repository A or Repository B that are not present in the current MediMind code**. UI-only differences and capabilities MediMind already matches or exceeds are excluded.

“Missing” is used narrowly: no equivalent end-to-end behavior could be established in the current code. A different architecture is not treated as a missing feature unless it creates a distinct functional capability.

---

# Fully implemented missing capabilities

## 1. Published, page-cited opioid safety guidance in the safety and RAG pipelines

- **Feature:** Deterministic matching of a patient's medications to published opioid-overdose guidance, including opioid-plus-sedative warnings, overdose signs, tolerance-after-a-break risk, breathing-condition risk, and advice concerning reversal medication. Relevant guidance is included in Q&A context and specific cross-check findings can be upgraded from unverified model knowledge to source-backed findings.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:**
  - A versioned local reference library contains verbatim statements, page numbers, publication metadata, conservative drug-class membership, and plain-language renderings (`reference_library.py:59-224`).
  - Exact class matching is performed over normalized medication ingredients rather than vector similarity (`reference_library.py:231-379`).
  - Dated treatment-window logic emits an opioid-plus-depressant finding only when the courses overlap (`reference_library.py:411-455`).
  - The cross-check uses the citation resolver before evidence grading, then adds `guideline_flagged_combinations` (`medical_extractor.py:1120-1141`).
  - Retrieval injects a distinct “published guidance” section into the answer context (`retrieval.py:632-643`, `retrieval.py:1054-1059`).
  - The same reference data can optionally be projected into Neo4j with `Guidance`, `GuidanceSource`, `DrugClass`, and `Medicine` nodes (`guidance_kg.py:49-218`). The local library remains the fail-safe source of truth.
- **How it differs from MediMind:** MediMind has deterministic interaction, dosage, allergy, timing, WHO-antidote, evidence-grading, and RAG logic, but there is no published-guidance library, guidance graph, page-cited opioid/depressant rule, or published-guidance RAG section. Its curated interaction explanations are code-maintained assertions without publication/page citations (`backend/drug_interactions.py`), and its WHO graph is limited to the poisoning/antidote section (`backend/poisoning_kg.py`).

## 2. Timing-aware triage that de-escalates non-concurrent historical medication findings

- **Feature:** Referral urgency explicitly changes when two implicated medication courses did not overlap. The finding remains visible as history but is reduced to routine urgency and marked `is_historical`; concurrent or possibly concurrent findings retain live-risk handling and structured dates.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** `_apply_timing()` consumes the cross-check finding's `timing.status`, `window_start`, `window_end`, and `gap_days`. `not_concurrent` findings are retained but relabeled as historical/routine; concurrent findings receive the active date window (`consult_triage.py:429-492`). This is called for interaction, duplicate, and dosage-conflict referral items (`consult_triage.py:494-539`).
- **How it differs from MediMind:** MediMind computes and attaches treatment timing in its risk/cross-check layer, but `generate_consult_triage()` routes interactions solely by severity and does not consume `timing.status` (`backend/consult_triage.py:242-276`). Therefore an interaction shown elsewhere as “never taken together” can still produce the same urgent/soon referral as a concurrent interaction.

## 3. Explicit urgent referral for concurrent duplicate-ingredient exposure

- **Feature:** A distinct triage trigger for periods in which two live prescriptions supplied the same ingredient, optionally including the combined daily dose and active date window.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** The cross-check's deterministic `concurrent_exposure` records are mapped to `concurrent_double_dose` referral items with fixed 0.9 confidence, structured timing, cumulative-dose text, and an urgent pharmacist route (`consult_triage.py:188-203`, `consult_triage.py:561-576`).
- **How it differs from MediMind:** MediMind already computes `concurrent_exposure` in its cross-check (`backend/medical_extractor.py:3503-3504`, `backend/risk_timeline.py`), but its triage module never reads that list. It routes ordinary duplicate prescriptions as “soon,” without a separate escalation for proven overlapping supply (`backend/consult_triage.py:278-290`).

## 4. Triage/referral generated from extraction and translation quality risks

- **Feature:** Poor document readability and uncertain cross-language normalization become actionable referral items, with different explanations and remediation paths rather than being treated as one generic low-confidence condition.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** `_items_from_extraction_quality()` scans timeline visits, calls the language-risk assessor, and emits:
  - `translation_uncertain` when a non-English document's effective translation confidence needs review; and
  - `low_extraction_confidence` when overall confidence is low or fields are marked illegible.
  Both are routed to a pharmacist with confidence inherited from the source-quality evidence (`consult_triage.py:624-684`). `triage_consultation()` includes these items whenever a timeline is supplied (`consult_triage.py:989-1032`), and the API supplies that timeline (`api.py:507`, `api.py:753`).
- **How it differs from MediMind:** MediMind has a language guard, OCR confidence, translation confidence, and low-confidence field metadata, but `generate_consult_triage()` accepts only cross-check, lab-trend, and dosage reports. It cannot create a consult/referral because a medication name may have been mistranslated or a document was too unclear to trust (`backend/consult_triage.py:211-220`).

## 5. Referral for a persistently abnormal lab series that never crosses from normal

- **Feature:** A lab test that is already abnormal at the first available observation and remains abnormal is routed for doctor review even though no normal-to-abnormal crossing exists.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** `_items_from_lab_trends()` checks the first and latest flags. If both are `high`/`low`, it emits `lab_persistently_abnormal` with a “soon” doctor route (`consult_triage.py:578-621`; routing rule at `consult_triage.py:224-237`).
- **How it differs from MediMind:** MediMind's lab trend engine recognizes an already-abnormal series in its explanation and risk score, but its triage only creates lab referral items for `crossed_into_abnormal_at` or `approaching_threshold` (`backend/consult_triage.py:337-376`). A persistently abnormal series with no crossing and no “approaching” flag can therefore be omitted from triage.

## 6. Model-assisted specialty selection for unmatched doctor-routed findings

- **Feature:** Doctor-routed findings that do not match the deterministic lab-specialty table can receive a specific specialty recommendation rather than always defaulting to primary care.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** Common lab mappings remain deterministic. Unmatched qualifying findings are batched into a low-temperature structured LLM call with a strict JSON schema; the result includes patient-facing specialty, clinical name, rationale, and confidence (`consult_triage.py:687-818`). `_assign_specialties()` applies rule matches first, uses the model only for unresolved cases, and fails safely to a general practitioner if the call fails (`consult_triage.py:820-889`).
- **How it differs from MediMind:** MediMind uses only a fixed lab-keyword map and a general-practitioner fallback (`backend/consult_triage.py:87-169`). It has no secondary specialty resolver for medication/allergy or uncommon findings. This comparison does **not** imply the model-assisted answer is clinically superior; it is simply an implemented capability that MediMind lacks.

## 7. Strict deterministic sanitization of incomplete, placeholder, and malformed extracted clinical dates

- **Feature:** All AI-extracted event, prescription-start, prescription-end, and lab-result dates are validated before persistence. Placeholder, incomplete, unsupported, or out-of-range dates become `null` rather than entering the record.
- **Which repository has it:** **Repository B**
- **Implementation method/technology/logic used:** A shared Pydantic `mode="before"` validator accepts only a full ISO date or one of a small set of explicit complete formats, enforces years 1900–2100, and rejects wildcard masks (`X`, `?`, `*`, `_`), partial dates, and text markers such as `unknown`/`N/A` (`backend/app/schemas/extraction.py:44-95`). It is attached to event, medication, and lab-result date fields (`backend/app/schemas/extraction.py:98-210`). The extraction prompt independently instructs the model to return `null` for ambiguous or incomplete dates (`backend/app/services/ai/prompts.py:8-35`).
- **How it differs from MediMind:** MediMind deliberately supports mixed and ambiguous real-world date strings and makes all downstream modules interpret them consistently (`backend/date_convention.py`; `backend/tests/test_date_convention.py`). However, its extraction JSON schema permits arbitrary strings for document and clinical-event dates, and there is no equivalent post-extraction validator that nulls placeholders or incomplete dates before storage (`backend/medical_extractor.py:2067-2135`, `backend/medical_extractor.py:2157`). Consistent interpretation and strict admission validation are different capabilities.

## 8. Additional deterministic drug-interaction pairs absent from MediMind's curated rule set

- **Feature:** Offline deterministic detection for four clinically relevant pairs not present in MediMind's deterministic knowledge base:
  1. warfarin + ciprofloxacin;
  2. lisinopril + ibuprofen;
  3. digoxin + furosemide; and
  4. amlodipine + simvastatin.
- **Which repository has it:** **Repository B**
- **Implementation method/technology/logic used:** A normalized, direction-independent in-memory pair index stores fixed severity and explanation text. Pair keys are alphabetically sorted after punctuation/whitespace normalization (`backend/app/services/medication_interactions.py:25-238`). The active-medication safety service checks every distinct pair against this index (`backend/app/services/medication_safety_service.py:492-528`).
- **How it differs from MediMind:** MediMind's class-based curated KB is broader overall, but these four pairs are not encoded in `backend/drug_interactions.py`. An LLM may still mention them, but MediMind cannot guarantee their detection through its deterministic interaction pass. This item is deliberately limited to those missing rules; it does not claim Repository B's interaction database is more comprehensive overall.

## 9. On-demand medication-safety re-analysis with per-finding reconciliation

- **Feature:** A dedicated API can rerun medication safety against the current persisted prescriptions, persist the result, update changed findings, leave unchanged findings untouched, remove resolved/stale findings, and return reconciliation counts.
- **Which repository has it:** **Repository B**
- **Implementation method/technology/logic used:**
  - `GET /medication-safety/check` performs a fresh read-only analysis.
  - `POST /medication-safety/analyze` performs analysis plus persistence (`backend/app/api/medication_safety.py:81-115`).
  - Findings have stable identities based on type and normalized medication subject; the persistence service reconciles created/updated/unchanged/removed rows transactionally and scopes deletion to finding types owned by the safety engine (`backend/app/services/medication_safety_persistence_service.py:1-226`).
  - Analysis queries only prescriptions active on the reference date (`backend/app/services/medication_safety_service.py:209-345`).
- **How it differs from MediMind:** MediMind computes and replaces the aggregate cross-check snapshot during upload/reprocessing and exposes it through a read endpoint. It has no dedicated endpoint that reruns the complete medication safety engine against unchanged stored records on demand, and no independently reconciled safety-finding rows/counts. Its aggregate-snapshot replacement does prevent old report content from accumulating, but it is not the same callable lifecycle.

## 10. Independently queryable, relational clinical entities with referential integrity

- **Feature:** Extracted medications, prescriptions, allergies, lab results, medical events, findings, and AI analyses are persisted as separate patient-scoped entities and can be queried independently.
- **Which repository has it:** **Repository B**
- **Implementation method/technology/logic used:** SQLAlchemy models and Alembic migrations create foreign-keyed tables with patient/document ownership, cascades, indexes, and separate medication-versus-prescription identity (`backend/app/models/*.py`; `backend/alembic/versions/b1b8329252b7_initial_medical_intelligence_schema.py`). `MedicalPersistenceService` writes all extracted entities in one transaction and deduplicates normalized medication identities (`backend/app/services/medical_persistence_service.py:18-177`). Patient-scoped record endpoints expose each entity class independently (`backend/app/api/records.py:68-317`).
- **How it differs from MediMind:** MediMind stores each source extraction and the merged patient timeline primarily as JSONB documents/snapshots (`backend/supabase_schema.sql:17-40`) and exposes timeline/snapshot-oriented APIs. It does not provide normalized medication, prescription, allergy, lab, event, and finding tables with database-enforced foreign keys and independently addressable rows. This is counted because it enables distinct server-side entity querying and safety-finding reconciliation—not merely because the schema style differs.

---

# Partial or experimental missing capabilities

## P1. Full essential-medicines-list graph ingestion and age-restriction lookup

- **Feature:** Parsing and graphing an entire adult/children essential-medicines list, including sections, alternatives, dosage forms, population labels, and age/weight restrictions; querying medicines by section and restrictions by drug; and comparing curated drug classes against the published list.
- **Which repository has it:** **Repository A**
- **Implementation method/technology/logic used:** `eml_kg.py` parses full PDFs (`extract_full_list()`), writes Neo4j nodes/relationships idempotently (`ingest_full_list()`), provides section and age-restriction queries (`medicines_in_section()`, `lookup_age_restrictions()`), and reports which local class members are corroborated by list sections (`corroborate_class_membership()`). Graph constraints for these node types are added in `graph_db.py`.
- **How it differs from MediMind:** MediMind parses only the antidote/poisoning section and uses it to grade applicable safety evidence (`backend/poisoning_kg.py`, `backend/evidence_grading.py`). It cannot ingest/query the complete list, alternatives, sections, or age restrictions.
- **Why classified partial/experimental:** The code is substantial and executable, but it is a CLI/graph utility. `lookup_age_restrictions()` and the full-list graph are not called by Repository A's API, extraction, cross-check, triage, or RAG runtime. The repository also does not ship the source PDFs or pre-populated graph. It therefore establishes an implemented ingestion/query subsystem, not an end-to-end patient-facing age-safety feature.

## P2. Patient profile metadata stored in the authentication provider

- **Feature:** Updating and retrieving name, legal name, phone, language, and date-of-birth metadata associated with the authenticated account.
- **Which repository has it:** **Repository B**
- **Implementation method/technology/logic used:** The client reads authentication-user metadata and writes updates through the authentication SDK (`frontend/src/lib/api.ts:1230-1294`).
- **How it differs from MediMind:** MediMind uses the verified authentication subject as the patient boundary and derives identity signals from uploaded document history. It has no equivalent account-profile update service or durable patient-entered date-of-birth/contact profile.
- **Why classified partial/experimental:** Repository B's backend `Patient` model contains only `id`, `user_id`, and timestamps (`backend/app/models/patient.py`); these profile values are not copied into the clinical database, checked against uploaded-document identity, or used by lab/dosage/triage logic. This is functional account metadata, but not an integrated medical-identity capability.

---

# Material exclusions (verified as not missing)

The following were inspected but are **not** reported as gaps because MediMind already implements equivalent or stronger behavior:

- OCR with native-PDF extraction, Tesseract confidence, and scanned-document fallback;
- multimodal image/PDF extraction;
- per-user authentication and tenant isolation;
- identity mismatch detection and held-document review;
- lab trends and reference-range crossing detection;
- deterministic dosage, allergy, duplicate-prescription, and broad class-based interaction checks;
- treatment-window and risk-calendar analysis;
- cited, grounded RAG and multi-turn conversation;
- live provider search, specialty mapping, referral history, and provider ranking;
- document deletion/reprocessing, background jobs, retries, correction history, conflict quarantine, audit logging, and export.

Repository B's provider-search database models and Repository A's graph projection by themselves were not treated as separate full features where no additional end-to-end behavior existed.

---

# Summary

**Fully implemented gaps:** 10 narrowly defined capabilities. Most of the clinically important gaps are concentrated in Repository A's newer published-guidance and triage logic; Repository B contributes strict date admission, several deterministic interaction rules, on-demand finding reconciliation, and normalized entity persistence.

**Partial/experimental gaps:** 2. The full essential-medicines graph is not connected to runtime patient analysis, and account profile metadata is not integrated into clinical identity or safety logic.
