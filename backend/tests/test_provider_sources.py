"""Focused safety/compliance tests for live directory source adapters.

No provider record is included in these tests. The mocked source responses are
limited to geocoding and empty result sets, ensuring no directory data can leak
from test fixtures into a production response.
"""

import os
import socket
import sys
from unittest import mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import provider_sources as sources
from provider_ranking import ranking_method_description


def test_google_places_uses_explicit_field_mask_and_location_bias():
    google = sources.GooglePlacesSource("backend-only-test-key")
    with mock.patch.object(
        sources,
        "_read_json",
        side_effect=[
            {
                "status": "OK",
                "results": [
                    {
                        "formatted_address": "Resolved Area",
                        "geometry": {"location": {"lat": 1.2, "lng": 3.4}},
                    }
                ],
            },
            {"places": []},
        ],
    ) as request:
        payload = google.search("Example Area", {"provider_query": "pharmacy"})

    assert payload.records == []
    assert payload.source_id == "google_places"
    _, search_kwargs = request.call_args
    assert search_kwargs["method"] == "POST"
    assert "X-Goog-Api-Key" in search_kwargs["headers"]
    assert "places.businessStatus" not in search_kwargs["headers"]["X-Goog-FieldMask"]
    assert "places.displayName" in search_kwargs["headers"]["X-Goog-FieldMask"]
    assert search_kwargs["body"]["locationBias"]["circle"]["center"] == {
        "latitude": 1.2,
        "longitude": 3.4,
    }


def test_osm_uses_identifying_user_agent_spacing_and_bounded_form_query():
    osm = sources.OpenStreetMapSource("MediMindTests/1.0 (contact: test@example.invalid)")
    with (
        mock.patch.object(sources, "_respect_osm_request_spacing") as spacing,
        mock.patch.object(
            sources,
            "_read_json",
            side_effect=[
                [{"display_name": "Resolved Area", "lat": "1.2", "lon": "3.4"}],
                {"elements": []},
            ],
        ) as request,
    ):
        payload = osm.search("Example Area", {"provider_query": "pharmacy"})

    assert payload.records == []
    assert "© OpenStreetMap contributors" in payload.source_label
    assert spacing.call_count == 2
    geocode_call, overpass_call = request.call_args_list
    assert geocode_call.kwargs["headers"]["User-Agent"].startswith("MediMindTests/")
    assert overpass_call.kwargs["method"] == "POST"
    assert "form_body" in overpass_call.kwargs
    assert "around:" in overpass_call.kwargs["form_body"]["data"]
    assert "pharmacy" in overpass_call.kwargs["form_body"]["data"]


def test_http_or_network_timeouts_remain_distinct_from_zero_results():
    with mock.patch.object(
        sources,
        "urlopen",
        side_effect=HTTPError("https://example.test", 504, "timeout", None, None),
    ):
        try:
            sources._read_json("https://example.test")
            raise AssertionError("expected ProviderSearchError")
        except sources.ProviderSearchError as exc:
            assert exc.code == "provider_timeout"
            assert exc.http_status == 504

    with mock.patch.object(sources, "urlopen", side_effect=URLError(socket.timeout("timed out"))):
        try:
            sources._read_json("https://example.test")
            raise AssertionError("expected ProviderSearchError")
        except sources.ProviderSearchError as exc:
            assert exc.code == "provider_timeout"
            assert exc.http_status == 504


def test_auto_source_uses_geoapify_when_keyed_and_osm_otherwise():
    os.environ.pop("PROVIDER_DIRECTORY_SOURCE", None)
    os.environ["GEOAPIFY_API_KEY"] = "abc123realkey"
    try:
        source = sources.get_provider_source()
        assert isinstance(source, sources.HybridDirectorySource)
        with mock.patch.object(
            sources,
            "_read_json",
            side_effect=[
                {"results": [{"formatted": "Kandy", "lat": 7.29, "lon": 80.63}]},
                {
                    "features": [
                        {"type": "Feature", "properties": {"name": "Clinic", "place_id": "x"}}
                    ]
                },
            ],
        ):
            payload = source.search("Kandy", {"id": "cardiology", "provider_query": "cardiologist"})
        assert payload.source_id == "geoapify"
        assert payload.source_label == "Geoapify"
        assert payload.records
    finally:
        os.environ.pop("GEOAPIFY_API_KEY", None)

    os.environ.pop("GEOAPIFY_API_KEY", None)
    source = sources.get_provider_source()
    assert isinstance(source, sources.HybridDirectorySource)
    with (
        mock.patch.object(sources, "_respect_osm_request_spacing"),
        mock.patch.object(
            sources,
            "_read_json",
            side_effect=[
                [{"display_name": "Kandy", "lat": "7.29", "lon": "80.63"}],
                {"elements": []},
            ],
        ),
    ):
        payload = source.search("Kandy", {"id": "cardiology", "provider_query": "cardiologist"})
    assert payload.source_id == "openstreetmap"


def test_directory_match_description_never_claims_clinical_quality():
    description = ranking_method_description().lower()
    assert "directory match" in description
    assert "do not measure clinical quality" in description
    assert "appointment availability" in description
