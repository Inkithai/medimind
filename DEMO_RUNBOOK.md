# MediMind 4–5 Minute Demo Runbook

Target duration: **4 minutes 30 seconds**. The official competition dataset is intentionally not stored in this repository; load it into the private workspace before the demo.

| Time | Duration | Action | Evidence to show |
|---|---:|---|---|
| 0:00 | 0:30 | Introduce the anonymous workspace and safety disclaimer. | No account; observations are not diagnoses. |
| 0:30 | 1:00 | Upload the prepared multi-document competition case. | Independent per-file progress, extraction, failures if any. |
| 1:30 | 0:45 | Open History and one source document. | Visits in date order, diagnoses/conditions, page traceability. |
| 2:15 | 0:45 | Open Safety. | Interaction/allergy flag, medication change/continuation, severity, confidence, source pages. |
| 3:00 | 0:35 | Open Lab Trends. | Graph, abnormal crossing, risk level, supporting dates. |
| 3:35 | 0:35 | Ask one cross-document question. | Grounded answer, confidence reason, citations, professional warning. |
| 4:10 | 0:20 | Select Find Care. | Triggered specialty reason, availability, real Google listings, transparent ranking. |

## Before presenting

1. Configure the LLM, Supabase, Cloudinary, and Google Places API (New).
2. Set `USE_BACKGROUND_JOBS=true` and keep the provider quota appropriate for the document count.
3. Upload and validate the official competition case once in a disposable workspace.
4. Confirm the case contains a genuine prescription issue and at least two dated values for one lab test.
5. Confirm Google Places returns real listings for the selected location; never substitute mock providers.
6. Start a fresh anonymous workspace and keep the prepared files in one folder for a single multi-select upload.
7. Use a stopwatch. If extraction takes longer than the one-minute upload segment, explain independent background progress and continue with the prevalidated workspace rather than fabricating a result.

## Safety script

> MediMind found a potential issue in the uploaded records. This is an AI observation, not a diagnosis. Do not start or stop medication based on it. The care directory matches public listings by search category, distance, available directory hours, and rating when available; it does not certify that a provider is medically suitable.
