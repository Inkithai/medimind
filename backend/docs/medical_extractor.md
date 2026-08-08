# MediMind — Extraction Engine Reference

`medical_extractor.py` is the core clinical pipeline. It turns raw files into normalized JSON and builds a single chronological record per anonymous workspace. `retrieval.py` depends on its `client` and `MODEL` exports — keep those names stable.

### Env & client

```bash
pip install openai pdfplumber pymupdf pillow python-dotenv python-dateutil --break-system-packages
export LLM_PROVIDER=gemini  # or groq
# gemini: export GEMINI_API_KEY=AIza...  # aistudio.google.com/app/apikey (15 RPM / 1M tok/day free)
# groq:   export GROQ_API_KEY=gsk_...    # console.groq.com/keys
```

- Calls LLM via OpenAI SDK (provider selected by `LLM_PROVIDER`). Groq: `https://api.groq.com/openai/v1` (`GROQ_BASE_URL`), Gemini: `https://generativelanguage.googleapis.com/v1beta/openai/` (`GEMINI_BASE_URL`), generic `LLM_BASE_URL` for Cerebras/OpenRouter.
- Raises at import if provider key missing (`GROQ_API_KEY` for groq, `GEMINI_API_KEY`/`GOOGLE_API_KEY` for gemini, `LLM_API_KEY` for generic) — fail fast.
- `MODEL` default `openai/gpt-oss-120b` (groq) or `gemini-2.0-flash` (gemini). Overridable via `GROQ_MODEL` / `GEMINI_MODEL` / `LLM_MODEL`.
- `VISION_MODEL` default `qwen/qwen3.6-27b` (groq) or `gemini-2.0-flash` multimodal (gemini). Overridable via `GROQ_VISION_MODEL` / `GEMINI_VISION_MODEL` / `LLM_VISION_MODEL`.
- Reasoning models (the qwen vision default) emit `<think>` chain-of-thought that breaks Groq's server-side JSON validation (`400 json_validate_failed`) and eats the TPM-capped vision token budget. `_completion_resilient()` therefore probes reasoning-suppression switches (`chat_template_kwargs.enable_thinking=false`, `reasoning_format=hidden`) per output-mode rung and caches per model what works (probe 400s and provably-ignored probes are crossed off permanently). Tune with `GROQ_DISABLE_REASONING` / `LLM_DISABLE_REASONING` (true = probe every non-strict model, false = never probe).
- Groq retires models on a schedule (Llama 4 Scout shut down 2026-07-17; Llama 3.1 8B / 3.3 70B shut down 2026-08-16) — a retired model ID 404s with `model_not_found`. `_chat_completion()` re-raises that as a provider-aware error pointing at `docs_url` and the env vars above.

### 1. Schema — strict structured output

`EXTRACTION_JSON_SCHEMA` with `strict: True` forces every document into the shape below. Strict json_schema is only supported on `openai/gpt-oss-*` models on Groq; for any other model (e.g. the vision default `qwen/qwen3.6-27b` or any Gemini model) `_format_ladder()` falls back to JSON-object mode and inlines the schema into the system prompt.

```jsonc
{
  document_type: "prescription" | "lab_report" | "discharge_summary" | "other",
  date, provider_or_doctor, patient_name,
  medications: [{name, ingredients: [INN English], dosage, frequency, duration,
                 dosage_value, dosage_unit, frequency_per_day, is_as_needed, confidence}],
  lab_results: [{test_name, value, unit, reference_range, flag, confidence}],
  allergies_noted: [string],
  clinical_notes, illegible_or_low_confidence_fields, overall_confidence
}
```

- `ingredients` always English INN generic, even if source is Spanish/Japanese brand — needed for cross-language duplicate detection.
- `dosage_value`/`dosage_unit` normalized to mg etc., `frequency_per_day` normalized numeric. Original strings kept for audit. Locale comma decimals handled (`1,5 g` → 1500 mg).
- Confidence bands: 0.90-1.00 clear print, 0.60-0.89 judgment needed (brand→generic, abbreviation), <0.60 hard handwriting/blur.

### 2. File-type routing

| Helper | Purpose |
|---|---|
| `pdf_has_text_layer(path, min_chars=30)` | Samples first 3 pages for embedded text |
| `extract_text_from_pdf(path)` | Plain text per page |
| `pdf_pages_to_images(path, dpi=200)` | Rasterize scanned PDF via PyMuPDF |
| `image_to_base64(img)` | PNG base64 for vision payload |

- Digital PDF → text extraction (cheap).
- Scanned PDF / image → vision OCR per page (one LLM call per page).

### 3. LLM calls

- `extract_from_image(img)` — sends `EXTRACTION_SCHEMA_PROMPT` + image_url, parses the response with `_parse_json_object`.
- `extract_from_text(text)` — same schema, text input.

Both do not attach `_source` — caller does.

**Structured-output resilience** — The provider validates model output server-side in json_object and strict json_schema modes and discards any generation that isn't valid JSON, rejecting the request with `400 json_validate_failed` (the body includes `failed_generation`, which is logged so a 400 is diagnosable instead of a mystery). All structured calls (`extract_from_image`, `extract_from_text`, `cross_check_prescriptions`) go through `_completion_resilient()`, which walks down `_format_ladder()` (`strict json_schema` on `openai/gpt-oss-*` → `json_object` + inlined schema → plain text with no `response_format` at all, where the provider does not validate and `_parse_json_object()` recovers JSON wrapped in markdown fences or surrounded by commentary) with these rules:

1. A response-format rung is retried only for genuinely transient errors (5xx, 408/409, network). A `400 json_validate_failed` or a client-side non-JSON parse failure (e.g. a `<think>`-only dump from the qwen vision model) means the SAME format will fail again, so the runner advances to the next looser rung immediately instead of burning doomed retries — previously one file could trigger several doomed json_object retries plus repair round-trips.
2. Rate limits (429) are paced using the provider's `Retry-After` header (falling back to exponential backoff), capped by `GEMINI_MAX_RATE_LIMIT_RETRIES` / `GROQ_MAX_RATE_LIMIT_RETRIES` / `LLM_MAX_RATE_LIMIT_RETRIES` (default 5) so a hard-throttled account fails fast with an actionable message instead of stalling an upload for many minutes. The OpenAI SDK's own retry loop is disabled (`max_retries=0`) so SDK Retry-After sleeps don't stack on top of our ladder.
3. Every provider error is logged with its full body via `_error_detail()` (status, code, message, response body) before retry or propagation, and non-retryable errors (401, 404 model_not_found, non-json_validate 400s) propagate immediately.
4. If every rung fails, two last-resort repairs run (a vision repair retry with the original image, then a cheap text-model repair), and only then does it raise a plain-language `RuntimeError` ("repeatedly failed to return valid structured JSON ... retry the upload").

- `_apply_confidence_ceiling(result, 0.85)` caps vision OCR results — handwritten read can never be 100% certain vs digital `text_layer`.

### 4. Entry routers

`process_document(file_path)`:

- Validates zip-inside-path, missing file, dir passed instead of file, unsupported extension — with actionable messages.
- Returns single doc dict or `{multi_page: True, pages:[...]}` for scanned PDFs. Each page tagged `_source: {file, method, page}`.

`process_patient_folder(folder_path)` — recursive `rglob`, supported extensions only, logs per-file failures.

### 5. Grouping & timeline

`group_documents_by_patient(raw_results, drop_demo=True)`:

- Flattens, drops `_is_demo_document` (DEMO/SAMPLE/DUMMY names), groups by lowercased `patient_name` → `unknown_patient` bucket for missing names, warns if >1 real patient.

`build_patient_timeline(raw_results)`:

- Assumes one patient (run group first if not guaranteed).
- Sorting now parses dates via `dateutil.parser` fuzzy — fixes lexicographic bug for `05 Jan 2026` vs `20 Apr 2026`. Unparseable → end.
- Output: `{visits: sorted, medications_timeline: flat with date+source_file, lab_results_timeline, known_allergies: deduped}` — primary contract with `retrieval.py`.

For MediMind anonymous flow, `user_id` from `POST /anonymous/session` IS patient key — every read/write scoped.

### 6. Cross-check

`cross_check_prescriptions(timeline)` — LLM prompt with strict schema, returns interactions/duplicates/dosage conflicts/allergy conflicts + `overall_recommendation` that always defers to clinician and states not a validated DB.

Plus deterministic `detect_exact_duplicate_medications(timeline)` — exact match on `ingredients + dosage_value + dosage_unit` across distinct `(date, source_file)` — language-independent. Merged with LLM results, source-set deduped.

### 7. Persistence helpers (CLI)

- `patient_docs_<sanitized>.json` — raw flat docs for merging later.
- `patient_report_<sanitized>.json` — timeline + cross-check + lab_trends.
- API uses Supabase instead (see `db.py`).

### 8. CLI

```bash
python medical_extractor.py file1.pdf file2.jpg
python medical_extractor.py "C:/path/To Patient X"
python medical_extractor.py <path> --chat   # interactive Q&A after indexing
```

Flow: extract → group → per patient: timeline → cross-check → `track_lab_trends` → `index_patient_timeline` (lazy import to avoid circular) → save JSON. Index failures logged not aborting. `--chat` picks patient if multiple then loops `input()` with conversation rewrite.
