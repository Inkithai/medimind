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
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import conversation
import db
import jobs
import storage
from care import CareConfigurationError, CareProviderError, get_care_provider
from care.postprocess import finalize as finalize_facilities
from care.recommendation import recommend_care
from care.recommendations import generate_care_recommendations
from care_recommendations import ProviderSearchError, recommendation_context, search_live_providers
from auth import get_current_user, issue_anonymous_token
from appointment_prep import build_appointment_prep
from change_detection import detect_record_changes
from document_filter import NonMedicalDocumentError, assert_medical_document
from follow_up import build_follow_up_plan
from lab_trends import track_lab_trends
from record_integrity import check_record_integrity


def _lab_trends_need_recompute(report: Any) -> bool:
    """True when a stored snapshot predates recovery / unit-mismatch fixes."""
    if not isinstance(report, dict):
        return True
    trends = report.get("trends")
    if not isinstance(trends, list):
        return True
    for trend in trends:
        if (
            not isinstance(trend, dict)
            or "returned_to_normal" not in trend
            or "risk_level" not in trend
        ):
            return True
    return False


def _lab_trends_for_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    stored = snapshot.get("lab_trends")
    if stored is None or _lab_trends_need_recompute(stored):
        return track_lab_trends(snapshot["patient_timeline"])
    return stored


from medical_extractor import (
    ProviderRateLimitError,
    _is_demo_document,
    build_patient_timeline,
    cross_check_prescriptions,
    process_document,
)
from memory_probe import log_rss
from retrieval import answer_question, index_patient_timeline, preload_embedding_model, timeline_fingerprint
from record_trust import (
    CorrectionValidationError,
    apply_correction_events,
    apply_conflict_quarantine,
    build_correction_events,
    detect_conflicts,
    document_id as trust_document_id,
    merge_conflict_state,
)
from care.models import FACILITY_KINDS
from care.service import CareNavigationError, get_care_service
import care_finder

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

    # Load the embedding model ONCE, at startup, outside any request. The
    # local ONNX MiniLM weights (~79 MB) were previously downloaded and the
    # session created in the middle of an upload, adding a large memory
    # spike exactly when extraction results were also in memory. Warming it
    # here makes startup memory visible and keeps uploads flat. Opt out with
    # PRELOAD_EMBEDDING_MODEL=false (it then loads lazily on first index).
    log_rss(logger, "startup")
    if os.environ.get("PRELOAD_EMBEDDING_MODEL", "true").strip().lower() not in ("false", "0", "no"):
        try:
            await asyncio.to_thread(preload_embedding_model)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Embedding model preload skipped: %s", exc)
        log_rss(logger, "startup_embeddings_ready")
    yield
    # Shutdown: nothing to clean up. The Chroma client and the embedding
    # model are process-wide singletons that live for the app's lifetime.


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


@app.exception_handler(care_finder.CareFinderError)
async def care_finder_error_handler(request: Request, exc: care_finder.CareFinderError):
    status = 422 if exc.code == "city_not_found" else 502
    logger.warning("care finder error for %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=status,
        content={
            "detail": str(exc),
            "code": exc.code,
            "retryable": exc.retryable,
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


class CorrectionChange(BaseModel):
    field_path: str
    corrected_value: Any = None
    expected_previous_value: Any = None


class CorrectionRequest(BaseModel):
    changes: List[CorrectionChange] = Field(min_length=1, max_length=100)
    reason: str = Field(min_length=3, max_length=500)


class ConflictResolutionRequest(BaseModel):
    authoritative_document_id: str = Field(min_length=1, max_length=200)
    note: Optional[str] = Field(default=None, max_length=1000)


class ConflictReopenRequest(BaseModel):
    note: Optional[str] = Field(default=None, max_length=1000)


def _empty_cross_check(reason: str) -> Dict[str, Any]:
    return {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
        "overall_recommendation": reason,
    }


async def _cross_check_trusted_timeline(timeline: Dict[str, Any]) -> Dict[str, Any]:
    if not timeline.get("medications_timeline"):
        return _empty_cross_check(
            "No trusted medication facts are currently available for safety analysis. "
            "Resolve quarantined conflicts and consult a doctor or pharmacist before making changes."
        )
    return await asyncio.get_running_loop().run_in_executor(
        _DOCUMENT_EXECUTOR,
        cross_check_prescriptions,
        timeline,
    )


class CareSearchRequest(BaseModel):
    """Find clinics/doctors near a city (Geoapify, OSM fallback)."""
    city: str = Field(..., min_length=2, max_length=160)
    specialty: Optional[str] = None
    days: List[str] = Field(default_factory=lambda: ["mon", "tue", "wed", "thu", "fri"])
    time_of_day: str = Field(default="any")
    radius_km: float = Field(default=8, ge=1, le=50)


class CareProviderSearchRequest(BaseModel):
    """Authenticated runtime search for real local care-provider records."""
    flag_id: str = Field(min_length=1, max_length=160)
    location: str = Field(min_length=2, max_length=200)
    availability: Literal["any", "today", "this_week", "evenings", "weekends"] = "any"


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
                # Stable application-level ID keeps old and new documents
                # correctable without exposing storage-provider identifiers.
                page.setdefault("_document_id", f"doc_{uuid.uuid4().hex}")
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

    # Detect conflicts before deriving anything. Resolved source choices are
    # replayed when still valid; unresolved/non-authoritative facts remain in
    # the document viewer but are removed from analytics and RAG inputs.
    detected_conflicts = detect_conflicts(all_docs)
    persisted_conflicts: List[Dict[str, Any]] = []
    if detected_conflicts:
        try:
            persisted_conflicts = db.load_conflicts(user_id)
        except db.SchemaNotInitializedError:
            raise
        except Exception as exc:
            logger.warning("upload: could not load conflict state; using fail-closed unresolved policy: %s", exc)
    active_conflicts = merge_conflict_state(detected_conflicts, persisted_conflicts)
    trusted_docs, trust_summary = apply_conflict_quarantine(all_docs, active_conflicts)

    try:
        timeline = build_patient_timeline(trusted_docs)
        timeline["trust_summary"] = trust_summary
        timeline["conflicts"] = active_conflicts
        _progress("safety", "Checking medicines and allergies")
        # Safety is another provider call, so it shares the same bounded pool
        # as extraction instead of bypassing load control or blocking polling.
        cross_check = await _cross_check_trusted_timeline(timeline)
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

    # ------------------------------------------------------------------
    # PERSIST FIRST. The medical record is the product; the vector index is
    # derived data that can always be rebuilt from it (retrieval.py
    # self-heals via _reindex_from_persisted_documents). Indexing used to
    # run before these two writes, so when the container was OOM-killed
    # during indexing the process died with the extracted documents still
    # only in memory — the user's upload "succeeded" in the logs and then
    # vanished. Writing to Supabase first makes a crash at worst cost the
    # search index, never the record.
    # ------------------------------------------------------------------
    timeline["_record_fingerprint"] = timeline_fingerprint(timeline)
    _progress("saving", "Saving your records securely")
    log_rss(logger, "upload_before_persist", user=user_id, new_pages=len(new_docs))
    db.insert_documents(user_id, new_docs)
    if detected_conflicts or persisted_conflicts:
        active_conflicts = db.sync_conflicts(user_id, detected_conflicts)
        timeline["conflicts"] = active_conflicts
    db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
    logger.info(
        "upload: user=%s persisted %d new page(s) to Supabase before indexing",
        user_id,
        len(new_docs),
    )

    _progress("indexing", "Making your record searchable", records_saved=True)
    log_rss(logger, "upload_indexing_start", user=user_id)
    indexed, index_error = True, None
    index_error_code: Optional[str] = None
    try:
        chunks_indexed = await asyncio.to_thread(
            index_patient_timeline, user_id, timeline, replace=True
        )
        if chunks_indexed == 0:
            indexed = False
            index_error_code = "no_indexable_content"
            index_error = "Extraction succeeded but no medications, lab results, clinical notes, diagnoses, or allergies were found to index — Q&A has no documents to search yet."
            logger.warning("upload: user=%s %s", user_id, index_error)
        else:
            logger.info("upload: user=%s re-indexed for Q&A (%d chunk(s))", user_id, chunks_indexed)
    except MemoryError as exc:
        indexed, index_error, index_error_code = False, str(exc) or "out of memory", "memory_limit"
        logger.error("upload: user=%s indexing ran out of memory: %s", user_id, exc)
    except Exception as exc:
        indexed, index_error = False, str(exc)
        index_error_code = "indexing_failed"
        logger.error("upload: user=%s indexing failed: %s", user_id, exc, exc_info=True)
    log_rss(logger, "upload_indexing_end", user=user_id, indexed=indexed)

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
        "trust_summary": trust_summary,
        "conflicts": active_conflicts,
        "failed_files": sorted(file_errors, key=lambda item: item.get("file_index", 0)),
    }
    if not indexed:
        response["index_error"] = index_error
        response["index_error_code"] = index_error_code
    # Indexing is derived data, so a failure there is NOT an upload failure:
    # the record is already saved. Report it as an explicit "partial" state
    # with machine-readable metadata instead of leaving the client stuck on
    # "indexing" (or lying with "ready").
    indexing_broke = index_error_code in {"memory_limit", "indexing_failed"}
    if indexing_broke:
        _progress(
            "partial",
            "Your documents are saved. Search and Q&A will finish setting up shortly.",
            stage="indexing",
            error=index_error_code,
            error_detail=index_error,
            records_saved=True,
            indexing_completed=False,
            files_completed=successfully_saved_files,
            retryable=True,
        )
    else:
        done_message = (
            "Your health record is up to date"
            if not file_errors
            else f"Finished — {successfully_saved_files} of {total_files} file(s) added"
        )
        _progress(
            "ready",
            done_message,
            records_saved=True,
            indexing_completed=indexed,
            files_completed=successfully_saved_files,
        )
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
        # Unsupported types are recorded per-file in the pipeline (failed_files)
        # rather than aborting the whole batch — one .txt next to a valid
        # prescription must not discard the prescription.
        suffix = Path(original_name).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            logger.warning(
                "upload_documents: user=%s will skip '%s' (unsupported type '%s')",
                user_id, original_name, suffix or "(none)",
            )
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
                # The pipeline may have finished in the "partial" state
                # (records saved, indexing did not complete). Don't overwrite
                # that with a blanket "ready" — the client needs to know the
                # difference between a fully-ready record and a saved record
                # whose search index still has to be rebuilt.
                current = jobs.get_job(job_id, user_id) or {}
                if (current.get("progress") or {}).get("step") == "partial":
                    jobs.update_job(job_id, status="completed", result=result)
                else:
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




@app.get("/api/v1/corrections")
async def list_corrections(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return the immutable field-level correction audit history."""
    return {"corrections": db.load_correction_events(user_id)}


@app.get("/api/v1/documents/{document_id}/corrections")
async def get_document_corrections(
    document_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    originals = db.load_documents(user_id, include_corrections=False)
    effective = db.load_documents(user_id)
    original = next((doc for doc in originals if trust_document_id(doc) == document_id), None)
    current = next((doc for doc in effective if trust_document_id(doc) == document_id), None)
    if original is None or current is None:
        raise HTTPException(404, "Document not found in this workspace.")
    return {
        "document_id": document_id,
        "original_extraction": original,
        "effective_extraction": current,
        "corrections": db.load_correction_events(user_id, document_id),
    }


@app.post("/api/v1/documents/{document_id}/corrections", status_code=201)
async def correct_document_extraction(
    document_id: str,
    body: CorrectionRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Append correction events, then rebuild every derived representation."""
    originals = db.load_documents(user_id, include_corrections=False)
    effective_docs = db.load_documents(user_id)
    original = next((doc for doc in originals if trust_document_id(doc) == document_id), None)
    current = next((doc for doc in effective_docs if trust_document_id(doc) == document_id), None)
    if original is None or current is None:
        raise HTTPException(404, "Document not found in this workspace.")

    batch_id = f"correction_{uuid.uuid4().hex}"
    changes = [change.model_dump(exclude_unset=True) for change in body.changes]
    try:
        events = build_correction_events(
            original,
            current,
            changes,
            user_id=user_id,
            correction_batch_id=batch_id,
            reason=body.reason,
        )
        prospective_docs = apply_correction_events(effective_docs, events)
        trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(
            user_id, prospective_docs
        )
        timeline, cross_check, lab_trends = await _derive_record(trusted, conflicts, trust_summary)
    except CorrectionValidationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderRateLimitError as exc:
        raise HTTPException(503, "The correction was not saved because the safety rebuild is temporarily unavailable. Please retry.") from exc
    except RuntimeError as exc:
        raise HTTPException(502, f"The correction was not saved because the record rebuild failed: {exc}") from exc

    # The expensive derivation succeeded. Append the audit rows first; source
    # documents are never updated. Then atomically replace each derived view
    # as far as the backing services permit.
    db.insert_correction_events(user_id, events)
    persisted_conflicts = db.sync_conflicts(user_id, detected)
    timeline["conflicts"] = persisted_conflicts
    db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
    indexed, index_error, chunks_indexed = await _replace_index(user_id, timeline)
    return {
        "correction_batch_id": batch_id,
        "document_id": document_id,
        "events": events,
        "timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": lab_trends,
        "conflicts": persisted_conflicts,
        "trust_summary": trust_summary,
        "indexed": indexed,
        "chunks_indexed": chunks_indexed,
        "index_error": index_error,
    }


@app.get("/api/v1/conflicts")
async def list_record_conflicts(
    include_inactive: bool = Query(default=False),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    documents = db.load_documents(user_id)
    if not documents:
        return {"conflicts": [], "resolution_events": [], "trust_summary": {}}
    detected = detect_conflicts(documents)
    db.sync_conflicts(user_id, detected)
    conflicts = db.load_conflicts(user_id, include_inactive=include_inactive)
    active = [item for item in conflicts if item.get("status") != "superseded"]
    _trusted, trust_summary = apply_conflict_quarantine(documents, active)
    return {
        "conflicts": conflicts,
        "resolution_events": db.load_conflict_events(user_id),
        "trust_summary": trust_summary,
    }


async def _change_conflict_status(
    user_id: str,
    conflict_id: str,
    *,
    status: str,
    authoritative_document_id: Optional[str],
    note: Optional[str],
) -> Dict[str, Any]:
    documents = db.load_documents(user_id)
    if not documents:
        raise HTTPException(404, "No records found in this workspace.")
    detected = detect_conflicts(documents)
    db.sync_conflicts(user_id, detected)
    persisted = db.load_conflicts(user_id)
    current = next((item for item in persisted if item.get("conflict_id") == conflict_id), None)
    if current is None:
        raise HTTPException(404, "Conflict not found or no longer active.")
    source_ids = {str(item.get("document_id")) for item in current.get("items", [])}
    if status == "resolved" and authoritative_document_id not in source_ids:
        raise HTTPException(400, "Choose one of the conflicting source documents as authoritative.")

    override = {
        "status": status,
        "authoritative_document_id": authoritative_document_id if status == "resolved" else None,
        "resolution_note": (note or "").strip() or None,
    }
    trusted, conflicts, trust_summary, _detected = _prepare_current_trust_state(
        user_id,
        documents,
        conflict_overrides={conflict_id: override},
    )
    try:
        timeline, cross_check, lab_trends = await _derive_record(trusted, conflicts, trust_summary)
    except ProviderRateLimitError as exc:
        raise HTTPException(503, "The source decision was not saved because the safety rebuild is temporarily unavailable. Please retry.") from exc
    except RuntimeError as exc:
        raise HTTPException(502, f"The source decision was not saved because the record rebuild failed: {exc}") from exc

    try:
        saved_conflict = db.set_conflict_resolution(
            user_id,
            conflict_id,
            status=status,
            authoritative_document_id=authoritative_document_id,
            note=note,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
    timeline["conflicts"] = [
        saved_conflict if item.get("conflict_id") == conflict_id else item
        for item in conflicts
    ]
    db.save_patient_snapshot(user_id, timeline, cross_check, lab_trends=lab_trends)
    indexed, index_error, chunks_indexed = await _replace_index(user_id, timeline)
    return {
        "conflict": saved_conflict,
        "timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": lab_trends,
        "trust_summary": trust_summary,
        "indexed": indexed,
        "chunks_indexed": chunks_indexed,
        "index_error": index_error,
    }


@app.post("/api/v1/conflicts/{conflict_id}/resolve")
async def resolve_record_conflict(
    conflict_id: str,
    body: ConflictResolutionRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    return await _change_conflict_status(
        user_id,
        conflict_id,
        status="resolved",
        authoritative_document_id=body.authoritative_document_id,
        note=body.note,
    )


@app.post("/api/v1/conflicts/{conflict_id}/reopen")
async def reopen_record_conflict(
    conflict_id: str,
    body: ConflictReopenRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    return await _change_conflict_status(
        user_id,
        conflict_id,
        status="unresolved",
        authoritative_document_id=None,
        note=body.note,
    )


def _prepare_current_trust_state(
    user_id: str,
    documents: Optional[List[Dict[str, Any]]] = None,
    *,
    conflict_overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any], List[Dict[str, Any]]]:
    corrected_docs = documents if documents is not None else db.load_documents(user_id)
    detected = detect_conflicts(corrected_docs)
    persisted = db.load_conflicts(user_id) if detected else []
    conflicts = merge_conflict_state(detected, persisted)
    if conflict_overrides:
        conflicts = [
            {**conflict, **conflict_overrides.get(str(conflict.get("conflict_id")), {})}
            for conflict in conflicts
        ]
    trusted_docs, trust_summary = apply_conflict_quarantine(corrected_docs, conflicts)
    return trusted_docs, conflicts, trust_summary, detected


def _timeline_from_trust_state(
    trusted_docs: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    trust_summary: Dict[str, Any],
) -> Dict[str, Any]:
    timeline = build_patient_timeline(trusted_docs)
    timeline["trust_summary"] = trust_summary
    timeline["conflicts"] = conflicts
    timeline["_record_fingerprint"] = timeline_fingerprint(timeline)
    return timeline


async def _derive_record(
    trusted_docs: List[Dict[str, Any]],
    conflicts: List[Dict[str, Any]],
    trust_summary: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    timeline = _timeline_from_trust_state(trusted_docs, conflicts, trust_summary)
    cross_check = await _cross_check_trusted_timeline(timeline)
    lab_trends = track_lab_trends(timeline)
    return timeline, cross_check, lab_trends


async def _replace_index(user_id: str, timeline: Dict[str, Any]) -> Tuple[bool, Optional[str], int]:
    try:
        count = await asyncio.to_thread(index_patient_timeline, user_id, timeline, replace=True)
        if count == 0:
            return False, "No trusted facts are currently available to index; unresolved conflicts may be quarantined.", 0
        return True, None, count
    except Exception as exc:
        logger.error("record rebuild: user=%s index replacement failed: %s", user_id, exc, exc_info=True)
        return False, str(exc), 0




@app.get("/api/v1/documents")
async def list_documents(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return every document page persisted for the authenticated user.

    This reads straight from Supabase, so it is the authoritative answer to
    "did my records survive the restart?". It never touches the vector
    index or any in-process state: a redeployed/OOM-restarted container
    returns exactly the same list. An empty list means the rows genuinely
    are not there — not that the process forgot them.
    """
    documents = db.load_documents(user_id)
    return {
        "user_id": user_id,
        "count": len(documents),
        "documents": documents,
    }


_EMPTY_CROSS_CHECK: Dict[str, Any] = {
    "potential_drug_interactions": [],
    "duplicate_prescriptions": [],
    "conflicting_dosage_instructions": [],
    "allergy_conflicts": [],
    "overall_recommendation": (
        "Your records were restored from storage, so the medication safety "
        "check has not been re-run yet. Upload a document or ask a question "
        "to refresh it."
    ),
}


def _rebuild_snapshot_from_documents(user_id: str) -> Optional[Dict[str, Any]]:
    """Reconstruct the patient snapshot directly from the saved documents.

    `patient_snapshots` is a convenience cache: everything in it is derived
    from the append-only `documents` rows. If that cache row is missing
    (never written because the process died mid-upload, or wiped), the
    dashboard must NOT claim the user has no records — the documents are
    still in the database. Rebuilding here is deterministic and free: the
    timeline merge and lab-trend analysis are pure functions. Only the
    safety cross-check needs an LLM, so it is returned empty and refreshed
    on the next upload rather than firing a provider call from a GET.
    """
    try:
        documents = db.load_documents(user_id)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("snapshot rebuild: user=%s could not load documents: %s", user_id, exc)
        return None
    if not documents:
        return None

    logger.info(
        "snapshot rebuild: user=%s reconstructing from %d persisted document(s)",
        user_id,
        len(documents),
    )
    timeline = build_patient_timeline(documents)
    return {
        "patient_timeline": timeline,
        "cross_check_report": dict(_EMPTY_CROSS_CHECK),
        "lab_trends": track_lab_trends(timeline),
        "updated_at": None,
        "rebuilt_from_documents": True,
    }


def _load_snapshot_or_rebuild(user_id: str) -> Optional[Dict[str, Any]]:
    """Return a current, fail-closed view rebuilt from durable source rows.

    The snapshot remains a cache for expensive safety output, but corrected
    and quarantined documents are replayed on every read so an older cache can
    never re-admit unresolved or non-authoritative facts.
    """
    snapshot = db.load_patient_snapshot(user_id)
    documents = db.load_documents(user_id)
    if not documents:
        return snapshot

    trusted, conflicts, summary, _detected = _prepare_current_trust_state(user_id, documents)
    timeline = _timeline_from_trust_state(trusted, conflicts, summary)
    saved_fingerprint = (snapshot or {}).get("patient_timeline", {}).get("_record_fingerprint")
    cache_is_current = bool(snapshot and saved_fingerprint == timeline.get("_record_fingerprint"))
    if cache_is_current and not summary.get("unresolved_conflicts"):
        cross_check = snapshot.get("cross_check_report") or dict(_EMPTY_CROSS_CHECK)
    else:
        cross_check = _empty_cross_check(
            "Safety analysis is withheld while corrected or conflicting evidence awaits a trusted rebuild. "
            "Confirm the source and consult a doctor or pharmacist before making changes."
        )
    result = {
        "patient_timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": track_lab_trends(timeline),
        "updated_at": (snapshot or {}).get("updated_at"),
    }
    if snapshot is None:
        result["rebuilt_from_documents"] = True
    return result


def _enhanced_cross_check(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """Backfill deterministic findings/source links for older snapshots."""
    from medication_history import detect_medication_transitions, enrich_cross_check_sources

    timeline = snapshot["patient_timeline"]
    report = dict(snapshot.get("cross_check_report") or {})
    report.setdefault("potential_drug_interactions", [])
    report.setdefault("duplicate_prescriptions", [])
    report.setdefault("conflicting_dosage_instructions", [])
    report.setdefault("allergy_conflicts", [])
    transitions = detect_medication_transitions(timeline)
    report.setdefault("medication_changes", transitions["medication_changes"])
    report.setdefault("medication_continuations", transitions["medication_continuations"])
    return enrich_cross_check_sources(report, timeline)


def _enhanced_lab_trends(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    saved = snapshot.get("lab_trends")
    if saved and all("risk_level" in trend for trend in saved.get("trends", [])):
        return saved
    return track_lab_trends(snapshot["patient_timeline"])


@app.get("/api/v1/timeline")
async def get_timeline(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's merged timeline (medications, lab
    results, visits, allergies) from the most recent upload/processing run."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return snapshot["patient_timeline"]


@app.get("/api/v1/cross-check")
async def get_cross_check(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's latest cross-check report
    (interactions, duplicates, dosage conflicts, allergy conflicts)."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No cross-check report found for this user.")
    return _enhanced_cross_check(snapshot)


@app.get("/api/v1/lab-trends")
async def get_lab_trends(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the authenticated user's lab result trends (direction of
    drift per test, reference-range crossings, plain-language explanations)
    computed from the most recent upload/processing run. Recomputed on the
    fly from the saved timeline for snapshots saved before this field
    existed."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return _lab_trends_for_snapshot(snapshot)


@app.get("/api/v1/changes")
async def get_record_changes(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Explain what changed between consecutive dated records.

    Results are deterministic and include both source records for every
    claim. Missing fields are never interpreted as clinical resolution or a
    discontinued treatment.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return detect_record_changes(snapshot["patient_timeline"])


@app.get("/api/v1/follow-up")
async def get_follow_up_plan(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return a source-grounded action queue without inferred deadlines."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    timeline = snapshot["patient_timeline"]
    lab_trends_data = snapshot.get("lab_trends") or track_lab_trends(timeline)
    return build_follow_up_plan(timeline, snapshot["cross_check_report"], lab_trends_data)


@app.get("/api/v1/record-integrity")
async def get_record_integrity(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Find source-linked cross-document discrepancies for verification."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    return check_record_integrity(snapshot["patient_timeline"])


@app.get("/api/v1/appointment-prep")
async def get_appointment_prep(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Build a printable, source-grounded clinician conversation packet."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No timeline found for this user.")
    timeline = snapshot["patient_timeline"]
    lab_trends_data = snapshot.get("lab_trends") or track_lab_trends(timeline)
    return build_appointment_prep(timeline, snapshot["cross_check_report"], lab_trends_data)


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
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient snapshot found for this user.")
    result: Dict[str, Any] = {
        "user_id": user_id,
        "patient_timeline": snapshot["patient_timeline"],
        "cross_check_report": _enhanced_cross_check(snapshot),
        "updated_at": snapshot.get("updated_at"),
    }
    if snapshot.get("rebuilt_from_documents"):
        # Tells the client this view was reconstructed from the durable
        # documents table rather than the cached snapshot row.
        result["rebuilt_from_documents"] = True
    result["lab_trends"] = _lab_trends_for_snapshot(snapshot)
    return result


# ---------------------------------------------------------------------------
# Live local-care recommendations (clinical flag -> specialty -> directory)
# ---------------------------------------------------------------------------

@app.get("/api/v1/care/recommendation")
async def get_care_recommendation(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Map saved safety/lab evidence to a transparent directory category."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record is available for a care recommendation.")
    return recommend_care(
        snapshot["patient_timeline"],
        _enhanced_cross_check(snapshot),
        _lab_trends_for_snapshot(snapshot),
    )


@app.get("/api/v1/care/recommendations")
async def get_scored_care_recommendations(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Analyze patient records and return ranked, scored care recommendations.

    Each recommendation carries a transparent 0-100 relevance_score assembled
    from explicit score_factors (medication/allergy conflicts, drug
    interactions, lab trends, polypharmacy, visit history), plus a
    has_safety_signal flag when a safety finding drives the suggestion.

    Pure rule-based analysis of the patient's structured data — no LLM.
    The score is an informational ranking, not a medical probability.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        return {
            "recommendations": [],
            "note": "No patient records found. Upload documents to get personalised care recommendations.",
        }
    try:
        recs = generate_care_recommendations(
            snapshot["patient_timeline"],
            _enhanced_cross_check(snapshot),
            _lab_trends_for_snapshot(snapshot),
        )
    except Exception as exc:
        logger.error("care recommendations failed for user=%s: %s", user_id, exc, exc_info=True)
        raise HTTPException(500, "Failed to generate care recommendations.")
    return {
        "recommendations": recs,
        "note": "These suggestions are derived from your medical records and are not a diagnosis or referral.",
    }

@app.get("/api/v1/care-recommendations")
async def get_care_recommendations(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return local-care search eligibility from current saved clinical flags.

    This endpoint does not diagnose and does not query a provider directory.
    It only exposes existing high-risk/low-confidence flags so the user can
    select one before providing a city/area and availability preference.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user. Upload and process medical documents first.")
    return recommendation_context(snapshot)


@app.post("/api/v1/care-recommendations/search")
async def search_care_recommendations(
    body: CareProviderSearchRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Search the configured live provider source from the backend only.

    Provider details are returned only when the selected source provides them
    during this request. There are no seeded, cached fallback, or fabricated
    provider records in this application.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user. Upload and process medical documents first.")
    try:
        return await asyncio.to_thread(
            search_live_providers,
            snapshot,
            flag_id=body.flag_id,
            location=body.location.strip(),
            availability=body.availability,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderSearchError as exc:
        return JSONResponse(
            status_code=exc.http_status,
            content={"detail": exc.detail, "code": exc.code, "retryable": exc.retryable},
        )


# ---------------------------------------------------------------------------
# Single-shot Q&A (Phase 1)
# ---------------------------------------------------------------------------

@app.post("/api/v1/qa")
async def qa(body: QARequest, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Answers one question grounded in the authenticated user's indexed
    timeline, with no session/conversation state (caller manages
    chat_history, if any)."""
    try:
        # answer_question() does blocking embedding + LLM I/O. Running it
        # directly in this coroutine stalls the whole event loop, so one slow
        # answer froze every other request (health checks and uploads
        # included). Hand it to a worker thread instead.
        return await asyncio.to_thread(
            answer_question,
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
        # Same reasoning as /qa: query rewriting + retrieval + answering are
        # blocking calls and must not run on the event loop.
        return await asyncio.to_thread(
            conversation.ask, session, body.question, top_k=body.top_k
        )
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
# Find care (specialty suggestion + OpenStreetMap directory)
# ---------------------------------------------------------------------------

def _care_timeline(user_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort record load. Find-care still works without a snapshot."""
    try:
        snapshot = _load_snapshot_or_rebuild(user_id)
    except Exception as exc:
        logger.warning("care finder: could not load snapshot for %s: %s", user_id, exc)
        return None
    return snapshot["patient_timeline"] if snapshot else None


@app.get("/api/v1/care/specialties")
async def list_care_specialties(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Catalogue of specialties the UI can offer, plus a suggestion from
    the caller's saved records when they have any."""
    return care_finder.suggest_specialties(_care_timeline(user_id))


@app.get("/api/v1/care/suggestion")
async def get_care_suggestion(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    return care_finder.suggest_specialties(_care_timeline(user_id))


@app.post("/api/v1/care/search")
async def search_care(
    body: CareSearchRequest, user_id: str = Depends(get_current_user)
) -> Dict[str, Any]:
    """Geocode the user's city and list nearby clinics, doctors, and
    hospitals. Geoapify is primary when GEOAPIFY_API_KEY is set;
    OpenStreetMap (Nominatim + Overpass) is the automatic fallback.
    Ranked by specialty match, opening hours, and distance."""
    return await asyncio.to_thread(
        care_finder.search_care,
        city=body.city,
        specialty_id=body.specialty,
        days=body.days,
        time_of_day=body.time_of_day,
        radius_km=body.radius_km,
        timeline=_care_timeline(user_id),
    )


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

# ---------------------------------------------------------------------------
# Care Navigation (decoupled — does not read the patient record)
# ---------------------------------------------------------------------------


@app.exception_handler(CareNavigationError)
async def care_navigation_error_handler(request: Request, exc: CareNavigationError):
    logger.warning("care navigation %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": str(exc), "code": exc.code},
    )


@app.get("/api/v1/care/facilities")
async def care_facilities(
    location: str = Query(default="", max_length=200),
    kind: str = Query(default="any", max_length=30),
    radius_km: float = Query(default=8.0, ge=1.0, le=50.0),
    latitude: Optional[float] = Query(default=None, ge=-90.0, le=90.0),
    longitude: Optional[float] = Query(default=None, ge=-180.0, le=180.0),
    specialty: Optional[str] = Query(default=None, max_length=80),
    availability: Optional[str] = Query(default=None, max_length=20),
    user_id: str = Depends(get_current_user),
) -> Any:
    """Directory search. Does not read timeline, safety, or labs.

    Map-confirmed clients send latitude/longitude and receive a normalized
    Facility list. The directory needs no API key: it defaults to
    OpenStreetMap/Overpass, and CARE_PROVIDER=google prefers Google Places
    API (New) while falling back to OpenStreetMap on any rejection. Legacy
    clients that only send ``location`` keep the packed OSM/Mapbox payload.
    """
    _ = user_id
    if (latitude is None) != (longitude is None):
        raise HTTPException(400, "latitude and longitude must be provided together.")

    normalized_kind = (kind or "any").strip().lower() or "any"
    allowed_kinds = {"any", "hospital", "clinic", "pharmacy", "laboratory", "lab", "doctor"}
    if normalized_kind not in allowed_kinds and normalized_kind not in FACILITY_KINDS:
        raise HTTPException(400, "Unsupported facility type.")

    # get_care_provider() always resolves to a usable adapter now (keyless
    # OpenStreetMap by default), so a missing/invalid Google key no longer
    # turns a map-confirmed search into a 503.
    try:
        provider = get_care_provider()
    except CareConfigurationError as error:
        if latitude is not None:
            logger.error("care navigation configuration error: %s", error)
            raise HTTPException(
                503,
                "The facility directory is temporarily unavailable. Please try again shortly.",
            ) from error
        provider = None

    if provider is not None:
        if not location.strip() and (latitude is None or longitude is None):
            raise HTTPException(400, "Choose a city/area or provide latitude and longitude.")
        try:
            search_options: Dict[str, Any] = {
                "latitude": latitude,
                "longitude": longitude,
            }
            if specialty and specialty.strip():
                search_options["specialty"] = specialty.strip()
            if availability and availability.strip():
                search_options["availability"] = availability.strip()
            facilities = await asyncio.to_thread(
                provider.search,
                location,
                normalized_kind,
                radius_km,
                **search_options,
            )
            # Enforce the kind and radius promises and remove duplicate
            # listings on the server, regardless of which provider produced
            # the results. A selected 5 km radius must never return a 17 km
            # facility, and a hospital search must never return a laboratory.
            facilities = finalize_facilities(
                facilities,
                radius_km=radius_km,
                latitude=latitude,
                longitude=longitude,
                kind=normalized_kind,
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

    if not location.strip():
        raise HTTPException(400, "Choose a city/area or provide latitude and longitude.")
    chosen = normalized_kind if normalized_kind in FACILITY_KINDS else "any"
    return await asyncio.to_thread(
        get_care_service().search_facilities,
        location=location,
        kind=chosen,
        radius_km=radius_km,
    )


@app.get("/api/v1/care/geocode")
async def care_geocode(q: str, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    _ = user_id
    point = await asyncio.to_thread(get_care_service().geocode, q)
    return {
        "latitude": point.latitude,
        "longitude": point.longitude,
        "label": point.label,
        "provider": point.provider,
    }


@app.get("/api/v1/care/routes")
async def care_routes(
    origin: str,
    destination: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = user_id
    return await asyncio.to_thread(get_care_service().get_route, origin, destination)


@app.get("/api/v1/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "MediMind"}


@app.get("/")
async def root() -> Dict[str, str]:
    return {"service": "MediMind", "status": "ok", "docs": "/docs"}
