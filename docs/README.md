# MediMind — Documentation

Project-level documentation, deployment guides and pitch material. Engineering
docs for individual backend modules live next to the code they describe, in
[`../backend/docs/`](../backend/docs/).

## Competition (YGC Final Round)

| File | What it covers |
| --- | --- |
| [`YGC_FINAL_ROUND_CHECKLIST.md`](YGC_FINAL_ROUND_CHECKLIST.md) | Official 19-item final-round checklist — all complete, with module evidence. |
| [`FEATURES.md`](FEATURES.md) | Full product inventory plus Round 1–5 feature checklists. |
| [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) | 4:30 demo script: upload → history → safety → labs → Ask → Find Care. |

## Deployment

| File | What it covers |
| --- | --- |
| [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) | End-to-end deploy: backend container, Vercel frontend, environment variables, Supabase schema, Find Care directory keys. |

## Implementation notes

| File | What it covers |
| --- | --- |
| [`IMPLEMENTATION_REPORT.md`](IMPLEMENTATION_REPORT.md) | Clinical-safety and longitudinal CDS build (renal/hepatic, drug–lab, contraindications, vitals, FHIR). |
| [`PENDING_GAPS_IMPLEMENTED.md`](PENDING_GAPS_IMPLEMENTED.md) | Normalized tables, EML graph, and patient-profile completion pass. |
| [`CORRECTED_GAP_ROADMAP.md`](CORRECTED_GAP_ROADMAP.md) | Re-check of claimed gaps against the actual codebase. |
| [`COMPARISON_REPORT.md`](COMPARISON_REPORT.md) | Feature-gap analysis vs. comparison repositories. |
| [`feature-gap-report.md`](feature-gap-report.md) | Earlier feature-gap notes. |
| [`repository-feature-gap-report-2026-08-18.md`](repository-feature-gap-report-2026-08-18.md) | Dated repository comparison snapshot. |
| [`ygc-repos-gap-analysis.md`](ygc-repos-gap-analysis.md) | YGC repo comparison notes. |
| [`system-comparison.md`](system-comparison.md) | Architecture comparison. |
| [`fhir-interoperability.md`](fhir-interoperability.md) | FHIR export / import notes. |

## Pitch material (Y Combinator Round 1)

| File | What it covers |
| --- | --- |
| [`PRESENTATION.md`](PRESENTATION.md) | Slide content in source form — edit this first. |
| `PRESENTATION.pptx` | Generated 16:9 deck. Rebuild with `python generate_pptx.py` from the repository root; it writes here, not to the root. |
| `PRESENTATION.html` | Browser-viewable version of the deck. |
| `MediMind_YGC_Round1_Technical_Summary.docx` | Technical summary submitted for Round 1. |
| `MediMind_YGC_Round1_Demo_Transcript_and_Preparation.docx` | Demo script and prep notes. |
| `ygc_round1_tech_doc.docx` | Round 1 technical document. |

## Backend module docs

See [`../backend/docs/`](../backend/docs/) for
[`pipeline.md`](../backend/docs/pipeline.md) (upload → extract → index → answer),
[`medical_extractor.md`](../backend/docs/medical_extractor.md),
[`retrieval.md`](../backend/docs/retrieval.md), and
[`care_recommendations.md`](../backend/docs/care_recommendations.md) (live Google Places / OpenStreetMap directory).
