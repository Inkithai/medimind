"""Normalized care-navigation response models."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class Facility:
    """Provider-neutral public facility listing returned by every adapter."""

    id: str
    name: str
    kind: str
    latitude: float
    longitude: float
    address: Optional[str] = None
    distance_km: Optional[float] = None
    rating: Optional[float] = None
    user_rating_count: Optional[int] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    opening_hours: Optional[List[str]] = None
    open_now: Optional[bool] = None
    source: str = "public listings"
    # Provider/patient-context enrichment (populated by the provider layer):
    entity_type: str = "facility"  # practitioner | facility | organization
    specialties: List[str] = field(default_factory=list)
    # Match against the requested specialty (None when none was requested):
    match_tier: Optional[int] = None
    match_level: Optional[str] = None  # exact | related | other
    match_reason: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready dictionary while retaining explicit nulls as a stable API."""
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "address": self.address,
            "distance_km": self.distance_km,
            "rating": self.rating,
            "user_rating_count": self.user_rating_count,
            "phone": self.phone,
            "website": self.website,
            "maps_url": self.maps_url,
            "opening_hours": self.opening_hours,
            "open_now": self.open_now,
            "source": self.source,
            "entity_type": self.entity_type,
            "specialties": self.specialties,
            "match_tier": self.match_tier,
            "match_level": self.match_level,
            "match_reason": self.match_reason,
        }
