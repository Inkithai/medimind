"""Provider-neutral result post-processing.

Every care-directory response passes through here before it reaches the
API layer, regardless of which provider produced it. This is where the
radius promise is actually enforced ("5 km" must mean no result beyond
5 km) and where duplicate listings are removed.
"""

import re
from typing import List, Optional

from care.models import Facility
from care.models import haversine_km as distance_km

# Two listings with the same normalized name within this distance are
# treated as the same real-world facility. Two facilities can legitimately
# share a name, so name alone is never enough — they must also be
# effectively at the same place.
_DUPLICATE_PROXIMITY_KM = 0.15


def normalize_name(name: str) -> str:
    """Lowercase, collapse punctuation/whitespace — for duplicate grouping only.

    Presentation keeps the original source name untouched.
    """
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower()).strip()


def _richness(facility: Facility) -> int:
    """How much real data a listing carries — richer duplicates win."""
    return sum(
        1
        for value in (
            facility.address,
            facility.phone,
            facility.website,
            facility.opening_hours,
            facility.specialty,
            facility.rating,
        )
        if value
    )


def dedupe(facilities: List[Facility]) -> List[Facility]:
    """Remove duplicate listings.

    A duplicate is: (a) the exact same source id, or (b) the same
    normalized name at effectively the same coordinates. Facilities that
    merely share a name but sit far apart are kept — they are genuinely
    different places.
    """
    kept: List[Facility] = []
    seen_ids: set = set()
    for facility in facilities:
        if facility.id and facility.id in seen_ids:
            continue
        duplicate_index = None
        name_key = normalize_name(facility.name)
        for index, existing in enumerate(kept):
            if normalize_name(existing.name) != name_key or not name_key:
                continue
            separation = distance_km(
                existing.latitude, existing.longitude, facility.latitude, facility.longitude
            )
            if separation <= _DUPLICATE_PROXIMITY_KM:
                duplicate_index = index
                break
        if duplicate_index is None:
            kept.append(facility)
        elif _richness(facility) > _richness(kept[duplicate_index]):
            # Keep the listing that actually carries more source data.
            kept[duplicate_index] = facility
        if facility.id:
            seen_ids.add(facility.id)
    return kept


def finalize(
    facilities: List[Facility],
    *,
    radius_km: float,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    kind: Optional[str] = None,
) -> List[Facility]:
    """Enforce kind + radius, fill distances, dedupe, and sort by distance.

    When the search origin is known, ``distance(result, origin) <= radius``
    is a hard rule — the radius control is real, not cosmetic. Without an
    origin (legacy text-only searches) distances cannot be computed, so the
    list is only deduplicated. A specific ``kind`` is likewise enforced here
    so a provider that returns broader results cannot leak mismatched
    categories into a filtered search.
    """
    normalized_kind = (kind or "any").strip().lower()
    if normalized_kind == "lab":
        normalized_kind = "laboratory"
    if normalized_kind not in ("", "any", "healthcare"):
        # The OpenStreetMap normalizer folds doctor practices into "clinic",
        # so a doctor search accepts both categories rather than returning
        # an empty list for OSM-backed results.
        accepted = {normalized_kind}
        if normalized_kind == "doctor":
            accepted.add("clinic")
        facilities = [f for f in facilities if f.kind in accepted]

    if latitude is not None and longitude is not None:
        with_distance: List[Facility] = []
        for facility in facilities:
            distance = facility.distance_km
            if distance is None:
                distance = round(
                    distance_km(latitude, longitude, facility.latitude, facility.longitude), 3
                )
                facility.distance_km = distance
            if distance <= radius_km:
                with_distance.append(facility)
        facilities = with_distance

    facilities = dedupe(facilities)
    facilities.sort(
        key=lambda item: item.distance_km if item.distance_km is not None else float("inf")
    )
    return facilities
