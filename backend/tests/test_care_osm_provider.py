"""Offline tests for the keyless OpenStreetMap directory adapter.

``OpenStreetMapProvider`` (care/providers/osm_directory.py) wraps the hardened
``OsmProvider`` so the map-based /api/v1/care/facilities route can use the
Overpass directory with no API key. These tests pin the bridging behaviour:
kind mapping, geocoding for text-only searches, distance ordering, and error
translation.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.errors import CareProviderError  # noqa: E402
from care.models import Facility, GeoPoint  # noqa: E402
from care.providers.base import ProviderUnavailableError  # noqa: E402
from care.providers.osm_directory import OpenStreetMapProvider  # noqa: E402

ORIGIN = GeoPoint(
    latitude=9.80138, longitude=80.1945344, label="Nelliyady", provider="openstreetmap"
)


def _facility(name, lat, lon, kind="hospital", identifier=None):
    return Facility(
        id=identifier or f"node/{abs(hash(name)) % 10000}",
        name=name,
        kind=kind,
        latitude=lat,
        longitude=lon,
        source_url="https://www.openstreetmap.org/node/1",
        provider="openstreetmap",
    )


class FakeOsm:
    """Stands in for the networked OsmProvider."""

    name = "openstreetmap"

    def __init__(self, facilities=None, point=ORIGIN, error=None):
        self.facilities = facilities if facilities is not None else []
        self.point = point
        self.error = error
        self.geocode_calls = []
        self.search_calls = []

    def geocode(self, query):
        self.geocode_calls.append(query)
        if self.error:
            raise self.error
        return self.point

    def search_nearby(self, origin, kind, radius_m):
        self.search_calls.append((origin, kind, radius_m))
        if self.error:
            raise self.error
        return list(self.facilities)


def test_coordinate_search_skips_geocoding_and_orders_by_distance():
    near = _facility("Nelliady Base Hospital", 9.8015, 80.1950)
    far = _facility("Point Pedro Base Hospital", 9.8100, 80.2000)
    fake = FakeOsm([far, near])
    provider = OpenStreetMapProvider(fake)

    results = provider.search("Nelliyady", "hospital", 5, latitude=9.80138, longitude=80.1945344)

    assert fake.geocode_calls == [], "coordinates must not trigger a geocode"
    assert [f.name for f in results] == ["Nelliady Base Hospital", "Point Pedro Base Hospital"]
    assert results[0].distance_km is not None and results[0].distance_km < 1
    assert results[0].source == "OpenStreetMap public listing"
    assert results[0].maps_url, "a map link should be filled from source_url"


def test_radius_is_converted_to_metres_and_clamped():
    fake = FakeOsm()
    OpenStreetMapProvider(fake).search("", "hospital", 5, latitude=9.8, longitude=80.19)
    assert fake.search_calls[0][2] == 5000

    fake = FakeOsm()
    OpenStreetMapProvider(fake).search("", "hospital", 999, latitude=9.8, longitude=80.19)
    assert fake.search_calls[0][2] == 50_000, "radius must be clamped to the 50 km maximum"


def test_text_only_search_geocodes_first():
    fake = FakeOsm([_facility("Jaffna Teaching Hospital", 9.668, 80.015)])
    results = OpenStreetMapProvider(fake).search("Jaffna", "hospital", 8)

    assert fake.geocode_calls == ["Jaffna"]
    assert len(results) == 1


def test_unknown_place_is_an_empty_directory_not_an_error():
    fake = FakeOsm(point=None)
    assert OpenStreetMapProvider(fake).search("Nowhere-at-all", "hospital", 8) == []


def test_kind_aliases_map_onto_overpass_queries():
    for requested, expected in [
        ("lab", "laboratory"),
        ("doctor", "clinic"),
        ("healthcare", "any"),
        ("pharmacy", "pharmacy"),
    ]:
        fake = FakeOsm()
        OpenStreetMapProvider(fake).search("", requested, 5, latitude=9.8, longitude=80.19)
        assert fake.search_calls[0][1] == expected, requested


def test_unsupported_kind_is_a_value_error():
    try:
        OpenStreetMapProvider(FakeOsm()).search("Jaffna", "dentist", 5)
    except ValueError as error:
        assert "Unsupported facility type" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_half_supplied_coordinates_are_rejected():
    try:
        OpenStreetMapProvider(FakeOsm()).search("Jaffna", "hospital", 5, latitude=9.8)
    except ValueError as error:
        assert "latitude and longitude" in str(error)
    else:
        raise AssertionError("expected ValueError")


def test_upstream_outage_becomes_a_care_provider_error():
    fake = FakeOsm(error=ProviderUnavailableError("Overpass mirrors exhausted"))
    try:
        OpenStreetMapProvider(fake).search("", "hospital", 5, latitude=9.8, longitude=80.19)
    except CareProviderError as error:
        # The care route/fallback only knows how to handle CareProviderError.
        assert "Overpass" in str(error)
    else:
        raise AssertionError("expected CareProviderError")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
