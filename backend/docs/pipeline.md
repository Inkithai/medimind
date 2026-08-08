# MediMind Clinical Pipeline — End-to-End Flow

Anonymous workspaces, no login. One browser → one isolated patient view.

```
                Frontend (React + TS + Vite)
                        │
                        ▼
               Anonymous Session (POST /anonymous/session → JWT anon_* stored in localStorage)
                        │
                        ▼
                   Dashboard / Overview
                        │
            ┌───────────┴────────────┐
            ▼                        ▼
      Upload Documents         Ask Question / Chat
            │                        │
            ▼                        ▼
      FastAPI /api/v1/          Conversation service
      documents (multipart)           │
            │                         ├── rewrite follow-up → self-contained query
            ▼                         │
      Clinical Pipeline          RAG Retrieval (Chroma)
      ┌─────────────┐                   │
      │ OCR / text  │                   ▼
      │ Extraction  │ ← LLM_PROVIDER (Groq Qwen3.6 27B + GPT-OSS 120B or Gemini 3.6 Flash multimodal, structured JSON)
      │ Filter      │   (document_filter: no extra LLM call)
      │ Timeline    │   (group + sort with dateutil, merge meds/labs/allergies)
      │ Safety      │   (LLM cross-check + deterministic duplicate)
      │ Lab Trends  │   (deterministic direction + crossing)
      └──────┬──────┘
             │
      ┌──────┴──────┬───────────────┐
      ▼             ▼               ▼
  Supabase      Cloudinary      Chroma per user
  documents     mediscan/<uid>/  collection = sanitized user_id
  snapshots     original files    vectors + plaintext chunks
      └──────┬───────┘
             ▼
      Patient Record {timeline, cross_check, lab_trends}
             │
      ┌──────┼───────────────┬────────────┐
      ▼      ▼               ▼            ▼
   History Medicine        Labs       Safety
   (chrono) (traceable) (trends)  (warnings)
```

### 1. Extraction — medical_extractor.py

- Detects digital PDF vs scanned PDF vs image.
- Digital → `pdfplumber` text extraction; scanned → `PyMuPDF` rasterize → `PIL.Image` → base64 → LLM vision (Groq Qwen3.6 or Gemini Flash).
- Strict `json_schema` output ensures fields always present: `document_type`, dates, provider, patient, meds with INN ingredients + normalized `dosage_value/unit` + `frequency_per_day`, lab results with flags, allergies, notes, confidences.
- `process_document()` returns single doc or `{multi_page, pages}` shape — callers must flatten.
- Friendly errors for zip-inside-path, missing file, folder passed, unsupported extension.

### 2. Grouping & Timeline

- `group_documents_by_patient()` — flattens, drops DEMO/SAMPLE/DUMMY docs, groups by lowercased `patient_name`, `unknown_patient` bucket for missing names, warns if multiple real patients.
- `build_patient_timeline()` — merges one patient's docs, **sorting via `dateutil.parser` fuzzy** (fixed lexicographic bug), outputs `visits`, `medications_timeline` (each with `date+source_file`), `lab_results_timeline`, `known_allergies`.

In MediMind API path, scoping uses anonymous `user_id` (`anon_*`) from JWT — no manual patient_name grouping needed beyond extraction.

### 3. Cross-checking

- LLM prompt asks for interactions (severity low/moderate/high), duplicates by ingredient not brand, conflicting dosages, allergy conflicts, plus overall recommendation that always says consult clinician and notes not a validated DB.
- Deterministic duplicate detector matches exact `ingredients + dosage_value + dosage_unit` across distinct `(date, source_file)` — language-independent.
- Merged, deduped by source sets.

### 4. Lab Trends — lab_trends.py

Deterministic, no LLM:

- Parse dates fuzzy, parse values numeric, parse ranges robust (`70-99 mg/dL`, `Reference: 0.74-1.35 mg/dL` handled, avoids `70-99` → `70,-99` bug).
- Group by lowercase test name, keep first casing for display.
- Require 2+ usable dated numeric points; else `insufficient_data` with reason.
- Computes direction `increasing/decreasing/stable/fluctuating (net ...)`, flag sequence phrase, crossing point (first normal→abnormal), approaching threshold (within 15% of boundary width).
- Template explanation: rise/fall + trail `value (date) → ...` + crossing/approaching wording. No LLM hallucination.
- Confidence discounted for dropped entries or disagreeing units/ranges.

### 5. Retrieval — retrieval.py

- `build_chunks_from_timeline()` → one chunk per medication / lab result / clinical note / single allergy list. Text is natural language embedding input; metadata strings (Chroma can't store None).
- Chunk IDs deterministic `sha256(patient_key|source_file|chunk_type|index)` → upsert safe.
- `embed_texts()` — OpenAI `text-embedding-3-small` if `OPENAI_API_KEY`, else local ONNX MiniLM. Batch size 100.
- `_sanitize_collection_name()` → 3-63 chars, alphanumeric start/end, stable mapping.
- `index_patient_timeline()` — chunks → embeddings → `collection.upsert()` into `CHROMA_DIR` (env overridable, e.g. Railway volume `/data/chroma_db`).
- `answer_question()` — embed query (or rewritten query from conversation), `collection.query(n_results=min(top_k,count))`, build tagged context `[date | source_file | type]\ntext`, plus optional chat_history, system prompt forces grounded answers, no diagnosis, forces professional consult for risk, strict JSON output. Returns no-info answer if no collection.

### 6. Conversation — conversation.py

- `ConversationSession` holds turns with ISO timestamps, summary cache.
- `get_history(max_turns=6)` — if total >20, summarizes older than last 6 via cheap LLM keeping safety details.
- `rewrite_query_with_context()` — resolves pronouns, preserves risk framing (safe/danger/allergy/interact), outputs only rewritten query, falls back to raw on failure.
- `ask(session, question)` — get history, rewrite, call `answer_question(question=original, chat_history=history, retrieval_query=rewritten)`, record turns, return result + `rewritten_query`.

### 7. API — api.py

- Lifespan startup → `db.ensure_indexes()` (no-op for Supabase but kept).
- CORS `*` by default, overridable via `CORS_ORIGINS`.
- `POST /anonymous/session` public → issues JWT server-side.
- `POST /documents` — validates extensions, extracts all first (no Cloudinary write until all pass to avoid orphans), filters demo + non-medical, archives to Cloudinary once per file, merges with Supabase existing docs, builds timeline, cross-check, trends, re-indexes, saves snapshot. `indexed` is false (with `index_error`) if indexing produced 0 retrievable chunks — the log line "No indexable content ... skipping indexing" is no longer followed by a misleading `indexed=True`.
- `GET /timeline, /cross-check, /lab-trends` — individual slices, 404 if no snapshot (kept for per-page use + backward compat).
- `GET /patient-snapshot` — the whole record (`patient_timeline`, `cross_check_report`, `lab_trends`, `updated_at`) in ONE request so the dashboard never fans out three calls; 404 if no snapshot (frontend treats that as first-run empty state). `lab_trends` recomputed on the fly for pre-trends snapshots.
- `POST /qa` and `POST /sessions/{id}/messages` — 400 empty, 502 LLM/embedding failure.

### 8. CLI wiring (medical_extractor __main__)

For local dev: `python medical_extractor.py <files|folder> --chat` → group → timeline → cross-check → trends → index → write local JSON reports. `--chat` drops into interactive loop with session `cli`.

### Dependencies

`openai pdfplumber pymupdf pillow chromadb python-dotenv python-dateutil fastapi uvicorn[standard] python-multipart supabase cloudinary pyjwt`

### Status

- Retrieval only over structured fields, not raw pages/images.
- No deletion reconciliation if timeline ordering shifts causing stale chunk IDs.
- Sessions in-memory per process.
- Next: evaluation harness, raw text retrieval, multi-patient diff.
