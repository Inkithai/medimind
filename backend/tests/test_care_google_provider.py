"""Offline regression tests for the Google Places care adapter."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.errors import CareConfigurationError  # noqa: E402
from care.providers.google import GoogleProvider  # noqa: E402


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


def test_non_finite_search_values_are_rejected_before_provider_request():
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": []})

    invalid_calls = [
        {"radius_km": float("nan")},
        {"radius_km": float("inf")},
        {"radius_km": 5, "latitude": float("nan"), "longitude": 80.0},
        {"radius_km": 5, "latitude": 91.0, "longitude": 80.0},
        {"radius_km": 5, "latitude": 9.0, "longitude": 181.0},
    ]
    for values in invalid_calls:
        try:
            provider.search(
                "Jaffna",
                "hospital",
                values["radius_km"],
                latitude=values.get("latitude"),
                longitude=values.get("longitude"),
            )
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid search values should be rejected: {values}")

    provider._request_json.assert_not_called()


def test_specialty_search_uses_location_bias_and_transparent_ranking():
    cardiology = {
        **GOOGLE_PLACE,
        "id": "cardiology",
        "displayName": {"text": "Northern Cardiology Centre"},
        "location": {"latitude": 9.67, "longitude": 80.017},
        "rating": 4.7,
        "currentOpeningHours": {"openNow": True},
    }
    general = {
        **GOOGLE_PLACE,
        "id": "general",
        "displayName": {"text": "General Medical Centre"},
        "location": {"latitude": 9.669, "longitude": 80.016},
        "rating": 4.9,
        "currentOpeningHours": {"openNow": False},
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [general, cardiology]})

    results = provider.search(
        "Jaffna",
        "doctor",
        8,
        latitude=9.668,
        longitude=80.015,
        specialty="cardiology",
        availability="today",
    )

    operation, payload = provider._request_json.call_args.args
    assert operation == "places:searchText"
    assert payload["textQuery"] == "cardiology in Jaffna"
    assert payload["locationBias"]["circle"]["radius"] == 8000
    assert results[0].id == "cardiology"
    assert results[0].specialty == "cardiology (directory search match)"
    assert results[0].availability_match is True
    assert "specialty search match" in results[0].ranking_reason


def test_malformed_provider_coordinates_are_skipped_without_breaking_results():
    malformed = {
        **GOOGLE_PLACE,
        "id": "bad-coordinates",
        "location": {"latitude": float("nan"), "longitude": 80.015},
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [malformed, GOOGLE_PLACE]})

    results = provider.search("Jaffna", "hospital", 8)

    assert [facility.id for facility in results] == ["ChIJ-care-1"]


def test_eye_clinic_with_doctor_type_is_not_classified_as_doctor():
    # Google returns "doctor" inside types for many businesses, but the
    # authoritative primaryType is eye_care. It must not be a "Doctor".
    eye_clinic = {
        **GOOGLE_PLACE,
        "id": "child-eye",
        "displayName": {"text": "Child Eye (Pvt) Ltd"},
        "types": ["doctor", "health", "eye_care"],
        "primaryType": "eye_care",
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [eye_clinic]})

    results = provider.search("Rajagiriya", "any", 5)

    assert len(results) == 1
    assert results[0].kind != "doctor"


def test_non_healthcare_entity_is_dropped_instead_of_becoming_doctor():
    # A students' committee / government office with no recognized
    # healthcare type must not reach the UI at all.
    committee = {
        **GOOGLE_PLACE,
        "id": "committee",
        "displayName": {"text": "Indigenous Medical Students' Committee"},
        "types": ["university", "point_of_interest", "establishment"],
        "primaryType": None,
    }
    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [committee, GOOGLE_PLACE]})

    results = provider.search("Rajagiriya", "any", 5)

    assert [facility.id for facility in results] == ["ChIJ-care-1"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
