# MediMind — Retrieval & Q&A Layer

Phase 1 (single-shot) + Phase 2 (conversations) over structured timelines. Imports `client` + `MODEL` from `medical_extractor.py` — chat runs on the active `LLM_PROVIDER` (Groq or Gemini) shared client. Never re-reads raw PDFs/images; works purely on `build_patient_timeline()` output.

**Embeddings:** Groq/Gemini have no embeddings API. Chain:
1. OpenAI `text-embedding-3-small` when `OPENAI_API_KEY` set (OpenAI client used only for embeddings).
2. Fallback: Chroma local ONNX `all-MiniLM-L6-v2` — no key, runs in-process, one-time weight download.

Different dimensionalities → after switching backend delete `./chroma_db` and re-upload.

### Constants

- `EMBEDDING_MODEL` = `text-embedding-3-small` (env `EMBEDDING_MODEL` override) — only used if OpenAI key present.
- `CHAT_MODEL = MODEL` — alias to `openai/gpt-oss-120b`; change this not extractor's MODEL if Q&A model should diverge.
- `CHROMA_DIR` = `CHROMA_DIR` env or `./chroma_db` (Railway volume override `/data/chroma_db`). Note: previously not gitignored — now listed.
- `EMBEDDING_BATCH_SIZE = 100` — safeguards per-request limit.

### Flow

```
build_patient_timeline() dict
  → build_chunks_from_timeline() → [{id, text, metadata}, ...]
  → embed_texts(texts) → vectors
  → index_patient_timeline() → Chroma collection.upsert() per anon user_id

question (+ optional chat_history)
  → effective retrieval query (original or rewritten by conversation.py)
  → embed_texts([retrieval_query])
  → collection.query(n_results=min(top_k,count))
  → context blocks [date | source_file | type]\ntext
  → chat.completions.create(response_format=ANSWER_RESPONSE_FORMAT)
  → parsed JSON answer
```

### Chunking

`build_chunks_from_timeline(patient_key, timeline)`:

- Expects `medications_timeline`, `lab_results_timeline`, `visits` for `_source.file` + `clinical_notes`, `known_allergies`.
- One chunk per:

| Type | Source | Text helper |
|---|---|---|
| `medication` | each med entry | `_medication_chunk_text()` includes INN + normalized dose/freq + printed dose + date + source |
| `lab_result` | each lab entry | `_lab_result_chunk_text()` test, value+unit, flag, ref range, date, source |
| `clinical_note` | visit with non-null notes | `_clinical_note_chunk_text()` date + source + notes |
| `allergy` | whole list (0/1 chunk) | `_allergy_chunk_text()` |

Chunk: `{id: sha256 hex, text: natural language, metadata: {patient_key, date, source_file, chunk_type}}`. Date/source_file empty string not None (Chroma metadata restriction).

IDs deterministic: `sha256(f"{patient_key}|{source_file}|{chunk_type}|{index}")`. Index is position in list. So re-index upserts, safe to call each upload. Known limitation: if order shifts due to new doc inserted earlier chronologically, some IDs collide with different content and old chunks not auto-deleted — stale chunks may linger (not a bug, Phase-1 scope).

### Embeddings

`embed_texts(texts)`:

- Empty → `[]`.
- OpenAI path batches by `EMBEDDING_BATCH_SIZE`.
- Raises `RuntimeError` wrapped around `OpenAIError` with batch size context — used both for indexing and question embedding.

### Storage

- `_sanitize_collection_name(patient_key)` → `[a-z0-9._-]+`, 3-63 chars, start/end alphanumeric, stable for anon ids like `anon_ab12cd...` → `anon_ab12cd...`.
- `_get_chroma_client()` → `PersistentClient(path=CHROMA_DIR)` fresh per call (fine for CLI; for server consider caching).
- `_get_patient_collection(key, create)` — `create=True` → `get_or_create_collection` (indexing); `False` → `get_collection` returns None on miss (querying).
- `index_patient_timeline(patient_key, timeline)` — validates key, chunks, embeds, upserts. Returns the number of chunks indexed, or **0 (without storing anything)** when the timeline has no retrievable content — callers must treat 0 as "not indexed" (Q&A has nothing to search), never as success.

### Q&A entry

`answer_question(patient_key, question, chat_history?, top_k=8, retrieval_query?)`:

- Validates non-empty key/question.
- Effective query = `retrieval_query` if provided and non-empty else `question` — allows conversation module to rewrite ambiguous follow-ups while final prompt still shows original question.
- If no collection or count 0 → returns `_NO_INFO_ANSWER` no API calls.
- Else embed query, `collection.query(query_embeddings=[...], n_results=min(top_k,count))`, build context blocks tagged with date/source/type, splice optional `chat_history` (list of `{role, content}` passed straight through), final user message `Retrieved patient records:\n\n{context}\n\nQuestion: {question}`.
- System prompt rules: answer only from retrieved context else "I don't have enough information", never diagnose, force `recommend_professional_consult=true` for risk/interaction/allergy/dosage, cite sources.
- Strict `ANSWER_RESPONSE_FORMAT` JSON schema: `{answer, confidence, sources[{date, source_file}], recommend_professional_consult}`.
- Raises `RuntimeError` on chat failure; embedding failures bubble as `RuntimeError`.

### Conversation integration — Phase 2

`conversation.py` wraps this:

- History window 6 turns, summary after 20 total (keeps safety details).
- `rewrite_query_with_context()` resolves pronouns, keeps risk framing words (safe/danger/interact/allergy), returns only rewritten query, falls back raw on failure.
- `ask(session, question)` → history → rewritten → `answer_question(question=original, chat_history=history, retrieval_query=rewritten)` → record user + assistant turn → return result + `rewritten_query` for UI transparency.

### Security notes

- `./chroma_db` plaintext chunk texts readable by filesystem.
- Retrieval only structured fields, not raw page formatting.
- `chat_history` trusted as-is — sanitize if exposed to untrusted callers (it sits beside system prompt).

### Usage snippet

```python
from medical_extractor import build_patient_timeline
from retrieval import index_patient_timeline, answer_question

timeline = build_patient_timeline(docs)  # docs from process_document
index_patient_timeline("anon_ab12cd34ef56", timeline)

res = answer_question("anon_ab12cd34ef56", "What was I prescribed for sinus infection?")
# {"answer": "...", "confidence": 0.9, "sources": [...], "recommend_professional_consult": False}
```

Used by CLI `--chat` and API `/qa` + `/sessions/.../messages`.

For anonymous MediMind workspace, `patient_key` is `user_id` from `POST /anonymous/session` → stored in `localStorage.medimind.session.v1` → isolation via Supabase + Chroma + Cloudinary.
