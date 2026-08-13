# Patient intelligence — Ask AI

How MediMind answers from the record without inventing facts.

```text
                 Patient Snapshot
                       │
       ┌───────────────┼────────────────┐
       ▼               ▼                ▼
   Timeline         Safety           Lab Trends
       │               │                │
       └───────────────┼────────────────┘
                       ▼
                  Ask AI / RAG
                       │
                       ▼
              Conversations
```

Ask AI never re-reads the original PDF or photo. It searches the structured timeline only.

Modules: `retrieval.py`, `vector_store.py`, `conversation.py`.

---

## Grounding rules

- Answer only from retrieved record chunks.
- If the record does not cover the question, say so.
- Never diagnose.
- If the question is about risk, interaction, allergy, or dose, recommend a professional consult and say so in the response.
- Cite the source file and date of every chunk used.

That is the product claim: **grounded questions over this patient’s documents**.

---

## Single question vs conversation

| Mode | Route | Extra |
|---|---|---|
| Single question | `/ask` | one retrieval + one answer |
| Conversation | `/conversations` | follow-ups are rewritten into a self-contained search query (“was that safe?” → the medication just discussed) |

The rewritten query is used only for search. The model still sees the words the patient typed.

Long conversations keep the last few turns verbatim and summarize older ones, without dropping safety details.

---

## Empty-record honesty

| Situation | What the user hears |
|---|---|
| Nothing uploaded | No indexed records yet |
| Files exist but nothing searchable | Records found, but no medications / labs / notes / allergies to search |
| Index missing after a redeploy, documents still in the database | Index is rebuilt from the saved documents, then the question is answered |

A missing database table is a deployment error, not “you have no records”.

---

## Engineering notes (not the main slide)

Chat uses the same LLM provider as extraction. Embeddings are separate: OpenAI if a key is set, otherwise a local MiniLM model. Switching embedding backends requires a fresh index.

Vectors live in local Chroma or in a Supabase `chunks` table (`VECTOR_STORE`). One collection / patient key per workspace.

Chunk types: medication, lab result, clinical note, allergy list. IDs are stable so re-upload upserts.

Collection names must start and end alphanumeric and stay under 63 characters. Truncation happens before that fixup so a long key is not rejected at index time.
