# MediMind Features

Official Young Global Changers final-round status: **19 / 19 complete**. See
[`YGC_FINAL_ROUND_CHECKLIST.md`](YGC_FINAL_ROUND_CHECKLIST.md).

## Visible Features

- Upload → Extract → Timeline → Safety/Labs → Ask AI
- Multilingual document extraction (Tamil/Arabic/etc., INN normalization)
- Non-medical document filter (early rejection before LLM/Chroma)
- Patient timeline + longitudinal lab trends (threshold approach detection)
- Deterministic medication-allergy contraindication KB — normalized ingredients matched in code against recorded allergies (allergen classes + direct ingredient names), so "amoxicillin prescribed; penicillin allergy on record" is caught even when the model misses it
- Active-prescription scoping — interaction/allergy/duplicate/dosage checks run only against courses still active at the reference date; provably ended courses are listed with reasons, never silently dropped, and the LLM pass is skipped entirely when nothing is active
- Dosage checks beyond mg — g/mcg converted exactly; tablet, mL and IU doses converted via documented standard strengths/exact factors with the assumption stated and a lower confidence; unconvertible doses reported "not evaluated"
- Strict trend-value classification — censored/approximate/tolerance/scientific-notation lab readings are excluded from trend math rather than estimated, so a fabricated magnitude can never invert a trend direction
- WHO antidote/poisoning reference knowledge graph — deterministic (non-LLM) ingestion of the WHO EML "Antidotes and other substances used in poisonings" section into Neo4j (adult EML + children's EMLc kept as independent listings), per-upload medication lookup, patient-facing reference notes, and reference-graph evidence grading that uncaps confidence on findings about WHO-listed antidotes
- Referral trail — every local-care search is persisted as a reviewable finding → specialty → search → providers record, with the referral reason (why the finding produced this referral) and a numeric per-provider ranking breakdown (signal weights, scores, contributions) so both stay answerable after the live results age out
- Offline Tesseract OCR pre-pass — scanned PDFs/images are OCR'd when the engine is installed; a confident transcript is extracted with the cheaper text model (zero image tokens), otherwise the vision model runs unchanged; per-page OCR confidence is recorded and OCR can never block an extraction
- Document-type normalization — the extractor's free-form type is pinned to the closed vocabulary (prescription / lab_report / discharge_summary / consultation_note / imaging_report / procedure_report / other) before persistence, with per-record type distributions in the API
- Magic-byte upload validation — a supported extension whose content is not actually that file type is rejected per-file (never aborts the batch) before it costs an extraction call
- Per-document reprocess — POST /documents/{id}/reprocess re-fetches the stored original, re-extracts it, replaces the file's rows, and rebuilds timeline/safety/labs/dosage/triage/index like an upload; failed documents no longer need re-uploading
- Patient-grounded RAG / Ask AI with conversational focus carry-over
- Risk Timeline page — when each safety finding was actually live, graded by evidence strength
- Duplicate re-upload detection — the same file or prescription is never counted twice

- Evidence-linked longitudinal diagnoses, symptoms, procedures, vital signs, and imaging results
- Event-specific chronology that separates a historical event date from the source document date
- “What Changed?” comparison across consecutive records, with before/after values and source evidence
- Conservative medication change semantics: newly documented is never mislabeled as started, and omission is never treated as stopped
- Appointment Prep: printable clinician handoff, prioritized questions, source evidence, and visit checklist
- Record Integrity: source-linked identity, allergy, same-date lab, and medication-instruction discrepancy checks
- Intent-routed Ask AI with category-targeted retrieval, citation validation, and explicit evidence sufficiency
- Action Center with grounded follow-up tasks, user-chosen browser reminders, completion tracking, and calendar export
- Patient-grounded RAG / Ask AI
- Persistent field-level extraction corrections with immutable original values and audit history
- Conflict review workflow for identity, medication instructions, lab values, and document dates
- Fail-closed evidence quarantine across RAG, timelines, lab trends, safety, and care analytics
- Source-confirmed rebuilds of snapshots, trends, safety checks, and vector indexes
- Evidence hierarchy using verification, source type/method, confidence, recency, and semantic relevance
- Page-level “View evidence” links for document facts, medicines, labs, allergies, and clinical notes
- Exact normalized highlight overlays for matched digital-PDF text and vision-extracted image regions
- Evidence-rich Q&A citations with verbatim quotes and deep links to the source highlight
- Truthful page/quote or page-only fallback when exact geometry cannot be established
- English, Sinhala, and Tamil UI with persisted/browser-detected language and locale-aware formatting
- WCAG-oriented keyboard, screen-reader, focus, contrast, reduced-motion, table, chart, form, and responsive-navigation support
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
- Curated medication-allergy KB runs alongside the LLM cross-check with fail-open semantics — a KB failure never takes down the report, and findings self-tag `source: curated_knowledge_base` so evidence grading treats them as deterministic (uncapped confidence)
- Allergy-text resolution recognizes negative statements ("no known drug allergies") while still matching named exceptions ("…except penicillin")
- Activity windows reuse `risk_timeline.build_treatment_windows` — activity and concurrency can never disagree; open-ended/PRN/undated courses stay active (fail active, never fail silent)
- Older snapshots without `medication_activity` are backfilled deterministically on read (no LLM call), mirroring the lab-trends recompute pattern
- WHO antidote graph is optional and fail-open: unconfigured/missing NEO4J_* env never blocks uploads, endpoint ingestion requires auth, `POST /api/v1/knowledge-graph/antidotes` ingests a WHO EML PDF deterministically (pdfplumber table parsing — no LLM, nothing to hallucinate)
- Antidote lookup is one bulk round trip per record, reused for both evidence grading and patient-facing notes; per-listing properties live on `:LISTED_IN` edges so adult EML and children's EMLc coexist without overwriting each other
- Neo4j observability: step/completion/retry logging, redacted URIs, MERGE write counters distinguish "re-ingest changed nothing" from "load matched nothing"; driver connection-lifetime/liveness tuning for idle-pooled cloud instances
- Referral-trail persistence is best-effort: a missing/unavailable referrals table never fails the live provider search; persisted trails are historical records OF searches (provenance + retrieved_at), never a provider directory
- Ranking disclosure is numeric and additive: each provider's `ranking.components` lists signal weight, 0-1 score, and contribution to the 0-100 match score alongside the existing plain-language explanations
- OCR layer fails open: engine absence, low confidence, or non-medical reads all fall back to the vision path; a transcript is only trusted above MEDIMIND_OCR_MIN_CONFIDENCE with real text volume
- OCR evidence quotes are attributed to their source page from the transcript (whitespace-tolerant, `ocr_text_search` locator, no fabricated geometry); malformed Tesseract rows degrade to unreadable instead of crashing
- Reprocess replaces every row sharing the file's content hash (multi-page docs are one physical file), preserves the stored document URL/identity, and replays corrections/conflicts through the standard trust-state rebuild
- Chroma collection sanitization; confidence-aware extraction
- Early cost-protection gate (reject before downstream AI)

## Differentiators / Novel

- Language-independent medical structure (multilingual → English INN)
- Longitudinal trend intelligence (not just extraction)
- Deterministic, citation-backed change detection across labs, medication instructions, and allergies
- Clinical action layer that converts safety findings and trends into record-grounded appointment questions
- Contradiction-aware record integrity workflow that shows both sources and never silently chooses a winner
- Deterministic question-intent routing and evidence-coverage gates before generative answering
- Follow-up intelligence that prioritizes record-backed work without inventing clinical deadlines
- Safety-first AI (interpretation ≠ diagnosis; professional-care cues)
- Provider-decoupled Care Navigation with pluggable server-side adapters (Google Places, OpenStreetMap) and graceful degradation between them
- Location accuracy through saved latitude/longitude rather than city text alone
- Neutral distance/category presentation with no “best hospital” or clinical referral claim

## Pending / Next Build Priorities

### Priority 0 — Trust and correction

- [ ] Persisted extraction correction with audit history
- [ ] Explicit discrepancy resolution: select/confirm a source without deleting evidence
- [ ] Rebuild timelines, analytics, and vector indexes after an approved correction
- [ ] Quarantine unresolved identity/fact conflicts from trends and Q&A
- [ ] Page-level and region-level evidence highlighting for extracted facts and answer claims
- [ ] Evidence hierarchy / source-quality ranking beyond extraction confidence

### Priority 1 — Data governance and clinical breadth

- [ ] Full structured-data/file export and server-side workspace deletion
- [ ] Retention controls, account recovery, and optional multi-device access
- [ ] Diagnoses, symptoms, procedures, vitals, and imaging longitudinal tracking
- [ ] Validated terminology and unit normalization (for example RxNorm/LOINC/SNOMED-aligned mappings where appropriate)
- [ ] Medication + lab + diagnosis cross-analysis after clinical validation
- [ ] Formal clinical evaluation set, audit logging, monitoring, and security/privacy assessment

### Priority 2 — Care coordination

- [ ] Consented, expiring clinician handoff links
- [ ] Optional push/email reminders; current reminders are browser/calendar only
- [ ] Verified provider availability and booking integration; current Find Care is a public directory
- [ ] Multilingual patient UI and accessibility evaluation beyond multilingual extraction

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
- [x] English, Sinhala, and Tamil UI catalogs with persistence and locale formatting
- [x] WCAG-oriented keyboard and screen-reader interaction across the existing UI
- [ ] Official competition dataset integration (intentionally left unchanged)

### Ask AI groundedness & safety

- [x] Citations validated server-side — a source the model invents is dropped, never shown
- [x] Page numbers attached from retrieved chunk metadata, never guessed by the model
- [x] An answer with no verifiable source cannot claim high confidence (capped at 0.5)
- [x] Clickable citations open the exact source document (and page) behind a claim
- [x] Prompt-injection defence: retrieved documents are fenced and treated as data, not instructions
- [x] Refuses to diagnose, or to advise starting/stopping/changing a dose
- [x] States plainly when something is not in the records instead of inventing it
- [x] Empty/whitespace/oversized questions rejected before reaching the model
- [x] Double-submit guard — rapid Ask clicks issue exactly one request
- [x] Friendly error copy for 401/422/429/500/502/offline, with technical detail collapsible
- [x] Suggested questions fill the box for editing instead of auto-sending

## Round 3 (Trust and Correction — Added)

- [x] Keep source extraction rows immutable
- [x] Append field-level correction events with original, previous, and corrected values
- [x] Correct patient/provider identity, date, medication, and lab fields in the document UI
- [x] Detect deterministic identity, same-date medication/lab, and same-file date conflicts
- [x] Select and audit an authoritative source; reopen decisions when needed
- [x] Quarantine unresolved/non-authoritative facts from all derived clinical views
- [x] Replace stale vector chunks after corrections and source decisions
- [x] Fingerprint indexes so Q&A self-heals rather than searching stale evidence
- [x] Rank retrieved context by semantic relevance and evidence quality

## Round 4 (Page-level Evidence — Added)

- [x] Extract a source page, verbatim quote, confidence, and optional region for each supported fact
- [x] Normalize all public boxes to `[left, top, right, bottom]` coordinates in the `0..1` range
- [x] Deterministically locate digital-PDF quotes with PyMuPDF rather than trusting model geometry
- [x] Remap per-page vision boxes to original scanned-PDF page numbers
- [x] Preserve stable evidence IDs and correction/conflict annotations through persistence reloads
- [x] Carry evidence IDs, pages, quotes, and serialized boxes through vector metadata
- [x] Server-normalize Q&A source locations against retrieved chunks
- [x] Link Q&A citations and structured facts to the original document highlight
- [x] Fall back to a quote/page or page-only locator without fabricating a rectangle

## Round 5 (Longitudinal Clinical Events — Added)

- [x] Extract documented diagnoses without inferring them from symptoms, medicines, labs, vitals, or imaging
- [x] Extract symptoms/signs, procedures, raw vital measurements, and imaging findings/impressions
- [x] Preserve event-specific dates independently from the enclosing document date
- [x] Build trusted chronological rollups for all five clinical event classes
- [x] Attach page-level evidence to every event and deep-link timeline rows to the highlight
- [x] Index each event as a separate evidence-ranked Q&A chunk
- [x] Extend append-only correction/audit workflows to all supported event fields
- [x] Quarantine conflicting vital values at the same explicitly recorded time
- [x] Keep legacy documents API-compatible with dynamically added empty event arrays
- [x] Avoid claiming validated terminology or unit normalization; retain source wording and units

## Round 3 (Intelligence hardening — Added)

- [x] Entity focus carry-over — deterministic per-session `focus` (medications/labs/documents under discussion) matched against the patient's own record vocabulary, so "what if I take it with this?" stays anchored even if the LLM rewrite fails
- [x] Richer QA response contract — `cross_document`, `low_confidence`, `consult_reason` flags; deterministic guard forces `recommend_professional_consult=true` on risk/allergy/dosage questions; `sources` enriched in code with `document_type` + `document_url`
- [x] Document deduplication — byte-for-byte re-uploads (`CBC_Report.pdf` / `CBC_Report (1).pdf`) skipped before extraction via `content_sha256`; same-prescription grouping (`prescription_group`) keeps duplicate detection counting prescriptions, not files
- [x] Risk timeline + evidence grading — chronological risk view (`GET /api/v1/risk-timeline`) separating live risks from courses that never overlapped; every finding graded `deterministic` vs `model_knowledge` with ungrounded confidence capped at 0.6

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
- [x] Single normalized facility-type mapping shared by counts, filters, and cards
- [x] Each card shows the real provider name, ⭐ rating + review count, type, address, phone, hours/open status, and distance
- [x] "Open in Google Maps" and "Call" actions on every result (Call only for real numbers)
- [x] Explicit "Not available" fallbacks — ratings, phones, hours, and names are never fabricated
- [x] Results overview map with numbered pins matching the card order
- [x] Suggested specialty pre-applied from extracted records, with keyword → specialty → verification reasoning
- [x] Named two-step location flow with location provenance (current / searched / pinned / saved)
- [x] Keyboard-movable map pin plus a text equivalent of the selected location
- [x] User-facing copy centralised in `frontend/src/i18n/` (no hardcoded strings in components)
