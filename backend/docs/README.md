# Backend docs — freeze this for the current branch

Competition story:

> **Messy medical documents → structured longitudinal record → deterministic safety and trends → source-grounded AI.**

Four claims: **Understand → Detect → Explain → Protect**

There is **no** `/care`, `/find-care`, Geoapify, OSM, Leaflet, or consultation pack in this tree. Do not draw them.

| Doc | Slide / layer |
|---|---|
| [01-end-to-end-pipeline.md](01-end-to-end-pipeline.md) | The deck: three slides + four claims |
| [02-extraction-engine.md](02-extraction-engine.md) | Understand — file → timeline |
| [03-retrieval-and-qa.md](03-retrieval-and-qa.md) | Explain — grounded Ask AI |
| [04-lab-trends.md](04-lab-trends.md) | Detect — deterministic labs |
| [05-api-storage-and-jobs.md](05-api-storage-and-jobs.md) | Protect — anonymous workspace isolation |
| [06-care-navigation-extension.md](06-care-navigation-extension.md) | **Not on the main deck.** Optional future Connect layer: provider-agnostic facility search. Not in this tree. |

Setup and deploy: repo-root [README.md](../../README.md), [DEPLOYMENT_GUIDE.md](../../DEPLOYMENT_GUIDE.md).

Model IDs, retry ladders, embeddings, and collection-name rules stay in **engineering notes** at the bottom of 02–05 — not on the main slides.
