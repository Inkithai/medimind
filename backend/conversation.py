"""
Conversational Q&A Layer (Phase 2)
=========================================
Builds on retrieval.py's single-shot answer_question() to support real
multi-turn conversations about a patient's medical timeline, without
changing retrieval.py's existing behavior for callers that don't use
sessions.

The core problem this solves: a raw embedding search on a follow-up like
"was that safe with my allergy?" retrieves poorly, because the follow-up
is only meaningful in light of what was said earlier. This module:

    1. Tracks conversation turns per (patient_key, session_id) in a plain
       in-memory ConversationSession.
    2. Rewrites each new question into a self-contained search query
       (using conversation history) before it is embedded/retrieved —
       the raw question is still what's shown to the final answering LLM.
    3. Keeps prompt/token cost bounded via a recent-turns window plus
       periodic summarization of older turns.

Env:
    export LLM_PROVIDER=gemini   (or groq; same provider key used by the rest of the pipeline)
    export GEMINI_API_KEY="AIza..."  (or GROQ_API_KEY="gsk_..." for groq)
"""

import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from medical_extractor import MODEL, _chat_completion
import retrieval

logger = logging.getLogger("conversation")

# Cheap/fast model for query rewriting and summarization — these are short,
# low-stakes generations, not the main answer synthesis.
REWRITE_MODEL = MODEL

SUMMARIZE_AFTER_TOTAL_TURNS = 20  # start summarizing once a session grows past this
KEEP_RECENT_TURNS_VERBATIM = 6    # ...but always keep this many most-recent turns as-is


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. Session management
# ---------------------------------------------------------------------------

class ConversationSession:
    """
    Holds the in-memory turn history for one (patient_key, session_id)
    conversation. Pure Python object — no external session store, so
    sessions live only as long as the process does.
    """

    def __init__(self, patient_key: str, session_id: str):
        self.patient_key = patient_key
        self.session_id = session_id
        self.turns: List[Dict[str, str]] = []  # full, untrimmed transcript
        self._summary: Optional[str] = None
        self._summary_covers_up_to = 0  # index into self.turns the cached summary accounts for
        # Monotonic so TTL is immune to wall-clock adjustments.
        self.last_used_at: float = time.monotonic()

    def touch(self) -> None:
        """Marks the session as recently used, deferring its eviction."""
        self.last_used_at = time.monotonic()

    def add_user_turn(self, text: str) -> None:
        """Appends a user turn with the current UTC timestamp."""
        self.turns.append({"role": "user", "content": text, "timestamp": _now_iso()})

    def add_assistant_turn(self, answer: Dict[str, Any]) -> None:
        """Appends an assistant turn. Stores the "answer" field as the turn's
        content (the same text a human would read), since the full answer
        dict (confidence, sources, etc.) is retrievable from logs/exports
        rather than needed for prompting future turns."""
        content = answer.get("answer", "") if isinstance(answer, dict) else str(answer)
        self.turns.append({"role": "assistant", "content": content, "timestamp": _now_iso()})

    def get_history(self, max_turns: int = 6) -> List[Dict[str, str]]:
        """
        Returns the last `max_turns` turns formatted as {"role", "content"}
        dicts, ready to splice into a chat_history list for prompting.

        Once the session exceeds SUMMARIZE_AFTER_TOTAL_TURNS total turns,
        everything older than the most recent KEEP_RECENT_TURNS_VERBATIM
        turns is collapsed into a single "conversation summary so far"
        system message (see summarize_old_turns), which is prepended ahead
        of the verbatim recent turns. This keeps prompt size bounded
        regardless of how long the conversation runs.
        """
        if len(self.turns) > SUMMARIZE_AFTER_TOTAL_TURNS:
            cutoff = len(self.turns) - KEEP_RECENT_TURNS_VERBATIM
            if self._summary_covers_up_to < cutoff:
                self._summary = summarize_old_turns(self.turns[:cutoff])
                self._summary_covers_up_to = cutoff
            recent = self.turns[cutoff:]
            if max_turns < len(recent):
                recent = recent[-max_turns:]
            formatted = [{
                "role": "system",
                "content": f"Conversation summary so far: {self._summary}",
            }]
            formatted.extend({"role": t["role"], "content": t["content"]} for t in recent)
            return formatted

        recent = self.turns[-max_turns:] if max_turns else []
        return [{"role": t["role"], "content": t["content"]} for t in recent]

    def get_full_history(self) -> List[Dict[str, str]]:
        """Returns the complete, untrimmed transcript (with timestamps) for
        logging/export. Unlike get_history(), this is never summarized or
        truncated — summarization only affects what's sent to the LLM for
        prompting, not what's retained in memory."""
        return list(self.turns)


#: Sessions are per-process and never expire on their own, so without a
#: bound this dict grows for the life of the server — every abandoned
#: conversation keeps its full transcript resident. Evict least-recently-used
#: sessions past this many, and drop ones untouched for the TTL.
MAX_SESSIONS = int(os.environ.get("MAX_CONVERSATION_SESSIONS", "500"))
SESSION_TTL_SECONDS = int(os.environ.get("CONVERSATION_SESSION_TTL_SECONDS", str(24 * 3600)))

# Durable transcripts: mirror every session to the Supabase
# conversation_sessions table (created by supabase_schema.sql) so
# conversations survive process restarts/redeploys AND in-memory LRU/TTL
# eviction. Enabled by default; degrades silently to memory-only when
# Supabase is unreachable or the table doesn't exist, so a persistence
# outage can never block Q&A.
PERSIST_SESSIONS = os.environ.get("PERSIST_SESSIONS", "true").lower() in ("true", "1", "yes")

#: OrderedDict = insertion/most-recent order, so eviction is O(1) from the
#: front. Guarded by a lock because FastAPI serves requests from a thread
#: pool: two concurrent turns in the same session would otherwise race.
_SESSIONS: "OrderedDict[Tuple[str, str], ConversationSession]" = OrderedDict()
_SESSIONS_LOCK = threading.RLock()


def _evict_locked() -> None:
    """Drop expired, then oldest, sessions. Caller must hold the lock."""
    now = time.monotonic()
    expired = [
        key
        for key, session in _SESSIONS.items()
        if now - session.last_used_at > SESSION_TTL_SECONDS
    ]
    for key in expired:
        _SESSIONS.pop(key, None)
    while len(_SESSIONS) > MAX_SESSIONS:
        _SESSIONS.popitem(last=False)


# ---------------------------------------------------------------------------
# 1b. Durable transcript store (Supabase, optional)
# ---------------------------------------------------------------------------

def _persist_session(session: ConversationSession) -> None:
    """Mirrors the full transcript to Supabase. Best-effort: any failure
    (missing table, network, misconfiguration) is logged once and swallowed
    so persistence problems never block a conversation turn."""
    if not PERSIST_SESSIONS:
        return
    try:
        from db import _get_client
        _get_client().table("conversation_sessions").upsert(
            {
                "user_id": session.patient_key,
                "session_id": session.session_id,
                "turns": session.turns,
                "updated_at": _now_iso(),
            },
            on_conflict="user_id,session_id",
        ).execute()
    except Exception as e:
        logger.warning("Session persist failed (kept in memory only): %s", e)


def _load_persisted_session(patient_key: str, session_id: str) -> Optional[ConversationSession]:
    """Rehydrates a ConversationSession from Supabase after a process
    restart or LRU/TTL eviction. Returns None when persistence is off, the
    row doesn't exist, or Supabase is unreachable."""
    if not PERSIST_SESSIONS:
        return None
    try:
        from db import _get_client
        res = (
            _get_client().table("conversation_sessions")
            .select("turns")
            .eq("user_id", patient_key)
            .eq("session_id", session_id)
            .limit(1)
            .execute()
        )
        rows = res.data or []
        if not rows:
            return None
        session = ConversationSession(patient_key, session_id)
        session.turns = list(rows[0].get("turns") or [])
        return session
    except Exception as e:
        logger.warning("Session rehydrate failed (treating as unknown session): %s", e)
        return None


def _delete_persisted_session(patient_key: str, session_id: str) -> bool:
    """Removes the durable copy of a session. Returns True if a row was
    deleted. Best-effort — failures are logged and reported as False."""
    if not PERSIST_SESSIONS:
        return False
    try:
        from db import _get_client
        res = (
            _get_client().table("conversation_sessions")
            .delete()
            .eq("user_id", patient_key)
            .eq("session_id", session_id)
            .execute()
        )
        return bool(res.data)
    except Exception as e:
        logger.warning("Session durable delete failed: %s", e)
        return False


def get_or_create_session(patient_key: str, session_id: str) -> ConversationSession:
    """Fetches the ConversationSession for (patient_key, session_id),
    rehydrating from the durable store on a memory miss, and creating +
    registering a new empty one if it doesn't exist anywhere yet."""
    key = (patient_key, session_id)
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            session = _load_persisted_session(patient_key, session_id)
            if session is None:
                session = ConversationSession(patient_key, session_id)
                _persist_session(session)  # register durably at creation time
            _SESSIONS[key] = session
        session.touch()
        _SESSIONS.move_to_end(key)
        _evict_locked()
        return session


def get_session(patient_key: str, session_id: str) -> Optional[ConversationSession]:
    """Fetches the ConversationSession for (patient_key, session_id) without
    creating one. Falls back to the durable store on a memory miss (process
    restarted, or the session was LRU/TTL-evicted since it was created).
    Returns None if no such session exists anywhere — used by callers
    (e.g. the HTTP API) that need to distinguish "unknown session" (404)
    from "brand new session" (auto-create)."""
    key = (patient_key, session_id)
    with _SESSIONS_LOCK:
        session = _SESSIONS.get(key)
        if session is None:
            session = _load_persisted_session(patient_key, session_id)
            if session is None:
                return None
            _SESSIONS[key] = session
        elif time.monotonic() - session.last_used_at > SESSION_TTL_SECONDS:
            # In-memory copy expired. With durable persistence the transcript
            # is still authoritative in Supabase — rehydrate instead of 404ing
            # so a conversation can continue after a long pause. Without
            # persistence, expired == unknown (fresh conversation).
            _SESSIONS.pop(key, None)
            session = _load_persisted_session(patient_key, session_id)
            if session is None:
                return None
            _SESSIONS[key] = session
        session.touch()
        _SESSIONS.move_to_end(key)
        return session


def delete_session(patient_key: str, session_id: str) -> bool:
    """Removes a session from the in-memory registry AND the durable store,
    freeing its turn history. Returns True if a session was found in either
    place and removed, False if it didn't exist."""
    with _SESSIONS_LOCK:
        removed_memory = _SESSIONS.pop((patient_key, session_id), None) is not None
    removed_durable = _delete_persisted_session(patient_key, session_id)
    return removed_memory or removed_durable


def session_count() -> int:
    """Number of live sessions — used by tests and operational checks."""
    with _SESSIONS_LOCK:
        return len(_SESSIONS)


# ---------------------------------------------------------------------------
# 2. Query rewriting
# ---------------------------------------------------------------------------

REWRITE_SYSTEM_PROMPT = """
You rewrite a patient's follow-up question into a single, fully
self-contained search query used to retrieve relevant chunks from that
patient's medical records (medications, lab results, clinical notes,
allergies).

Rules:
- Resolve pronouns and vague references ("that", "it", "the other one",
  "this medication") into the specific medication/lab/date/event they refer
  to, using the conversation history provided.
- Preserve ALL safety-relevant framing from the original question. If the
  patient is asking about risk, danger, safety, interactions, allergies, or
  dosage, the rewritten query must keep that risk framing explicit (e.g.
  keep words like "safe", "danger", "interact", "allergy") — never rewrite
  it into a neutral factual lookup that loses the risk framing.
- Do not answer the question. Do not add information that isn't implied by
  the conversation.
- Output ONLY the rewritten query text — no quotes, no preamble, no
  explanation.
"""


def rewrite_query_with_context(question: str, history: List[Dict[str, str]]) -> str:
    """
    Turns an ambiguous follow-up question into a self-contained search
    query, using recent conversation history for context. This rewritten
    string is what gets embedded for Chroma retrieval — the original
    `question` is left untouched for the final answer-generation prompt.

    If `history` is empty (first turn in a session), rewriting is skipped
    and `question` is returned as-is, since there's no prior context to
    resolve against. If the rewrite LLM call fails for any reason (auth,
    rate limit, network), falls back to the raw `question` rather than
    raising, so a rewrite failure never blocks retrieval entirely.
    """
    if not question or not question.strip():
        return question
    if not history:
        return question

    messages = [{"role": "system", "content": REWRITE_SYSTEM_PROMPT}]
    messages.extend(history)
    messages.append({
        "role": "user",
        "content": (
            f"New follow-up question to rewrite: {question}\n\n"
            "Output only the rewritten, self-contained search query."
        ),
    })

    try:
        response = _chat_completion(model=REWRITE_MODEL, messages=messages)
        rewritten = (response.choices[0].message.content or "").strip()
        return rewritten if rewritten else question
    except Exception as e:
        # _chat_completion raises ProviderRateLimitError (a RuntimeError),
        # APIError, and connection errors — not just OpenAIError. Swallowing
        # only OpenAIError let the common 429/quota path crash the whole turn
        # instead of falling back to the raw question as documented.
        logger.warning("Query rewrite failed, falling back to raw question for retrieval: %s", e)
        return question


# ---------------------------------------------------------------------------
# 3. Summarization of older turns (context-window safety)
# ---------------------------------------------------------------------------

SUMMARIZE_SYSTEM_PROMPT = """
You compress the older portion of a patient/assistant conversation about a
patient's medical records into a short, dense summary that will be used as
background context for later turns in the same conversation.

Rules:
- Preserve every safety-relevant detail: allergies mentioned, medications
  and lab results discussed, and any risk/interaction/dosage questions
  raised — including whether a professional consult was recommended in the
  response.
- Do not soften, omit, or generalize away risk-related content.
- Do not add new information, speculation, or medical advice.
- Output 3-6 sentences of plain prose. No headers, no bullet points, no
  markdown.
"""


def summarize_old_turns(turns: List[Dict[str, str]]) -> str:
    """
    Collapses a list of older {"role", "content"} turns into a single
    compact summary string via a cheap LLM call, preserving safety-relevant
    details (allergies, risk questions, professional-consult flags) rather
    than softening or dropping them.

    Falls back to a crude truncated concatenation of the turns (instead of
    raising) if the summarization call fails, so older context degrades
    gracefully rather than being silently lost.
    """
    if not turns:
        return ""

    transcript = "\n".join(f"{t['role'].upper()}: {t['content']}" for t in turns)
    messages = [
        {"role": "system", "content": SUMMARIZE_SYSTEM_PROMPT},
        {"role": "user", "content": f"Conversation to summarize:\n\n{transcript}"},
    ]

    try:
        response = _chat_completion(model=REWRITE_MODEL, messages=messages)
        return (response.choices[0].message.content or "").strip()
    except Exception as e:
        # Same as rewrite_query_with_context: a hard quota / 429 must not
        # take down get_history() (and therefore ask()) on a long session.
        logger.warning("Conversation summarization failed, using raw fallback: %s", e)
        return transcript[:2000]


# ---------------------------------------------------------------------------
# 4. Conversational answer function
# ---------------------------------------------------------------------------

def ask(session: ConversationSession, question: str, top_k: int = 8) -> Dict[str, Any]:
    """
    Answers one turn of a multi-turn conversation about session.patient_key.

    1. Pulls recent history from the session (get_history()).
    2. Rewrites `question` into a self-contained retrieval query using that
       history (rewrite_query_with_context()) — skipped on the first turn.
    3. Calls retrieval.answer_question() with the rewritten query used for
       Chroma retrieval, but the ORIGINAL question + history passed through
       for the final answer-generation prompt, so the model responds
       naturally to what was actually asked while retrieving against a
       fully-specified query.
    4. Records both the user turn and assistant turn on the session.

    Returns the same JSON shape as retrieval.answer_question() (answer,
    confidence, sources, recommend_professional_consult), plus
    "rewritten_query" — the retrieval query actually used, for debugging
    and demo transparency.

    Raises ValueError for an empty question. A session_id that hasn't been
    seen before is not this function's concern — use get_or_create_session()
    to obtain `session`, which auto-creates one if needed.
    """
    if not question or not question.strip():
        raise ValueError("question is required and cannot be empty.")

    history = session.get_history()
    rewritten_query = rewrite_query_with_context(question, history)

    result = retrieval.answer_question(
        patient_key=session.patient_key,
        question=question,
        chat_history=history,
        top_k=top_k,
        retrieval_query=rewritten_query,
    )

    session.add_user_turn(question)
    session.add_assistant_turn(result)
    _persist_session(session)  # best-effort durable mirror after every turn

    result = dict(result)
    result["rewritten_query"] = rewritten_query
    return result
