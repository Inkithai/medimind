"""Normalize live Google Places/OpenStreetMap records into one provider shape.

Only source-returned metadata is displayed as provider information. Distance is
calculated locally from source-returned coordinates and the geocoded search
origin; no provider fields are invented when a source omits them.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Optional

from provider_sources import ProviderSourcePayload


def _text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


def _haversine_km(origin_lat: float, origin_lon: float, latitude: float, longitude: float) -> float:
    radius_km = 6371.0088
    lat1, lon1, lat2, lon2 = map(math.radians, [origin_lat, origin_lon, latitude, longitude])
    delta_lat, delta_lon = lat2 - lat1, lon2 - lon1
    a = math.sin(delta_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    return round(radius_km * 2 * math.asin(math.sqrt(a)), 1)


def _distance(payload: ProviderSourcePayload, latitude: Optional[float], longitude: Optional[float]) -> Optional[float]:
    if payload.origin is None or latitude is None or longitude is None:
        return None
    return _haversine_km(payload.origin.latitude, payload.origin.longitude, latitude, longitude)


def _unique_strings(values: Iterable[Any]) -> List[str]:
    found: List[str] = []
    for value in values:
        text = _text(value)
        if text and text not in found:
            found.append(text)
    return found


def _google_record(record: Dict[str, Any], payload: ProviderSourcePayload) -> Optional[Dict[str, Any]]:
    display_name = record.get("displayName") if isinstance(record.get("displayName"), dict) else {}
    name = _text(display_name.get("text"))
    if not name:
        return None
    location = record.get("location") if isinstance(record.get("location"), dict) else {}
    latitude, longitude = _number(location.get("latitude")), _number(location.get("longitude"))
    regular_hours = record.get("regularOpeningHours") if isinstance(record.get("regularOpeningHours"), dict) else {}
    current_hours = record.get("currentOpeningHours") if isinstance(record.get("currentOpeningHours"), dict) else {}
    opening_hours = _unique_strings(regular_hours.get("weekdayDescriptions", []) if isinstance(regular_hours.get("weekdayDescriptions"), list) else [])
    source_types = _unique_strings(
        [record.get("primaryType"), *(record.get("types", []) if isinstance(record.get("types"), list) else [])]
    )
    rating = _number(record.get("rating"))
    rating_count_raw = record.get("userRatingCount")
    rating_count = int(rating_count_raw) if isinstance(rating_count_raw, int) and rating_count_raw >= 0 else None
    return {
        "source_provider_id": _text(record.get("id")),
        "name": name,
        "provider_type": ", ".join(source_types) if source_types else None,
        "source_specialties": [],  # Google type metadata is not claimed to be a medical specialty.
        "address": _text(record.get("formattedAddress")),
        "latitude": latitude,
        "longitude": longitude,
        "distance_km": _distance(payload, latitude, longitude),
        "rating": rating,
        "rating_count": rating_count,
        "phone": _text(record.get("nationalPhoneNumber")) or _text(record.get("internationalPhoneNumber")),
        "opening_hours": opening_hours,
        "open_now": current_hours.get("openNow") if isinstance(current_hours.get("openNow"), bool) else None,
        "map_url": _text(record.get("googleMapsUri")),
        "website_url": None,
        "source": payload.source_label,
    }


def _osm_address(tags: Dict[str, Any]) -> Optional[str]:
    if _text(tags.get("addr:full")):
        return _text(tags.get("addr:full"))
    parts = _unique_strings(
        [
            " ".join(part for part in [_text(tags.get("addr:housenumber")), _text(tags.get("addr:street"))] if part),
            tags.get("addr:suburb"),
            tags.get("addr:city"),
            tags.get("addr:postcode"),
            tags.get("addr:country"),
        ]
    )
    return ", ".join(parts) if parts else None


def _osm_record(record: Dict[str, Any], payload: ProviderSourcePayload) -> Optional[Dict[str, Any]]:
    tags = record.get("tags") if isinstance(record.get("tags"), dict) else {}
    name = _text(tags.get("name"))
    if not name:
        return None
    center = record.get("center") if isinstance(record.get("center"), dict) else {}
    latitude = _number(record.get("lat")) or _number(center.get("lat"))
    longitude = _number(record.get("lon")) or _number(center.get("lon"))
    # OSM commonly stores one or more source specialty values in a
    # semicolon-separated tag. Preserve only those source-returned values.
    flat_specialties: List[str] = []
    for key in ("healthcare:speciality", "medical_specialty", "speciality"):
        raw_specialty = _text(tags.get(key))
        if raw_specialty:
            flat_specialties.extend(part.strip() for part in raw_specialty.replace(";", ",").split(",") if part.strip())
    flat_specialties = _unique_strings(flat_specialties)
    provider_type = _text(tags.get("healthcare")) or _text(tags.get("amenity"))
    # A website is not a map link. Build an OSM location link only when the
    # live record supplied coordinates; otherwise leave map_url absent.
    map_url = (
        f"https://www.openstreetmap.org/?mlat={latitude}&mlon={longitude}#map=18/{latitude}/{longitude}"
        if latitude is not None and longitude is not None
        else None
    )
    rating = _number(tags.get("rating"))
    raw_id = record.get("id")
    source_provider_id = (
        f"{record.get('type')}/{raw_id}"
        if _text(record.get("type")) and raw_id is not None and str(raw_id).strip()
        else None
    )
    return {
        "source_provider_id": source_provider_id,
        "name": name,
        "provider_type": provider_type,
        "source_specialties": flat_specialties,
        "address": _osm_address(tags),
        "latitude": latitude,
        "longitude": longitude,
        "distance_km": _distance(payload, latitude, longitude),
        "rating": rating,
        "rating_count": None,
        "phone": _text(tags.get("contact:phone")) or _text(tags.get("phone")),
        "opening_hours": [_text(tags.get("opening_hours"))] if _text(tags.get("opening_hours")) else [],
        "open_now": None,
        "map_url": map_url,
        "website_url": _text(tags.get("website")),
        "source": payload.source_label,
    }


def normalize_provider_records(payload: ProviderSourcePayload) -> List[Dict[str, Any]]:
    """Normalize and de-duplicate source results without manufacturing fields."""
    normalizer = _google_record if payload.source_id == "google_places" else _osm_record
    normalized: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for raw in payload.records:
        candidate = normalizer(raw, payload)
        if candidate is None:
            continue
        # Prefer a stable source ID; fall back to source/name/address solely to
        # avoid duplicate records returned by the same live response.
        key = candidate.get("source_provider_id") or "|".join(
            [str(candidate.get("name") or ""), str(candidate.get("address") or "")]
        ).lower()
        if not key or key in seen:
            continue
        seen.add(key)
        normalized.append(candidate)
    return normalized
