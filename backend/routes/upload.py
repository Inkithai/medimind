"""Document upload pipeline — uploads, jobs, corrections, reprocess,
conflicts, document CRUD, signed URLs, analyses, and knowledge-graph
reference uploads.
"""

import asyncio
import hashlib
import logging
import os
import threading

from dotenv import load_dotenv

load_dotenv(override=True)
import re  # noqa: E402
import uuid  # noqa: E402
from datetime import date, datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from tempfile import TemporaryDirectory  # noqa: E402
from typing import Any, Dict, List, Optional, Tuple  # noqa: E402

import jwt  # noqa: E402
from fastapi import (  # noqa: E402
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    Header,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import audit  # noqa: E402
import conversation  # noqa: E402
import db  # noqa: E402
import graph_db  # noqa: E402
import jobs  # noqa: E402
import storage  # noqa: E402
import vector_store  # noqa: E402
from analysis_log import build_extraction_analyses  # noqa: E402
from auth import get_current_user  # noqa: E402
from brand_resolver import resolve_brand_ingredients  # noqa: E402
from document_filter import (  # noqa: E402
    NonMedicalDocumentError,
    assert_medical_document,
    has_medical_content,
)
from document_processing import process_raw_text  # noqa: E402
from document_types import normalize_document_type, summarize_document_types  # noqa: E402
from identity_guard import build_identity_review, check_batch_identity  # noqa: E402
from lab_trends import track_lab_trends  # noqa: E402
from language_guard import (  # noqa: E402
    apply_language_degradation,
    assess_documents_translation_risk,
)
from medical_extractor import (  # noqa: E402
    SKIP_DEMO_DOCUMENTS,
    ProviderRateLimitError,
    _is_demo_document,
    build_patient_timeline,
)
from memory_probe import log_rss  # noqa: E402
from record_trust import (  # noqa: E402
    CorrectionValidationError,
    apply_conflict_quarantine,
    apply_correction_events,
    build_correction_events,
    detect_conflicts,
    merge_conflict_state,
)
from record_trust import (  # noqa: E402
    document_id as trust_document_id,
)
from retrieval import timeline_fingerprint  # noqa: E402
from upload_validation import validate_upload_content  # noqa: E402

logger = logging.getLogger("api.upload")

from routes.records import (  # noqa: E402, F401
    _DOCUMENT_EXECUTOR,
    UPLOAD_FILE_CONCURRENCY,
)

SUPPORTED_EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".webp")

router = APIRouter()

# Concurrent reprocess of the same document used to run two full pipelines
# at once (duplicate LLM spend, racing snapshot writes). Process-local, the
# same constraint FastAPI BackgroundTasks already has.
_active_document_jobs: set = set()
_active_document_jobs_lock = threading.Lock()


def register_document_job(user_id: str, document_id: str) -> bool:
    """Register an in-flight per-document job. False if already running."""
    key = (user_id, document_id)
    with _active_document_jobs_lock:
        if key in _active_document_jobs:
            return False
        _active_document_jobs.add(key)
        return True


def unregister_document_job(user_id: str, document_id: str) -> None:
    with _active_document_jobs_lock:
        _active_document_jobs.discard((user_id, document_id))


def is_document_job_active(user_id: str, document_id: str) -> bool:
    with _active_document_jobs_lock:
        return (user_id, document_id) in _active_document_jobs


def _belongs_to_same_upload(selected: Dict[str, Any]):
    """Match every extracted page of one physical file."""
    content_sha256 = selected.get("content_sha256")
    public_id = selected.get("cloudinary_public_id")
    storage_path = selected.get("storage_path")
    source_file = ((selected.get("_source") or {}).get("file")) or None
    document_id = trust_document_id(selected)

    def belongs(doc: Dict[str, Any]) -> bool:
        if content_sha256:
            return doc.get("content_sha256") == content_sha256
        if public_id:
            return doc.get("cloudinary_public_id") == public_id
        if storage_path:
            return doc.get("storage_path") == storage_path
        if source_file:
            return ((doc.get("_source") or {}).get("file")) == source_file
        return trust_document_id(doc) == document_id

    return belongs


from routes.records import (  # noqa: E402
    _antidote_context,
    _attach_eml_age_safety,
    _cross_check_trusted_timeline,
    _derive_record,
    _openfda_reference_context,
    _prepare_current_trust_state,
    _rebuild_after_document_deletion,
    _replace_index,
    _workspace_has_active_upload,
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


def _should_use_background(request: Request, prefer_header: Optional[str] = None) -> bool:
    """Client can force async via ?async=true or Prefer: respond-async, or server via USE_BACKGROUND_JOBS."""  # noqa: E501
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
                "error": "The server's document-reading model is no longer available. This file was not processed.",  # noqa: E501
                "kind": "transient",
                "code": error.code,
                "retryable": False,
                "retry_after_seconds": error.retry_after_seconds,
            }
        if error.hard_quota:
            return {
                **base,
                "error": "The document-reading service has no available quota right now. This is not a problem with your file.",  # noqa: E501
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
        hard = any(
            marker in text for marker in ("limit: 0", "per day", "daily quota", "quota exhausted")
        )
        return {
            **base,
            "error": (
                "The document-reading service has no available quota right now. This is not a problem with your file."  # noqa: E501
                if hard
                else "The document-reading service is temporarily busy. Please wait a minute before retrying."  # noqa: E501
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
                "error": "We couldn't reliably read this file. Try a clearer, upright image or a higher-resolution scan.",  # noqa: E501
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


def _blocked_file_error(
    capacity_error: Dict[str, Any], file_name: str, file_index: int
) -> Dict[str, Any]:
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
        (
            float(item["retry_after_seconds"])
            for item in file_errors
            if item.get("retry_after_seconds")
        ),
        default=None,
    )
    if "provider_model_unavailable" in codes:
        raise UploadPipelineError(
            502,
            "Document reading is unavailable because the server is configured with an AI model that has been retired. No files were added. Please contact support.",  # noqa: E501
            code="provider_model_unavailable",
            retryable=False,
        )
    if "provider_quota_exhausted" in codes:
        raise UploadPipelineError(
            502,
            "Document reading is temporarily unavailable because the AI service has no usable quota. No files were added, and this is not a problem with your documents. Please try again later or contact support.",  # noqa: E501
            code="provider_quota_exhausted",
            retryable=False,
            retry_after_seconds=retry_after,
        )
    if "provider_rate_limited" in codes:
        wait = f" in about {max(1, round(retry_after))} seconds" if retry_after else " in a minute"
        raise UploadPipelineError(
            502,
            f"The document-reading service reached a temporary rate-limit, so no files were added. Please try again{wait}.",  # noqa: E501
            code="provider_rate_limited",
            retryable=True,
            retry_after_seconds=retry_after,
        )

    kinds = {item.get("kind") for item in file_errors}
    if kinds and kinds <= {"not_medical", "invalid", "unsupported"}:
        # A raised HTTP error has no separate per-file status list beneath it,
        # so the previous "review below" instruction hid the only useful
        # explanation. These error strings are curated user-facing messages
        # (never provider traces); include a bounded set directly in detail.
        reasons = "; ".join(
            f"{item.get('file', 'file')}: {item.get('error', 'no usable content found')}"
            for item in file_errors[:5]
        )
        if len(file_errors) > 5:
            reasons += f"; and {len(file_errors) - 5} more file(s)"
        raise UploadPipelineError(
            422,
            f"We couldn't find readable medical information in any of the "
            f"{total_files} file(s). {reasons}",
            code="no_medical_content",
            retryable=False,
        )
    raise UploadPipelineError(
        502,
        f"We couldn't process any of the {total_files} file(s) because document processing was interrupted. No files were added; please try again.",  # noqa: E501
        code="processing_interrupted",
        retryable=True,
    )


async def _execute_upload_pipeline(
    user_id: str,
    files_data: List[Tuple[str, bytes]],
    job_id: Optional[str] = None,
    confirm_identity_mismatch: bool = False,
) -> Dict[str, Any]:
    """Process child documents independently, then finalize one patient record.

    Extraction work is submitted to a shared bounded executor. Thus separate
    files can be queued/reading/extracting at different times without allowing
    one batch (or several users) to overwhelm the upstream model provider.

    Safety pipeline per file: extract -> medical-relevance filter ->
    language/normalization guard -> identity guard (batch-level, held files
    are excluded unless confirm_identity_mismatch=True). Then batch-level:
    timeline -> cross-check (+ deterministic interaction KB) -> dosage rules
    -> lab trends -> consult triage -> index -> persist.
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
    duplicate_files_skipped: List[Dict[str, Any]] = []
    successfully_saved_files = 0
    # Pages carrying a demo/placeholder marker. They are ADDED like any
    # other; this only records which ones they were.
    demo_documents: List[str] = []

    # Loaded up front (rather than after extraction) so an already-uploaded
    # file can be recognised BEFORE it costs a vision/extraction call.
    # Re-uploading a file this user already sent used to add a SECOND copy of
    # the same document — inflating the timeline, duplicating every
    # medication on it, and skewing the safety evidence. A byte-for-byte
    # content hash catches `CBC_Report.pdf` / `CBC_Report (1).pdf` re-uploads
    # regardless of the new filename. Fail-open: if the document history is
    # unreachable, dedup is skipped and the upload proceeds normally.
    dedup_existing_docs: List[Dict[str, Any]] = []
    try:
        dedup_existing_docs = db.load_documents(user_id) or []
    except Exception as exc:
        logger.warning(
            "upload: user=%s could not load document history for dedup check: %s", user_id, exc
        )
    seen_hashes: Dict[str, Dict[str, Any]] = {
        d["content_sha256"]: d for d in dedup_existing_docs if d.get("content_sha256")
    }
    # sha256 of every file in THIS batch that has already been accepted, so
    # the same file sent twice in one request is only processed once.
    batch_hashes: Dict[str, str] = {}
    # content hash per accepted file index, attached to pages at save time.
    file_hashes: Dict[int, str] = {}

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
                _file_progress(
                    file_index,
                    status="failed",
                    step="failed",
                    message=info["error"],
                    error_info=info,
                )
                continue

            # Magic-byte check: a supported extension whose CONTENT is not
            # actually that file type is rejected per-file (never aborts the
            # batch) before it can cost an extraction call.
            content_error = validate_upload_content(content, original_name)
            if content_error:
                info = {
                    "file": original_name,
                    "file_id": f"file-{file_index}",
                    "file_index": file_index,
                    "error": content_error,
                    "kind": "invalid",
                    "code": "invalid_file_content",
                    "retryable": False,
                    "retry_after_seconds": None,
                }
                file_errors.append(info)
                _file_progress(
                    file_index,
                    status="failed",
                    step="failed",
                    message=info["error"],
                    error_info=info,
                )
                continue

            content_sha256 = hashlib.sha256(content).hexdigest()
            already = seen_hashes.get(content_sha256) or (
                {"_source": {"file": batch_hashes[content_sha256]}}
                if content_sha256 in batch_hashes
                else None
            )
            if already is not None:
                first_seen = already.get("uploaded_at") or "this upload"
                logger.info(
                    "upload: user=%s skipping '%s' — identical file already on file as '%s' (sha256=%s)",  # noqa: E501
                    user_id,
                    original_name,
                    (already.get("_source") or {}).get("file", "unknown"),
                    content_sha256[:12],
                )
                duplicate_files_skipped.append(
                    {
                        "filename": original_name,
                        "reason": "identical_file_already_uploaded",
                        "previously_uploaded_as": (already.get("_source") or {}).get("file"),
                        "previously_uploaded_at": already.get("uploaded_at"),
                        "message": (
                            f"'{original_name}' is byte-for-byte identical to a document "
                            f"already in your records (uploaded {first_seen}), so it was not "
                            "added again. Nothing was lost — the existing copy is still there."
                        ),
                    }
                )
                _file_progress(
                    file_index,
                    status="completed",
                    step="ready",
                    message="Already in your records — duplicate file skipped",
                )
                continue

            batch_hashes[content_sha256] = original_name
            file_hashes[file_index] = content_sha256
            safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(original_name).stem) or "upload"
            tmp_path = Path(tmp_dir) / f"{file_index:03d}_{safe_stem}{suffix}"
            tmp_path.write_bytes(content)
            work_items.append((file_index, original_name, tmp_path))

        # Results are keyed by input index so concurrent workers never reorder
        # the response or mismatch duplicate-looking filenames.
        extracted: Dict[int, Tuple[Path, str, List[Dict[str, Any]], Dict[str, Any]]] = {}
        extraction_errors: Dict[int, Dict[str, Any]] = {}
        # Pages kept despite incomplete drug-name translation, so the response
        # can name the medications that will not take part in cross-checking.
        language_degradations: List[Dict[str, Any]] = []
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
                        _file_progress(
                            file_index,
                            status="failed",
                            step="failed",
                            message=info["error"],
                            error_info=info,
                        )
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
                        raw_text_processing = process_raw_text(str(tmp_path))
                        structured = process_document(
                            str(tmp_path),
                            progress_callback=report_file_step,
                        )
                        return {
                            "structured": structured,
                            "raw_text_processing": raw_text_processing,
                        }

                    try:
                        result_bundle = await loop.run_in_executor(_DOCUMENT_EXECUTOR, run_document)
                        result = (
                            result_bundle.get("structured")
                            if isinstance(result_bundle, dict)
                            else result_bundle
                        )
                        raw_text_processing = (
                            result_bundle.get("raw_text_processing")
                            if isinstance(result_bundle, dict)
                            and isinstance(result_bundle.get("raw_text_processing"), dict)
                            else {}
                        )
                    except NonMedicalDocumentError as exc:
                        info = {
                            "file": original_name,
                            "file_id": f"file-{file_index}",
                            "file_index": file_index,
                            "error": "This doesn't appear to contain medical information we can add.",  # noqa: E501
                            "kind": "not_medical",
                            "code": "not_medical",
                            "retryable": False,
                            "retry_after_seconds": None,
                        }
                        logger.warning(
                            "upload: user=%s rejected '%s': %s", user_id, original_name, exc.reason
                        )
                        extraction_errors[file_index] = info
                        _file_progress(
                            file_index,
                            status="failed",
                            step="failed",
                            message=info["error"],
                            error_info=info,
                        )
                        continue
                    except ProviderRateLimitError as exc:
                        # Expected capacity failures are already fully logged at
                        # the provider boundary. Avoid repeating a multi-page
                        # SDK traceback for every uploaded document.
                        logger.warning(
                            "upload: document provider unavailable for '%s' (code=%s, retry_after=%s)",  # noqa: E501
                            original_name,
                            exc.code,
                            exc.retry_after_seconds,
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
                        capacity_failure = info
                        continue
                    except Exception as exc:
                        logger.error(
                            "upload: user=%s processing failed for '%s': %s",
                            user_id,
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
                    skipped_page_reasons: List[str] = []
                    page_degradations: List[Dict[str, Any]] = []
                    for page_num, page in enumerate(pages, start=1):
                        label = (
                            original_name
                            if len(pages) == 1
                            else f"{original_name} (page {page_num})"
                        )
                        # CLASSIFY, never skip solely for demo marker alone when clinical content present.
                        # Tag demo documents so caller can label/filter them; skipping empty templates
                        # remains an explicit opt-in via SKIP_DEMO_DOCUMENTS.
                        page["is_demo_document"] = _is_demo_document(page)
                        if page["is_demo_document"]:
                            demo_documents.append(label)
                            medical_content_found = has_medical_content(page)
                            if SKIP_DEMO_DOCUMENTS and not medical_content_found:
                                reason = (
                                    f"'{label}' matched a demo/placeholder marker and contained "
                                    "no structured clinical content"
                                )
                                skipped_page_reasons.append(reason)
                                logger.warning(
                                    "upload: user=%s skipped page %s",
                                    user_id,
                                    reason,
                                )
                                continue
                            logger.info(
                                "upload: user=%s '%s' matches a demo/placeholder "
                                "marker — keeping it and tagging it is_demo_document=true "
                                "(medical content present: %s)",
                                user_id,
                                label,
                                has_medical_content(page),
                            )
                        try:
                            assert_medical_document(page, label)
                        except NonMedicalDocumentError as exc:
                            # Skip the non-medical page rather than failing the
                            # whole file: a multi-page PDF with a cover letter,
                            # blank divider, or stray receipt page must not cost
                            # the real clinical pages around it. A single-page
                            # file that fails here ends up with no kept pages
                            # and is rejected as before.
                            reason = f"'{label}' {exc.reason}"
                            skipped_page_reasons.append(reason)
                            logger.warning(
                                "upload: user=%s skipped page %s",
                                user_id,
                                reason,
                            )
                            continue
                        # Deterministic brand -> generic resolution from the
                        # FDA NDC directory BEFORE language degradation: a
                        # Latin-script brand the model could not map to an
                        # ingredient gets its INN filled from the directory,
                        # so it takes part in cross-checking instead of
                        # silently dropping out. Fail-open: no key, no hit, or
                        # a lookup failure leaves the page exactly as
                        # extracted. Non-Latin names are never queried (NDC
                        # brand names are Latin) and remain language_guard's
                        # responsibility.
                        try:
                            ndc_summary = resolve_brand_ingredients(page)
                        except Exception as exc:  # defensive — never block a record on a lookup
                            logger.warning(
                                "upload: user=%s NDC brand resolution failed for '%s': %s",
                                user_id,
                                label,
                                exc,
                            )
                            ndc_summary = {}
                        if ndc_summary.get("resolved"):
                            logger.info(
                                "upload: user=%s NDC resolved %d brand name(s) on '%s': %s",
                                user_id,
                                len(ndc_summary["resolved"]),
                                label,
                                ", ".join(ndc_summary["resolved"]),
                            )
                        # A page whose drug names could not all be normalized
                        # is KEPT at a lowered confidence with the unmatchable
                        # medications marked, instead of failing the whole
                        # file. Rejecting discarded the medications that HAD
                        # resolved; for a photographed non-English
                        # prescription partial translation is the normal
                        # result, so refusing made the common case the failing
                        # case. The gap is now recorded ON the record
                        # (cross_check_eligible=False) rather than implied by
                        # the document's absence from it.
                        degraded = apply_language_degradation(page, label)
                        if degraded["degraded"]:
                            logger.warning(
                                "upload: user=%s accepted '%s' at reduced confidence %.2f "
                                "(languages=%s): %d medication(s) cannot be cross-checked: %s",
                                user_id,
                                label,
                                degraded["confidence"],
                                ", ".join(degraded["languages"]) or "unreported",
                                len(degraded["unmatched_medications"]),
                                "; ".join(degraded["unmatched_medications"]),
                            )
                            page_degradations.append(degraded)
                        if isinstance(page.get("_source"), dict):
                            page["_source"]["file"] = original_name
                        kept_pages.append(page)

                    if not kept_pages:
                        # Every page was non-medical (or the extractor produced
                        # no pages at all). Say what actually happened instead
                        # of guessing a cause: the reasons are per-page, so a
                        # blank/corrupt file is told apart from a folder of
                        # placeholders.
                        detail = "This doesn't appear to contain medical information we can add."
                        if skipped_page_reasons:
                            detail += " " + "; ".join(skipped_page_reasons[:3])
                        info = {
                            "file": original_name,
                            "file_id": f"file-{file_index}",
                            "file_index": file_index,
                            "error": detail,
                            "kind": "not_medical",
                            "code": "not_medical",
                            "retryable": False,
                            "retry_after_seconds": None,
                        }
                        extraction_errors[file_index] = info
                        _file_progress(
                            file_index,
                            status="failed",
                            step="failed",
                            message=info["error"],
                            error_info=info,
                        )
                        continue

                    # Only report degradations for a file that survived the
                    # rest of the checks — a page dropped as non-medical must
                    # not also be announced as "kept with a translation gap".
                    language_degradations.extend(page_degradations)
                    extracted[file_index] = (
                        tmp_path,
                        original_name,
                        kept_pages,
                        raw_text_processing,
                    )
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

        # --- Identity guard (pre-persistence) --------------------------------
        # Compare each extracted file's patient identity against this
        # account's document history (and the batch itself for new accounts).
        # Held files are excluded BEFORE storage/persistence — never silently
        # merged — unless the caller explicitly confirmed the mismatch.
        identity_existing_docs = db.load_documents(user_id)
        # Patient-entered profile data is an additional identity signal, never
        # an override. Represent it in the same comparison shape as history so
        # mismatches are held for confirmation rather than silently merged.
        try:
            profile = db.load_patient_profile(user_id)
        except Exception:
            profile = None  # additive migration may not yet be deployed
        if profile and (profile.get("legal_name") or profile.get("preferred_name")):
            profile_doc: Dict[str, Any] = {
                "patient_name": profile.get("legal_name") or profile.get("preferred_name"),
                "date": date.today().isoformat(),
                "patient_gender": None,
            }
            if profile.get("date_of_birth"):
                try:
                    born = date.fromisoformat(str(profile["date_of_birth"]))
                    today = date.today()
                    profile_doc["patient_age"] = (
                        today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                    )
                except ValueError:
                    pass
            identity_existing_docs.append(profile_doc)
        identity_review: Optional[Dict[str, Any]] = None
        if extracted and not confirm_identity_mismatch:
            _progress("safety", "Checking the documents belong to this record")
            docs_by_file = {
                original_name: kept_pages
                for (_tmp, original_name, kept_pages, _raw_processing) in extracted.values()
            }
            identity_result = check_batch_identity(docs_by_file, identity_existing_docs)
            held = identity_result["held"]
            if held:
                held_files = {f for h in held for f in h["source_files"]}
                for file_index in sorted(extracted):
                    # `extracted` holds 4-tuples (tmp_path, original_name,
                    # kept_pages, raw_text_processing). Unpacking three here
                    # raised ValueError, so every identity-mismatch hold
                    # crashed the whole upload with a 500 instead of
                    # returning the 409 "confirm to add anyway" review.
                    _tmp, original_name, _pages, _raw = extracted[file_index]
                    if original_name in held_files:
                        del extracted[file_index]
                        _file_progress(
                            file_index,
                            status="failed",
                            step="failed",
                            message=(
                                "Held: the patient on this document doesn't match your "
                                "other documents. Confirm to add it anyway."
                            ),
                            error_info={
                                "error": "Patient identity mismatch — document held for confirmation.",  # noqa: E501
                                "code": "identity_mismatch_held",
                                "retryable": True,
                                "retry_after_seconds": None,
                            },
                        )
                identity_review = build_identity_review(held, identity_result["known_identity"])
                logger.warning(
                    "upload: user=%s identity guard held %d file group(s): %s",
                    user_id,
                    len(held),
                    sorted(held_files),
                )
                audit.record(
                    user_id,
                    "documents.identity_held",
                    {
                        "held_files": sorted(held_files),
                        "confirmable": True,
                    },
                )

        # uploaded_at is stamped here (one timestamp for the whole batch)
        # rather than left for db.insert_documents() to set later, because
        # build_patient_timeline() below runs BEFORE that insert — without
        # this, the snapshot saved from THIS request would carry visits
        # with no uploaded_at at all, only gaining one retroactively once
        # a later upload rebuilds the timeline from the now-saved records.
        batch_uploaded_at = db.now_iso()
        # Cloud storage is per-file too: one storage failure should not discard
        # documents that were extracted and saved successfully.
        for file_index in sorted(extracted):
            tmp_path, filename, kept_pages, raw_text_processing = extracted[file_index]
            _file_progress(
                file_index, status="processing", step="saving", message="Saving securely"
            )
            try:
                upload_info = await asyncio.to_thread(
                    storage.upload_patient_document,
                    user_id,
                    str(tmp_path),
                    filename,
                )
            except Exception as exc:
                logger.error(
                    "upload: user=%s secure save failed for '%s': %s",
                    user_id,
                    filename,
                    exc,
                    exc_info=True,
                )
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
                _file_progress(
                    file_index,
                    status="failed",
                    step="failed",
                    message=info["error"],
                    error_info=info,
                )
                continue

            for page in kept_pages:
                # Stable application-level ID keeps old and new documents
                # correctable without exposing storage-provider identifiers.
                page.setdefault("_document_id", f"doc_{uuid.uuid4().hex}")
                page["document_url"] = upload_info["document_url"]
                page["uploaded_at"] = batch_uploaded_at
                page["cloudinary_public_id"] = upload_info.get("cloudinary_public_id")
                page["storage_backend"] = upload_info.get("storage_backend") or "cloudinary"
                if upload_info.get("storage_path"):
                    page["storage_path"] = upload_info.get("storage_path")
                if upload_info.get("storage_bucket"):
                    page["storage_bucket"] = upload_info.get("storage_bucket")
                page["raw_text_processing"] = raw_text_processing
                # Pin the model's free-form type to the closed vocabulary so
                # chunk metadata / evidence weighting downstream are stable.
                page["document_type"] = normalize_document_type(page.get("document_type"))
                # Persisted with the document so a future re-upload of this
                # exact file is recognised before extraction (hash check at
                # the top of this pipeline).
                if file_hashes.get(file_index):
                    page["content_sha256"] = file_hashes[file_index]
                new_docs.append(page)
            successfully_saved_files += 1
            _file_progress(
                file_index,
                status="completed",
                step="ready",
                message="Details extracted and saved",
            )

    if not new_docs:
        if duplicate_files_skipped and not file_errors and not identity_review:
            # Every file in this batch was a byte-for-byte re-upload of a
            # document already on file: nothing to extract, nothing to
            # rebuild. Return the existing record untouched, with the skip
            # list explaining what happened. Not an error — the user's
            # record is exactly as complete as before.
            logger.info(
                "upload: user=%s all %d file(s) were duplicates — nothing added",
                user_id,
                len(duplicate_files_skipped),
            )
            snapshot = None
            try:
                snapshot = db.load_patient_snapshot(user_id)
            except Exception as exc:
                logger.warning(
                    "upload: user=%s snapshot read after all-duplicate batch failed: %s",
                    user_id,
                    exc,
                )
            dup_response: Dict[str, Any] = {
                "user_id": user_id,
                "documents_added": 0,
                "documents_total": len(dedup_existing_docs),
                "files_received": total_files,
                "files_added": 0,
                "timeline": (snapshot or {}).get("patient_timeline") or {},
                "cross_check_report": (snapshot or {}).get("cross_check_report") or {},
                "indexed": True,
                "failed_files": [],
                "duplicate_files_skipped": duplicate_files_skipped,
                "all_files_duplicate": True,
            }
            if snapshot and "lab_trends" in snapshot:
                dup_response["lab_trends"] = snapshot["lab_trends"]
            _progress("ready", "These files are already in your records — nothing was added twice")
            return dup_response
        if identity_review:
            # Every usable file was held by the identity guard: not an
            # extraction failure — surface the review block so the caller can
            # confirm. 409 (conflict) rather than 422: the files are valid,
            # they just don't appear to belong to this record.
            raise UploadPipelineError(
                409,
                identity_review["message"],
                code="identity_mismatch_held",
                retryable=True,
            )
        _raise_no_usable_files(file_errors, total_files)

    _progress("organizing", "Updating your medical history")
    existing_docs = db.load_documents(user_id)
    all_docs = existing_docs + new_docs
    logger.info(
        "upload: user=%s merged documents: +%d new, %d total", user_id, len(new_docs), len(all_docs)
    )

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
            logger.warning(
                "upload: could not load conflict state; using fail-closed unresolved policy: %s",
                exc,
            )
    active_conflicts = merge_conflict_state(detected_conflicts, persisted_conflicts)
    trusted_docs, trust_summary = apply_conflict_quarantine(all_docs, active_conflicts)

    try:
        timeline = build_patient_timeline(trusted_docs)
        timeline["trust_summary"] = trust_summary
        timeline["conflicts"] = active_conflicts
        _progress("safety", "Checking medicines and allergies")
        # Look the medication list up in the WHO antidote reference graph
        # BEFORE cross-checking, so any finding about a drug the graph
        # actually documents can be graded as evidence-backed and cite its
        # source, instead of being capped as unverifiable model recall.
        # Fail-open as always: no graph just means every finding grades as
        # model_knowledge.
        graph_backed_findings, antidote_reference_notes = _antidote_context(
            timeline, user_id, "upload_documents"
        )
        # Warm the openFDA caches (labels + recalls) BEFORE the cross-check so
        # interaction findings can be corroborated by FDA Structured Product
        # Labels and the recall check can match ingredients. Fail-open: a cold
        # cache or a failed fetch just means those findings don't appear,
        # exactly as they did before this feature existed.
        _openfda_reference_context(timeline, user_id, "upload_documents")
        # Safety is another provider call, so it shares the same bounded pool
        # as extraction instead of bypassing load control or blocking polling.
        cross_check = await _cross_check_trusted_timeline(timeline, graph_backed_findings)
        _attach_eml_age_safety(cross_check, timeline, user_id)
    except NonMedicalDocumentError as exc:
        raise UploadPipelineError(422, str(exc), code="not_medical", retryable=False) from exc
    except ProviderRateLimitError as exc:
        if exc.retired_model:
            message = "The files were read, but the safety check uses a retired AI model. Please contact support; the record was not updated."  # noqa: E501
        elif exc.hard_quota:
            message = "The files were read, but the AI service has no quota available for the safety check. Please try again later; the record was not updated."  # noqa: E501
        else:
            message = "The files were read, but the safety service is temporarily busy. Please retry the upload later."  # noqa: E501
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
            "The files were read, but the safety check was interrupted. The record was not updated; please retry.",  # noqa: E501
            code="safety_check_failed",
            retryable=True,
        ) from exc
    except Exception as exc:
        logger.error("upload: user=%s cross-check failed: %s", user_id, exc, exc_info=True)
        raise UploadPipelineError(
            502,
            "The files were read, but the safety check could not finish. The record was not updated; please retry.",  # noqa: E501
            code="safety_check_failed",
            retryable=True,
        ) from exc

    issue_count = sum(len(value) for value in cross_check.values() if isinstance(value, list))
    logger.info(
        "upload: user=%s timeline rebuilt, cross-check found %d issue(s)", user_id, issue_count
    )

    # Attach the reference notes AFTER issue_count is computed so this
    # enrichment list is never counted as safety findings. Persisted with
    # the snapshot so later GET /cross-check reads include it too.
    cross_check["antidote_reference_notes"] = antidote_reference_notes
    lab_trends = track_lab_trends(timeline)
    logger.info(
        "upload: user=%s lab trends: %d trends, %d insufficient",
        user_id,
        len(lab_trends["trends"]),
        len(lab_trends["insufficient_data"]),
    )

    # Deterministic dosage validation (rule table, no LLM) — findings feed
    # the consult triage below and are persisted with the snapshot.
    dosage_report = check_dosages(timeline)
    if dosage_report["findings"]:
        logger.warning(
            "upload: user=%s dosage rules flagged %d finding(s)",
            user_id,
            len(dosage_report["findings"]),
        )

    # Consult triage: deterministic routing of every finding to a
    # pharmacist or doctor with urgency + specialty. Never de-escalates.
    consult_triage_report = generate_consult_triage(
        cross_check, lab_trends, dosage_report, timeline
    )

    # Graded OCR/translation risk banner across the whole record (never blocks).
    translation_risk = assess_documents_translation_risk(all_docs)
    if translation_risk["flag"] != "none":
        logger.warning(
            "upload: user=%s translation risk flag=%s on %d document(s)",
            user_id,
            translation_risk["flag"],
            len(translation_risk["documents"]),
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
    db.save_patient_snapshot(
        user_id,
        timeline,
        cross_check,
        lab_trends=lab_trends,
        dosage_report=dosage_report,
        consult_triage=consult_triage_report,
    )
    audit.record(
        user_id,
        "documents.upload_result",
        {
            "files_received": total_files,
            "files_added": successfully_saved_files,
            "documents_added": len(new_docs),
            "failed_files": len(file_errors),
            "cross_check_issues": issue_count,
        },
    )
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
            index_error = "Extraction succeeded but no medications, lab results, clinical notes, allergies, diagnoses, symptoms, procedures, vital signs, or imaging results were found to index — Q&A has no documents to search yet."  # noqa: E501
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
        "upload: user=%s complete: +%d new pages, %d saved files, %d total pages, indexed=%s, failed=%d",  # noqa: E501
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
        "dosage_report": dosage_report,
        "consult_triage": consult_triage_report,
        "translation_risk": translation_risk,
        "antidote_reference_notes": antidote_reference_notes,
        "document_types": summarize_document_types(all_docs),
        "indexed": indexed,
        "trust_summary": trust_summary,
        "conflicts": active_conflicts,
        "failed_files": sorted(file_errors, key=lambda item: item.get("file_index", 0)),
        # Documents that matched a demo/placeholder marker. They were added
        # normally — this names them so a caller can label or filter them.
        "demo_documents": demo_documents,
        # Present (and non-empty) when a re-uploaded file was recognised and
        # not added a second time.
        "duplicate_files_skipped": duplicate_files_skipped,
        # Non-empty when a document was accepted at reduced confidence
        # because some drug names could not be normalized. Each entry names
        # the file, the medications that cannot be cross-checked, and why.
        "language_degradations": language_degradations,
    }
    if language_degradations:
        logger.info(
            "upload: user=%s accepted %d page(s) with incomplete drug-name translation",
            user_id,
            len(language_degradations),
        )
    if duplicate_files_skipped:
        logger.info(
            "upload: user=%s skipped %d duplicate re-upload(s): %s",
            user_id,
            len(duplicate_files_skipped),
            ", ".join(d["filename"] for d in duplicate_files_skipped),
        )
    if identity_review:
        response["identity_review_needed"] = identity_review
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


@router.post("/api/v1/documents", status_code=201)
async def upload_documents(
    request: Request,
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    user_id: str = Depends(get_current_user),
    prefer: Optional[str] = Header(None, alias="Prefer"),
    confirm_identity_mismatch: bool = Form(False),
) -> Dict[str, Any]:
    """
    Uploads one or more documents (PDF/image) for the authenticated user.
    Supports both sync (201) and async (202) modes:
      - Sync (default): processes immediately and returns UploadResponse
      - Async: when USE_BACKGROUND_JOBS=true or ?async=true or Prefer: respond-async,
        returns 202 {job_id, status} and processes in background. Poll GET /jobs/{id}.

    Identity guard: documents whose extracted patient identity doesn't match
    this account's document history are HELD (not stored, not merged) and
    reported under identity_review_needed. To add held files anyway,
    resubmit just those files with confirm_identity_mismatch=true.
    """
    logger.info("upload_documents: user=%s received %d file(s)", user_id, len(files))
    if not files:
        raise HTTPException(400, "No files were uploaded.")
    audit.record(
        user_id,
        "documents.upload",
        {
            "file_count": len(files),
            "file_names": [Path(f.filename or "").name or "upload" for f in files],
        },
    )

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
                user_id,
                original_name,
                suffix or "(none)",
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
                    progress={
                        "step": "upload",
                        "message": "Files received; assigning processing slots",
                    },
                )
                result = await _execute_upload_pipeline(
                    user_id,
                    files_data,
                    job_id=job_id,
                    confirm_identity_mismatch=confirm_identity_mismatch,
                )
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
                public_message = (
                    exc.detail
                    if isinstance(exc.detail, str)
                    else "Document processing could not finish."
                )
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
                logger.error(
                    "Background job %s failed (HTTP %s): %s",
                    job_id,
                    exc.status_code,
                    public_message,
                )
            except Exception as exc:
                logger.error("Background job %s failed: %s", job_id, exc, exc_info=True)
                public_message = "Document processing stopped unexpectedly. No record was updated; please try again."  # noqa: E501
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
    return await _execute_upload_pipeline(
        user_id,
        files_data,
        confirm_identity_mismatch=confirm_identity_mismatch,
    )


# --- Background Jobs polling ---


@router.get("/api/v1/jobs")
async def list_jobs(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """List recent jobs for the authenticated user (most recent first)."""
    vals = jobs.list_jobs(user_id, limit=20)
    return {"jobs": vals}


@router.get("/api/v1/jobs/{job_id}")
async def get_job(job_id: str, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Poll a background job. Returns 404 if not found or not owned."""
    job = jobs.get_job(job_id, user_id)
    if not job:
        raise HTTPException(404, f"Job '{job_id}' not found.")
    return job


@router.get("/api/v1/corrections")
async def list_corrections(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return the immutable field-level correction audit history."""
    return {"corrections": db.load_correction_events(user_id)}


@router.get("/api/v1/documents/{document_id}/corrections")
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


@router.post("/api/v1/documents/{document_id}/corrections", status_code=201)
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
        timeline, cross_check, lab_trends = await _derive_record(
            trusted, conflicts, trust_summary, user_id
        )
    except CorrectionValidationError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ProviderRateLimitError as exc:
        raise HTTPException(
            503,
            "The correction was not saved because the safety rebuild is temporarily unavailable. Please retry.",  # noqa: E501
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            502, f"The correction was not saved because the record rebuild failed: {exc}"
        ) from exc

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


@router.post("/api/v1/documents/{document_id}/reprocess", status_code=200)
async def reprocess_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Re-runs the full per-document pipeline for one stored document and
    rebuilds every derived representation (timeline, safety, labs, dosage,
    triage, index) from the result.

    This is the recovery path for a document that failed or extracted
    poorly the first time — the original file is fetched from storage and
    re-extracted, so nothing has to be re-uploaded. All rows belonging to
    the same physical file (multi-page documents share its content hash)
    are replaced together, and corrections/conflicts are replayed on the
    rebuild exactly as they are for an upload.
    """
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409,
            "A document upload is still processing. Wait for it to finish before reprocessing.",
        )
    docs = db.load_documents(user_id)
    doc = next((d for d in docs if trust_document_id(d) == document_id), None)
    if doc is None:
        raise HTTPException(404, "Document not found in this workspace.")
    if not register_document_job(user_id, document_id):
        raise HTTPException(
            409,
            "This document is already being reprocessed. Wait for it to finish.",
        )

    try:
        return await _reprocess_document_locked(user_id, document_id, doc)
    finally:
        unregister_document_job(user_id, document_id)


async def _reprocess_document_locked(
    user_id: str, document_id: str, doc: Dict[str, Any]
) -> Dict[str, Any]:
    source_file = ((doc.get("_source") or {}).get("file")) or "document"
    try:
        content = storage.download_original_bytes(doc)
    except storage.StorageDownloadError as exc:
        raise HTTPException(502, str(exc)) from exc

    content_error = validate_upload_content(content, source_file)
    if content_error:
        raise HTTPException(422, content_error)

    try:
        with TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / Path(source_file).name
            tmp_path.write_bytes(content)
            logger.info(
                "reprocess: user=%s document=%s re-extracting '%s'",
                user_id,
                document_id,
                source_file,
            )
            try:
                raw_text_processing = await asyncio.to_thread(process_raw_text, str(tmp_path))
                result = await asyncio.to_thread(process_document, str(tmp_path))
            except NonMedicalDocumentError as exc:
                raise HTTPException(422, str(exc)) from exc
            except ProviderRateLimitError as exc:
                raise HTTPException(
                    503,
                    (
                        "The document-reading service is temporarily unavailable. "
                        "The document was not changed; please retry later."
                    ),
                ) from exc
            except Exception as exc:
                logger.error(
                    "reprocess: user=%s document=%s extraction failed: %s",
                    user_id,
                    document_id,
                    exc,
                    exc_info=True,
                )
                raise HTTPException(
                    502,
                    "The document could not be re-read right now. The stored "
                    "record was not changed; please retry.",
                ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "reprocess: user=%s document=%s failed: %s", user_id, document_id, exc, exc_info=True
        )
        raise HTTPException(500, "Reprocessing failed unexpectedly.") from exc

    pages: List[Dict[str, Any]] = (
        result["pages"] if isinstance(result, dict) and result.get("multi_page") else [result]
    )
    for page in pages:
        page.setdefault("_document_id", doc.get("_document_id"))
        page["document_url"] = doc.get("document_url")
        page["cloudinary_public_id"] = doc.get("cloudinary_public_id")
        page["storage_backend"] = doc.get("storage_backend") or "cloudinary"
        if doc.get("storage_path"):
            page["storage_path"] = doc.get("storage_path")
        if doc.get("storage_bucket"):
            page["storage_bucket"] = doc.get("storage_bucket")
        page["raw_text_processing"] = raw_text_processing
        if doc.get("content_sha256"):
            page["content_sha256"] = doc["content_sha256"]
        page["document_type"] = normalize_document_type(page.get("document_type"))

    replaced = db.replace_document_group(
        user_id,
        content_sha256=doc.get("content_sha256"),
        source_file=source_file,
        pages=pages,
    )
    logger.info(
        "reprocess: user=%s document=%s replaced %d row(s) with %d page(s)",
        user_id,
        document_id,
        replaced,
        len(pages),
    )

    # Rebuild the record exactly as an upload would: conflicts -> quarantine
    # -> timeline -> safety -> labs -> dosage -> triage -> snapshot -> index.
    updated_docs = db.load_documents(user_id)
    trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(
        user_id, updated_docs
    )
    if detected:
        db.sync_conflicts(user_id, detected)
    timeline, cross_check, lab_trends = await _derive_record(
        trusted, conflicts, trust_summary, user_id
    )
    dosage_report = check_dosages(timeline)
    consult_triage_report = generate_consult_triage(
        cross_check, lab_trends, dosage_report, timeline
    )
    timeline["_record_fingerprint"] = timeline_fingerprint(timeline)
    db.save_patient_snapshot(
        user_id,
        timeline,
        cross_check,
        lab_trends=lab_trends,
        dosage_report=dosage_report,
        consult_triage=consult_triage_report,
    )
    indexed, index_error, _ = await _replace_index(user_id, timeline)
    audit.record(
        user_id,
        "documents.reprocessed",
        {
            "document_id": document_id,
            "rows_replaced": replaced,
            "pages": len(pages),
            "indexed": indexed,
        },
    )

    response: Dict[str, Any] = {
        "document_id": document_id,
        "documents_reprocessed": 1,
        "timeline": timeline,
        "cross_check_report": cross_check,
        "lab_trends": lab_trends,
        "dosage_report": dosage_report,
        "consult_triage": consult_triage_report,
        "document_types": summarize_document_types(updated_docs),
        "trust_summary": trust_summary,
        "conflicts": conflicts,
        "indexed": indexed,
    }
    if index_error:
        response["index_error"] = index_error
    return response


@router.get("/api/v1/conflicts")
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
        timeline, cross_check, lab_trends = await _derive_record(
            trusted, conflicts, trust_summary, user_id
        )
    except ProviderRateLimitError as exc:
        raise HTTPException(
            503,
            "The source decision was not saved because the safety rebuild is temporarily unavailable. Please retry.",  # noqa: E501
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            502, f"The source decision was not saved because the record rebuild failed: {exc}"
        ) from exc

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
        saved_conflict if item.get("conflict_id") == conflict_id else item for item in conflicts
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


@router.post("/api/v1/conflicts/{conflict_id}/resolve")
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


@router.post("/api/v1/conflicts/{conflict_id}/reopen")
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


@router.delete("/api/v1/documents/{document_id}")
async def delete_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Permanently delete one uploaded file and rebuild all dependent views."""
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409,
            "A document upload is still processing. Wait for it to finish before deleting a document.",  # noqa: E501
        )
    documents = db.load_documents(user_id)
    selected = next((doc for doc in documents if trust_document_id(doc) == document_id), None)
    if selected is None:
        raise HTTPException(404, "Document not found in this workspace.")

    content_sha256 = selected.get("content_sha256")
    public_id = selected.get("cloudinary_public_id")
    storage_path = selected.get("storage_path")
    source_file = ((selected.get("_source") or {}).get("file")) or None
    belongs_to_upload = _belongs_to_same_upload(selected)

    deleted_group = [doc for doc in documents if belongs_to_upload(doc)]
    remaining = [doc for doc in documents if not belongs_to_upload(doc)]
    document_ids = [trust_document_id(doc) for doc in deleted_group]

    # Remove the original first. If secure storage is unavailable, keep the
    # database and every derived view unchanged so the user can safely retry.
    try:
        await asyncio.to_thread(storage.delete_uploaded_document, selected)
    except storage.StorageDeletionError as exc:
        raise HTTPException(502, str(exc)) from exc

    deleted_rows = db.delete_document_group(
        user_id,
        content_sha256=str(content_sha256) if content_sha256 else None,
        cloudinary_public_id=str(public_id) if public_id else None,
        storage_path=str(storage_path) if storage_path else None,
        source_file=str(source_file) if source_file else None,
        document_id=document_id,
    )
    if not deleted_rows:
        raise HTTPException(
            409, "The document changed before it could be deleted. Refresh and try again."
        )
    db.delete_document_corrections(user_id, document_ids)
    # Stored conversations, completed job payloads, referral trails, and audit
    # details may still quote the deleted source. Clear them rather than leave
    # residual copies that the normal record rebuild cannot rewrite safely.
    db.clear_document_derived_history(user_id)
    jobs.delete_user_jobs(user_id)
    conversation.delete_patient_sessions(user_id)
    rebuild = await _rebuild_after_document_deletion(user_id, remaining)
    audit.record(
        user_id,
        "documents.delete",
        {
            "document_id": document_id,
            "rows_deleted": deleted_rows,
            "documents_remaining": len(remaining),
        },
    )
    return {
        "deleted": True,
        "document_id": document_id,
        "file_name": source_file,
        "pages_deleted": deleted_rows,
        **rebuild,
    }


@router.delete("/api/v1/workspace")
async def delete_workspace(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Permanently erase originals, extracted records, derived data and history."""
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409,
            "A document upload is still processing. Wait for it to finish before deleting the workspace.",  # noqa: E501
        )
    documents = db.load_documents(user_id, include_corrections=False)
    try:
        await asyncio.to_thread(storage.delete_workspace_originals, documents)
    except storage.StorageDeletionError as exc:
        raise HTTPException(502, str(exc)) from exc

    # Clear the configured vector store before the database sweep. If this
    # fails, abort while the durable record still exists so the UI can safely
    # retry instead of reporting an error after deletion already completed.
    await asyncio.to_thread(vector_store.delete_collection, user_id)
    deleted = await asyncio.to_thread(db.delete_workspace_data, user_id)
    # Clear process-local copies after durable deletion succeeds.
    jobs.delete_user_jobs(user_id)
    conversation.delete_patient_sessions(user_id)
    logger.info("workspace permanently deleted: user=%s tables=%s", user_id, sorted(deleted))
    return {"deleted": True}


def _select_document_group(
    user_id: str, document_id: str
) -> Tuple[Dict[str, Any], List[Dict[str, Any]], List[Dict[str, Any]]]:
    documents = db.load_documents(user_id)
    selected = next((doc for doc in documents if trust_document_id(doc) == document_id), None)
    if selected is None:
        raise HTTPException(404, "Document not found in this workspace.")
    belongs = _belongs_to_same_upload(selected)
    group = [doc for doc in documents if belongs(doc)]
    remaining = [doc for doc in documents if not belongs(doc)]
    return selected, group, remaining


def _document_access_token(user_id: str, document_id: str, expires_in_seconds: int) -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise HTTPException(500, "Server misconfigured: JWT_SECRET is not set.")
    now = datetime.now(timezone.utc)
    payload = {
        "purpose": "document_access",
        "user_id": user_id,
        "document_id": document_id,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def _verify_document_access_token(token: str, document_id: str) -> str:
    secret = os.environ.get("JWT_SECRET")
    if not secret:
        raise HTTPException(500, "Server misconfigured: JWT_SECRET is not set.")
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(401, "Document access link has expired.")
    except jwt.InvalidTokenError as exc:
        raise HTTPException(401, f"Invalid document access link: {exc}")
    if (
        payload.get("purpose") != "document_access"
        or str(payload.get("document_id")) != document_id
    ):
        raise HTTPException(401, "Document access link does not match this document.")
    user_id = str(payload.get("user_id") or "")
    if not user_id:
        raise HTTPException(401, "Document access link is missing its owner.")
    return user_id


def _content_type_for_document(doc: Dict[str, Any]) -> str:
    name = str(((doc.get("_source") or {}).get("file")) or "").lower()
    if name.endswith(".pdf"):
        return "application/pdf"
    if name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if name.endswith(".png"):
        return "image/png"
    if name.endswith(".webp"):
        return "image/webp"
    return "application/octet-stream"


@router.post("/api/v1/documents/{document_id}/signed-url")
async def create_document_signed_url(
    document_id: str,
    request: Request,
    expires_in_seconds: int = Query(default=900, ge=60, le=3600),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return a time-limited URL for the original uploaded document.

    Private Supabase-stored documents receive a provider signed URL. Legacy
    Cloudinary documents receive a short-lived MediMind proxy URL so access is
    still time-limited even though their storage URL predates private buckets.
    """
    selected, _group, _remaining = _select_document_group(user_id, document_id)
    expires = max(60, min(int(expires_in_seconds), 3600))
    if selected.get("storage_backend") == "supabase" and selected.get("storage_path"):
        url = storage.create_signed_storage_url(selected, expires)
        mode = "private_storage_signed_url"
    else:
        token = _document_access_token(user_id, document_id, expires)
        url = (
            str(request.url_for("download_signed_document", document_id=document_id))
            + f"?token={token}"
        )
        mode = "medimind_expiring_proxy"
    audit.record(
        user_id,
        "documents.signed_url",
        {"document_id": document_id, "expires_in_seconds": expires, "mode": mode},
    )
    return {"document_id": document_id, "url": url, "expires_in_seconds": expires, "mode": mode}


@router.get("/api/v1/documents/{document_id}/file", name="download_signed_document")
async def download_signed_document(document_id: str, token: str = Query(...)):
    user_id = _verify_document_access_token(token, document_id)
    selected, _group, _remaining = _select_document_group(user_id, document_id)
    try:
        content = await asyncio.to_thread(storage.download_original_bytes, selected)
    except storage.StorageDownloadError as exc:
        raise HTTPException(502, str(exc)) from exc
    filename = (
        Path(str(((selected.get("_source") or {}).get("file")) or "document")).name or "document"
    )
    headers = {"Content-Disposition": f'inline; filename="{filename}"'}
    return Response(content, media_type=_content_type_for_document(selected), headers=headers)


@router.post("/api/v1/documents/{document_id}/process-text")
async def process_document_text_layer(
    document_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Persist or refresh the raw text/OCR processing layer for a document.

    This does not rerun clinical AI extraction. It stores the intermediate raw
    text lifecycle metadata on every extracted page belonging to the physical
    upload so the text layer can be inspected/reused independently.
    """
    selected, group, _remaining = _select_document_group(user_id, document_id)
    source_file = ((selected.get("_source") or {}).get("file")) or "document"
    suffix = Path(source_file).suffix or ".bin"
    try:
        content = await asyncio.to_thread(storage.download_original_bytes, selected)
    except storage.StorageDownloadError as exc:
        raise HTTPException(502, str(exc)) from exc
    from document_processing import process_raw_text

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / ("original" + suffix)
        tmp_path.write_bytes(content)
        raw_processing = await asyncio.to_thread(process_raw_text, str(tmp_path))
    updated_pages = []
    for page in group:
        clone = dict(page)
        clone["raw_text_processing"] = raw_processing
        updated_pages.append(clone)
    replaced = db.replace_document_group(
        user_id,
        content_sha256=str(selected.get("content_sha256"))
        if selected.get("content_sha256")
        else None,
        source_file=str(source_file) if source_file else None,
        pages=updated_pages,
    )
    audit.record(
        user_id,
        "documents.process_text",
        {
            "document_id": document_id,
            "status": raw_processing.get("processing_status"),
            "rows_replaced": replaced,
        },
    )
    return {
        "document_id": document_id,
        "raw_text_processing": raw_processing,
        "rows_updated": len(updated_pages),
    }


@router.get("/api/v1/analyses")
async def list_ai_analyses(
    limit: int = Query(default=50, ge=1, le=200),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Return patient-scoped AI/analysis log cards for extraction and Q&A.

    This is an audit/display surface. It reconstructs extraction entries from
    durable document rows and conversation QA entries from persisted sessions
    where available; it never exposes model chain-of-thought.
    """
    records: List[Dict[str, Any]] = []
    try:
        docs = db.load_documents(user_id)
    except Exception:
        docs = []
    # Documents are persisted one row per extracted PAGE. Emitting one card
    # per row showed a multi-page (or re-extracted) file as several separate
    # extractions of the same document, with its medications and labs counted
    # once per page. build_extraction_analyses() collapses the page rows back
    # into the physical upload they came from — see analysis_log.py.
    records.extend(build_extraction_analyses(docs))

    # Best-effort Q&A log from persisted conversation sessions. Older/local
    # deployments may not have the table; extraction logs still return.
    try:
        rows = (
            db._get_client()
            .table("conversation_sessions")
            .select("session_id, turns, updated_at")
            .eq("user_id", user_id)
            .execute()
            .data
            or []
        )
        for row in rows:
            session_id = str(row.get("session_id") or "")
            turns = list(row.get("turns") or [])
            for idx, turn in enumerate(turns):
                if turn.get("role") != "assistant":
                    continue
                content = str(turn.get("content") or "").strip()
                if not content:
                    continue
                source_files = [
                    str(v) for v in ((turn.get("entities") or {}).get("source_files") or []) if v
                ]
                records.append(
                    {
                        "id": f"qa:{session_id}:{idx}",
                        "analysis_type": "qa",
                        "result": {
                            "paragraphs": [content],
                            "citations": [
                                {
                                    "documentTitle": source,
                                    "document_title": source,
                                    "page": 1,
                                    "quote": "Referenced in the saved answer.",
                                }
                                for source in source_files
                            ],
                            "guidance": "Saved Q&A answer grounded in the uploaded record context.",
                        },
                        "confidence": None,
                        "summary": content[:240],
                        "created_at": turn.get("timestamp") or row.get("updated_at") or "",
                    }
                )
    except Exception as exc:
        logger.info("analysis log: conversation session rows unavailable: %s", exc)

    records.sort(key=lambda item: str(item.get("created_at") or ""), reverse=True)
    return {"analyses": records[:limit], "count": min(len(records), limit), "total": len(records)}


@router.get("/api/v1/documents")
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
        "document_types": summarize_document_types(documents),
    }


@router.post("/api/v1/knowledge-graph/antidotes", status_code=201)
async def upload_antidote_reference(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    Ingests the "Antidotes and other substances used in poisonings"
    section of a WHO Model List of Essential Medicines PDF into the Neo4j
    reference graph. Extraction is deterministic table parsing, so the
    graph holds only what the document literally prints — notably NOT
    which poison each antidote treats, which the source never states.

    Accepts both WHO lists: the main EML (adults) and the EMLc (children).
    Each is stored as its own :SourceDocument, so the two coexist and a
    drug on both keeps a separate listing (and dosage form) per document.
    Which population a PDF covers is read off its own title text.

    Unlike every other route here, what this writes is shared reference
    data, not per-patient data, so it is not scoped by user_id — a valid
    token is still required to keep the write authenticated.
    """
    if not graph_db.is_configured():
        raise HTTPException(
            503,
            "The antidote reference graph is not configured on this server "
            "(NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD missing or the neo4j "
            "driver is not installed).",
        )
    from poisoning_kg import extract_antidote_section, ingest_antidote_entries

    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".pdf":
        raise HTTPException(
            400,
            f"Unsupported file type '{suffix or '(no extension)'}'. "
            "Antidote reference ingestion requires a PDF (table extraction).",
        )

    with TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir) / file.filename
        tmp_path.write_bytes(await file.read())
        logger.info(
            "upload_antidote_reference: user=%s parsing '%s'",
            user_id,
            file.filename,
        )
        try:
            section = extract_antidote_section(str(tmp_path))
        except Exception as e:
            logger.error(
                "upload_antidote_reference: user=%s parse failed for '%s': %s",
                user_id,
                file.filename,
                e,
                exc_info=True,
            )
            raise HTTPException(422, f"Could not parse '{file.filename}': {e}")

    entries = section["entries"]
    if not entries:
        raise HTTPException(
            422,
            f"No 'Antidotes and other substances used in poisonings' section "
            f"found in '{file.filename}'.",
        )

    try:
        count = ingest_antidote_entries(section, source_document=file.filename)
    except Exception as e:
        logger.error(
            "upload_antidote_reference: user=%s ingest failed for '%s': %s",
            user_id,
            file.filename,
            e,
            exc_info=True,
        )
        raise HTTPException(503, f"The reference graph is unreachable: {e}")
    categories = sorted({e["subsection"] for e in entries if e["subsection"]})
    logger.info(
        "upload_antidote_reference: user=%s ingested %d entrie(s) from '%s' (population=%s)",
        user_id,
        count,
        file.filename,
        section["population"],
    )
    audit.record(
        user_id,
        "knowledge_graph.antidotes_ingested",
        {
            "source_document": file.filename,
            "entries_ingested": count,
            "population": section["population"],
        },
    )
    return {
        "source_document": file.filename,
        "population": section["population"],
        "entries_ingested": count,
        "categories": categories,
    }


@router.post("/api/v1/knowledge-graph/essential-medicines", status_code=201)
async def upload_full_essential_medicines_reference(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Parse and idempotently ingest a complete adult/children list."""
    if not graph_db.is_configured():
        raise HTTPException(503, "The reference graph is not configured on this server.")
    if Path(file.filename or "").suffix.lower() != ".pdf":
        raise HTTPException(400, "Full essential-medicines ingestion requires a PDF.")
    from eml_kg import extract_full_list, ingest_full_list

    with TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / (file.filename or "essential-medicines.pdf")
        path.write_bytes(await file.read())
        try:
            parsed = await asyncio.to_thread(extract_full_list, str(path))
        except Exception as exc:
            raise HTTPException(
                422, f"Could not parse the essential-medicines list: {exc}"
            ) from exc
    if not parsed.get("entries"):
        raise HTTPException(422, "No essential-medicine entries were found in this PDF.")
    try:
        counts = await asyncio.to_thread(
            ingest_full_list, parsed, source_document=file.filename or path.name
        )
    except Exception as exc:
        raise HTTPException(503, f"The reference graph is unreachable: {exc}") from exc
    audit.record(
        user_id,
        "knowledge_graph.full_eml_ingested",
        {
            "source_document": file.filename,
            "population": parsed.get("population"),
            **counts,
        },
    )
    return {
        "source_document": file.filename,
        "population": parsed.get("population"),
        "age_restrictions": len(parsed.get("age_restrictions") or []),
        **counts,
    }


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# Tests patch these names on the `api` module; resolve through api at call time.


def process_document(*args, **kwargs):
    import api as _api

    return _api.process_document(*args, **kwargs)


def index_patient_timeline(*args, **kwargs):
    import api as _api

    return _api.index_patient_timeline(*args, **kwargs)


def check_dosages(*args, **kwargs):
    import api as _api

    return _api.check_dosages(*args, **kwargs)


def generate_consult_triage(*args, **kwargs):
    import api as _api

    return _api.generate_consult_triage(*args, **kwargs)
