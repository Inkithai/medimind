"""Provider-neutral shapes. Adapters must convert into these."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(min(1.0, a)))


FACILITY_KINDS = ("hospital", "clinic", "pharmacy", "laboratory", "doctor", "healthcare", "any")

DISCLAIMER = (
    "This is a public directory lookup, not a medical referral and not a "
    "recommendation of the best place to go. Listings may be incomplete. "
    "Confirm details with the facility and a licensed clinician."
)


@dataclass(frozen=True)
class GeoPoint:
    latitude: float
    longitude: float
    label: str
    provider: str


@dataclass
class Facility:
    """Provider-neutral public facility listing returned by every adapter."""

    id: str
    name: str
    kind: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    distance_km: Optional[float] = None
    source_url: Optional[str] = None
    provider: str = ""
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    maps_url: Optional[str] = None
    opening_hours: Optional[List[str]] = None
    open_now: Optional[bool] = None
    specialty: Optional[str] = None
    specialty_match: Optional[float] = None
    availability_match: Optional[bool] = None
    ranking_score: Optional[float] = None
    ranking_reason: Optional[str] = None
    source: str = "public listings"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready dictionary while retaining explicit nulls as a stable API."""
        return asdict(self)


@dataclass
class RouteEstimate:
    origin: GeoPoint
    destination: GeoPoint
    distance_km: float
    mode: str
    provider: str
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "origin": asdict(self.origin),
            "destination": asdict(self.destination),
            "distance_km": self.distance_km,
            "mode": self.mode,
            "provider": self.provider,
            "note": self.note,
        }


def pack_facilities(
    *,
    query: str,
    kind: str,
    origin: Optional[GeoPoint],
    facilities: List[Facility],
    provider: str,
) -> Dict[str, Any]:
    return {
        "query": {"location": query, "kind": kind},
        "origin": asdict(origin) if origin else None,
        "facilities": [item.to_dict() for item in facilities],
        "result_count": len(facilities),
        "provider": provider,
        "disclaimer": DISCLAIMER,
    }
