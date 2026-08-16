"""Care Navigation is isolated from medical intelligence.

These tests inject a fake provider. They never call OSM/Mapbox/Google and
they never import the extraction or lab-trend modules as a dependency of
the search path.
"""
import os
import sys
from dataclasses import replace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.models import Facility, GeoPoint, RouteEstimate, haversine_km
from care.normalizer import normalize_osm_elements
from care.service import CareNavigationError, CareNavigationService


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.geocode_queries = []
        self.search_calls = []

    def geocode(self, query: str):
        self.geocode_queries.append(query)
        if "nowhere" in query.lower():
            return None
        return GeoPoint(7.29, 80.63, "Kandy, Sri Lanka", self.name)

    def search_nearby(self, origin, kind, radius_m):
        self.search_calls.append((origin, kind, radius_m))
        return [
            Facility(
                id="1",
                name="General Hospital",
                kind="hospital",
                latitude=7.30,
                longitude=80.64,
                address="Kandy",
                provider=self.name,
            ),
            Facility(
                id="2",
                name="City Clinic",
                kind="clinic",
                latitude=7.28,
                longitude=80.62,
                address="Kandy",
                provider=self.name,
            ),
        ]

    def route(self, origin, destination):
        return RouteEstimate(
            origin=origin,
            destination=destination,
            distance_km=haversine_km(
                origin.latitude, origin.longitude, destination.latitude, destination.longitude
            ),
            mode="approximate_straight_line",
            provider=self.name,
            note="test",
        )


def test_search_does_not_import_medical_pipeline():
    import care.service as module

    source = open(module.__file__, encoding="utf-8").read()
    for banned in ("medical_extractor", "lab_trends", "retrieval", "document_filter"):
        assert banned not in source


def test_search_returns_normalized_facilities_with_distance():
    service = CareNavigationService(FakeProvider())
    result = service.search_facilities(location="Kandy", kind="any")
    assert result["result_count"] == 2
    assert result["provider"] == "fake"
    assert result["origin"]["label"] == "Kandy, Sri Lanka"
    assert result["facilities"][0]["distance_km"] is not None
    assert "not a medical referral" in result["disclaimer"].lower()


def test_kind_filter_is_applied_after_normalize():
    service = CareNavigationService(FakeProvider())
    result = service.search_facilities(location="Kandy", kind="hospital")
    assert [item["kind"] for item in result["facilities"]] == ["hospital"]


def test_unknown_location_is_a_client_error():
    service = CareNavigationService(FakeProvider())
    with pytest.raises(CareNavigationError) as exc:
        service.search_facilities(location="Nowhereville")
    assert exc.value.code == "location_not_found"
    assert exc.value.http_status == 422


def test_blank_location_rejected():
    service = CareNavigationService(FakeProvider())
    with pytest.raises(CareNavigationError) as exc:
        service.geocode(" ")
    assert exc.value.code == "location_required"


def test_distance_is_provider_independent():
    service = CareNavigationService(FakeProvider())
    a = GeoPoint(0.0, 0.0, "a", "x")
    b = replace(a, latitude=0.0, longitude=1.0, label="b")
    km = service.calculate_distance(a, b)
    assert 110 < km < 112  # ~111 km per degree longitude at equator


def test_osm_normalizer_maps_amenity_tags():
    facilities = normalize_osm_elements(
        [
            {
                "type": "node",
                "id": 9,
                "lat": 7.3,
                "lon": 80.6,
                "tags": {"name": "Peradeniya Hospital", "amenity": "hospital", "phone": "081"},
            }
        ]
    )
    assert len(facilities) == 1
    assert facilities[0].kind == "hospital"
    assert facilities[0].provider == "openstreetmap"
    assert "081" in (facilities[0].phone or "")
