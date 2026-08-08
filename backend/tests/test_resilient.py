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
    json_object; must advance to plain text and succeed there."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("response_format"))
        if kwargs.get("response_format") == {"type": "json_object"}:
            return _resp("<think> The user wants me to extract data from a medical lab report...</think>")
        return _resp("<think>ok</think>\n" + VALID_JSON)

    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
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
