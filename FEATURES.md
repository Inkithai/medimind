# MediMind Features

## Visible Features

- Upload → Extract → Timeline → Safety/Labs → Ask AI
- Multilingual document extraction (Tamil/Arabic/etc., INN normalization)
- Non-medical document filter (early rejection before LLM/Chroma)
- Patient timeline + longitudinal lab trends (threshold approach detection)
- “What Changed?” comparison across consecutive records, with before/after values and source evidence
- Conservative medication change semantics: newly documented is never mislabeled as started, and omission is never treated as stopped
- Appointment Prep: printable clinician handoff, prioritized questions, source evidence, and visit checklist
- Record Integrity: source-linked identity, allergy, same-date lab, and medication-instruction discrepancy checks
- Intent-routed Ask AI with category-targeted retrieval, citation validation, and explicit evidence sufficiency
- Patient-grounded RAG / Ask AI
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
- Deterministic, citation-backed change detection across labs, medication instructions, and allergies
- Clinical action layer that converts safety findings and trends into record-grounded appointment questions
- Contradiction-aware record integrity workflow that shows both sources and never silently chooses a winner
- Deterministic question-intent routing and evidence-coverage gates before generative answering
- Safety-first AI (interpretation ≠ diagnosis; professional-care cues)
- Provider-decoupled Care Navigation with a server-side Google Places adapter
- Location accuracy through saved latitude/longitude rather than city text alone
- Neutral distance/category presentation with no “best hospital” or clinical referral claim

## Round 1 (Core System — Verified)

- [x] Multi-document extraction
- [x] Patient timeline
- [x] Prescription interaction checking
- [x] Duplicate medication detection
- [x] Dosage conflict detection
- [x] Lab trend analysis
- [x] Plain-language explanations
- [x] Multi-document Q&A
- [x] Confidence scoring
- [x] High-risk/low-confidence detection

## Round 2 (Care Navigation — Added)

- [x] Detect appropriate specialty
- [x] Ask user's city/area
- [x] Search-as-you-type location suggestions
- [x] “Use my current location” fallback
- [x] Confirm or adjust the location on a map
- [x] Save and send latitude/longitude
- [x] Ask user's availability
- [x] Connect to Google Places API (New) through the backend
- [x] Keep the Google Maps API key server-side
- [x] Search based on coordinates, radius, and facility type
- [x] Support city/area-only legacy searches through Google Text Search
- [x] Match results to specialty
- [x] Rank/filter results (distance/category neutral, no “best” claim)
- [x] Show real provider info through normalized `Facility[]`
- [x] Handle zero results (empty list + message)
- [x] Handle API failure (provider-neutral error; key hidden)
- [x] Clearly indicate source (public listings; not a MediMind recommendation)
- [x] Medical disclaimer (directory extension; not clinical referral)
