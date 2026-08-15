# MediMind — Documentation

Project-level documentation, deployment guides and pitch material. Engineering
docs for individual backend modules live next to the code they describe, in
[`../backend/docs/`](../backend/docs/).

## Deployment

| File | What it covers |
| --- | --- |
| [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) | End-to-end deploy: backend container, Vercel frontend, environment variables, Supabase schema. |

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
[`medical_extractor.md`](../backend/docs/medical_extractor.md) and
[`retrieval.md`](../backend/docs/retrieval.md).
