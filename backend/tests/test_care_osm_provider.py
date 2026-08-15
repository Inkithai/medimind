"""Offline tests for the OpenStreetMap (Overpass) care adapter.

Categorization must come from structured OSM tags (healthcare=*,
amenity=*), never from the display name, and never forced into "clinic".
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.providers.osm import OsmProvider, _kind_from_tags  # noqa: E402

ORIGIN = {"latitude": 9.8166, "longitude": 80.2333}


def _element(id, name, tags, lat=9.8180, lon=80.2340, type="node"):
    return {"type": type, "id": id, "lat": lat, "lon": lon, "tags": {"name": name, **tags}}


# -- Tag-based categorization -------------------------------------------------

def test_hospital_tags_classify_as_hospital_not_clinic():
    # "Trail Cancer Hospital Tellipalai" style bug: hospital tagged as
    # healthcare=hospital must never surface as a clinic.
    assert _kind_from_tags({"healthcare": "hospital"}) == "hospital"
    assert _kind_from_tags({"amenity": "hospital"}) == "hospital"
    assert _kind_from_tags({"building": "hospital"}) == "hospital"


def test_laboratory_tags_classify_as_laboratory():
    assert _kind_from_tags({"healthcare": "laboratory"}) == "laboratory"
    assert _kind_from_tags({"healthcare": "sample_collection"}) == "laboratory"
    assert _kind_from_tags({"amenity": "laboratory"}) == "laboratory"


def test_doctor_tags_classify_as_doctor():
    assert _kind_from_tags({"healthcare": "doctor"}) == "doctor"
    assert _kind_from_tags({"healthcare": "doctors"}) == "doctor"
    assert _kind_from_tags({"amenity": "doctors"}) == "doctor"


def test_clinic_and_pharmacy_tags():
    assert _kind_from_tags({"healthcare": "clinic"}) == "clinic"
    assert _kind_from_tags({"amenity": "clinic"}) == "clinic"
    assert _kind_from_tags({"healthcare": "pharmacy"}) == "pharmacy"
    assert _kind_from_tags({"amenity": "pharmacy"}) == "pharmacy"


def test_healthcare_tag_wins_over_amenity():
    assert _kind_from_tags({"healthcare": "laboratory", "amenity": "clinic"}) == "laboratory"


def test_unknown_tags_become_other_healthcare_not_clinic():
    assert _kind_from_tags({"healthcare": "alternative"}) == "healthcare"
    assert _kind_from_tags({}) == "healthcare"


def test_name_never_drives_classification():
    # Even a name containing "Hospital" stays in its tagged category.
    element = _element(1, "Vasantham Hospital", {"healthcare": "clinic"})
    provider = OsmProvider()
    facility = provider._normalize(element, ORIGIN["latitude"], ORIGIN["longitude"])
    assert facility.kind == "clinic"


# -- Normalization -------------------------------------------------------------

def test_normalize_builds_facility_with_source_and_distance():
    provider = OsmProvider()
    element = _element(
        7,
        "Sri Ram Clinic",
        {
            "healthcare": "clinic",
            "addr:street": "Temple Road",
            "addr:city": "Point Pedro",
            "phone": "+94 21 226 0000",
            "healthcare:speciality": "general;paediatrics",
            "opening_hours": "Mo-Fr 08:00-17:00",
        },
    )
    facility = provider._normalize(element, ORIGIN["latitude"], ORIGIN["longitude"])
    assert facility.id == "osm:node/7"
    assert facility.source == "OpenStreetMap"
    assert facility.kind == "clinic"
    assert facility.address == "Temple Road, Point Pedro"
    assert facility.specialties == ["general", "paediatrics"]
    assert facility.opening_hours == ["Mo-Fr 08:00-17:00"]
    assert facility.distance_km is not None and facility.distance_km < 1


def test_locality_only_address_is_derived_without_fabricating_street():
    provider = OsmProvider()
    element = _element(8, "PHM Office", {"healthcare": "clinic", "addr:city": "Point Pedro"})
    facility = provider._normalize(element, ORIGIN["latitude"], ORIGIN["longitude"])
    assert facility.address == "Point Pedro"


def test_unnamed_elements_are_dropped():
    provider = OsmProvider()
    element = {"type": "node", "id": 9, "lat": 9.8, "lon": 80.2, "tags": {"healthcare": "clinic"}}
    assert provider._normalize(element, ORIGIN["latitude"], ORIGIN["longitude"]) is None


def test_way_elements_use_center_coordinates():
    provider = OsmProvider()
    element = {
        "type": "way",
        "id": 11,
        "center": {"lat": 9.8180, "lon": 80.2340},
        "tags": {"name": "Base Hospital", "healthcare": "hospital"},
    }
    facility = provider._normalize(element, ORIGIN["latitude"], ORIGIN["longitude"])
    assert facility is not None
    assert facility.kind == "hospital"
    assert facility.maps_url == "https://www.openstreetmap.org/way/11"


# -- Search plumbing -----------------------------------------------------------

def test_search_queries_overpass_with_radius_and_all_tagging_schemes():
    provider = OsmProvider()
    provider._request_overpass = mock.Mock(return_value=[])
    provider.search("", "any", 5, **ORIGIN)
    query = provider._request_overpass.call_args.args[0]
    assert "around:5000" in query
    assert '"healthcare"' in query
    assert "amenity" in query


def test_search_rejects_unsupported_kind():
    provider = OsmProvider()
    try:
        provider.search("", "spa", 5, **ORIGIN)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unsupported kind")


def test_lab_alias_maps_to_laboratory():
    provider = OsmProvider()
    provider._request_overpass = mock.Mock(return_value=[])
    provider.search("", "lab", 5, **ORIGIN)
    query = provider._request_overpass.call_args.args[0]
    assert "laboratory" in query


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
