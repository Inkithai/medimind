# MediMind architecture (this branch)

**Source of truth for slides.** This checkout has no care-navigation product.

```text
Understand  →  Detect  →  Explain  →  Protect
```

Do not put `/care`, `/find-care`, Geoapify, OSM, Leaflet, or a consultation pack on this page.

---

## Slide 1 — Intelligence pipeline

Input → extraction → validation → clinical intelligence → grounded AI.

```text
                    MediMind
                       │
                       ▼
             Anonymous Workspace
          No signup · Isolated user_id
                       │
                       ▼
              Patient Snapshot
                       │
          ┌────────────┼────────────┐
          ▼            ▼            ▼
       Upload       Timeline      Ask AI
          │            │            │
          ▼            ▼            ▼
     Extraction      Safety      Retrieval
          │            │            │
          └────────────┼────────────┘
                       ▼
             Patient Intelligence
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
    History         Medicines          Labs
       │               │                │
       └───────────────┼────────────────┘
                       ▼
                    Safety
                       │
                       ▼
                 Ask / Chat
```

What the judge should take away:

> Upload a private medical file. MediMind structures it, checks safety, tracks labs, and answers only from that record.

---

## Slide 2 — Patient data pipeline

```text
Upload
  │
  ▼
PDF / Image
  │
  ├── Digital PDF → text layer
  │
  └── Scanned / photo → vision OCR
              │
              ▼
        Medical extraction
              │
              ▼
        Document validation
              │
              ▼
        Patient timeline
              │
      ┌───────┼────────┐
      ▼       ▼        ▼
   Safety   Lab      Search index
            trends
```

Safety is a medication / allergy / dosage review over the extracted record. Lab trends are arithmetic over extracted numbers. Neither is a diagnosis.

---

## Slide 3 — Privacy and isolation

```text
Anonymous session
      │
      ▼
 anon_* user_id
      │
      ├──────── JWT
      │
      ├──────── X-User-Id must match the token
      │
      ├──────── Postgres rows scoped by user_id
      │
      ├──────── Files under /<user_id>/
      │
      └──────── Vector collection / patient_key
```

One browser → one isolated patient workspace.

Isolation is enforced **in the application data-access layer**, not by “turning on RLS”:

```text
Frontend
   ↓
JWT authentication
   ↓
user_id ↔ X-User-Id verification
   ↓
Backend authorization
   ↓
Service-role database access
   ↓
Every query filtered by that user_id
```

Supabase RLS is enabled with **no policies**. The service-role key bypasses RLS. Do not tell a judge that RLS is what isolates tenants. The stronger claim is:

> Tenant isolation uses the authenticated `user_id` across Postgres, file storage, and the vector store.

---

## Product on this branch

| Surface | Role |
|---|---|
| History | Chronological visits |
| Medicines | Traceable prescriptions |
| Labs | Trends, crossings, recovery |
| Safety | Interactions, duplicates, allergy conflicts |
| Ask / Conversations | Grounded answers from the record |

There is no Find Local Care product here. If that work lives on another branch, merge it before drawing it.

---

## What not to put on the main slide

These are real, but they are backup-slide material:

- retry ladders and JSON repair
- model IDs and token budgets
- JPEG size / EXIF
- collection-name sanitization
- worker-pool concurrency
- Geoapify / OSM / Leaflet (not in this tree)

The main slide is the product. Engineering notes live in [02](02-extraction-engine.md)–[05](05-api-storage-and-jobs.md).
