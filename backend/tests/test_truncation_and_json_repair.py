"""Regression tests for two production bugs seen in deploy logs
(2026-08-17, medimind-hmim.onrender.com):

1. TRUNCATED OUTPUT MISDIAGNOSED AS "non-JSON".
   Files whose extraction JSON was cut off at the provider's max_tokens
   limit (finish_reason='length') logged
   ``returned non-JSON (snippet '{   "document_type": "lab_report", ...')
   — advancing to the next rung`` and then re-sent the SAME vision request
   with the SAME budget — which truncates at the same point again — costing
   25-45s of wasted latency per file. The ladder now detects
   finish_reason=length, raises the completion budget, and retries the same
   rung; the final error (if all escalations fail) names truncation as the
   root cause instead of blaming "reasoning/non-JSON".

2. RAW CONTROL CHARACTERS INSIDE JSON STRINGS.
   _try_repair_json's docstring promised "unescaped control chars" repair
   but never implemented it — a literal newline inside e.g.
   "clinical_notes" makes json.loads (and every repair path) fail even
   though the JSON is otherwise complete.
"""
import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ.setdefault("GROQ_VISION_MODEL", "qwen/qwen3.6-27b")

import medical_extractor as me

VALID_JSON = json.dumps({
    "document_type": "lab_report",
    "date": "2026-06-10",
    "provider_or_doctor": "Dr. Rohan Silva",
    "patient_name": "PERERA, Anjali (Mrs.)",
    "medications": [],
    "lab_results": [{"test": "Hemoglobin", "value": 10.2, "unit": "g/dL"}],
    "overall_confidence": 0.9,
})

VISION_CONTENT = [
    {"type": "text", "text": "t"},
    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,x"}},
]


def _resp(content: str, finish_reason: str = "stop"):
    choice = mock.Mock(message=mock.Mock(content=content))
    choice.finish_reason = finish_reason
    return mock.Mock(choices=[choice])


def _run_ladder(fake_create, env=None):
    me._SUPPRESS_STATE.clear()
    with mock.patch.object(me.client.chat.completions, "create", fake_create), \
         mock.patch.dict(os.environ, env or {"GROQ_DISABLE_REASONING": "false"}), \
         mock.patch.object(me, "time") as fake_time:
        fake_time.sleep = lambda s: None
        return me._completion_resilient(
            model="qwen/qwen3.6-27b",
            system_prompt="sys",
            user_content=VISION_CONTENT,
            strict_format=me.EXTRACTION_RESPONSE_FORMAT,
        )


def test_truncated_output_escalates_budget_on_same_rung():
    """finish_reason='length' with a cut-off JSON prefix must NOT be treated
    as a non-JSON output format problem. The budget is raised and the SAME
    json_object rung retried — no wasted 'advance to the next rung' call
    with an unchanged token budget."""
    calls = []

    def fake_create(**kwargs):
        calls.append((kwargs.get("response_format"), kwargs.get("max_tokens")))
        if kwargs.get("max_tokens", 0) < 4096:
            # 4096-token-budget generation cut mid-JSON (like the deploy logs'
            # '{ "document_type": "lab_report", ... "lab_res')
            return _resp(VALID_JSON[: len(VALID_JSON) // 2], finish_reason="length")
        return _resp(VALID_JSON, finish_reason="stop")

    raw = _run_ladder(fake_create)
    assert VALID_JSON in raw
    # Both calls stayed on the json_object rung; the budget escalated.
    assert calls == [
        ({"type": "json_object"}, 2048),  # groq vision default budget
        ({"type": "json_object"}, 4096),  # escalated after truncation
    ], calls


def test_complete_json_returned_even_with_length_finish_reason():
    """A generation that reports finish_reason='length' but still contains
    complete parseable JSON (finished exactly at the boundary) is accepted
    without wasting an escalation."""
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs.get("max_tokens"))
        return _resp(VALID_JSON, finish_reason="length")

    raw = _run_ladder(fake_create)
    assert VALID_JSON in raw
    assert calls == [2048], calls


def test_persistent_truncation_surfaces_token_limit_root_cause():
    """When truncation persists past every escalation, the final
    RuntimeError must name the completion-token limit — not the old
    misleading 'model kept emitting reasoning/non-JSON' hint."""
    calls = []

    def fake_create(**kwargs):
        calls.append((kwargs.get("response_format"), kwargs.get("max_tokens")))
        return _resp(VALID_JSON[: len(VALID_JSON) // 2], finish_reason="length")

    try:
        _run_ladder(fake_create)
    except RuntimeError as e:
        msg = str(e)
        assert "completion-token limit" in msg, msg
        assert "reasoning/non-JSON" not in msg, msg
    else:
        raise AssertionError("expected RuntimeError when truncation never resolves")
    # rung0: two escalated attempts; rung1: one attempt at the ceiling —
    # no doomed retries at an unchanged budget.
    assert calls == [
        ({"type": "json_object"}, 2048),
        ({"type": "json_object"}, 4096),
        (None, 8192),
    ], calls


def test_control_chars_inside_strings_repaired():
    raw = (
        '{"document_type": "consultation_note", '
        '"clinical_notes": "Line one\nLine two\tTabbed", '
        '"medications": []}'
    )
    # json.loads alone rejects the raw newline/tab inside the string value.
    try:
        json.loads(raw)
        raise AssertionError("test premise broken: raw parses without repair")
    except json.JSONDecodeError:
        pass
    obj = me._parse_json_object(raw)
    assert obj["clinical_notes"] == "Line one\nLine two\tTabbed"
    assert obj["medications"] == []


def test_control_chars_with_trailing_comma_repaired():
    raw = '{"a": "x\ny", "b": ["i", "j",],}'
    obj = me._try_repair_json(raw)
    assert obj == {"a": "x\ny", "b": ["i", "j"]}


def test_control_chars_outside_strings_left_alone():
    # Newlines between tokens are legal JSON whitespace; the escaper must
    # not touch them (escaping them there would corrupt the document).
    raw = '{\n  "a": 1,\n  "b": 2\n}'
    assert json.loads(me._escape_control_chars_in_strings(raw)) == {"a": 1, "b": 2}
