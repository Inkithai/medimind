"""
Medical Document Extraction Pipeline
=====================================
Handles PDF (text-based or scanned) and image uploads (prescriptions, lab
reports, discharge summaries), extracts structured data using OpenAI-
compatible LLM providers and returns clean JSON ready for timeline
building, RAG indexing, and cross-checking.

Provider is selected via LLM_PROVIDER (default: groq). All providers use
the standard OpenAI SDK — only base URL, API key, and model names differ.

  groq (default):  GROQ_API_KEY (gsk_...), https://api.groq.com/openai/v1
                   text openai/gpt-oss-120b, vision qwen/qwen3.6-27b — free, no card
  gemini:          GEMINI_API_KEY (or GOOGLE_API_KEY), https://generativelanguage.googleapis.com/v1beta/openai/
                   text/vision gemini-3.6-flash — current stable multimodal model

Generic OpenAI-compatible providers (cerebras, openrouter, openai, custom)
work via LLM_API_KEY + LLM_BASE_URL + LLM_MODEL env vars.

Install:
    pip install openai pdfplumber pymupdf pillow --break-system-packages

Env (pick one provider):
    export GROQ_API_KEY="gsk_..."        (https://console.groq.com/keys)        # LLM_PROVIDER=groq
    export GEMINI_API_KEY="AIza..."      (https://aistudio.google.com/app/apikey) # LLM_PROVIDER=gemini
"""  # noqa: E501

import base64
import copy
import io
import json
import os
import re
import threading
import time
from collections import deque
from datetime import timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import pdfplumber

try:
    import pymupdf  # PyMuPDF >= 1.24 exposes the modern module name (no deprecation warning)
except ImportError:  # older PyMuPDF releases only ship the legacy `fitz` module name
    import fitz as pymupdf
import logging

from dotenv import load_dotenv
from openai import (
    APIConnectionError,
    APIError,
    NotFoundError,
    OpenAI,
)
from PIL import Image, ImageOps

from clinical_events import (
    CLINICAL_EVENT_COLLECTIONS,
    CLINICAL_EVENT_DATE_FIELDS,
    CLINICAL_TIMELINE_KEYS,
)
from evidence import (
    first_evidence,
    locate_ocr_text_evidence,
    locate_pdf_text_evidence,
    normalize_document_evidence,
)
from ocr_service import (
    InvalidImageError,
    InvalidPDFError,
    OCRError,
    TesseractNotFoundError,
    is_tesseract_available,
    ocr_image_bytes,
    ocr_pdf_pages,
    transcript_is_usable,
)

load_dotenv(override=True)

logger = logging.getLogger("medical_extractor")

# ---------------------------------------------------------------------------
# LLM provider layer — OpenAI-compatible via LLM_PROVIDER
# ---------------------------------------------------------------------------
# Provider resolution (LLM_PROVIDER, _PROVIDER_DEFAULTS, _resolve_provider_config,
# _resolve_api_key, client, ...) lives in llm_provider.py so the same
# configuration is shared by every module that talks to the LLM. Re-export
# the legacy names here so existing `from medical_extractor import ...`
# callers keep working unchanged.
from llm_provider import (  # noqa: E402
    _PROVIDER_CFG,
    _PROVIDER_DEFAULTS,  # noqa: F401  (re-exported for test compatibility)
    GROQ_API_KEY,  # noqa: F401  (re-exported for backward compatibility)
    LLM_API_KEY,  # noqa: F401  (re-exported for backward compatibility)
    LLM_PROVIDER,
    _configured_secret,
    client,
)

_openrouter_fallback_lock = threading.Lock()
_openrouter_fallback_active = False
openrouter_fallback_client: Optional[OpenAI] = None
_OPENROUTER_FALLBACK_ENABLED = False
_OPENROUTER_API_KEY = ""
_OPENROUTER_MODEL = ""
_OPENROUTER_VISION_MODEL = ""
# OpenRouter's router is preferable to a hard-coded free model: it selects a
# currently available model with the capabilities required by the request.
# This also keeps a stale user-configured model from making the whole upload
# fail when OpenRouter retires or temporarily removes a model variant.
_OPENROUTER_AUTO_MODEL = "openrouter/free"


def _ensure_openrouter_fallback_client() -> Optional[OpenAI]:
    """Resolve and return an OpenRouter fallback client if configured.

    Checks os.environ (and reloads .env) so credentials added without a
    process restart or enabled via alias environment variables are picked up
    automatically. Setting an OpenRouter API key and fallback model is sufficient
    to enable fallback (unless explicitly disabled with OPENROUTER_FALLBACK_ENABLED=false).
    """
    global openrouter_fallback_client, _OPENROUTER_FALLBACK_ENABLED
    global _OPENROUTER_API_KEY, _OPENROUTER_MODEL, _OPENROUTER_VISION_MODEL

    with _openrouter_fallback_lock:
        if openrouter_fallback_client is not None:
            return openrouter_fallback_client

        load_dotenv(override=True)
        enabled_raw = (
            os.environ.get("OPENROUTER_FALLBACK_ENABLED", "").strip().lower()
            or os.environ.get("OPENROUTER_FALLBACK", "").strip().lower()
            or os.environ.get("OPENROUTER_ENABLED", "").strip().lower()
            or os.environ.get("FALLBACK_OPENROUTER_ENABLED", "").strip().lower()
        )
        api_key = (
            _configured_secret("OPENROUTER_API_KEY")
            or _configured_secret("OPENROUTER_KEY")
            or _configured_secret("OPENROUTER_FALLBACK_API_KEY")
            or _configured_secret("OPENROUTER_FALLBACK_KEY")
        )
        model = (
            os.environ.get("OPENROUTER_FALLBACK_MODEL", "").strip()
            or os.environ.get("OPENROUTER_MODEL", "").strip()
            or os.environ.get("OPENROUTER_DEFAULT_MODEL", "").strip()
            or (
                os.environ.get("LLM_FALLBACK_MODEL", "").strip()
                if os.environ.get("LLM_FALLBACK_PROVIDER", "").strip().lower() == "openrouter"
                or os.environ.get("FALLBACK_PROVIDER", "").strip().lower() == "openrouter"
                or "openrouter" in os.environ.get("LLM_FALLBACK_MODEL", "").strip().lower()
                else ""
            )
        )
        vision_model = (
            os.environ.get("OPENROUTER_FALLBACK_VISION_MODEL", "").strip()
            or os.environ.get("OPENROUTER_VISION_MODEL", "").strip()
            or model
        )

        enabled = (
            enabled_raw in {"1", "true", "yes", "on"}
            or os.environ.get("FALLBACK_PROVIDER", "").strip().lower() == "openrouter"
            or os.environ.get("LLM_FALLBACK_PROVIDER", "").strip().lower() == "openrouter"
            or (enabled_raw not in {"0", "false", "no", "off"} and bool(api_key and model))
        )

        if enabled and api_key and model:
            _OPENROUTER_FALLBACK_ENABLED = True
            _OPENROUTER_API_KEY = api_key
            _OPENROUTER_MODEL = model
            _OPENROUTER_VISION_MODEL = vision_model
            openrouter_fallback_client = OpenAI(
                api_key=_OPENROUTER_API_KEY,
                base_url=os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
                max_retries=0,
            )
            return openrouter_fallback_client

        if enabled_raw in {"1", "true", "yes", "on"} and (not api_key or not model):
            logger.warning(
                "OpenRouter fallback explicitly enabled but missing OPENROUTER_API_KEY or OPENROUTER_FALLBACK_MODEL; fallback disabled."  # noqa: E501
            )
            _OPENROUTER_FALLBACK_ENABLED = False

        return None


# Initialize at import time if already configured
_ensure_openrouter_fallback_client()


def _activate_openrouter_fallback() -> bool:
    """Trip the process-wide circuit breaker after a hard primary quota error."""
    global _openrouter_fallback_active
    client_instance = _ensure_openrouter_fallback_client()
    if not client_instance:
        return False
    with _openrouter_fallback_lock:
        newly_activated = not _openrouter_fallback_active
        _openrouter_fallback_active = True
    if newly_activated:
        logger.warning(
            "Primary provider '%s' has no usable quota; switching new LLM calls to configured OpenRouter fallback.",  # noqa: E501
            LLM_PROVIDER,
        )
    return True


def _openrouter_fallback_is_active() -> bool:
    if not _openrouter_fallback_active:
        return False
    return (
        openrouter_fallback_client is not None or _ensure_openrouter_fallback_client() is not None
    )


# Model defaults — provider-specific, overridable via env vars. LLM_* generic
# vars take precedence so a single .env swap can retarget any provider.
MODEL = os.environ.get("LLM_MODEL") or os.environ.get(
    _PROVIDER_CFG["model_env"], _PROVIDER_CFG["model_default"]
)
VISION_MODEL = os.environ.get("LLM_VISION_MODEL") or os.environ.get(
    _PROVIDER_CFG["vision_env"], _PROVIDER_CFG["vision_default"]
)
FALLBACK_MODEL = (
    os.environ.get("LLM_FALLBACK_MODEL")
    or os.environ.get(_PROVIDER_CFG["fallback_env"], _PROVIDER_CFG["fallback_default"])
    or ""
)
if not VISION_MODEL:
    VISION_MODEL = (
        MODEL  # providers without a distinct vision model (e.g. Cerebras) reuse text model
    )

# Groq retires hosted models on a schedule — keep an eye on
# https://console.groq.com/docs/deprecations and override the models above
# via env vars rather than editing code.
#   * meta-llama/llama-4-scout-17b-16e-instruct shut down 2026-07-17 (old
#     default MODEL — requests to it now 404 with model_not_found).
#   * llama-3.1-8b-instant / llama-3.3-70b-versatile shut down 2026-08-16.
# For Gemini, vision is multimodal — same model handles text + images.

# Constrained-decoding strict json_schema is only available on Groq's
# gpt-oss family (https://console.groq.com/docs/structured-outputs). Every
# other model — including qwen vision and all Gemini models — gets JSON
# Object Mode instead (valid JSON guaranteed; schema adherence via inlined prompt).
_STRICT_SCHEMA_MODELS = frozenset(
    {
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-safeguard-20b",
    }
)


# ---------------------------------------------------------------------------
# Call-rate pacer — prevent 429s by spacing LLM requests to stay under the
# provider's per-minute quota.  Free-tier Gemini allows 5 RPM; Groq allows
# more but still benefits from pacing when multiple files are uploaded.
# Configurable via LLM_MAX_RPM (0 disables pacing).
# ---------------------------------------------------------------------------


class _CallPacer:
    """Thread-safe sliding-window rate limiter for LLM API calls.

    Tracks the timestamps of recent calls in a deque.  Before each call,
    ``acquire()`` blocks until there is room in the window — i.e. the
    oldest tracked call has aged past the 60-second window.  With
    max_rpm=5 and 7 calls needed (6 extractions + 1 safety check), pacing
    prevents the safety check from hitting a 429 after exhausting the
    per-minute quota on extraction alone.
    """

    def __init__(self, max_rpm: int, window_seconds: float = 60.0) -> None:
        self._max_rpm = max_rpm
        self._window = window_seconds
        self._lock = threading.Lock()
        self._timestamps: deque = deque()

    @property
    def enabled(self) -> bool:
        return self._max_rpm > 0

    def acquire(self) -> None:
        """Block until a call slot is available within the rate window."""
        if not self.enabled:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                # Evict timestamps older than the window
                while self._timestamps and (now - self._timestamps[0]) >= self._window:
                    self._timestamps.popleft()
                if len(self._timestamps) < self._max_rpm:
                    self._timestamps.append(now)
                    return
                # Need to wait for the oldest call to age out of the window
                wait_until = self._timestamps[0] + self._window
                sleep_s = wait_until - now
            if sleep_s > 0:
                logger.info(
                    "CallPacer: rate-limit pacing — sleeping %.1fs to stay within %d RPM",
                    sleep_s,
                    self._max_rpm,
                )
                time.sleep(sleep_s)


def _pacer_max_rpm() -> int:
    """Resolve the pacing cap: LLM_MAX_RPM > provider default > disabled."""
    explicit = os.environ.get("LLM_MAX_RPM")
    if explicit is not None:
        try:
            return max(0, int(explicit))
        except ValueError:
            pass
    # Sensible provider defaults for free-tier quotas
    _provider_defaults = {
        "gemini": 4,  # Gemini free tier is 5 RPM; use 4 for safety margin
        "groq": 0,  # Groq free tier is generous (30 RPM); no pacing needed
    }
    return _provider_defaults.get(LLM_PROVIDER, 0)


_call_pacer = _CallPacer(_pacer_max_rpm())


def _chat_completion(**kwargs) -> Any:
    """client.chat.completions.create() with a provider-churn-aware error.

    A request against a retired model ID comes back as a 404
    'model_not_found'. Translate that into an actionable fix hint instead
    of a bare stack trace. Provider-aware so messages stay correct when
    LLM_PROVIDER=gemini (or generic).
    """
    # Pace calls to stay within the provider's per-minute quota — prevents
    # the safety/cross-check call from hitting a 429 after file extractions
    # have already consumed the free-tier budget.
    _call_pacer.acquire()
    active_client = (
        openrouter_fallback_client or _ensure_openrouter_fallback_client() or client
        if _openrouter_fallback_is_active()
        else client
    )
    if _openrouter_fallback_is_active():
        # The caller still supplies its primary model name. Translate only at
        # the transport boundary so extraction/cross-check code remains
        # provider-agnostic. Image calls use the separately configured vision model.
        kwargs = dict(kwargs)
        is_vision = (kwargs.get("model") == VISION_MODEL and VISION_MODEL != MODEL) or any(
            isinstance(msg.get("content"), list)
            and any(
                isinstance(part, dict) and part.get("type") == "image_url"
                for part in msg["content"]
            )
            for msg in kwargs.get("messages", [])
            if isinstance(msg, dict)
        )
        kwargs["model"] = _OPENROUTER_VISION_MODEL if is_vision else _OPENROUTER_MODEL
    try:
        return active_client.chat.completions.create(**kwargs)
    except NotFoundError:
        # OpenRouter model slugs are not permanent. A configured :free model
        # can disappear (or be unavailable at a particular provider) while
        # OpenRouter's dynamic router remains available. Retry the request once
        # through that router before surfacing the model error. This is
        # especially important for vision uploads: the router filters for
        # models that support image input instead of guessing a text-only model.
        requested_model = str(kwargs.get("model") or "unknown")
        if _openrouter_fallback_is_active() and requested_model != _OPENROUTER_AUTO_MODEL:
            retry_kwargs = dict(kwargs)
            retry_kwargs["model"] = _OPENROUTER_AUTO_MODEL
            try:
                logger.warning(
                    "OpenRouter rejected configured fallback model '%s'; retrying through '%s'.",
                    requested_model,
                    _OPENROUTER_AUTO_MODEL,
                )
                return active_client.chat.completions.create(**retry_kwargs)
            except NotFoundError as router_error:
                # Fall through and report the router rejection with the normal
                # actionable provider error below.
                kwargs = retry_kwargs
                e = router_error
        model = str(kwargs.get("model") or "unknown")
        model_env = _PROVIDER_CFG.get("model_env", "LLM_MODEL")
        vision_env = _PROVIDER_CFG.get("vision_env", "LLM_VISION_MODEL")
        docs = _PROVIDER_CFG.get("docs_url") or "provider docs"
        provider_name = "openrouter" if _openrouter_fallback_is_active() else LLM_PROVIDER
        logger.error(
            "Provider '%s' rejected model '%s' (404 model_not_found). Check %s, then update %s/%s. "
            "Current defaults: text='%s', vision='%s'.",
            provider_name,
            model,
            docs,
            model_env,
            vision_env,
            MODEL,
            VISION_MODEL,
        )
        raise ProviderRateLimitError(
            provider=provider_name,
            model=model,
            hard_quota=True,
            retired_model=True,
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


class ProviderRateLimitError(RuntimeError):
    """A user-safe, machine-readable provider capacity failure.

    ``hard_quota`` distinguishes a project/model with no usable quota (daily
    allowance exhausted, billing disabled, or a retired model whose quota is
    now zero) from a short per-minute throttle. Callers use this distinction
    to stop sending the remaining files in a batch instead of multiplying one
    provider outage into N files × N retries.
    """

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        retry_after_seconds: Optional[float] = None,
        hard_quota: bool = False,
        retired_model: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.retry_after_seconds = retry_after_seconds
        self.hard_quota = hard_quota
        self.retired_model = retired_model
        if retired_model:
            self.code = "provider_model_unavailable"
            message = (
                f"The configured {provider} model '{model}' is no longer available. "
                "Update the server's model setting before retrying."
            )
        elif hard_quota:
            self.code = "provider_quota_exhausted"
            message = (
                f"The {provider} document-reading quota is currently unavailable or exhausted. "
                "Trying the same file again now will not help."
            )
        else:
            self.code = "provider_rate_limited"
            wait = (
                f" Try again in about {max(1, round(retry_after_seconds))} seconds."
                if retry_after_seconds
                else " Please wait a minute before trying again."
            )
            message = (
                f"The {provider} document-reading service is temporarily busy (HTTP 429).{wait}"
            )
        super().__init__(message)


# Models which Google has fully shut down. The OpenAI-compatible endpoint has
# been observed returning HTTP 429 with quota limit=0 for these IDs, so detect
# them explicitly instead of telling users to retry a document that can never
# succeed with the configured model.
_RETIRED_GEMINI_MODELS = {
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash-lite-001",
}


def _provider_error_text(exc: Exception) -> str:
    """Flatten an SDK exception/body to searchable lower-case text."""
    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            parts.append(json.dumps(body, ensure_ascii=False))
        except (TypeError, ValueError):
            parts.append(str(body))
    return " ".join(parts).lower()


def _is_hard_quota_error(exc: Exception) -> bool:
    """True when waiting a few seconds cannot make this HTTP 429 usable.

    Gemini includes quota IDs in the body. Per-day exhaustion, an explicit
    ``limit: 0``, and billing/account quota failures should fail immediately;
    only ordinary per-minute throttles should consume retry sleeps.
    """
    text = _provider_error_text(exc)
    hard_markers = (
        "generaterequestsperday",
        "requestsperday",
        "requests_per_day",
        "per-day",
        "per day",
        "daily quota",
        "limit: 0",
        '"limit": 0',
    )
    return any(marker in text for marker in hard_markers)


def _is_retired_provider_model(model: str) -> bool:
    return LLM_PROVIDER == "gemini" and model.lower() in _RETIRED_GEMINI_MODELS


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
    return any(
        marker in text
        for marker in (
            "tokens per minute",
            "tpm",
            "rate_limit_exceeded",
            "request too large for model",
        )
    )


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


def _error_detail(exc: Exception) -> str:
    """Best-effort serialization of an OpenAI/Groq APIError for logging:
    status code, error code, message, and the raw response body — which for
    Groq includes the model's discarded generation on a 400
    'json_validate_failed' (`error.failed_generation`), i.e. exactly the
    evidence needed to see WHY a request was rejected."""
    parts = []
    status = getattr(exc, "status_code", None)
    if status is not None:
        parts.append(f"status={status}")
    code = getattr(exc, "code", None)
    if code:
        parts.append(f"code={code}")
    message = getattr(exc, "message", None) or str(exc)
    if message:
        parts.append(f"message={message!r}")
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            body_str = json.dumps(body, ensure_ascii=False)
        except (TypeError, ValueError):
            body_str = str(body)
        parts.append(f"body={body_str[:1500]}")
    return " ".join(parts) or repr(exc)


def _retry_after_seconds(exc: Exception, fallback: float) -> float:
    """Best-effort parse of a provider's requested retry delay.

    OpenAI-compatible providers normally use ``Retry-After``. Gemini's
    compatibility endpoint often omits that header and puts either
    ``google.rpc.RetryInfo.retryDelay: \"14s\"`` or ``Please retry in
    14.3s`` in the JSON error body instead. Honouring the body prevents the
    old 1s/2s retry loop from hammering a provider which explicitly asked us
    to wait close to a minute.
    """
    headers = getattr(exc, "headers", None)
    if headers is None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None) if response is not None else None
    if headers is not None:
        try:
            raw = headers.get("retry-after") or headers.get("Retry-After")
        except Exception:
            raw = None
        if raw:
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                # HTTP-date form is uncommon for these APIs. Continue to the
                # provider-body parser before using exponential backoff.
                pass

    text = _provider_error_text(exc)
    body_patterns = (
        r'retrydelay["\'\s:]+([0-9]+(?:\.[0-9]+)?)\s*s',
        r"please\s+retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*s",
        r"retry\s+in\s+([0-9]+(?:\.[0-9]+)?)\s*seconds?",
    )
    for pattern in body_patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except (TypeError, ValueError):
                pass
    return fallback


def _is_vision_content(user_content: Any) -> bool:
    return isinstance(user_content, list) and any(
        isinstance(part, dict) and part.get("type") == "image_url" for part in user_content
    )


def _completion_token_budget(user_content: Any) -> int:
    """Choose a completion budget that fits the active provider's limits.

    Groq's common 8K TPM tier needs a tight vision budget (2048) or even a
    94 KB image + 4096 max_tokens exceeds TPM (reported as 413). Gemini
    quotas vary by project/model, so a conservative cap is useful there too.
    Provider-specific
    env vars (GEMINI_MAX_TOKENS, GROQ_MAX_TOKENS, LLM_MAX_TOKENS) override.

    Vision requests consume substantially more input tokens than text calls,
    so vision defaults are capped lower on constrained providers.
    """

    def _int_env(names: List[str], default: int) -> int:
        for n in names:
            v = os.environ.get(n)
            if v is not None:
                try:
                    return max(256, int(v))
                except ValueError:
                    logger.warning("Ignoring invalid %s=%r; using %d", n, v, default)
                    return default
        return default

    global_budget = _int_env(
        [
            f"{LLM_PROVIDER.upper()}_MAX_TOKENS",
            "LLM_MAX_TOKENS",
            "GROQ_MAX_TOKENS",
            "GEMINI_MAX_TOKENS",
        ],
        4096,
    )

    if not _is_vision_content(user_content):
        return global_budget

    # Vision-specific override if set
    for n in [
        f"{LLM_PROVIDER.upper()}_VISION_MAX_TOKENS",
        "LLM_VISION_MAX_TOKENS",
        "GROQ_VISION_MAX_TOKENS",
        "GEMINI_VISION_MAX_TOKENS",
    ]:
        v = os.environ.get(n)
        if v is not None:
            try:
                return max(256, int(v))
            except ValueError:
                logger.warning("Ignoring invalid %s=%r; using 2048", n, v)
                return 2048
    # Default vision cap: Groq 8K TPM tier needs 2048; Gemini dense lab
    # reports were observed truncating at 4096 output tokens in production
    # (finish_reason=length, JSON cut mid-"lab_results"), so the untuned
    # default floor is 8192. An explicit global budget override still wins,
    # and if a tier rejects the budget the token-budget error path halves it.
    _global_override_set = any(
        os.environ.get(n)
        for n in (
            f"{LLM_PROVIDER.upper()}_MAX_TOKENS",
            "LLM_MAX_TOKENS",
            "GROQ_MAX_TOKENS",
            "GEMINI_MAX_TOKENS",
        )
    )
    if LLM_PROVIDER == "gemini":
        return global_budget if _global_override_set else 8192
    return min(global_budget, 2048)


# finish_reason values that mean "the generation was cut off by the
# completion-token limit before the JSON could finish" (OpenAI-compat
# spelling 'length'; Gemini's native spelling 'MAX_TOKENS' defensively
# included in case a provider leaks it through).
_LENGTH_FINISH_REASONS = frozenset({"length", "max_tokens"})

# How many times a truncated generation may escalate the completion budget
# (each escalation doubles max_tokens up to the provider ceiling) before the
# ladder gives up on this strategy. Bounds worst-case latency per file.
_MAX_BUDGET_ESCALATIONS = 3


def _max_completion_ceiling() -> int:
    """Absolute completion-token ceiling used when escalating a truncated
    generation. Provider/env overridable; Gemini comfortably emits 16K-token
    JSON for dense lab reports, other providers get a conservative 8K."""
    default = 16384 if LLM_PROVIDER == "gemini" else 8192
    for n in (f"{LLM_PROVIDER.upper()}_MAX_COMPLETION_TOKENS", "LLM_MAX_COMPLETION_TOKENS"):
        v = os.environ.get(n)
        if v is not None:
            try:
                return max(512, int(v))
            except ValueError:
                logger.warning("Ignoring invalid %s=%r; using %d", n, v, default)
                return default
    return default


def _finish_reason_text(response: Any) -> str:
    """Lowercased finish_reason of a chat response, or '' when absent."""
    try:
        fr = response.choices[0].finish_reason
    except (AttributeError, IndexError, TypeError):
        return ""
    return fr.strip().lower() if isinstance(fr, str) else ""


def _response_was_truncated(response: Any) -> bool:
    return _finish_reason_text(response) in _LENGTH_FINISH_REASONS


# ---------------------------------------------------------------------------
# Reasoning-model suppression — keep chain-of-thought OFF the wire
# ---------------------------------------------------------------------------
# Qwen3-family / QwQ / DeepSeek-derived reasoning models "think" before they
# answer. On Groq that breaks structured extraction two ways (both visible in
# production logs):
#   * json_object mode: the generation is not pure JSON (or comes back EMPTY
#     because the real output went to the reasoning channel), so Groq's
#     server-side validator rejects the whole request with 400
#     'json_validate_failed' and 'failed_generation': ''.
#   * plain-text mode: the <think> trace consumes the whole (TPM-capped)
#     completion budget and is truncated before any JSON appears — output
#     observed cut off mid-think at '...The schema allows "prescrip'.
# The fix is to tell the provider not to think on these calls. There is no
# universal switch: Qwen3 honors the chat-template kwarg
# enable_thinking=false, Groq's reasoning API additionally offers
# reasoning_format="hidden", and a given (provider, model) pair may reject
# one with a 400 while silently ignoring the other. So instead of guessing,
# _completion_resilient PROBES the switches below per output-mode rung and
# caches the outcome per model (process-wide): a switch that 400s ("unknown
# parameter") or provably leaves thinking enabled is crossed off forever,
# and the first switch that yields clean JSON becomes the default for every
# later call with that model. Happy-path cost: zero extra requests once a
# working switch is known (probe order is best-first).
#
# Override the applicability heuristic with GROQ_DISABLE_REASONING /
# LLM_DISABLE_REASONING:  true/1/yes = probe for every non-strict model,
# false/0/no = never probe. Non-Groq providers only probe on explicit
# opt-in (LLM_DISABLE_REASONING=true) — unknown params may 400 elsewhere.

_REASONING_SUPPRESS_PROBES: List[Dict[str, Any]] = [
    # Qwen3 chat template: decisive — the model never generates a think
    # block at all, so the completion budget goes to the actual answer.
    {"chat_template_kwargs": {"enable_thinking": False}},
    # Groq reasoning API: hide the reasoning trace from the response so
    # server-side JSON validation sees clean output.
    {"reasoning_format": "hidden"},
]

_REASONING_SUPPRESS_LABELS = [
    "chat_template_kwargs.enable_thinking=false",
    "reasoning_format=hidden",
]

# Process-wide per-model probe results: model -> {"dead": set[int], "good": Optional[int]}
_SUPPRESS_STATE: Dict[str, Dict[str, Any]] = {}

# Model-name fragments that mark a reasoning/thinking model family.
_REASONING_MODEL_HINTS = ("qwen", "qwq", "deepseek", "-r1", "think", "reasoning")


def _env_flag(*names: str) -> Optional[bool]:
    """First set env var among `names` parsed as a boolean, else None."""
    for n in names:
        v = os.environ.get(n)
        if v is not None:
            return v.strip().lower() in ("1", "true", "yes", "on")
    return None


def _suppression_applies(model: str) -> bool:
    """Should this model's requests probe reasoning-suppression switches?

    Strict-schema models (Groq gpt-oss family) are excluded: constrained
    decoding already guarantees clean JSON for them, and Groq handles their
    reasoning channel natively.
    """
    if model in _STRICT_SCHEMA_MODELS:
        return False
    forced = _env_flag("GROQ_DISABLE_REASONING", "LLM_DISABLE_REASONING")
    if LLM_PROVIDER != "groq":
        # Other providers may reject unknown params with a 400 before our
        # ladder can react — only probe on explicit opt-in.
        return forced is True
    if forced is not None:
        return forced
    hint = model.lower()
    return any(h in hint for h in _REASONING_MODEL_HINTS)


def _suppress_state(model: str) -> Dict[str, Any]:
    return _SUPPRESS_STATE.setdefault(model, {"dead": set(), "good": None})


def _suppression_candidates(model: str) -> List[Tuple[Optional[int], Optional[Dict[str, Any]]]]:
    """Ordered (probe_index, extra_body) pairs to try per output-mode rung.

    Best-known-working probe first, then untried probes, and always the bare
    request (None, None) last so a model immune to every switch still gets
    the pre-suppression behavior. Probes already proven dead/ineffective for
    this model are skipped entirely.
    """
    if not _suppression_applies(model):
        return [(None, None)]
    st = _suppress_state(model)
    order: List[int] = []
    good = st.get("good")
    if good is not None and good not in st["dead"]:
        order.append(good)
    order.extend(
        i for i in range(len(_REASONING_SUPPRESS_PROBES)) if i not in order and i not in st["dead"]
    )
    return [(i, _REASONING_SUPPRESS_PROBES[i]) for i in order] + [(None, None)]


def _best_suppression_extra_body(model: str) -> Optional[Dict[str, Any]]:
    """The proven (or most promising) suppression extra_body for one-off
    calls outside the ladder (e.g. the vision repair retry), or None."""
    for probe_idx, extra in _suppression_candidates(model):
        if probe_idx is not None:
            return extra
    return None


def _contains_reasoning_dump(text: str) -> bool:
    """True if the output visibly contains chain-of-thought tags — i.e. the
    active suppression switch (if any) provably did not suppress thinking."""
    head = text[:4000].lower()
    return any(
        marker in head
        for marker in (
            "<think",
            "<reasoning",
            "<thought",
            "<analysis",
            "&lt;think",
            "&lt;reasoning",
        )
    )


def _failed_generation_shows_thinking(exc: Exception) -> bool:
    """True only when a 400 json_validate_failed carries positive evidence
    that the (probed) model STILL emitted chain-of-thought: the discarded
    `failed_generation` itself contains think tags. An empty or absent
    failed_generation is ambiguous — it must NOT be used to cross a probe
    off, because the empty-generation failure also happens for reasons
    unrelated to reasoning (and the probe may be working perfectly)."""
    body = getattr(exc, "body", None)
    failed_generation = ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            gen = error.get("failed_generation")
            if isinstance(gen, str):
                failed_generation = gen
        elif isinstance(body.get("failed_generation"), str):
            failed_generation = body["failed_generation"]
    return bool(failed_generation) and _contains_reasoning_dump(failed_generation)


def _is_unsupported_param_error(exc: Exception, extra_body: Optional[Dict[str, Any]]) -> bool:
    """True if the provider 400-rejected the request because a probe switch
    is not supported for this model (e.g. 'Unknown field
    \"chat_template_kwargs\"' / 'Unrecognized request argument:
    reasoning_format'). Only consulted when a suppression probe was actually
    attached to the request, so a generic unsupported-parameter 400 on a
    plain request still propagates as a permanent error."""
    if extra_body is None:
        return False
    # Groq rejects unknown JSON fields with 400; OpenAI-compatible validators
    # (pydantic-style request-body validation) use 422 for the same thing.
    if getattr(exc, "status_code", None) not in (400, 422):
        return False
    if _is_json_validation_failure(exc):
        return False
    parts = [str(exc), str(getattr(exc, "message", "") or "")]
    body = getattr(exc, "body", None)
    if body is not None:
        try:
            parts.append(json.dumps(body))
        except (TypeError, ValueError):
            parts.append(str(body))
    text = " ".join(parts).lower()
    markers = (
        "unknown field",
        "unrecognized request argument",
        "unsupported parameter",
        "unsupported param",
        "unknown parameter",
        "unknown argument",
        "extraneous field",
        "not supported",
        "invalid parameter",
        "extra inputs are not permitted",
        "additional properties",
        "unexpected keyword",
    )
    if any(m in text for m in markers):
        return True
    # Message that names the probe's own top-level key in an error context.
    return any(
        key.lower() in text and ("invalid" in text or "unsupported" in text or "unknown" in text)
        for key in extra_body
    )


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
        "\n\nCRITICAL OUTPUT RULES — you MUST follow every single one — VIOLATION WILL CAUSE SYSTEM FAILURE:\n"  # noqa: E501
        "1. Output **ONLY** a single valid JSON object as the entire response — no other text, ever.\n"  # noqa: E501
        "2. The VERY FIRST character you emit must be '{' and the VERY LAST must be '}'.\n"
        "3. No markdown, no ``` or ```json fences, no bullet points, no analysis, no preamble, no apologies, no explanations.\n"  # noqa: E501
        "4. **ABSOLUTELY NO** <think>, </think>, <thought>, <reasoning>, or any reasoning/chain-of-thought tags or hidden thinking. "  # noqa: E501
        "Your internal reasoning MUST remain hidden and MUST NOT appear in the output. "
        "Do NOT output any step-by-step, do NOT describe the document structure, do NOT say 'The user wants...'.\n"  # noqa: E501
        "5. Do NOT prefix with 'Here is the JSON:' or similar — start immediately with '{'.\n"
        "6. Conform EXACTLY to this JSON Schema (all required fields present, no extra fields):\n"
        # Compact JSON materially reduces prompt tokens on the 8K TPM tier.
        f"{json.dumps(schema, separators=(',', ':'))}\n"
        "Example of the required shape (illustrative values, adapt to the actual document):\n"
        '{\n  "document_type": "prescription",\n  "date": "2024-03-15",\n  "provider_or_doctor": "Dr. Smith",\n  "patient_name": "John Doe",\n  "medications": [],\n  "lab_results": [],\n  "diagnoses": [],\n  "symptoms": [],\n  "procedures": [],\n  "vital_signs": [],\n  "imaging_results": [],\n  "allergies_noted": [],\n  "diagnoses_or_conditions": [],\n  "clinical_notes": null,\n  "field_evidence": {"date": [], "provider_or_doctor": [], "patient_name": [], "allergies_noted": [], "clinical_notes": []},\n  "illegible_or_low_confidence_fields": [],\n  "overall_confidence": 0.92\n}\n'  # noqa: E501
    )
    if model in _STRICT_SCHEMA_MODELS:
        return [
            (strict_format, ""),  # Groq enforces the schema server-side
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

    Recovery ladder, from most to least server-side enforcement:
      1. Output-mode rungs from _format_ladder() (strict json_schema for
         gpt-oss models; json_object then plain text otherwise), each tried
         up to `primary_attempts` / `fallback_attempts` times.
      2. Each output mode is first attempted WITH reasoning-suppression
         probes (_suppression_candidates) when the model looks like a
         thinker: a reasoning model's <think> preamble is what most often
         breaks server-side JSON validation AND eats the (TPM-capped)
         completion budget, so suppressing thinking is tried before giving
         up on the mode. Probe results are cached per model process-wide —
         a probe the API 400-rejects or that provably leaves thinking on is
         never retried, and the first probe that yields clean JSON becomes
         this model's default. Non-thinking models see exactly one
         candidate (the bare request), so their behavior is unchanged.
      3. In plain-text mode Groq does not validate anything, so the raw
         content comes back to us and is parsed client-side (see
         _parse_json_object) — recovering generations Groq would otherwise
         have discarded, e.g. JSON wrapped in markdown fences or preceded
         by commentary.
      4. With every rung exhausted, ONE vision repair retry (actual image
         + explicit JSON-only instruction) is attempted. There is
         deliberately NO text-model repair fallback anymore: the fallback
         model cannot see the image, so fed only the error snippet it
         fabricated a minimal all-empty JSON — structurally valid but
         clinically meaningless — which the medical-document filter then
         rejected with a misleading "'x.jpg' does not appear to be a
         medical document" 422 for what was really a transient provider
         failure (rate limits / model hiccup). An honest RuntimeError ->
         HTTP 502 ("please retry") replaces that.

    Additionally validates that the returned content is actually parseable
    as JSON (via _parse_json_object). If the model returns a non-JSON
    reasoning dump (e.g. "<think> The user wants..." without any JSON), or
    Groq discards a generation server-side (400 'json_validate_failed'),
    the SAME request is unlikely to succeed on retry, so the runner
    advances to the next rung immediately instead of burning attempts.
    Temporary rate limits (429) are paced using Retry-After or Gemini's
    body-level RetryInfo delay (falling back to exponential backoff). Daily
    quota / limit=0 failures stop immediately, and consecutive temporary
    waits are capped so uploads cannot stall indefinitely.

    Returns the raw assistant message content (callers parse it with
    _parse_json_object). Raises RuntimeError with a plain-language
    explanation (including the real underlying cause — e.g. repeated 429s)
    if every attempt fails.
    """
    formats = _format_ladder(model, strict_format)
    # Tune attempts: vision models (non-strict) tend to fail json_object consistently with <think>,
    # so waste fewer retries there and give more retries to plain-text where we control parsing.
    if model not in _STRICT_SCHEMA_MODELS:
        primary_attempts = min(primary_attempts, 2)
        fallback_attempts = max(fallback_attempts, 3)
    last_error: Optional[Exception] = None
    total_attempts = 0
    rate_limit_waits = 0
    last_retry_after: Optional[float] = None
    # Provider-aware rate-limit cap: check {PROVIDER}_MAX_RATE_LIMIT_RETRIES, LLM_*, then legacy GROQ_*  # noqa: E501
    _rate_limit_cap_env = None
    for _env in [
        f"{LLM_PROVIDER.upper()}_MAX_RATE_LIMIT_RETRIES",
        "LLM_MAX_RATE_LIMIT_RETRIES",
        "GROQ_MAX_RATE_LIMIT_RETRIES",
        "GEMINI_MAX_RATE_LIMIT_RETRIES",
    ]:
        if os.environ.get(_env) is not None:
            _rate_limit_cap_env = _env
            break
    try:
        if _rate_limit_cap_env:
            max_rate_limit_waits = int(os.environ.get(_rate_limit_cap_env, "5"))
        else:
            max_rate_limit_waits = int(os.environ.get("GROQ_MAX_RATE_LIMIT_RETRIES", "5"))
    except ValueError:
        max_rate_limit_waits = 5
    last_raw_snippet: str = ""
    max_tokens = _completion_token_budget(user_content)
    completion_ceiling = _max_completion_ceiling()
    budget_escalations = 0
    suppress_state = _suppress_state(model) if _suppression_applies(model) else None
    # Provider-error trail for the final RuntimeError's root-cause hint:
    # (status, code) -> times seen across every rung and repair attempt.
    status_counts: Dict[Tuple[Any, Any], int] = {}

    def _note_status(exc: Exception) -> None:
        key = (getattr(exc, "status_code", None), getattr(exc, "code", None) or None)
        if key[0] is not None:
            status_counts[key] = status_counts.get(key, 0) + 1

    # Walk rungs as: output format (server-enforced -> looser) ×
    # reasoning-suppression probe (best -> bare). Suppression probes only
    # cost extra requests on the FAILURE path — the happy path returns on
    # the first rung — and for a reasoning model they convert a guaranteed
    # fail (400 json_validate_failed / truncated <think>) into a one-call
    # success. Once a probe is proven to work it is tried first for every
    # later format and later call with this model (_suppress_state cache).
    level = 0
    rung_index = 0
    while level < len(formats):
        response_format, prompt_suffix = formats[level]
        candidates = _suppression_candidates(
            model
        )  # recomputed per format: probes crossed off earlier are skipped
        ci = 0
        while ci < len(candidates):
            probe_idx, probe_extra = candidates[ci]
            probe_label = (
                _REASONING_SUPPRESS_LABELS[probe_idx] if probe_idx is not None else "no suppression"
            )
            is_last_rung = (level == len(formats) - 1) and (ci == len(candidates) - 1)
            attempts = primary_attempts if rung_index == 0 else fallback_attempts
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
                    if probe_extra is not None:
                        # Sent via the OpenAI SDK's extra_body passthrough — the
                        # provider either honors it, rejects it with a 400 we
                        # detect below, or silently ignores it (detected via
                        # _contains_reasoning_dump on the response).
                        request_kwargs["extra_body"] = probe_extra
                    response = _chat_completion(**request_kwargs)
                    raw = response.choices[0].message.content or ""
                    truncated = _response_was_truncated(response)
                    # Validate parseability before returning: if raw contains no parseable JSON
                    # (e.g. a <think>-only reasoning dump), the same response format will likely
                    # fail again — advance to the next rung instead of burning retries.
                    parse_err: Optional[ValueError] = None
                    if raw.strip():
                        try:
                            _parse_json_object(raw)
                        except ValueError as err:
                            parse_err = err
                            last_error = err
                            last_raw_snippet = raw[:500]
                    if parse_err is None and raw.strip():
                        if probe_idx is not None and suppress_state is not None:
                            # Probe proven to work — lead with it from now on.
                            suppress_state["good"] = probe_idx
                            logger.info(
                                "_completion_resilient: model='%s' clean JSON with suppression probe '%s' — "  # noqa: E501
                                "using it as the default for this model",
                                model,
                                probe_label,
                            )
                        return raw
                    if truncated:
                        # The provider cut the generation at max_tokens BEFORE the
                        # JSON closed (finish_reason='length'). This is the #1
                        # cause of "valid-looking JSON that won't parse" on dense
                        # lab reports — the raw text starts with '{' but ends
                        # mid-string/mid-array. Advancing to the next rung used to
                        # re-send the SAME request with the SAME budget, which
                        # truncates at the same point again and only succeeds by
                        # luck. Instead: raise the completion budget and retry
                        # THIS rung; only advance (with the raised budget kept)
                        # once the ceiling or escalation cap is reached.
                        last_error = ValueError(
                            "model output was truncated at the provider's token limit "
                            f"(finish_reason={_finish_reason_text(response)}) before the JSON completed"  # noqa: E501
                        )
                        raised_budget = min(max_tokens * 2, completion_ceiling)
                        if (
                            raised_budget > max_tokens
                            and budget_escalations < _MAX_BUDGET_ESCALATIONS
                        ):
                            budget_escalations += 1
                            logger.warning(
                                "_completion_resilient: model='%s' level=%d attempt=%d (%s) output was "  # noqa: E501
                                "TRUNCATED at max_tokens=%d before the JSON completed — retrying this "  # noqa: E501
                                "rung with max_tokens=%d (escalation %d/%d)",
                                model,
                                level,
                                attempt,
                                probe_label,
                                max_tokens,
                                raised_budget,
                                budget_escalations,
                                _MAX_BUDGET_ESCALATIONS,
                            )
                            max_tokens = raised_budget
                            continue
                        logger.warning(
                            "_completion_resilient: model='%s' level=%d attempt=%d (%s) output was "
                            "TRUNCATED (finish_reason=%s) and the completion budget cannot be raised "  # noqa: E501
                            "further (max_tokens=%d, ceiling=%d) — advancing to the next rung: %s",
                            model,
                            level,
                            attempt,
                            probe_label,
                            _finish_reason_text(response),
                            max_tokens,
                            completion_ceiling,
                            parse_err or last_error,
                        )
                        break
                    if not raw or not raw.strip():
                        last_error = ValueError(
                            "model returned an empty response — no JSON to parse"
                        )
                        logger.warning(
                            "_completion_resilient: model='%s' level=%d attempt=%d (%s) returned an EMPTY "  # noqa: E501
                            "response — advancing to the next rung",
                            model,
                            level,
                            attempt,
                            probe_label,
                        )
                        # An empty generation is a model-side hiccup; retrying the
                        # exact same request usually repeats it, so move on to the
                        # next probe/output mode instead of burning attempts.
                        break
                    # Non-JSON output (reasoning dump, commentary, ...) with no
                    # truncation involved — same request likely fails again, so
                    # advance to the next rung instead of burning retries.
                    if parse_err is not None:
                        if probe_idx is not None and _contains_reasoning_dump(raw):
                            # The switch provably left thinking on (provider
                            # silently ignored it) — cross it off for good so
                            # no later format or later call wastes a request on it.
                            suppress_state["dead"].add(probe_idx)
                            logger.warning(
                                "_completion_resilient: model='%s' suppression probe '%s' did not stop "  # noqa: E501
                                "the model emitting <think> — crossing the probe off",
                                model,
                                probe_label,
                            )
                        else:
                            logger.warning(
                                "_completion_resilient: model='%s' level=%d attempt=%d (%s) returned non-JSON "  # noqa: E501
                                "(snippet %r) — advancing to the next rung: %s",
                                model,
                                level,
                                attempt,
                                probe_label,
                                raw[:250].replace(chr(10), " "),
                                parse_err,
                            )
                        break
                except APIError as e:
                    if _is_unsupported_param_error(e, probe_extra):
                        # Provider/model doesn't recognize this suppression
                        # switch — cross it off permanently and move to the
                        # next probe instead of erroring the upload. (Not
                        # counted in status_counts: this 400 is our own
                        # probe artifact, not provider trouble worth
                        # surfacing in the root-cause hint.)
                        suppress_state["dead"].add(probe_idx)
                        last_error = e
                        logger.warning(
                            "_completion_resilient: provider '%s' does not accept suppression probe '%s' "  # noqa: E501
                            "for model='%s' (HTTP %s) — crossing the probe off: %s",
                            LLM_PROVIDER,
                            probe_label,
                            model,
                            getattr(e, "status_code", "?"),
                            _error_detail(e),
                        )
                        break
                    _note_status(e)
                    if not _is_retryable_api_error(e):
                        logger.error(
                            f"Provider '{LLM_PROVIDER}' request failed for model='%s' (non-retryable, not retrying): %s",  # noqa: E501
                            model,
                            _error_detail(e),
                        )
                        raise
                    if _is_json_validation_failure(e):
                        # Groq validated the generation server-side and discarded
                        # it (typically because a reasoning model emitted a
                        # <think> preamble, or produced nothing). Re-issuing the
                        # SAME request will fail again — try the next
                        # suppression probe / looser output mode.
                        last_error = e
                        if probe_idx is not None and _failed_generation_shows_thinking(e):
                            # Positive evidence thinking survived the probe —
                            # the provider ignored it; never try it again.
                            # (An empty/ambiguous failed_generation does NOT
                            # cross the probe off: suppression may have worked
                            # and the answer JSON failed for another reason.)
                            suppress_state["dead"].add(probe_idx)
                            logger.warning(
                                "_completion_resilient: model='%s' discarded generation still contains "  # noqa: E501
                                "<think> despite suppression probe '%s' — crossing the probe off",
                                model,
                                probe_label,
                            )
                        logger.warning(
                            f"Provider '{LLM_PROVIDER}' rejected model='%s' generation server-side (JSON validation) — "  # noqa: E501
                            "advancing to the next rung (%s): %s",
                            model,
                            probe_label,
                            _error_detail(e),
                        )
                        break
                    if _is_token_budget_error(e):
                        # A provider-side 413 here is not an oversized upload. It
                        # means prompt/image tokens + max_tokens exceed TPM. Retry
                        # with less output headroom instead of returning a 422.
                        last_error = e
                        reduced_budget = max(256, max_tokens // 2)
                        if reduced_budget < max_tokens:
                            logger.warning(
                                f"Provider '{LLM_PROVIDER}' token budget rejected model='%s' request; "  # noqa: E501
                                "reducing max_tokens from %d to %d: %s",
                                model,
                                max_tokens,
                                reduced_budget,
                                _error_detail(e),
                            )
                            max_tokens = reduced_budget
                        if is_last_rung and attempt == attempts:
                            break
                        time.sleep(backoff_seconds * attempt)
                        continue
                    if getattr(e, "status_code", None) == 429:
                        rate_limit_waits += 1
                        last_error = e
                        sleep_s = min(_retry_after_seconds(e, backoff_seconds * attempt), 60.0)
                        last_retry_after = sleep_s

                        # A daily/account quota, explicit limit=0, or a
                        # retired model cannot recover after a short sleep.
                        # Fail on the first response so a four-file upload
                        # does not turn into twenty identical provider calls.
                        hard_quota = _is_hard_quota_error(e)
                        retired_model = _is_retired_provider_model(model)
                        if hard_quota or retired_model:
                            # A configured OpenRouter fallback is deliberately
                            # used only for unrecoverable quota/model failures,
                            # never routine short-lived 429s. Re-run this exact
                            # ladder rung through the fallback client.
                            if (
                                not _openrouter_fallback_is_active()
                                and _activate_openrouter_fallback()
                            ):
                                logger.warning(
                                    "Retrying model='%s' through OpenRouter fallback after primary hard quota failure.",  # noqa: E501
                                    model,
                                )
                                continue
                            provider_name = (
                                "openrouter" if _openrouter_fallback_is_active() else LLM_PROVIDER
                            )
                            logger.error(
                                "Provider '%s' has no usable quota for model='%s' "
                                "(hard_quota=%s retired=%s); not retrying: %s",
                                provider_name,
                                model,
                                hard_quota,
                                retired_model,
                                _error_detail(e),
                            )
                            raise ProviderRateLimitError(
                                provider=provider_name,
                                model=model,
                                retry_after_seconds=sleep_s,
                                hard_quota=True,
                                retired_model=retired_model,
                            ) from e

                        if rate_limit_waits >= max_rate_limit_waits:
                            raise ProviderRateLimitError(
                                provider="openrouter"
                                if _openrouter_fallback_is_active()
                                else LLM_PROVIDER,
                                model=model,
                                retry_after_seconds=sleep_s,
                            ) from e
                        logger.warning(
                            "Provider '%s' rate-limited (429) model='%s' — sleeping %.0fs before retry "  # noqa: E501
                            "(wait %d/%d): %s",
                            LLM_PROVIDER,
                            model,
                            sleep_s,
                            rate_limit_waits,
                            max_rate_limit_waits,
                            _error_detail(e),
                        )
                        if is_last_rung and attempt == attempts:
                            break
                        time.sleep(sleep_s)
                        continue
                    # Other transient provider errors (5xx, 408/409) and network
                    # blips — these are worth retrying on the same rung.
                    last_error = e
                    logger.warning(
                        f"Provider '{LLM_PROVIDER}' transient error for model='%s', retrying (attempt %d/%d): %s",  # noqa: E501
                        model,
                        attempt,
                        attempts,
                        _error_detail(e),
                    )
                    if is_last_rung and attempt == attempts:
                        break  # last rung exhausted — no point sleeping first
                    time.sleep(backoff_seconds * attempt)
                except ValueError as e:
                    # Defensive net: any ValueError we raised ourselves above is
                    # already handled; this catches direct raises from callbacks.
                    last_error = e
                    if "empty response" in str(e):
                        logger.warning(
                            "_completion_resilient: model='%s' empty response on attempt %d",
                            model,
                            attempt,
                        )
                    if is_last_rung and attempt == attempts:
                        break
                    time.sleep(backoff_seconds * attempt)
                    continue
            rung_index += 1
            ci += 1
        level += 1

    # All ladder rungs exhausted — one last vision repair retry with the
    # ACTUAL image and an explicit JSON-only instruction. This is the only
    # honest repair available for image inputs: a text-only fallback model
    # fed just the error snippet cannot recover document content, so the
    # old "text-model repair" strategy was removed — it fabricated a minimal
    # all-empty JSON (document_type 'other', confidence 0.0) that the
    # medical-document filter then rejected with a misleading "not a medical
    # document" 422, hiding what was really a transient provider failure
    # (rate limits / model hiccup). An honest RuntimeError -> HTTP 502
    # "please retry" replaces that dead end.
    if last_error is not None and (
        "could not be parsed" in str(last_error)
        or "empty response" in str(last_error)
        or _is_json_validation_failure(last_error)
    ):
        if _is_vision_content(user_content):
            try:
                logger.info(
                    "Attempting vision repair retry with explicit JSON-only instruction for model=%s",  # noqa: E501
                    model,
                )
                repair_system_vision = (
                    "You are a medical document extraction engine. Your previous response was INVALID because it contained "  # noqa: E501
                    "reasoning, analysis, or <think> tags instead of ONLY JSON. Now you MUST output ONLY a single valid JSON object. "  # noqa: E501
                    "The very first character must be '{' and the last must be '}'. No <think>, no markdown, no explanations. "  # noqa: E501
                    "Conform exactly to the provided JSON Schema."
                )
                # Build repair user content: keep the original image but replace text with repair instruction  # noqa: E501
                repair_text = (
                    f"Previous attempt failed: {str(last_error)[:300]}. Last snippet: {last_raw_snippet[:400]!r}. "  # noqa: E501
                    "Now extract structured data from this medical document image and output ONLY the JSON object, starting with '{'."  # noqa: E501
                )
                # Preserve image_url entries from original user_content
                image_parts = [
                    c for c in user_content if isinstance(c, dict) and c.get("type") == "image_url"
                ]
                repair_user_content = [{"type": "text", "text": repair_text}] + image_parts
                repair_messages = [
                    {
                        "role": "system",
                        "content": repair_system_vision
                        + "\nSchema: "
                        + json.dumps(strict_format["json_schema"]["schema"], indent=2),
                    },
                    {"role": "user", "content": repair_user_content},
                ]
                repair_kwargs: Dict[str, Any] = {
                    "model": model,
                    "messages": repair_messages,
                    "temperature": 0,
                    "top_p": 1,
                    "max_tokens": max_tokens,
                    # No response_format — use plain text so we can parse ourselves even if model adds stray text  # noqa: E501
                }
                best_extra = _best_suppression_extra_body(model)
                if best_extra is not None:
                    repair_kwargs["extra_body"] = best_extra
                resp = _chat_completion(**repair_kwargs)
                raw_repair_vision = resp.choices[0].message.content or ""
                if raw_repair_vision and raw_repair_vision.strip():
                    try:
                        _parse_json_object(raw_repair_vision)
                        logger.info("Vision repair retry succeeded")
                        return raw_repair_vision
                    except ValueError as ve:
                        logger.warning(
                            "Vision repair also not parseable: %s (snippet %r)",
                            ve,
                            raw_repair_vision[:250],
                        )
                        last_error = ve
                        last_raw_snippet = raw_repair_vision[:500]
            except Exception as repair_e:
                logger.warning("Vision repair attempt failed: %s", repair_e)
                _note_status(repair_e)

    # Surface the REAL cause so the API's 502 "please retry" message tells the
    # truth — e.g. repeated rate-limiting on a saturated token budget, or a
    # model that keeps emitting reasoning instead of JSON — summarized from
    # every provider rejection seen along the way (not just the last error,
    # which often hides the earlier, more informative ones).
    cause_bits: List[str] = []
    total_429s = sum(count for (status, _code), count in status_counts.items() if status == 429)
    if total_429s and last_error is not None and getattr(last_error, "status_code", None) == 429:
        raise ProviderRateLimitError(
            provider="openrouter" if _openrouter_fallback_is_active() else LLM_PROVIDER,
            model=model,
            retry_after_seconds=last_retry_after,
        ) from last_error
    if total_429s:
        cause_bits.append(
            f"the provider rate-limited (HTTP 429) {total_429s} attempt(s), which usually means "
            "the account's per-minute token budget is saturated"
        )
    provider_summary = ", ".join(
        f"HTTP {status}{f' ({code})' if code else ''} ×{count}"
        for (status, code), count in sorted(status_counts.items(), key=lambda kv: -kv[1])
        if status != 429
    )
    if provider_summary:
        cause_bits.append(f"provider rejections along the way: {provider_summary}")
    if last_error is not None and "truncated at the provider's token limit" in str(last_error):
        cause_bits.append(
            "the model's output kept being cut off by the provider's completion-token limit "
            "before the JSON could finish, even after the budget was raised — the document may "
            "be too dense for a single response (try fewer pages per file)"
        )
    elif last_error is not None and "could not be parsed" in str(last_error):
        cause_bits.append(
            "the model kept emitting reasoning/non-JSON instead of the required JSON across all output modes"  # noqa: E501
        )
    cause = (" Root cause hint: " + "; ".join(cause_bits) + ".") if cause_bits else ""

    raise RuntimeError(
        f"Model '{model}' repeatedly failed to return valid structured JSON "
        f"({total_attempts} attempt(s) across {rung_index} output-mode/suppression "
        "combination(s), including retries with looser output formats and "
        "reasoning suppression)." + cause + " This is usually a transient "
        "hiccup on the model provider's side — please retry the upload. If "
        "the same file keeps failing, it may be too blurry, rotated, or "
        "mostly handwritten; try a clearer photo or a higher-resolution "
        f"scan. Last snippet: {last_raw_snippet[:250]!r}"
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
_THINK_OPEN_RE = re.compile(
    r"<\s*(think|thinking|thought|reasoning|analysis)\s*>", flags=re.IGNORECASE
)
# Also handle HTML-entity encoded tags that sometimes surface in logging/transport
_THINK_ENCODED_BLOCK_RE = re.compile(
    r"&lt;\s*(think|thinking|thought|reasoning|analysis)\s*&gt;.*?&lt;\s*/\s*(think|thinking|thought|reasoning|analysis)\s*&gt;",
    flags=re.DOTALL | re.IGNORECASE,
)
_THINK_ENCODED_OPEN_RE = re.compile(
    r"&lt;\s*(think|thinking|thought|reasoning|analysis)\s*&gt;", flags=re.IGNORECASE
)


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
            tail = cleaned[m.end() :]
            # Check if there's a closer of either form after opener
            closer = re.search(
                r"<\s*/\s*(think|thinking|thought|reasoning|analysis)\s*>",
                tail,
                flags=re.IGNORECASE,
            )
            closer_enc = re.search(
                r"&lt;\s*/\s*(think|thinking|thought|reasoning|analysis)\s*&gt;",
                tail,
                flags=re.IGNORECASE,
            )
            closer_pos = None
            if closer and closer_enc:
                closer_pos = (
                    closer.start() if closer.start() < closer_enc.start() else closer_enc.start()
                )
                closer_end = (
                    closer.end() if closer.start() < closer_enc.start() else closer_enc.end()
                )
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
            cleaned = cleaned[: m.start()] + tail
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


def _escape_control_chars_in_strings(candidate: str) -> str:
    """Escape raw control characters that appear INSIDE JSON string values.

    A frequent provider quirk: the model emits a literal newline/tab inside a
    string value (e.g. a multi-line "clinical_notes") instead of the escaped
    \\n/\\t form. json.loads rejects those with "Invalid control character",
    and every other repair path fails on the same bytes. Outside string
    literals, control characters are legal JSON whitespace and are left
    untouched (escaping them there would corrupt the document).
    """
    if not any(ord(ch) < 0x20 for ch in candidate):
        return candidate
    short_escapes = {"\n": "\\n", "\r": "\\r", "\t": "\\t", "\b": "\\b", "\f": "\\f"}
    out: List[str] = []
    in_string = False
    escaped = False
    for ch in candidate:
        if escaped:
            out.append(ch)
            escaped = False
            continue
        if ch == "\\":
            out.append(ch)
            escaped = True
            continue
        if ch == '"':
            in_string = not in_string
            out.append(ch)
            continue
        if in_string and ord(ch) < 0x20:
            out.append(short_escapes.get(ch) or f"\\u{ord(ch):04x}")
            continue
        out.append(ch)
    return "".join(out)


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
    no_trailing = re.sub(r",\s*([}\]])", r"\1", cleaned)
    try:
        obj = json.loads(no_trailing)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
    try:
        # Raw control characters inside string values (a literal newline in
        # "clinical_notes" etc.) — escape them and re-parse. Combines with the
        # trailing-comma fix above since both quirks can appear together.
        escaped = _escape_control_chars_in_strings(no_trailing)
        obj = json.loads(escaped)
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
        fenced = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?```", source, flags=re.DOTALL | re.IGNORECASE
        )
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
        span = text[start : end + 1]
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
        candidate = raw_decoded[s_idx : e_idx + 1]
        repaired4 = _try_repair_json(candidate)
        if repaired4 is not None:
            return repaired4
        obj6 = _find_first_json_object(candidate)
        if obj6 is not None:
            return obj6

    snippet = raw_stripped[:350].replace("\n", " ").replace("\r", "")
    raise ValueError(f"model output could not be parsed as JSON (starts with: {snippet!r})")


# ---------------------------------------------------------------------------
# 1. Extraction schema — keeps every document's output shape consistent
# ---------------------------------------------------------------------------

EXTRACTION_SCHEMA_PROMPT = """
You are a medical document extraction engine. You will be shown an image or
text from a medical document (prescription, lab or imaging report, discharge
summary, consultation note, or procedure report).

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

LONGITUDINAL CLINICAL EVENTS — extract only what the document explicitly
states, preserving separate event dates when printed:
- `diagnoses`: documented problem-list/assessment diagnoses only. Never infer
  a diagnosis from symptoms, medication, labs, or imaging. `status` describes
  how the source presents it: confirmed, suspected, history, resolved, or
  unknown. Keep any printed ICD/code in `code`; otherwise null.
- `symptoms`: patient-reported symptoms or documented signs. Do not turn a
  symptom into a diagnosis. Use only printed severity/status information.
- `procedures`: completed, planned, cancelled, or historical operations,
  interventions, therapies, or bedside procedures. Keep outcome/body site
  only when documented.
- `vital_signs`: one object per printed measurement (blood pressure, pulse,
  temperature, respiratory rate, oxygen saturation, height, weight, BMI,
  etc.). Keep `value` exactly as printed and never guess or convert a unit.
- `imaging_results`: one object per radiology/imaging study. Keep the study,
  body site, findings, and impression as documented; never promote an imaging
  finding into a diagnosis.
- Use null for an event-specific date when the document does not print one;
  the timeline will fall back to the enclosing document date.

PAGE-LEVEL EVIDENCE — every extracted fact must point back to the document:
- Include a short VERBATIM quote for every date, identity, provider, allergy,
  clinical note, medication, lab result, diagnosis, symptom, procedure, vital
  sign, and imaging result. Never paraphrase the quote.
- `page` is 1-based. Text PDFs contain explicit `--- Page N ---` markers;
  use that N. For a single image use page 1.
- For image input, return `bbox` as [left, top, right, bottom] in a 0..1000
  coordinate frame around the smallest readable line/row supporting the
  fact. For text input, set bbox to null; deterministic PDF text search will
  calculate the exact rectangle after extraction.
- If a fact is inferred rather than printed (for example a generic ingredient
  inferred from a brand), cite the printed brand line and lower evidence
  confidence. If no supporting text exists, use an empty evidence array.

PATIENT IDENTITY FIELDS — used to detect a document that belongs to a
different patient than this account's other documents:
- patient_age: the patient's age as printed on the document (a number), or
  null if not printed. Never estimate an age that isn't stated.
- patient_gender: "male", "female", or the document's own wording,
  lowercased; null if not stated.

LANGUAGE / CONFIDENCE METADATA — used to grade OCR risk vs translation
risk separately (they have different fixes):
- document_language: the main language the document is printed in, as an
  English name (e.g. "English", "Japanese", "Sinhala"); null only if
  genuinely indeterminate.
- additional_languages: other languages that appear on the document
  (mixed-language documents are common); empty array if none.
- ocr_confidence: 0.0-1.0 — could you READ the characters off the page?
  Low for handwriting, blur, glare, cut-off edges. Independent of language.
- translation_confidence: 0.0-1.0 — did you convert what you read into the
  normalized English fields (ingredients as INN names, units, frequencies)
  faithfully? Low for transliterated drug names, unfamiliar regional
  brands, ambiguous dosing phrases. A crisply printed foreign-language
  document can score HIGH on ocr_confidence and lower on
  translation_confidence; a blurry English note is the opposite. Report
  them independently — do not blend them.

Rules:
- Extract diagnoses_or_conditions only when the document explicitly names
  them. Preserve the printed wording; do not infer a diagnosis from a test,
  symptom, or medication.
- If handwriting is unclear, make your best guess but LOWER the confidence
  score for that field and add a note to illegible_or_low_confidence_fields.
- Never invent data. Use null for missing string fields (per the schema).
- Do not provide medical advice or infer a new diagnosis — extraction of documented facts only.
"""

# One supporting region. Vision returns 0..1000 coordinates which are
# normalized to 0..1 after parsing; digital PDFs return null and are resolved
# exactly with PyMuPDF text search against the original page.
EVIDENCE_REGION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "page": {"type": "integer", "minimum": 1},
        "quote": {"type": "string"},
        "bbox": {
            "type": ["array", "null"],
            "items": {"type": "number", "minimum": 0, "maximum": 1000},
            "minItems": 4,
            "maxItems": 4,
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["page", "quote", "bbox", "confidence"],
    "additionalProperties": False,
}

EVIDENCE_LIST_JSON_SCHEMA = {
    "type": "array",
    "items": EVIDENCE_REGION_JSON_SCHEMA,
}

# Longitudinal events must be explicitly documented, so accepting an event
# without at least one source locator would violate the record's trust model.
CLINICAL_EVIDENCE_LIST_JSON_SCHEMA = {
    **EVIDENCE_LIST_JSON_SCHEMA,
    "minItems": 1,
}

DIAGNOSIS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "code": {"type": ["string", "null"]},
        "status": {
            "type": "string",
            "enum": ["active", "confirmed", "suspected", "history", "resolved", "unknown"],
        },
        "onset_date": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": CLINICAL_EVIDENCE_LIST_JSON_SCHEMA,
    },
    "required": ["name", "code", "status", "onset_date", "confidence", "evidence"],
    "additionalProperties": False,
}

SYMPTOM_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "severity": {"type": "string", "enum": ["mild", "moderate", "severe", "unknown"]},
        "status": {
            "type": "string",
            "enum": ["current", "resolved", "intermittent", "historical", "unknown"],
        },
        "onset_date": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": CLINICAL_EVIDENCE_LIST_JSON_SCHEMA,
    },
    "required": ["name", "severity", "status", "onset_date", "confidence", "evidence"],
    "additionalProperties": False,
}

PROCEDURE_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "procedure_date": {"type": ["string", "null"]},
        "body_site": {"type": ["string", "null"]},
        "status": {
            "type": "string",
            "enum": ["completed", "planned", "cancelled", "historical", "unknown"],
        },
        "outcome": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": CLINICAL_EVIDENCE_LIST_JSON_SCHEMA,
    },
    "required": [
        "name",
        "procedure_date",
        "body_site",
        "status",
        "outcome",
        "confidence",
        "evidence",
    ],
    "additionalProperties": False,
}

VITAL_SIGN_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "value": {"type": "string"},
        "unit": {"type": ["string", "null"]},
        "measured_at": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": CLINICAL_EVIDENCE_LIST_JSON_SCHEMA,
    },
    "required": ["name", "value", "unit", "measured_at", "confidence", "evidence"],
    "additionalProperties": False,
}

IMAGING_RESULT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "study_type": {"type": "string"},
        "body_site": {"type": ["string", "null"]},
        "study_date": {"type": ["string", "null"]},
        "findings": {"type": "string"},
        "impression": {"type": ["string", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "evidence": CLINICAL_EVIDENCE_LIST_JSON_SCHEMA,
    },
    "required": [
        "study_type",
        "body_site",
        "study_date",
        "findings",
        "impression",
        "confidence",
        "evidence",
    ],
    "additionalProperties": False,
}

# Strict JSON Schema (OpenAI Structured Outputs) — guarantees every field,
# including evidence links, is always present in the response.
EXTRACTION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "document_type": {
            "type": "string",
            "enum": [
                "prescription",
                "lab_report",
                "discharge_summary",
                "imaging_report",
                "consultation_note",
                "procedure_report",
                "other",
            ],
        },
        "date": {"type": ["string", "null"]},
        "provider_or_doctor": {"type": ["string", "null"]},
        "patient_name": {"type": ["string", "null"]},
        "patient_age": {"type": ["number", "null"]},
        "patient_gender": {"type": ["string", "null"]},
        "document_language": {"type": ["string", "null"]},
        "additional_languages": {"type": "array", "items": {"type": "string"}},
        "ocr_confidence": {"type": ["number", "null"]},
        "translation_confidence": {"type": ["number", "null"]},
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
                    "evidence": EVIDENCE_LIST_JSON_SCHEMA,
                },
                "required": [
                    "name",
                    "ingredients",
                    "dosage",
                    "frequency",
                    "duration",
                    "dosage_value",
                    "dosage_unit",
                    "frequency_per_day",
                    "is_as_needed",
                    "confidence",
                    "evidence",
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
                    "evidence": EVIDENCE_LIST_JSON_SCHEMA,
                },
                "required": [
                    "test_name",
                    "value",
                    "unit",
                    "reference_range",
                    "flag",
                    "confidence",
                    "evidence",
                ],
                "additionalProperties": False,
            },
        },
        "diagnoses": {"type": "array", "items": DIAGNOSIS_JSON_SCHEMA},
        "symptoms": {"type": "array", "items": SYMPTOM_JSON_SCHEMA},
        "procedures": {"type": "array", "items": PROCEDURE_JSON_SCHEMA},
        "vital_signs": {"type": "array", "items": VITAL_SIGN_JSON_SCHEMA},
        "imaging_results": {"type": "array", "items": IMAGING_RESULT_JSON_SCHEMA},
        "allergies_noted": {"type": "array", "items": {"type": "string"}},
        "diagnoses_or_conditions": {"type": "array", "items": {"type": "string"}},
        "clinical_notes": {"type": ["string", "null"]},
        "field_evidence": {
            "type": "object",
            "properties": {
                "date": EVIDENCE_LIST_JSON_SCHEMA,
                "provider_or_doctor": EVIDENCE_LIST_JSON_SCHEMA,
                "patient_name": EVIDENCE_LIST_JSON_SCHEMA,
                "allergies_noted": EVIDENCE_LIST_JSON_SCHEMA,
                "clinical_notes": EVIDENCE_LIST_JSON_SCHEMA,
            },
            "required": [
                "date",
                "provider_or_doctor",
                "patient_name",
                "allergies_noted",
                "clinical_notes",
            ],
            "additionalProperties": False,
        },
        "illegible_or_low_confidence_fields": {"type": "array", "items": {"type": "string"}},
        "overall_confidence": {"type": "number"},
    },
    "required": [
        "document_type",
        "date",
        "provider_or_doctor",
        "patient_name",
        "patient_age",
        "patient_gender",
        "document_language",
        "additional_languages",
        "ocr_confidence",
        "translation_confidence",
        "medications",
        "lab_results",
        "diagnoses",
        "symptoms",
        "procedures",
        "vital_signs",
        "imaging_results",
        "allergies_noted",
        "diagnoses_or_conditions",
        "clinical_notes",
        "field_evidence",
        "illegible_or_low_confidence_fields",
        "overall_confidence",
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


def pdf_pages_to_images(
    pdf_path: str,
    dpi: int = 200,
    page_indices: Optional[List[int]] = None,
) -> List[Image.Image]:
    """Render PDF pages into PIL images.

    ``page_indices`` (0-based) limits rendering to those pages so a hybrid
    PDF does not rasterize digital text pages that will be extracted as
    text. When omitted, every page is rendered (scanned-PDF path).
    """
    images = []
    doc = pymupdf.open(pdf_path)
    zoom = dpi / 72
    matrix = pymupdf.Matrix(zoom, zoom)
    indices = list(page_indices) if page_indices is not None else list(range(len(doc)))
    for i in indices:
        page = doc[i]
        pix = page.get_pixmap(matrix=matrix)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        images.append(img)
    doc.close()
    return images


# A page with fewer than this many extracted characters is treated as
# scanned/image-only and sent through vision OCR. 40 is high enough that
# a digital letterhead-only cover (hospital name + address) still counts
# as text, but a junk OCR layer of a few random glyphs does not.
PAGE_TEXT_MIN_CHARS = 40


def _pdf_page_texts(pdf_path: str) -> List[str]:
    """Return stripped text for every page, in order."""
    texts: List[str] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            texts.append((page.extract_text() or "").strip())
    return texts


def classify_pdf_pages(
    page_texts: List[str], min_chars: int = PAGE_TEXT_MIN_CHARS
) -> Tuple[List[int], List[int]]:
    """Split page indices into (has_usable_text, needs_vision)."""
    text_idx: List[int] = []
    image_idx: List[int] = []
    for i, text in enumerate(page_texts):
        if len((text or "").strip()) >= min_chars:
            text_idx.append(i)
        else:
            image_idx.append(i)
    return text_idx, image_idx


def _ocr_scan_pdf_pages(
    file_path: str, page_indices: List[int], progress_callback: Optional[Any] = None
) -> Tuple[Optional[str], Optional[float], List[int]]:
    """Best-effort offline OCR of scanned PDF pages.

    Returns (transcript, avg_confidence, ocr_pages) when Tesseract is
    available AND the transcript is trustworthy; (None, None, []) in every
    other case — including engine absence and OCR failures. This layer
    never blocks an extraction: the caller keeps its vision path when it
    declines.
    """
    if not page_indices or not is_tesseract_available():
        return None, None, []
    try:
        _emit_document_progress(
            progress_callback,
            "reading",
            f"Reading scanned page(s) with offline OCR ({len(page_indices)} page(s))",
        )
        results = ocr_pdf_pages(file_path, page_indices)
        usable, joined, avg = transcript_is_usable(results, min_chars=PAGE_TEXT_MIN_CHARS)
        if not usable:
            logger.info(
                "ocr: '%s' transcript not trusted (avg confidence=%s); using vision for %d page(s)",
                Path(file_path).name,
                avg,
                len(page_indices),
            )
            return None, None, []
        logger.info(
            "ocr: '%s' transcript usable (avg confidence=%s) for %d scanned page(s) — text path",
            Path(file_path).name,
            avg,
            len(page_indices),
        )
        return joined, avg, [r.page for r in results if r.text and r.text.strip()]
    except (TesseractNotFoundError, InvalidPDFError, OCRError) as exc:
        logger.warning("ocr: '%s' skipped (%s); using vision", Path(file_path).name, exc)
        return None, None, []
    except Exception as exc:  # defensive — OCR must never take down extraction
        logger.warning(
            "ocr: '%s' failed unexpectedly (%s); using vision", Path(file_path).name, exc
        )
        return None, None, []


def _ocr_image_file(file_path: str) -> Tuple[Optional[str], Optional[float]]:
    """Best-effort offline OCR of a single image file. Same fail-open
    contract as _ocr_scan_pdf_pages."""
    if not is_tesseract_available():
        return None, None
    try:
        with open(file_path, "rb") as f:
            result = ocr_image_bytes(f.read(), page=1)
        usable, joined, avg = transcript_is_usable([result], min_chars=PAGE_TEXT_MIN_CHARS)
        if not usable:
            return None, None
        return joined, avg
    except (TesseractNotFoundError, InvalidImageError, OCRError) as exc:
        logger.warning("ocr: '%s' skipped (%s); using vision", Path(file_path).name, exc)
        return None, None
    except Exception as exc:
        logger.warning(
            "ocr: '%s' failed unexpectedly (%s); using vision", Path(file_path).name, exc
        )
        return None, None


def image_to_base64(
    img: Image.Image,
) -> str:  # Downscale image if too large to prevent huge base64 payload size and potential network/timeout/size issues.  # noqa: E501
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


def _normalize_extraction_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill fields and enforce deterministic clinical-date admission."""
    diagnoses = result.get("diagnoses_or_conditions")
    if not isinstance(diagnoses, list):
        result["diagnoses_or_conditions"] = []
    else:
        result["diagnoses_or_conditions"] = [
            value.strip() for value in diagnoses if isinstance(value, str) and value.strip()
        ]

    from date_convention import sanitize_clinical_date

    date_fields = {
        "date",
        "onset_date",
        "procedure_date",
        "study_date",
        "measured_at",
        "start_date",
        "end_date",
        "result_date",
    }

    def sanitize(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in list(value.items()):
                if key in date_fields:
                    value[key] = sanitize_clinical_date(child)
                else:
                    sanitize(child)
        elif isinstance(value, list):
            for child in value:
                sanitize(child)

    sanitize(result)
    return result


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
    return _normalize_extraction_result(_parse_json_object(raw))


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
    return _normalize_extraction_result(_parse_json_object(raw))


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
    for collection in ("medications", "lab_results", *CLINICAL_EVENT_COLLECTIONS):
        for fact in result.get(collection, []) or []:
            if isinstance(fact, dict) and isinstance(fact.get("confidence"), (int, float)):
                fact["confidence"] = min(fact["confidence"], ceiling)
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

    # 1. Filename-based non-medical indicators.
    # Must be token-aware: a substring check for "cv" falsely flags
    # cardiovascular_report.pdf, recovery.pdf, coverage.pdf, etc.
    has_cv_filename = bool(
        re.search(
            r"(?:^|[^a-z0-9])(cv|resume|curriculum|portfolio)(?:[^a-z0-9]|$)",
            fn_lower,
        )
    )

    # 2. Text-based non-medical indicators (e.g. CV / Resume keywords)
    cv_keywords = [
        "curriculum vitae",
        "education",
        "experience",
        "skills",
        "projects",
        "languages",
        "publications",
        "employment",
        "work history",
        "hobbies",
        "interests",
        "about me",
        "academic history",
        "professional summary",
    ]
    cv_matches = 0
    for kw in cv_keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
            cv_matches += 1

    # 3. Medical keyword density
    medical_keywords = [
        "prescription",
        "rx",
        "medication",
        "medicine",
        "drug",
        "tablet",
        "capsule",
        "dosage",
        "dose",
        "frequency",
        "mg",
        "g",
        "ml",
        "lab",
        "laboratory",
        "report",
        "test",
        "results",
        "analysis",
        "allergy",
        "allergies",
        "clinical",
        "hospital",
        "clinic",
        "treatment",
        "diagnosis",
        "symptom",
        "procedure",
        "surgery",
        "discharge",
        "summary",
        "patient",
        "doctor",
        "physician",
        "imaging",
        "radiology",
        "x-ray",
        "ultrasound",
        "blood pressure",
        "pulse",
        "temperature",
        "oxygen saturation",
    ]
    medical_matches = 0
    for kw in medical_keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", text_lower):
            medical_matches += 1

    # If the filename or the text has strong CV indicators and very low medical keyword matches, it is rejected.  # noqa: E501
    if has_cv_filename and medical_matches < 3:
        return False

    if re.search(r"\bcurriculum vitae\b|\bresume\b", text_lower) and medical_matches < 3:
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
            "raw text analysis indicates this is a non-medical document (e.g. CV/Resume) with low medical relevance.",  # noqa: E501
        )


# ---------------------------------------------------------------------------
# 4. Top-level entry point — routes any uploaded file correctly
# ---------------------------------------------------------------------------

DocumentProgressCallback = Callable[[str, str], None]


def _emit_document_progress(
    callback: Optional[DocumentProgressCallback],
    step: str,
    message: str,
) -> None:
    """Progress reporting must never be able to break extraction itself."""
    if callback is None:
        return
    try:
        callback(step, message)
    except Exception as exc:  # pragma: no cover - defensive observer isolation
        logger.warning("Document progress callback failed: %s", exc)


def process_document(
    file_path: str,
    model: str = MODEL,
    vision_model: str = VISION_MODEL,
    progress_callback: Optional[DocumentProgressCallback] = None,
) -> Dict[str, Any]:
    """
    Accepts a path to a PDF or image file. Detects type and routes to the
    right extraction path (`model` for text-layer PDFs, `vision_model` for
    scanned pages and image files). Returns structured JSON (or a list of
    per-page JSON objects for multi-page scanned PDFs).
    """
    path = Path(file_path)
    suffix = path.suffix.lower()
    _emit_document_progress(progress_callback, "reading", "Opening and checking the document")

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
            '(e.g. "...\\Year 1\\" breaks Windows\' command-line parsing — '
            'remove the final backslash so it ends "...\\Year 1").'
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
        # Classify EACH page. The old all-or-nothing check sampled only the
        # first 3 pages: a digital coversheet in front of scanned labs made
        # the whole file take the text-layer path, so every image page was
        # silently dropped.
        page_texts = _pdf_page_texts(file_path)
        text_idx, image_idx = classify_pdf_pages(page_texts)

        if text_idx and not image_idx:
            text = extract_text_from_pdf(file_path)
            # deterministic check on the text layer before calling the LLM
            assert_text_looks_medical(text, path.name)
            _emit_document_progress(
                progress_callback, "extracting", "Finding medical details in the text"
            )
            result = extract_from_text(text, model=model)
            result = normalize_document_evidence(result, default_page=1, vision=False)
            try:
                result = locate_pdf_text_evidence(file_path, result)
            except Exception as exc:
                # Evidence enrichment must never discard an otherwise valid
                # extraction. Keep its page/quote fallback if PDF geometry
                # cannot be resolved (encrypted/irregular PDFs, etc.).
                logger.warning(
                    "Could not locate PDF evidence rectangles for '%s': %s", path.name, exc
                )
            result["_source"] = {"file": path.name, "method": "text_layer"}
            return result

        if image_idx and not text_idx:
            # Offline OCR pre-pass first: a confident transcript lets the
            # cheaper text model extract the record with zero image tokens.
            # The vision path below remains the higher-level interpreter
            # whenever OCR is unavailable or not trustworthy.
            ocr_text, ocr_conf, ocr_pages = _ocr_scan_pdf_pages(
                file_path, list(range(len(page_texts))), progress_callback
            )
            if ocr_text is not None:
                try:
                    assert_text_looks_medical(ocr_text, path.name)
                except Exception:
                    # A scanned document whose OCR read doesn't look medical
                    # may still be one — the vision model gets to judge.
                    ocr_text = None
            if ocr_text is not None:
                _emit_document_progress(
                    progress_callback, "extracting", "Finding medical details in the OCR text"
                )
                result = extract_from_text(ocr_text, model=model)
                result = normalize_document_evidence(result, default_page=1, vision=False)
                result = locate_ocr_text_evidence(ocr_text, result)
                result["_source"] = {
                    "file": path.name,
                    "method": "ocr_text_layer",
                    "ocr_confidence": ocr_conf,
                    "ocr_pages": ocr_pages,
                }
                return result

            pages = pdf_pages_to_images(file_path)
            page_results = []
            for i, img in enumerate(pages):
                _emit_document_progress(
                    progress_callback,
                    "extracting",
                    f"Finding medical details on page {i + 1} of {len(pages)}",
                )
                res = extract_from_image(img, model=vision_model)
                res = _apply_confidence_ceiling(res, VISION_OCR_CONFIDENCE_CEILING)
                res = normalize_document_evidence(res, default_page=i + 1, vision=True)
                res["_source"] = {
                    "file": path.name,
                    "method": "vision_ocr",
                    "page": i + 1,
                }
                page_results.append(res)
            return {"multi_page": True, "pages": page_results}

        # Hybrid: digital pages via text extraction, scanned pages via
        # vision — with the same offline OCR pre-pass for the scanned part.
        page_results = []
        if text_idx:
            combined = "\n\n".join(f"--- Page {i + 1} ---\n{page_texts[i]}" for i in text_idx)
            assert_text_looks_medical(combined, path.name)
            _emit_document_progress(
                progress_callback,
                "extracting",
                f"Finding medical details in {len(text_idx)} text page(s)",
            )
            text_result = extract_from_text(combined, model=model)
            text_result["_source"] = {"file": path.name, "method": "text_layer"}
            page_results.append(text_result)
        if image_idx:
            ocr_text, ocr_conf, ocr_pages = _ocr_scan_pdf_pages(
                file_path, image_idx, progress_callback
            )
            if ocr_text is not None:
                try:
                    assert_text_looks_medical(ocr_text, path.name)
                except Exception:
                    ocr_text = None
            if ocr_text is not None:
                _emit_document_progress(
                    progress_callback,
                    "extracting",
                    f"Finding medical details in the OCR text of {len(image_idx)} scanned page(s)",
                )
                ocr_result = extract_from_text(ocr_text, model=model)
                ocr_result = normalize_document_evidence(ocr_result, default_page=1, vision=False)
                ocr_result = locate_ocr_text_evidence(ocr_text, ocr_result)
                ocr_result["_source"] = {
                    "file": path.name,
                    "method": "ocr_text_layer",
                    "ocr_confidence": ocr_conf,
                    "ocr_pages": ocr_pages,
                }
                page_results.append(ocr_result)
            else:
                images = pdf_pages_to_images(file_path, page_indices=image_idx)
                for page_i, img in zip(image_idx, images):
                    _emit_document_progress(
                        progress_callback,
                        "extracting",
                        f"Finding medical details on scanned page {page_i + 1} of {len(page_texts)}",  # noqa: E501
                    )
                    res = extract_from_image(img, model=vision_model)
                    res = _apply_confidence_ceiling(res, VISION_OCR_CONFIDENCE_CEILING)
                    res["_source"] = {
                        "file": path.name,
                        "method": "vision_ocr",
                        "page": page_i + 1,
                    }
                    page_results.append(res)
        if len(page_results) == 1:
            return page_results[0]
        return {"multi_page": True, "pages": page_results}

    else:  # image types
        # Offline OCR pre-pass first (same fail-open contract as the scanned
        # PDF path): confident transcript -> text model; otherwise vision.
        ocr_text, ocr_conf = _ocr_image_file(file_path)
        if ocr_text is not None:
            try:
                assert_text_looks_medical(ocr_text, path.name)
            except Exception:
                ocr_text = None
        if ocr_text is not None:
            _emit_document_progress(
                progress_callback, "extracting", "Finding medical details in the OCR text"
            )
            result = extract_from_text(ocr_text, model=model)
            result = normalize_document_evidence(result, default_page=1, vision=False)
            result = locate_ocr_text_evidence(ocr_text, result)
            result["_source"] = {
                "file": path.name,
                "method": "ocr_text_layer",
                "ocr_confidence": ocr_conf,
                "page": 1,
            }
            return result

        img = Image.open(file_path)
        # Phone photos carry an EXIF orientation tag instead of rotated
        # pixels — apply it, or the vision model reads the document
        # sideways/upside-down and extraction silently degrades.
        # Older Pillow builds returned None when no EXIF orientation was
        # present; never pass that through to extract_from_image.
        transposed = ImageOps.exif_transpose(img)
        img = transposed if transposed is not None else img
        _emit_document_progress(
            progress_callback, "extracting", "Finding medical details in the image"
        )
        result = extract_from_image(img, model=vision_model)
        result = _apply_confidence_ceiling(result, VISION_OCR_CONFIDENCE_CEILING)
        result = normalize_document_evidence(result, default_page=1, vision=True)
        result["_source"] = {"file": path.name, "method": "vision_ocr", "page": 1}
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

    files = sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in supported)

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


# Placeholder/template markers, per script.
#
# Why this is not English-only: the extraction prompt's LANGUAGE AND UNIT
# NORMALIZATION section normalizes medication `ingredients` to the English
# INN, but `patient_name` and medication `name` are deliberately kept
# exactly as printed, in the source language. So an English-only check
# silently misses a demo/template page printed in Tamil or Sinhala — which
# for a Sri Lanka deployment is the common case, not an exotic one. A
# missed template page is ingested as real patient data and pollutes the
# timeline, the safety cross-check and the lab trends.
#
# Two sets, because matching rules differ by script:
#
#   _DEMO_MARKERS_WORD — scripts that delimit words with whitespace. These
#     are matched on word boundaries, so a legitimate name that merely
#     *contains* the letters (e.g. Spanish surname "Muestras", or an English
#     "Sampleton") is not falsely rejected. False-rejecting a real document
#     is worse than admitting a demo one, so precision matters more here.
#
#   _DEMO_MARKERS_SUBSTRING — scripts with no whitespace word delimiters
#     (Japanese), where \b cannot work because adjacent kana are all word
#     characters. Substring matching is the only option; these strings are
#     distinctive enough that the false-positive risk is acceptable.
#
# Matching is casefold()-based, not .upper(). .upper() is a no-op for
# Tamil/Sinhala/Japanese/Arabic (they are caseless), so it only ever
# normalized the Latin entries; casefold() is the correct Unicode-aware
# operation and handles e.g. "ÉCHANTILLON"/"échantillon" uniformly.
#
# This list is a pragmatic net, not a guarantee — it cannot cover every
# language. The structural `_source.method == "synthetic"` check below is
# the reliable signal; these markers are the best-effort fallback for
# vendor sample packs we did not generate ourselves.
#
# Detection always runs, but dropping is opt-in. A false positive here would
# otherwise remove a page before it reaches the patient's record, with only a
# server log to explain the loss. Deployments intentionally importing vendor
# sample packs can set SKIP_DEMO_DOCUMENTS=true; ordinary patient uploads keep
# placeholder-looking pages and still pass the normal medical-content filter.
SKIP_DEMO_DOCUMENTS = os.getenv("SKIP_DEMO_DOCUMENTS", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

_DEMO_MARKERS_WORD = frozenset(
    {
        "demo",
        "sample",
        "dummy",
        "placeholder",
        "specimen",  # English
        "test patient",
        "demo patient",
        "sample patient",  # English phrases
        "மாதிரி",
        "டெமோ",  # Tamil (sample / demo)
        "නියැදිය",
        "ආදර්ශ",  # Sinhala (sample / model-example)
        "डेमो",
        "नमूना",
        "उदाहरण",  # Hindi (demo / sample / example)
        "muestra",
        "ejemplo",
        "prueba",  # Spanish
        "exemple",
        "échantillon",  # French
        "تجريبي",
        "عينة",
        "نموذج",  # Arabic (trial / sample / model)
    }
)

_DEMO_MARKERS_SUBSTRING = frozenset(
    {
        "デモ",
        "サンプル",  # Japanese (demo / sample)
    }
)

# Built once at import: alternation of word-boundary-anchored markers.
# re.UNICODE \b is script-aware, so it works for Tamil/Sinhala/Hindi/Arabic
# (all of which use spaces) as well as Latin.
_DEMO_MARKER_RE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(m) for m in sorted(_DEMO_MARKERS_WORD)) + r")(?!\w)",
    re.UNICODE,
)


def _has_demo_marker(value: Any) -> bool:
    """True if `value` contains a placeholder marker in any supported
    script. Caseless via casefold(); word-anchored for space-delimited
    scripts, substring for CJK."""
    if not value or not isinstance(value, str):
        return False
    folded = value.casefold()
    if _DEMO_MARKER_RE.search(folded):
        return True
    return any(marker in folded for marker in _DEMO_MARKERS_SUBSTRING)


def _is_demo_document(d: Dict[str, Any]) -> bool:
    """Detect placeholder/template documents (e.g. sample datasets that
    include a 'DEMO PATIENT' / 'DEMO MEDICINE' mock page) so they don't get
    silently treated as real patient data.

    Checks, in order of reliability:
      1. `_source.method == "synthetic"` — documents produced by
         generate_lab_test_data.py. Structural and exact, no guessing.
      2. Placeholder markers in patient_name / medication names, across
         every script in _DEMO_MARKERS_* (patient and medication names are
         never translated during extraction, so English-only would miss
         non-English template pages)."""
    source = d.get("_source")
    if isinstance(source, dict) and str(source.get("method") or "").strip().lower() == "synthetic":
        return True

    if _has_demo_marker(d.get("patient_name")):
        return True

    for med in d.get("medications", []) or []:
        if not isinstance(med, dict):
            continue
        if _has_demo_marker(med.get("name")):
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
    raw_results: List[Dict[str, Any]], drop_demo_documents: bool = SKIP_DEMO_DOCUMENTS
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Splits a flat list of extracted documents into groups keyed by patient
    name. This prevents unrelated prescriptions (e.g. a folder that
    accidentally contains sample docs for different people) from being
    merged into one timeline and cross-checked against each other.

    Returns: { "amit sharma": [doc, doc, ...], "mary smith": [...], ... }
    Also prints a warning if more than one distinct real patient is found,
    or if demo/placeholder documents were dropped. A demo-marked document
    that nevertheless contains structured medical content is KEPT: the
    marker is a hint about a printed name, not a substitute for the content.
    """
    docs = _flatten_documents(raw_results)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    dropped = []

    for d in docs:
        if drop_demo_documents:
            source = d.get("_source") if isinstance(d.get("_source"), dict) else {}
            # A `method == "synthetic"` marker is structural, not a name hint:
            # the document was generated by generate_lab_test_data.py, so it is
            # dropped regardless of what it contains.
            if str(source.get("method") or "").strip().lower() == "synthetic":
                dropped.append(source.get("file", "unknown_file"))
                continue
            # A placeholder marker in a NAME is a hint about what is printed,
            # not what the page contains: the extracted medications / lab
            # results / allergies are evidence about its CONTENT, and content
            # wins. A real prescription belonging to someone whose name
            # happens to contain a marker, or a lab report whose patient field
            # caught "Sample Collected", is a medical document whatever the
            # marker says. Only drop a demo-marked document that also has no
            # structured medical content in it.
            if _is_demo_document(d):
                from document_filter import has_medical_content

                if not has_medical_content(d):
                    dropped.append(source.get("file", "unknown_file"))
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


def _parse_timeline_date(date_str: Optional[str], dayfirst: bool = True):
    """Best-effort parse of wildly varying date formats in extracted docs.
    Returns datetime or None for unparseable/missing dates. Used only for
    sorting, so failure falls back to far-future.

    Ambiguous slash dates follow the record's inferred day/month convention
    (date_convention.py) — the same reading used by lab_trends,
    change_detection, record_integrity and risk_timeline, so every feature
    orders the same documents the same way."""
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        from date_convention import parse_mixed_datetime

        parsed = parse_mixed_datetime(date_str, dayfirst=dayfirst)
        if parsed is None:
            return None
        # Extracted event dates may mix date-only values with ISO timestamps.
        # Normalize aware values to UTC-naive so Python can sort both safely.
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except Exception:
        return None


def build_patient_timeline(raw_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merge extracted documents (output of process_document, one per file) into
    a single chronological patient timeline: one entry per visit/document,
    sorted by date, plus flattened evidence-linked rollups of medications,
    labs, diagnoses, symptoms, procedures, vital signs, and imaging results.

    NOTE: assumes all documents passed in already belong to ONE patient.
    Use group_documents_by_patient() first if a batch might mix patients
    or contain demo/placeholder documents.
    """
    docs = _flatten_documents(raw_results)

    # Tag documents that record the SAME physical prescription (a scan and a
    # photo of one page, the same file re-sent under another name). Nothing is
    # dropped — the tag exists so duplicate detection below counts
    # prescriptions rather than files. Without it, one prescription uploaded
    # twice makes every drug on it look prescribed twice. See
    # document_dedup.py.
    from document_dedup import annotate_prescription_groups

    annotate_prescription_groups(docs)

    # One day/month convention for the whole record, inferred from all its
    # document dates: a "26/02/2026" anywhere settles every "03/11/2025".
    # Shared with lab trends / change detection / risk windows so no two
    # features read the same ambiguous date as different days.
    from date_convention import infer_dayfirst

    dayfirst = infer_dayfirst([d.get("date") for d in docs])

    # Sort by parsed date; undated/unparseable docs go to the end.
    # Previously sorted by raw string which broke for formats like
    # "05 Jan 2026" vs "20 Apr 2026" (lexicographic != chronological).
    def sort_key(d):
        dt = _parse_timeline_date(d.get("date"), dayfirst=dayfirst)
        # Use max datetime for missing, and original string as tiebreaker for stability
        return (dt is None, dt or d.get("date") or "9999-99-99")

    docs_sorted = sorted(docs, key=sort_key)

    all_medications = []
    all_lab_results = []
    clinical_rollups: Dict[str, List[Dict[str, Any]]] = {
        timeline_key: [] for timeline_key in CLINICAL_TIMELINE_KEYS.values()
    }
    all_allergies = set()
    allergy_evidence = []
    trusted_visits = []

    for d in docs_sorted:
        visit_date = d.get("date")
        source = d.get("_source", {}) if isinstance(d.get("_source"), dict) else {}
        source_file = source.get("file")
        source_page = source.get("page")
        doc_id = str(d.get("_document_id") or "")
        if bool((d.get("_trust") or {}).get("quarantined")):
            continue

        safe_visit = copy.deepcopy(d)
        fact_collections = ("medications", "lab_results", *CLINICAL_EVENT_COLLECTIONS)
        has_quarantined_fact = any(
            isinstance(fact, dict) and (fact.get("_trust") or {}).get("quarantined")
            for collection in fact_collections
            for fact in safe_visit.get(collection, []) or []
        )
        for collection in fact_collections:
            safe_visit[collection] = [
                fact
                for fact in safe_visit.get(collection, [])
                if isinstance(fact, dict) and not (fact.get("_trust") or {}).get("quarantined")
            ]
        if has_quarantined_fact:
            # Notes and legacy diagnosis strings are unstructured mirrors of
            # extracted facts. If a competing fact is quarantined, retaining
            # the same value here would leak it back into RAG and analytics.
            safe_visit["clinical_notes"] = None
            safe_visit["diagnoses_or_conditions"] = []
        trusted_visits.append(safe_visit)

        for index, med in enumerate(d.get("medications", [])):
            if not isinstance(med, dict) or (med.get("_trust") or {}).get("quarantined"):
                continue
            medication_evidence = first_evidence(med) or {}
            all_medications.append(
                {
                    **med,
                    "date": visit_date,
                    "source_file": source_file,
                    "source_page": medication_evidence.get("page") or source_page,
                    "source_method": source.get("method"),
                    "document_id": doc_id,
                    "fact_path": f"/medications/{index}",
                    "document_type": d.get("document_type"),
                    "prescription_group": d.get("prescription_group"),
                }
            )

        for index, lab in enumerate(d.get("lab_results", [])):
            if not isinstance(lab, dict) or (lab.get("_trust") or {}).get("quarantined"):
                continue
            lab_evidence = first_evidence(lab) or {}
            all_lab_results.append(
                {
                    **lab,
                    "date": visit_date,
                    "source_file": source_file,
                    "source_page": lab_evidence.get("page") or source_page,
                    "source_method": source.get("method"),
                    "document_id": doc_id,
                    "fact_path": f"/lab_results/{index}",
                    "document_type": d.get("document_type"),
                }
            )

        # Legacy generic diagnoses remain available as low-detail events.
        for index, diagnosis in enumerate(
            (d.get("diagnoses_or_conditions", []) or []) if not has_quarantined_fact else []
        ):
            if isinstance(diagnosis, str) and diagnosis.strip():
                clinical_rollups["diagnoses_timeline"].append(
                    {
                        "name": diagnosis.strip(),
                        # The enclosing document date is provenance, not an
                        # explicitly documented diagnosis/onset date.
                        "date": None,
                        "document_date": visit_date,
                        "source_file": source_file,
                        "source_page": source_page,
                        "source_method": source.get("method"),
                        "document_id": doc_id,
                        "fact_path": f"/diagnoses_or_conditions/{index}",
                        "document_type": d.get("document_type"),
                    }
                )

        for collection in CLINICAL_EVENT_COLLECTIONS:
            timeline_key = CLINICAL_TIMELINE_KEYS[collection]
            event_date_field = CLINICAL_EVENT_DATE_FIELDS[collection]
            for index, fact in enumerate(d.get(collection, [])):
                if not isinstance(fact, dict) or (fact.get("_trust") or {}).get("quarantined"):
                    continue
                fact_evidence = first_evidence(fact) or {}
                clinical_rollups[timeline_key].append(
                    {
                        **fact,
                        # Never relabel the enclosing document date as the event
                        # date. Undated facts remain undated and retain the source
                        # date separately for provenance.
                        "date": fact.get(event_date_field) or None,
                        "document_date": visit_date,
                        "source_file": source_file,
                        "source_page": fact_evidence.get("page") or source.get("page"),
                        "source_method": source.get("method"),
                        "document_id": doc_id,
                        "fact_path": f"/{collection}/{index}",
                        "document_type": d.get("document_type"),
                    }
                )

        allergy_regions = (d.get("field_evidence") or {}).get("allergies_noted") or []
        for allergy in d.get("allergies_noted", []) or []:
            all_allergies.add(allergy)
            allergy_evidence.append(
                {
                    "allergy": allergy,
                    "document_id": doc_id,
                    "date": visit_date,
                    "source_file": source_file,
                    "source_method": source.get("method"),
                    "document_type": d.get("document_type"),
                    "confidence": d.get("overall_confidence"),
                    "evidence": copy.deepcopy(allergy_regions),
                    "_trust": copy.deepcopy(d.get("_trust")),
                }
            )

    # Event-specific dates (for example a historical procedure date printed
    # in a recent discharge summary) can differ from the enclosing document
    # date, so sort every clinical rollup independently.
    for values in clinical_rollups.values():
        values.sort(
            key=lambda item: (
                _parse_timeline_date(item.get("date"), dayfirst=dayfirst) is None,
                _parse_timeline_date(item.get("date"), dayfirst=dayfirst)
                or item.get("date")
                or "9999-99-99",
            )
        )

    from document_dedup import find_duplicate_document_groups

    return {
        "visits": trusted_visits,
        "documents": docs_sorted,
        "medications_timeline": all_medications,
        "lab_results_timeline": all_lab_results,
        **clinical_rollups,
        "known_allergies": sorted(all_allergies),
        "allergy_evidence": allergy_evidence,
        # Documents that record the SAME physical prescription (re-uploads,
        # scan + photo of one page). Nothing was removed from the timeline —
        # this is the review list explaining which files collapse into one
        # prescription for duplicate-detection purposes. Empty in the common
        # case. See document_dedup.py.
        "duplicate_document_groups": find_duplicate_document_groups(docs_sorted),
    }


# ---------------------------------------------------------------------------
# 6. Medication safety — dedicated service (not extraction)
# ---------------------------------------------------------------------------
# Interaction / duplicate / dosage / allergy analysis lives in
# medication_safety.py so the extractor only produces a timeline. Existing
# `from medical_extractor import cross_check_prescriptions` imports keep
# working via these re-exports.

from medication_safety import (  # noqa: E402
    CROSS_CHECK_JSON_SCHEMA,  # noqa: F401  (public re-export)
    CROSS_CHECK_PROMPT,  # noqa: F401  (public re-export)
    CROSS_CHECK_RESPONSE_FORMAT,  # noqa: F401  (public re-export)
    analyze_medication_safety,  # noqa: F401  (public re-export)
    cross_check_prescriptions,
    detect_exact_duplicate_medications,  # noqa: F401  (public re-export)
)

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
        print('  Whole patient folder:   python medical_extractor.py "C:\\path\\to\\Patient x"')
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

    # Step 2: split by patient name. Demo/placeholder detection always runs,
    # while dropping is controlled by SKIP_DEMO_DOCUMENTS (off by default).
    # This prevents a marker false-positive from silently losing patient data;
    # sample-pack imports can explicitly opt into filtering.
    print("\nGrouping documents by patient ...")
    patient_groups = group_documents_by_patient(all_results)

    if not patient_groups:
        print("No documents remained after filtering. Exiting.")
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
        print(
            f"  Dosage conflict flags: {len(cross_check.get('conflicting_dosage_instructions', []))}"  # noqa: E501
        )

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

        from conversation import ask as conversation_ask
        from conversation import get_or_create_session

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
