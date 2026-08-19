"""
LLM Provider Resolution
========================
Centralizes how MediMind selects and configures its OpenAI-compatible LLM
provider from environment variables.

Provider is selected via LLM_PROVIDER (default: groq). All providers use
the standard OpenAI SDK — only base URL, API key, and model names differ.

  groq (default):  GROQ_API_KEY (gsk_...), https://api.groq.com/openai/v1
                   text openai/gpt-oss-120b, vision qwen/qwen3.6-27b — free, no card
  gemini:          GEMINI_API_KEY (or GOOGLE_API_KEY),
                   https://generativelanguage.googleapis.com/v1beta/openai/
                   text/vision gemini-3.6-flash — current stable multimodal model

Generic OpenAI-compatible providers (cerebras, openrouter, openai, custom)
work via LLM_API_KEY + LLM_BASE_URL + LLM_MODEL env vars.

Env (pick one provider):
    export GROQ_API_KEY="gsk_..."        (https://console.groq.com/keys)        # LLM_PROVIDER=groq
    export GEMINI_API_KEY="AIza..."      (https://aistudio.google.com/app/apikey) # LLM_PROVIDER=gemini
"""  # noqa: E501

import os
from typing import Any, Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv(override=True)

# ---------------------------------------------------------------------------
# LLM provider layer — OpenAI-compatible via LLM_PROVIDER
# ---------------------------------------------------------------------------
# LLM_PROVIDER selects the backend (default "groq" for backward compat).
# All providers use the OpenAI SDK; only base_url / api_key / model names
# differ. Provider quotas vary by project and model, so the upload worker pool
# (api.py) deliberately keeps LLM concurrency bounded instead of assuming a
# fixed free-tier allowance.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "groq").strip().lower() or "groq"

_PROVIDER_DEFAULTS = {
    "groq": {
        "api_key_env": "GROQ_API_KEY",
        "api_key_alts": (),
        "base_url_default": "https://api.groq.com/openai/v1",
        "base_url_env": "GROQ_BASE_URL",
        "model_default": "openai/gpt-oss-120b",
        "model_env": "GROQ_MODEL",
        "vision_default": "qwen/qwen3.6-27b",
        "vision_env": "GROQ_VISION_MODEL",
        "fallback_default": "openai/gpt-oss-20b",
        "fallback_env": "GROQ_FALLBACK_MODEL",
        "key_url": "https://console.groq.com/keys",
        "docs_url": "https://console.groq.com/docs/deprecations",
    },
    "gemini": {
        "api_key_env": "GEMINI_API_KEY",
        "api_key_alts": ("GOOGLE_API_KEY",),
        "base_url_default": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "base_url_env": "GEMINI_BASE_URL",
        # Gemini 2.0 Flash was shut down on 2026-06-01. Google may report
        # requests to that retired model as quota limit=0 / HTTP 429 rather
        # than model_not_found, so keeping the retired ID here causes an
        # endless-looking rate-limit failure. 3.6 Flash is Google's stable
        # replacement and supports image input + structured output.
        "model_default": "gemini-3.6-flash",
        "model_env": "GEMINI_MODEL",
        "vision_default": "gemini-3.6-flash",
        "vision_env": "GEMINI_VISION_MODEL",
        "fallback_default": "gemini-3.5-flash-lite",
        "fallback_env": "GEMINI_FALLBACK_MODEL",
        "key_url": "https://aistudio.google.com/app/apikey",
        "docs_url": "https://ai.google.dev/gemini-api/docs/deprecations",
    },
}


def _resolve_provider_config(provider: str) -> Dict[str, Any]:
    cfg = _PROVIDER_DEFAULTS.get(provider)
    if cfg is not None:
        return dict(cfg)
    # Generic OpenAI-compatible (cerebras, openrouter, openai, custom) via LLM_* env vars
    return {
        "api_key_env": "LLM_API_KEY",
        "api_key_alts": ("OPENAI_API_KEY",),
        "base_url_default": os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1"),
        "base_url_env": "LLM_BASE_URL",
        "model_default": os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        "model_env": "LLM_MODEL",
        "vision_default": os.environ.get(
            "LLM_VISION_MODEL", os.environ.get("LLM_MODEL", "gpt-4o-mini")
        ),
        "vision_env": "LLM_VISION_MODEL",
        "fallback_default": os.environ.get("LLM_FALLBACK_MODEL", ""),
        "fallback_env": "LLM_FALLBACK_MODEL",
        "key_url": "https://platform.openai.com/api-keys",
        "docs_url": "",
    }


_PROVIDER_CFG = _resolve_provider_config(LLM_PROVIDER)


def _resolve_api_key(cfg: Dict[str, Any]) -> Optional[str]:
    for env in (cfg["api_key_env"],) + tuple(cfg.get("api_key_alts", ())):
        val = os.environ.get(env)
        if not val or not val.strip():
            continue
        stripped = val.strip()
        if stripped in (
            "your-groq-api-key",
            "your-gemini-api-key",
            "your-api-key",
            "your-openai-api-key",
        ) or stripped.startswith("your-"):
            continue
        return stripped
    # Fallback to generic LLM_API_KEY for known providers too
    if cfg["api_key_env"] != "LLM_API_KEY":
        val = os.environ.get("LLM_API_KEY")
        if val and val.strip() and not val.strip().startswith("your-"):
            return val.strip()
    return None


_PROVIDER_API_KEY = _resolve_api_key(_PROVIDER_CFG)
if not _PROVIDER_API_KEY:
    _env = _PROVIDER_CFG["api_key_env"]
    _alts = ", ".join(_PROVIDER_CFG.get("api_key_alts", ()))
    _alts_msg = f" or {_alts}" if _alts else ""
    _url = _PROVIDER_CFG["key_url"]
    raise RuntimeError(
        f"{_env} is not set for LLM_PROVIDER='{LLM_PROVIDER}' (still placeholder or missing) — "
        f"copy .env.example to .env and add your API key{_alts_msg} (create a free one at {_url}). "
        f"Or set LLM_PROVIDER=groq|gemini and the matching key env var. "
        f"For generic providers set LLM_API_KEY + LLM_BASE_URL + LLM_MODEL."
    )

# Keep legacy GROQ_API_KEY name for backward compat (tests / external imports)
_raw_groq = os.environ.get("GROQ_API_KEY", "")
if _raw_groq.strip() in ("", "your-groq-api-key") or _raw_groq.strip().startswith("your-"):
    _raw_groq = ""
GROQ_API_KEY = _raw_groq or (_PROVIDER_API_KEY if LLM_PROVIDER == "groq" else "")
# Also expose provider-resolved key under a generic name
LLM_API_KEY = _PROVIDER_API_KEY

_PROVIDER_BASE_URL = os.environ.get(
    _PROVIDER_CFG["base_url_env"], _PROVIDER_CFG["base_url_default"]
)
# LLM_BASE_URL overrides any provider when explicitly set (custom endpoint)
if os.environ.get("LLM_BASE_URL"):
    _PROVIDER_BASE_URL = os.environ["LLM_BASE_URL"]

client = OpenAI(
    api_key=_PROVIDER_API_KEY,
    base_url=_PROVIDER_BASE_URL,
    # Retries are handled inside _completion_resilient() so one SDK call is
    # exactly one HTTP request. With the SDK's own retry loop enabled (the
    # default max_retries=2), a rate-limited call used to stack Retry-After
    # waits (28s, 37s, 45s ...) on top of our ladder retries, turning a
    # single upload into a multi-minute stall. Now 429s surface immediately
    # and _completion_resilient() paces them deliberately.
    max_retries=0,
)


# Optional failover for a *hard* primary-provider quota outage. It is off by
# default because medical documents are sensitive and enabling it sends the
# same request to OpenRouter, a separate service. Set the explicit opt-in plus
# an OpenRouter key and models to enable it.
def _configured_secret(name: str) -> str:
    value = os.environ.get(name, "").strip()
    return "" if not value or value.startswith("your-") else value
