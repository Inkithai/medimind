# MediMind — Prioritized Implementation Roadmap from the Comparison Review

**Date:** 2026-08-17
**Basis:** Full source inspection of MediMind (`/home/user/medimind`, commit `79ed34b`) and the two comparison repositories (referred to anonymously as **Repository A** and **Repository B**). The detailed evidence tables are superseded by this document; every priority below is traceable to inspected code.

---

## 0. Bottom line

MediMind is already ahead of both comparison repositories in several major areas. Do not copy everything. The features worth adding are the ones that (a) close a real safety gap, (b) build on infrastructure MediMind already has, or (c) extend an existing engine rather than replace it.

**Where MediMind is already stronger (do not regress):**

| Area | MediMind | Comparison repos |
|---|---|---|
| RAG / Ask AI | Citation-validated RAG, grounding gates, evidence grading, self-healing indexes, multi-turn focus carry-over | Repository B's Ask AI is a UI shell with an `unconfigured()` stub; Repository A removed its vector store entirely |
| Provider search | Live Google Places + OSM/Overpass with failover, GPS refinement, category filters, specialty mapping | Repository B ships hardcoded demo providers and an `unconfigured()` search stub |
| Drug-interaction KB | Class-based deterministic rules (NSAIDs, anticoagulants, ACE-Is, …) + LLM cross-check | Repository B has a small pairwise list |
| Dosage rules | Max single **and** daily dose, max frequency, sub-therapeutic minimums, PRN handling | Repository B is single-dose-only |
| Evidence & trust | Page-level evidence, corrections, conflicts, quarantine, evidence hierarchy, risk timeline | Neither repo approaches this |
| Clinical breadth | Change detection, follow-up, appointment prep, record integrity, i18n (en/si/ta), accessibility | Absent in both |

---

## 1. Highest-value features to add

### 1.1 Deterministic medication ↔ allergy contraindication

- **What:** Rule-based medication name/class → patient allergy matching. Never depend on the LLM noticing it.
- **Where in MediMind:** New module alongside `backend/drug_interactions.py` (mirror its `_CLASS_MEMBERS` design): an allergen-class map (e.g., penicillin allergy → amoxicillin/ampicillin/…) plus a normalized-name table, matched against the extracted `allergies_noted` and medication `ingredients` lists. Surface findings through the same cross-check/`clinical_flags.py` path with a fixed conservative confidence (pattern: 0.95) and "unknown severity fails safe to high" (pattern: Repository B `medication_safety_service.py::_check_allergies`).
- **Why it wins:** Deterministic catch of "prescribed amoxicillin; patient has a penicillin allergy" — the clearest safety improvement, pure code, no API cost.

### 1.2 Prescription active/inactive windows

- **What:** `start_date` / `end_date` awareness — only run interaction/allergy/dosage checks against currently active prescriptions; report the reference date and active set.
- **Where in MediMind:** Extend the cross-check inputs in `backend/medical_extractor.py` (and/or `medication_history.py`, which already computes transitions). Rule (pattern: Repository B `is_prescription_active`): no `end_date` → active; `end_date >= today` → active; else inactive. MediMind's conservative date extraction already supplies the dates.
- **Why it wins:** A 2023 prescription that explicitly ended is currently still included in MediMind's interaction check. This complements the existing medication-history logic rather than duplicating it.

### 1.3 Antidote / poisoning knowledge graph (Neo4j + WHO EML)

- **What:** Deterministic ingestion of the WHO EML "Antidotes and other substances used in poisonings" section (adult EML + children's EMLc) into Neo4j; per-upload lookup of extracted medications; antidote reference notes in the cross-check.
- **Where in MediMind:** This is the cheapest big win — `backend/evidence_grading.py` **already defines** the `reference_graph` evidence source, the `graph_backed_findings` parameter, and confidence-uncapping for reference-backed findings; only a hardcoded test fixture feeds it today. Port the pattern (Repository A `poisoning_kg.py` + `graph_db.py`): pdfplumber table parsing, per-listing properties on edges (the two WHO lists disagree), MERGE-based idempotent ingest, bulk lookup, optional-graph fail-closed with observability logging. Wire the lookup into the upload pipeline and feed matches into `grade_cross_check(..., graph_backed_findings=...)`.
- **Why it wins:** Adds the actual knowledge source and graph layer to infrastructure MediMind already built — evidence hierarchy, not a new concept.

### 1.4 Dosage unit normalization

- **What:** Extend the dosage engine beyond mg: parse and compare mg, g, mL, IU, tablets with canonical-unit conversion; unparseable/non-comparable units → explicit **"not evaluated"**, never guessed.
- **Where in MediMind:** Extend `backend/dosage_rules.py` — keep its existing max single/max daily/max frequency/min-dose/PRN logic (stronger than the comparison), and add the unit-conversion layer (pattern: Repository B `medication_dosage_rules.py::DosageAmount` + canonical-unit conversion). Add converted ceilings to the curated rule table per unit.
- **Why it wins:** Volume- and unit-dosed medicines (syrups, insulin, creams) currently fall into the `skipped` bucket; this upgrades the existing engine without replacing it.

### 1.5 OCR pre-processing layer (Tesseract)

- **What:** Offline text layer for images/scanned PDFs: per-page text + average OCR confidence, digital-text-first (PyMuPDF) with Tesseract fallback, typed OCR errors.
- **Where in MediMind:** New pre-pass module feeding `backend/medical_extractor.py` — run OCR to produce a transcript, then keep vision-based extraction as the higher-level interpretation layer. Use the transcript for (a) token-free digitization, (b) an independent text for indexing/evidence when the vision model is unavailable, (c) per-page confidence metadata.
- **Why it wins:** Offline fallback + reduced LLM/vision usage on clean scans; vision extraction remains the interpreter.

### 1.6 Strict UNKNOWN lab-value handling

- **What:** Never convert `"<5"`, `">1000"`, `"~5"`, `"5 ± 1"`, locale-ambiguous `"1,200"` (unresolvable case) or scientific notation into an artificial numeric value for trends. `UNKNOWN → insufficient evidence → no misleading trend`; trend state `INSUFFICIENT_DATA` for <2 usable points.
- **Where in MediMind:** `backend/lab_trends.py::_parse_value` currently drops qualifiers and trends the magnitude (`"<5" → 5.0`, censoring carried only in the flag). Change the classifier to return an UNKNOWN sentinel for censored/approximate/tolerance/ambiguous values, and have `_direction`/`_trend_risk` treat UNKNOWN points as excluded evidence (pattern: Repository B `lab_intelligence_service.py` `_CENSORED_VALUE_MARKERS` + UNKNOWN status). Keep MediMind's superior thousands/European separator disambiguation for values that *are* parseable.
- **Why it wins:** Fits MediMind's safety-first design — a trend computed on an estimated censored magnitude can silently invert direction.

### 1.7 Document-type classification

- **What:** Per-document classification: prescription | lab report | discharge summary | consultation note | other — plus a short summary and overall confidence.
- **Where in MediMind:** Extend the extraction schema (alongside `backend/document_filter.py`'s binary medical/non-medical gate, which stays as the early cost gate). Persist the type on the snapshot/document record.
- **Why it wins:** Enables type-aware validation and retrieval (e.g., lab-only rules, prescription-only cross-checks, type-scoped Q&A routing in `question_routing.py`).

### 1.8 Finding → specialty → provider workflow (concept only)

- **What:** Persist the referral relationship: `Safety Finding → Recommended Specialty → Search → Provider results`, including *why* the referral was made and *why* each provider was ranked (transparent weight disclosure).
- **Where in MediMind:** MediMind already has the hard parts — live provider search (`backend/care/`) and specialty mapping (`specialty_mapping.py`). Add: a persisted search-intent record (finding_id, specialty, location, radius, availability preference), a transparent ranking breakdown per result (e.g., Specialty/Distance/Completeness/Verified weights), and deep links from safety findings to the search. Do **not** copy the static demo-provider data layer.
- **Why it wins:** Turns MediMind's already-live search into a closed clinical loop with auditability.

---

## 2. Lower priority (engineering improvements, not differentiators)

Useful, but none of these changes the competition outcome. Do them opportunistically:

- **Magic-byte upload validation** — sniff `%PDF`/JPEG/PNG signatures in `backend/api.py` instead of extension-only filtering.
- **Per-document retry/re-process endpoints** — `POST /documents/{id}/process` + `/extract` idempotent endpoints next to the existing `backend/jobs.py` queue.
- **AI provider abstraction + mock provider** — `BaseAIProvider` interface with a mock so safety/QA pipelines are testable offline.
- **Retrospective duplicate review CLI** — reuse `backend/document_dedup.py` logic in a read-only audit tool for pre-existing records.
- **Retrieval-context inspection CLI** — print the exact assembled QA context per patient/question (observability).
- **Account profile management** — legal name/DOB/phone/language, password change, data export, deletion (note: comparison implementation is partially stubbed).
- **Multi-strategy JWT verification** — only relevant if MediMind moves to Supabase Auth.

---

## 3. Things NOT to copy

Confirmed during the review — these only *look* like advantages:

- **Repository B's Ask AI/RAG** → MediMind's is already much more mature.
- **Repository B's provider search** → MediMind already has live provider search; B's is static demo data + a stub.
- **Repository B's static Jaffna doctor list** → never replace MediMind's live directory with hardcoded rows.
- **Repository B's dosage rules as a whole** → adopt only its **unit conversion**; keep MediMind's daily-dose/frequency engine.
- **Repository A's general clinical pipeline** → largely derived from an earlier MediMind architecture; already superseded.
- **Ollama support** → README-only in B; ignore.
- **Repository A's "no vector store" retrieval** → a deliberate simplification; MediMind's RAG is strictly more capable.

---

## 4. Build plan (YGC)

### Phase 1 — Safety (start here)

1. Deterministic allergy contraindication engine (§1.1) — ✅ **implemented** (`backend/drug_allergy_rules.py`, merged into the cross-check pipeline)
2. Active prescription filtering for safety checks (§1.2) — ✅ **implemented** (`backend/medication_activity.py`, scoped cross-check + dosage checks, LLM skipped when nothing active)
3. Dosage unit normalization (§1.4) — ✅ **implemented** (`backend/dosage_rules.py::_dose_to_mg`, tablet/mL/IU → mg with documented strengths + "not evaluated" fallback)
4. Strict UNKNOWN lab-value handling (§1.6) — ✅ **implemented** (`backend/lab_trends.py::_parse_trend_value`, censored/approximate/tolerance/scientific-notation readings excluded from trend math)

### Phase 2 — Clinical knowledge

5. WHO antidote/poisoning knowledge graph → reference-graph evidence integration (§1.3) — ✅ **implemented** (`backend/graph_db.py` + `backend/poisoning_kg.py` + `graph_backed_findings_from_antidotes` in `evidence_grading.py`; optional Neo4j, fail-open, `POST /api/v1/knowledge-graph/antidotes` ingestion endpoint, per-upload lookup wired into upload + record-rebuild paths)

### Phase 3 — Doctor recommendation

6. Finding → specialty → provider search → transparent ranking → persisted referral reason (§1.8) — ✅ **implemented** (`backend/referral_trail.py` + `provider_ranking.py` numeric components + `db.save_referral_search`/`load_referral_searches` + `referral_searches` table in `supabase_schema.sql`; search endpoint persists and returns the trail, `GET /api/v1/care-referrals` serves history; frontend renders the referral reason and per-provider breakdown)

**Phases 1–3 complete.** Remaining: Phase 4 (Robustness — OCR fallback, document-type detection, upload hardening, retry endpoints).

### Phase 4 — Robustness

7. Tesseract OCR fallback (§1.5)
8. Document-type detection (§1.7)
9. Magic-byte upload validation + per-document retry endpoints (§2)

**Net result:** new clinical functionality in the areas where MediMind is genuinely behind, with zero regressions in the areas (RAG, provider search, evidence/trust, dosage breadth) where MediMind is already substantially stronger.
