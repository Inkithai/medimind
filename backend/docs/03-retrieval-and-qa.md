# Retrieval, Q&A, and conversations

Works only on `build_patient_timeline()` output. Never re-reads the PDF or image.

Chat uses the same `LLM_PROVIDER` client as extraction (`client`, `MODEL` from `medical_extractor.py`). Embeddings are a separate chain — Groq and Gemini have no embeddings API.

## Embedding chain

1. OpenAI `text-embedding-3-small` if `OPENAI_API_KEY` is a real key (used **only** for embeddings).
2. Else Chroma’s in-process ONNX `all-MiniLM-L6-V2` (one-time weight download).

The two backends have different dimensions. After switching, delete `./chroma_db` or clear the `chunks` table and re-upload.

`EMBEDDING_BATCH_SIZE = 100`. Empty input → `[]`. Failures raise `RuntimeError` with batch size context.

## Vector store (`vector_store.py`)

| `VECTOR_STORE` | Where | Deploy note |
|---|---|---|
| `chroma` (default) | `PersistentClient(CHROMA_DIR)` | Needs a volume on Railway (`CHROMA_DIR=/data/chroma_db`) |
| `supabase` | table `chunks` (jsonb embeddings) | No volume. Brute-force cosine in Python — fine for 10–30 chunks/user |

Same façade: `upsert`, `query`, `count`, `delete_collection`, `get_store_name`.

A missing `chunks` table (PGRST205) raises `VectorStoreSchemaError` (HTTP 502 with “run `supabase_schema.sql`”). It must **not** look like “no indexed records”.

Numpy embeddings are converted with `.tolist()` before the jsonb upsert.

## Collection names

`retrieval._sanitize_collection_name` and `vector_store._sanitize_collection_name` **must stay identical** or a write and a later read hit different collections. A test asserts they agree.

Rules: 3–63 chars, `[a-z0-9._-]`, first and last alphanumeric.

**Truncate to 63, then strip trailing separators, then apply the end-alphanumeric fix.** The old `return name[:63]` after the fixup left a trailing `_` when the cut landed on a space-turned-separator. Chroma rejected the name → `indexed=False` with no clear error.

## Chunking

`build_chunks_from_timeline(patient_key, timeline)`:

| `chunk_type` | Source | Text |
|---|---|---|
| `medication` | each med | INN, printed + normalized dose/freq, date, source |
| `lab_result` | each lab | test, value+unit, flag, range, date, source |
| `clinical_note` | visit with notes | date, source, notes |
| `allergy` | whole list (0 or 1 chunk) | joined names |

```
id = sha256(patient_key|source_file|chunk_type|index)
metadata = { patient_key, date, source_file, chunk_type }   # strings only — Chroma rejects None
```

Re-index upserts in place. Limitation: if chronological order shifts, some IDs collide with different text and old chunks are not deleted.

`index_patient_timeline` returns the chunk count, or **0 without writing** when there is nothing retrievable. Callers must treat 0 as not indexed — never `indexed=True`.

On the Chroma path, `retrieval` still calls `_get_patient_collection` so existing test mocks keep working. On the Supabase path it goes through `vector_store.upsert`.

## Single-shot Q&A

`answer_question(patient_key, question, chat_history?, top_k=8, retrieval_query?)`

1. Effective retrieval string = `retrieval_query` or `question`.
2. Empty index **self-heals**: if persisted `documents` exist (Chroma wiped by a redeploy, or `chunks` created after the last upload), rebuild the index from those docs and answer.
3. Distinguish empty states:
   - no documents at all → `_NO_INFO_ANSWER` (“no indexed records were found…”)
   - documents exist but nothing indexable → `_NO_INDEXABLE_CONTENT_ANSWER`
4. Embed query → `vector_store.query` or `collection.query` → context blocks

```
[date: … | source_file: … | type: medication]
Medication: Metformin. …
```

5. System prompt: answer only from context; never diagnose; set `recommend_professional_consult=true` for risk / interaction / allergy / dosage; cite sources.
6. Strict JSON: `{ answer, confidence, sources[{date, source_file}], recommend_professional_consult }`.
7. Parse via `_parse_json_object` so a leaked `<think>` block does not 500 the endpoint. History-bearing turns use a direct `_chat_completion`; first turns use `_completion_resilient`.

Raises `ValueError` (empty question) or `RuntimeError` (embed / chat / missing schema).

## Conversations (`conversation.py`)

In-memory per process. Restart drops sessions (Supabase documents stay).

| Piece | Behavior |
|---|---|
| `ConversationSession` | full transcript + optional summary cache |
| `get_history(max_turns=6)` | after 20 turns, summarize older than the last 6; keep safety details |
| `rewrite_query_with_context` | resolve “was that safe?”; keep words like safe / allergy / interact; fall back to raw on LLM failure |
| `ask(session, question)` | history → rewrite → `answer_question(question=original, retrieval_query=rewritten)` → append turns → add `rewritten_query` |

API:

- `POST /sessions` → `{ user_id, session_id }`
- `POST /sessions/{id}/messages` → Q&A + `rewritten_query`
- `GET /sessions/{id}` → full untrimmed transcript
- `DELETE /sessions/{id}` → 204
- Unknown / other-user session → 404 (expired in-memory session after restart)

## Isolation and caveats

- Chunk text is plaintext on disk (`chroma_db`) or in `chunks.text`.
- Retrieval is structured fields only, not raw OCR pages.
- `chat_history` is trusted as-is (it sits next to the system prompt).
- Switching embedding backends without wiping the store produces garbage neighbors.
