# MediMind Features

## Visible Features
- Upload → Extract → Timeline → Safety/Labs → Ask AI
- Multilingual document extraction (Tamil/Arabic/etc., INN normalization)
- Non-medical document filter (early rejection before LLM/Chroma)
- Patient timeline + longitudinal lab trends (threshold approach detection)
- Patient-grounded RAG / Ask AI
- Optional Care Navigation (facility search via provider abstraction)

## Hidden / Engineering Features
- Synthetic lab fixture generator (`generate_lab_test_data.py`)
- Provider abstraction (Google/OSM/Mapbox) — medical layer unaware
- Regression tests for reference-range formatting + trend direction
- Chroma collection sanitization; confidence-aware extraction
- Early cost-protection gate (reject before downstream AI)

## Differentiators / Novel
- Language-independent medical structure (multilingual → English INN)
- Longitudinal trend intelligence (not just extraction)
- Safety-first AI (interpretation ≠ diagnosis; professional-care cues)
- Provider-decoupled Care Nav (Google Places via provider adapter)

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
- [x] Ask user's availability
- [x] Connect to real provider API (Google Places)
- [x] Search based on location
- [x] Match results to specialty
- [x] Rank/filter results (provider-neutral, no "best" claim)
- [x] Show real provider info (normalized Facility[])
- [x] Handle zero results (empty list + message)
- [x] Handle API failure (provider-neutral error; key hidden)
- [x] Clearly indicate source (public listings; not MediMind recommendation)
- [x] Medical disclaimer (optional extension; not clinical referral)
