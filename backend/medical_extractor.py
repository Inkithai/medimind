"""
Medical Document Extraction Pipeline
=====================================
Handles PDF (text-based or scanned) and image uploads (prescriptions, lab
reports, discharge summaries), extracts structured data using Groq-hosted
models (text: GPT-OSS 120B; vision: Qwen3.6 27B), and returns clean
JSON ready for timeline building, RAG indexing, and cross-checking.

Groq is accessed through its OpenAI-compatible endpoint
(https://api.groq.com/openai/v1) via the standard OpenAI SDK — only the
base URL, API key, and model names differ. Groq's free tier needs no
credit card (rate-limited; create a key at https://console.groq.com/keys).

Install:
    pip install openai pdfplumber pymupdf pillow --break-system-packages

Env:
    export GROQ_API_KEY="gsk_..."   (create one at https://console.groq.com/keys)
"""

import os
import io
import re
import json
import time
import base64
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import pdfplumber
import fitz  # PyMuPDF, used to rasterize scanned PDFs
from PIL import Image, ImageOps
from openai import (
    OpenAI,
    NotFoundError,
    APIError,
    APIConnectionError,
)
from dotenv import load_dotenv
import logging

load_dotenv()

logger = logging.getLogger("medical_extractor")

# Groq — Groq's API is OpenAI-compatible, so we reuse the OpenAI SDK
# pointed at https://api.groq.com/openai/v1. Free key (no credit card):
# https://console.groq.com/keys
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
if not GROQ_API_KEY or GROQ_API_KEY.strip() in ("", "your-groq-api-key"):
    raise RuntimeError(
        "GROQ_API_KEY is not set or is still the placeholder — copy .env.example to .env and add your "
        "actual Groq API key (create a free one at https://console.groq.com/keys)."
    )

client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
)

# Groq retires hosted models on a schedule — keep an eye on
# https://console.groq.com/docs/deprecations and override the models below
# via env vars rather than editing code.
#   * meta-llama/llama-4-scout-17b-16e-instruct shut down 2026-07-17 (old
#     default MODEL — requests to it now 404 with model_not_found).
#   * llama-3.1-8b-instant / llama-3.3-70b-versatile shut down 2026-08-16.
# Per Groq's migration guidance:
#   - MODEL (text-layer extraction, cross-checking, chat) defaults to
#     openai/gpt-oss-120b, a production model with strict json_schema support.
#   - VISION_MODEL (scanned PDFs, photos of documents) needs a multimodal
#     model: qwen/qwen3.6-27b is currently Groq's only vision chat model.
#     NOTE: it does NOT support strict json_schema — _format_ladder() drops
#     to JSON-object mode with the schema inlined in the prompt for models
#     outside _STRICT_SCHEMA_MODELS, and _completion_resilient() falls back
#     further (plain text + client-side JSON parsing) if Groq rejects a
#     generation server-side.
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
VISION_MODEL = os.environ.get("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")
FALLBACK_MODEL = os.environ.get("GROQ_FALLBACK_MODEL", "openai/gpt-oss-20b")        # cheap/fast text model for high-volume / less critical docs

# Groq's constrained-decoding strict json_schema mode is only available on
# these models (https://console.groq.com/docs/structured-outputs). Every
# other model — including the current vision model — gets JSON Object Mode
# instead (valid JSON guaranteed; schema adherence via the inlined prompt).
_STRICT_SCHEMA_MODELS = frozenset({
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-safeguard-20b",
})


def _chat_completion(**kwargs) -> Any:
    """client.chat.completions.create() with a Groq-churn-aware error.

    A request against a retired model ID comes back as a 404
    'model_not_found' (the Novice-unfriendly raw error that prompted this
    wrapper). Translate that into an actionable fix hint instead of a bare
    stack trace.
    """
    try:
        return client.chat.completions.create(**kwargs)
    except NotFoundError as e:
        model = kwargs.get("model")
        raise RuntimeError(
            f"Groq rejected model '{model}' (404 model_not_found) — it has most "
            "likely been decommissioned; Groq retires hosted models regularly. "
            "Check https://console.groq.com/docs/deprecations for the "
            "recommended replacement, then set GROQ_MODEL (text jobs) and/or "
            "GROQ_VISION_MODEL (image/scanned-PDF jobs) in .env — no code "
            f"change needed. Current defaults: text='{MODEL}', "
            f"vision='{VISION_MODEL}'."
        ) from e


# ---------------------------------------------------------------------------
# Structured-output resilience — retry + fallback ladder + tolerant parsing
# ---------------------------------------------------------------------------
# Groq validates the model's output SERVER-SIDE in json_object mode and in
# strict json_schema mode: if the generation isn't valid JSON — or the model
# hiccups and produces nothing at all, which surfaces as a 400
# 'json_validate_failed' with `failed_generation: ''` — Groq discards the
# output and rejects the whole request. The content never reaches the
# client, so no amount of defensive parsing downstream can recover it; the
# request itself must be retried and/or re-issued in a looser mode.

_RETRYABLE_STATUS_CODES = frozenset({408, 409, 429, 500, 502, 503, 504})


def _is_token_budget_error(exc: Exception) -> bool:
    """Return True for Groq's 413 response when a request exceeds its TPM cap.

    Groq reports this as ``413 Payload Too Large`` even though the uploaded
    file itself can be tiny: input tokens (including image tokens) plus the
    requested completion budget exceed the account's per-minute allowance.
    It is safe to retry this specific 413 with a smaller completion budget;
    unrelated 413 responses must still propagate.
    """
    if getattr(exc, "status_code", None) != 413:
        return False

    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            parts.append(json.dumps(body))
        except (TypeError, ValueError):
            parts.append(str(body))
    text = " ".join(parts).lower()
    return any(marker in text for marker in (
        "tokens per minute",
        "tpm",
        "rate_limit_exceeded",
        "request too large for model",
    ))


def _is_json_validation_failure(exc: Exception) -> bool:
    """True if Groq rejected the request because the model's generation
    failed server-side JSON validation (400 'json_validate_failed'). This is
    a model-side hiccup (the generation is frequently empty — see
    'failed_generation') rather than a problem with the request itself, so
    retrying — and ultimately falling back to a mode where WE parse the raw
    text — is the right recovery."""
    # 1. Check exception string or message first
    exc_str = str(exc)
    message = getattr(exc, "message", "") or ""
    if "json_validate_failed" in exc_str or "Failed to validate JSON" in exc_str:
        return True
    if "json_validate_failed" in message or "Failed to validate JSON" in message:
        return True

    # 2. Check body as dict if available
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            if error.get("code") == "json_validate_failed":
                return True
            err_msg = error.get("message")
            if isinstance(err_msg, str) and "Failed to validate JSON" in err_msg:
                return True

    # 3. Check code attribute
    code = getattr(exc, "code", None)
    if code == "json_validate_failed":
        return True

    return False


def _is_retryable_api_error(exc: Exception) -> bool:
    """Transient failures worth retrying: Groq-side JSON validation failures
    (generation discarded before we saw it), rate limits / server errors,
    and network blips. Auth (401), not-found (404), and other permanent
    errors propagate immediately."""
    if isinstance(exc, APIConnectionError):
        return True
    if _is_json_validation_failure(exc) or _is_token_budget_error(exc):
        return True
    return getattr(exc, "status_code", None) in _RETRYABLE_STATUS_CODES


def _is_vision_content(user_content: Any) -> bool:
    return isinstance(user_content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url"
        for part in user_content
    )


def _completion_token_budget(user_content: Any) -> int:
    """Choose a completion budget that fits Groq's common 8K TPM tier.

    Vision requests consume substantially more input tokens than text calls.
    Reserving 4096 output tokens made even a 94 KB image request total about
    8900 tokens and Groq rejected it before inference. Keep the legacy global
    setting for text, but cap vision to 2048 by default. A dedicated setting
    can tune vision independently for accounts with different limits.
    """
    try:
        global_budget = int(os.environ.get("GROQ_MAX_TOKENS", "4096"))
    except ValueError:
        global_budget = 4096
    global_budget = max(256, global_budget)

    if not _is_vision_content(user_content):
        return global_budget

    configured = os.environ.get("GROQ_VISION_MAX_TOKENS")
    if configured is not None:
        try:
            return max(256, int(configured))
        except ValueError:
            logger.warning(
                "Ignoring invalid GROQ_VISION_MAX_TOKENS=%r; using 2048",
                configured,
            )
    return min(global_budget, 2048)


def _format_ladder(
    model: str, strict_format: Dict[str, Any]
) -> List[Tuple[Optional[Dict[str, Any]], str]]:
    """Ordered (response_format, prompt_suffix) pairs to try for `model`,
    from most to least server-side enforcement:

    - Strict-capable models: strict json_schema -> json_object mode ->
      plain text (no response_format).
    - All other models (e.g. the qwen vision default): json_object mode ->
      plain text.

    For every rung below strict json_schema, the JSON Schema is inlined into
    the system prompt — json_object mode never sends the schema to Groq, and
    plain text obviously doesn't either, so without the inlined contract the
    model would have nothing to conform to.
    """
    schema = strict_format["json_schema"]["schema"]
    schema_suffix = (
        "\n\nCRITICAL OUTPUT RULES — you MUST follow every single one — VIOLATION WILL CAUSE SYSTEM FAILURE:\n"
        "1. Output **ONLY** a single valid JSON object as the entire response — no other text, ever.\n"
        "2. The VERY FIRST character you emit must be '{' and the VERY LAST must be '}'.\n"
        "3. No markdown, no ``` or ```json fences, no bullet points, no analysis, no preamble, no apologies, no explanations.\n"
        "4. **ABSOLUTELY NO** <think>, </think>, <thought>, <reasoning>, or any reasoning/chain-of-thought tags or hidden thinking. "
        "Your internal reasoning MUST remain hidden and MUST NOT appear in the output. "
        "Do NOT output any step-by-step, do NOT describe the document structure, do NOT say 'The user wants...'.\n"
        "5. Do NOT prefix with 'Here is the JSON:' or similar — start immediately with '{'.\n"
        "6. Conform EXACTLY to this JSON Schema (all required fields present, no extra fields):\n"
        # Compact JSON materially reduces prompt tokens on the 8K TPM tier.
        f"{json.dumps(schema, separators=(',', ':'))}\n"
        "Example of the required shape (illustrative values, adapt to the actual document):\n"
        '{\n  "document_type": "prescription",\n  "date": "2024-03-15",\n  "provider_or_doctor": "Dr. Smith",\n  "patient_name": "John Doe",\n  "medications": [],\n  "lab_results": [],\n  "allergies_noted": [],\n  "clinical_notes": null,\n  "illegible_or_low_confidence_fields": [],\n  "overall_confidence": 0.92\n}\n'
    )
    if model in _STRICT_SCHEMA_MODELS:
        return [
            (strict_format, ""),   # Groq enforces the schema server-side
            ({"type": "json_object"}, schema_suffix),
            (None, schema_suffix),  # raw text — we parse the JSON ourselves
        ]
    return [
        ({"type": "json_object"}, schema_suffix),
        (None, schema_suffix),
    ]


def _completion_resilient(
    model: str,
    system_prompt: str,
    user_content: Any,
    strict_format: Dict[str, Any],
    primary_attempts: int = 3,
    fallback_attempts: int = 2,
    backoff_seconds: float = 1.0,
) -> str:
    """Runs a chat completion against `model`, recovering from Groq's
    server-side JSON validation rejections and from client-side non-JSON outputs.

    Recovery ladder:
      1. The primary response format (strict json_schema, or json_object
         mode for models without strict support), retried `primary_attempts`
         times — empty/invalid generations are usually transient.
      2. Looser rungs from _format_ladder() (json_object mode, then plain
         text with the schema still inlined in the prompt), retried
         `fallback_attempts` times each. In plain-text mode Groq does not
         validate anything, so the raw content comes back to us and is
         parsed client-side (see _parse_json_object) — recovering
         generations Groq would otherwise have discarded, e.g. JSON wrapped
         in markdown fences or preceded by commentary.

    Additionally validates that the returned content is actually parseable
    as JSON (via _parse_json_object). If the model returns a non-JSON
    reasoning dump (e.g. "<think> The user wants..." without any JSON),
    that is treated as a transient failure and retried — previously this
    would have been returned as success and only failed later in the
    caller with a confusing "could not be parsed" error.

    Returns the raw assistant message content (callers parse it with
    _parse_json_object). Raises RuntimeError with a plain-language
    explanation if every attempt fails.
    """
    ladder = _format_ladder(model, strict_format)
    # Tune attempts: vision models (non-strict) tend to fail json_object consistently with <think>,
    # so waste fewer retries there and give more retries to plain-text where we control parsing.
    if model not in _STRICT_SCHEMA_MODELS:
        primary_attempts = min(primary_attempts, 2)
        fallback_attempts = max(fallback_attempts, 3)
    last_error: Optional[Exception] = None
    total_attempts = 0
    last_raw_snippet: str = ""
    max_tokens = _completion_token_budget(user_content)

    for level, (response_format, prompt_suffix) in enumerate(ladder):
        attempts = primary_attempts if level == 0 else fallback_attempts
        messages = [
            {"role": "system", "content": system_prompt + prompt_suffix},
            {"role": "user", "content": user_content},
        ]
        for attempt in range(1, attempts + 1):
            total_attempts += 1
            try:
                request_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": messages,
                    "temperature": 0,
                    "top_p": 1,
                }
                # OpenAI SDK accepts max_tokens for Groq compatibility. Vision
                # uses a lower budget because image tokens count toward TPM.
                request_kwargs["max_tokens"] = max_tokens
                if response_format is not None:
                    # response_format=None means plain-text mode — omit the kwarg entirely
                    request_kwargs["response_format"] = response_format
                response = _chat_completion(**request_kwargs)
                raw = response.choices[0].message.content or ""
                if not raw or not raw.strip():
                    raise ValueError("model returned an empty response — no JSON to parse")
                # Validate parseability before returning: if raw contains no parseable JSON,
                # treat as transient failure and retry (covers <think>-only outputs in plain-text mode)
                try:
                    _parse_json_object(raw)
                except ValueError as parse_err:
                    last_error = parse_err
                    last_raw_snippet = raw[:500]
                    logger.warning(
                        "_completion_resilient: model='%s' level=%d attempt=%d returned non-JSON (snippet %r), retrying: %s",
                        model, level, attempt, raw[:250].replace(chr(10), " "), parse_err,
                    )
                    if level == len(ladder) - 1 and attempt == attempts:
                        break
                    time.sleep(backoff_seconds * attempt)
                    continue
                return raw
            except APIError as e:
                if not _is_retryable_api_error(e):
                    raise
                last_error = e
                last_raw_snippet = str(e)[:500]
                if _is_token_budget_error(e):
                    # A provider-side 413 here is not an oversized upload. It
                    # means prompt/image tokens + max_tokens exceed TPM. Retry
                    # with less output headroom instead of returning a 422.
                    reduced_budget = max(256, max_tokens // 2)
                    if reduced_budget < max_tokens:
                        logger.warning(
                            "Groq token budget rejected model='%s' request; "
                            "reducing max_tokens from %d to %d",
                            model, max_tokens, reduced_budget,
                        )
                        max_tokens = reduced_budget
                if level == len(ladder) - 1 and attempt == attempts:
                    break  # last rung exhausted — no point sleeping first
                time.sleep(backoff_seconds * attempt)
            except ValueError as e:
                # Empty or non-parseable that we raised above already handled; but also catch direct raise
                last_error = e
                if level == len(ladder) - 1 and attempt == attempts:
                    break
                # Already logged for parse case; log empty case here
                if "empty response" in str(e):
                    logger.warning("_completion_resilient: model='%s' empty response on attempt %d", model, attempt)
                time.sleep(backoff_seconds * attempt)
                continue

    # All ladder rungs exhausted — try repair strategies before giving up
    if last_error is not None and ("could not be parsed" in str(last_error) or "empty response" in str(last_error)):
        # Strategy 1: If this was a vision call (user_content contains image), retry once with a very explicit repair prompt
        # that includes the original image and tells the model its previous output was invalid.
        is_vision_call = _is_vision_content(user_content)
        if is_vision_call:
            try:
                logger.info("Attempting vision repair retry with explicit JSON-only instruction for model=%s", model)
                repair_system_vision = (
                    "You are a medical document extraction engine. Your previous response was INVALID because it contained "
                    "reasoning, analysis, or <think> tags instead of ONLY JSON. Now you MUST output ONLY a single valid JSON object. "
                    "The very first character must be '{' and the last must be '}'. No <think>, no markdown, no explanations. "
                    "Conform exactly to the provided JSON Schema."
                )
                # Build repair user content: keep the original image but replace text with repair instruction
                repair_text = (
                    f"Previous attempt failed: {str(last_error)[:300]}. Last snippet: {last_raw_snippet[:400]!r}. "
                    "Now extract structured data from this medical document image and output ONLY the JSON object, starting with '{'."
                )
                # Preserve image_url entries from original user_content
                image_parts = [c for c in user_content if isinstance(c, dict) and c.get("type") == "image_url"]
                repair_user_content = [{"type": "text", "text": repair_text}] + image_parts
                repair_messages = [
                    {"role": "system", "content": repair_system_vision + "\nSchema: " + json.dumps(strict_format["json_schema"]["schema"], indent=2)},
                    {"role": "user", "content": repair_user_content},
                ]
                repair_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": repair_messages,
                    "temperature": 0,
                    "top_p": 1,
                    "max_tokens": max_tokens,
                    # No response_format — use plain text so we can parse ourselves even if model adds stray text
                }
                resp = _chat_completion(**repair_kwargs)
                raw_repair_vision = resp.choices[0].message.content or ""
                if raw_repair_vision and raw_repair_vision.strip():
                    try:
                        _parse_json_object(raw_repair_vision)
                        logger.info("Vision repair retry succeeded")
                        return raw_repair_vision
                    except ValueError as ve:
                        logger.warning("Vision repair also not parseable: %s (snippet %r)", ve, raw_repair_vision[:250])
                        last_error = ve
                        last_raw_snippet = raw_repair_vision[:500]
            except Exception as repair_e:
                logger.warning("Vision repair attempt failed: %s", repair_e)
        # Strategy 2: Fallback to text model stub (no image) so upload does not completely fail
        if model != FALLBACK_MODEL and FALLBACK_MODEL:
            try:
                logger.info("Attempting fallback text-model repair via %s for final JSON recovery", FALLBACK_MODEL)
                repair_system = (
                    "You are a medical document extraction fallback. The primary vision model failed to produce valid JSON. "
                    "You will be given the error snippet and must output a minimal valid JSON object conforming to the required schema. "
                    "If you cannot infer fields, use null/empty arrays with low confidence and note the failure in illegible_or_low_confidence_fields. "
                    "Output ONLY JSON, starting with '{' ."
                )
                repair_user = (
                    f"Primary model '{model}' failed after {total_attempts} attempts. Last error: {last_error}. "
                    f"Last raw snippet: {last_raw_snippet[:800]!r}. "
                    f"Schema: {json.dumps(strict_format['json_schema']['schema'], indent=2)}. "
                    "Produce a valid JSON object now."
                )
                strict_kwargs: Dict[str, Any] = {
                    "model": FALLBACK_MODEL,
                    "messages": [{"role": "system", "content": repair_system}, {"role": "user", "content": repair_user}],
                    "response_format": strict_format,
                    "temperature": 0,
                    "max_tokens": 2000,
                }
                resp = _chat_completion(**strict_kwargs)
                raw_repair = resp.choices[0].message.content or ""
                if raw_repair and raw_repair.strip():
                    try:
                        _parse_json_object(raw_repair)
                        logger.info("Fallback repair succeeded via %s", FALLBACK_MODEL)
                        return raw_repair
                    except ValueError:
                        logger.warning("Fallback repair also not parseable, discarding")
            except Exception as repair_e:
                logger.warning("Fallback repair failed: %s", repair_e)

    raise RuntimeError(
        f"Model '{model}' repeatedly failed to return valid structured JSON "
        f"({total_attempts} attempt(s) across {len(ladder)} fallback "
        "level(s), including retries with a looser output format). This is "
        "usually a transient hiccup on the model provider's side — please "
        "retry the upload. If the same file keeps failing, it may be too "
        "blurry, rotated, or mostly handwritten; try a clearer photo or a "
        f"higher-resolution scan. Last snippet: {last_raw_snippet[:250]!r}"
    ) from last_error


# Tags used by reasoning models (e.g. DeepSeek-R1, Qwen-QwQ, Groq
# "reasoning" variants) to delimit their chain-of-thought. These must be
# stripped before we attempt to locate/parse the JSON object — otherwise
# the <think> opener sits ahead of the first "{" and our brace-scan
# returns a span that still contains the un-closed tag (or, in the
# "unterminated think" case, the whole response is one long think block).
# Covers <think>, <thinking>, <thought>, <reasoning>, <analysis> variants
# and handles HTML-encoded forms (&lt;think&gt;) that appear in logs.
_THINK_BLOCK_RE = re.compile(
    r"<\s*(think|thinking|thought|reasoning|analysis)\s*>.*?<\s*/\s*(think|thinking|thought|reasoning|analysis)\s*>",
    flags=re.DOTALL | re.IGNORECASE,
)
_THINK_OPEN_RE = re.compile(r"<\s*(think|thinking|thought|reasoning|analysis)\s*>", flags=re.IGNORECASE)
# Also handle HTML-entity encoded tags that sometimes surface in logging/transport
_THINK_ENCODED_BLOCK_RE = re.compile(
    r"&lt;\s*(think|thinking|thought|reasoning|analysis)\s*&gt;.*?&lt;\s*/\s*(think|thinking|thought|reasoning|analysis)\s*&gt;",
    flags=re.DOTALL | re.IGNORECASE,
)
_THINK_ENCODED_OPEN_RE = re.compile(r"&lt;\s*(think|thinking|thought|reasoning|analysis)\s*&gt;", flags=re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    """Remove reasoning/chain-of-thought blocks from model output.

    Covers <think>...</think> and variants (<thinking>, <thought>,
    <reasoning>, <analysis>) plus HTML-encoded forms. Also handles the
    "unterminated think" case where the model opens a tag and never
    closes it before the JSON (a few Groq reasoning variants do this
    under load); in that case we keep everything from the first "{" after
    the opener onward, dropping the reasoning preamble.
    """
    if not text:
        return text
    # Decode HTML entities for tag detection but keep original for JSON extraction
    # First remove encoded blocks
    cleaned = _THINK_ENCODED_BLOCK_RE.sub("", text)
    # Then standard blocks
    cleaned = _THINK_BLOCK_RE.sub("", cleaned)

    # Handle any remaining open tags (no closer) — drop preamble up to first JSON brace
    # Do this for both literal and encoded openers
    for pattern in (_THINK_OPEN_RE, _THINK_ENCODED_OPEN_RE):
        while pattern.search(cleaned):
            m = pattern.search(cleaned)
            assert m is not None
            tail = cleaned[m.end():]
            # Check if there's a closer of either form after opener
            closer = re.search(r"<\s*/\s*(think|thinking|thought|reasoning|analysis)\s*>", tail, flags=re.IGNORECASE)
            closer_enc = re.search(r"&lt;\s*/\s*(think|thinking|thought|reasoning|analysis)\s*&gt;", tail, flags=re.IGNORECASE)
            closer_pos = None
            if closer and closer_enc:
                closer_pos = closer.start() if closer.start() < closer_enc.start() else closer_enc.start()
                closer_end = closer.end() if closer.start() < closer_enc.start() else closer_enc.end()
            elif closer:
                closer_pos = closer.start()
                closer_end = closer.end()
            elif closer_enc:
                closer_pos = closer_enc.start()
                closer_end = closer_enc.end()
            if closer_pos is not None:
                tail = tail[closer_end:]
            else:
                # No closer: assume first top-level "{" starts JSON payload
                brace = tail.find("{")
                if brace != -1:
                    tail = tail[brace:]
                else:
                    # No JSON at all after <think> — drop the opener and rest
                    # so downstream parsers raise appropriate error
                    tail = ""
            cleaned = cleaned[:m.start()] + tail
    return cleaned


def _find_first_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Find and parse the *first* top-level JSON object in text using
    proper brace-depth counting (handles strings, escaped quotes, etc.).
    This is far more reliable than simple find('{') / rfind('}') when
    the model emits commentary, markdown, or puts JSON inside <think> blocks.

    Returns the dict if a valid top-level JSON *object* is found, else None.
    """
    if not text or not isinstance(text, str):
        return None
    text = text.strip()
    if "{" not in text:
        return None
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "{":
            depth = 0
            start = i
            j = i
            in_string = False
            escape = False
            while j < n:
                ch = text[j]
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    if not escape:
                        in_string = not in_string
                elif not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            candidate = text[start : j + 1]
                            try:
                                obj = json.loads(candidate)
                                if isinstance(obj, dict):
                                    return obj
                            except (json.JSONDecodeError, TypeError, ValueError):
                                repaired = _try_repair_json(candidate)
                                if repaired is not None:
                                    return repaired
                            i = j + 1
                            break
                j += 1
            else:
                break
        i += 1
    return None


def _try_repair_json(candidate: str) -> Optional[Dict[str, Any]]:
    """Attempt to repair common LLM JSON mistakes and parse.

    Handles: trailing commas, single-quoted strings, unescaped control chars,
    and BOM. Returns dict if repair succeeds, else None.
    """
    if not candidate:
        return None
    cleaned = candidate.lstrip("\ufeff\u200b\u200c\u200d").strip()
    try:
        obj = json.loads(cleaned)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    try:
        no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
        obj = json.loads(no_trailing)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    if "'" in cleaned and '"' not in cleaned[:500]:
        try:
            import ast
            obj = ast.literal_eval(cleaned)
            if isinstance(obj, dict):
                return json.loads(json.dumps(obj))
        except Exception:
            pass
    try:
        m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", cleaned, flags=re.DOTALL)
        if m:
            inner = m.group(1).strip()
            obj = json.loads(inner)
            if isinstance(obj, dict):
                return obj
            no_trailing2 = re.sub(r",\s*([}\]])", r"\1", inner)
            obj = json.loads(no_trailing2)
            if isinstance(obj, dict):
                return obj
    except json.JSONDecodeError:
        pass
    return None


def _parse_json_object(raw: str) -> Dict[str, Any]:
    """Robustly parse a model's raw output into a JSON object.

    Tolerates the ways LLMs mangle JSON output even when told not to:
    reasoning/chain-of-thought blocks (<think>...</think>), markdown code
    fences (```json ... ```), prose/commentary wrapped around the object,
    trailing commas, single quotes, and trailing junk after the closing brace.
    Raises ValueError with a diagnostic snippet if nothing parseable is found.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("model returned an empty response — no JSON to parse")

    raw_stripped = raw.strip().lstrip("\ufeff")

    text = _strip_reasoning(raw_stripped)
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    repaired = _try_repair_json(text)
    if repaired is not None:
        return repaired

    obj = _find_first_json_object(text)
    if obj is not None:
        return obj

    for source in (text, raw_stripped):
        fenced = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", source, flags=re.DOTALL | re.IGNORECASE)
        if fenced:
            candidate = fenced.group(1).strip()
            candidate = candidate.replace("&lt;", "<").replace("&gt;", ">")
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
            repaired2 = _try_repair_json(candidate)
            if repaired2 is not None:
                return repaired2
            obj2 = _find_first_json_object(candidate)
            if obj2 is not None:
                return obj2

    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        span = text[start:end + 1]
        span = _strip_reasoning(span)
        span = span.replace("&lt;", "<").replace("&gt;", ">")
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            pass
        repaired3 = _try_repair_json(span)
        if repaired3 is not None:
            return repaired3
        obj3 = _find_first_json_object(span)
        if obj3 is not None:
            return obj3

    raw_decoded = raw_stripped.replace("&lt;", "<").replace("&gt;", ">")
    obj4 = _find_first_json_object(raw_decoded)
    if obj4 is not None:
        return obj4
    obj5 = _find_first_json_object(raw_stripped)
    if obj5 is not None:
        return obj5

    s_idx, e_idx = raw_decoded.find("{"), raw_decoded.rfind("}")
    if s_idx != -1 and e_idx > s_idx:
        candidate = raw_decoded[s_idx:e_idx+1]
        repaired4 = _try_repair_json(candidate)
        if repaired4 is not None:
            return repaired4
        obj6 = _find_first_json_object(candidate)
        if obj6 is not None:
            return obj6

    snippet = raw_stripped[:350].replace("\n", " ").replace("\r", "")
    raise ValueError(f"model output could not be parsed as JSON (starts with: {snippet!r})")

#---------------------------------------------------------------------------
# 1. Extraction schema — keeps every document's output shape consistent
# ---------------------------------------------------------------------------

EXTRACTION_SCHEMA_PROMPT = """
You are a medical document extraction engine. You will be shown an image of
a medical document (prescription, lab report, or discharge summary).

**CRITICAL INSTRUCTION — FOLLOW EXACTLY:**
- Output **ONLY** a single valid JSON object. Nothing else.
- Do **NOT** output any <think>, </think>, reasoning, chain-of-thought, 
  explanations, bullet points, markdown, or any text before or after the JSON.
- The very first character of your response must be '{' and the last must be '}'.
- If you are a reasoning model, you MUST put any thinking inside your internal 
  process only — the final answer sent to the user MUST be pure JSON with no 
  <think> wrapper at all.

Extract every field defined in the JSON schema provided. For medications,
always attempt to identify the active ingredient(s) using your medical
knowledge, even if the document only prints a brand name (e.g. brand
"Panadol" -> ingredients ["Paracetamol"]). Use an empty array only if the
ingredient is genuinely unknown/undeterminable.

CONFIDENCE SCORING — anchor every confidence value to these bands. Do not
default to a high score; think about which band actually applies before
writing a number:
- 0.90-1.00: text is clearly printed/typed and the field maps to the schema
  with no judgment required.
- 0.60-0.89: text is legible but you had to exercise judgment — expanding an
  abbreviation, reading a partially cut-off table cell, or inferring an
  active ingredient from a brand name that was NOT itself printed on the
  document.
- Below 0.60: handwriting is genuinely hard to read, the text is blurry or
  cut off, or you are inferring a value rather than reading one directly off
  the page.
A medication's active ingredient being inferred (not printed) rather than
read directly is, by itself, enough to keep that medication's confidence
below 0.90 — brand-to-generic mapping is your knowledge substituting for
what the document actually says, not a transcription.

LANGUAGE AND UNIT NORMALIZATION — documents may be in any language, and a
patient's timeline may combine documents from several languages. Two
prescriptions for the same drug at the same dose must be recognizable as
the same regardless of what language or units each was printed in:
- ingredients must always be the English INN (International Nonproprietary
  Name) / generic drug name, regardless of the document's language (e.g.
  "Amoxicilina" (Spanish) or "アモキシシリン" (Japanese) -> ingredients:
  ["Amoxicillin"]).
- dosage and frequency stay exactly as printed, in the original language —
  these are for human/audit display, so a reviewer can see literally what
  the document said.
- dosage_value / dosage_unit are your best-effort NORMALIZED numeric dose,
  independent of source language: "500 mg" -> dosage_value=500,
  dosage_unit="mg"; "0.5 g" -> dosage_value=500, dosage_unit="mg" (convert
  mass units to mg so entries become directly comparable); "5 mL" ->
  dosage_value=5, dosage_unit="mL" (do not convert volume/count/unit-based
  dosing). Use null for both if the dose can't be reduced to one
  value+unit (e.g. a titration schedule).
- frequency_per_day is your best-effort NORMALIZED doses-per-day count,
  independent of source language or phrasing — "cada 8 horas" (Spanish),
  "3 fois par jour" (French), and "3x daily" (English) must all normalize
  to frequency_per_day=3. Set is_as_needed=true (and frequency_per_day=
  null) for PRN/as-needed dosing with no fixed daily count. Set
  is_as_needed=false and frequency_per_day=null only if genuinely
  indeterminate.
- Watch for locale-specific number formatting: some locales use a comma as
  the decimal separator (e.g. "1,5 g" means 1.5 grams, not 15 grams).
  Misreading this is a real dosing error, not a cosmetic one.
- Translating an ingredient name, converting a unit, or resolving a
  frequency phrase is itself inference, not transcription — factor that
  into the medication's confidence the same way an inferred brand-to-
  generic mapping is.

Rules:
- If handwriting is unclear, make your best guess but LOWER the confidence
  score for that field and add a note to illegible_or_low_confidence_fields.
- Never invent data. Use null for missing string fields (per the schema).
- Do not provide medical advice or diagnosis — extraction only.
"""

# Strict JSON Schema (OpenAI Structured Outputs) — guarantees every field,
# including "ingredients", is always present in the response.
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": ["prescription", "lab_report", "discharge_summary", "other"],
        },
        "date": {"type": ["string", "null"]},
        "provider_or_doctor": {"type": ["string", "null"]},
        "patient_name": {"type": ["string", "null"]},
        "medications": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "ingredients": {"type": "array", "items": {"type": "string"}},
                    "dosage": {"type": "string"},
                    "frequency": {"type": "string"},
                    "duration": {"type": ["string", "null"]},
                    "dosage_value": {"type": ["number", "null"]},
                    "dosage_unit": {"type": ["string", "null"]},
                    "frequency_per_day": {"type": ["number", "null"]},
                    "is_as_needed": {"type": "boolean"},
                    "confidence": {"type": "number"},
                },
                "required": [
                    "name", "ingredients", "dosage", "frequency", "duration",
                    "dosage_value", "dosage_unit", "frequency_per_day", "is_as_needed",
                    "confidence",
                ],
                "additionalProperties": False,
            },
        },
        "lab_results": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "test_name": {"type": "string"},
                    "value": {"type": "string"},
                    "unit": {"type": ["string", "null"]},
                    "reference_range": {"type": ["string", "null"]},
                    "flag": {"type": "string", "enum": ["normal", "high", "low", "unknown"]},
                    "confidence": {"type": "number"},
                },
                "required": ["test_name", "value", "unit", "reference_range", "flag", "confidence"],
                "additionalProperties": False,
            },
        },
        "allergies_noted": {"type": "array", "items": {"type": "string"}},
        "clinical_notes": {"type": ["string", "null"]},
        "illegible_or_low_confidence_fields": {"type": "array", "items": {"type": "string"}},
        "overall_confidence": {"type": "number"},
    },
    "required": [
        "document_type", "date", "provider_or_doctor", "patient_name",
        "medications", "lab_results", "allergies_noted", "clinical_notes",
        "illegible_or_low_confidence_fields", "overall_confidence",
    ],
    "additionalProperties": False,
}

EXTRACTION_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "medical_document_extraction",
        "strict": True,
        "schema": EXTRACTION_JSON_SCHEMA,
    },
}


# ---------------------------------------------------------------------------
# 2. File-type detection and preprocessing
# ---------------------------------------------------------------------------

def pdf_has_text_layer(pdf_path: str, min_chars: int = 30) -> bool:
    """Quick check: does this PDF have a usable embedded text layer?"""
    with pdfplumber.open(pdf_path) as pdf:
        total_chars = 0
        for page in pdf.pages[:3]:  # sample first few pages only
            text = page.extract_text() or ""
            total_chars += len(text.strip())
        return total_chars >= min_chars


def extract_text_from_pdf(pdf_path: str) -> str:
    """Direct text extraction for digital PDFs (no OCR/vision needed)."""
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            chunks.append(f"--- Page {i + 1} ---\n{text}")
    return "\n\n".join(chunks)


def pdf_pages_to_images(pdf_path: str, dpi: int = 200) -> List[Image.Image]:
    """Render each page of a scanned/image-only PDF into a PIL image."""
    images = []
    doc = fitz.open(pdf_path)
    zoom = dpi / 72
    matrix = fitz.Matrix(zoom, zoom)
    for page in doc:
        pix = page.get_pixmap(matrix=matrix)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    doc.close()
    return images


def image_to_base64(img: Image.Image) -> str:
    # Downscale image if too large to prevent huge base64 payload size and potential network/timeout/size issues.
    # 1600px is more than enough for medical document OCR.
    max_side = 1600
    if max(img.size) > max_side:
        scale = max_side / max(img.size)
        new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
        img = img.resize(new_size, Image.Resampling.LANCZOS)

    # Save as JPEG with quality=85 (highly compressed yet legible for OCR).
    # PNG format is uncompressed losslessly, inflating base64 payload sizes to 15-20MB.
    # JPEG format reduces payload to ~150-300KB (100x lighter and faster).
    buf = io.BytesIO()
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")
    img.save(buf, format="JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ---------------------------------------------------------------------------
# 3. Vision extraction call
# ---------------------------------------------------------------------------

def extract_from_image(img: Image.Image, model: str = VISION_MODEL) -> Dict[str, Any]:
    """Send a single page image to the vision model and parse structured JSON.

    Uses the resilient completion runner: Groq validates JSON output
    server-side, and a model hiccup surfaces as a 400 'json_validate_failed'
    with the generation discarded (commonly an empty `failed_generation`).
    The runner retries, then falls back to looser output modes so the raw
    text comes back to us for tolerant parsing instead of failing the whole
    upload with a raw provider error.
    """
    b64 = image_to_base64(img)

    raw = _completion_resilient(
        model=model,
        system_prompt=EXTRACTION_SCHEMA_PROMPT,
        user_content=[
            {
                "type": "text",
                "text": "Extract structured data from this medical document image.",
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
            },
        ],
        strict_format=EXTRACTION_RESPONSE_FORMAT,
    )
    return _parse_json_object(raw)


def extract_from_text(text: str, model: str = MODEL) -> Dict[str, Any]:
    """For digital PDFs — run the same schema extraction on plain text.

    Same server-side JSON-validation resilience as extract_from_image().
    """
    raw = _completion_resilient(
        model=model,
        system_prompt=EXTRACTION_SCHEMA_PROMPT,
        user_content=f"Extract structured data from this document text:\n\n{text}",
        strict_format=EXTRACTION_RESPONSE_FORMAT,
    )
    return _parse_json_object(raw)


VISION_OCR_CONFIDENCE_CEILING = 0.85  # a vision/handwriting read is never "fully certain"


def _apply_confidence_ceiling(result: Dict[str, Any], ceiling: float) -> Dict[str, Any]:
    """
    Caps every confidence value in an extraction result at `ceiling`. Used
    for vision_ocr-sourced documents (scanned PDFs, photographed
    prescriptions) so a model's self-reported 0.95 on a handwriting read
    can't outrank what the extraction method itself can actually support.
    Text-layer (text_layer) extractions are left uncapped since those come
    from a digital text source, not a visual read.
    """
    if "overall_confidence" in result and isinstance(result["overall_confidence"], (int, float)):
        result["overall_confidence"] = min(result["overall_confidence"], ceiling)
    for med in result.get("medications", []) or []:
        if isinstance(med.get("confidence"), (int, float)):
            med["confidence"] = min(med["confidence"], ceiling)
    for lab in result.get("lab_results", []) or []:
        if isinstance(lab.get("confidence"), (int, float)):
            lab["confidence"] = min(lab["confidence"], ceiling)
    return result


def looks_like_medical_text(text: str, filename: str) -> bool:
    """
    Analyzes raw text from a text-layer PDF to see if it represents a medical
    document. This is a local, fast, deterministic check to avoid calling
    the expensive LLM on completely non-medical text files like CVs,
    receipts, boarding passes, etc.
    """
    text_lower = text.lower()
    fn_lower = filename.lower()
    
    # 1. Filename-based non-medical indicators
    has_cv_filename = any(p in fn_lower for p in ("cv", "resume", "portfolio"))
    
    # 2. Text-based non-medical indicators (e.g. CV / Resume keywords)
    cv_keywords = [
        "curriculum vitae", "education", "experience", "skills", "projects", 
        "languages", "publications", "employment", "work history", "hobbies", 
        "interests", "about me", "academic history", "professional summary"
    ]
    cv_matches = 0
    for kw in cv_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            cv_matches += 1
    
    # 3. Medical keyword density
    medical_keywords = [
        "prescription", "rx", "medication", "medicine", "drug", "tablet", "capsule",
        "dosage", "dose", "frequency", "mg", "g", "ml", "lab", "laboratory", "report",
        "test", "results", "analysis", "allergy", "allergies", "clinical", "hospital",
        "clinic", "treatment", "diagnosis", "discharge", "summary", "patient", "doctor",
        "physician"
    ]
    medical_matches = 0
    for kw in medical_keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text_lower):
            medical_matches += 1
    
    # If the filename or the text has strong CV indicators and very low medical keyword matches, it is rejected.
    if has_cv_filename and medical_matches < 3:
        return False
        
    if re.search(r'\bcurriculum vitae\b|\bresume\b', text_lower) and medical_matches < 3:
        return False
        
    if cv_matches >= 3 and medical_matches < 2:
        return False
        
    return True


def assert_text_looks_medical(text: str, filename: str) -> None:
    """
    Deterministic pre-LLM validation check. Raises NonMedicalDocumentError
    if the raw text does not appear to be a medical document.
    """
    from document_filter import NonMedicalDocumentError
    
    if not looks_like_medical_text(text, filename):
        raise NonMedicalDocumentError(
            filename,
            "raw text analysis indicates this is a non-medical document (e.g. CV/Resume) with low medical relevance."
        )


# ---------------------------------------------------------------------------
# 4. Top-level entry point — routes any uploaded file correctly
# ---------------------------------------------------------------------------

def process_document(
    file_path: str,
    model: str = MODEL,
    vision_model: str = VISION_MODEL,
) -> Dict[str, Any]:
    """
    Accepts a path to a PDF or image file. Detects type and routes to the
    right extraction path (`model` for text-layer PDFs, `vision_model` for
    scanned pages and image files). Returns structured JSON (or a list of
    per-page JSON objects for multi-page scanned PDFs).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    # --- Friendly diagnostics for the most common mistakes ---
    if ".zip" in file_path.lower():
        raise ValueError(
            "This path still points INSIDE a .zip file — that doesn't work. "
            "Right-click the .zip in File Explorer, choose 'Extract All', "
            "then re-run this script pointing at the EXTRACTED folder "
            "(the path should not contain '.zip' anywhere)."
        )
    if not path.exists():
        raise FileNotFoundError(
            f"Path does not exist: {file_path}\n"
            "  Common causes: the .zip wasn't extracted yet, a typo in the "
            "path, or a trailing backslash right before a closing quote "
            "(e.g. \"...\\Year 1\\\" breaks Windows' command-line parsing — "
            "remove the final backslash so it ends \"...\\Year 1\")."
        )
    if path.is_dir():
        raise IsADirectoryError(
            f"'{file_path}' is a folder, not a file. Pass it directly to "
            "process_patient_folder(), or from the command line just run: "
            f'python medical_extractor.py "{file_path}"  (without pointing '
            "at a specific file — the script auto-detects folders)."
        )
    if suffix not in (".pdf", ".png", ".jpg", ".jpeg", ".webp"):
        raise ValueError(
            f"Unsupported file type '{suffix or '(no extension)'}' for "
            f"'{file_path}'. Supported: .pdf, .png, .jpg, .jpeg, .webp"
        )
    # --- End diagnostics ---

    if suffix == ".pdf":
        if pdf_has_text_layer(file_path):
            text = extract_text_from_pdf(file_path)
            # deterministic check on the text layer before calling OpenAI/Groq API
            assert_text_looks_medical(text, path.name)
            result = extract_from_text(text, model=model)
            result["_source"] = {"file": path.name, "method": "text_layer"}
            return result
        else:
            # Scanned PDF -> render pages -> vision extraction per page
            pages = pdf_pages_to_images(file_path)
            page_results = []
            for i, img in enumerate(pages):
                res = extract_from_image(img, model=vision_model)
                res = _apply_confidence_ceiling(res, VISION_OCR_CONFIDENCE_CEILING)
                res["_source"] = {
                    "file": path.name,
                    "method": "vision_ocr",
                    "page": i + 1,
                }
                page_results.append(res)
            return {"multi_page": True, "pages": page_results}

    else:  # image types
        img = Image.open(file_path)
        # Phone photos carry an EXIF orientation tag instead of rotated
        # pixels — apply it, or the vision model reads the document
        # sideways/upside-down and extraction silently degrades.
        img = ImageOps.exif_transpose(img)
        result = extract_from_image(img, model=vision_model)
        result = _apply_confidence_ceiling(result, VISION_OCR_CONFIDENCE_CEILING)
        result["_source"] = {"file": path.name, "method": "vision_ocr"}
        return result


def process_patient_folder(
    folder_path: str,
    model: str = MODEL,
    vision_model: str = VISION_MODEL,
) -> List[Dict[str, Any]]:
    """
    Walks a patient's folder (including subfolders like 'Year 1', 'Year 2')
    and processes every supported document it finds. Returns a flat list of
    extraction results, same shape as calling process_document() repeatedly.
    """
    supported = {".pdf", ".png", ".jpg", ".jpeg", ".webp"}
    folder = Path(folder_path)

    if not folder.exists():
        raise FileNotFoundError(f"Folder not found: {folder_path}")

    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in supported
    )

    if not files:
        print(f"No supported documents found in {folder_path}")
        return []

    results = []
    for f in files:
        print(f"Extracting {f} ...")
        try:
            result = process_document(str(f), model=model, vision_model=vision_model)
            results.append(result)
        except Exception as e:
            print(f"  Failed: {e}")

    return results


# ---------------------------------------------------------------------------
# 5. Timeline builder — merge multiple documents into one patient timeline
# ---------------------------------------------------------------------------

def _flatten_documents(raw_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Multi-page scanned PDFs return {'multi_page': True, 'pages': [...]}.
    Flatten everything into a single flat list of per-document dicts."""
    flat = []
    for r in raw_results:
        if r.get("multi_page"):
            flat.extend(r["pages"])
        else:
            flat.append(r)
    return flat


def _is_demo_document(d: Dict[str, Any]) -> bool:
    """Detect placeholder/template documents (e.g. sample datasets that
    include a 'DEMO PATIENT' / 'DEMO MEDICINE' mock page) so they don't get
    silently treated as real patient data."""
    name = (d.get("patient_name") or "").upper()
    if "DEMO" in name or "SAMPLE" in name or "DUMMY" in name:
        return True
    for med in d.get("medications", []):
        med_name = (med.get("name") or "").upper()
        if "DEMO" in med_name or "SAMPLE" in med_name:
            return True
    return False


def _normalize_patient_key(name: Any) -> str:
    """Group documents by patient name. Missing/null names go into their
    own 'unknown_patient' bucket rather than being silently merged with
    everything else."""
    if not name or not isinstance(name, str) or not name.strip():
        return "unknown_patient"
    return name.strip().lower()


def group_documents_by_patient(
    raw_results: List[Dict[str, Any]], drop_demo_documents: bool = True
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Splits a flat list of extracted documents into groups keyed by patient
    name. This prevents unrelated prescriptions (e.g. a folder that
    accidentally contains sample docs for different people) from being
    merged into one timeline and cross-checked against each other.

    Returns: { "amit sharma": [doc, doc, ...], "mary smith": [...], ... }
    Also prints a warning if more than one distinct real patient is found,
    or if demo/placeholder documents were dropped.
    """
    docs = _flatten_documents(raw_results)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    dropped = []

    for d in docs:
        if drop_demo_documents and _is_demo_document(d):
            dropped.append(d.get("_source", {}).get("file", "unknown_file"))
            continue
        key = _normalize_patient_key(d.get("patient_name"))
        groups.setdefault(key, []).append(d)

    if dropped:
        print(f"  Skipped {len(dropped)} demo/placeholder document(s): {dropped}")

    real_patients = [k for k in groups if k != "unknown_patient"]
    if len(real_patients) > 1:
        print(
            f"  WARNING: found {len(real_patients)} distinct patient names in this "
            f"batch ({real_patients}) — building a SEPARATE timeline for each, "
            f"they will NOT be cross-checked against one another."
        )

    return groups


def _parse_timeline_date(date_str: Optional[str]):
    """Best-effort parse of wildly varying date formats in extracted docs.
    Returns datetime or None for unparseable/missing dates. Used only for
    sorting, so failure falls back to far-future."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        from dateutil import parser as _date_parser
        return _date_parser.parse(date_str, fuzzy=True)
    except Exception:
        return None


def build_patient_timeline(raw_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge extracted documents (output of process_document, one per file) into
    a single chronological patient timeline: one entry per visit/document,
    sorted by date, plus flattened rollups of all medications and lab
    results for easy downstream cross-checking.

    NOTE: assumes all documents passed in already belong to ONE patient.
    Use group_documents_by_patient() first if a batch might mix patients
    or contain demo/placeholder documents.
    """
    docs = _flatten_documents(raw_results)

    # Sort by parsed date; undated/unparseable docs go to the end.
    # Previously sorted by raw string which broke for formats like
    # "05 Jan 2026" vs "20 Apr 2026" (lexicographic != chronological).
    def sort_key(d):
        dt = _parse_timeline_date(d.get("date"))
        # Use max datetime for missing, and original string as tiebreaker for stability
        return (dt is None, dt or d.get("date") or "9999-99-99")

    docs_sorted = sorted(docs, key=sort_key)

    all_medications = []
    all_lab_results = []
    all_allergies = set()

    for d in docs_sorted:
        visit_date = d.get("date")
        source_file = d.get("_source", {}).get("file")

        for med in d.get("medications", []):
            all_medications.append({**med, "date": visit_date, "source_file": source_file})

        for lab in d.get("lab_results", []):
            all_lab_results.append({**lab, "date": visit_date, "source_file": source_file})

        for allergy in d.get("allergies_noted", []) or []:
            all_allergies.add(allergy)

    return {
        "visits": docs_sorted,               # one entry per document, chronological
        "medications_timeline": all_medications,
        "lab_results_timeline": all_lab_results,
        "known_allergies": sorted(all_allergies),
    }


# ---------------------------------------------------------------------------
# 6. Cross-checking — interactions, duplicates, conflicting dosages
# ---------------------------------------------------------------------------

CROSS_CHECK_PROMPT = """
You are a clinical safety cross-checking assistant. You are given a
patient's full medication timeline (medications prescribed across multiple
visits, each with a date and source document) and their known allergies.

Analyze the list and return STRICT JSON (no markdown, no commentary) in
this shape:

{
  "potential_drug_interactions": [
    {
      "medications_involved": ["Drug A", "Drug B"],
      "explanation": "plain language explanation of the interaction risk",
      "severity": "low | moderate | high",
      "confidence": 0.0-1.0
    }
  ],
  "duplicate_prescriptions": [
    {
      "medication": "string",
      "occurrences": [{"date": "YYYY-MM-DD", "source_file": "string", "dosage": "string"}],
      "explanation": "why this looks like a duplicate",
      "confidence": 0.0-1.0
    }
  ],
  "conflicting_dosage_instructions": [
    {
      "medication": "string",
      "conflicting_instructions": [{"date": "YYYY-MM-DD", "source_file": "string", "dosage": "string", "frequency": "string"}],
      "explanation": "what conflicts and why it matters",
      "confidence": 0.0-1.0
    }
  ],
  "allergy_conflicts": [
    {
      "medication": "string",
      "allergy": "string",
      "explanation": "string",
      "confidence": 0.0-1.0
    }
  ],
  "overall_recommendation": "1-2 sentence plain-language summary that ALWAYS recommends the patient consult a doctor or pharmacist before making any changes. Never present this as a diagnosis."
}

CONFIDENCE SCORING — anchor every confidence value to these bands. Do not
default to a high score:
- 0.90-1.00: the interaction/conflict/duplicate is well-established,
  unambiguous clinical knowledge (e.g. a textbook contraindicated pairing,
  an exact-ingredient duplicate).
- 0.60-0.89: plausible and worth surfacing, but depends on dose, timing, or
  patient-specific factors you cannot verify from this data alone.
- Below 0.60: a weak or speculative signal — include it only if omitting it
  would be the more dangerous error, and mark it clearly as low-confidence.

Rules:
- Compare medications by their active ingredients (not just brand names) —
  two different brand names with the same active ingredient is a likely
  duplicate.
- Medications are the SAME regardless of source language or printed
  wording — compare using ingredients (already normalized to English
  generic names), dosage_value + dosage_unit, and frequency_per_day
  (already normalized numeric fields), NOT the original dosage/frequency
  text. Do not flag something as a conflict or a difference if it is only
  a translation or unit-formatting difference — e.g. "500 mg" and "0.5 g"
  that both normalized to dosage_value=500/dosage_unit="mg" are the SAME
  dose, not a conflict. Only flag genuine differences in the normalized
  values.
- Only flag interactions you have reasonable clinical confidence about;
  lower the confidence score rather than omitting a plausible risk.
- Do not diagnose. Do not tell the patient to stop or start any medication.
  Always defer to a licensed professional.
- You are a reasoning layer over extracted text, NOT a validated clinical
  drug-interaction database. overall_recommendation must state plainly that
  this analysis is not a substitute for a pharmacist or a licensed
  drug-interaction checking tool, in addition to recommending consultation.
"""


CROSS_CHECK_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "potential_drug_interactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medications_involved": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "moderate", "high"]},
                    "confidence": {"type": "number"},
                },
                "required": ["medications_involved", "explanation", "severity", "confidence"],
                "additionalProperties": False,
            },
        },
        "duplicate_prescriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "occurrences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": ["string", "null"]},
                                "source_file": {"type": ["string", "null"]},
                                "dosage": {"type": ["string", "null"]},
                            },
                            "required": ["date", "source_file", "dosage"],
                            "additionalProperties": False,
                        },
                    },
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "occurrences", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "conflicting_dosage_instructions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "conflicting_instructions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": ["string", "null"]},
                                "source_file": {"type": ["string", "null"]},
                                "dosage": {"type": ["string", "null"]},
                                "frequency": {"type": ["string", "null"]},
                            },
                            "required": ["date", "source_file", "dosage", "frequency"],
                            "additionalProperties": False,
                        },
                    },
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "conflicting_instructions", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "allergy_conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "allergy": {"type": "string"},
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "allergy", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "overall_recommendation": {"type": "string"},
    },
    "required": [
        "potential_drug_interactions", "duplicate_prescriptions",
        "conflicting_dosage_instructions", "allergy_conflicts",
        "overall_recommendation",
    ],
    "additionalProperties": False,
}

CROSS_CHECK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "medical_cross_check",
        "strict": True,
        "schema": CROSS_CHECK_JSON_SCHEMA,
    },
}


def detect_exact_duplicate_medications(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Deterministic (non-LLM) duplicate detection using the normalized
    ingredients + dosage_value + dosage_unit fields set during extraction.

    Why this exists alongside the LLM cross-check: the LLM pass is
    instructed to compare medications via normalized fields rather than
    raw printed text, but it's still a probabilistic reasoning step run
    once per patient. An exact match on ingredient set + numeric dose,
    across two different source documents, is something code can determine
    for certain — independent of what language either document was
    written in — and shouldn't depend on the model reliably catching it
    every single time. This function only flags matches it can verify
    exactly; anything looser (different doses that might still interact,
    brand-name-only duplicates with no normalized dose available) is left
    to the LLM pass, which remains the primary check.
    """
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for med in timeline.get("medications_timeline", []):
        ingredients = tuple(sorted(med.get("ingredients") or []))
        dosage_value = med.get("dosage_value")
        dosage_unit = med.get("dosage_unit")
        if not ingredients or dosage_value is None or not dosage_unit:
            continue  # nothing normalized to compare — leave this one to the LLM pass
        key = (ingredients, dosage_value, dosage_unit)
        groups.setdefault(key, []).append(med)

    duplicates: List[Dict[str, Any]] = []
    for (ingredients, dosage_value, dosage_unit), meds in groups.items():
        distinct_sources = {(m.get("date"), m.get("source_file")) for m in meds}
        if len(distinct_sources) < 2:
            continue  # same medication appearing once is not a duplicate
        duplicates.append({
            "medication": " / ".join(ingredients),
            "occurrences": [
                {"date": m.get("date"), "source_file": m.get("source_file"), "dosage": m.get("dosage")}
                for m in meds
            ],
            "explanation": (
                f"Deterministic check: identical active ingredient(s) ({', '.join(ingredients)}) "
                f"at the same normalized dose ({dosage_value} {dosage_unit}) appear in "
                f"{len(distinct_sources)} separate documents, regardless of source language or "
                "printed wording."
            ),
            "confidence": 0.95,  # exact numeric/ingredient match, not model inference
        })
    return duplicates


def cross_check_prescriptions(timeline: Dict[str, Any], model: str = MODEL) -> Dict[str, Any]:
    """
    Runs interaction / duplicate / dosage-conflict / allergy cross-checking
    over a patient's merged medication timeline (output of
    build_patient_timeline). Merges in a deterministic, language-
    independent duplicate check (see detect_exact_duplicate_medications)
    alongside the LLM's own duplicate detection, rather than relying on
    the LLM pass alone to catch exact cross-language matches.
    """
    payload = {
        "medications_timeline": timeline["medications_timeline"],
        "known_allergies": timeline["known_allergies"],
    }
    raw = _completion_resilient(
        model=model,
        system_prompt=CROSS_CHECK_PROMPT,
        user_content=f"Patient medication data:\n\n{json.dumps(payload, indent=2)}",
        strict_format=CROSS_CHECK_RESPONSE_FORMAT,
    )
    result = _parse_json_object(raw)

    deterministic_duplicates = detect_exact_duplicate_medications(timeline)
    existing = result.setdefault("duplicate_prescriptions", [])
    existing_source_sets = [
        frozenset((occ.get("date"), occ.get("source_file")) for occ in d.get("occurrences", []))
        for d in existing
    ]
    for dup in deterministic_duplicates:
        dup_sources = frozenset((occ["date"], occ["source_file"]) for occ in dup["occurrences"])
        if dup_sources not in existing_source_sets:
            existing.append(dup)

    return result


# ---------------------------------------------------------------------------
# 7. Persistence helpers — patient report / raw-document cache on disk
# ---------------------------------------------------------------------------
# Shared by the CLI (__main__ below) and the HTTP API (api.py), so a patient
# processed via either entry point is visible to the other. Two files per
# patient:
#   patient_docs_<name>.json   - raw extracted per-document dicts (flattened,
#                                pre-timeline), so a later API upload can
#                                merge new documents in rather than
#                                replacing the patient's whole history.
#   patient_report_<name>.json - the merged {"patient_key", "patient_timeline",
#                                "cross_check_report"} snapshot, same shape
#                                the CLI has always written.

def _safe_patient_filename(patient_key: str) -> str:
    """Maps a patient_key into a filesystem-safe name for the two files
    above. Same sanitization the CLI used to do inline."""
    return re.sub(r"[^a-z0-9_]+", "_", patient_key.lower()).strip("_") or "patient"


def _patient_docs_path(patient_key: str) -> str:
    return f"patient_docs_{_safe_patient_filename(patient_key)}.json"


def _patient_report_path(patient_key: str) -> str:
    return f"patient_report_{_safe_patient_filename(patient_key)}.json"


def load_patient_documents(patient_key: str) -> List[Dict[str, Any]]:
    """Loads the raw extracted documents previously saved for this patient
    via save_patient_documents(). Returns [] if this patient has never been
    processed before (nothing to merge new uploads into)."""
    path = _patient_docs_path(patient_key)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def save_patient_documents(patient_key: str, docs: List[Dict[str, Any]]) -> None:
    """Persists the full raw extracted-document list for a patient (flat,
    already run through _flatten_documents) so a future upload can extend
    it instead of overwriting this patient's document history."""
    with open(_patient_docs_path(patient_key), "w") as f:
        json.dump(docs, f, indent=2)


def load_patient_report(patient_key: str) -> Optional[Dict[str, Any]]:
    """Loads the {"patient_key", "patient_timeline", "cross_check_report"}
    snapshot previously written for this patient, or None if this patient
    hasn't been processed yet."""
    path = _patient_report_path(patient_key)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def save_patient_report(
    patient_key: str,
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Optional[Dict[str, Any]] = None,
) -> None:
    """Writes the merged timeline + cross-check report (+ optional lab
    trend analysis) to disk — same shape and naming convention the CLI
    __main__ flow has always used. `lab_trends` is optional so callers
    (and old saved reports on disk, loaded back via load_patient_report())
    that predate lab trend tracking keep working unchanged."""
    output = {
        "patient_key": patient_key,
        "patient_timeline": timeline,
        "cross_check_report": cross_check,
    }
    if lab_trends is not None:
        output["lab_trends"] = lab_trends
    with open(_patient_report_path(patient_key), "w") as f:
        json.dump(output, f, indent=2)


# ---------------------------------------------------------------------------
# 8. Example usage — full pipeline: extract -> merge -> cross-check
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  Single/multiple files:  python medical_extractor.py file1.pdf file2.jpg ...")
        print("  Whole patient folder:   python medical_extractor.py \"C:\\path\\to\\Patient x\"")
        print("  Then chat about it:     add --chat to either form above")
        sys.exit(1)

    # Imported here (not at module top) so retrieval.py's `from
    # medical_extractor import client, MODEL` doesn't create a circular import.
    from retrieval import index_patient_timeline

    args = sys.argv[1:]
    chat_mode = "--chat" in args
    args = [a for a in args if a != "--chat"]

    for a in args:
        if ".zip" in a.lower():
            print(f"ERROR: This path still points inside a .zip file:\n  {a}")
            print("Extract the zip first (right-click -> Extract All in File Explorer),")
            print("then re-run this script pointing at the extracted folder.")
            sys.exit(1)

    # Step 1: extract — folder mode if a single directory was passed, else file list
    if len(args) == 1 and Path(args[0]).is_dir():
        print(f"Scanning folder: {args[0]}")
        all_results = process_patient_folder(args[0])
    else:
        all_results = []
        for file_path in args:
            print(f"Extracting {file_path} ...")
            try:
                result = process_document(file_path)
                all_results.append(result)
            except Exception as e:
                print(f"  Failed: {e}")

    if not all_results:
        print("No documents were successfully extracted. Exiting.")
        sys.exit(1)

    # Step 2: split by patient name, dropping demo/placeholder documents.
    # This stops unrelated prescriptions (e.g. sample docs for different
    # people sitting in the same folder) from being merged into one
    # timeline and cross-checked against each other.
    print("\nGrouping documents by patient ...")
    patient_groups = group_documents_by_patient(all_results, drop_demo_documents=True)

    if not patient_groups:
        print("No real (non-demo) documents remained after filtering. Exiting.")
        sys.exit(1)

    # Step 3 + 4: for EACH distinct patient found, merge into a timeline and
    # cross-check independently.
    for patient_key, docs in patient_groups.items():
        print(f"\n=== Patient: {patient_key} ({len(docs)} document(s)) ===")
        print("Building patient timeline ...")
        timeline = build_patient_timeline(docs)

        print("Cross-checking prescriptions ...")
        cross_check = cross_check_prescriptions(timeline)

        print("Tracking lab result trends ...")
        from lab_trends import track_lab_trends
        lab_trends = track_lab_trends(timeline)

        print("Indexing timeline for retrieval (Q&A) ...")
        try:
            index_patient_timeline(patient_key, timeline)
        except Exception as e:
            print(f"  Indexing failed (Q&A won't be available for this patient): {e}")

        # Persist raw docs too (not just the merged report) so a later API
        # upload for this same patient can merge new documents in.
        save_patient_documents(patient_key, docs)
        save_patient_report(patient_key, timeline, cross_check, lab_trends=lab_trends)
        out_path = _patient_report_path(patient_key)

        print(f"Saved report to {out_path}")
        print(f"  Documents in timeline: {len(timeline['visits'])}")
        print(f"  Medications tracked: {len(timeline['medications_timeline'])}")
        print(f"  Interaction flags: {len(cross_check.get('potential_drug_interactions', []))}")
        print(f"  Duplicate flags: {len(cross_check.get('duplicate_prescriptions', []))}")
        print(f"  Dosage conflict flags: {len(cross_check.get('conflicting_dosage_instructions', []))}")

    # Step 5 (optional): interactive Q&A over whatever was just indexed.
    if chat_mode:
        patient_keys = list(patient_groups.keys())
        if len(patient_keys) == 1:
            active_patient = patient_keys[0]
        else:
            print("\nMultiple patients were processed:")
            for i, k in enumerate(patient_keys):
                print(f"  [{i}] {k}")
            choice = input("Select a patient index to chat about: ").strip()
            try:
                active_patient = patient_keys[int(choice)]
            except (ValueError, IndexError):
                print("Invalid selection. Exiting.")
                sys.exit(1)

        from conversation import get_or_create_session, ask as conversation_ask

        print(f"\nChatting about patient '{active_patient}'. Type 'exit' to quit.")
        session = get_or_create_session(active_patient, session_id="cli")
        while True:
            question = input("\nQuestion: ").strip()
            if question.lower() in ("exit", "quit"):
                break
            if not question:
                continue
            try:
                result = conversation_ask(session, question)
            except Exception as e:
                print(f"  Error: {e}")
                continue
            print(f"  [retrieval query]: {result.get('rewritten_query')}")
            print(json.dumps(result, indent=2))
