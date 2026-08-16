"""API contract tests for the Ask AI endpoints.

Covers input validation (empty/whitespace/oversized questions) and the
error mapping the UI relies on to show a friendly message instead of a
raw stack trace.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


ANSWER = {
    "answer": "You are taking Paracetamol 500mg twice daily.",
    "confidence": 0.9,
    "sources": [{"date": "2026-08-07", "source_file": "Arun (2).jpg", "page": 1}],
    "recommend_professional_consult": False,
}


def _client():
    async def override_user():
        return "anon_qa_test"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


def test_empty_question_is_rejected_before_reaching_the_model():
    answerer = mock.Mock(return_value=ANSWER)
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                response = client.post("/api/v1/qa", json={"question": ""})
        assert response.status_code == 422, response.text
        answerer.assert_not_called()
    finally:
        api.app.dependency_overrides.clear()


def test_whitespace_only_question_is_rejected():
    answerer = mock.Mock(return_value=ANSWER)
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                response = client.post("/api/v1/qa", json={"question": "     "})
        assert response.status_code == 422, response.text
        answerer.assert_not_called()
    finally:
        api.app.dependency_overrides.clear()


def test_question_is_trimmed_before_it_reaches_the_model():
    answerer = mock.Mock(return_value=ANSWER)
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                response = client.post(
                    "/api/v1/qa", json={"question": "  What medications?  "}
                )
        assert response.status_code == 200, response.text
        assert answerer.call_args.kwargs["question"] == "What medications?"
    finally:
        api.app.dependency_overrides.clear()


def test_absurdly_long_question_is_rejected():
    answerer = mock.Mock(return_value=ANSWER)
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                response = client.post(
                    "/api/v1/qa",
                    json={"question": "a" * (api.MAX_QUESTION_LENGTH + 1)},
                )
        assert response.status_code == 422, response.text
        answerer.assert_not_called()
    finally:
        api.app.dependency_overrides.clear()


def test_question_at_the_length_limit_is_accepted():
    try:
        with mock.patch.object(api, "answer_question", return_value=ANSWER):
            with _client() as client:
                response = client.post(
                    "/api/v1/qa", json={"question": "a" * api.MAX_QUESTION_LENGTH}
                )
        assert response.status_code == 200, response.text
    finally:
        api.app.dependency_overrides.clear()


def test_special_characters_and_unicode_are_accepted_verbatim():
    """Script tags are data, not markup: the API must not mangle or reject them."""
    answerer = mock.Mock(return_value=ANSWER)
    questions = [
        "What medications am I taking????",
        "What medications am I taking 🤔?",
        "What is <script>alert(1)</script>?",
        "මම ගන්නා ඖෂධ මොනවාද?",
        "நான் எடுக்கும் மருந்துகள் யாவை?",
    ]
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                for question in questions:
                    response = client.post("/api/v1/qa", json={"question": question})
                    assert response.status_code == 200, (question, response.text)
                    assert answerer.call_args.kwargs["question"] == question
    finally:
        api.app.dependency_overrides.clear()


def test_top_k_is_bounded():
    try:
        with mock.patch.object(api, "answer_question", return_value=ANSWER):
            with _client() as client:
                too_big = client.post(
                    "/api/v1/qa", json={"question": "hi", "top_k": 999}
                )
                too_small = client.post(
                    "/api/v1/qa", json={"question": "hi", "top_k": 0}
                )
        assert too_big.status_code == 422
        assert too_small.status_code == 422
    finally:
        api.app.dependency_overrides.clear()


def test_top_k_is_forwarded_to_retrieval():
    answerer = mock.Mock(return_value=ANSWER)
    try:
        with mock.patch.object(api, "answer_question", answerer):
            with _client() as client:
                response = client.post(
                    "/api/v1/qa", json={"question": "What meds?", "top_k": 3}
                )
        assert response.status_code == 200, response.text
        assert answerer.call_args.kwargs["top_k"] == 3
    finally:
        api.app.dependency_overrides.clear()


def test_model_failure_becomes_a_502_not_a_stack_trace():
    try:
        with mock.patch.object(
            api, "answer_question", side_effect=RuntimeError("Chat completion failed: boom")
        ):
            with _client() as client:
                response = client.post("/api/v1/qa", json={"question": "What meds?"})
        assert response.status_code == 502
        assert "Traceback" not in response.text
    finally:
        api.app.dependency_overrides.clear()


def test_answer_shape_reaches_the_client_with_page_citations():
    try:
        with mock.patch.object(api, "answer_question", return_value=ANSWER):
            with _client() as client:
                response = client.post("/api/v1/qa", json={"question": "What meds?"})
        body = response.json()
        assert body["answer"].startswith("You are taking")
        assert body["sources"][0]["source_file"] == "Arun (2).jpg"
        assert body["sources"][0]["page"] == 1
        assert body["recommend_professional_consult"] is False
    finally:
        api.app.dependency_overrides.clear()


def test_session_message_rejects_a_blank_question_too():
    try:
        with _client() as client:
            created = client.post("/api/v1/sessions")
            session_id = created.json()["session_id"]
            response = client.post(
                f"/api/v1/sessions/{session_id}/messages", json={"question": "   "}
            )
        assert response.status_code == 422, response.text
    finally:
        api.app.dependency_overrides.clear()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
