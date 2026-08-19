"""Care routes — care recommendations, live provider search, and
care navigation (facilities / geocode / routes).
"""

import asyncio
import logging

from dotenv import load_dotenv

load_dotenv(override=True)


from typing import Any, Dict, List, Literal, Optional  # noqa: E402

from fastapi import (  # noqa: E402
    APIRouter,
    Depends,
    HTTPException,
    Query,
)
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

import audit  # noqa: E402
import care_finder  # noqa: E402
import db  # noqa: E402
from auth import get_current_user  # noqa: E402
from care import CareConfigurationError, CareProviderError  # noqa: E402
from care.models import FACILITY_KINDS  # noqa: E402
from care.postprocess import finalize as finalize_facilities  # noqa: E402
from care.recommendation import recommend_care  # noqa: E402
from care.recommendations import generate_care_recommendations  # noqa: E402
from care_recommendations import ProviderSearchError, recommendation_context  # noqa: E402
from referral_trail import build_referral_search  # noqa: E402

logger = logging.getLogger("api.care")

router = APIRouter()


from routes.records import (  # noqa: E402
    _enhanced_cross_check,
    _lab_trends_for_snapshot,
    _load_snapshot_or_rebuild,
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
    radius_km: float = Field(default=10, ge=1, le=50)
    # Optional coordinates from the frontend's map autocomplete. When both are
    # present the live source searches around this exact point instead of
    # re-geocoding the free-text location.
    latitude: Optional[float] = Field(default=None, ge=-90, le=90)
    longitude: Optional[float] = Field(default=None, ge=-180, le=180)


# ---------------------------------------------------------------------------
# Patient profile and normalized clinical entities
# ---------------------------------------------------------------------------


@router.get("/api/v1/care/recommendation")
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


@router.get("/api/v1/care/recommendations")
async def get_scored_care_recommendations(
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
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
            "note": "No patient records found. Upload documents to get personalised care recommendations.",  # noqa: E501
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
        "note": "These suggestions are derived from your medical records and are not a diagnosis or referral.",  # noqa: E501
    }


@router.get("/api/v1/care-recommendations")
async def get_care_recommendations(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Return local-care search eligibility from current saved clinical flags.

    This endpoint does not diagnose and does not query a provider directory.
    It only exposes existing high-risk/low-confidence flags so the user can
    select one before providing a city/area and availability preference.
    """
    snapshot = _load_snapshot_or_rebuild(user_id)
    if snapshot is None:
        raise HTTPException(
            404,
            "No patient record found for this user. Upload and process medical documents first.",
        )
    return recommendation_context(snapshot)


@router.post("/api/v1/care-recommendations/search")
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
        raise HTTPException(
            404,
            "No patient record found for this user. Upload and process medical documents first.",
        )
    try:
        result = await asyncio.to_thread(
            search_live_providers,
            snapshot,
            flag_id=body.flag_id,
            location=body.location.strip(),
            availability=body.availability,
            radius_km=body.radius_km,
            latitude=body.latitude,
            longitude=body.longitude,
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
        audit.record(
            user_id,
            "care.referral_search",
            {
                "referral_id": referral["search_id"],
                "flag_id": body.flag_id,
                "provider_count": len(result["providers"]),
            },
        )
    except db.SchemaNotInitializedError as exc:
        logger.warning(
            "care search: user=%s referral trail not persisted (referrals table "
            "missing — run the updated supabase_schema.sql); live results returned: %s",
            user_id,
            exc,
        )
    except Exception as exc:
        logger.warning(
            "care search: user=%s referral trail persistence failed (live results "
            "still returned): %s",
            user_id,
            exc,
        )
    return result


@router.get("/api/v1/care-referrals")
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


def _care_timeline(user_id: str) -> Optional[Dict[str, Any]]:
    """Best-effort record load. Find-care still works without a snapshot."""
    try:
        snapshot = _load_snapshot_or_rebuild(user_id)
    except Exception as exc:
        logger.warning("care finder: could not load snapshot for %s: %s", user_id, exc)
        return None
    return snapshot["patient_timeline"] if snapshot else None


@router.get("/api/v1/care/specialties")
async def list_care_specialties(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    """Catalogue of specialties the UI can offer, plus a suggestion from
    the caller's saved records when they have any."""
    return care_finder.suggest_specialties(_care_timeline(user_id))


@router.get("/api/v1/care/suggestion")
async def get_care_suggestion(user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    return care_finder.suggest_specialties(_care_timeline(user_id))


@router.post("/api/v1/care/search")
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


@router.get("/api/v1/care/facilities")
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


@router.get("/api/v1/care/geocode")
async def care_geocode(q: str, user_id: str = Depends(get_current_user)) -> Dict[str, Any]:
    _ = user_id
    point = await asyncio.to_thread(get_care_service().geocode, q)
    return {
        "latitude": point.latitude,
        "longitude": point.longitude,
        "label": point.label,
        "provider": point.provider,
    }


@router.get("/api/v1/care/routes")
async def care_routes(
    origin: str,
    destination: str,
    user_id: str = Depends(get_current_user),
) -> Dict[str, Any]:
    _ = user_id
    return await asyncio.to_thread(get_care_service().get_route, origin, destination)


# ---------------------------------------------------------------------------
# Patchable indirection
# ---------------------------------------------------------------------------
# Tests patch these names on the `api` module; resolve through api at call time.


def get_care_provider(*args, **kwargs):
    import api as _api

    return _api.get_care_provider(*args, **kwargs)


def get_care_service(*args, **kwargs):
    import api as _api

    return _api.get_care_service(*args, **kwargs)


def process_document(*args, **kwargs):
    import api as _api

    return _api.process_document(*args, **kwargs)


# Patchable indirection: tests patch these names on the `api` module.
def search_live_providers(*args, **kwargs):
    import api as _api

    return _api.search_live_providers(*args, **kwargs)
