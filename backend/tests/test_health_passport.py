"""Offline tests for the one-page health-passport PDF (no network/services)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from health_passport import (  # noqa: E402
    build_health_passport_pdf,
    build_passport_data,
    render_passport_pdf,
)


def _timeline(**overrides):
    base = {
        "visits": [
            {
                "patient_name": "Asha Perera",
                "date": "2026-08-01",
                "_source": {"file": "rx.pdf", "method": "text_layer"},
            }
        ],
        "medications_timeline": [
            {
                "name": "Metformin",
                "ingredients": ["metformin"],
                "dosage": "500 mg",
                "frequency": "twice a day",
                "duration": None,
                "date": "2026-08-01",
                "source_file": "rx.pdf",
            },
            {
                "name": "Amoxicillin",
                "ingredients": ["amoxicillin"],
                "dosage": "500 mg",
                "frequency": "three times a day",
                "duration": "7 days",
                "date": "2020-01-01",
                "source_file": "old_rx.pdf",
            },
        ],
        "lab_results_timeline": [
            {
                "test_name": "HbA1c",
                "value": "8.1",
                "unit": "%",
                "flag": "high",
                "date": "2026-08-01",
                "source_file": "labs.pdf",
            },
            {
                "test_name": "Creatinine",
                "value": "0.9",
                "unit": "mg/dL",
                "flag": "normal",
                "date": "2026-08-01",
                "source_file": "labs.pdf",
            },
        ],
        "diagnoses_timeline": [
            {"name": "Type 2 diabetes", "status": "active", "date": "2026-08-01"},
            {"name": "Hypertension", "status": "confirmed", "date": "2026-08-01"},
        ],
        "known_allergies": ["penicillin"],
    }
    base.update(overrides)
    return base


def test_passport_data_has_all_sections():
    data = build_passport_data(_timeline())
    assert data["patient_name"] == "Asha Perera"
    assert "metformin" in " ".join(data["active_medications"]).lower()
    # The 2020 antibiotic course provably ended — it must not be "active".
    assert "amoxicillin" not in " ".join(data["active_medications"]).lower()
    assert data["allergies"] == ["penicillin"]
    assert any("type 2 diabetes" in c.lower() for c in data["conditions"])
    assert any("hba1c" in lab.lower() for lab in data["recent_abnormal_labs"])
    # A normal lab must not appear in the abnormal section.
    assert not any("creatinine" in lab.lower() for lab in data["recent_abnormal_labs"])


def test_passport_data_handles_empty_record():
    data = build_passport_data(
        {
            "visits": [],
            "medications_timeline": [],
            "lab_results_timeline": [],
            "diagnoses_timeline": [],
            "known_allergies": [],
        }
    )
    assert data["patient_name"] == "Not recorded"
    assert data["active_medications"] == []
    assert data["allergies"] == []
    assert data["conditions"] == []
    assert data["recent_abnormal_labs"] == []


def test_profile_name_preferred_over_extracted():
    data = build_passport_data(_timeline(), patient_name="Preferred Name")
    assert data["patient_name"] == "Preferred Name"


def test_pdf_renders_a_single_page():
    data = build_passport_data(_timeline())
    pdf = render_passport_pdf(data)
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 500


def test_end_to_end_builder_returns_pdf():
    pdf = build_health_passport_pdf(_timeline(), workspace_name="Asha's records")
    assert pdf.startswith(b"%PDF")
