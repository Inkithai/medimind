"""Offline tests for specialty suggestion, opening-hours matching, ranking,
geocode/directory failures, Geoapify primary, and OSM fallback."""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import care_finder as cf


DIABETES_TIMELINE = {
    "medications_timeline": [
        {"name": "Metformin", "ingredients": ["Metformin"], "dosage": "500 mg"},
    ],
    "lab_results_timeline": [
        {"test_name": "HbA1c", "value": "8.1", "flag": "high"},
    ],
    "known_allergies": ["Penicillin"],
    "visits": [{"clinical_notes": "Follow-up for type 2 diabetes."}],
}


def test_diabetes_record_suggests_endocrinology():
    out = cf.suggest_specialties(DIABETES_TIMELINE)
    assert out["suggested"]["id"] == "endocrinology"
    joined = " ".join(out["suggested"]["reasons"]).lower()
    assert "metformin" in joined or "hba1c" in joined
    assert out["has_records"] is True
    allergy_ids = {item["id"] for item in out["alternatives"]} | {out["suggested"]["id"]}
    assert "allergy_immunology" in allergy_ids or any(
        "allerg" in r.lower() for alt in out["alternatives"] for r in alt["reasons"]
    )


def test_empty_record_defaults_to_general_practice():
    out = cf.suggest_specialties(None)
    assert out["suggested"]["id"] == "general_practice"
    assert out["has_records"] is False


def test_opening_hours_weekday_morning_is_open():
    hours = "Mo-Fr 08:00-17:00; Sa 09:00-12:00"
    assert cf.availability_status(hours, ["mon", "tue"], "morning") == "open"
    assert cf.availability_status(hours, ["sat"], "morning") == "open"
    assert cf.availability_status(hours, ["sat"], "evening") == "closed"
    assert cf.availability_status(hours, ["sun"], "any") == "closed"
    assert cf.availability_status("24/7", ["sun"], "evening") == "open"
    assert cf.availability_status(None, ["mon"], "morning") == "unknown"
    assert cf.availability_status("by appointment", ["mon"], "morning") == "unknown"


def test_city_not_found_is_not_retryable():
    def empty_geocode(_url, **_kwargs):
        return []

    try:
        cf.geocode_city("zzzznotacity", http_json=empty_geocode)
    except cf.CityNotFoundError as exc:
        assert exc.code == "city_not_found"
        assert exc.retryable is False
    else:
        raise AssertionError("expected CityNotFoundError")


def test_directory_outage_is_retryable():
    def boom(_url, **_kwargs):
        raise cf.DirectoryUnavailableError()

    try:
        cf.geocode_city("Kandy", http_json=boom)
    except cf.DirectoryUnavailableError as exc:
        assert exc.retryable is True
        assert exc.code == "directory_unavailable"
    else:
        raise AssertionError("expected DirectoryUnavailableError")


def _osm_geocode(city):
    return {"lat": 7.29, "lon": 80.63, "label": "Kandy, Sri Lanka", "source": "OpenStreetMap Nominatim"}


def _osm_places(lat, lon, radius_m):
    return [
        {
            "type": "node",
            "id": 1,
            "lat": 7.291,
            "lon": 80.633,
            "tags": {
                "name": "Kandy Diabetes Clinic",
                "amenity": "clinic",
                "healthcare:speciality": "endocrinology",
                "phone": "+94 81 0000000",
                "opening_hours": "Mo-Fr 08:00-16:00",
                "addr:city": "Kandy",
            },
        },
        {
            "type": "node",
            "id": 2,
            "lat": 7.295,
            "lon": 80.640,
            "tags": {
                "name": "Neighbourhood GP",
                "amenity": "doctors",
                "opening_hours": "Mo-Fr 09:00-12:00",
            },
        },
        {
            "type": "way",
            "id": 3,
            "center": {"lat": 7.30, "lon": 80.65},
            "tags": {"name": "Teaching Hospital Kandy", "amenity": "hospital"},
        },
    ]


def test_search_ranks_specialty_match_above_generic_and_handles_zero():
    result = cf.search_care(
        city="Kandy",
        specialty_id="endocrinology",
        days=["mon"],
        time_of_day="morning",
        timeline=DIABETES_TIMELINE,
        geocode=_osm_geocode,
        fetch_places=_osm_places,
    )
    assert result["result_count"] == 3
    assert result["results"][0]["name"] == "Kandy Diabetes Clinic"
    assert result["results"][0]["match_kind"] == "specialty"
    assert result["results"][0]["availability"] == "open"
    assert result["results"][0]["source"] == "OpenStreetMap"
    assert "openstreetmap.org/node/1" in result["results"][0]["source_url"]
    assert result["source"]["name"] == "OpenStreetMap"
    assert result["source"]["geocoder"] == "Nominatim"
    assert result["source"]["directory"] == "Overpass API"
    assert "fallback_from" not in result["source"]
    assert "not a medical referral" in result["disclaimer"].lower()
    assert "failed" not in result["disclaimer"].lower()
    assert "google" not in result["disclaimer"].lower()

    empty = cf.search_care(
        city="Kandy",
        specialty_id="endocrinology",
        geocode=_osm_geocode,
        fetch_places=lambda *a: [],
    )
    assert empty["results"] == []
    assert empty["zero_results_hint"]
    assert "km" in empty["zero_results_hint"]
    assert empty["source"]["name"] == "OpenStreetMap"


def test_unknown_specialty_falls_back_to_general_practice():
    result = cf.search_care(
        city="Kandy",
        specialty_id="not_a_real_specialty",
        geocode=_osm_geocode,
        fetch_places=lambda *a: [],
    )
    assert result["query"]["specialty_id"] == "general_practice"


def test_geoapify_key_ignores_placeholders():
    os.environ.pop("GEOAPIFY_API_KEY", None)
    assert cf.geoapify_configured() is False
    os.environ["GEOAPIFY_API_KEY"] = "your-geoapify-api-key"
    try:
        assert cf.geoapify_configured() is False
        os.environ["GEOAPIFY_API_KEY"] = "abc123realkey"
        assert cf.geoapify_key() == "abc123realkey"
    finally:
        os.environ.pop("GEOAPIFY_API_KEY", None)


def test_geoapify_is_primary_when_configured():
    os.environ["GEOAPIFY_API_KEY"] = "abc123realkey"
    geo_payload = cf._pack_search(
        city="Kandy",
        chosen_id="endocrinology",
        chosen_label="Endocrinology / diabetes",
        wanted_days=["mon"],
        tod="morning",
        radius_km_used=8.0,
        location={"lat": 7.29, "lon": 80.63, "label": "Kandy, Sri Lanka", "source": "Geoapify Geocoding"},
        suggestion=cf.suggest_specialties(None),
        places=[{
            "id": "geoapify/abc",
            "name": "Kandy Endocrine Centre",
            "place_type": "clinic",
            "match_kind": "specialty",
            "specialties": ["endocrinology"],
            "address": "Kandy",
            "phone": "+94 81 111",
            "website": None,
            "opening_hours": "Mo-Fr 08:00-16:00",
            "availability": "open",
            "lat": 7.29,
            "lon": 80.63,
            "distance_km": 0.2,
            "score": 170,
            "source": "Geoapify",
            "source_url": "https://www.openstreetmap.org/?mlat=7.29&mlon=80.63",
        }],
        source=cf.SOURCE_GEOAPIFY,
    )
    try:
        with mock.patch.object(cf, "_search_geoapify", return_value=geo_payload):
            hit = cf.search_care(city="Kandy", specialty_id="endocrinology")
        assert hit["results"][0]["source"] == "Geoapify"
        assert hit["source"]["name"] == "Geoapify"
        assert hit["source"]["directory"] == "Geoapify Places API"
        assert "fallback_from" not in hit["source"]
        assert "failed" not in hit["disclaimer"].lower()
    finally:
        os.environ.pop("GEOAPIFY_API_KEY", None)


def test_osm_used_when_geoapify_unavailable_or_empty():
    os.environ["GEOAPIFY_API_KEY"] = "abc123realkey"
    try:
        with mock.patch.object(cf, "_search_geoapify", side_effect=cf.DirectoryUnavailableError("quota")), \
             mock.patch.object(cf, "geocode_city", _osm_geocode), \
             mock.patch.object(cf, "fetch_osm_places", _osm_places):
            cascaded = cf.search_care(city="Kandy", specialty_id="endocrinology")
        assert cascaded["results"][0]["name"] == "Kandy Diabetes Clinic"
        assert cascaded["source"]["name"] == "OpenStreetMap"
        assert "fallback_from" not in cascaded["source"]
        assert "failed" not in cascaded["disclaimer"].lower()
        assert "geoapify" not in cascaded["disclaimer"].lower()

        empty_geo = cf._pack_search(
            city="Kandy",
            chosen_id="endocrinology",
            chosen_label="Endocrinology / diabetes",
            wanted_days=["mon"],
            tod="any",
            radius_km_used=8.0,
            location={"lat": 7.29, "lon": 80.63, "label": "Kandy", "source": "Geoapify Geocoding"},
            suggestion=cf.suggest_specialties(None),
            places=[],
            source=cf.SOURCE_GEOAPIFY,
        )
        with mock.patch.object(cf, "_search_geoapify", return_value=empty_geo), \
             mock.patch.object(cf, "geocode_city", _osm_geocode), \
             mock.patch.object(cf, "fetch_osm_places", _osm_places):
            after_zero = cf.search_care(city="Kandy", specialty_id="endocrinology")
        assert after_zero["source"]["name"] == "OpenStreetMap"
        assert after_zero["results"][0]["name"] == "Kandy Diabetes Clinic"
    finally:
        os.environ.pop("GEOAPIFY_API_KEY", None)


def test_geoapify_normalizes_specialty_from_categories():
    feature = {
        "type": "Feature",
        "properties": {
            "name": "Kandy Endocrine Centre",
            "lat": 7.291,
            "lon": 80.633,
            "formatted": "Peradeniya Rd, Kandy",
            "categories": ["healthcare.clinic_or_praxis.endocrinology"],
            "place_id": "abc",
            "datasource": {"raw": {"phone": "+94 81 000", "opening_hours": "Mo-Fr 08:00-16:00"}},
        },
        "geometry": {"type": "Point", "coordinates": [80.633, 7.291]},
    }
    place = cf._normalize_geoapify_place(
        feature,
        origin={"lat": 7.29, "lon": 80.63},
        specialty_id="endocrinology",
        days=["mon"],
        time_of_day="morning",
        radius_km=8.0,
    )
    assert place is not None
    assert place["source"] == "Geoapify"
    assert place["match_kind"] == "specialty"
    assert place["availability"] == "open"
    assert place["phone"] == "+94 81 000"
    assert "endocrinology" in place["specialties"]


def test_stack_is_geoapify_then_osm():
    assert not hasattr(cf, "google_places_key")
    assert not hasattr(cf, "fetch_google_places")
    assert cf.SOURCE_GEOAPIFY["name"] == "Geoapify"
    assert cf.SOURCE_OSM["name"] == "OpenStreetMap"
    assert callable(cf.geoapify_key)
    assert callable(cf.fetch_geoapify_places)
    assert callable(cf.fetch_osm_places)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
