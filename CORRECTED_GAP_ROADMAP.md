# Corrected Gap Analysis for MediMind

> This document re-checks the proposed roadmap claim-by-claim against MediMind's actual
> source code. Each verdict cites file:line evidence. The short version: the roadmap's
> **"confirmed gaps" (Section 1, items A–G) are almost all already implemented in MediMind**,
> and a few of the "bigger gaps" are also already present. The *genuinely* missing items are
> a smaller, sharper list — mostly next-generation CDS that no comparison repo has either.

---

## 1. The "confirmed gaps" are mostly NON-gaps (verified in code)

These were presented as the strongest, code-demonstrated gaps. Checking the code shows
they are **already implemented**. The root error in the source analysis: it assumed
anything present in Repository A was absent from MediMind — but Repository A is MediMind's
own earlier branch, so MediMind inherited (and extended) all of it.

| Claimed gap | Verdict | Evidence in MediMind |
|---|---|---|
| **A. Published-guideline safety engine** (opioid/sedative guidance, reversal meds, page citations, `Guidance` layer) | ❌ **Already implemented** | `reference_library.py:18-22` — SAMHSA Overdose Prevention & Response Toolkit (PEP23-03-00-001, 2026), verbatim page-13 quote; `REVERSAL_MEDICATIONS = {naloxone, nalmefene}`; `guidance_kg.py:8-10` — `(:Guidance)-[:PUBLISHED_IN]->(:GuidanceSource)`, `:REQUIRES`, `:COMBINED_WITH`; `evidence_grading.py:54-56` — `reference_graph` grade with `MODEL_KNOWLEDGE_CONFIDENCE_CEILING = 0.6` |
| **B. Timing-aware triage** ("non-overlapping drugs should not be urgent") | ❌ **Already implemented — exactly this behavior** | `consult_triage.py` `_apply_timing`: `if status == "not_concurrent": item["urgency"] = "routine"; item["is_historical"] = True; "The documented courses did not overlap, so this is not presented as a current interaction."` Backed by `risk_timeline.py` (`CONCURRENT` / `POSSIBLE` / `NOT_CONCURRENT` + `gap_days`). |
| **C. Concurrent duplicate-dose escalation** | ❌ **Already implemented** | `risk_timeline.py` computes concurrent-exposure windows + double-dosing exposure; `consult_triage.py:455` consumes `cross_check["concurrent_exposure"]`; the Jan→Feb non-overlap example would be marked `not_concurrent`. |
| **D. Persistent abnormal lab → referral** | ❌ **Already implemented** | `consult_triage.py:537` — `trigger="lab_persistently_abnormal"`, "outside the supplied reference range at both the earliest and latest available readings", `route="doctor"`, `urgency="soon"`. |
| **E. Extraction/translation uncertainty → review** | ❌ **Already implemented** | `consult_triage.py` "Extraction/translation quality referrals" block → `translation_uncertain` and `low_extraction_confidence` items routed to **pharmacist** from `assess_translation_risk`. |
| **F. AI-assisted specialty routing** | ⚠️ **Implemented, but opt-in** | `consult_triage.py:175` `_assign_model_specialties` does a structured model call to resolve GP fallbacks — gated by env `MEDIMIND_MODEL_SPECIALTY_SELECTION` (off by default; fails safe to GP). So it exists; turning it on is a config flip, not a build. |
| **G. Four missing interaction rules** (warfarin+cipro, lisinopril+ibuprofen, digoxin+furosemide, amlodipine+simvastatin) | ❌ **All four already present** | `drug_interactions.py:132, 135, 138, 141` — every one of the four pairs is defined, with severity and plain-language text. |

**Net:** 0 of the 7 "confirmed clinical gaps" survive inspection. The triage engine is
genuinely timing-aware, the lab engine does refer on persistent abnormality, the
guidance/KG layer is real, and the named drug pairs all exist.

---

## 2. Platform gaps — which are real

| Claim | Verdict | Notes |
|---|---|---|
| **H. Persistent authenticated accounts** | ✅ **Real gap** | MediMind is anonymous-only (`auth.issue_anonymous_token`). Confirmed earlier vs. Repository B. |
| **I. Multi-patient-per-account** | ✅ **Real gap** | Strict 1 workspace = 1 patient. |
| **J. Normalized relational entity model** | ✅ **Real (architecture)** | JSON-documents + derived projections; no ORM/normalized tables. |
| **K. Persistent safety-finding lifecycle** | 🟡 **Partial** | MediMind already has more than the roadmap implies: `record_trust.py` correction replay, conflict quarantine, per-fact `status` vocabularies (`active/confirmed/suspected/resolved/...` at `record_trust.py:141-143`), and conflict **resolve/reopen** endpoints. Missing: a general finding-lifecycle (reviewed→dismissed→clinician-confirmed) **with reason capture and performance metrics**. |
| **L. Provider-search history** | ✅ **Real gap** | Find-Care is stateless; no saved searches. |

---

## 3. "Bigger gaps" — corrected against the code

Several "next-generation gaps" are also **already in MediMind**:

| Claimed gap | Verdict | Evidence |
|---|---|---|
| **14. FHIR interoperability** | 🟡 **Export exists; ingestion is the gap** | `GET /api/v1/export?format=fhir` emits a **FHIR R4 Bundle** (Patient, MedicationStatement, Observation, AllergyIntolerance, Provenance) at `export.py:127-201`; plus `/api/v1/export/validation?format=fhir` (`api.py:2670-2704`). What's missing is **FHIR ingestion** (receiving structured data instead of PDFs). |
| **5. Medication reconciliation** | 🟡 **Partial** | `medication_history.detect_medication_transitions` (started/stopped/dose-changed) + `medication_activity` (active/inactive windows) already exist deterministically. Missing: patient-reported/non-adherence input + a reconciled "current list" view. |
| **13. Finding-level provenance/explainability** | 🟢 **Largely implemented** | `evidence.py` (page/quote/box provenance, stable evidence IDs), `evidence_grading.py` (deterministic/reference/model tier), `evidence_builder.py`, and the guidance-KG link (finding → rule → guideline → source). The only missing slice is raw model-reasoning metadata. |

The following **are genuinely missing** (verified absent in code):

| Gap | Status in code | Priority |
|---|---|---|
| **M. Renal/hepatic patient-specific dosing** | Absent — and self-documented as a limit: `dosage_rules.py:294,350` states checks "do not account for this patient's age, weight, kidney/liver function." No eGFR/creatinine/LFT → dose logic exists. | 🔴 P0 |
| **N. Drug–laboratory interaction checking** | Absent as a category. There are drug-*drug* rules that *involve* electrolytes (ACE-inhibitor + potassium-sparing diuretic → hyperkalemia, `drug_interactions.py:94`), but nothing cross-checks the patient's **measured** lab value (e.g. K⁺ = 6.1) against a drug's effect. | 🔴 P0 |
| **O. Condition-specific contraindication engine** | Absent as an engine. Conditions appear only in specialty routing (`care_finder`), export codes, and as *textual* risk factors in the opioid guidance (`reference_library.py:214-218`). No extracted-diagnosis × drug contraindication matcher. (EML *age* restrictions exist; *condition* restrictions do not.) | 🔴 P0 |
| **12. Clinician feedback / validation loop** | Partial — corrections + conflict resolution exist, but no FP/FN/override-rate capture or per-rule performance metrics. | 🔴 P0 |
| **8. Vital-sign longitudinal intelligence** | Absent — `lab_trends.py` is lab-only; BP/HR/SpO₂/weight trends are not analyzed despite vitals being extracted. | 🟠 P1 |
| **7. Patient-reported symptoms → reasoning** | Absent — strictly document-centric; no free-text symptom intake + cross-record synthesis. | 🟠 P1 |
| **4/11. Preventive-care / care-gap + alert-fatigue** | Absent — no screening/immunization gap detection; no alert suppression/dedup/override-reason. | 🟠 P1 |
| **6. Adherence intelligence** | Absent — activity windows exist, but no refill-gap / patient-reported adherence distinction. | 🟡 P2 |
| **9. Early-warning scoring (NEWS-style)** | Absent (high validation burden). | 🟡 P2 |
| **10. Living (auto-updating) guidelines** | Absent — guidance is version-pinned in git, not auto-refreshed. | 🟡 P2 |
| **14b. FHIR ingestion** | Absent (export exists, ingestion does not). | 🟡 P2 |
| **15. Patient-generated health data** | Absent. | 🟡 P2 |
| **16. Secure provider messaging** | Absent (provider discovery exists, messaging does not). | 🟡 P2 |

---

## 4. Corrected priority roadmap (what is actually worth building)

```
🔴 P0 — real clinical-safety depth (none of these exist in any of the 3 repos)
   1. Renal/hepatic patient-specific dosing        (dosage_rules.py currently disclaims this)
   2. Drug–laboratory interaction checking         (connect measured labs to drug effects)
   3. Condition-specific contraindication engine   (extracted diagnosis × drug)
   4. Clinician feedback loop + performance metrics(FP/FN/override capture)

🟠 P1 — longitudinal / patient-facing CDS
   5. Vital-sign trend engine (BP/HR/SpO₂/weight)  (mirror the existing lab_trends design)
   6. Patient symptom intake + cross-record synthesis
   7. Preventive-care / care-gap detection
   8. Alert-fatigue management (suppression/dedup/override-reason)

🟡 P2 — platform maturity
   9.  Authenticated accounts + multi-patient (caregiver) model
   10. FHIR ingestion (export already works)
   11. Full safety-finding lifecycle + metrics (extends existing record_trust)
   12. Adherence intelligence; PGHD; secure messaging; living guidelines
```

### The key correction
The single biggest error in the source roadmap was treating **Repository A's features as
absent from MediMind**. Because A is MediMind's own lineage, all of its "guidance layer,
timing-aware triage, persistent-abnormal referral, extraction-risk referral, AI specialty
routing, and the named drug pairs" are **already in MediMind** — the proof is in
`reference_library.py`, `guidance_kg.py`, `risk_timeline.py`, `consult_triage.py`, and
`drug_interactions.py`. Chasing any of A–G would be re-building what is already there.

The **genuine** opportunity is the P0 cluster: MediMind reasons about *drug × drug*, but
not yet about **drug × kidney, drug × lab-value, or drug × patient-condition** — and its own
`dosage_rules.py` openly documents that limitation. That is the highest-value next step,
and it is a real gap none of the three repositories addresses.
