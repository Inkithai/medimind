"""Offline regression tests for the keyless OpenStreetMap care adapter."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.errors import CareProviderError  # noqa: E402
from care.providers.osm import OpenStreetMapProvider  # noqa: E402


HOSPITAL_NODE = {
    "type": "node",
    "id": 123456,
    "lat": 9.669,
    "lon": 80.016,
    "tags": {
        "name": "Jaffna Teaching Hospital",
        "amenity": "hospital",
        "addr:street": "Hospital Road",
        "addr:city": "Jaffna",
        "phone": "+94 21 222 2261",
        "website": "https://example.lk",
        "opening_hours": "24/7",
    },
}

PHARMACY_WAY = {
    "type": "way",
    "id": 777,
    "center": {"lat": 9.70, "lon": 80.05},
    "tags": {"name": "City Pharmacy", "healthcare": "pharmacy"},
}


def _provider():
    return OpenStreetMapProvider(endpoints=["https://overpass.test/api/interpreter"], timeout_seconds=5)


def test_coordinate_search_normalizes_and_orders_by_distance():
    provider = _provider()
    provider._overpass_json = mock.Mock(return_value={"elements": [PHARMACY_WAY, HOSPITAL_NODE]})

    results = provider.search("Jaffna", "any", 8, latitude=9.668, longitude=80.015)

    assert [facility.name for facility in results] == ["Jaffna Teaching Hospital", "City Pharmacy"]
    hospital = results[0]
    assert hospital.kind == "hospital"
    assert hospital.id == "osm:node:123456"
    assert hospital.address == "Hospital Road, Jaffna"
    assert hospital.phone == "+94 21 222 2261"
    assert hospital.open_now is True
    assert hospital.distance_km is not None and hospital.distance_km < 1
    assert hospital.source == "OpenStreetMap public listing"
    assert results[1].kind == "pharmacy"


def test_query_uses_requested_kind_and_radius():
    provider = _provider()
    provider._overpass_json = mock.Mock(return_value={"elements": []})

    provider.search("", "hospital", 5, latitude=9.668, longitude=80.015)

    query = provider._overpass_json.call_args.args[0]
    assert '["amenity"="hospital"]' in query
    assert '["amenity"="pharmacy"]' not in query
    assert "(around:5000,9.668000,80.015000)" in query


def test_text_only_search_geocodes_before_querying():
    provider = _provider()
    provider._geocode = mock.Mock(return_value=(9.668, 80.015))
    provider._overpass_json = mock.Mock(return_value={"elements": [HOSPITAL_NODE]})

    results = provider.search("Jaffna", "hospital", 8)

    provider._geocode.assert_called_once_with("Jaffna")
    assert len(results) == 1


def test_unnamed_and_malformed_elements_are_skipped():
    provider = _provider()
    provider._overpass_json = mock.Mock(
        return_value={
            "elements": [
                {"type": "node", "id": 1, "lat": 9.6, "lon": 80.0, "tags": {"amenity": "hospital"}},
                {"type": "node", "id": 2, "tags": {"name": "No coordinates", "amenity": "clinic"}},
                "not-a-dict",
                HOSPITAL_NODE,
            ]
        }
    )

    results = provider.search("", "any", 8, latitude=9.668, longitude=80.015)

    assert [facility.id for facility in results] == ["osm:node:123456"]


def test_mirror_failover_tries_next_endpoint():
    provider = OpenStreetMapProvider(
        endpoints=["https://down.test/api", "https://up.test/api"], timeout_seconds=5
    )
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b'{"elements": []}'

    with mock.patch(
        "care.providers.osm.urlopen",
        side_effect=[OSError("boom"), response],
    ) as mocked_open:
        assert provider._overpass_json("[out:json];") == {"elements": []}

    assert mocked_open.call_count == 2
    assert mocked_open.call_args_list[1].args[0].full_url == "https://up.test/api"


def test_all_mirrors_down_raises_provider_error():
    provider = OpenStreetMapProvider(endpoints=["https://a.test", "https://b.test"], timeout_seconds=5)
    with mock.patch("care.providers.osm.urlopen", side_effect=OSError("boom")):
        try:
            provider._overpass_json("[out:json];")
        except CareProviderError as error:
            assert "Overpass" in str(error)
        else:
            raise AssertionError("expected CareProviderError")


def test_unsupported_kind_is_a_value_error():
    provider = _provider()
    try:
        provider.search("Jaffna", "dentist", 5)
    except ValueError as error:
        assert "Unsupported facility type" in str(error)
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
