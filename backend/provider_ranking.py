"""Explainable ranking for normalized live provider records.

Ranking never creates provider attributes. It evaluates only:
* specialty relevance against source-returned tags/types/name;
* calculated distance from source-returned coordinates;
* source-returned rating, when present; and
* source-returned regular opening-hours text, when it can support the user's
  requested time preference.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from specialty_mapping import specialty_search_terms

_AVAILABILITY_LABELS = {
    "any": "Any consultation time",
    "today": "Today",
    "this_week": "This week",
    "evenings": "Evenings",
    "weekends": "Weekends",
}


def availability_label(value: str) -> str:
    return _AVAILABILITY_LABELS.get(value, _AVAILABILITY_LABELS["any"])


def _text(value: Any) -> str:
    return str(value or "").strip().lower()


def _score_specialty(provider: Dict[str, Any], specialty: Dict[str, Any]) -> Tuple[float, str]:
    terms = [term.lower() for term in specialty_search_terms(specialty) if term]
    source_specialties = " ".join(_text(value) for value in provider.get("source_specialties", []))
    provider_text = " ".join(
        [source_specialties, _text(provider.get("provider_type")), _text(provider.get("name"))]
    )
    matched = [term for term in terms if term in provider_text]
    if matched:
        return (
            1.0,
            f"Source metadata matches the selected provider category ({', '.join(sorted(set(matched))[:3])}).",  # noqa: E501
        )

    # A provider can be returned by a specialty-specific live source query but
    # omit speciality tags. Keep it eligible as a broad clinical option without
    # claiming source-confirmed specialty.
    broad_markers = ("doctor", "clinic", "hospital", "pharmacy", "healthcare")
    if any(marker in provider_text for marker in broad_markers):
        return (
            0.55,
            "Listed as a broad healthcare provider, but the source did not provide a matching specialty tag.",  # noqa: E501
        )
    return 0.20, "The source returned limited provider-type metadata for this result."


def _score_distance(distance_km: Optional[float]) -> Tuple[Optional[float], str]:
    if distance_km is None:
        return (
            None,
            "Distance was unavailable because the source did not provide usable coordinates.",
        )
    # Smooth 0–1 decay over 30 km; distance itself remains visible to the user.
    return max(
        0.0, 1.0 - min(float(distance_km), 30.0) / 30.0
    ), f"Approximately {distance_km:.1f} km from the searched area."


def _score_rating(provider: Dict[str, Any]) -> Tuple[Optional[float], str]:
    rating = provider.get("rating")
    if not isinstance(rating, (int, float)):
        return None, "No rating was provided by the live directory."
    bounded = max(0.0, min(5.0, float(rating))) / 5.0
    count = provider.get("rating_count")
    count_phrase = f" from {count} ratings" if isinstance(count, int) else ""
    return bounded, f"Live directory rating: {float(rating):.1f}/5{count_phrase}."


def _hour_to_24(hour: str, minute: str, meridiem: str) -> int:
    value = int(hour) % 12
    return value + (12 if meridiem.lower() == "pm" else 0)


def _availability_match(provider: Dict[str, Any], preference: str) -> Tuple[Optional[float], str]:
    if preference == "any":
        return None, "No availability preference was used for ranking."

    hours = provider.get("opening_hours") or []
    if not isinstance(hours, list) or not hours:
        return (
            None,
            "Opening-hours information was not provided by the live directory, so availability was not used for ranking.",  # noqa: E501
        )

    # OSM often supplies compact opening_hours syntax. Display it, but do not
    # pretend it has been safely interpreted for availability ranking.
    if len(hours) == 1 and ":" not in str(hours[0]):
        return (
            None,
            "Opening-hours text was provided but was not in a safely interpretable format; availability was not used for ranking.",  # noqa: E501
        )

    normalized_hours = [str(item).lower() for item in hours]
    weekday = datetime.now().strftime("%A").lower()
    today_lines = [line for line in normalized_hours if line.startswith(weekday)]

    if preference == "today":
        if provider.get("open_now") is True:
            return 1.0, "The live directory reports this provider as currently open."
        if today_lines and not any("closed" in line for line in today_lines):
            return (
                0.75,
                "Regular hours are listed for today; live appointment availability is not guaranteed.",  # noqa: E501
            )
        return 0.0, "No regular opening-hours match for today was provided."

    if preference == "this_week":
        if any("closed" not in line for line in normalized_hours):
            return (
                0.75,
                "Regular hours are listed this week; live appointment availability is not guaranteed.",  # noqa: E501
            )
        return 0.0, "No regular opening hours this week were provided."

    if preference == "weekends":
        weekend_lines = [
            line
            for line in normalized_hours
            if line.startswith("saturday") or line.startswith("sunday")
        ]
        if any("closed" not in line for line in weekend_lines):
            return (
                1.0,
                "Regular weekend hours are listed; live appointment availability is not guaranteed.",  # noqa: E501
            )
        return 0.0, "No regular weekend hours were provided."

    if preference == "evenings":
        closing_hours: List[int] = []
        for line in normalized_hours:
            times = re.findall(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)", line)
            if len(times) >= 2:
                hour, minute, meridiem = times[-1]
                closing_hours.append(_hour_to_24(hour, minute or "0", meridiem))
        if any(hour >= 17 for hour in closing_hours):
            return (
                1.0,
                "Regular hours indicate an evening closing time; live appointment availability is not guaranteed.",  # noqa: E501
            )
        if closing_hours:
            return 0.0, "Listed regular hours do not show an evening closing time."
        return (
            None,
            "Opening-hours text could not be safely interpreted for evenings, so availability was not used for ranking.",  # noqa: E501
        )

    return None, "Availability preference was not recognized, so it was not used for ranking."


def rank_providers(
    providers: List[Dict[str, Any]],
    specialty: Dict[str, Any],
    availability: str,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Return source-derived providers ordered by transparent weighted signals."""
    ranked: List[Dict[str, Any]] = []
    for provider in providers:
        specialty_score, specialty_explanation = _score_specialty(provider, specialty)
        distance_score, distance_explanation = _score_distance(provider.get("distance_km"))
        rating_score, rating_explanation = _score_rating(provider)
        availability_score, availability_explanation = _availability_match(provider, availability)

        # Mandatory signals: specialty (55) and distance (35 when available).
        # Optional source metadata only affects ranking when it actually exists.
        weighted: List[Tuple[float, float]] = [(specialty_score, 55.0)]
        if distance_score is not None:
            weighted.append((distance_score, 35.0))
        if rating_score is not None:
            weighted.append((rating_score, 10.0))
        if availability_score is not None:
            weighted.append((availability_score, 5.0))
        total_weight = sum(weight for _, weight in weighted)
        score = round(sum(value * weight for value, weight in weighted) / total_weight * 100, 1)

        result = dict(provider)
        result["ranking"] = {
            "score": score,
            "specialty_relevance": specialty_explanation,
            "distance": distance_explanation,
            "rating": rating_explanation,
            "availability": availability_explanation,
            "availability_preference": availability_label(availability),
            # Numeric disclosure of the same signals: weight, 0-1 score,
            # and contribution to the final 0-100 match score. Everything
            # here is computed above — never invented provider attributes.
            "components": [
                {
                    "signal": "specialty_relevance",
                    "weight": 55.0,
                    "score": round(specialty_score, 2),
                    "contribution": round(specialty_score * 55.0 / total_weight * 100, 1),
                    "explanation": specialty_explanation,
                },
                *(
                    [
                        {
                            "signal": "distance",
                            "weight": 35.0,
                            "score": round(distance_score, 2),
                            "contribution": round(distance_score * 35.0 / total_weight * 100, 1),
                            "explanation": distance_explanation,
                        },
                    ]
                    if distance_score is not None
                    else []
                ),
                *(
                    [
                        {
                            "signal": "rating",
                            "weight": 10.0,
                            "score": round(rating_score, 2),
                            "contribution": round(rating_score * 10.0 / total_weight * 100, 1),
                            "explanation": rating_explanation,
                        },
                    ]
                    if rating_score is not None
                    else []
                ),
                *(
                    [
                        {
                            "signal": "availability",
                            "weight": 5.0,
                            "score": round(availability_score, 2),
                            "contribution": round(availability_score * 5.0 / total_weight * 100, 1),
                            "explanation": availability_explanation,
                        },
                    ]
                    if availability_score is not None
                    else []
                ),
            ],
        }
        ranked.append(result)

    return sorted(
        ranked,
        key=lambda item: (
            -float(item["ranking"]["score"]),
            item.get("distance_km") is None,
            float(item.get("distance_km") or 999999),
            _text(item.get("name")),
        ),
    )[: max(1, min(20, limit))]


def ranking_method_description() -> str:
    return (
        "Directory match scores use only source-returned provider category/specialty metadata, calculated distance from the searched area, "  # noqa: E501
        "and rating or regular opening-hours information only when those fields are actually returned by the live directory. "  # noqa: E501
        "They do not measure clinical quality, qualifications, or appointment availability."
    )
