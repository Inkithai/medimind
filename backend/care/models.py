"""Normalized care-navigation response models."""

from dataclasses import asdict, dataclass
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
    # Structured specialty tags from the source directory (e.g. OSM
    # healthcare:speciality). Display-only; never inferred from the name.
    specialties: Optional[List[str]] = None
    source: str = "public listings"

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready dictionary while retaining explicit nulls as a stable API."""
        return asdict(self)
