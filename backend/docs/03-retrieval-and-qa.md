# ③ Explain — grounded Ask AI

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

Ask AI never re-reads the original PDF or photo. It searches the structured record only.

This is not “upload PDF → ChatGPT.”

| UI | Backend |
|---|---|
| `/ask` | `POST /api/v1/qa` |
| `/conversations` | `POST /api/v1/sessions` then `POST /api/v1/sessions/{id}/messages` |

---

## Grounding rules

- Answer only from retrieved record chunks.
- If the record does not cover the question, say so.
- Never diagnose.
- Risk, interaction, allergy, or dose → recommend a professional consult.
- Cite **source file + date** for every chunk used.

```text
Patient record
      ↓
Retrieval
      ↓
Grounded answer
      ↓
Source + date
```

---

## Single question vs conversation

A first question searches the index and answers.

A follow-up such as “was that safe?” is rewritten into a self-contained search query. Search uses the rewrite. The model still sees the words the patient typed.

Long conversations keep recent turns verbatim and summarize older ones without dropping safety details.

---

## Empty-record honesty

| Situation | What the user hears |
|---|---|
| Nothing uploaded | No indexed records yet |
| Files exist but nothing searchable | Records found, but nothing to search |
| Index gone after a redeploy, documents still saved | Index rebuilt, then answered |
| Vector table missing | Deployment error — not “you have no records” |

---

## Engineering notes (appendix)

Chat uses the same LLM provider layer as extraction. Embeddings are a separate chain (hosted if a key is set, otherwise local). Switching embedding backends needs a fresh index.

Vectors live in a local store or a `chunks` table. One collection / patient key per workspace.

Chunk types: medication, lab result, clinical note, allergy list. IDs are stable so re-upload upserts.
