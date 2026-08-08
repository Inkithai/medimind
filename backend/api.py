"""
HTTP API (Phase 3 + 4)
=========================================
Exposes the extraction -> timeline -> cross-check -> trend-track -> retrieval
-> conversation pipeline (medical_extractor.py, lab_trends.py, retrieval.py,
conversation.py) over HTTP, under the /api/v1/ prefix. This is a thin
wrapper — all business logic stays in those modules; this file only handles
request/response marshalling, validation, and HTTP status codes.

Every route except /health requires an authenticated caller (see auth.py):
    Authorization: Bearer <jwt>
    X-User-Id: <user_id>

There is one patient per user — user_id from the verified token IS the
patient key used throughout the pipeline, so every read/write is naturally
scoped to the caller. Uploaded files are archived to Cloudinary
(storage.py) and their structured extraction + document_url is persisted
in Supabase Postgres (db.py), keyed by user_id.

Run:
    uvicorn api:app --reload
    # then see interactive docs at http://127.0.0.1:8000/docs

Install (in addition to Phase 1/2 dependencies):
    pip install fastapi uvicorn[standard] python-multipart supabase cloudinary pyjwt

Env:
    LLM_PROVIDER + provider key (GROQ_API_KEY or GEMINI_API_KEY / GOOGLE_API_KEY),
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET,
    JWT_SECRET
    (optional: OPENAI_API_KEY — used only for embeddings, since Groq/Gemini have no
    embeddings API; without it, embeddings run locally via Chroma's ONNX
    MiniLM model)
    (optional: VECTOR_STORE=chroma|supabase, USE_BACKGROUND_JOBS=true for async uploads)
"""

import logging
import os
import re
import uuid
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import conversation
import db
import jobs
import storage
from auth import get_current_user, issue_anonymous_token
from document_filter import NonMedicalDocumentError, assert_medical_document
from lab_trends import track_lab_trends
from medical_extractor import (
    _is_demo_document,
    build_patient_timeline,
    cross_check_prescriptions,
    process_document,
)
from retrieval import answer_question, index_patient_timeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api")

SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".webp")

from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure tables exist (Supabase schema is created via SQL editor,
    # so this is a no-op but kept for compatibility)
    try:
        db.ensure_indexes()
    except Exception as e:
        logger.warning("ensure_indexes failed on startup: %s", e)
    yield
    # Shutdown: nothing to clean up (Chroma client is short-lived per request)


app = FastAPI(title="MediMind API", version="1.0.0", lifespan=lifespan)

# The authenticated routes require custom Authorization / X-User-Id headers,
# which trigger a CORS preflight when the frontend is served from a different
# origin than the API. Allow cross-origin requests from the browser app;
# restrict via CORS_ORIGINS (comma-separated list of origins) when deployed.
# NOTE: allow_credentials=True is invalid with allow_origins=["*"] (browsers
# reject it). When CORS_ORIGINS is "*" we allow all origins without credentials.
_cors_origins_raw = os.environ.get("CORS_ORIGINS", "*").strip()
if _cors_origins_raw == "*":
    _cors_allow_origins = ["*"]
    _cors_allow_credentials = False
else:
    _cors_allow_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]
    _cors_allow_credentials = True
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=_cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(db.SchemaNotInitializedError)
async def schema_not_initialized_handler(request: Request, exc: db.SchemaNotInitializedError):
    """Supabase is reachable but the app's tables don't exist (setup SQL
    never run). Surface the fix as a 503 with instructions instead of a
    bare 500 with a PostgREST PGRST205 stack trace."""
    logger.error("schema not initialized for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(status_code=503, content={"detail": str(exc)})


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class QARequest(BaseModel):
    """Body for the single-shot (Phase 1) Q&A endpoint."""
    question: str
    chat_history: Optional[List[Dict[str, str]]] = None
    top_k: int = Field(default=8, ge=1, le=50)


class MessageRequest(BaseModel):
    """Body for posting a message into a conversation session (Phase 2)."""
    question: str
    top_k: int = Field(default=8, ge=1, le=50)


# ---------------------------------------------------------------------------
# Documents / timeline / cross-check / lab trends
# ---------------------------------------------------------------------------


def _should_use_background(request: Request, prefer_header: Optional[str] = None) -> bool:
    """Client can force async via ?async=true or Prefer: respond-async, or server via USE_BACKGROUND_JOBS."""
    if os.environ.get("USE_BACKGROUND_JOBS", "").lower() in ("true", "1", "yes"):
        return True
    if prefer_header and "respond-async" in prefer_header.lower():
        return True
    try:
        if request.query_params.get("async") == "true":
            return True
    except Exception:
        pass
    return False


async def _execute_upload_pipeline(
    user_id: str,
    files_data: List[Tuple[str, bytes]],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Core upload pipeline shared by sync and background paths."""
    def _progress(step: str, message: str):
        if job_id:
            jobs.update_job(job_id, progress={"step": step, "message": message})
    _progress("reading", f"Processing {len(files_data)} file(s)")
    per_file_pages: List[Tuple[Path, str, List[Dict[str, Any]]]] = []
    new_docs: List[Dict[str, Any]] = []
    # Per-file failures are collected instead of aborting the whole batch: a
    # single unreadable/non-medical file must not discard the successful
    # extractions around it (previously one rejected file failed the entire
    # upload and the client re-processed every file from scratch — paying
    # the provider's rate-limit cost all over again). The request only
    # fails outright when NOTHING could be kept.
    file_errors: List[Dict[str, str]] = []
    from tempfile import TemporaryDirectory as _TD
    with _TD() as tmp_dir:
        for file_index, (original_name, content) in enumerate(files_data, start=1):
            suffix = Path(original_name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                # Unreachable in practice (upload_documents validates
                # extensions up front) — recorded, not raised, for parity.
                logger.warning("upload: user=%s rejected '%s' (unsupported type '%s')", user_id, original_name, suffix or "(none)")
                file_errors.append({
                    "file": original_name,
                    "error": f"Unsupported file type '{suffix or '(no extension)'}' for '{original_name}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}",
                    "kind": "unsupported",
                })
                continue
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem) or "upload"
            tmp_path = Path(tmp_dir) / f"{file_index:03d}_{safe_stem}{suffix}"
            tmp_path.write_bytes(content)
            logger.info("upload: user=%s processing '%s' (%d bytes)", user_id, original_name, len(content))
            _progress("extracting", f"Extracting {original_name} ({file_index}/{len(files_data)})")
            try:
                result = process_document(str(tmp_path))
            except NonMedicalDocumentError as e:
                logger.warning("upload: user=%s rejected '%s': %s", user_id, original_name, e.reason)
                file_errors.append({"file": original_name, "error": str(e), "kind": "not_medical"})
                continue
            except RuntimeError as e:
                logger.error("upload: user=%s processing failed for '%s': %s", user_id, original_name, e, exc_info=True)
                file_errors.append({
                    "file": original_name,
                    "error": f"Processing failed for '{original_name}': {e}. Please retry — this is usually transient. If it keeps happening, try a clearer photo or higher-resolution scan.",
                    "kind": "transient",
                })
                continue
            except ValueError as e:
                msg = str(e)
                if "could not be parsed as JSON" in msg or "model returned" in msg:
                    logger.error("upload: user=%s extraction parse failed for '%s': %s", user_id, original_name, e, exc_info=True)
                    file_errors.append({
                        "file": original_name,
                        "error": f"Extraction failed for '{original_name}': {e}. The AI had trouble reading this file — please retry or try a clearer image.",
                        "kind": "transient",
                    })
                else:
                    logger.error("upload: user=%s extraction failed for '%s': %s", user_id, original_name, e, exc_info=True)
                    file_errors.append({"file": original_name, "error": f"Extraction failed for '{original_name}': {e}", "kind": "invalid"})
                continue
            except Exception as e:
                logger.error("upload: user=%s extraction failed for '%s': %s", user_id, original_name, e, exc_info=True)
                file_errors.append({"file": original_name, "error": f"Processing failed for '{original_name}': {e}. Please retry.", "kind": "transient"})
                continue
            if isinstance(result, dict) and result.get("multi_page"):
                logger.info("upload: user=%s '%s' extracted as %d page(s)", user_id, original_name, len(result["pages"]))
                pages = result["pages"]
            else:
                pages = [result]
            kept_pages: List[Dict[str, Any]] = []
            rejected_reason: Optional[str] = None
            for page_num, page in enumerate(pages, start=1):
                label = original_name if len(pages) == 1 else f"{original_name} (page {page_num})"
                if _is_demo_document(page):
                    logger.warning("upload: user=%s skipped demo/placeholder page '%s'", user_id, label)
                    continue
                try:
                    assert_medical_document(page, label)
                except NonMedicalDocumentError as e:
                    rejected_reason = str(e)
                    break
                if isinstance(page.get("_source"), dict):
                    page["_source"]["file"] = original_name
                kept_pages.append(page)
            if rejected_reason is not None:
                logger.warning("upload: user=%s rejected '%s': %s", user_id, original_name, rejected_reason)
                file_errors.append({"file": original_name, "error": rejected_reason, "kind": "not_medical"})
                continue
            if kept_pages:
                per_file_pages.append((tmp_path, original_name, kept_pages))
        if not per_file_pages:
            if file_errors:
                # Nothing was kept — fail with the per-file reasons verbatim.
                # Pure content problems (non-medical/invalid) keep the old 422;
                # any transient (provider) failure yields a retryable 502.
                kinds = {e["kind"] for e in file_errors}
                detail = " | ".join(e["error"] for e in file_errors)[:2000]
                if "transient" in kinds:
                    raise HTTPException(502, detail)
                raise HTTPException(422, detail)
            raise HTTPException(422, "No medical content found in the uploaded file(s) (all pages were demo/placeholder documents).")
        _progress("upload", "Uploading to Cloudinary")
        for tmp_path, filename, kept_pages in per_file_pages:
            upload_info = storage.upload_patient_document(user_id, str(tmp_path), filename)
            for page in kept_pages:
                page["document_url"] = upload_info["document_url"]
                page["cloudinary_public_id"] = upload_info["cloudinary_public_id"]
                new_docs.append(page)
    _progress("organizing", "Building timeline")
    existing_docs = db.load_documents(user_id)
    all_docs = existing_docs + new_docs
    logger.info("upload: user=%s merged documents: +%d new, %d total", user_id, len(new_docs), len(all_docs))
    try:
        timeline = build_patient_timeline(all_docs)
        _progress("safety", "Cross-checking prescriptions")
        cross_check = cross_check_prescriptions(timeline)
    except NonMedicalDocumentError as e:
        raise HTTPException(422, str(e))
    except RuntimeError as e:
        logger.error("upload: user=%s cross-check failed: %s", user_id, e, exc_info=True)
        raise HTTPException(502, f"Cross-check failed: {e}. Please retry.")
    except Exception as e:
        logger.error("upload: user=%s cross-check failed: %s", user_id, e, exc_info=True)
        raise HTTPException(502, f"Cross-check failed: {e}")
    issue_count = sum(len(v) for v in cross_check.values() if isinstance(v, list))
    logger.info("upload: user=%s timeline rebuilt, cross-check found %d issue(s)", user_id, issue_count)
    lab_trends = track_lab_trends(timeline)
    logger.info("upload: user=%s lab trends: %d trends, %d insufficient", user_id, len(lab_trends["trends"]), len(lab_trends["insufficient_data"]))
    _progress("indexing", "Indexing for Q&A")
    indexed, index_error = True, None
    try:
        chunks_indexed = index_patient_timeline(user_id, timeline)
        if chunks_indexed == 0:
            indexed = False
            index_error = "Extraction succeeded but no medications, lab results, clinical notes, or allergies were found to index — Q&A has no documents to search yet."
            logger.warning("upload: user=%s %s", user_id, index_error)
        else:
            logger.info("upload: user=%s re-indexed for Q&A (%d chunk(s))", user_id, chunks_indexed)
    except Exception as e:
        indexed, index_error = False, str(e)
        logger.error("upload: user=%s indexing failed: %s", user_id, e, exc_info=True)
    db.insert_documents(user_id, new_docs)
    db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
    logger.info("upload: user=%s complete: +%d new, %d total, indexed=%s, failed=%d", user_id, len(new_docs), len(all_docs), indexed, len(file_errors))
    response = {
        "user_id": user_id,
        "documents_added": len(new_docs),
        "documents_total": len(all_docs),
        "timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": lab_trends,
        "indexed": indexed,
        # Files that could not be processed (bad photo, provider hiccup,
        # non-medical content). The rest of the batch is already merged into
        # the timeline above — the client can offer a targeted retry for
        # just these instead of re-uploading everything.
        "failed_files": file_errors,
    }
    if not indexed:
        response["index_error"] = index_error
    done_msg = "Complete" if not file_errors else f"Complete — {len(file_errors)} of {len(files_data)} file(s) failed"
    _progress("ready", done_msg)
    return response


@app.post("/api/v1/documents", status_code=201)
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user),
    prefer: Optional[str] = Header(None, alias="Prefer"),
) -> Dict[str, Any]:
    """
    Uploads one or more documents (PDF/image) for the authenticated user.
    Supports both sync (201) and async (202) modes:
      - Sync (default): processes immediately and returns UploadResponse
      - Async: when USE_BACKGROUND_JOBS=true or ?async=true or Prefer: respond-async,
        returns 202 {job_id, status} and processes in background. Poll GET /jobs/{id}.
    """
    logger.info("upload_documents: user=%s received %d file(s)", user_id, len(files))
    if not files:
        raise HTTPException(400, "No files were uploaded.")

    # Read files upfront (needed for background after request ends)
    files_data: List[Tuple[str, bytes]] = []
    for upload in files:
        original_name = Path(upload.filename or "").name or "upload"
        # Validate extension early
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            logger.warning("upload_documents: user=%s rejected '%s' (unsupported type '%s')", user_id, original_name, suffix or "(none)")
            raise HTTPException(400, f"Unsupported file type '{suffix or '(no extension)'}' for '{original_name}'. Supported: {', '.join(SUPPORTED_EXTENSIONS)}")
        content = await upload.read()
        files_data.append((original_name, content))

    # Decide sync vs async
    use_background = _should_use_background(request, prefer)
    if use_background:
        # Validate all files are medical-like before queuing? We do full validation in background
        # Create job and return 202
        job = jobs.create_job(user_id, [name for name, _ in files_data])
        job_id = job["job_id"]

        async def _run_job():
            try:
                jobs.update_job(job_id, status="processing", progress={"step": "extracting", "message": "Starting extraction"})
                result = await _execute_upload_pipeline(user_id, files_data, job_id=job_id)
                jobs.update_job(job_id, status="completed", progress={"step": "ready", "message": "Complete"}, result=result)
            except HTTPException as e:
                # Preserve the HTTP status as error for polling
                err_msg = e.detail if isinstance(e.detail, str) else str(e.detail)
                jobs.update_job(job_id, status="failed", error=err_msg, progress={"step": "failed", "message": err_msg})
                logger.error("Background job %s failed (HTTP %s): %s", job_id, e.status_code, err_msg)
            except Exception as e:
                logger.error("Background job %s failed: %s", job_id, e, exc_info=True)
                jobs.update_job(job_id, status="failed", error=str(e), progress={"step": "failed", "message": str(e)})

        background_tasks.add_task(_run_job)
        # Return 202 immediately
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=202, content={"job_id": job_id, "status": "processing", "message": "Upload queued — poll GET /api/v1/jobs/{job_id}"})

    # Sync path (default, used by tests)
    return await _execute_upload_pipeline(user_id, files_data)


# --- Background Jobs polling ---
@app.get("/api/v1/jobs")
async def list_jobs(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """List recent jobs for the authenticated user (most recent first)."""
    vals = jobs.list_jobs(user_id, limit=20)
    return {"jobs": vals}


@app.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Poll a background job. Returns 404 if not found or not owned."""
    job = jobs.get_job(job_id, user_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    return job




@app.get("/api/v1/timeline")
async def get_timeline(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's merged timeline (medications, lab
    results, visits, allergies) from the most recent upload/processing run."""
    snapshot = db.load_patient_snapshot(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return snapshot["patient_timeline"]


@app.get("/api/v1/cross-check")
async def get_cross_check(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's latest cross-check report
    (interactions, duplicates, dosage conflicts, allergy conflicts)."""
    snapshot = db.load_patient_snapshot(user_id)
    if snapshot is None:
        raise HTTPException(404, "No cross-check report found for this user.")
    return snapshot["cross_check_report"]


@app.get("/api/v1/lab-trends")
async def get_lab_trends(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's lab result trends (direction of
    drift per test, reference-range crossings, plain-language explanations)
    computed from the most recent upload/processing run. Recomputed on the
    fly from the saved timeline for snapshots saved before this field
    existed."""
    snapshot = db.load_patient_snapshot(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    if "lab_trends" in snapshot:
        return snapshot["lab_trends"]
    return track_lab_trends(snapshot["patient_timeline"])


@app.get("/api/v1/patient-snapshot")
async def get_patient_snapshot(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's entire latest snapshot — patient
    timeline, cross-check report, and lab trends — in a single response, so
    the dashboard can render from ONE request instead of three
    (/timeline, /cross-check, /lab-trends). 404s if the user has never
    been processed (frontend treats that as the first-run empty state).

    `lab_trends` is recomputed on the fly for snapshots saved before the
    field existed, mirroring get_lab_trends()'s backward-compat behavior.
    """
    snapshot = db.load_patient_snapshot(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient snapshot found for this user.")
    result: Dict[str, Any] = {
        "user_id": user_id,
        "patient_timeline": snapshot["patient_timeline"],
        "cross_check_report": snapshot["cross_check_report"],
        "updated_at": snapshot.get("updated_at"),
    }
    if "lab_trends" in snapshot:
        result["lab_trends"] = snapshot["lab_trends"]
    else:
        result["lab_trends"] = track_lab_trends(snapshot["patient_timeline"])
    return result


# ---------------------------------------------------------------------------
# Single-shot Q&A (Phase 1)
# ---------------------------------------------------------------------------

@app.post("/api/v1/qa")
async def qa(body: QARequest, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Answers one question grounded in the authenticated user's indexed
    timeline, with no session/conversation state (caller manages
    chat_history, if any)."""
    try:
        return answer_question(
            patient_key=user_id,
            question=body.question,
            chat_history=body.chat_history,
            top_k=body.top_k,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


# ---------------------------------------------------------------------------
# Multi-turn conversation (Phase 2)
# ---------------------------------------------------------------------------

@app.post("/api/v1/sessions", status_code=201)
async def create_session(user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Starts a new conversation session for the authenticated user and
    returns its session_id, to be used in subsequent
    /sessions/{session_id}/messages calls."""
    session_id = uuid.uuid4().hex
    conversation.get_or_create_session(user_id, session_id)
    return {"user_id": user_id, "session_id": session_id}


@app.post("/api/v1/sessions/{session_id}/messages")
async def post_message(
    session_id: str, body: MessageRequest, user_id: str = Depends(get_current_user),
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
        return conversation.ask(session, body.question, top_k=body.top_k)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except RuntimeError as e:
        raise HTTPException(502, str(e))


@app.get("/api/v1/sessions/{session_id}")
async def get_session_history(
    session_id: str, user_id: str = Depends(get_current_user),
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


@app.delete("/api/v1/sessions/{session_id}", status_code=204)
async def delete_session(session_id: str, user_id: str = Depends(get_current_user)) -> None:
    """Ends a conversation session, freeing its in-memory turn history."""
    if not conversation.delete_session(user_id, session_id):
        raise HTTPException(404, f"Session '{session_id}' not found.")


# ---------------------------------------------------------------------------
# Anonymous session — zero-login flow for MediMind frontend
# ---------------------------------------------------------------------------

@app.post("/api/v1/anonymous/session", status_code=201)
async def create_anonymous_session() -> Dict[str, str]:
    """
    Creates an anonymous workspace for the MediMind frontend. No auth
    required. Issues a signed JWT whose user_id claim is a fresh anon_*
    identifier. The frontend stores {user_id, token} in localStorage and
    uses them as Authorization + X-User-Id for all subsequent calls, so
    existing authenticated routes keep working without any manual credential
    entry. One browser = one isolated patient record.
    """
    user_id, token = issue_anonymous_token()
    logger.info("anonymous session created: user_id=%s", user_id)
    return {"user_id": user_id, "token": token, "session_id": user_id}


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@app.get("/api/v1/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "MediMind"}


@app.get("/")
async def root() -> Dict[str, str]:
    return {"service": "MediMind", "status": "ok", "docs": "/docs"}
