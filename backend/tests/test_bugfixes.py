"""Regression tests for bugs found during a repo-wide audit.

Each test pins a specific defect that reached the product:

  * BUG-A  blocking LLM calls stalled the whole event loop
  * BUG-B  "1,200" parsed as 1 in lab trend text
  * BUG-C  different patients could share a Chroma collection
  * BUG-D  conversation sessions were never evicted (unbounded memory)
"""

import os
import sys
import threading
import time
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
import conversation  # noqa: E402
import lab_trends  # noqa: E402
import vector_store  # noqa: E402


# ---------------------------------------------------------------------------
# BUG-A: a slow answer must not block every other request
# ---------------------------------------------------------------------------

def _client():
    async def override_user():
        return "anon_bugfix"

    api.app.dependency_overrides[api.get_current_user] = override_user
    return TestClient(api.app)


SLOW_SECONDS = 1.0
ANSWER = {
    "answer": "Documented.",
    "confidence": 0.9,
    "sources": [],
    "recommend_professional_consult": False,
}


def test_a_slow_qa_request_does_not_block_the_event_loop():
    """One in-flight Ask AI call previously froze the entire server."""

    def slow_answer(**_kwargs):
        time.sleep(SLOW_SECONDS)
        return dict(ANSWER)

    try:
        with mock.patch.object(api, "answer_question", side_effect=slow_answer):
            with _client() as client:
                worker = threading.Thread(
                    target=lambda: client.post("/api/v1/qa", json={"question": "x"})
                )
                worker.start()
                try:
                    time.sleep(SLOW_SECONDS * 0.25)  # ensure /qa is mid-flight
                    started = time.monotonic()
                    health = client.get("/api/v1/health")
                    elapsed = time.monotonic() - started
                finally:
                    worker.join()

        assert health.status_code == 200
        # Comfortably under the blocking time; it was ~1.2s when broken.
        assert elapsed < SLOW_SECONDS * 0.5, f"event loop stalled for {elapsed:.2f}s"
    finally:
        api.app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# BUG-B: grouped thousands were truncated
# ---------------------------------------------------------------------------

def test_b_grouped_thousands_are_not_truncated():
    assert lab_trends._parse_value("1,200") == 1200.0
    assert lab_trends._parse_value("12,345.6") == 12345.6
    assert lab_trends._parse_value("1 200") == 1200.0


def test_b_plain_and_unitful_values_still_parse():
    assert lab_trends._parse_value("9.8") == 9.8
    assert lab_trends._parse_value("9.8 g/dL") == 9.8
    assert lab_trends._parse_value("<0.01") == 0.01
    assert lab_trends._parse_value(42) == 42.0


def test_b_non_numeric_values_stay_none():
    for value in ("negative", "", None, "not detected", True, False):
        assert lab_trends._parse_value(value) is None, value


def test_b_trend_text_reports_the_real_platelet_count():
    """The explanation is patient-facing: 1,200 must not render as 1."""
    timeline = {
        "lab_results_timeline": [
            {
                "test_name": "Platelet Count",
                "value": "1,200",
                "unit": "10^3/uL",
                "reference_range": "150-400",
                "flag": "high",
                "date": "2026-08-07",
                "source_file": "a.jpg",
            },
            {
                "test_name": "Platelet Count",
                "value": "950",
                "unit": "10^3/uL",
                "reference_range": "150-400",
                "flag": "high",
                "date": "2026-08-11",
                "source_file": "b.jpg",
            },
        ]
    }
    report = lab_trends.track_lab_trends(timeline)
    explanation = report["trends"][0]["explanation"]

    assert "1200" in explanation or "1,200" in explanation, explanation
    # The old bug produced "1 10^3/uL"; make sure that shape is gone.
    assert "1 10^3/uL" not in explanation
    # A real 250-unit drop is a decrease, not "stable".
    assert report["trends"][0]["direction"] != "stable"


# ---------------------------------------------------------------------------
# BUG-C: collection names must be unique per patient
# ---------------------------------------------------------------------------

def test_c_similar_patient_keys_get_distinct_collections():
    """Two patients sharing a collection would leak records between them."""
    colliding_pairs = [
        ("Bob", "bob"),
        ("user@x.com", "user_x.com"),
        ("a b", "a_b"),
        ("anon_" + "x" * 80, "anon_" + "x" * 79 + "y"),
    ]
    for first, second in colliding_pairs:
        assert vector_store._sanitize_collection_name(
            first
        ) != vector_store._sanitize_collection_name(second), (first, second)


def test_c_same_key_is_stable_across_calls():
    """Stability matters: an unstable name would orphan the existing index."""
    for key in ("anon_ab12", "Bob", "user@x.com"):
        assert vector_store._sanitize_collection_name(
            key
        ) == vector_store._sanitize_collection_name(key)


def test_c_collection_names_satisfy_chroma_constraints():
    for key in ("a", "anon_" + "x" * 200, "!!!", "  ", "Bob"):
        name = vector_store._sanitize_collection_name(key)
        assert 3 <= len(name) <= 63, (key, name)
        assert name[0].isalnum() and name[-1].isalnum(), (key, name)


# ---------------------------------------------------------------------------
# BUG-D: sessions were never evicted
# ---------------------------------------------------------------------------

def _reset_sessions():
    with conversation._SESSIONS_LOCK:
        conversation._SESSIONS.clear()


def test_d_session_registry_is_bounded():
    original = conversation.MAX_SESSIONS
    _reset_sessions()
    try:
        conversation.MAX_SESSIONS = 5
        for index in range(50):
            conversation.get_or_create_session("patient", f"session-{index}")
        assert conversation.session_count() == 5
    finally:
        conversation.MAX_SESSIONS = original
        _reset_sessions()


def test_d_eviction_drops_the_least_recently_used_session():
    original = conversation.MAX_SESSIONS
    _reset_sessions()
    try:
        conversation.MAX_SESSIONS = 3
        for name in ("a", "b", "c"):
            conversation.get_or_create_session("patient", name)
        # Touching "a" should make "b" the coldest.
        conversation.get_session("patient", "a")
        conversation.get_or_create_session("patient", "d")

        assert conversation.get_session("patient", "a") is not None
        assert conversation.get_session("patient", "b") is None
        assert conversation.get_session("patient", "d") is not None
    finally:
        conversation.MAX_SESSIONS = original
        _reset_sessions()


def test_d_expired_sessions_are_reported_as_missing():
    original_ttl = conversation.SESSION_TTL_SECONDS
    _reset_sessions()
    try:
        conversation.SESSION_TTL_SECONDS = 0
        conversation.get_or_create_session("patient", "stale")
        time.sleep(0.01)
        assert conversation.get_session("patient", "stale") is None
    finally:
        conversation.SESSION_TTL_SECONDS = original_ttl
        _reset_sessions()


def test_d_concurrent_session_creation_is_race_free():
    """FastAPI serves from a thread pool, so the registry must be locked."""
    original = conversation.MAX_SESSIONS
    _reset_sessions()
    try:
        conversation.MAX_SESSIONS = 1000
        seen = []
        barrier = threading.Barrier(8)

        def create():
            barrier.wait()
            seen.append(conversation.get_or_create_session("patient", "shared"))

        threads = [threading.Thread(target=create) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        # Every caller must get the SAME object, or turns would be lost.
        assert len({id(session) for session in seen}) == 1
        assert conversation.session_count() == 1
    finally:
        conversation.MAX_SESSIONS = original
        _reset_sessions()


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
