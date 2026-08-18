# YGC Final Round — Competition Checklist

Derived from the official brief
[`YGC_FINAL_ROUND_RULES.md`](YGC_FINAL_ROUND_RULES.md)
(*AI Medical Report & Prescription Cross-Checker with Local Doctor Recommendation*).

Every required item is implemented. The required flow is:

**detect flag → ask location and availability → call the live API → show results.**

---

## 2. Round 1 baseline (stays as it is)

- [x] **R1** — Extract data from multiple medical documents (lab reports, prescriptions, notes, discharge summaries)
  - `backend/medical_extractor.py`, `backend/document_types.py`, `POST /api/v1/documents`
- [x] **R2** — Merge extracted data into one patient timeline
  - `GET /api/v1/timeline`, History (`/history`)
- [x] **R3** — Cross-check prescriptions for interactions, duplicates, or conflicting dosages
  - `backend/drug_interactions.py`, `backend/dosage_rules.py`, `backend/document_dedup.py`, Safety (`/safety`)
- [x] **R4** — Track lab result trends over time
  - `backend/lab_trends.py`, Test Results (`/labs`)
- [x] **R5** — Explain lab trends in plain language
  - Direction, crossing/recovery badges, and patient-facing copy on `/labs`
- [x] **R6** — Answer follow-up questions across multiple documents
  - `backend/retrieval.py`, `backend/conversation.py`, Ask (`/ask`) and Conversations (`/conversations`)
- [x] **R7** — Give a confidence score for flagged issues
  - `backend/evidence_grading.py`
- [x] **R8** — Recommend consulting a doctor for high-risk or low-confidence cases
  - `recommend_professional_consult` + `consult_reason`; Safety and Care pages

---

## 3. Final Round new feature — Local Doctor Recommendation

- [x] **R9** — Identify the right type of doctor from the flagged issue
  - Heart-related flag → cardiologist; drug interaction → prescribing doctor / pharmacist
  - `backend/specialty_mapping.py`, `backend/consult_triage.py`, `GET /api/v1/care-recommendations`
- [x] **R10** — Ask the user for their location (city/area)
  - Find Local Care (`/care`) + `LocationPicker`
- [x] **R11** — Ask the user for their availability (this week, evenings, etc.)
  - `any` / `today` / `this_week` / `evenings` / `weekends` on `/care`
- [x] **R12** — Search real, publicly available doctors/clinics via Google Maps Places API or a free alternative
  - Google Places API (New): `PROVIDER_DIRECTORY_SOURCE=google_places` / `CARE_PROVIDER=google`
  - Free alternative: OpenStreetMap Nominatim + Overpass (default, no API key)
- [x] **R13** — Result list shows doctor/clinic name, specialty, address, distance, and rating/contact if available
  - `ProviderResultCard` / `FacilityList` — unpublished fields stay “Not available”
- [x] **R14** — If nothing is found, say so clearly and suggest widening the search area (no fake result)
  - Empty `providers` list + `no_results_message`

Straightforward flow only — no agentic planning is required or used.

---

## 4. Data rules

- [x] **R15** — No synthetic or made-up doctor/clinic data. All listings come from a real public source (Google Places, OpenStreetMap/Nominatim, or another public directory).
  - Live directory only. Missing rating/phone/hours stay `null` / “Not available”.
  - Round 1 synthetic/de-identified **medical documents** remain allowed for testing.
- [x] **R16** — The app never presents itself as making a diagnosis. It only flags a possible issue and points the user to a suitable doctor.
  - Disclaimers on landing, Safety, Ask, and Care. Prompts refuse diagnosis.

**Automatic deduction if fabricated doctor/clinic data is shown as real.**

---

## 5. Deliverables

- [x] **R17** — Working application: document upload → flag detected → location and availability asked → doctor list shown
  - `/upload` → `/safety` → `/care`
- [x] **R18** — Working web app link with a short README explaining which API was used and how
  - [README.md](../README.md) documents Google Places API (New) and the OpenStreetMap/Nominatim fallback
  - Deploy: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md)
- [x] **R19** — A short demo (5 minutes) covering the flow above
  - [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) — 4:30 script

---

## 6. Evaluation criteria (how judges score)

| Category | Weight | How MediMind addresses it |
| --- | ---: | --- |
| AI Depth & Use | 30% | Deterministic cross-check (interactions, duplicates, dosage, allergy) plus flag → specialty → live directory. |
| Technical Execution | 30% | Real Google Places / OSM calls; empty and failed API results are explicit, never mocked. |
| Originality & Innovation | 20% | Explainable specialty mapping and ranking (specialty match + distance + hours + rating when published). |
| Usefulness & Impact | 10% | Name, address, distance, phone, and Google Maps link so the patient can actually reach a real local doctor. |
| Presentation & UX | 10% | Demo runbook + on-screen source label (`Live provider data — <source>`) and medical disclaimer. |

---

### 19 items — all complete

See [FEATURES.md](FEATURES.md) for the broader product inventory and
[care_recommendations](../backend/docs/care_recommendations.md) for the
live-directory contract.
