"""Offline tests for _completion_resilient() retry ladder behavior.

These mock the OpenAI/Groq client so no network is involved. They verify:
  1. <think>-only output on the json_object rung advances to plain text
     (and succeeds there) instead of burning doomed retries.
  2. A 400 json_validate_failed advances to a looser rung immediately.
  3. 429s are paced via Retry-After and eventually succeed.
  4. A non-retryable 400 propagates (with the error detail logged).
  5. max_retries=0 is set on the client (SDK retries disabled).
"""
import os
import sys
import time
import json
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ.setdefault("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

import medical_extractor as me
from openai import APIStatusError

VALID_JSON = json.dumps({
    "document_type": "prescription",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "John Doe",
    "medications": [],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "illegible_or_low_confidence_fields": [],
    "overall_confidence": 0.92,
})


def _resp(content: str):
    return mock.Mock(choices=[mock.Mock(message=mock.Mock(content=content))])


def _api_error(status, body, code=None, headers=None):
    resp = mock.Mock()
    resp.status_code = status
    resp.headers = headers or {}
    exc = APIStatusError("boom", response=resp, body=body)
    exc.code = code
    return exc


def test_client_disables_sdk_retries():
    assert me.client.max_retries == 0


def test_think_only_advances_rung():
    """json_object returns a <think>-only dump (non-JSON): must NOT retry
    json_object; must advance to plain text and succeed there.

    Suppression probing is disabled here so this test covers the pure
    output-format ladder; probing behavior has its own tests below."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("response_format"))
        if kwargs.get("response_format") == {"type": "json_object"}:
            return _resp("<think> The user wants me to extract data from a medical lab report...</think>")
        return _resp("<think>ok</think>\n" + VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.dict(os.environ, {"GROQ_DISABLE_REASONING": "false"}), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        raw = me._completion_resilient(
            model="qwen/qwen3.6-27b",
            system_prompt="sys",
            user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )
    # Exactly 2 HTTP calls: 1 json_object + 1 plain text (no doomed retries)
    assert len(calls) == 2, calls
    assert calls[0] == {"type": "json_object"}
    assert calls[1] is None  # plain text
    assert VALID_JSON in raw


def test_json_validate_failed_400_advances_rung():
    """Groq 400 json_validate_failed (server discarded the generation):
    must advance to plain text instead of re-trying the same format."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("response_format"))
        if kwargs.get("response_format") == {"type": "json_object"}:
            raise _api_error(
                400,
                {"error": {"code": "json_validate_failed",
                           "message": "Failed to validate JSON",
                           "failed_generation": "<think> The user wants..."}},
                code="json_validate_failed",
            )
        return _resp(VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.dict(os.environ, {"GROQ_DISABLE_REASONING": "false"}), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        raw = me._completion_resilient(
            model="qwen/qwen3.6-27b",
            system_prompt="sys",
            user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )
    assert len(calls) == 2, calls
    assert VALID_JSON in raw


def test_suppression_probe_sent_and_cached():
    """A reasoning model gets the Qwen3 enable_thinking=false probe attached
    (via extra_body); when the provider honors it, the FIRST call succeeds
    and the probe is cached as the model's default for later calls."""
    me._SUPPRESS_STATE.clear()
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("extra_body"))
        # Provider honors enable_thinking=false: no <think>, clean JSON.
        return _resp(VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        for _ in range(2):  # second call must reuse the cached probe
            raw = me._completion_resilient(
                model="qwen/qwen3.6-27b",
                system_prompt="sys",
                user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
                strict_format=me.EXTRACTION_RESPONSE_FORMAT,
            )
            assert VALID_JSON in raw
    assert calls == [
        {"chat_template_kwargs": {"enable_thinking": False}},
        {"chat_template_kwargs": {"enable_thinking": False}},
    ], calls
    assert me._SUPPRESS_STATE["qwen/qwen3.6-27b"]["good"] == 0


def test_unsupported_probe_param_crossed_off():
    """If the provider 400-rejects the first probe as an unknown parameter,
    the runner crosses it off (forever) and succeeds with the next probe —
    the probe error must NOT surface as a request failure."""
    me._SUPPRESS_STATE.clear()
    calls = []

    def fake_create(**kwargs):
        extra = kwargs.get("extra_body")
        calls.append(extra)
        if extra and "chat_template_kwargs" in extra:
            raise _api_error(400, {"error": {"message": 'Unknown field "chat_template_kwargs"'}})
        return _resp(VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        raw = me._completion_resilient(
            model="qwen/qwen3.6-27b",
            system_prompt="sys",
            user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )
    assert VALID_JSON in raw
    assert calls == [
        {"chat_template_kwargs": {"enable_thinking": False}},  # 400 unknown param
        {"reasoning_format": "hidden"},                        # accepted, clean JSON
    ], calls
    state = me._SUPPRESS_STATE["qwen/qwen3.6-27b"]
    assert state["dead"] == {0} and state["good"] == 1, state


def test_suppression_ignored_falls_through_and_remembers():
    """If the provider silently IGNORES the suppression switches (still
    emits <think>), both probes get crossed off via the reasoning-dump
    detection and the bare plain-text rung still recovers the JSON."""
    me._SUPPRESS_STATE.clear()
    calls = []

    def fake_create(**kwargs):
        extra = kwargs.get("extra_body")
        fmt = kwargs.get("response_format")
        calls.append((fmt, extra))
        if extra:  # probe attached but provider ignores it
            return _resp("<think> full reasoning dump, no JSON </think>")
        if fmt == {"type": "json_object"}:
            raise _api_error(
                400,
                {"error": {"code": "json_validate_failed", "message": "Failed to validate JSON"}},
                code="json_validate_failed",
            )
        return _resp(VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        raw = me._completion_resilient(
            model="qwen/qwen3.6-27b",
            system_prompt="sys",
            user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )
    assert VALID_JSON in raw
    # json_object×2 probes (both ignored: <think> leak), json_object bare (400),
    # then plain-text bare succeeds (probes skipped on later formats — crossed off).
    assert calls == [
        ({"type": "json_object"}, {"chat_template_kwargs": {"enable_thinking": False}}),
        ({"type": "json_object"}, {"reasoning_format": "hidden"}),
        ({"type": "json_object"}, None),
        (None, None),
    ], calls
    state = me._SUPPRESS_STATE["qwen/qwen3.6-27b"]
    assert state["dead"] == {0, 1}, state


def test_no_fabricated_stub_fallback_on_total_failure():
    """When every rung fails, _completion_resilient raises RuntimeError —
    it must NOT call the FALLBACK_MODEL to fabricate a minimal empty JSON
    (which the medical filter then rejected with a misleading 422)."""
    me._SUPPRESS_STATE.clear()
    called_models = []

    def fake_create(**kwargs):
        called_models.append(kwargs.get("model"))
        raise _api_error(
            400,
            {"error": {"code": "json_validate_failed", "message": "Failed to validate JSON", "failed_generation": ""}},
            code="json_validate_failed",
        )

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        try:
            me._completion_resilient(
                model="qwen/qwen3.6-27b",
                system_prompt="sys",
                user_content=[{"type": "text", "text": "t"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}}],
                strict_format=me.EXTRACTION_RESPONSE_FORMAT,
            )
        except RuntimeError as e:
            msg = str(e)
            assert "repeatedly failed" in msg
            assert "HTTP 400" in msg  # root-cause hint survives to the API layer
        else:
            raise AssertionError("expected RuntimeError on total ladder failure")
    # Only the vision model was ever called — never the text fallback stub.
    assert set(called_models) == {"qwen/qwen3.6-27b"}, set(called_models)
    assert me.FALLBACK_MODEL not in called_models


def test_429_uses_retry_after_then_succeeds():
    """429s sleep Retry-After and eventually succeed; rate-limit count is
    tracked and no extra format rungs are burned."""
    calls = []
    sleeps = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("response_format"))
        if len(calls) <= 2:
            raise _api_error(429, {"error": {"message": "rate limit"}}, headers={"retry-after": "3"})
        return _resp(VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: sleeps.append(s)
        raw = me._completion_resilient(
            model="openai/gpt-oss-120b",
            system_prompt="sys",
            user_content="text-only",
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )
    assert len(calls) == 3, calls
    assert sleeps == [3.0, 3.0], sleeps
    assert VALID_JSON in raw


def test_non_retryable_400_raises():
    """A 400 that is NOT json_validate_failed is permanent — must raise."""
    def fake_create(**kwargs):
        raise _api_error(400, {"error": {"message": "unsupported parameter 'foo'"}})

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        try:
            me._completion_resilient(
                model="openai/gpt-oss-120b",
                system_prompt="sys",
                user_content="text",
                strict_format=me.EXTRACTION_RESPONSE_FORMAT,
            )
        except me.APIError as e:
            assert e.status_code == 400
        else:
            raise AssertionError("expected APIError to propagate")


def test_rate_limit_cap_fails_fast():
    """After GROQ_MAX_RATE_LIMIT_RETRIES consecutive 429s, raise a clear
    RuntimeError instead of retrying forever."""
    def fake_create(**kwargs):
        raise _api_error(429, {"error": {"message": "rate limit"}}, headers={"retry-after": "1"})

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.object(me, "time") as fake_time, \
         mock.patch.dict(os.environ, {"GROQ_MAX_RATE_LIMIT_RETRIES": "2"}):
        fake_time.sleep = lambda s: None
        try:
            me._completion_resilient(
                model="openai/gpt-oss-120b",
                system_prompt="sys",
                user_content="text",
                strict_format=me.EXTRACTION_RESPONSE_FORMAT,
            )
        except RuntimeError as e:
            assert "429" in str(e)
        else:
            raise AssertionError("expected RuntimeError after rate-limit cap")


def test_parse_think_wrapped_json():
    """_parse_json_object handles <think>...JSON...</think> output."""
    obj = me._parse_json_object("<think> reasoning </think>\n" + VALID_JSON)
    assert obj["document_type"] == "prescription"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
