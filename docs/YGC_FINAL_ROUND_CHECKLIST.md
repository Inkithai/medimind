# YGC Final Round — Competition Checklist

Official Young Global Changers final-round requirements, mapped to what MediMind
ships. Every item is implemented. Evidence lives in the cited modules; the
end-to-end path is **upload → flag → location + availability → live doctor list**.

---

## ROUND 1 BASELINE (Must Already Be Built)

- [x] **R1** — Extract data from multiple medical documents (lab reports, prescriptions, notes, discharge summaries)
  - `backend/medical_extractor.py`, `backend/document_types.py`, `POST /api/v1/documents`
- [x] **R2** — Merge extracted data into one unified patient timeline
  - `GET /api/v1/timeline`, History page (`/history`)
- [x] **R3** — Cross-check prescriptions for interactions, duplicates, or conflicting dosages
  - `backend/drug_interactions.py`, `backend/dosage_rules.py`, `backend/document_dedup.py`, Safety page (`/safety`)
- [x] **R4** — Track lab result trends over time
  - `backend/lab_trends.py`, Test Results page (`/labs`)
- [x] **R5** — Explain lab trends in plain language
  - Trend direction, crossing/recovery badges, and patient-facing copy on `/labs`
- [x] **R6** — Answer follow-up questions across multiple documents
  - `backend/retrieval.py`, `backend/conversation.py`, Ask (`/ask`) and Conversations (`/conversations`)
- [x] **R7** — Give a confidence score for flagged issues
  - `backend/evidence_grading.py`; safety findings carry a graded confidence
- [x] **R8** — Recommend consulting a doctor for high-risk or low-confidence cases
  - `recommend_professional_consult` + `consult_reason` on Q&A; Safety and Care pages

---

## FINAL ROUND NEW FEATURE (Must Be Newly Developed)

- [x] **R9** — Identify the right type of doctor based on the flagged issue (specialty matching)
  - `backend/specialty_mapping.py`, `backend/consult_triage.py`, `GET /api/v1/care-recommendations`
- [x] **R10** — Ask the user for their location (city/area)
  - Find Local Care (`/care`) location field + reusable `LocationPicker`
- [x] **R11** — Ask the user for their availability for consultation
  - Availability preference (`any` / `today` / `this_week` / `evenings` / `weekends`) on `/care`
- [x] **R12** — Search real, publicly available data using Google Maps Places API or a free alternative (OpenStreetMap/Nominatim)
  - Google Places API (New) via `PROVIDER_DIRECTORY_SOURCE=google_places` / `CARE_PROVIDER=google`
  - Free alternative: OpenStreetMap Nominatim + Overpass (default, no API key)
- [x] **R13** — Display a result list showing: doctor/clinic name, specialty, address, distance, and rating/contact number
  - `ProviderResultCard` / `FacilityList` — name, specialty, address, distance, rating, phone when the source published them
- [x] **R14** — Handle no-results gracefully: clear message + suggest widening the search area (no fake results)
  - Empty `providers` list + `no_results_message`; never fabricates clinicians

---

## DATA RULES

- [x] **R15** — All doctor/clinic data must come from a real public source (no synthetic or fabricated data)
  - Live Google Places or OpenStreetMap only. Missing rating/phone/hours stay `null` / “Not available”.
- [x] **R16** — App must never present itself as making a diagnosis
  - Disclaimer on landing, Safety, Ask, and Care. Prompts refuse diagnosis. Findings are observations to review with a clinician.

---

## DELIVERABLES

- [x] **R17** — Working application demonstrating the full end-to-end flow: upload → flag → location asked → doctor list shown
  - `/upload` → `/safety` → `/care` (flag + specialty → city + availability → live list)
- [x] **R18** — Working web app link with a README explaining which API was used and how
  - Root [README.md](../README.md) documents Google Places API (New) and the OpenStreetMap/Nominatim fallback. Deploy: [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md).
- [x] **R19** — A short demo (5 minutes) covering the full flow
  - [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) — 4:30 script covering upload, history, safety, labs, Ask, and Find Care.

---

### 19 ITEMS — ALL COMPLETE

- 8 Round 1 baseline requirements
- 6 Final Round new feature requirements
- 2 Data rules
- 3 Deliverables

See [FEATURES.md](FEATURES.md) for the broader product inventory and [care_recommendations](../backend/docs/care_recommendations.md) for the live-directory contract.
