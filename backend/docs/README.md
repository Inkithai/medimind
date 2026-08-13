# Backend docs

Internals of the MediMind clinical pipeline as it exists on this branch.
Start with the end-to-end map, then drop into a module.

| Doc | What it covers |
|---|---|
| [01-end-to-end-pipeline.md](01-end-to-end-pipeline.md) | Workspace → upload → record → UI. The current product flow. |
| [02-extraction-engine.md](02-extraction-engine.md) | `medical_extractor.py` + `document_filter.py`: files → structured JSON, grouping, safety. |
| [03-retrieval-and-qa.md](03-retrieval-and-qa.md) | `retrieval.py` + `vector_store.py` + `conversation.py`: chunks, embeddings, Q&A, chat. |
| [04-lab-trends.md](04-lab-trends.md) | `lab_trends.py`: deterministic direction, crossings, recovery, unit clashes. |
| [05-api-storage-and-jobs.md](05-api-storage-and-jobs.md) | `api.py`, `auth.py`, `db.py`, `storage.py`, `jobs.py`: HTTP, persistence, async uploads. |

These pages replace the older `pipeline.md`, `medical_extractor.md`, and `retrieval.md`.
They describe **this checkout** — anonymous workspaces, timeline / safety / labs / Ask AI.
`/care` and `/find-care` live on later `main` commits and are not part of this tree.

Setup and deploy stay in the repo-root [README.md](../../README.md) and [DEPLOYMENT_GUIDE.md](../../DEPLOYMENT_GUIDE.md).
