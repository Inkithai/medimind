# Live Local Care Recommendations

This Round 2 extension reuses the saved MediMind patient snapshot. It does not
replace extraction, timeline, safety, trends, RAG, authentication, or storage.

```text
patient snapshot
  → deterministic clinical_flags.py
  → specialty_mapping.py
  → authenticated city/availability request
  → provider_sources.py (live source only)
  → provider_normalizer.py
  → provider_ranking.py
  → React Find Local Care page
```

## Activation boundary

`clinical_flags.py` reads the existing `patient_timeline`,
`cross_check_report`, and `lab_trends` snapshot fields. It unlocks the search
only for:

- an existing interaction explicitly marked `high` by the Round 1 safety
  report;
- an existing allergy conflict; or
- an extraction/safety/lab/trend result with confidence below `0.60`.

The module never diagnoses a condition. It labels the source of the flag and
shows the exact evidence used to select a provider category.

## Specialty matching

`specialty_mapping.py` maps medication safety issues to **Pharmacist /
prescribing doctor**. For low-confidence record evidence it uses explicit,
reviewable term matches to select cardiology, nephrology, pulmonology,
neurology, or dermatology. Ambiguous evidence uses **General Physician**.

The mapping chooses a directory search category; it is not a diagnosis. The live-directory request receives only the selected generic category (for example, `cardiologist` or `pharmacy`) and the user-entered city/area—not raw document text, patient names, medications, lab values, or safety explanations.

## Live data sources

No doctor, clinic, address, rating, phone number, or provider record is stored
in code, tests, seed data, or a local JSON file.

Select the source in backend environment variables:

### Google Places — preferred

```ini
PROVIDER_DIRECTORY_SOURCE=google_places
GOOGLE_PLACES_API_KEY=...
```

The backend geocodes the city/area then calls Google Places Text Search. The
field mask asks only for name, address, coordinates, rating/count, phone,
regular/current hours, map URI, and source types. The browser never receives
the key.

### OpenStreetMap — public alternative

```ini
PROVIDER_DIRECTORY_SOURCE=openstreetmap
OSM_NOMINATIM_USER_AGENT=MediMind/1.0 (contact: support@example.com)
```

The backend uses Nominatim only to geocode the city/area and Overpass to obtain
nearby source records tagged as doctor/clinic/hospital/pharmacy. Configure a
meaningful User-Agent and comply with the live services' current usage policies
and rate limits. MediMind spaces public OSM requests process-wide using
`OSM_MIN_REQUEST_INTERVAL_SECONDS` (default one second) and identifies the
source as OpenStreetMap data. OSM often has sparse specialty, ratings, hours, and contact
metadata; omitted fields remain omitted in the UI.

## API

All routes require the established `Authorization: Bearer <jwt>` plus
`X-User-Id` headers.

- `GET /api/v1/care-recommendations` — current eligible clinical flags and
  specialty rationale. Each flag now has additive `pathway_evidence` and
  `care_route_explanation` fields built deterministically from the same saved
  patient snapshot. It does not call an external directory.
- `POST /api/v1/care-recommendations/search` — retains all existing live
  provider fields and also returns the selected flag's `evidence` list and
  `care_route_explanation`. These clinical-evidence fields are resolved before
  the live source is queried and never contain provider-directory data.

```json
{
  "flag_id": "interaction-0",
  "location": "Negombo",
  "availability": "weekends"
}
```

`availability` accepts `any`, `today`, `this_week`, `evenings`, or `weekends`.

The selected-flag search response also includes an additive `consultation_pack`.
It is constructed deterministically from the same patient's saved timeline,
cross-check report, lab trends, and Phase 1 source-linked evidence. It contains
only relevant documents, medication records to discuss, relevant allergies/lab
points, low-confidence items, safe clinician-discussion templates, and a
medical disclaimer. It never contains provider ratings, hours, or other
provider-directory data.

Responses label provenance as `Live provider data — <source>`. When no source
records match, the API returns an empty `providers` list plus a clear
`no_results_message`; it never manufactures fallback providers.

## Ranking

Ranking is explained per result and uses only legitimate data:

1. specialty relevance from source-returned provider type/specialty/name;
2. calculated distance from source-returned coordinates and geocoded search
   origin;
3. source-returned rating, only if present; and
4. regular opening-hours information, only if present and safely interpretable
   for the requested preference.

Opening hours are not appointment availability. Missing metadata does not get
invented or displayed.

## Failures

The source client maps configuration errors, timeouts, rate limits, invalid
responses, network failures, and service failures into structured HTTP errors:

- `provider_configuration_missing` / `provider_configuration_invalid` → 503
- `provider_timeout` → 504
- `provider_rate_limited` → 429
- `provider_network_error` / `provider_service_unavailable` → 503
- `provider_invalid_response` / `provider_request_failed` → 502

The frontend uses the existing `ApiError` / `ErrorState` path to show failures
without replacing results with sample data.
