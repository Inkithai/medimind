"""Care Navigation provider resilience.

The deployed 500s came from a bare RuntimeError escaping the OSM adapter
whenever the public Overpass instance rate-limited or timed out. These tests
pin the new contract: typed ProviderUnavailableError, mirror failover, brief
retries, in-process caching, and a clean 503 mapping in the service layer.
They inject fakes — they never touch the network.
"""

import urllib.error
from unittest import mock

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.models import GeoPoint
from care.providers.base import ProviderUnavailableError
from care.providers.osm import OsmProvider, _fetch_json
from care.service import CareNavigationError, CareNavigationService

ORIGIN = GeoPoint(7.2906, 80.6337, "Kandy, Sri Lanka", "test")
OVERPASS_A = "https://overpass-a.example/api/interpreter"
OVERPASS_B = "https://overpass-b.example/api/interpreter"
ELEMENTS = {
    "elements": [
        {
            "type": "node",
            "id": 9,
            "lat": 7.30,
            "lon": 80.64,
            "tags": {"name": "General Hospital", "amenity": "hospital"},
        }
    ]
}


def _provider(http_json, **kwargs):
    kwargs.setdefault("overpass_urls", [OVERPASS_A, OVERPASS_B])
    kwargs.setdefault("backoff_seconds", 0)
    return OsmProvider(http_json=http_json, **kwargs)


def test_fails_over_to_next_mirror_on_transient_error():
    calls = []

    def http_json(url, data=None):
        calls.append(url)
        if url == OVERPASS_A:
            raise ProviderUnavailableError("HTTP 429", retryable=True)
        return ELEMENTS

    facilities = _provider(http_json).search_nearby(ORIGIN, "hospital", 5000)
    assert len(facilities) == 1
    assert facilities[0].name == "General Hospital"
    # Both attempts on the first mirror, then the failover mirror.
    assert calls[:2] == [OVERPASS_A, OVERPASS_A]
    assert calls[-1] == OVERPASS_B


def test_non_retryable_error_skips_failover_and_retries():
    calls = []

    def http_json(url, data=None):
        calls.append(url)
        raise ProviderUnavailableError("HTTP 400 — bad query", retryable=False)

    with pytest.raises(ProviderUnavailableError):
        _provider(http_json).search_nearby(ORIGIN, "hospital", 5000)
    assert calls == [OVERPASS_A]


def test_all_mirrors_down_raises_typed_error():
    def http_json(url, data=None):
        raise ProviderUnavailableError("HTTP 504", retryable=True)

    provider = _provider(http_json)
    with pytest.raises(ProviderUnavailableError) as exc:
        provider.search_nearby(ORIGIN, "any", 5000)
    assert "temporarily unavailable" in str(exc.value)


def test_identical_searches_are_cached():
    calls = []

    def http_json(url, data=None):
        calls.append(url)
        return ELEMENTS

    provider = _provider(http_json)
    first = provider.search_nearby(ORIGIN, "hospital", 5000)
    second = provider.search_nearby(ORIGIN, "hospital", 5000)
    assert len(calls) == 1
    assert first[0].name == second[0].name


def test_cache_disabled_with_zero_ttl():
    calls = []

    def http_json(url, data=None):
        calls.append(url)
        return ELEMENTS

    provider = _provider(http_json, search_cache_ttl=0)
    provider.search_nearby(ORIGIN, "hospital", 5000)
    provider.search_nearby(ORIGIN, "hospital", 5000)
    assert len(calls) == 2


def test_geocode_is_cached_and_normalizes_case():
    calls = []

    def http_json(url, data=None):
        calls.append(url)
        return [{"lat": "7.2906", "lon": "80.6337", "display_name": "Kandy, Sri Lanka"}]

    provider = _provider(http_json)
    one = provider.geocode("Kandy")
    two = provider.geocode("  kandy ")
    assert len(calls) == 1
    assert one == two
    assert one.latitude == 7.2906


def test_fetch_json_maps_retryable_http_status():
    error = urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(ProviderUnavailableError) as exc:
            _fetch_json("http://x")
    assert exc.value.retryable is True


def test_fetch_json_maps_permanent_http_status():
    error = urllib.error.HTTPError("http://x", 400, "Bad Request", {}, None)
    with mock.patch("urllib.request.urlopen", side_effect=error):
        with pytest.raises(ProviderUnavailableError) as exc:
            _fetch_json("http://x")
    assert exc.value.retryable is False


def test_fetch_json_maps_network_failure():
    with mock.patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        with pytest.raises(ProviderUnavailableError) as exc:
            _fetch_json("http://x")
    assert exc.value.retryable is True


def test_fetch_json_maps_unreadable_body():
    response = mock.MagicMock()
    response.read.return_value = b"<html>rate limited</html>"
    response.__enter__.return_value = response
    with mock.patch("urllib.request.urlopen", return_value=response):
        with pytest.raises(ProviderUnavailableError) as exc:
            _fetch_json("http://x")
    assert "unreadable" in str(exc.value)


class DownGeocoderProvider:
    name = "down"

    def geocode(self, query):
        raise ProviderUnavailableError("HTTP 429", retryable=True)

    def search_nearby(self, origin, kind, radius_m):
        return []

    def route(self, origin, destination):
        raise NotImplementedError


class DownDirectoryProvider(DownGeocoderProvider):
    def geocode(self, query):
        return GeoPoint(7.2906, 80.6337, "Kandy, Sri Lanka", self.name)

    def search_nearby(self, origin, kind, radius_m):
        raise ProviderUnavailableError("HTTP 504", retryable=True)


class DownRouteProvider(DownDirectoryProvider):
    def search_nearby(self, origin, kind, radius_m):
        return []

    def route(self, origin, destination):
        raise ProviderUnavailableError("boom", retryable=True)


def test_service_maps_geocoder_failure_to_503():
    service = CareNavigationService(DownGeocoderProvider())
    with pytest.raises(CareNavigationError) as exc:
        service.geocode("Kandy")
    assert exc.value.code == "geocoder_unavailable"
    assert exc.value.http_status == 503


def test_service_maps_directory_failure_to_503():
    service = CareNavigationService(DownDirectoryProvider())
    with pytest.raises(CareNavigationError) as exc:
        service.search_facilities(location="Kandy")
    assert exc.value.code == "directory_unavailable"
    assert exc.value.http_status == 503


def test_service_maps_router_failure_to_503():
    service = CareNavigationService(DownRouteProvider())
    with pytest.raises(CareNavigationError) as exc:
        service.get_route("Kandy", "Colombo")
    assert exc.value.code == "router_unavailable"
    assert exc.value.http_status == 503
