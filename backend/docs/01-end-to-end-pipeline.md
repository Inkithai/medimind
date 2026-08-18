# MediMind architecture — freeze for this branch

**Understand → Detect → Explain → Protect**

Do not add `/care`, provider maps, or a consultation pack. They are not in this tree.

---

## The story judges should remember

> Messy medical documents become a structured longitudinal record. Safety and lab trends are computed, not guessed. Questions are answered only from that record. One anonymous workspace is one isolated patient record.

---

## Four claims

### ① Understand

Turn messy medical documents into a structured longitudinal record.

```text
PDF / Image
     ↓
Extraction
     ↓
Validation
     ↓
Timeline
```

### ② Detect

Find patterns and potential safety issues without diagnosing.

```text
Timeline
 ├── Medication Safety Service  (medication_safety.py — not extraction)
 ├── Allergy conflicts
 ├── Duplicate prescriptions
 └── Lab trends   (no language model)
```

### ③ Explain

Answer from the patient’s own records, not generic medical knowledge.

```text
Patient record
      ↓
Retrieval
      ↓
Grounded answer
      ↓
Source + date
```

### ④ Protect

Keep the anonymous patient’s data isolated across the stack.

```text
Anonymous workspace
      ↓
anon_* user_id
      ↓
DB + files + vectors
      ↓
Isolated patient record
```

---

## Slide 1 — Intelligence pipeline

Upload creates and updates the record. Timeline, safety, labs, and the search index are **derived** from that record. Ask AI reads the index. They are not three parallel inputs to a snapshot.

```text
                         MediMind
                            │
                            ▼
                 Anonymous Workspace
                    isolated user_id
                            │
                            ▼
                       Upload
                            │
                            ▼
                  PDF / Image Documents
                            │
                            ▼
                     Extraction
                            │
                            ▼
                  Document Validation
                            │
                            ▼
                   Patient Timeline
                            │
             ┌──────────────┼──────────────┐
             ▼              ▼              ▼
     Medication Safety  Lab Trends      Search Index
     (dedicated service)
             │              │              │
             └──────────────┼──────────────┘
                            ▼
                   Patient Intelligence
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
             Dashboard            Ask AI / Chat
```

---

## Slide 2 — From record to grounded answers

```text
Original documents
       │
       ▼
Structured patient record
       │
       ├── Timeline
       ├── Safety
       ├── Lab Trends
       │
       ▼
   Search index
       │
       ▼
    Ask AI

   Grounded in structured patient data
```

Lab trends: **no language model. No diagnosis.** Direction, crossing, recovery, and threshold are computed; the sentence is filled from those numbers.

Ask AI never re-reads the PDF or photo.

---

## Slide 3 — Privacy and isolation

Say: **one anonymous workspace → one isolated patient record.**

The browser only stores session credentials. The backend enforces the boundary.

```text
                    Anonymous Session
                           │
                           ▼
                       anon_* ID
                           │
                           ▼
                     Signed JWT
                           │
                           ▼
                 Backend authentication
                           │
                    ┌──────┴──────┐
                    ▼             ▼
              JWT user_id    Header user_id
                    │             │
                    └──────┬──────┘
                           ▼
                       Must match
                           │
                           ▼
                  user_id-scoped queries
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
      Supabase         Cloudinary        Vectors
      user_id          mediscan/         patient key
                       <user_id>/
```

Do **not** say “RLS protects the data.” RLS is on with no policies. The service-role key bypasses it. Isolation is application-scoped `user_id` after JWT + header verification.

---

## UI vs API (keep these separate)

| What the user opens | What the backend does |
|---|---|
| `/` landing → start workspace | `POST /api/v1/anonymous/session` |
| `/upload` | `POST /api/v1/documents` (async job + poll) |
| `/dashboard` | `GET /api/v1/patient-snapshot` |
| `/history` | snapshot timeline |
| `/medicines` | snapshot medications |
| `/labs` | `GET /api/v1/lab-trends` (or snapshot) |
| `/safety` | snapshot cross-check |
| `/ask` | `POST /api/v1/qa` |
| `/conversations` | `POST /api/v1/sessions` then `/sessions/{id}/messages` |

Legacy aliases (`/timeline`, `/qa`, `/sessions`, …) still work. They are not the product names.

---

## What stays off these three slides

- Groq / Gemini / OpenRouter model IDs
- Retry ladders, token budgets, JSON repair
- Embedding implementation and Chroma name rules
- Worker-pool concurrency
- JPEG size, EXIF, filename heuristics

Those belong in the engineering notes of [02](02-extraction-engine.md)–[05](05-api-storage-and-jobs.md).

On the main slide the LLM layer is vendor-neutral:

```text
                 LLM provider layer
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
        Text extraction        Vision extraction
```
