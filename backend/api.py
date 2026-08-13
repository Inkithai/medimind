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
    (optional: VECTOR_STORE=chroma|supabase, USE_BACKGROUND_JOBS=true,
     UPLOAD_FILE_CONCURRENCY=1 for async per-file worker load control)
    (care directory needs no key: defaults to OpenStreetMap/Overpass.
     Optional CARE_PROVIDER=google + GOOGLE_MAPS_API_KEY with Places API
     (New) enabled + billing, which falls back to OpenStreetMap on failure)
"""

import asyncio
import logging
import os
from dotenv import load_dotenv
load_dotenv(override=True)
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import conversation
import db
import jobs
import storage
from care import CareConfigurationError, CareProviderError, get_care_provider
from auth import get_current_user, issue_anonymous_token
from document_filter import NonMedicalDocumentError, assert_medical_document
from lab_trends import track_lab_trends
from medical_extractor import (
    ProviderRateLimitError,
    _is_demo_document,
    build_patient_timeline,
    cross_check_prescriptions,
    process_document,
)
from retrieval import answer_question, index_patient_timeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api")

SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".webp")


def _upload_worker_count() -> int:
    """Global extraction concurrency, bounded to protect provider quotas.

    One shared executor load-balances documents across all upload jobs. The
    conservative default of one avoids multiplying free-tier LLM calls; a
    paid deployment can raise UPLOAD_FILE_CONCURRENCY without changing the
    API or UI. Individual files still have independent queued/active states.
    """
    try:
        return max(1, min(8, int(os.environ.get("UPLOAD_FILE_CONCURRENCY", "1"))))
    except ValueError:
        return 1


UPLOAD_FILE_CONCURRENCY = _upload_worker_count()
_DOCUMENT_EXECUTOR = ThreadPoolExecutor(
    max_workers=UPLOAD_FILE_CONCURRENCY,
    thread_name_prefix="medimind-document",
)


class UploadPipelineError(HTTPException):
    """HTTP failure carrying metadata used by async job polling clients."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        *,
        code: str,
        retryable: bool,
        retry_after_seconds: Optional[float] = None,
    ) -> None:
        headers = None
        if retry_after_seconds:
            headers = {"Retry-After": str(max(1, round(retry_after_seconds)))}
        super().__init__(status_code=status_code, detail=detail, headers=headers)
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds


from contextlib import asynccontextmanager


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Document worker pool ready: concurrency=%d", UPLOAD_FILE_CONCURRENCY)
    # The care directory always has a keyless OpenStreetMap default, so this
    # only reports which adapter is active rather than gating the feature.
    try:
        care_provider = get_care_provider()
        logger.info("Care directory ready: provider=%s", care_provider.name)
    except CareConfigurationError as error:
        logger.warning("Care directory is not configured: %s", error)
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


@app.exception_handler(UploadPipelineError)
async def upload_pipeline_error_handler(request: Request, exc: UploadPipelineError):
    """Keep upload failures concise while preserving retry metadata."""
    logger.warning(
        "upload pipeline error for %s %s: code=%s retryable=%s",
        request.method,
        request.url.path,
        exc.code,
        exc.retryable,
    )
    return JSONResponse(
        status_code=exc.status_code,
        headers=exc.headers,
        content={
            "detail": str(exc.detail),
            "code": exc.code,
            "retryable": exc.retryable,
            "retry_after_seconds": exc.retry_after_seconds,
        },
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


def _classify_processing_error(error: Exception, file_name: str, file_index: int) -> Dict[str, Any]:
    """Translate internal/provider exceptions into a concise public file error."""
    base: Dict[str, Any] = {
        "file": file_name,
        "file_id": f"file-{file_index}",
        "file_index": file_index,
    }
    if isinstance(error, ProviderRateLimitError):
        if error.retired_model:
            return {
                **base,
                "error": "The server's document-reading model is no longer available. This file was not processed.",
                "kind": "transient",
                "code": error.code,
                "retryable": False,
                "retry_after_seconds": error.retry_after_seconds,
            }
        if error.hard_quota:
            return {
                **base,
                "error": "The document-reading service has no available quota right now. This is not a problem with your file.",
                "kind": "transient",
                "code": error.code,
                "retryable": False,
                "retry_after_seconds": error.retry_after_seconds,
            }
        wait = (
            f" Try again in about {max(1, round(error.retry_after_seconds))} seconds."
            if error.retry_after_seconds
            else " Please wait a minute before retrying."
        )
        return {
            **base,
            "error": "The document-reading service is temporarily busy." + wait,
            "kind": "transient",
            "code": error.code,
            "retryable": True,
            "retry_after_seconds": error.retry_after_seconds,
        }

    text = str(error).lower()
    if "429" in text or "rate-limit" in text or "rate limit" in text or "quota" in text:
        hard = any(marker in text for marker in ("limit: 0", "per day", "daily quota", "quota exhausted"))
        return {
            **base,
            "error": (
                "The document-reading service has no available quota right now. This is not a problem with your file."
                if hard
                else "The document-reading service is temporarily busy. Please wait a minute before retrying."
            ),
            "kind": "transient",
            "code": "provider_quota_exhausted" if hard else "provider_rate_limited",
            "retryable": not hard,
            "retry_after_seconds": None,
        }

    if isinstance(error, ValueError):
        if "could not be parsed as json" in text or "model returned" in text:
            return {
                **base,
                "error": "We couldn't reliably read this file. Try a clearer, upright image or a higher-resolution scan.",
                "kind": "invalid",
                "code": "unreadable_document",
                "retryable": True,
                "retry_after_seconds": None,
            }
        return {
            **base,
            "error": "This file could not be opened or read. Check the file and try again.",
            "kind": "invalid",
            "code": "invalid_document",
            "retryable": False,
            "retry_after_seconds": None,
        }

    return {
        **base,
        "error": "Document processing was interrupted. Please try this file again.",
        "kind": "transient",
        "code": "processing_interrupted",
        "retryable": True,
        "retry_after_seconds": None,
    }


def _blocked_file_error(capacity_error: Dict[str, Any], file_name: str, file_index: int) -> Dict[str, Any]:
    retryable = bool(capacity_error.get("retryable", True))
    return {
        "file": file_name,
        "file_id": f"file-{file_index}",
        "file_index": file_index,
        "error": (
            "Not started because the document-reading service has no available quota right now."
            if not retryable
            else "Not started because the document-reading service is temporarily busy."
        ),
        "kind": capacity_error.get("kind", "transient"),
        "code": capacity_error.get("code", "provider_rate_limited"),
        "retryable": retryable,
        "retry_after_seconds": capacity_error.get("retry_after_seconds"),
    }


def _raise_no_usable_files(file_errors: List[Dict[str, Any]], total_files: int) -> None:
    """Fail a zero-success batch once, without concatenating provider traces."""
    codes = {item.get("code") for item in file_errors}
    retry_after = max(
        (float(item["retry_after_seconds"]) for item in file_errors if item.get("retry_after_seconds")),
        default=None,
    )
    if "provider_model_unavailable" in codes:
        raise UploadPipelineError(
            502,
            "Document reading is unavailable because the server is configured with an AI model that has been retired. No files were added. Please contact support.",
            code="provider_model_unavailable",
            retryable=False,
        )
    if "provider_quota_exhausted" in codes:
        raise UploadPipelineError(
            502,
            "Document reading is temporarily unavailable because the AI service has no usable quota. No files were added, and this is not a problem with your documents. Please try again later or contact support.",
            code="provider_quota_exhausted",
            retryable=False,
            retry_after_seconds=retry_after,
        )
    if "provider_rate_limited" in codes:
        wait = f" in about {max(1, round(retry_after))} seconds" if retry_after else " in a minute"
        raise UploadPipelineError(
            502,
            f"The document-reading service reached a temporary rate-limit, so no files were added. Please try again{wait}.",
            code="provider_rate_limited",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    kinds = {item.get("kind") for item in file_errors}
    if kinds and kinds <= {"not_medical", "invalid", "unsupported"}:
        names = ", ".join(str(item.get("file", "file")) for item in file_errors[:5])
        if len(file_errors) > 5:
            names += f", and {len(file_errors) - 5} more"
        raise UploadPipelineError(
            422,
            f"We couldn't find readable medical information in any of the {total_files} file(s): {names}. Review each file's status below.",
            code="no_medical_content",
            retryable=False,
        )
    raise UploadPipelineError(
        502,
        f"We couldn't process any of the {total_files} file(s) because document processing was interrupted. No files were added; please try again.",
        code="processing_interrupted",
        retryable=True,
    )


async def _execute_upload_pipeline(
    user_id: str,
    files_data: List[Tuple[str, bytes]],
    job_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Process child documents independently, then finalize one patient record.

    Extraction work is submitted to a shared bounded executor. Thus separate
    files can be queued/reading/extracting at different times without allowing
    one batch (or several users) to overwhelm the upstream model provider.
    """

    def _progress(step: str, message: str, **metadata: Any) -> None:
        if job_id:
            jobs.update_job(job_id, progress={"step": step, "message": message, **metadata})

    def _file_progress(
        file_index: int,
        *,
        status: Optional[str] = None,
        step: Optional[str] = None,
        message: Optional[str] = None,
        error_info: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not job_id:
            return
        jobs.update_file_progress(
            job_id,
            file_index,
            status=status,
            step=step,
            message=message,
            error=error_info.get("error") if error_info else None,
            error_code=error_info.get("code") if error_info else None,
            retryable=error_info.get("retryable") if error_info else None,
            retry_after_seconds=error_info.get("retry_after_seconds") if error_info else None,
        )

    total_files = len(files_data)
    _progress(
        "reading",
        f"Preparing {total_files} file(s) for independent processing",
        worker_limit=UPLOAD_FILE_CONCURRENCY,
    )
    new_docs: List[Dict[str, Any]] = []
    file_errors: List[Dict[str, Any]] = []
    successfully_saved_files = 0

    with TemporaryDirectory() as tmp_dir:
        work_items: List[Tuple[int, str, Path]] = []
        for file_index, (original_name, content) in enumerate(files_data, start=1):
            suffix = Path(original_name).suffix.lower()
            if suffix not in SUPPORTED_EXTENSIONS:
                info = {
                    "file": original_name,
                    "file_id": f"file-{file_index}",
                    "file_index": file_index,
                    "error": f"This file type ({suffix or 'no extension'}) is not supported.",
                    "kind": "unsupported",
                    "code": "unsupported_file_type",
                    "retryable": False,
                    "retry_after_seconds": None,
                }
                file_errors.append(info)
                _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                continue
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem) or "upload"
            tmp_path = Path(tmp_dir) / f"{file_index:03d}_{safe_stem}{suffix}"
            tmp_path.write_bytes(content)
            work_items.append((file_index, original_name, tmp_path))

        # Results are keyed by input index so concurrent workers never reorder
        # the response or mismatch duplicate-looking filenames.
        extracted: Dict[int, Tuple[Path, str, List[Dict[str, Any]]]] = {}
        extraction_errors: Dict[int, Dict[str, Any]] = {}
        queue: asyncio.Queue[Optional[Tuple[int, str, Path]]] = asyncio.Queue()
        for item in work_items:
            queue.put_nowait(item)

        # Set after a terminal provider-capacity failure. Workers check it
        # before taking the next queued file, preventing N identical retries.
        capacity_failure: Optional[Dict[str, Any]] = None
        loop = asyncio.get_running_loop()

        async def _worker() -> None:
            nonlocal capacity_failure
            while True:
                item = await queue.get()
                if item is None:
                    queue.task_done()
                    return
                file_index, original_name, tmp_path = item
                try:
                    if capacity_failure is not None:
                        info = _blocked_file_error(capacity_failure, original_name, file_index)
                        extraction_errors[file_index] = info
                        _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                        continue

                    def report_file_step(step: str, message: str) -> None:
                        _file_progress(file_index, status="processing", step=step, message=message)

                    def run_document() -> Dict[str, Any]:
                        # This wrapper starts only when the shared executor has
                        # a real slot. Until then the file truthfully remains
                        # "queued" instead of claiming to be read while it is
                        # sitting behind another upload job.
                        logger.info(
                            "upload: user=%s processing '%s' (%d/%d)",
                            user_id,
                            original_name,
                            file_index,
                            total_files,
                        )
                        _file_progress(
                            file_index,
                            status="processing",
                            step="reading",
                            message="Opening and checking the document",
                        )
                        return process_document(
                            str(tmp_path),
                            progress_callback=report_file_step,
                        )

                    try:
                        result = await loop.run_in_executor(_DOCUMENT_EXECUTOR, run_document)
                    except NonMedicalDocumentError as exc:
                        info = {
                            "file": original_name,
                            "file_id": f"file-{file_index}",
                            "file_index": file_index,
                            "error": "This doesn't appear to contain medical information we can add.",
                            "kind": "not_medical",
                            "code": "not_medical",
                            "retryable": False,
                            "retry_after_seconds": None,
                        }
                        logger.warning("upload: user=%s rejected '%s': %s", user_id, original_name, exc.reason)
                        extraction_errors[file_index] = info
                        _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                        continue
                    except ProviderRateLimitError as exc:
                        # Expected capacity failures are already fully logged at
                        # the provider boundary. Avoid repeating a multi-page
                        # SDK traceback for every uploaded document.
                        logger.warning(
                            "upload: document provider unavailable for '%s' (code=%s, retry_after=%s)",
                            original_name,
                            exc.code,
                            exc.retry_after_seconds,
                        )
                        info = _classify_processing_error(exc, original_name, file_index)
                        extraction_errors[file_index] = info
                        _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                        capacity_failure = info
                        continue
                    except Exception as exc:
                        logger.error("upload: user=%s processing failed for '%s': %s", user_id, original_name, exc, exc_info=True)
                        info = _classify_processing_error(exc, original_name, file_index)
                        extraction_errors[file_index] = info
                        _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                        if info.get("code") in {
                            "provider_rate_limited",
                            "provider_quota_exhausted",
                            "provider_model_unavailable",
                        }:
                            capacity_failure = info
                        continue

                    if not isinstance(result, dict):
                        raise ValueError("model returned an invalid extraction structure")
                    pages = result["pages"] if result.get("multi_page") else [result]
                    kept_pages: List[Dict[str, Any]] = []
                    rejected = False
                    for page_num, page in enumerate(pages, start=1):
                        label = original_name if len(pages) == 1 else f"{original_name} (page {page_num})"
                        if _is_demo_document(page):
                            # During explicit user uploads, demo/placeholder
                            # documents are NOT silently rejected — the user
                            # chose to upload these files.  Log an info note
                            # but still run the medical-content assertion so
                            # genuinely empty pages are caught.  The
                            # _is_demo_document gate is reserved for batch/
                            # folder processing (group_documents_by_patient)
                            # where a folder might accidentally mix in sample
                            # documents alongside real patient data.
                            logger.info(
                                "upload: user=%s demo/placeholder content detected in '%s' — processing anyway",
                                user_id, label,
                            )
                        try:
                            assert_medical_document(page, label)
                        except NonMedicalDocumentError as exc:
                            logger.warning("upload: user=%s rejected '%s': %s", user_id, original_name, exc.reason)
                            rejected = True
                            break
                        if isinstance(page.get("_source"), dict):
                            page["_source"]["file"] = original_name
                        kept_pages.append(page)

                    if rejected or not kept_pages:
                        info = {
                            "file": original_name,
                            "file_id": f"file-{file_index}",
                            "file_index": file_index,
                            "error": "This doesn't appear to contain medical information we can add.",
                            "kind": "not_medical",
                            "code": "not_medical",
                            "retryable": False,
                            "retry_after_seconds": None,
                        }
                        extraction_errors[file_index] = info
                        _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                        continue

                    extracted[file_index] = (tmp_path, original_name, kept_pages)
                    _file_progress(
                        file_index,
                        status="processing",
                        step="saving",
                        message="Medical details found; waiting to save securely",
                    )
                except Exception as exc:
                    # Do not let one malformed extraction result terminate a
                    # worker and leave queue.join() waiting forever.
                    logger.error(
                        "upload: unexpected per-file failure for '%s': %s",
                        original_name,
                        exc,
                        exc_info=True,
                    )
                    info = _classify_processing_error(exc, original_name, file_index)
                    extraction_errors[file_index] = info
                    _file_progress(
                        file_index,
                        status="failed",
                        step="failed",
                        message=info["error"],
                        error_info=info,
                    )
                finally:
                    queue.task_done()

        worker_count = min(UPLOAD_FILE_CONCURRENCY, len(work_items))
        if worker_count:
            _progress(
                "extracting",
                f"Processing files independently ({worker_count} at a time)",
                worker_limit=UPLOAD_FILE_CONCURRENCY,
            )
        workers = [asyncio.create_task(_worker()) for _ in range(worker_count)]
        for _ in workers:
            queue.put_nowait(None)
        if workers:
            await queue.join()
            await asyncio.gather(*workers)

        file_errors.extend(extraction_errors[index] for index in sorted(extraction_errors))

        # Cloud storage is per-file too: one storage failure should not discard
        # documents that were extracted and saved successfully.
        for file_index in sorted(extracted):
            tmp_path, filename, kept_pages = extracted[file_index]
            _file_progress(file_index, status="processing", step="saving", message="Saving securely")
            try:
                upload_info = await asyncio.to_thread(
                    storage.upload_patient_document,
                    user_id,
                    str(tmp_path),
                    filename,
                )
            except Exception as exc:
                logger.error("upload: user=%s secure save failed for '%s': %s", user_id, filename, exc, exc_info=True)
                info = {
                    "file": filename,
                    "file_id": f"file-{file_index}",
                    "file_index": file_index,
                    "error": "We read this file but couldn't save it securely. Please retry it.",
                    "kind": "transient",
                    "code": "storage_unavailable",
                    "retryable": True,
                    "retry_after_seconds": None,
                }
                file_errors.append(info)
                _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                continue

            for page in kept_pages:
                page["document_url"] = upload_info["document_url"]
                page["cloudinary_public_id"] = upload_info["cloudinary_public_id"]
                new_docs.append(page)
            successfully_saved_files += 1
            _file_progress(
                file_index,
                status="completed",
                step="ready",
                message="Details extracted and saved",
            )

    if not new_docs:
        _raise_no_usable_files(file_errors, total_files)

    _progress("organizing", "Updating your medical history")
    existing_docs = db.load_documents(user_id)
    all_docs = existing_docs + new_docs
    logger.info("upload: user=%s merged documents: +%d new, %d total", user_id, len(new_docs), len(all_docs))
    try:
        timeline = build_patient_timeline(all_docs)
        _progress("safety", "Checking medicines and allergies")
        # Safety is another provider call, so it shares the same bounded pool
        # as extraction instead of bypassing load control or blocking polling.
        cross_check = await asyncio.get_running_loop().run_in_executor(
            _DOCUMENT_EXECUTOR,
            cross_check_prescriptions,
            timeline,
        )
    except NonMedicalDocumentError as exc:
        raise UploadPipelineError(422, str(exc), code="not_medical", retryable=False) from exc
    except ProviderRateLimitError as exc:
        if exc.retired_model:
            message = "The files were read, but the safety check uses a retired AI model. Please contact support; the record was not updated."
        elif exc.hard_quota:
            message = "The files were read, but the AI service has no quota available for the safety check. Please try again later; the record was not updated."
        else:
            message = "The files were read, but the safety service is temporarily busy. Please retry the upload later."
        raise UploadPipelineError(
            502,
            message,
            code=exc.code,
            retryable=not (exc.hard_quota or exc.retired_model),
            retry_after_seconds=exc.retry_after_seconds,
        ) from exc
    except RuntimeError as exc:
        logger.error("upload: user=%s cross-check failed: %s", user_id, exc, exc_info=True)
        raise UploadPipelineError(
            502,
            "The files were read, but the safety check was interrupted. The record was not updated; please retry.",
            code="safety_check_failed",
            retryable=True,
        ) from exc
    except Exception as exc:
        logger.error("upload: user=%s cross-check failed: %s", user_id, exc, exc_info=True)
        raise UploadPipelineError(
            502,
            "The files were read, but the safety check could not finish. The record was not updated; please retry.",
            code="safety_check_failed",
            retryable=True,
        ) from exc

    issue_count = sum(len(value) for value in cross_check.values() if isinstance(value, list))
    logger.info("upload: user=%s timeline rebuilt, cross-check found %d issue(s)", user_id, issue_count)
    lab_trends = track_lab_trends(timeline)
    logger.info(
        "upload: user=%s lab trends: %d trends, %d insufficient",
        user_id,
        len(lab_trends["trends"]),
        len(lab_trends["insufficient_data"]),
    )

    _progress("indexing", "Making your record searchable")
    indexed, index_error = True, None
    try:
        chunks_indexed = await asyncio.to_thread(index_patient_timeline, user_id, timeline)
        if chunks_indexed == 0:
            indexed = False
            index_error = "Extraction succeeded but no medications, lab results, clinical notes, or allergies were found to index — Q&A has no documents to search yet."
            logger.warning("upload: user=%s %s", user_id, index_error)
        else:
            logger.info("upload: user=%s re-indexed for Q&A (%d chunk(s))", user_id, chunks_indexed)
    except Exception as exc:
        indexed, index_error = False, str(exc)
        logger.error("upload: user=%s indexing failed: %s", user_id, exc, exc_info=True)

    db.insert_documents(user_id, new_docs)
    db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
    logger.info(
        "upload: user=%s complete: +%d new pages, %d saved files, %d total pages, indexed=%s, failed=%d",
        user_id,
        len(new_docs),
        successfully_saved_files,
        len(all_docs),
        indexed,
        len(file_errors),
    )
    response: Dict[str, Any] = {
        "user_id": user_id,
        "documents_added": len(new_docs),
        "documents_total": len(all_docs),
        "files_received": total_files,
        "files_added": successfully_saved_files,
        "timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": lab_trends,
        "indexed": indexed,
        "failed_files": sorted(file_errors, key=lambda item: item.get("file_index", 0)),
    }
    if not indexed:
        response["index_error"] = index_error
    done_message = (
        "Your health record is up to date"
        if not file_errors
        else f"Finished — {successfully_saved_files} of {total_files} file(s) added"
    )
    _progress("ready", done_message)
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
                jobs.update_job(
                    job_id,
                    status="processing",
                    progress={"step": "upload", "message": "Files received; assigning processing slots"},
                )
                result = await _execute_upload_pipeline(user_id, files_data, job_id=job_id)
                jobs.update_job(
                    job_id,
                    status="completed",
                    progress={"step": "ready", "message": "Your health record is up to date"},
                    result=result,
                )
            except HTTPException as exc:
                # Keep public text concise and expose structured retry metadata
                # through progress. Per-file rows are preserved by update_job's
                # merge semantics.
                public_message = exc.detail if isinstance(exc.detail, str) else "Document processing could not finish."
                jobs.update_job(
                    job_id,
                    status="failed",
                    error=public_message,
                    progress={
                        "step": "failed",
                        "message": public_message,
                        "error_code": getattr(exc, "code", "upload_failed"),
                        "retryable": getattr(exc, "retryable", exc.status_code >= 500),
                        "retry_after_seconds": getattr(exc, "retry_after_seconds", None),
                        "http_status": exc.status_code,
                    },
                )
                logger.error("Background job %s failed (HTTP %s): %s", job_id, exc.status_code, public_message)
            except Exception as exc:
                logger.error("Background job %s failed: %s", job_id, exc, exc_info=True)
                public_message = "Document processing stopped unexpectedly. No record was updated; please try again."
                jobs.update_job(
                    job_id,
                    status="failed",
                    error=public_message,
                    progress={
                        "step": "failed",
                        "message": public_message,
                        "error_code": "upload_failed",
                        "retryable": True,
                        "http_status": 500,
                    },
                )

        background_tasks.add_task(_run_job)
        # Return 202 immediately
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=202,
            content={
                "job_id": job_id,
                "status": "pending",
                "message": f"Upload queued — poll GET /api/v1/jobs/{job_id}",
                "file_count": len(files_data),
                "worker_limit": UPLOAD_FILE_CONCURRENCY,
            },
        )

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
# Care navigation (optional, provider-neutral public directory)
# ---------------------------------------------------------------------------

@app.get("/api/v1/care/facilities")
async def get_care_facilities(
    location: str = Query(default="", max_length=200),
    kind: str = Query(default="any", max_length=30),
    radius_km: float = Query(default=8.0, ge=1.0, le=50.0),
    latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    user_id: str = Depends(get_current_user),
) -> List[Dict[str, Any]]:
    """Return normalized public healthcare listings near an area or point.

    Provider credentials stay server-side. The default adapter is keyless
    OpenStreetMap/Overpass; when ``CARE_PROVIDER=google`` is configured with a
    valid key, Places API (New) is used first and OpenStreetMap covers any
    rejection or empty result. Results are directory listings, not clinical
    referrals or a claim that a facility is "best".
    """
    del user_id  # Authentication protects the optional directory from abuse.
    if not location.strip() and (latitude is None or longitude is None):
        raise HTTPException(400, "Choose a city/area or provide latitude and longitude.")
    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "latitude and longitude must be provided together.")

    normalized_kind = kind.strip().lower() or "any"
    allowed_kinds = {"any", "hospital", "clinic", "pharmacy", "laboratory", "lab", "doctor"}
    if normalized_kind not in allowed_kinds:
        raise HTTPException(400, "Unsupported facility type.")

    try:
        provider = get_care_provider()
        facilities = await asyncio.to_thread(
            provider.search,
            location,
            normalized_kind,
            radius_km,
            latitude=latitude,
            longitude=longitude,
        )
        logger.info(
            "care navigation: provider=%s kind=%s coordinate_search=%s results=%d",
            provider.name,
            normalized_kind,
            latitude is not None,
            len(facilities),
        )
        return [facility.to_dict() for facility in facilities]
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    except CareConfigurationError as error:
        logger.error("care navigation configuration error: %s", error)
        raise HTTPException(
            503,
            "The facility directory is temporarily unavailable. Please try again shortly.",
        ) from error
    except CareProviderError as error:
        logger.warning("care navigation provider error: %s", error)
        raise HTTPException(
            503,
            "The facility directory is temporarily unavailable. Please try again shortly.",
        ) from error
    except Exception as error:
        logger.exception("unexpected care navigation failure: %s", error)
        raise HTTPException(
            503,
            "The facility directory is temporarily unavailable. Please try again shortly.",
        ) from error


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
