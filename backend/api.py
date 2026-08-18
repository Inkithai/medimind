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
import hashlib
import logging
import os
from dotenv import load_dotenv
load_dotenv(override=True)
import re
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

import conversation
import db
import jobs
import storage
import vector_store
from care import CareConfigurationError, CareProviderError, get_care_provider
from care.postprocess import finalize as finalize_facilities
from care.recommendation import recommend_care
from care.recommendations import generate_care_recommendations
from care_recommendations import ProviderSearchError, recommendation_context, search_live_providers
from referral_trail import build_referral_search
from document_types import normalize_document_type, summarize_document_types
from upload_validation import validate_upload_content
from auth import get_current_user, issue_anonymous_token
from appointment_prep import build_appointment_prep
from change_detection import detect_record_changes
import audit
import export as export_module
from consult_triage import generate_consult_triage
from document_filter import NonMedicalDocumentError, assert_medical_document
from dosage_rules import check_dosages
from identity_guard import build_identity_review, check_batch_identity
from language_guard import (
    LanguageNormalizationError,
    assert_language_normalized,
    assess_documents_translation_risk,
)
from follow_up import build_follow_up_plan
import graph_db
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
from risk_timeline import build_treatment_windows, concurrent_exposure, risk_calendar
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

    # The WHO antidote reference graph is an enrichment, not core: a missing
    # NEO4J_* var or an unreachable instance must not stop the API from
    # serving documents, timelines, cross-checks or Q&A. The upload read
    # path is already fail-open, so this is the only place Neo4j could take
    # the whole service down — and it cannot.
    if graph_db.is_configured():
        try:
            graph_db.ensure_constraints()
            logger.info("startup: antidote reference graph ready")
        except Exception as e:
            logger.warning(
                "startup: antidote reference graph unavailable, continuing without it "
                "(antidote reference notes will be empty on every upload): %s", e,
            )
    else:
        logger.info("startup: antidote reference graph not configured — skipping")

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


class PatientProfileRequest(BaseModel):
    legal_name: Optional[str] = Field(default=None, max_length=200)
    preferred_name: Optional[str] = Field(default=None, max_length=200)
    date_of_birth: Optional[str] = None
    phone: Optional[str] = Field(default=None, max_length=50)
    emergency_contact: Optional[str] = Field(default=None, max_length=300)
    preferred_language: Optional[str] = Field(default=None, max_length=50)

    @field_validator("date_of_birth")
    @classmethod
    def validate_birth_date(cls, value: Optional[str]) -> Optional[str]:
        if value in (None, ""):
            return None
        from date_convention import sanitize_clinical_date
        cleaned = sanitize_clinical_date(value)
        if cleaned is None or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", cleaned):
            raise ValueError("Date of birth must be a complete YYYY-MM-DD date.")
        parsed = date.fromisoformat(cleaned)
        if parsed > date.today():
            raise ValueError("Date of birth cannot be in the future.")
        return cleaned

    @field_validator("legal_name", "preferred_name", "phone", "emergency_contact", "preferred_language")
    @classmethod
    def trim_optional(cls, value: Optional[str]) -> Optional[str]:
        cleaned = (value or "").strip()
        return cleaned or None


def _empty_cross_check(reason: str) -> Dict[str, Any]:
    return {
        "potential_drug_interactions": [],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
        "overall_recommendation": reason,
        "reference_date": None,
        "medication_activity": {
            "reference_date": None,
            "active_medications": [],
            "inactive_medications": [],
            "active_count": 0,
            "inactive_count": 0,
        },
    }


def _antidote_context(
    timeline: Dict[str, Any], user_id: str, operation: str
) -> Tuple[Dict[str, Dict[str, Any]], List[Dict[str, Any]]]:
    """Best-effort WHO antidote reference-graph lookup for a medication
    timeline. Returns (graph_backed_findings, reference_notes).

    Fail-open by design: an unconfigured, unreachable, or failing graph
    never fails the upload — it just means no reference notes are attached
    and findings grade as model knowledge (the honest default). One round
    trip to the graph per record, reused for both evidence grading and the
    patient-facing reference notes.
    """
    if not graph_db.is_configured():
        logger.debug(
            "%s: user=%s antidote graph not configured (NEO4J_* unset or driver "
            "missing) — skipping reference lookup",
            operation, user_id,
        )
        return {}, []

    from evidence_grading import graph_backed_findings_from_antidotes
    from poisoning_kg import lookup_antidote_references

    med_names = sorted({
        m.get("name") for m in timeline.get("medications_timeline", []) if m.get("name")
    })
    try:
        logger.info(
            "%s: user=%s querying antidote graph for %d medication name(s)",
            operation, user_id, len(med_names),
        )
        references = lookup_antidote_references(med_names)
    except Exception as e:
        # graph_db/poisoning_kg have already logged the failing step and the
        # (redacted) URI; this records that the operation CONTINUED without
        # the enrichment — an empty reference_notes list means "not checked",
        # not "checked and found nothing".
        logger.warning(
            "%s: user=%s antidote reference lookup skipped, continuing without it "
            "(findings will grade as unverified model knowledge): %s",
            operation, user_id, e,
        )
        return {}, []

    notes = [
        {"medication": name, **ref}
        for name, ref in sorted(references.items())
    ]
    if notes:
        logger.info(
            "%s: user=%s antidote graph matched %d of %d medication(s): %s",
            operation, user_id, len(notes), len(med_names),
            ", ".join(n["medication"] for n in notes),
        )
    return graph_backed_findings_from_antidotes(references), notes


def _attach_eml_age_safety(
    cross_check: Dict[str, Any], timeline: Dict[str, Any], user_id: Optional[str] = None
) -> None:
    """Attach full-list age restrictions when the optional graph is populated."""
    if not graph_db.is_configured():
        cross_check.setdefault("eml_age_restrictions", [])
        cross_check.setdefault("eml_age_conflicts", [])
        return
    medication_names = sorted({
        str(ingredient).strip().lower()
        for medication in timeline.get("medications_timeline") or []
        for ingredient in medication.get("ingredients") or []
        if str(ingredient).strip()
    })
    if not medication_names:
        return
    try:
        from eml_kg import lookup_age_restrictions
        from eml_safety import evaluate_age_restrictions, patient_age_from_timeline
        restrictions = lookup_age_restrictions(medication_names)
        age = patient_age_from_timeline(timeline)
        if age is None and user_id:
            try:
                profile = db.load_patient_profile(user_id)
                if profile and profile.get("date_of_birth"):
                    born = date.fromisoformat(str(profile["date_of_birth"]))
                    today = date.today()
                    age = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
            except Exception:
                pass
        cross_check["eml_age_restrictions"] = restrictions
        cross_check["eml_age_conflicts"] = evaluate_age_restrictions(age, restrictions)
    except Exception as exc:
        logger.warning("full EML age lookup skipped: %s", exc)
        cross_check.setdefault("eml_age_restrictions", [])
        cross_check.setdefault("eml_age_conflicts", [])


async def _cross_check_trusted_timeline(
    timeline: Dict[str, Any],
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    if not timeline.get("medications_timeline"):
        return _empty_cross_check(
            "No trusted medication facts are currently available for safety analysis. "
            "Resolve quarantined conflicts and consult a doctor or pharmacist before making changes."
        )
    def _run() -> Dict[str, Any]:
        return cross_check_prescriptions(timeline, graph_backed_findings=graph_backed_findings)

    return await asyncio.get_running_loop().run_in_executor(_DOCUMENT_EXECUTOR, _run)


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
# Patient profile and normalized clinical entities
# ---------------------------------------------------------------------------

@app.get("/api/v1/profile")
async def get_patient_profile(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    profile = db.load_patient_profile(user_id)
    return profile or {
        "user_id": user_id, "legal_name": None, "preferred_name": None,
        "date_of_birth": None, "phone": None, "emergency_contact": None,
        "preferred_language": None, "updated_at": None,
    }


@app.put("/api/v1/profile")
async def update_patient_profile(
    request: PatientProfileRequest,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    profile = db.save_patient_profile(user_id, request.model_dump())
    audit.record(user_id, "profile.updated", {
        "fields": sorted(key for key, value in request.model_dump().items() if value is not None),
    })
    return profile


@app.get("/api/v1/clinical-entities/{kind}")
async def get_clinical_entities(
    kind: Literal[
        "clinical_medications", "clinical_prescriptions", "clinical_allergies",
        "clinical_lab_results", "clinical_events", "safety_findings",
    ],
    limit: int = Query(default=500, ge=1, le=1000),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    rows = db.load_clinical_entities(user_id, kind, limit)
    return {"kind": kind, "count": len(rows), "items": rows}


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
        logger.warning("upload: user=%s could not load document history for dedup check: %s", user_id, exc)
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
                _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
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
                _file_progress(file_index, status="failed", step="failed", message=info["error"], error_info=info)
                continue

            content_sha256 = hashlib.sha256(content).hexdigest()
            already = seen_hashes.get(content_sha256) or (
                {"_source": {"file": batch_hashes[content_sha256]}}
                if content_sha256 in batch_hashes else None
            )
            if already is not None:
                first_seen = already.get("uploaded_at") or "this upload"
                logger.info(
                    "upload: user=%s skipping '%s' — identical file already on file as '%s' (sha256=%s)",
                    user_id, original_name, (already.get("_source") or {}).get("file", "unknown"), content_sha256[:12],
                )
                duplicate_files_skipped.append({
                    "filename": original_name,
                    "reason": "identical_file_already_uploaded",
                    "previously_uploaded_as": (already.get("_source") or {}).get("file"),
                    "previously_uploaded_at": already.get("uploaded_at"),
                    "message": (
                        f"'{original_name}' is byte-for-byte identical to a document "
                        f"already in your records (uploaded {first_seen}), so it was not "
                        "added again. Nothing was lost — the existing copy is still there."
                    ),
                })
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
                        # sitting behind another upload job. The first progress
                        # event (reading/"Opening and checking the document") is
                        # emitted by process_document() itself — emitting it here
                        # too used to duplicate the jobs-table write and the log
                        # line for every file.
                        logger.info(
                            "upload: user=%s processing '%s' (%d/%d)",
                            user_id,
                            original_name,
                            file_index,
                            total_files,
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
                    language_rejected_info: Optional[Dict[str, Any]] = None
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
                        try:
                            assert_language_normalized(page, label)
                        except LanguageNormalizationError as exc:
                            logger.warning(
                                "upload: user=%s language guard rejected '%s': %s",
                                user_id, original_name, exc.reason,
                            )
                            language_rejected_info = {
                                "file": original_name,
                                "file_id": f"file-{file_index}",
                                "file_index": file_index,
                                "error": str(exc),
                                "kind": "language_normalization",
                                "code": "language_normalization_failed",
                                "retryable": False,
                                "retry_after_seconds": None,
                            }
                            rejected = True
                            break
                        if isinstance(page.get("_source"), dict):
                            page["_source"]["file"] = original_name
                        kept_pages.append(page)

                    if rejected or not kept_pages:
                        # The language guard produces a specific, actionable
                        # error; the generic not-medical message covers the rest.
                        info = language_rejected_info or {
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
                    profile_doc["patient_age"] = today.year - born.year - ((today.month, today.day) < (born.month, born.day))
                except ValueError:
                    pass
            identity_existing_docs.append(profile_doc)
        identity_review: Optional[Dict[str, Any]] = None
        if extracted and not confirm_identity_mismatch:
            _progress("safety", "Checking the documents belong to this record")
            docs_by_file = {
                original_name: kept_pages
                for (_tmp, original_name, kept_pages) in extracted.values()
            }
            identity_result = check_batch_identity(docs_by_file, identity_existing_docs)
            held = identity_result["held"]
            if held:
                held_files = {f for h in held for f in h["source_files"]}
                for file_index in sorted(extracted):
                    _tmp, original_name, _pages = extracted[file_index]
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
                                "error": "Patient identity mismatch — document held for confirmation.",
                                "code": "identity_mismatch_held",
                                "retryable": True,
                                "retry_after_seconds": None,
                            },
                        )
                identity_review = build_identity_review(held, identity_result["known_identity"])
                logger.warning(
                    "upload: user=%s identity guard held %d file group(s): %s",
                    user_id, len(held), sorted(held_files),
                )
                audit.record(user_id, "documents.identity_held", {
                    "held_files": sorted(held_files),
                    "confirmable": True,
                })

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
                user_id, len(duplicate_files_skipped),
            )
            snapshot = None
            try:
                snapshot = db.load_patient_snapshot(user_id)
            except Exception as exc:
                logger.warning("upload: user=%s snapshot read after all-duplicate batch failed: %s", user_id, exc)
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
        # Look the medication list up in the WHO antidote reference graph
        # BEFORE cross-checking, so any finding about a drug the graph
        # actually documents can be graded as evidence-backed and cite its
        # source, instead of being capped as unverifiable model recall.
        # Fail-open as always: no graph just means every finding grades as
        # model_knowledge.
        graph_backed_findings, antidote_reference_notes = _antidote_context(
            timeline, user_id, "upload_documents"
        )
        # Safety is another provider call, so it shares the same bounded pool
        # as extraction instead of bypassing load control or blocking polling.
        cross_check = await _cross_check_trusted_timeline(timeline, graph_backed_findings)
        _attach_eml_age_safety(cross_check, timeline, user_id)
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
            user_id, len(dosage_report["findings"]),
        )

    # Consult triage: deterministic routing of every finding to a
    # pharmacist or doctor with urgency + specialty. Never de-escalates.
    consult_triage_report = generate_consult_triage(cross_check, lab_trends, dosage_report, timeline)

    # Graded OCR/translation risk banner across the whole record (never blocks).
    translation_risk = assess_documents_translation_risk(all_docs)
    if translation_risk["flag"] != "none":
        logger.warning(
            "upload: user=%s translation risk flag=%s on %d document(s)",
            user_id, translation_risk["flag"], len(translation_risk["documents"]),
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
        user_id, timeline, cross_check, lab_trends=lab_trends,
        dosage_report=dosage_report, consult_triage=consult_triage_report,
    )
    audit.record(user_id, "documents.upload_result", {
        "files_received": total_files,
        "files_added": successfully_saved_files,
        "documents_added": len(new_docs),
        "failed_files": len(file_errors),
        "cross_check_issues": issue_count,
    })
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
            index_error = "Extraction succeeded but no medications, lab results, clinical notes, allergies, diagnoses, symptoms, procedures, vital signs, or imaging results were found to index — Q&A has no documents to search yet."
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
        "dosage_report": dosage_report,
        "consult_triage": consult_triage_report,
        "translation_risk": translation_risk,
        "antidote_reference_notes": antidote_reference_notes,
        "document_types": summarize_document_types(all_docs),
        "indexed": indexed,
        "trust_summary": trust_summary,
        "conflicts": active_conflicts,
        "failed_files": sorted(file_errors, key=lambda item: item.get("file_index", 0)),
        # Present (and non-empty) when a re-uploaded file was recognised and
        # not added a second time.
        "duplicate_files_skipped": duplicate_files_skipped,
    }
    if duplicate_files_skipped:
        logger.info(
            "upload: user=%s skipped %d duplicate re-upload(s): %s",
            user_id, len(duplicate_files_skipped),
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


@app.post("/api/v1/documents", status_code=201)
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
    audit.record(user_id, "documents.upload", {
        "file_count": len(files),
        "file_names": [Path(f.filename or "").name or "upload" for f in files],
    })

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
                result = await _execute_upload_pipeline(
                    user_id, files_data, job_id=job_id,
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
    return await _execute_upload_pipeline(
        user_id, files_data, confirm_identity_mismatch=confirm_identity_mismatch,
    )


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
        timeline, cross_check, lab_trends = await _derive_record(trusted, conflicts, trust_summary, user_id)
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


@app.post("/api/v1/documents/{document_id}/reprocess", status_code=200)
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
    docs = db.load_documents(user_id)
    doc = next((d for d in docs if trust_document_id(d) == document_id), None)
    if doc is None:
        raise HTTPException(404, "Document not found in this workspace.")

    source_file = ((doc.get("_source") or {}).get("file")) or "document"
    try:
        content = storage.download_document_bytes(doc)
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
                user_id, document_id, source_file,
            )
            try:
                result = await asyncio.to_thread(process_document, str(tmp_path))
            except NonMedicalDocumentError as exc:
                raise HTTPException(422, str(exc)) from exc
            except ProviderRateLimitError as exc:
                raise HTTPException(503, (
                    "The document-reading service is temporarily unavailable. "
                    "The document was not changed; please retry later."
                )) from exc
            except Exception as exc:
                logger.error(
                    "reprocess: user=%s document=%s extraction failed: %s",
                    user_id, document_id, exc, exc_info=True,
                )
                raise HTTPException(
                    502,
                    "The document could not be re-read right now. The stored "
                    "record was not changed; please retry.",
                ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("reprocess: user=%s document=%s failed: %s", user_id, document_id, exc, exc_info=True)
        raise HTTPException(500, "Reprocessing failed unexpectedly.") from exc

    pages: List[Dict[str, Any]] = (
        result["pages"] if isinstance(result, dict) and result.get("multi_page") else [result]
    )
    for page in pages:
        page.setdefault("_document_id", doc.get("_document_id"))
        page["document_url"] = doc.get("document_url")
        page["cloudinary_public_id"] = doc.get("cloudinary_public_id")
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
        user_id, document_id, replaced, len(pages),
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
    consult_triage_report = generate_consult_triage(cross_check, lab_trends, dosage_report, timeline)
    timeline["_record_fingerprint"] = timeline_fingerprint(timeline)
    db.save_patient_snapshot(
        user_id, timeline, cross_check, lab_trends=lab_trends,
        dosage_report=dosage_report, consult_triage=consult_triage_report,
    )
    indexed, index_error, _ = await _replace_index(user_id, timeline)
    audit.record(user_id, "documents.reprocessed", {
        "document_id": document_id,
        "rows_replaced": replaced,
        "pages": len(pages),
        "indexed": indexed,
    })

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
        timeline, cross_check, lab_trends = await _derive_record(trusted, conflicts, trust_summary, user_id)
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
    user_id: str,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    timeline = _timeline_from_trust_state(trusted_docs, conflicts, trust_summary)
    graph_backed_findings, antidote_reference_notes = _antidote_context(
        timeline, user_id, "record_rebuild"
    )
    cross_check = await _cross_check_trusted_timeline(timeline, graph_backed_findings)
    _attach_eml_age_safety(cross_check, timeline, user_id)
    cross_check["antidote_reference_notes"] = antidote_reference_notes
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




async def _rebuild_after_document_deletion(
    user_id: str,
    remaining_documents: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Replace every derived view without retaining facts from a deleted source."""
    db.clear_conflict_history(user_id)
    if not remaining_documents:
        db.delete_patient_snapshot(user_id)
        await asyncio.to_thread(vector_store.delete_collection, user_id)
        return {
            "documents_remaining": 0,
            "timeline": None,
            "indexed": True,
            "index_error": None,
        }

    trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(
        user_id, remaining_documents
    )
    persisted_conflicts = db.sync_conflicts(user_id, detected) if detected else []
    # Re-run the complete safety pipeline immediately. Deletion must remove
    # findings that depended on the deleted source without leaving the
    # remaining medication record temporarily unchecked.
    timeline, cross_check, lab_trends = await _derive_record(
        trusted, persisted_conflicts, trust_summary, user_id
    )
    dosage_report = check_dosages(timeline)
    consult_triage_report = generate_consult_triage(cross_check, lab_trends, dosage_report, timeline)
    db.save_patient_snapshot(
        user_id,
        timeline,
        cross_check,
        lab_trends=lab_trends,
        dosage_report=dosage_report,
        consult_triage=consult_triage_report,
    )
    indexed, index_error, _ = await _replace_index(user_id, timeline)
    return {
        "documents_remaining": len(remaining_documents),
        "timeline": timeline,
        "indexed": indexed,
        "index_error": index_error,
    }


def _workspace_has_active_upload(user_id: str) -> bool:
    return any(
        job.get("status") in {"pending", "processing"}
        for job in jobs.list_jobs(user_id, limit=100)
    )


@app.delete("/api/v1/documents/{document_id}")
async def delete_document(
    document_id: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Permanently delete one uploaded file and rebuild all dependent views."""
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409,
            "A document upload is still processing. Wait for it to finish before deleting a document.",
        )
    documents = db.load_documents(user_id)
    selected = next((doc for doc in documents if trust_document_id(doc) == document_id), None)
    if selected is None:
        raise HTTPException(404, "Document not found in this workspace.")

    content_sha256 = selected.get("content_sha256")
    public_id = selected.get("cloudinary_public_id")
    source_file = ((selected.get("_source") or {}).get("file")) or None

    def belongs_to_upload(doc: Dict[str, Any]) -> bool:
        if content_sha256:
            return doc.get("content_sha256") == content_sha256
        if public_id:
            return doc.get("cloudinary_public_id") == public_id
        if source_file:
            return ((doc.get("_source") or {}).get("file")) == source_file
        return trust_document_id(doc) == document_id

    deleted_group = [doc for doc in documents if belongs_to_upload(doc)]
    remaining = [doc for doc in documents if not belongs_to_upload(doc)]
    document_ids = [trust_document_id(doc) for doc in deleted_group]

    # Remove the original first. If secure storage is unavailable, keep the
    # database and every derived view unchanged so the user can safely retry.
    try:
        await asyncio.to_thread(storage.delete_patient_document, str(public_id or ""))
    except storage.StorageDeletionError as exc:
        raise HTTPException(502, str(exc)) from exc

    deleted_rows = db.delete_document_group(
        user_id,
        content_sha256=str(content_sha256) if content_sha256 else None,
        cloudinary_public_id=str(public_id) if public_id else None,
        source_file=str(source_file) if source_file else None,
        document_id=document_id,
    )
    if not deleted_rows:
        raise HTTPException(409, "The document changed before it could be deleted. Refresh and try again.")
    db.delete_document_corrections(user_id, document_ids)
    # Stored conversations, completed job payloads, referral trails, and audit
    # details may still quote the deleted source. Clear them rather than leave
    # residual copies that the normal record rebuild cannot rewrite safely.
    db.clear_document_derived_history(user_id)
    jobs.delete_user_jobs(user_id)
    conversation.delete_patient_sessions(user_id)
    rebuild = await _rebuild_after_document_deletion(user_id, remaining)
    audit.record(user_id, "documents.delete", {
        "document_id": document_id,
        "rows_deleted": deleted_rows,
        "documents_remaining": len(remaining),
    })
    return {
        "deleted": True,
        "document_id": document_id,
        "file_name": source_file,
        "pages_deleted": deleted_rows,
        **rebuild,
    }


@app.delete("/api/v1/workspace")
async def delete_workspace(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Permanently erase originals, extracted records, derived data and history."""
    if _workspace_has_active_upload(user_id):
        raise HTTPException(
            409,
            "A document upload is still processing. Wait for it to finish before deleting the workspace.",
        )
    documents = db.load_documents(user_id, include_corrections=False)
    public_ids = [doc.get("cloudinary_public_id") for doc in documents]
    try:
        await asyncio.to_thread(storage.delete_workspace_documents, public_ids)
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
        "document_types": summarize_document_types(documents),
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
    "reference_date": None,
    "medication_activity": {
        "reference_date": None,
        "active_medications": [],
        "inactive_medications": [],
        "active_count": 0,
        "inactive_count": 0,
    },
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
    from medication_activity import analyze_medication_activity

    timeline = snapshot["patient_timeline"]
    report = dict(snapshot.get("cross_check_report") or {})
    report.setdefault("potential_drug_interactions", [])
    report.setdefault("duplicate_prescriptions", [])
    report.setdefault("conflicting_dosage_instructions", [])
    report.setdefault("allergy_conflicts", [])
    transitions = detect_medication_transitions(timeline)
    report.setdefault("medication_changes", transitions["medication_changes"])
    report.setdefault("medication_continuations", transitions["medication_continuations"])
    # Snapshots saved before activity scoping exist: backfill the
    # deterministic active/inactive classification on read (no LLM call)
    # so every stored record gets reference-date awareness.
    if "medication_activity" not in report:
        activity = analyze_medication_activity(timeline)
        report["medication_activity"] = activity
        report["reference_date"] = activity["reference_date"]
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


@app.post("/api/v1/medication-safety/reanalyze")
async def reanalyze_medication_safety(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Re-run and persist the complete safety/triage pipeline on demand.

    Uses the corrected, conflict-filtered durable documents rather than a
    potentially stale snapshot. The response includes before/after counts so
    clients can explain whether findings were added or resolved.
    """
    if _workspace_has_active_upload(user_id):
        raise HTTPException(409, "Wait for the active upload to finish before re-running safety analysis.")
    documents = db.load_documents(user_id)
    if not documents:
        raise HTTPException(404, "No documents are available for safety analysis.")

    previous = db.load_patient_snapshot(user_id) or {}
    previous_cross_check = previous.get("cross_check_report") or {}
    trusted, conflicts, trust_summary, detected = _prepare_current_trust_state(user_id, documents)
    if detected:
        conflicts = db.sync_conflicts(user_id, detected)
    timeline, cross_check, lab_trends = await _derive_record(
        trusted, conflicts, trust_summary, user_id
    )
    dosage_report = check_dosages(timeline)
    triage = generate_consult_triage(
        cross_check, lab_trends, dosage_report, timeline
    )
    reconciliation = db.save_patient_snapshot(
        user_id, timeline, cross_check, lab_trends=lab_trends,
        dosage_report=dosage_report, consult_triage=triage,
    ) or {"available": False, "tables": {}}
    indexed, index_error, indexed_chunks = await _replace_index(user_id, timeline)

    finding_lists = (
        "potential_drug_interactions", "duplicate_prescriptions",
        "conflicting_dosage_instructions", "allergy_conflicts",
        "guideline_flagged_combinations", "concurrent_exposure", "eml_age_conflicts",
    )
    count = lambda report: sum(len(report.get(key) or []) for key in finding_lists)
    before_count = count(previous_cross_check)
    after_count = count(cross_check)
    audit.record(user_id, "medication_safety.reanalyzed", {
        "findings_before": before_count,
        "findings_after": after_count,
        "indexed": indexed,
    })
    return {
        "reanalyzed": True,
        "findings_before": before_count,
        "findings_after": after_count,
        "net_change": after_count - before_count,
        "resolved_count": max(0, before_count - after_count),
        "finding_reconciliation": reconciliation.get("safety_findings", {}),
        "normalized_projection": reconciliation,
        "cross_check_report": cross_check,
        "dosage_report": dosage_report,
        "consult_triage": triage,
        "indexed": indexed,
        "indexed_chunks": indexed_chunks,
        "index_error": index_error,
    }


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


@app.get("/api/v1/risk-timeline")
async def get_risk_timeline(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns this user's safety findings placed in time — a chronological
    risk view of the record: which risks were live during which dates, most
    recent period first, plus any period where two prescriptions supplied the
    same ingredient at once (double-dosing arithmetic).

    Two drugs only interact if they were taken together, so findings whose
    courses never overlapped are grouped separately as history rather than
    presented as current risks. Every finding also carries its evidence
    grade (deterministic vs model knowledge). Computed from the printed
    prescription dates and durations — no model call.

    For snapshots saved before timing/grading existed, the report is
    re-annotated on the fly from the saved timeline."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")

    timeline = snapshot.get("patient_timeline") or {}
    cross_check = dict(snapshot.get("cross_check_report") or {})

    # Backward compat: older snapshots carry findings with no timing/grading.
    if cross_check and "timing_summary" not in cross_check:
        from risk_timeline import annotate_findings_with_timing
        annotate_findings_with_timing(cross_check, timeline)
    if cross_check and "evidence_summary" not in cross_check:
        from evidence_grading import grade_cross_check
        grade_cross_check(cross_check)
    if "concurrent_exposure" not in cross_check:
        cross_check["concurrent_exposure"] = concurrent_exposure(timeline)

    return {
        "calendar": risk_calendar(cross_check, timeline),
        "concurrent_exposure": cross_check.get("concurrent_exposure") or [],
        "treatment_windows": [
            {**w, "start": w["start"].isoformat() if w["start"] else None,
             "end": w["end"].isoformat() if w["end"] else None}
            for w in build_treatment_windows(timeline)
        ],
        "timing_summary": cross_check.get("timing_summary") or {},
        "evidence_summary": cross_check.get("evidence_summary") or {},
    }


@app.get("/api/v1/consult-triage")
async def get_consult_triage(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns who this user should talk to about what the pipeline found —
    a pharmacist or a doctor, how soon, with what confidence, and for a
    doctor, which specialty. Deterministic routing over the saved
    cross-check, dosage findings, and lab trends (see consult_triage.py);
    recomputed on the fly for snapshots saved before this feature existed.

    Safety properties: never de-escalates (consult_needed=false means "no
    trigger found", not "you're fine") and low confidence never lowers
    urgency."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    if "consult_triage" in snapshot:
        audit.record(user_id, "records.read", {"view": "consult_triage"})
        return snapshot["consult_triage"]
    lab_trends = _lab_trends_for_snapshot(snapshot)
    dosage_report = snapshot.get("dosage_report") or check_dosages(snapshot["patient_timeline"])
    result = generate_consult_triage(snapshot["cross_check_report"], lab_trends, dosage_report, snapshot["patient_timeline"])
    audit.record(user_id, "records.read", {"view": "consult_triage", "recomputed": True})
    return result


@app.get("/api/v1/dosage-report")
async def get_dosage_report(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns the deterministic dosage validation report — each medication's
    normalized dose checked against published adult limits (dosage_rules.py).
    Recomputed on the fly for snapshots saved before this feature existed."""
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No records found for this user.")
    if "dosage_report" in snapshot:
        audit.record(user_id, "records.read", {"view": "dosage_report"})
        return snapshot["dosage_report"]
    result = check_dosages(snapshot["patient_timeline"])
    audit.record(user_id, "records.read", {"view": "dosage_report", "recomputed": True})
    return result


# ---------------------------------------------------------------------------
# Reference knowledge graph (Neo4j) — WHO antidote reference data
# ---------------------------------------------------------------------------

@app.post("/api/v1/knowledge-graph/antidotes", status_code=201)
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
            "upload_antidote_reference: user=%s parsing '%s'", user_id, file.filename,
        )
        try:
            section = extract_antidote_section(str(tmp_path))
        except Exception as e:
            logger.error(
                "upload_antidote_reference: user=%s parse failed for '%s': %s",
                user_id, file.filename, e, exc_info=True,
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
            user_id, file.filename, e, exc_info=True,
        )
        raise HTTPException(503, f"The reference graph is unreachable: {e}")
    categories = sorted({e["subsection"] for e in entries if e["subsection"]})
    logger.info(
        "upload_antidote_reference: user=%s ingested %d entrie(s) from '%s' (population=%s)",
        user_id, count, file.filename, section["population"],
    )
    audit.record(user_id, "knowledge_graph.antidotes_ingested", {
        "source_document": file.filename,
        "entries_ingested": count,
        "population": section["population"],
    })
    return {
        "source_document": file.filename,
        "population": section["population"],
        "entries_ingested": count,
        "categories": categories,
    }


@app.post("/api/v1/knowledge-graph/essential-medicines", status_code=201)
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
            raise HTTPException(422, f"Could not parse the essential-medicines list: {exc}") from exc
    if not parsed.get("entries"):
        raise HTTPException(422, "No essential-medicine entries were found in this PDF.")
    try:
        counts = await asyncio.to_thread(
            ingest_full_list, parsed, source_document=file.filename or path.name
        )
    except Exception as exc:
        raise HTTPException(503, f"The reference graph is unreachable: {exc}") from exc
    audit.record(user_id, "knowledge_graph.full_eml_ingested", {
        "source_document": file.filename,
        "population": parsed.get("population"),
        **counts,
    })
    return {
        "source_document": file.filename,
        "population": parsed.get("population"),
        "age_restrictions": len(parsed.get("age_restrictions") or []),
        **counts,
    }


@app.get("/api/v1/export")
async def export_record(
    format: str = Query("json", description="Export format: 'json' (native, lossless) or 'fhir' (FHIR R4 Bundle)"),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Exports the authenticated user's assembled record for portability.

    - format=json: the complete MediMind-native snapshot (timeline +
      cross-check + lab trends) in a self-describing envelope.
    - format=fhir: a FHIR R4 collection Bundle (Patient,
      MedicationStatement, Observation, AllergyIntolerance, Provenance)
      mapping the portable core of the record onto standard resources for
      hand-off to other health systems.

    404s if the user has never been processed. Deterministic — no LLM calls.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user — upload documents first.")
    if "lab_trends" not in snapshot:
        snapshot = {**snapshot, "lab_trends": _lab_trends_for_snapshot(snapshot)}
    try:
        result = export_module.build_export(user_id, snapshot, format)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record(user_id, "records.export", {"format": format.strip().lower()})
    return result


@app.get("/api/v1/export/validation")
async def validate_record_export(
    format: str = Query("fhir", description="Validation format; currently only 'fhir' is supported"),
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    """Generate and validate the authenticated user's FHIR export.

    This is a deterministic local structural R4 check, not a substitute for
    the HL7 Java validator. It is exposed separately so the exported Bundle
    remains valid FHIR JSON without application metadata added to it.
    """
    if format.strip().lower() != "fhir":
        raise HTTPException(400, "Validation currently supports only format=fhir.")
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user — upload documents first.")
    bundle = export_module.build_fhir_bundle(user_id, snapshot)
    report = export_module.validate_fhir_bundle(bundle)
    report["format"] = "fhir"
    report["bundle_type"] = bundle.get("type")
    audit.record(user_id, "records.export_validation", {"format": "fhir", "valid": report["valid"]})
    return report


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
    # Derived safety reports — recomputed for pre-feature snapshots so the
    # dashboard always has them.
    result["dosage_report"] = snapshot.get("dosage_report") or check_dosages(snapshot["patient_timeline"])
    result["consult_triage"] = snapshot.get("consult_triage") or generate_consult_triage(
        snapshot["cross_check_report"], result["lab_trends"], result["dosage_report"],
        snapshot["patient_timeline"],
    )
    try:
        result["patient_profile"] = db.load_patient_profile(user_id)
    except Exception:
        # Profile storage is additive; an older deployment must still serve
        # the clinical dashboard accurately while its schema is upgraded.
        result["patient_profile"] = None
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

    Every search also produces a referral trail (finding -> specialty ->
    search -> ranked providers with the referral reason and per-provider
    ranking breakdown) that is appended to this user's persisted history.
    Persistence is best-effort: a missing/unavailable referrals table never
    fails the live search itself.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(404, "No patient record found for this user. Upload and process medical documents first.")
    try:
        result = await asyncio.to_thread(
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

    # Phase 3 — referral trail: persist WHY this finding produced this
    # referral and WHY each provider was ranked where it was, so the
    # relationship remains reviewable after the live results age out.
    referral = build_referral_search(
        clinical_flag=result["clinical_flag"],
        specialty=result["specialty"],
        location=result["location"],
        availability=result["availability"],
        providers=result["providers"],
        provenance=result["provenance"],
        care_route_explanation=result.get("care_route_explanation"),
        evidence=result.get("evidence"),
    )
    result["referral"] = referral
    result["referral_id"] = referral["search_id"]
    result["referral_reason"] = referral["intent"]["referral_reason"]
    try:
        db.save_referral_search(user_id, referral)
        audit.record(user_id, "care.referral_search", {
            "referral_id": referral["search_id"],
            "flag_id": body.flag_id,
            "provider_count": len(result["providers"]),
        })
    except db.SchemaNotInitializedError as exc:
        logger.warning(
            "care search: user=%s referral trail not persisted (referrals table "
            "missing — run the updated supabase_schema.sql); live results returned: %s",
            user_id, exc,
        )
    except Exception as exc:
        logger.warning(
            "care search: user=%s referral trail persistence failed (live results "
            "still returned): %s", user_id, exc,
        )
    return result


@app.get("/api/v1/care-referrals")
async def get_care_referrals(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Returns this user's persisted referral-trail history, newest first.

    Each entry is a historical record of one provider search: the clinical
    finding that motivated it, the mapped specialty, the referral reason,
    the location/availability used, and the providers returned at that
    moment with their ranking breakdowns. These are records OF searches,
    not a live provider directory — re-run the search for live data.
    """
    referrals = db.load_referral_searches(user_id)
    audit.record(user_id, "records.read", {"view": "care_referrals"})
    return {
        "referrals": referrals,
        "note": (
            "These are historical records of provider searches derived from your "
            "uploaded records. They are routing information — not a diagnosis and "
            "not an endorsement of any provider. Run a new search for live results."
        ),
    }


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

@app.post("/api/v1/sessions", status_code=201)
async def create_session(user_id: str = Depends(get_current_user)) -> Dict[str, str]:
    """Starts a new conversation session for the authenticated user and
    returns its session_id, to be used in subsequent
    /sessions/{session_id}/messages calls."""
    session_id = uuid.uuid4().hex
    conversation.get_or_create_session(user_id, session_id)
    audit.record(user_id, "session.create", {"session_id": session_id})
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
        result = await asyncio.to_thread(
            conversation.ask, session, body.question, top_k=body.top_k
        )
        audit.record(user_id, "session.message", {
            "session_id": session_id,
            "question_chars": len(body.question or ""),
        })
        return result
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
    """Ends a conversation session, removing its transcript from memory and
    the durable store."""
    if not conversation.delete_session(user_id, session_id):
        raise HTTPException(404, f"Session '{session_id}' not found.")
    audit.record(user_id, "session.delete", {"session_id": session_id})


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
