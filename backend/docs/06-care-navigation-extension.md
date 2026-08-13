# Optional extension — Care Navigation (not in this branch)

**Do not put this on the main judging slides.**  
The frozen deck is still [01-end-to-end-pipeline.md](01-end-to-end-pipeline.md):

> **Understand → Detect → Explain → Protect**

This page is the **future / architecture** story only: a fifth capability, **Connect**, that must stay decoupled from medical intelligence.

There is no Care Navigation code in this tree. If it is built, it belongs on another branch and must not rewrite Upload → Timeline → Ask AI.

---

## Plan: new architecture, old core product flow

```text
                MEDIMIND
                   │
                   ▼
       Understand → Detect
              → Explain
              → Protect
                   │
                   ▼
          Patient Intelligence
                   │
          ┌────────┴────────┐
          │                 │
       Ask AI          Optional
                     Care Navigation
```

**Main demo (unchanged):**

```text
Upload
  ↓
Extract
  ↓
Patient Timeline
  ↓
Safety + Lab Trends
  ↓
Ask AI
```

**Architecture / future slide only:**

```text
                    MediMind
                       │
          ┌────────────┴────────────┐
          │                         │
 Medical Intelligence        Care Navigation
          │                         │
 Timeline / Safety / Labs     Facility Search
 RAG / Ask AI                Geocoding / Routing
          │                         │
          └────────────┬────────────┘
                       │
              Provider abstraction
                       │
             OSM / Mapbox / etc.
```

Do **not** rebuild MediMind around maps. Maps must not appear on the Understand / Detect / Explain / Protect slide.

---

## Why a separate module

Wrong:

```text
MediMind
   ├── Google Maps
   ├── Geoapify
   ├── OSM
   └── Leaflet
```

Right:

```text
MediMind
│
├── Medical Intelligence
│   ├── Extraction
│   ├── Timeline
│   ├── Safety
│   ├── Labs
│   └── Ask AI
│
└── Care Navigation
    ├── Facility Search
    ├── Geocoding
    ├── Distance
    ├── Routing
    └── Maps UI
```

Care Navigation **consumes** structured patient context. It is not another intelligence module and it does not diagnose.

---

## Provider-independent service

The app must not call a maps vendor from domain logic or from page components.

```text
CareNavigationService
        │
        ├── searchFacilities()
        ├── geocode()
        ├── calculateDistance()
        └── getRoute()
```

Adapters behind that contract:

```text
CareNavigationService
        │
        ├── OSMProvider
        ├── MapboxProvider
        ├── GoogleProvider
        └── GeoapifyProvider
```

```text
"Find hospitals near me"
        ↓
CareNavigationService
        ↓
FacilitySearchProvider
        ↓
provider API
        ↓
normalized Facility[]
```

The frontend never sees a provider-specific API.

---

## Four geospatial capabilities (keep them separate)

“Maps API” is not one thing.

| Capability | Responsibility | Typical tool |
|---|---|---|
| **Map rendering** | tiles, markers, pan, zoom | Leaflet / MapLibre / Mapbox |
| **Geocoding** | “Teaching Hospital Jaffna” → lat/lng | geocoder adapter |
| **Facility / POI search** | nearby hospitals, clinics, labs, pharmacies | places adapter |
| **Routing** | walk / drive distance and ETA | routing adapter |

A rendering library is not a search source. A Places API is not a map.

---

## Product flow if this is ever built

Not: Dashboard → map → random hospitals.

```text
Patient Snapshot
       ↓
Safety / Labs / History
       ↓
Need professional evaluation?
       ↓
Find Care   (user chooses to look)
       ↓
Choose facility type
       ↓
Nearby facilities
       ↓
Distance + basic directory information
       ↓
External navigation / contact
```

AI explains the record. Care Navigation finds facilities. Those stay separate.

Avoid: “AI recommends the best hospital.”  
Say: **MediMind helps the patient find relevant nearby facilities for a need they selected.**

```text
Lab trend detected
      ↓
Value was outside the reference range
      ↓
Consider discussing this with a healthcare professional
      ↓
Optional: Find nearby healthcare facilities
```

---

## Suggested shape (other branch only)

```text
backend/
├── medical/          # existing core — do not fold maps into this
└── care/
    ├── service.py
    ├── models.py
    ├── normalizer.py
    └── providers/
        ├── base.py
        ├── osm.py
        ├── mapbox.py
        └── google.py
```

```text
GET /api/v1/care/facilities
GET /api/v1/care/geocode
GET /api/v1/care/routes
```

Frontend:

```text
FindCarePage
     ├── FacilityFilters
     ├── FacilityList
     └── MapView → MapAdapter
```

Swap MapLibre for Mapbox by changing the adapter, not the page.

---

## If time is short

For a competition demo: **provider abstraction + a minimal facility-search prototype** only. Keep full map / routing off the judging flow.

The line to remember:

> New architecture, old core product flow. Care Navigation is a decoupled extension, not a rewrite of MediMind.
