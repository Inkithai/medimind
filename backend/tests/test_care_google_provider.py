"""Offline regression tests for the Google Places care adapter."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.errors import CareConfigurationError  # noqa: E402
from care.providers.google import (  # noqa: E402
    FACILITY_KINDS,
    GoogleProvider,
    google_maps_url,
    normalize_kind,
)


GOOGLE_PLACE = {
    "id": "ChIJ-care-1",
    "displayName": {"text": "Jaffna Teaching Hospital", "languageCode": "en"},
    "formattedAddress": "Hospital Road, Jaffna, Sri Lanka",
    "location": {"latitude": 9.668, "longitude": 80.015},
    "types": ["hospital", "health"],
    "primaryType": "hospital",
    "rating": 4.2,
    "userRatingCount": 321,
    "googleMapsUri": "https://maps.google.com/?cid=1",
    "internationalPhoneNumber": "+94 21 222 2261",
    "regularOpeningHours": {"weekdayDescriptions": ["Monday: Open 24 hours"]},
    "currentOpeningHours": {"openNow": True},
}


def test_text_search_calls_places_new_and_normalizes_facility():
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [GOOGLE_PLACE]})

    results = provider.search("Jaffna", "hospital", 8)

    operation, payload = provider._request_json.call_args.args
    assert operation == "places:searchText"
    assert payload["textQuery"] == "hospitals in Jaffna"
    assert payload["includedType"] == "hospital"
    assert len(results) == 1
    facility = results[0]
    assert facility.id == "ChIJ-care-1"
    assert facility.name == "Jaffna Teaching Hospital"
    assert facility.kind == "hospital"
    assert facility.rating == 4.2
    assert facility.source == "Google Places public listing"


def test_coordinates_use_nearby_search_and_distance_order():
    farther = {
        **GOOGLE_PLACE,
        "id": "farther",
        "displayName": {"text": "Farther Hospital"},
        "location": {"latitude": 9.70, "longitude": 80.05},
    }
    nearer = {
        **GOOGLE_PLACE,
        "id": "nearer",
        "displayName": {"text": "Nearby Hospital"},
        "location": {"latitude": 9.669, "longitude": 80.016},
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [farther, nearer]})

    results = provider.search(
        "Jaffna",
        "hospital",
        8,
        latitude=9.668,
        longitude=80.015,
    )

    operation, payload = provider._request_json.call_args.args
    assert operation == "places:searchNearby"
    circle = payload["locationRestriction"]["circle"]
    assert circle["radius"] == 8000
    assert payload["rankPreference"] == "DISTANCE"
    assert [facility.id for facility in results] == ["nearer", "farther"]
    assert results[0].distance_km is not None


def test_rest_request_keeps_key_in_header_and_uses_places_new_endpoint():
    response = mock.MagicMock()
    response.__enter__.return_value.read.return_value = b'{"places": []}'
    provider = GoogleProvider(api_key="AIza-test-key", timeout_seconds=3)

    with mock.patch("care.providers.google.urlopen", return_value=response) as mocked_open:
        result = provider._request_json("places:searchText", {"textQuery": "hospitals in Jaffna"})

    assert result == {"places": []}
    request = mocked_open.call_args.args[0]
    assert request.full_url == "https://places.googleapis.com/v1/places:searchText"
    assert "AIza-test-key" not in request.full_url
    headers = {key.lower(): value for key, value in request.header_items()}
    assert headers["x-goog-api-key"] == "AIza-test-key"
    assert "places.displayName" in headers["x-goog-fieldmask"]


def test_no_results_is_a_valid_empty_list():
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={})
    assert provider.search("Jaffna", "clinic", 8) == []


def test_placeholder_key_fails_with_actionable_configuration_error():
    try:
        GoogleProvider(api_key="AI")
    except CareConfigurationError as error:
        assert "GOOGLE_MAPS_API_KEY" in str(error)
        assert "Places API (New)" in str(error)
    else:
        raise AssertionError("placeholder key should have been rejected")


def test_kind_normalization_is_exhaustive_and_never_drops_a_listing():
    """Every listing lands in exactly one UI category (BUG-001/BUG-013)."""
    assert normalize_kind("hospital", ["health"], "any") == "hospital"
    assert normalize_kind("general_hospital", [], "any") == "hospital"
    assert normalize_kind("medical_clinic", [], "any") == "clinic"
    assert normalize_kind("medical_center", [], "any") == "clinic"
    assert normalize_kind("pharmacy", [], "any") == "pharmacy"
    assert normalize_kind("drugstore", [], "any") == "pharmacy"
    assert normalize_kind("medical_lab", [], "any") == "laboratory"
    assert normalize_kind("doctor", [], "any") == "doctor"
    assert normalize_kind("dentist", [], "any") == "doctor"
    # An unclassifiable healthcare listing is bucketed, never discarded.
    assert normalize_kind("point_of_interest", ["establishment"], "any") == "other"
    assert normalize_kind(None, [], "lab") == "laboratory"
    for value in ("hospital", "clinic", "pharmacy", "laboratory", "doctor", "other"):
        assert normalize_kind(None, [], value) in FACILITY_KINDS


def test_search_results_all_carry_a_renderable_kind():
    """The count of results equals the count assignable to a chip."""
    places = [
        {**GOOGLE_PLACE, "id": "a", "primaryType": "pharmacy", "types": ["pharmacy"]},
        {**GOOGLE_PLACE, "id": "b", "primaryType": "medical_lab", "types": ["medical_lab"]},
        {**GOOGLE_PLACE, "id": "c", "primaryType": "spa", "types": ["establishment"]},
    ]
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": places})

    results = provider.search("Jaffna", "any", 8)

    assert len(results) == 3
    assert [facility.kind for facility in results] == ["pharmacy", "laboratory", "other"]
    assert all(facility.kind in FACILITY_KINDS for facility in results)


def test_missing_fields_stay_none_and_are_never_fabricated():
    sparse = {
        "id": "sparse",
        "displayName": {"text": "Village Dispensary"},
        "location": {"latitude": 9.66, "longitude": 80.01},
        "types": ["medical_clinic"],
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [sparse]})

    facility = provider.search("Jaffna", "clinic", 8)[0]

    assert facility.name == "Village Dispensary"
    assert facility.rating is None
    assert facility.user_rating_count is None
    assert facility.phone is None
    assert facility.address is None
    assert facility.opening_hours is None
    assert facility.open_now is None


def test_unnamed_listing_is_dropped_rather_than_given_a_generic_name():
    """Never show "Clinic" where a real provider name belongs."""
    unnamed = {
        "id": "unnamed",
        "displayName": {"text": "   "},
        "location": {"latitude": 9.66, "longitude": 80.01},
        "types": ["medical_clinic"],
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [unnamed]})

    assert provider.search("Jaffna", "clinic", 8) == []


def test_maps_url_always_points_at_google_maps():
    without_uri = {key: value for key, value in GOOGLE_PLACE.items() if key != "googleMapsUri"}
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [without_uri]})

    facility = provider.search("Jaffna", "hospital", 8)[0]

    assert facility.maps_url is not None
    assert facility.maps_url.startswith("https://www.google.com/maps/")
    assert "openstreetmap" not in facility.maps_url.lower()
    # Built from the facility's real name + address.
    assert "Jaffna+Teaching+Hospital" in facility.maps_url


def test_google_maps_url_falls_back_to_coordinates_without_a_name():
    url = google_maps_url(None, None, 9.668, 80.015)
    assert url == "https://www.google.com/maps/search/?api=1&query=9.668%2C80.015"


def test_specialty_uses_text_search_biased_to_the_selected_circle():
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [GOOGLE_PLACE]})

    results = provider.search(
        "Jaffna",
        "any",
        8,
        latitude=9.668,
        longitude=80.015,
        specialty="gastroenterologist",
    )

    operation, payload = provider._request_json.call_args.args
    assert operation == "places:searchText"
    assert "gastroenterologist" in payload["textQuery"]
    assert payload["locationBias"]["circle"]["radius"] == 8000
    assert results[0].distance_km is not None


def test_specialty_match_flag_is_none_when_no_specialty_requested():
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [GOOGLE_PLACE]})
    assert provider.search("Jaffna", "hospital", 8)[0].specialty_match is None


def test_specialty_match_flag_reflects_the_listing_not_a_guess():
    matching = {
        **GOOGLE_PLACE,
        "id": "match",
        "displayName": {"text": "Colombo Gastroenterology Centre"},
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [matching, GOOGLE_PLACE]})

    results = provider.search("Colombo", "any", 8, specialty="gastroenterologist")

    assert results[0].specialty_match is True
    assert results[1].specialty_match is False


def test_results_outside_the_radius_are_trimmed_for_specialty_searches():
    far_away = {
        **GOOGLE_PLACE,
        "id": "far",
        "displayName": {"text": "Distant Hospital"},
        "location": {"latitude": 10.5, "longitude": 80.9},
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [GOOGLE_PLACE, far_away]})

    results = provider.search(
        "Jaffna", "any", 5, latitude=9.668, longitude=80.015, specialty="cardiologist"
    )

    assert [facility.id for facility in results] == ["ChIJ-care-1"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
