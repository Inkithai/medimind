"""Offline tests for clinical-flag and specialty-routing logic.

These tests deliberately use only synthetic/de-identified medical findings.
They contain no provider, doctor, clinic, address, rating, phone, or directory
fixture data: live directory records must only ever come from runtime sources.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from care_recommendations import recommendation_context
from provider_ranking import availability_label
from specialty_mapping import match_specialty


def _snapshot(timeline, cross_check=None, lab_trends=None):
    return {
        "patient_timeline": timeline,
        "cross_check_report": cross_check or {},
        "lab_trends": lab_trends or {},
    }


def test_high_severity_interaction_unlocks_pharmacist_search():
    context = recommendation_context(
        _snapshot(
            {"visits": [], "medications_timeline": [], "lab_results_timeline": []},
            {
                "potential_drug_interactions": [
                    {
                        "medications_involved": ["Medicine A", "Medicine B"],
                        "severity": "high",
                        "confidence": 0.91,
                        "explanation": "Potential interaction requires professional review.",
                    }
                ],
                "allergy_conflicts": [],
            },
        )
    )
    assert context["eligible"] is True
    flag = context["flags"][0]
    assert flag["trigger"] == "high_risk"
    assert flag["specialty"]["id"] == "pharmacy"
    assert flag["specialty"]["provider_query"] == "pharmacy"


def test_low_confidence_kidney_related_lab_routes_to_nephrology_without_diagnosis():
    context = recommendation_context(
        _snapshot(
            {
                "visits": [],
                "medications_timeline": [],
                "lab_results_timeline": [
                    {
                        "test_name": "Creatinine",
                        "value": "1.32",
                        "unit": "mg/dL",
                        "source_file": "deidentified_lab.pdf",
                        "confidence": 0.45,
                    }
                ],
            }
        )
    )
    assert context["eligible"] is True
    flag = context["flags"][0]
    assert flag["trigger"] == "low_confidence"
    assert flag["specialty"]["id"] == "nephrology"
    assert "not a diagnosis" in flag["specialty"]["reason"].lower()


def test_specialty_categories_are_mapped_from_reviewable_terms():
    assert match_specialty("low_confidence_document", "Troponin was difficult to read.")["id"] == "cardiology"
    assert match_specialty("low_confidence_document", "Spirometry value was difficult to read.")["id"] == "pulmonology"
    assert match_specialty("low_confidence_document", "A migraine note was difficult to read.")["id"] == "neurology"
    assert match_specialty("low_confidence_document", "A skin rash note was difficult to read.")["id"] == "dermatology"


def test_ambiguous_evidence_uses_general_physician():
    specialty = match_specialty("low_confidence_document", "Text could not be read reliably.")
    assert specialty["id"] == "general_practice"
    assert specialty["provider_query"] == "general practitioner"


def test_availability_labels_are_explicit():
    assert availability_label("weekends") == "Weekends"
    assert availability_label("unexpected") == "Any consultation time"
