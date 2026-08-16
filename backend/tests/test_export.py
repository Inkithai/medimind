"""Offline tests for the record export module (native JSON + FHIR R4)."""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from export import build_export, build_fhir_bundle, build_native_export  # noqa: E402


SNAPSHOT = {
    "patient_timeline": {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Metformin", "ingredients": ["metformin"],
                "dosage": "500 mg", "frequency": "2x daily", "duration": "30 days",
                "date": "2024-03-15", "source_file": "rx.pdf",
            },
        ],
        "lab_results_timeline": [
            {
                "test_name": "HbA1c", "value": "6.8", "unit": "%",
                "reference_range": "4.0-5.6", "flag": "high",
                "date": "2024-03-15", "source_file": "labs.pdf",
            },
            {
                "test_name": "Urine culture", "value": "no growth", "unit": None,
                "reference_range": None, "flag": None,
                "date": "not-a-date", "source_file": "labs.pdf",
            },
        ],
        "known_allergies": ["penicillin"],
    },
    "cross_check_report": {"potential_drug_interactions": [], "overall_recommendation": "Consult a professional."},
    "lab_trends": {"trends": [], "insufficient_data": []},
    "updated_at": "2024-03-16T00:00:00+00:00",
}


def _resources_of(bundle, resource_type):
    return [e["resource"] for e in bundle["entry"] if e["resource"]["resourceType"] == resource_type]


def test_native_export_is_lossless_and_self_describing():
    result = build_native_export("anon_x", SNAPSHOT)
    assert result["format"] == "medimind-record-export"
    assert result["user_id"] == "anon_x"
    assert result["patient_timeline"] == SNAPSHOT["patient_timeline"]
    assert result["cross_check_report"] == SNAPSHOT["cross_check_report"]
    assert result["lab_trends"] == SNAPSHOT["lab_trends"]


def test_fhir_bundle_maps_all_resource_types():
    bundle = build_fhir_bundle("anon_x", SNAPSHOT)
    assert bundle["resourceType"] == "Bundle"
    assert bundle["type"] == "collection"
    assert len(_resources_of(bundle, "Patient")) == 1
    assert len(_resources_of(bundle, "MedicationStatement")) == 1
    assert len(_resources_of(bundle, "Observation")) == 2
    assert len(_resources_of(bundle, "AllergyIntolerance")) == 1
    assert len(_resources_of(bundle, "Provenance")) == 1
    assert bundle["total"] == len(bundle["entry"])


def test_fhir_numeric_lab_uses_value_quantity_and_freetext_uses_value_string():
    bundle = build_fhir_bundle("anon_x", SNAPSHOT)
    observations = _resources_of(bundle, "Observation")
    hba1c = next(o for o in observations if o["code"]["text"] == "HbA1c")
    assert hba1c["valueQuantity"] == {"value": 6.8, "unit": "%"}
    assert hba1c["effectiveDateTime"] == "2024-03-15"
    culture = next(o for o in observations if o["code"]["text"] == "Urine culture")
    assert culture["valueString"] == "no growth"
    # invalid date must be omitted, not emitted malformed
    assert "effectiveDateTime" not in culture


def test_fhir_medication_maps_dosage_and_date():
    bundle = build_fhir_bundle("anon_x", SNAPSHOT)
    med = _resources_of(bundle, "MedicationStatement")[0]
    assert med["medication"]["concept"]["text"] == "Metformin"
    assert med["effectiveDateTime"] == "2024-03-15"
    assert "500 mg" in med["dosage"][0]["text"]


def test_fhir_provenance_targets_every_other_resource():
    bundle = build_fhir_bundle("anon_x", SNAPSHOT)
    provenance = _resources_of(bundle, "Provenance")[0]
    non_provenance = [e for e in bundle["entry"] if e["resource"]["resourceType"] != "Provenance"]
    assert len(provenance["target"]) == len(non_provenance)


def test_build_export_rejects_unknown_format():
    with pytest.raises(ValueError):
        build_export("anon_x", SNAPSHOT, "hl7v2")


def test_build_export_dispatch():
    assert build_export("anon_x", SNAPSHOT, "json")["format"] == "medimind-record-export"
    assert build_export("anon_x", SNAPSHOT, "fhir")["resourceType"] == "Bundle"
    assert build_export("anon_x", SNAPSHOT, "FHIR")["resourceType"] == "Bundle"  # case-insensitive
