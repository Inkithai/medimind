# Backend docs — current source of truth

This folder describes **this branch**. The product is:

```text
Medical documents → extraction → validation → patient intelligence → grounded AI
```

There is **no** `/care`, `/find-care`, Geoapify, OSM, Leaflet, or consultation pack in this tree. Do not put those on the main architecture.

Use **three layers**, not one giant diagram.

| Slide / doc | Layer | Question it answers |
|---|---|---|
| [01-end-to-end-pipeline.md](01-end-to-end-pipeline.md) | Presentation architecture | What is MediMind? |
| [02-extraction-engine.md](02-extraction-engine.md) | Patient data pipeline | How does a file become a record? |
| [03-retrieval-and-qa.md](03-retrieval-and-qa.md) | Patient intelligence | How does Ask AI stay grounded? |
| [04-lab-trends.md](04-lab-trends.md) | Patient intelligence | How do labs move over time? |
| [05-api-storage-and-jobs.md](05-api-storage-and-jobs.md) | Trust / isolation | How is one browser one patient? |

Narrative for judges:

**Understand → Detect → Explain → Protect**

Setup and deploy stay in the repo-root [README.md](../../README.md) and [DEPLOYMENT_GUIDE.md](../../DEPLOYMENT_GUIDE.md). Retry ladders, token budgets, and collection-name sanitization belong in engineering notes — not on the main slide.
