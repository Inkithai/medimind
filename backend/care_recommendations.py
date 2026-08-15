"""Orchestrates the optional live local-care recommendation flow.

This module composes independent clinical flags, specialty mapping, source
integration, normalization, and ranking. It contains no hard-coded provider
records and persists no provider-directory data.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from clinical_flags import derive_clinical_flags, find_flag
from consultation_pack import build_consultation_pack
from evidence_builder import enrich_care_flag
from provider_normalizer import normalize_provider_records
from provider_ranking import rank_providers, ranking_method_description
from provider_sources import ProviderSearchError, get_provider_source


MEDICAL_DISCLAIMER = (
    "MediMind does not diagnose medical conditions. It identifies potential issues and confidence limits in uploaded records. "
    "These provider suggestions are intended only to help find an appropriate healthcare professional; review the information with a licensed clinician or pharmacist."
)


def flags_from_snapshot(snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Derive and enrich only the current patient's saved flags.

    ``enrich_care_flag`` receives the same snapshot components that produced
    the flag, so a response cannot accidentally resolve evidence from another
    user or an external provider source.
    """
    timeline = snapshot.get("patient_timeline") or {}
    cross_check = snapshot.get("cross_check_report") or {}
    lab_trends = snapshot.get("lab_trends") or {}
    flags = derive_clinical_flags(timeline, cross_check, lab_trends)
    return [enrich_care_flag(flag, timeline, cross_check, lab_trends) for flag in flags]


def recommendation_context(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    flags = flags_from_snapshot(snapshot)
    return {
        "eligible": bool(flags),
        "flags": flags,
        "disclaimer": MEDICAL_DISCLAIMER,
        "message": (
            "A local-care search is available because MediMind found an existing high-risk or low-confidence flag."
            if flags
            else "No high-risk or low-confidence flag is currently available for local-care search."
        ),
    }


def search_live_providers(
    snapshot: Dict[str, Any],
    *,
    flag_id: str,
    location: str,
    availability: str,
) -> Dict[str, Any]:
    """Search one configured live directory for an authenticated snapshot flag."""
    flags = flags_from_snapshot(snapshot)
    selected_flag = find_flag(flags, flag_id)
    if selected_flag is None:
        raise ValueError("The selected clinical flag is unavailable. Refresh the care recommendations and select a current flag.")

    # This pack is built solely from the selected patient's snapshot and
    # Phase 1 evidence. It deliberately remains independent of provider data.
    consultation_pack = build_consultation_pack(
        selected_flag,
        snapshot,
        pathway_evidence=selected_flag.get("pathway_evidence"),
    )

    source = get_provider_source()
    payload = source.search(location, selected_flag["specialty"])
    normalized = normalize_provider_records(payload)
    ranked = rank_providers(normalized, selected_flag["specialty"], availability)
    no_results_message = payload.no_results_message
    if not ranked and not no_results_message:
        no_results_message = (
            "No suitable live provider records were found for this search. Try a broader city/area or use the broader provider category."
        )

    return {
        "clinical_flag": selected_flag,
        "specialty": selected_flag["specialty"],
        # Additive clinical-evidence fields. These are resolved before the
        # provider-source call and never include provider directory records.
        "evidence": selected_flag.get("pathway_evidence", []),
        "care_route_explanation": selected_flag.get("care_route_explanation"),
        "consultation_pack": consultation_pack,
        "location": {
            "query": location,
            "resolved_area": payload.origin.label if payload.origin else None,
            "latitude": payload.origin.latitude if payload.origin else None,
            "longitude": payload.origin.longitude if payload.origin else None,
        },
        "availability": availability,
        "provenance": {
            "live": True,
            "source_id": payload.source_id,
            "label": f"Live provider data — {payload.source_label}",
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
        },
        "ranking_method": ranking_method_description(),
        "providers": ranked,
        "no_results_message": no_results_message,
        "disclaimer": MEDICAL_DISCLAIMER,
    }


__all__ = [
    "MEDICAL_DISCLAIMER",
    "ProviderSearchError",
    "recommendation_context",
    "search_live_providers",
]
