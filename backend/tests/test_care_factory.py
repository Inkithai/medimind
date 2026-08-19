"""Offline tests for care-provider selection and keyless fallback."""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.errors import CareConfigurationError, CareProviderError  # noqa: E402
from care.factory import FallbackProvider, get_care_provider  # noqa: E402
from care.models import Facility  # noqa: E402
from care.providers.google import GoogleProvider  # noqa: E402
from care.providers.osm_directory import OpenStreetMapProvider  # noqa: E402

FACILITY = Facility(id="a", name="A", kind="hospital", latitude=1.0, longitude=2.0)


class StubProvider:
    def __init__(self, name, results=None, error=None):
        self.name = name
        self.results = results if results is not None else []
        self.error = error
        self.calls = 0

    def search(self, location, kind, radius_km, **coordinates):
        self.calls += 1
        if self.error:
            raise self.error
        return self.results


def _env(**values):
    return mock.patch.dict(os.environ, values, clear=False)


def test_missing_care_provider_defaults_to_keyless_openstreetmap():
    with _env(CARE_PROVIDER=""):
        provider = get_care_provider()
    assert isinstance(provider, OpenStreetMapProvider)
    assert provider.name == "openstreetmap"


def test_explicit_osm_selection():
    with _env(CARE_PROVIDER="osm"):
        assert isinstance(get_care_provider(), OpenStreetMapProvider)


def test_google_without_usable_key_falls_back_instead_of_failing():
    with _env(CARE_PROVIDER="google", GOOGLE_MAPS_API_KEY="AI"):
        provider = get_care_provider()
    assert isinstance(provider, OpenStreetMapProvider)


def test_google_with_key_wraps_openstreetmap_fallback():
    with _env(CARE_PROVIDER="google", GOOGLE_MAPS_API_KEY="AIza-real-looking-key"):
        provider = get_care_provider()
    assert isinstance(provider, FallbackProvider)
    assert isinstance(provider.primary, GoogleProvider)
    assert isinstance(provider.fallback, OpenStreetMapProvider)
    assert provider.name == "google+openstreetmap"


def test_fallback_disabled_keeps_strict_google_behaviour():
    with _env(CARE_PROVIDER="google", GOOGLE_MAPS_API_KEY="AI", CARE_FALLBACK="off"):
        try:
            get_care_provider()
        except CareConfigurationError as error:
            assert "GOOGLE_MAPS_API_KEY" in str(error)
        else:
            raise AssertionError("expected CareConfigurationError")


def test_unsupported_provider_name_still_rejected():
    with _env(CARE_PROVIDER="mapbox"):
        try:
            get_care_provider()
        except CareConfigurationError as error:
            assert "mapbox" in str(error)
        else:
            raise AssertionError("expected CareConfigurationError")


def test_permission_denied_from_google_serves_openstreetmap_results():
    google = StubProvider(
        "google",
        error=CareProviderError(
            "Google Places API rejected the request (HTTP 403): PERMISSION_DENIED"
        ),
    )
    osm = StubProvider("openstreetmap", results=[FACILITY])
    provider = FallbackProvider(google, osm)

    results = provider.search("Jaffna", "hospital", 5, latitude=9.8, longitude=80.19)

    assert results == [FACILITY]
    assert google.calls == 1 and osm.calls == 1


def test_empty_primary_result_tries_fallback():
    google = StubProvider("google", results=[])
    osm = StubProvider("openstreetmap", results=[FACILITY])

    assert FallbackProvider(google, osm).search("Jaffna", "hospital", 5) == [FACILITY]


def test_successful_primary_result_skips_fallback():
    google = StubProvider("google", results=[FACILITY])
    osm = StubProvider("openstreetmap", results=[])

    assert FallbackProvider(google, osm).search("Jaffna", "hospital", 5) == [FACILITY]
    assert osm.calls == 0


def test_invalid_input_is_not_retried_against_fallback():
    google = StubProvider("google", error=ValueError("Unsupported facility type."))
    osm = StubProvider("openstreetmap", results=[FACILITY])
    try:
        FallbackProvider(google, osm).search("Jaffna", "dentist", 5)
    except ValueError:
        assert osm.calls == 0
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
