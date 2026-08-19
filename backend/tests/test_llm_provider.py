"""
Unit tests for backend/llm_provider.py — provider resolution logic.

Covers _PROVIDER_DEFAULTS, _resolve_provider_config, _resolve_api_key,
_configured_secret, and the module-level derived constants (LLM_PROVIDER,
_PROVIDER_CFG, GROQ_API_KEY / LLM_API_KEY aliases).
"""

import importlib
import sys

import pytest


# llm_provider reads the environment at import time and raises RuntimeError
# when no usable key is configured, so every test that imports the module
# must first install a valid-looking key.
@pytest.fixture(autouse=True)
def _provider_env(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test-provider-env-key")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)
    yield


@pytest.fixture()
def provider_module(_provider_env):
    """Freshly (re)loaded llm_provider module honoring the patched env."""
    _drop_module()
    module = importlib.import_module("llm_provider")
    yield module
    _drop_module()


def _drop_module():
    for name in list(sys.modules):
        if name == "llm_provider" or name.startswith("llm_provider."):
            del sys.modules[name]


def test_provider_defaults_cover_builtin_providers(provider_module):
    defaults = provider_module._PROVIDER_DEFAULTS
    assert "groq" in defaults
    assert "gemini" in defaults
    for cfg in defaults.values():
        assert "api_key_env" in cfg
        assert "base_url_default" in cfg
        assert "model_default" in cfg
        assert "vision_default" in cfg
    assert defaults["groq"]["api_key_env"] == "GROQ_API_KEY"
    assert defaults["gemini"]["api_key_env"] == "GEMINI_API_KEY"


def test_llm_provider_default_is_groq(provider_module):
    assert provider_module.LLM_PROVIDER == "groq"


def test_llm_provider_lowercased_and_stripped(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "  Gemini ")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-gemini-key")
    module = _reload()
    assert module.LLM_PROVIDER == "gemini"


def test_resolve_provider_config_known_provider(provider_module):
    cfg = provider_module._resolve_provider_config("gemini")
    assert cfg["api_key_env"] == "GEMINI_API_KEY"
    assert cfg["api_key_alts"] == ("GOOGLE_API_KEY",)
    assert cfg["base_url_default"].startswith("https://generativelanguage")
    # Returns a copy — mutating it must not touch the defaults table.
    cfg["model_default"] = "changed"
    assert provider_module._PROVIDER_DEFAULTS["gemini"]["model_default"] == "gemini-3.6-flash"


def test_resolve_provider_config_unknown_provider_is_generic(provider_module, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "https://custom.example/v1")
    monkeypatch.setenv("LLM_MODEL", "custom-model")
    cfg = provider_module._resolve_provider_config("cerebras")
    assert cfg["api_key_env"] == "LLM_API_KEY"
    assert cfg["base_url_default"] == "https://custom.example/v1"
    assert cfg["model_default"] == "custom-model"


def test_resolve_provider_config_unknown_provider_defaults(provider_module):
    cfg = provider_module._resolve_provider_config("unknown-provider")
    assert cfg["api_key_env"] == "LLM_API_KEY"
    assert cfg["base_url_default"] == "https://api.openai.com/v1"
    assert cfg["model_default"] == "gpt-4o-mini"


def test_resolve_api_key_returns_primary_env(provider_module):
    cfg = provider_module._resolve_provider_config("groq")
    assert provider_module._resolve_api_key(cfg) == "gsk_test-provider-env-key"


def test_resolve_api_key_uses_alt_env(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "AIza-alt-key")
    module = _reload()
    cfg = module._resolve_provider_config("gemini")
    assert module._resolve_api_key(cfg) == "AIza-alt-key"


def test_resolve_api_key_rejects_placeholders(provider_module, monkeypatch):
    for placeholder in (
        "your-groq-api-key",
        "your-gemini-api-key",
        "your-api-key",
        "your-openai-api-key",
        "your-custom-secret",
    ):
        monkeypatch.setenv("GROQ_API_KEY", placeholder)
        cfg = provider_module._resolve_provider_config("groq")
        assert provider_module._resolve_api_key(cfg) is None, placeholder


def test_resolve_api_key_blank_values_are_missing(provider_module, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "   ")
    cfg = provider_module._resolve_provider_config("groq")
    assert provider_module._resolve_api_key(cfg) is None


def test_resolve_api_key_generic_fallback_for_known_provider(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("LLM_API_KEY", "llm-fallback-key")
    module = _reload()
    cfg = module._resolve_provider_config("groq")
    assert module._resolve_api_key(cfg) == "llm-fallback-key"


def test_groq_api_key_legacy_alias(provider_module):
    assert provider_module.GROQ_API_KEY == "gsk_test-provider-env-key"
    assert provider_module.LLM_API_KEY == "gsk_test-provider-env-key"


def test_missing_key_raises_at_import(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    _drop_module()
    with pytest.raises(RuntimeError, match="GROQ_API_KEY is not set"):
        importlib.import_module("llm_provider")
    _drop_module()


def test_configured_secret(provider_module, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-real-key")
    monkeypatch.setenv("OPENROUTER_KEY", "your-placeholder")
    assert provider_module._configured_secret("OPENROUTER_API_KEY") == "sk-or-real-key"
    assert provider_module._configured_secret("OPENROUTER_KEY") == ""
    assert provider_module._configured_secret("UNSET_VAR") == ""


def _reload():
    _drop_module()
    module = importlib.import_module("llm_provider")
    return module
