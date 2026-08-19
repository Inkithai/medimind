"""Conversation routes — single-shot Q&A and multi-turn sessions."""

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv(override=True)
import uuid  # noqa: E402
from typing import Any, Dict, List, Optional  # noqa: E402

from fastapi import (  # noqa: E402
    APIRouter,
    Depends,
    HTTPException,
)
from pydantic import BaseModel, Field, field_validator  # noqa: E402

import audit  # noqa: E402
import conversation  # noqa: E402
from auth import get_current_user  # noqa: E402

logger = logging.getLogger("api.conversation")

router = APIRouter()


#: A question longer than this is a paste accident or an abuse attempt, not
#: a question about a medical record. Rejected before it reaches the LLM.
MAX_QUESTION_LENGTH = 2000


class QARequest(BaseModel):
    """Body for the single-shot (Phase 1) Q&A endpoint."""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    chat_history: Optional[List[Dict[str, str]]] = None
    top_k: int = Field(default=8, ge=1, le=50)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        """A whitespace-only question must never reach the model."""
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Enter a question about your records.")
        return cleaned


class MessageRequest(BaseModel):
    """Body for posting a message into a conversation session (Phase 2)."""

    question: str = Field(min_length=1, max_length=MAX_QUESTION_LENGTH)
    top_k: int = Field(default=8, ge=1, le=50)

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Enter a question about your records.")
        return cleaned


@router.post("/api/v1/qa")
async def qa(body: QARequest, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Answers one question grounded in the authenticated user's indexed
    timeline, with no session/conversation state (caller manages
    chat_history, if any)."""
    try:
        # answer_question() does blocking embedding + LLM I/O. Running it
        # directly in this coroutine stalls the whole event loop, so one slow
        # answer froze every other request (health checks and uploads
        # included). Hand it to a worker thread instead.
        result = await asyncio.to_thread(
            answer_question,
            patient_key=user_id,
            question=body.question,
            chat_history=body.chat_history,
            top_k=body.top_k,
        )
        audit.record(user_id, "qa.ask", {"question_chars": len(body.question or "")})
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------------------------------------------------------------------------
# Multi-turn conversation (Phase 2)
# ---------------------------------------------------------------------------


@router.post("/api/v1/sessions", status_code=201)
async def create_session(user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Starts a new conversation session for the authenticated user and
    returns its session_id, to be used in subsequent
    /sessions/{session_id}/messages calls."""
    session_id = uuid.uuid4().hex
    conversation.get_or_create_session(user_id, session_id)
    audit.record(user_id, "session.create", {"session_id": session_id})
    return {"user_id": user_id, "session_id": session_id}


@router.post("/api/v1/sessions/{session_id}/messages")
async def post_message(
    session_id: str,
    body: MessageRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Asks one question within an existing conversation session — the
    question is rewritten into a self-contained retrieval query using prior
    turns before Chroma retrieval, then answered against the original
    question + history. 404s if the session doesn't exist yet (create it via
    POST /sessions first), or belongs to a different user."""
    session = conversation.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    try:
        # Same reasoning as /qa: query rewriting + retrieval + answering are
        # blocking calls and must not run on the event loop.
        result = await asyncio.to_thread(conversation.ask, session, body.question, top_k=body.top_k)
        audit.record(
            user_id,
            "session.message",
            {
                "session_id": session_id,
                "question_chars": len(body.question or ""),
            },
        )
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@router.get("/api/v1/sessions/{session_id}")
async def get_session_history(
    session_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Returns the full, untrimmed transcript of a conversation session
    (for logging/export/debugging) — never summarized or truncated,
    regardless of how conversation.ask() compacts history for prompting."""
    session = conversation.get_session(user_id, session_id)
    if session is None:
        raise HTTPException(404, f"Session '{session_id}' not found.")
    return {
        "user_id": user_id,
        "session_id": session_id,
        "turns": session.get_full_history(),
    }


@router.delete("/api/v1/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: str = Depends(get_current_user)) -> None:
    """Ends a conversation session, removing its transcript from memory and
    the durable store."""
    if not conversation.delete_session(user_id, session_id):
        raise HTTPException(404, f"Session '{session_id}' not found.")
    audit.record(user_id, "session.delete", {"session_id": session_id})


# ---------------------------------------------------------------------------
# Find care (specialty suggestion + OpenStreetMap directory)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# Tests patch these names on the `api` module; resolve through api at call time.


def answer_question(*args, **kwargs):
    import api as _api

    return _api.answer_question(*args, **kwargs)


def process_document(*args, **kwargs):
    import api as _api

    return _api.process_document(*args, **kwargs)
