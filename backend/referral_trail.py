"""
Referral trail — persisted finding → specialty → search → providers
====================================================================
Closes the loop between a safety finding and the provider search it
motivated, and makes both reviewable later.

For every local-care search the pipeline produces:

  intent    which clinical flag (finding) drove the referral, which
            specialty it was mapped to, the location/availability the
            patient searched with, and WHY this referral exists —
            `referral_reason`, a plain-language explanation assembled
            from the finding's own evidence and the specialty matcher's
            reasoning;

  results   the live provider records returned at that moment, each
            carrying its transparent ranking breakdown (numeric signal
            weights, scores, and contributions) so "why was this
            provider ranked where it is" remains answerable after the
            fact.

Design rules, matching the rest of the care stack:
  * Nothing here invents provider attributes — every result field and
    every ranking component came from the live directory or from
    arithmetic over its data.
  * A persisted trail is a historical record OF A SEARCH, not a provider
    directory: each entry keeps its provenance (source id, label,
    retrieved_at) so stale results can never be mistaken for live ones.
  * The referral reason is routing advice, never a diagnosis — the same
    framing as the triage and care modules.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from provider_ranking import availability_label, ranking_method_description

_REFERRAL_DISCLAIMER = (
    "This referral trail records why a provider search was suggested and how its "
    "results were ranked. It is routing information derived from the uploaded "
    "records — not a diagnosis, and not an endorsement of any provider."
)


def referral_reason(clinical_flag: Dict[str, Any]) -> str:
    """Plain-language explanation of WHY this finding produced this
    referral, assembled only from fields already attached to the flag.

    Shape: finding title + risk framing + specialty matcher's stated
    reason + routing-not-diagnosis caveat.
    """
    title = clinical_flag.get("title") or "A safety finding"
    risk_level = clinical_flag.get("risk_level")
    trigger = clinical_flag.get("trigger")
    if risk_level == "high" or trigger == "high_risk":
        framing = "a high-risk finding in the uploaded records"
    else:
        framing = "a low-confidence finding in the uploaded records"

    specialty = clinical_flag.get("specialty") or {}
    specialty_label = specialty.get("label") or "a suitable professional"
    specialty_reason = specialty.get("reason") or (
        "the available record does not support a narrower specialty choice."
    )

    return (
        f"{title} was flagged as {framing}. MediMind routed this finding to "
        f"{specialty_label}, because {specialty_reason.lower().rstrip('.')}. "
        "This is a routing suggestion, not a diagnosis."
    )


def build_referral_search(
    *,
    clinical_flag: Dict[str, Any],
    specialty: Dict[str, Any],
    location: Dict[str, Any],
    availability: str,
    providers: List[Dict[str, Any]],
    provenance: Dict[str, Any],
    care_route_explanation: Optional[str] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Assembles the serializable referral-trail record for one search.

    The returned record is what gets persisted (db.save_referral_search)
    and echoed back to the client, so the response and the stored history
    can never disagree about what happened.
    """
    flag_id = clinical_flag.get("id") or ""
    search_id = f"{flag_id}::{uuid.uuid4().hex[:12]}" if flag_id else uuid.uuid4().hex

    return {
        "search_id": search_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "intent": {
            "clinical_flag": {
                "id": flag_id,
                "issue_type": clinical_flag.get("issue_type"),
                "trigger": clinical_flag.get("trigger"),
                "risk_level": clinical_flag.get("risk_level"),
                "title": clinical_flag.get("title"),
                "evidence": clinical_flag.get("evidence"),
                "source": clinical_flag.get("source"),
                "confidence": clinical_flag.get("confidence"),
            },
            "specialty": {
                "id": specialty.get("id"),
                "label": specialty.get("label"),
                "provider_query": specialty.get("provider_query"),
                "reason": specialty.get("reason"),
            },
            "referral_reason": referral_reason(clinical_flag),
            "care_route_explanation": care_route_explanation,
            "evidence": evidence or [],
            "location": {
                "query": location.get("query"),
                "resolved_area": location.get("resolved_area"),
                "latitude": location.get("latitude"),
                "longitude": location.get("longitude"),
            },
            "availability": availability,
            "availability_label": availability_label(availability),
        },
        "results": providers,
        "ranking_method": ranking_method_description(),
        "provenance": {
            "source_id": provenance.get("source_id"),
            "label": provenance.get("label"),
            "retrieved_at": provenance.get("retrieved_at"),
        },
        "disclaimer": _REFERRAL_DISCLAIMER,
    }
