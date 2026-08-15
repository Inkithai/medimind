"""Regression tests for care taxonomy + explicit specialty matching.

These lock in the fixes for the reported Find Care bugs:
  * eye-care / dental / committees must not be classified as "doctor"
  * category counts come from the listing's OWN type, never the query
  * a generic "doctor" is "specialty not stated", never gastroenterologist
  * gastro relevance must rank above a nearer unrelated (eye) provider
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care.providers.google import GoogleProvider  # noqa: E402
from care.taxonomy import classify, score_match  # noqa: E402
from unittest import mock  # noqa: E402


def _place(name, primary, types, lat=6.9, lng=79.9):
    return {
        "id": name.lower().replace(" ", "-"),
        "displayName": {"text": name},
        "formattedAddress": "Colombo, Sri Lanka",
        "location": {"latitude": lat, "longitude": lng},
        "types": types,
        "primaryType": primary,
        "businessStatus": "OPERATIONAL",
    }


def test_eye_clinic_is_not_a_doctor():
    info = classify("eye_care", ["doctor", "health", "eye_care"], "Child Eye (Pvt) Ltd")
    assert info is not None
    assert info["kind"] == "other"
    assert "eye" in info["specialties"]
    assert info["entity_type"] == "facility"


def test_national_department_and_student_committee_are_dropped():
    # No recognized healthcare type -> must not reach the UI at all.
    assert classify("government_office", ["point_of_interest"], "National Department for the Deaf") is None
    assert classify(None, ["university", "point_of_interest"], "Indigenous Medical Students' Committee") is None


def test_generic_doctor_specialty_is_not_stated():
    info = classify("doctor", ["doctor", "health"], "Dr. Perera Medical Centre")
    assert info is not None
    assert info["kind"] == "doctor"
    assert info["specialties"] == []
    tier, reason, level = score_match("doctor", [], "gastroenterology")
    assert level == "related"
    assert "specialty not stated" in reason.lower()


def test_named_gastro_clinic_matches_exactly():
    info = classify("medical_clinic", ["medical_clinic", "health"], "Colombo Gastroenterology Clinic")
    assert "gastroenterology" in info["specialties"]
    tier, reason, level = score_match(info["kind"], info["specialties"], "gastroenterology")
    assert level == "exact"
    assert tier == 0


def test_specialty_relevance_outranks_distance():
    # Eye clinic is nearer (49 m) but unrelated; gastro clinic is farther.
    eye = _place("Child Eye (Pvt) Ltd", "eye_care", ["doctor", "eye_care", "health"], 6.9000, 79.9000)
    gastro = _place("Colombo Gastroenterology Clinic", "medical_clinic", ["medical_clinic", "health"], 6.92, 79.92)

    provider = GoogleProvider(api_key="AIza-test-key")
    provider._request_json = mock.Mock(return_value={"places": [eye, gastro]})

    results = provider.search(
        "Rajagiriya",
        "any",
        5,
        latitude=6.9000,
        longitude=79.9000,
        specialty="gastroenterology",
    )

    assert results[0].name == "Colombo Gastroenterology Clinic"
    assert results[0].match_level == "exact"
    # The eye clinic is still returned (as "other"/unrelated) but ranks last.
    assert results[-1].name == "Child Eye (Pvt) Ltd"
    assert results[-1].match_level == "other"
