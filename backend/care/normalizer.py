"""Turn raw provider records into Facility objects. No clinical ranking."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from care.models import Facility


def _text(value: Any) -> Optional[str]:
    text = str(value).strip() if value is not None else ""
    return text or None


def normalize_osm_elements(elements: Iterable[Dict[str, Any]]) -> List[Facility]:
    facilities: List[Facility] = []
    seen = set()
    for raw in elements:
        if not isinstance(raw, dict):
            continue
        tags = raw.get("tags") if isinstance(raw.get("tags"), dict) else {}
        name = _text(tags.get("name") or tags.get("official_name"))
        lat = raw.get("lat")
        lon = raw.get("lon")
        center = raw.get("center") if isinstance(raw.get("center"), dict) else {}
        if lat is None:
            lat = center.get("lat")
        if lon is None:
            lon = center.get("lon")
        try:
            latitude, longitude = float(lat), float(lon)
        except (TypeError, ValueError):
            continue
        amenity = (tags.get("amenity") or tags.get("healthcare") or "").lower()
        if amenity in {"hospital"}:
            kind = "hospital"
        elif amenity in {"clinic", "doctors", "doctor", "centre", "center"}:
            kind = "clinic"
        elif amenity in {"pharmacy"}:
            kind = "pharmacy"
        elif amenity in {"laboratory", "lab"}:
            kind = "laboratory"
        else:
            kind = "clinic"
        if not name:
            name = kind.title()
        osm_type = raw.get("type") or "node"
        osm_id = raw.get("id")
        key = f"{osm_type}/{osm_id}"
        if key in seen:
            continue
        seen.add(key)
        address_parts = [
            tags.get("addr:housenumber"),
            tags.get("addr:street"),
            tags.get("addr:city") or tags.get("addr:town"),
        ]
        address = ", ".join(str(p) for p in address_parts if p) or _text(tags.get("addr:full"))
        facilities.append(
            Facility(
                id=key,
                name=name,
                kind=kind,
                latitude=latitude,
                longitude=longitude,
                address=address,
                phone=_text(tags.get("phone") or tags.get("contact:phone")),
                website=_text(tags.get("website") or tags.get("contact:website")),
                source_url=f"https://www.openstreetmap.org/{osm_type}/{osm_id}" if osm_id else None,
                provider="openstreetmap",
            )
        )
    return facilities
