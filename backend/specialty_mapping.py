"""Explainable specialty matching for care-navigation recommendations.

This module does not diagnose a condition. It maps terms already present in
MediMind's extracted records or safety findings to a *provider search category*
so a user can find an appropriate professional to review a potential issue.

It deliberately contains only clinical-category vocabulary and search labels;
it contains no provider, clinic, address, rating, or other directory data.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

# The terms are intentionally conservative and are used only to choose a
# provider-search category. They are not a diagnostic model.
_SPECIALTIES: List[Dict[str, Any]] = [
    {
        "id": "cardiology",
        "label": "Cardiologist",
        "provider_query": "cardiologist",
        "match_terms": [
            "cardiac",
            "cardiology",
            "cardiologist",
            "heart",
            "troponin",
            "bnp",
            "ecg",
            "electrocardiogram",
            "arrhythm",
            "palpitation",
            "hypertension",
            "blood pressure",
            "chest pain",
        ],
    },
    {
        "id": "nephrology",
        "label": "Nephrologist",
        "provider_query": "nephrologist",
        "match_terms": [
            "kidney",
            "renal",
            "nephro",
            "creatinine",
            "egfr",
            "gfr",
            "urea",
            "bun",
            "albuminuria",
            "proteinuria",
            "dialysis",
        ],
    },
    {
        "id": "pulmonology",
        "label": "Pulmonologist",
        "provider_query": "pulmonologist",
        "match_terms": [
            "respiratory",
            "pulmonary",
            "pulmonologist",
            "lung",
            "asthma",
            "bronch",
            "wheez",
            "spirometry",
            "oxygen",
            "shortness of breath",
        ],
    },
    {
        "id": "neurology",
        "label": "Neurologist",
        "provider_query": "neurologist",
        "match_terms": [
            "neurolog",
            "brain",
            "seizure",
            "migraine",
            "stroke",
            "numbness",
            "neuropathy",
            "dizziness",
            "vertigo",
        ],
    },
    {
        "id": "dermatology",
        "label": "Dermatologist",
        "provider_query": "dermatologist",
        "match_terms": [
            "dermat",
            "skin",
            "rash",
            "eczema",
            "psoriasis",
            "lesion",
            "hives",
            "urticaria",
        ],
    },
]

_PHARMACY: Dict[str, Any] = {
    "id": "pharmacy",
    "label": "Pharmacist / prescribing doctor",
    "provider_query": "pharmacy",
    "match_terms": ["medication", "drug", "dosage", "dose", "interaction", "allergy"],
}

_GENERAL: Dict[str, Any] = {
    "id": "general_practice",
    "label": "General Physician",
    "provider_query": "general practitioner",
    "match_terms": ["general physician", "general practitioner", "primary care"],
}


def _normalise_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").lower()).strip()


def _basic_profile(profile: Dict[str, Any]) -> Dict[str, str]:
    """A small serializable provider-search route with no clinical claim."""
    return {
        "id": profile["id"],
        "label": profile["label"],
        "provider_query": profile["provider_query"],
    }


def _profile(
    profile: Dict[str, Any],
    reason: str,
    matched_terms: Iterable[str] = (),
    *,
    include_general_alternative: bool = True,
) -> Dict[str, Any]:
    """Return the legacy primary fields plus additive care-route metadata.

    Existing callers continue to read ``id``, ``label``, and
    ``provider_query``. ``primary`` and ``alternative`` are additive and make
    the broader route explicit without automatically searching it.
    """
    primary = _basic_profile(profile)
    alternative = (
        _basic_profile(_GENERAL)
        if include_general_alternative and profile["id"] != _GENERAL["id"]
        else None
    )
    return {
        **primary,
        "reason": reason,
        "matched_terms": sorted(set(matched_terms)),
        "primary": primary,
        "alternative": alternative,
    }


def match_specialty(issue_type: str, evidence: str) -> Dict[str, Any]:
    """Choose an appropriate search category for an already-flagged issue.

    Medication interactions, dosage conflicts, and allergy conflicts are
    deliberately directed to a pharmacist/prescribing-doctor category. For
    all other issues, the matcher looks for transparent category terms in
    source evidence. If there is no reliable category signal it returns a
    general-physician search rather than asserting a diagnosis.
    """
    normalized_issue_type = _normalise_text(issue_type)
    text = _normalise_text(evidence)

    if normalized_issue_type in {
        "high_severity_interaction",
        "allergy_conflict",
        "dosage_conflict",
        "low_confidence_medication",
        "low_confidence_interaction",
        "low_confidence_duplicate",
        "low_confidence_dosage",
    }:
        return _profile(
            _PHARMACY,
            "This flag concerns medication safety or prescription instructions; a pharmacist or the prescribing doctor is the appropriate first review.",  # noqa: E501
        )

    candidates: List[tuple[int, Dict[str, Any], List[str]]] = []
    for profile in _SPECIALTIES:
        matched = [term for term in profile["match_terms"] if term in text]
        if matched:
            candidates.append((len(matched), profile, matched))

    if candidates:
        _, profile, matched = max(candidates, key=lambda item: item[0])
        return _profile(
            profile,
            "This provider category was selected from terms already present in the flagged record; it is not a diagnosis.",  # noqa: E501
            matched,
        )

    return _profile(
        _GENERAL,
        "The available record does not support a narrower specialty choice, so a general physician is the safer starting point.",  # noqa: E501
    )


def specialty_search_terms(specialty: Dict[str, Any]) -> List[str]:
    """Terms used only to score source-returned provider metadata."""
    specialty_id = specialty.get("id")
    for profile in [*_SPECIALTIES, _PHARMACY, _GENERAL]:
        if profile["id"] == specialty_id:
            return [profile["provider_query"], *profile["match_terms"]]
    return [str(specialty.get("provider_query") or "").strip()]
