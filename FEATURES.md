# MediMind Features

## Visible Features

- Upload → Extract → Timeline → Safety/Labs → Ask AI
- Multilingual document extraction (Tamil/Arabic/etc., INN normalization)
- Non-medical document filter (early rejection before LLM/Chroma)
- Patient timeline + longitudinal lab trends (threshold approach detection)
- Patient-grounded RAG / Ask AI
- Care Navigation with search-as-you-type, current location, map confirmation, and nearby facility results — works with no API key or billing account
- Facility category filters for hospitals, clinics, pharmacies, laboratories, and doctors
- Public listing details including distance, address, rating, phone, website, opening hours, and map link when available
- High-accuracy GPS capture that refines the fix before use, shows its margin of error, and asks for a pin correction when the reading is coarse
- Sticky desktop sidebar that stays in view on long pages

## Hidden / Engineering Features

- Synthetic lab fixture generator `generate_lab_test_data.py`
- Provider-neutral care interface; Google Places API (New) and OpenStreetMap/Overpass are both isolated from the medical layer
- Keyless-by-default directory: OpenStreetMap/Overpass needs no API key, billing, or cloud project
- Automatic provider fallback—a Google rejection or empty result silently degrades to OpenStreetMap instead of a 503
- Overpass mirror failover across multiple public endpoints
- Server-side Google key handling—the browser never receives `GOOGLE_MAPS_API_KEY`
- Coordinate searches use Google Nearby Search; city/area-only legacy clients use Google Text Search, and OpenStreetMap geocodes area text before querying
- Every provider's response normalized to one stable `Facility[]` contract
- Provider-neutral empty and failure responses; provider details and credentials stay in server logs
- Regression tests for Google payloads, OpenStreetMap tags, normalization, distance ordering, mirror failover, provider fallback, empty results, and neutral API failures
- Geolocation refinement via watchPosition with best-fix retention, early exit at 30 m, and best-effort return on timeout
- Reverse geocoding used for naming only—device coordinates are never overwritten by a feature centroid
- Regression tests for GPS refinement, cache avoidance, permission/timeout handling, and accuracy labelling
- Regression tests for reference-range formatting + trend direction
- Chroma collection sanitization; confidence-aware extraction
- Early cost-protection gate (reject before downstream AI)

## Differentiators / Novel

- Language-independent medical structure (multilingual → English INN)
- Longitudinal trend intelligence (not just extraction)
- Safety-first AI (interpretation ≠ diagnosis; professional-care cues)
- Provider-decoupled Care Navigation with pluggable server-side adapters (Google Places, OpenStreetMap) and graceful degradation between them
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
- [x] Keyless OpenStreetMap/Overpass adapter as the default and as a fallback
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
