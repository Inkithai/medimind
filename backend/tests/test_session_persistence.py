"""Offline tests for durable conversation sessions (Supabase-mirrored)."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

import conversation  # noqa: E402


def _clear(patient_key, session_id):
    conversation._SESSIONS.pop((patient_key, session_id), None)


def test_get_session_rehydrates_from_durable_store_on_memory_miss():
    stored_turns = [
        {"role": "user", "content": "What meds am I on?", "timestamp": "2024-01-01T00:00:00+00:00"},
        {
            "role": "assistant",
            "content": "Metformin 500 mg.",
            "timestamp": "2024-01-01T00:00:05+00:00",
        },
    ]
    _clear("u1", "s1")
    with mock.patch.object(conversation, "_load_persisted_session") as load:
        rehydrated = conversation.ConversationSession("u1", "s1")
        rehydrated.turns = list(stored_turns)
        load.return_value = rehydrated

        session = conversation.get_session("u1", "s1")
        assert session is not None
        assert session.get_full_history() == stored_turns
        # ...and it is now cached in memory so the next hit skips the store.
        load.reset_mock()
        again = conversation.get_session("u1", "s1")
        assert again is session
        load.assert_not_called()
    _clear("u1", "s1")


def test_get_session_returns_none_when_nowhere():
    _clear("u2", "s2")
    with mock.patch.object(conversation, "_load_persisted_session", return_value=None):
        assert conversation.get_session("u2", "s2") is None


def test_get_or_create_persists_new_sessions_at_creation():
    _clear("u3", "s3")
    with (
        mock.patch.object(conversation, "_load_persisted_session", return_value=None),
        mock.patch.object(conversation, "_persist_session") as persist,
    ):
        session = conversation.get_or_create_session("u3", "s3")
        assert session.turns == []
        persist.assert_called_once_with(session)
    _clear("u3", "s3")


def test_delete_session_removes_durable_copy_too():
    _clear("u4", "s4")
    conversation._SESSIONS[("u4", "s4")] = conversation.ConversationSession("u4", "s4")
    with mock.patch.object(conversation, "_delete_persisted_session", return_value=True) as ddel:
        assert conversation.delete_session("u4", "s4") is True
        ddel.assert_called_once_with("u4", "s4")
    # durable-only session (memory already gone after a restart)
    with mock.patch.object(conversation, "_delete_persisted_session", return_value=True):
        assert conversation.delete_session("u4", "s4") is True
    with mock.patch.object(conversation, "_delete_persisted_session", return_value=False):
        assert conversation.delete_session("u4", "s4") is False


def test_persist_failure_never_raises():
    session = conversation.ConversationSession("u5", "s5")
    session.add_user_turn("hello")
    with mock.patch("db._get_client", side_effect=RuntimeError("supabase down")):
        # Must not raise even though the client blows up.
        conversation._persist_session(session)


def test_rehydrate_failure_treated_as_unknown_session():
    with mock.patch("db._get_client", side_effect=RuntimeError("supabase down")):
        assert conversation._load_persisted_session("u6", "s6") is None
