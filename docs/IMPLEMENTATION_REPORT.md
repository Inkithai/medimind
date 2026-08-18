# Implementation Report — Clinical-Safety & Longitudinal CDS Roadmap

All roadmap features implemented and committed (4 commits on the working branch).
**Authentication features explicitly excluded** per requirement (no
register/login/accounts/multi-patient).

Conventions honoured throughout: **deterministic-first** (no LLM for any new
safety rule), **positive-evidence-only** abnormality, **no diagnosis** (every
finding says "ask your clinician"), **fail-safe integration** (each new
checker is in try/except and can never break the existing pipeline),
**anonymous-workspace-scoped**, and **curated-source grading** (`source:
curated_knowledge_base` → graded `deterministic`).

Tests: **55 new offline tests, all green**. Existing suite: 822 passing; the
only failures are pre-existing openai-client version mismatches in retry-ladder
tests (none in files this work touched). App imports clean; **67 API routes**.

---

## P0 — Clinical safety (the real gap)

| # | Feature | Module(s) | API | Status |
|---|---|---|---|---|
| 1 | **Renal/Hepatic dosing** — flags renally/hepatically sensitive drugs vs the patient's own organ-function markers (eGFR/creatinine/BUN/urea; ALT/AST/bilirubin/albumin). Surfaces a dose-review reason, **never** a replacement dose. | `renal_hepatic_dosing.py` (+`clinical_lab_values.py`) | merged into cross-check; in `consult-triage` | ✅ |
| 2 | **Drug–Lab interaction checking** — drug vs the patient's *measured* lab value (ACEi/ARB/K-sparing/K-supplement + high K; digoxin + low K; Na-lowering + low Na; anticoagulant + high INR). | `drug_lab_interactions.py` | merged into cross-check | ✅ |
| 3 | **Condition-specific contraindications** — drug vs extracted condition (NSAID+ulcer, beta-blocker+asthma, ACEi/warfarin/statin+pregnancy, anticoagulant+active bleeding, …). | `condition_contraindications.py` | merged into cross-check | ✅ |
| 4 | **Clinician feedback loop** — reviewer verdicts (confirmed/false_positive/needs_change/overridden) + reason + metrics (confirmation/FP/override rates, noisiest rules). | `clinician_feedback.py` | `POST/GET /findings/feedback`, `GET /findings/feedback/metrics` | ✅ |

New findings auto-backfill into old snapshots (`_enhanced_cross_check`) and
route to a doctor in `consult_triage` by severity.

## P1 — Longitudinal / patient-facing CDS

| # | Feature | Module | API | Status |
|---|---|---|---|---|
| 5 | **Vital-sign trends** — BP/pulse/SpO2/weight/temp/RR/glucose drift + latest-reading screening flags (BP parsed systolic/diastolic). | `vital_trends.py` | `GET /vital-trends` | ✅ |
| 6 | **Symptom intake & reasoning** — patient symptom cross-referenced vs relevant meds/conditions/abnormal labs; **not a diagnosis**. | `symptom_intake.py` | `POST /symptoms/analyse` | ✅ |
| 7 | **Preventive-care / care-gap detection** — age/sex/condition-based screening & immunisation reminders. | `preventive_care.py` | `GET /preventive-care` | ✅ |
| 8 | **Alert-fatigue management** — override suppression + near-duplicate collapse. | `alert_management.py` (+ feedback) | `GET /findings/alerts`; override state annotated on every cross-check finding | ✅ |

## P2 — Platform maturity

| # | Feature | Module | API | Status |
|---|---|---|---|---|
| 9 | **FHIR ingestion** — FHIR R4 Bundle → extraction doc shape (reverse of `export.py`). | `fhir_ingestion.py` | `POST /import/fhir` | ✅ (parse; persistence needs configured DB) |
| 10 | **Safety-finding lifecycle** — state machine new→active→reviewed→confirmed/dismissed/resolved/reopened with validated transitions + history. | `finding_lifecycle.py` | `POST/GET /findings/lifecycle` | ✅ |
| 11 | **Medication adherence** — supply-pattern signals (refill gaps, late refills, apparent stops) from prescription dates; supply ≠ intake. | `adherence.py` | `GET /adherence` | ✅ |
| 12 | **Early-warning score** — NEWS2-style aggregate deterioration screen from vitals+labs. | `early_warning.py` | `GET /early-warning` | ✅ |
| 13 | **Living guidelines** — version registry + staleness detection for every curated clinical source. | `living_guidelines.py` | `GET /guidelines/status` | ✅ (scaffold; auto-refresh needs a content pipeline) |
| 14 | **Patient-generated health data** — home BP/glucose/etc. folded into vital/lab analysis via `augment_timeline`; tagged `patient_reported`. | `patient_data.py` | `POST/GET /patient-data/measurements` | ✅ |
| 15 | **Secure provider messaging** — provider message-thread store (care-workflow layer). | `secure_messaging.py` | `POST/GET /provider-messages` | ✅ (store; external transport wired by operator) |

---

## Verification

- 55 new offline tests pass (`test_p0_clinical_safety.py`, `test_p1_p2_features.py`).
- End-to-end integration: detect → merge into cross-check → route in triage, verified on a combined patient (high-K + low-eGFR + ulcer) → 3 findings, all routed to doctor, urgency = urgent.
- `cross_check_prescriptions` integration test still green (no regression to existing KB/allergy passes).
- Live API smoke test (uvicorn): anonymous session → FHIR parse, PGHD recording, symptom analysis, preventive care, feedback metrics, guidelines status all return 200 on a fresh offline workspace.
- `finding_feedback` table added to `supabase_schema.sql` (optional best-effort mirror; in-memory-first).
