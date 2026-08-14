# MediMind Features

> Checklist status: `[x]` is implemented in the current repository; `[ ]` is pending or not yet verified end to end.

## Visible Features

- Upload → Extract → Timeline → Safety/Labs → Ask AI
- Multilingual document extraction (Tamil/Arabic/etc., INN normalization)
- Non-medical document filter (early rejection before LLM/Chroma)
- Patient timeline + longitudinal lab trends (threshold approach detection)
- Patient-grounded RAG / Ask AI
- English, Sinhala, and Tamil UI with persisted/browser-detected language and locale-aware formatting
- WCAG-oriented keyboard, screen-reader, focus, contrast, reduced-motion, table, chart, form, and responsive-navigation support
- Optional Care Navigation with search-as-you-type, current location, map confirmation, and nearby facility results
- Facility category filters for hospitals, clinics, pharmacies, laboratories, and doctors
- Public listing details including distance, address, rating, phone, website, opening hours, and map link when available

## Hidden / Engineering Features

- Synthetic lab fixture generator `generate_lab_test_data.py`
- Provider-neutral care interface; Google Places API (New) is isolated from the medical layer
- Server-side Google key handling—the browser never receives `GOOGLE_MAPS_API_KEY`
- Coordinate searches use Google Nearby Search; city/area-only legacy clients use Google Text Search
- Google responses normalized to a stable `Facility[]` contract
- Provider-neutral empty and failure responses; provider details and credentials stay in server logs
- Regression tests for Google payloads, normalization, distance ordering, empty results, and neutral API failures
- Regression tests for reference-range formatting + trend direction
- Chroma collection sanitization; confidence-aware extraction
- Early cost-protection gate (reject before downstream AI)

## Differentiators / Novel

- Language-independent medical structure (multilingual → English INN)
- Longitudinal trend intelligence (not just extraction)
- Safety-first AI (interpretation ≠ diagnosis; professional-care cues)
- Provider-decoupled Care Navigation with a server-side Google Places adapter
- Location accuracy through saved latitude/longitude rather than city text alone
- Neutral distance/category presentation with no “best hospital” or clinical referral claim

# Detailed Feature Checklist

## Core Medical Intelligence

### 1. Document Upload

- [x] Upload multiple PDFs.
- [x] Support reports from different visits.
- [x] Support lab reports.
- [x] Support prescriptions.
- [x] Support doctor's notes.
- [x] Support discharge summaries.
- [x] Show uploaded document list.
- [x] Show processing status.
- [x] Handle failed document processing.

### 2. Medical Document Processing

- [x] Extract text from PDFs.
- [x] OCR scanned documents.
- [x] Identify patient information.
- [x] Identify document type.
- [x] Identify doctor/provider.
- [x] Identify visit date.
- [x] Preserve document/page references.
- [x] Handle messy document layouts.

### 3. Structured Medical Extraction

- [x] Extract medication names.
- [x] Extract dosage.
- [x] Extract frequency.
- [x] Extract duration.
- [x] Extract test names.
- [x] Extract test values.
- [x] Extract reference ranges.
- [x] Extract allergies.
- [x] Extract diagnoses/conditions mentioned.
- [x] Extract important clinical notes.

### 4. Patient Timeline

- [x] Merge information from all documents.
- [x] Sort events chronologically.
- [x] Group information by visit.
- [x] Show medications by date.
- [x] Show lab results by date.
- [x] Show allergies/contradictions.
- [x] Allow clicking an event to see its source document.

### 5. Prescription Cross-Checker ⭐

- [x] Detect duplicate medications.
- [x] Detect possible drug interactions.
- [x] Detect conflicting dosages.
- [x] Detect conflicting frequencies.
- [x] Detect medication changes.
- [x] Detect medication continuation.
- [x] Detect allergy–medication conflicts.
- [x] Compare prescriptions across visits.
- [x] Explain why something was flagged.
- [x] Show severity/risk level.
- [x] Show source documents for the flag.

### 6. Lab Trend Analysis ⭐

- [x] Group the same lab test across visits.
- [x] Compare values over time.
- [x] Detect increasing trends.
- [x] Detect decreasing trends.
- [x] Detect abnormal values.
- [x] Detect gradual deterioration.
- [x] Detect improvement.
- [x] Show trend graph.
- [x] Explain trend in simple language.
- [x] Show supporting test dates.

### 7. Multi-Document AI Reasoning ⭐⭐⭐

- [x] Allow questions about all documents.
- [x] Retrieve relevant documents.
- [x] Retrieve relevant pages/chunks.
- [x] Connect information across visits.
- [x] Connect medications with allergies.
- [x] Connect medications with previous prescriptions.
- [x] Connect lab results across time.
- [x] Answer questions using evidence.
- [x] Show source citations.
- [x] Never answer from unsupported information.

### 8. Confidence & Safety ⭐

- [x] Give confidence score to every AI answer.
- [x] Explain why confidence is low.
- [x] Flag high-risk findings.
- [x] Flag low-confidence findings.
- [x] Recommend doctor/pharmacist when appropriate.
- [x] Add medical disclaimer.
- [x] Never claim to diagnose.
- [x] Clearly separate **AI observation** from **medical diagnosis**.

### 9. Dashboard

- [x] Patient overview.
- [x] Medical timeline.
- [x] Medication section.
- [x] Allergy section.
- [x] Lab trends.
- [x] Risk/flag section.
- [x] Document viewer.
- [x] AI chat.
- [x] Confidence indicators.
- [x] Source references.

### 10. AI Architecture ⭐⭐⭐

- [x] PDF extraction pipeline.
- [x] OCR pipeline.
- [x] Structured extraction layer.
- [x] Medical normalization layer.
- [x] Timeline engine.
- [x] Deterministic safety rules.
- [x] RAG/retrieval layer.
- [x] LLM reasoning layer.
- [x] Confidence calculation.
- [x] Evidence/source tracking.

### 11. Robustness

- [x] Handle missing fields.
- [x] Handle unreadable PDFs.
- [x] Handle duplicate documents.
- [x] Handle conflicting information.
- [x] Handle different date formats.
- [x] Handle different medication formats.
- [x] Handle API failures.
- [x] Handle LLM failures.
- [x] Show useful error messages.

### 12. Demo Preparation ⭐⭐⭐

- [ ] Use the **official competition dataset**.
- [x] Upload multiple documents.
- [x] Show extraction.
- [x] Show patient timeline.
- [x] Show a real prescription conflict.
- [x] Show a real lab trend.
- [x] Ask a cross-document question.
- [x] Show confidence score.
- [x] Show source evidence.
- [x] Show doctor/pharmacist warning.
- [x] Finish within 4–5 minutes.

## Care Recommendation and Provider Search

### 1. Detect High-Risk Flag

- [x] Detect high-risk prescription issue.
- [x] Detect low-confidence result.
- [x] Detect allergy conflict.
- [x] Detect serious lab trend.
- [x] Trigger recommendation flow.

### 2. Determine Doctor Specialty ⭐

- [x] Map issue → appropriate specialty.
- [x] Heart issue → cardiologist.
- [x] Drug interaction → prescribing doctor/pharmacist.
- [x] Skin issue → dermatologist.
- [x] Digestive issue → gastroenterologist.
- [x] Blood-related issue → relevant specialist.
- [x] Unknown issue → general physician.
- [x] Explain why the specialty was selected.

### 3. Ask User Location

- [x] Ask user's city/area.
- [x] Allow manual location entry.
- [x] Example: Jaffna.
- [x] Example: Colombo.
- [x] Validate location input.

### 4. Ask Availability

- [x] Ask when user is available.
- [x] This week.
- [x] Today.
- [x] Evening.
- [x] Weekend.
- [x] Store selection for filtering/display.

### 5. Real Doctor/Clinic Search ⭐⭐⭐

- [x] Connect to Google Places API **or** permitted free alternative.
- [x] Search using location.
- [x] Search using required specialty.
- [x] Search real clinics/doctors.
- [x] Do **not** use mock doctor data.
- [x] Do **not** hard-code fake clinics.
- [x] Do **not** fabricate ratings.
- [x] Do **not** fabricate phone numbers.

### 6. Doctor Results

Show:

- [x] Doctor/clinic name.
- [x] Specialty.
- [x] Address.
- [x] Distance.
- [x] Rating if available.
- [x] Contact number if available.
- [x] Map/directions link if available.
- [x] Source/provider information.

### 7. Doctor Ranking ⭐⭐

Instead of simply showing random results:

- [x] Rank by specialty match.
- [x] Rank by distance.
- [x] Consider rating.
- [x] Consider availability if API provides it.
- [x] Explain ranking logic.
- [x] Show top relevant results first.

### 8. No-Result Handling

- [x] Detect zero results.
- [x] Tell user no suitable result was found.
- [x] Never create fake results.
- [x] Suggest expanding search area.
- [x] Allow user to change location.
- [x] Allow broader specialty search.

### 9. Safety

- [x] Say this is **not a diagnosis**.
- [x] Say the AI detected a potential issue.
- [x] Recommend professional consultation.
- [x] Don't tell user to start/stop medication.
- [x] Don't claim a doctor is medically suitable beyond specialty matching.
