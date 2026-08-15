"""Interface implemented by care-directory providers."""

from typing import List, Optional, Protocol

from care.models import Facility


class CareProvider(Protocol):
    name: str

    def search(
        self,
        location: str,
        kind: str,
        radius_km: float,
        *,
        latitude: Optional[float] = None,
        longitude: Optional[float] = None,
        specialty: Optional[str] = None,
    ) -> List[Facility]:
        """Return normalized public facility listings near a place or point."""
        ...
