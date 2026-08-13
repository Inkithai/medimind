# Extraction engine

`medical_extractor.py` turns a PDF or image into normalized JSON and builds one chronological record per workspace. `retrieval.py` imports its `client` and `MODEL` — keep those names stable.

Companion: `document_filter.py` (post-extraction, no extra LLM call).

## Provider layer

All LLM calls use the OpenAI SDK. Only `base_url` / `api_key` / `model` change.

| `LLM_PROVIDER` | Key | Text | Vision |
|---|---|---|---|
| `groq` (default) | `GROQ_API_KEY` | `openai/gpt-oss-120b` | `qwen/qwen3.6-27b` |
| `gemini` (recommended) | `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `gemini-3.6-flash` | same model, multimodal |
| anything else | `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL` | `LLM_MODEL` | `LLM_VISION_MODEL` |

Import **fails fast** if the resolved key is missing or still a `your-…` placeholder.

Do not configure `gemini-2.0-flash`. It was shut down 2026-06-01; the compatibility endpoint can return HTTP 429 with `limit: 0` instead of `model_not_found`.

Optional **OpenRouter hard-quota fallback** (`OPENROUTER_FALLBACK_ENABLED` + key + model) only trips after an unrecoverable primary quota / retired-model error. It is off by default because it sends document content to a second service.

`max_retries=0` on the SDK. Retries live in `_completion_resilient()` so 429s are paced once, not stacked.

## Schema

`EXTRACTION_JSON_SCHEMA` (`strict: True`) is enforced server-side only on Groq `openai/gpt-oss-*`. Every other model (Qwen vision, Gemini) walks `_format_ladder()`: `json_object` + inlined schema → plain text, then `_parse_json_object()`.

```jsonc
{
  "document_type": "prescription | lab_report | discharge_summary | other",
  "date": "string | null",
  "provider_or_doctor": "string | null",
  "patient_name": "string | null",
  "medications": [{
    "name": "as printed",
    "ingredients": ["English INN"],
    "dosage": "as printed",
    "frequency": "as printed",
    "duration": "string | null",
    "dosage_value": "number | null",
    "dosage_unit": "mg | mL | …",
    "frequency_per_day": "number | null",
    "is_as_needed": true,
    "confidence": 0.0
  }],
  "lab_results": [{
    "test_name": "", "value": "", "unit": null,
    "reference_range": null,
    "flag": "normal | high | low | unknown",
    "confidence": 0.0
  }],
  "allergies_noted": [],
  "clinical_notes": null,
  "illegible_or_low_confidence_fields": [],
  "overall_confidence": 0.0
}
```

- Ingredients are always English INN, even when the page is Tamil / Spanish / Japanese. Needed for cross-language duplicates.
- `dosage_value` / `frequency_per_day` are normalized. Printed strings stay for audit. Locale commas (`1,5 g`) become 1500 mg.
- Confidence bands in the prompt: 0.90–1.00 clear print; 0.60–0.89 judgment (brand→generic); below 0.60 blur / handwriting.
- Vision results are capped at **0.85** (`_apply_confidence_ceiling`). A handwriting read cannot outrank a digital text layer.

## File routing

| Input | Path |
|---|---|
| Digital PDF (`pdf_has_text_layer`, ≥30 chars on first 3 pages) | `pdfplumber` → `looks_like_medical_text` → `extract_from_text` → `_source.method = text_layer` |
| Scanned PDF | PyMuPDF rasterize @ 200 dpi → one vision call per page → `{ multi_page, pages }` |
| Image `.png/.jpg/.jpeg/.webp` | `ImageOps.exif_transpose` → JPEG ≤1600 px, quality 85 → vision |

`image_to_base64` writes **JPEG**, not PNG. Uncompressed PNG payloads were 15–20 MB and timed out.

`process_document(path, progress_callback=?)` emits `reading` / `extracting` without talking to the job store. Callers flatten `{multi_page, pages}`.

Pre-LLM text-layer check (`looks_like_medical_text`):

- Filename tokens `cv`, `resume`, `portfolio` are **word-anchored**. `recovery.pdf` and `cardiovascular_report.pdf` are not treated as CVs.
- Dense CV keyword text with almost no medical terms is rejected before an LLM call.

## Resilience (`_completion_resilient`)

1. Output-mode ladder: strict schema (gpt-oss only) → `json_object` → plain text.
2. Reasoning-model probes (`enable_thinking=false`, `reasoning_format=hidden`) cached per model. A 400 “unknown parameter” or a response that still contains `<think>` crosses that probe off.
3. Transient 5xx / 408 / network retry on the same rung. `json_validate_failed` or a non-JSON dump **advances** the rung (same format will fail again).
4. 429 honors `Retry-After` or Gemini `retryDelay`, capped by `*_MAX_RATE_LIMIT_RETRIES` (default 5). Daily quota / `limit: 0` / retired Gemini → `ProviderRateLimitError` immediately.
5. TPM 413 reduces `max_tokens` and retries. Vision default is 2048 on Groq’s 8K TPM tier.
6. Last resort for images: one vision repair with the **original image**. There is no text-only repair — that used to fabricate empty JSON and 422 as “not a medical document”.

`_parse_json_object` strips `<think>` / HTML-encoded tags, fences, trailing commas, and finds the first balanced `{…}`.

## Grouping and timeline

`group_documents_by_patient(raw, drop_demo_documents=True)` — CLI / folder path:

- Flattens multi-page results.
- Drops `_is_demo_document`.
- Groups by lowercased `patient_name`; missing names → `unknown_patient`.
- Warns if more than one real patient is in the batch.

`_is_demo_document` (current):

1. `_source.method == "synthetic"` (fixture generator).
2. Word-boundary markers in **many scripts** (English, Tamil, Sinhala, Hindi, Spanish, French, Arabic) plus Japanese substring markers.
3. Matching uses `casefold()`, not `.upper()`.
4. Names that merely *contain* a marker (`Sampleton`, `Demopoulos`) are **kept**. False-rejecting a real record is worse than admitting a demo page.

On **HTTP upload**, demo pages are logged and still processed. The user chose the file. The medical-content assertion still runs.

`build_patient_timeline(docs)` assumes one patient (the API uses `user_id`, not name grouping):

- Sorts with `dateutil.parser` fuzzy. Raw-string sort used to put `05 Jan 2026` after `20 Apr 2026`.
- Output: `{ visits, medications_timeline, lab_results_timeline, known_allergies }`. Each med/lab carries `date` + `source_file`.

## Safety cross-check

`cross_check_prescriptions(timeline)` — LLM, same resilient ladder, schema:

- `potential_drug_interactions` (severity low/moderate/high)
- `duplicate_prescriptions`
- `conflicting_dosage_instructions`
- `allergy_conflicts`
- `overall_recommendation` — always defer to a clinician; state this is not a validated interaction DB.

`detect_exact_duplicate_medications` is deterministic: same `ingredients + dosage_value + dosage_unit` on two distinct `(date, source_file)` pairs. Merged into the LLM list, deduped by source set. Language-independent.

## Filter — `document_filter.py`

Runs **after** extraction, **before** Cloudinary / timeline / safety / index. No second model call.

A page is kept if:

- it has structured meds, labs, or allergies, **or**
- `document_type` is prescription / lab_report / discharge_summary **and** `overall_confidence ≥ 0.35`.

`clinical_notes` alone is not enough — a Zoom screenshot produces a non-empty note.

## CLI

```bash
python medical_extractor.py file1.pdf file2.jpg
python medical_extractor.py /path/to/folder
python medical_extractor.py <path> --chat
```

Flow: extract → group (drop demos) → per patient: timeline → safety → lab trends → index → `patient_docs_*.json` + `patient_report_*.json`. The HTTP API uses Supabase instead of those files.
