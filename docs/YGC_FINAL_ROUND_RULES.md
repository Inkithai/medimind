# YGC – AI Architecture & Design Competition 2026

## Final Round Theme

**AI Medical Report & Prescription Cross-Checker with Local Doctor Recommendation**

This is the official Final Round brief. MediMind’s compliance map is
[`YGC_FINAL_ROUND_CHECKLIST.md`](YGC_FINAL_ROUND_CHECKLIST.md).

---

## 1. Scope of the Final Round Theme

The Final Round theme requires teams to extend their Round 1 “AI Medical Report
& Prescription Cross-Checker” solution with a **Local Doctor Recommendation**
feature.

This document defines the scope of that theme: what is already built (Round 1),
what new feature must be developed for the Final Round, the rules for that
feature, required deliverables, and the evaluation criteria.

---

## 2. What Is Already Built (Round 1 Solution)

Teams already have a system that:

- Extracts data from multiple medical documents (lab reports, prescriptions,
  notes, discharge summaries) and merges it into one patient timeline.
- Cross-checks prescriptions for interactions, duplicates, or conflicting
  dosages.
- Tracks lab result trends over time and explains them in plain language.
- Answers follow-up questions across multiple documents.
- Gives a confidence score and recommends consulting a doctor for high-risk or
  low-confidence cases.

This part of the system stays as it is. It is the foundation the Final Round
feature is built on.

---

## 3. What Needs to Be Developed (New Feature)

Add a **Local Doctor Recommendation** feature. When the system flags a
high-risk or low-confidence issue, it must help the user find a real doctor
nearby to consult.

This feature must:

- Identify the right type of doctor based on the flagged issue (e.g. a
  heart-related flag → cardiologist; a drug interaction → the prescribing
  doctor or a pharmacist).
- Ask the user two simple questions: (1) their location (city/area), and (2)
  their availability for a consultation (e.g. this week, evenings, etc.).
- Search real, publicly available data for doctors/clinics near that location
  using Google Maps Places API or a free alternative (see Section 4).
- Show a simple result list with doctor/clinic name, specialty, address,
  distance, and rating/contact number if available.
- Handle no results properly: if nothing is found, say so clearly and suggest
  widening the search area, instead of showing a fake result.

No agentic behavior, planning, or multi-step autonomy is required for this
feature. A straightforward flow of: **detect flag → ask location and
availability → call the API → show results**, is sufficient.

---

## 4. Data Rules

- No synthetic or made-up doctor/clinic data is allowed. All doctor/clinic
  information shown must come from a real, public source (Google Places API,
  OpenStreetMap/Nominatim, or another public directory).
- Medical document samples used for testing can remain the
  synthetic/de-identified sets from Round 1 — this rule applies only to the
  doctor/clinic data.
- The app must never present itself as making a diagnosis. It only flags a
  possible issue and points the user to a suitable doctor.

---

## 5. Deliverables

- Working application showing the full flow: document upload → flag detected →
  location and availability asked → doctor list shown.
- Working webApp link with a short README explaining which API was used and
  how.
- A short demo (5 minutes) covering the flow above.

---

## 6. Evaluation Criteria

| Category | Weight | What is judged |
| --- | ---: | --- |
| AI Depth & Use | 30% | Quality of medical cross-checking logic, plus how well the new doctor-recommendation feature works. |
| Technical Execution | 30% | Code quality, real API integration (not mocked), and handling of missing/failed API results. |
| Originality & Innovation | 20% | How well the specialty-matching and doctor-ranking approach is designed. |
| Usefulness & Impact | 10% | Whether the feature genuinely helps a patient find and reach a real local doctor. |
| Presentation & UX | 10% | Clarity of the demo and how the results/disclaimers are shown to the user. |

**Note:** Any fabricated doctor/clinic data shown as real will result in an
automatic deduction, regardless of how the rest of the feature performs.
