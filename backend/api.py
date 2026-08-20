"""
HTTP API (Phase 3 + 4)
=========================================
Exposes the extraction -> timeline -> medication-safety -> trend-track ->
retrieval -> conversation pipeline (medical_extractor.py,
medication_safety.py, lab_trends.py, retrieval.py, conversation.py) over
HTTP, under the /api/v1/ prefix.

This file is a thin FastAPI app assembly: it creates the app, wires up
middleware, exception handlers, structured logging, health/metrics
endpoints, and mounts the feature route modules from backend/routes/
(upload, records, clinical, conversation, care). All business logic stays
in the service modules.

Every route except /health and /api/v1/anonymous/session requires an
authenticated caller (see auth.py):
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

Env:
    LLM_PROVIDER + provider key (GROQ_API_KEY or GEMINI_API_KEY / GOOGLE_API_KEY),
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET,
    JWT_SECRET
    (optional: OPENAI_API_KEY — used only for embeddings; without it,
     embeddings run locally via Chroma's ONNX MiniLM model)
    (optional: METRICS_TOKEN — bearer token guarding GET /metrics; when
     unset the endpoint is only reachable from loopback)
"""

import asyncio
import hmac
import logging
import os
import re
from contextlib import asynccontextmanager
from typing import Dict

from dotenv import load_dotenv

load_dotenv(override=True)

from fastapi import FastAPI, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.responses import JSONResponse, PlainTextResponse  # noqa: E402
from pythonjsonlogger import jsonlogger  # noqa: E402

# Module re-exports kept for source compatibility: tests and external callers
# reference these as attributes of the `api` module (e.g. api.db, api.audit).
import audit  # noqa: E402, F401
import care_finder  # noqa: E402, F401
import conversation  # noqa: E402, F401
import db  # noqa: E402, F401
import graph_db  # noqa: E402, F401
import jobs  # noqa: E402, F401
import storage  # noqa: E402, F401
import vector_store  # noqa: E402, F401
from auth import (  # noqa: E402, F401
    get_current_user,
    issue_anonymous_token,
)
from care import CareConfigurationError, CareProviderError, get_care_provider  # noqa: E402, F401
from care.service import CareNavigationError, get_care_service  # noqa: E402, F401
from care_recommendations import search_live_providers  # noqa: E402, F401
from consult_triage import generate_consult_triage  # noqa: E402, F401
from dosage_rules import check_dosages  # noqa: E402, F401
from medical_extractor import process_document  # noqa: E402, F401
from medication_safety import cross_check_prescriptions  # noqa: E402, F401
from memory_probe import log_rss  # noqa: E402
from retrieval import (  # noqa: E402, F401
    answer_question,
    index_patient_timeline,
    preload_embedding_model,
)
from routes.care import router as care_router  # noqa: E402
from routes.clinical import router as clinical_router  # noqa: E402
from routes.conversation import MAX_QUESTION_LENGTH  # noqa: E402, F401
from routes.conversation import router as conversation_router  # noqa: E402
from routes.records import router as records_router  # noqa: E402
from routes.upload import (  # noqa: E402
    UPLOAD_FILE_CONCURRENCY,
    UploadPipelineError,
    delete_document,  # noqa: F401  (re-exported for test compatibility)
    delete_workspace,  # noqa: F401  (re-exported for test compatibility)
    router as upload_router,
)

# Import the real implementations: records.py exposes patchable wrappers
# under the public names, and api.* must stay the real functions so the
# wrappers resolve through api without recursing.
from routes.records import (  # noqa: E402
    _derive_record_impl as _derive_record,  # noqa: F401
    _enhanced_cross_check_impl as _enhanced_cross_check,  # noqa: F401
    _load_snapshot_or_rebuild_impl as _load_snapshot_or_rebuild,  # noqa: F401
    _prepare_current_trust_state_impl as _prepare_current_trust_state,  # noqa: F401
    _rebuild_after_document_deletion_impl as _rebuild_after_document_deletion,  # noqa: F401
    _replace_index_impl as _replace_index,  # noqa: F401
    _workspace_has_active_upload_impl as _workspace_has_active_upload,  # noqa: F401
)  # noqa: E402


# ---------------------------------------------------------------------------
# Structured JSON logging
# ---------------------------------------------------------------------------
class _JsonFormatter(jsonlogger.JsonFormatter):
    """JSON-formatted, machine-parseable log lines for production."""

    def add_fields(self, log_record, record, message_dict):
        super().add_fields(log_record, record, message_dict)
        log_record.setdefault("level", record.levelname.lower())
        log_record.setdefault("logger", record.name)


_handler = logging.StreamHandler()
_handler.setFormatter(
    _JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={"asctime": "timestamp"},
    )
)
logging.basicConfig(level=logging.INFO, handlers=[_handler], force=True)
logger = logging.getLogger("api")


# ---------------------------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Document worker pool ready", extra={"concurrency": UPLOAD_FILE_CONCURRENCY})
    # The care directory always has a keyless OpenStreetMap default, so this
    # only reports which adapter is active rather than gating the feature.
    try:
        care_provider = get_care_provider()
        logger.info("Care directory ready", extra={"provider": care_provider.name})
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
    # serving documents, timelines, cross-checks or Q&A.
    if graph_db.is_configured():
        try:
            graph_db.ensure_constraints()
            logger.info("startup: antidote reference graph ready")
        except Exception as e:
            logger.warning(
                "startup: antidote reference graph unavailable, continuing without it "
                "(antidote reference notes will be empty on every upload): %s",
                e,
            )
    else:
        logger.info("startup: antidote reference graph not configured — skipping")

    # Load the embedding model ONCE, at startup, outside any request.
    log_rss(logger, "startup")
    if os.environ.get("PRELOAD_EMBEDDING_MODEL", "true").strip().lower() not in (
        "false",
        "0",
        "no",
    ):
        try:
            await asyncio.to_thread(preload_embedding_model)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Embedding model preload skipped: %s", exc)
        log_rss(logger, "startup_embeddings_ready")
    yield
    # Shutdown: nothing to clean up. The Chroma client and the embedding
    # model are process-wide singletons that live for the app's lifetime.


app = FastAPI(title="MediMind API", version="1.0.0", lifespan=lifespan)


def parse_cors_settings(
    cors_origins: str | None = None,
    frontend_url: str | None = None,
) -> tuple[list[str], bool, str | None]:
    """Build CORS allow_origins + allow_credentials + allow_origin_regex.

    ``CORS_ORIGINS`` is the explicit allowlist (comma-separated). ``FRONTEND_URL``
    is accepted as an alias so a Vercel/production URL can be set without a
    second variable. Trailing slashes are stripped: browsers send Origin without
    one, but operators often paste ``https://app.example.com/``.

    Entries containing a ``*`` (other than a bare ``*``) are treated as wildcard
    patterns, e.g. ``https://*.vercel.app`` matches every per-deployment Vercel
    preview URL (``https://medimind-abc123.vercel.app``) — Vercel mints a new
    random subdomain on each deploy, so allowlisting exact preview URLs is not
    practical. Patterns are compiled into a single ``allow_origin_regex`` for
    Starlette's CORSMiddleware, which matches the specific Origin header and
    reflects it back (so credentialed requests still work).

    ``allow_credentials=True`` is invalid with ``allow_origins=["*"]`` (browsers
    reject it). When the allowlist is ``*`` we allow all origins without
    credentials. An explicit FRONTEND_URL promotes the allowlist off ``*`` so
    credentialed browser calls from that origin succeed.
    """
    raw = (cors_origins if cors_origins is not None else os.environ.get("CORS_ORIGINS", "*")).strip()
    extra = (
        frontend_url if frontend_url is not None else os.environ.get("FRONTEND_URL", "")
    ).strip()

    def _clean(value: str) -> str:
        return value.strip().rstrip("/")

    origins: list[str] = []
    patterns: list[str] = []

    def _add(value: str) -> None:
        cleaned = _clean(value)
        if not cleaned or cleaned == "*":
            return
        if "*" in cleaned:
            if cleaned not in patterns:
                patterns.append(cleaned)
        elif cleaned not in origins:
            origins.append(cleaned)

    if extra:
        for item in extra.split(","):
            _add(item)

    if raw == "*" or not raw:
        if origins or patterns:
            return origins, True, _compile_origin_patterns(patterns)
        return ["*"], False, None

    for item in raw.split(","):
        _add(item)
    if not origins and not patterns:
        return ["*"], False, None
    return origins, True, _compile_origin_patterns(patterns)


def _compile_origin_patterns(patterns: list[str]) -> str | None:
    """Translate wildcard origin patterns into one regex for CORSMiddleware.

    Each ``*`` in a pattern becomes ``.*``; everything else is escaped
    literally. The middleware applies ``re.fullmatch``, so
    ``https://*.vercel.app`` becomes ``https://.*\\.vercel\\.app`` and cannot
    match e.g. ``https://evil.vercel.app.attacker.com``.
    """
    if not patterns:
        return None
    return "|".join(
        ".*".join(re.escape(part) for part in pattern.split("*")) for pattern in patterns
    )


# The authenticated routes require custom Authorization / X-User-Id headers,
# which trigger a CORS preflight when the frontend is served from a different
# origin than the API. Restrict via CORS_ORIGINS / FRONTEND_URL when deployed;
# wildcard patterns like https://*.vercel.app are supported (see
# parse_cors_settings).
_cors_allow_origins, _cors_allow_credentials, _cors_origin_regex = parse_cors_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins,
    allow_credentials=_cors_allow_credentials,
    allow_origin_regex=_cors_origin_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------
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


@app.exception_handler(CareNavigationError)
async def care_navigation_error_handler(request: Request, exc: CareNavigationError):
    logger.warning("care navigation %s %s: %s", request.method, request.url.path, exc)
    return JSONResponse(
        status_code=exc.http_status,
        content={"detail": str(exc), "code": exc.code},
    )


# ---------------------------------------------------------------------------
# Metrics (Prometheus) — guarded by an internal-only token check
# ---------------------------------------------------------------------------
_metrics_enabled = False
_metrics_registry = None
try:
    from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, generate_latest

    # A private registry keeps metric registration idempotent across module
    # re-imports (e.g. tests that reload `api`), which the default registry
    # would reject with "Duplicated timeseries" on the second import.
    _metrics_registry = CollectorRegistry()
    REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path", "status"],
        registry=_metrics_registry,
    )
    ERRORS_TOTAL = Counter(
        "http_errors_total",
        "Total HTTP 5xx responses",
        ["method", "path"],
        registry=_metrics_registry,
    )
    _metrics_enabled = True
except Exception:  # pragma: no cover - metrics are optional
    logger.warning("prometheus_client unavailable — /metrics disabled")


def _metrics_authorized(request: Request) -> bool:
    """Internal-only guard for /metrics.

    When METRICS_TOKEN is set, the caller must present it as a bearer token.
    Otherwise the endpoint is restricted to loopback. Private RFC1918 ranges
    are NOT treated as internal: on Render/Railway/Fly the TCP peer is the
    platform proxy on 10/8 or 172.16/12, which would make /metrics
    world-readable without a token.
    """
    expected = os.environ.get("METRICS_TOKEN", "").strip()
    if expected:
        auth_header = request.headers.get("authorization", "")
        provided = auth_header[7:].strip() if auth_header.lower().startswith("bearer ") else ""
        if not provided or len(provided) != len(expected):
            return False
        return hmac.compare_digest(provided, expected)
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    response = await call_next(request)
    if _metrics_enabled:
        try:
            path = request.url.path
            status = response.status_code
            REQUESTS_TOTAL.labels(method=request.method, path=path, status=status).inc()
            if status >= 500:
                ERRORS_TOTAL.labels(method=request.method, path=path).inc()
        except Exception:  # pragma: no cover - metrics must never break requests
            pass
    return response


@app.get("/metrics")
async def metrics(request: Request):
    if not _metrics_enabled or _metrics_registry is None:
        raise HTTPException(status_code=404, detail="metrics disabled")
    if not _metrics_authorized(request):
        raise HTTPException(status_code=403, detail="forbidden")
    return PlainTextResponse(generate_latest(_metrics_registry), media_type=CONTENT_TYPE_LATEST)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/api/v1/health")
@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "MediMind", "version": "1.0.0"}


@app.get("/")
async def root() -> Dict[str, str]:
    return {"service": "MediMind", "status": "ok", "docs": "/docs"}


@app.post("/api/v1/anonymous/session", status_code=201)
async def create_anonymous_session() -> Dict[str, str]:
    """
    Creates an anonymous workspace for the MediMind frontend. No auth
    required. Issues a signed JWT whose user_id claim is a fresh anon_*
    identifier. The frontend stores {user_id, token} in localStorage and
    uses them as Authorization + X-User-Id for all subsequent calls.
    """
    user_id, token = issue_anonymous_token()
    logger.info("anonymous session created: user_id=%s", user_id)
    return {"user_id": user_id, "token": token, "session_id": user_id}


# ---------------------------------------------------------------------------
# Feature routers
# ---------------------------------------------------------------------------
app.include_router(upload_router)
app.include_router(records_router)
app.include_router(clinical_router)
app.include_router(conversation_router)
app.include_router(care_router)
