"""Offline tests for evidence grading of safety findings.

Every cross-check finding must carry an evidence_source grade, and
ungrounded model-knowledge claims must have their confidence capped —
while findings computed deterministically from the patient's own records
keep their score. Verifies the cross-check integration too:
cross_check_prescriptions() output arrives already graded and timed.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"

import evidence_grading  # noqa: E402
import medical_extractor  # noqa: E402


def _sample_report():
    return {
        "potential_drug_interactions": [
            {"medications_involved": ["Fluconazole", "Montelukast"],
             "explanation": "CYP inhibition.", "severity": "moderate", "confidence": 0.65},
            {"medications_involved": ["Cetirizine", "Chlorpheniramine"],
             "explanation": "Additive sedation.", "severity": "moderate", "confidence": 0.95},
            {"medications_involved": ["Fluconazole", "Omeprazole"],
             "explanation": "Usually small impact.", "severity": "low", "confidence": 0.45},
        ],
        "duplicate_prescriptions": [
            {"medication": "Cetirizine", "occurrences": [], "confidence": 0.95,
             "explanation": "Deterministic check...",
             "evidence_source": evidence_grading.DETERMINISTIC},
            {"medication": "Paracetamol", "occurrences": [], "confidence": 0.9,
             "explanation": "Model spotted these look similar."},
        ],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [
            {"medication": "Amoxicillin", "allergy": "Penicillin",
             "explanation": "Penicillin-class antibiotic.", "confidence": 0.93},
        ],
    }


def test_model_knowledge_is_capped_and_flagged():
    report = _sample_report()
    evidence_grading.grade_cross_check(report)

    interaction = report["potential_drug_interactions"][1]
    assert interaction["evidence_source"] == evidence_grading.MODEL_KNOWLEDGE
    assert interaction["grounded"] is False
    assert interaction["confidence"] == 0.6
    assert interaction["model_reported_confidence"] == 0.95
    assert "pharmacist" in interaction["evidence_note"]


def test_just_above_ceiling_is_capped_too():
    report = _sample_report()
    evidence_grading.grade_cross_check(report)
    just_over = report["potential_drug_interactions"][0]
    assert just_over["confidence"] == 0.6
    assert just_over["model_reported_confidence"] == 0.65


def test_below_ceiling_never_inflated():
    report = _sample_report()
    evidence_grading.grade_cross_check(report)
    low = report["potential_drug_interactions"][2]
    assert low["confidence"] == 0.45
    assert "model_reported_confidence" not in low


def test_deterministic_findings_keep_their_score():
    report = _sample_report()
    evidence_grading.grade_cross_check(report)
    deterministic = report["duplicate_prescriptions"][0]
    assert deterministic["evidence_source"] == evidence_grading.DETERMINISTIC
    assert deterministic["grounded"] is True
    assert deterministic["confidence"] == 0.95, "verifiable findings must keep their score"
    assert "model_reported_confidence" not in deterministic
    # Same list, LLM-authored twin IS capped.
    assert report["duplicate_prescriptions"][1]["confidence"] == 0.6


def test_missing_confidence_defaults_to_ceiling():
    finding = {"medication": "X", "explanation": "no confidence supplied"}
    evidence_grading.grade_finding(finding)
    assert finding["confidence"] == evidence_grading.MODEL_KNOWLEDGE_CONFIDENCE_CEILING
    assert finding["evidence_source"] == evidence_grading.MODEL_KNOWLEDGE


def test_reference_graph_hook_uncapped():
    backed = {"naloxone": {"source": "WHO EML", "display_name": "naloxone", "listings": []}}
    finding = {"medications_involved": ["Naloxone", "Morphine"],
               "explanation": "Reversal.", "severity": "high", "confidence": 0.9}
    evidence_grading.grade_finding(finding, backed)
    assert finding["evidence_source"] == evidence_grading.REFERENCE_GRAPH
    assert finding["grounded"] is True
    assert finding["confidence"] == 0.9
    assert "naloxone" in finding["reference"]


def test_evidence_summary_counts():
    report = _sample_report()
    evidence_grading.grade_cross_check(report)
    summary = report["evidence_summary"]
    assert summary["total_findings"] == 6
    assert summary["deterministic"] == 1
    assert summary["reference_graph"] == 0
    assert summary["model_knowledge"] == 5
    assert summary["model_knowledge_confidence_ceiling"] == 0.6


def test_empty_report_grades_cleanly():
    empty = evidence_grading.grade_cross_check({
        "potential_drug_interactions": [], "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [], "allergy_conflicts": []})
    assert empty["evidence_summary"]["total_findings"] == 0
    assert "nothing to grade" in empty["evidence_summary"]["note"]


def test_cross_check_prescriptions_returns_graded_and_timed():
    """Integration: cross_check_prescriptions() merges the deterministic
    duplicate detector, then grades and places every finding in time."""
    timeline = {
        "visits": [],
        "medications_timeline": [
            # Open-ended courses (no duration) stay active at any reference
            # date, keeping this test independent of the day it runs on.
            {"name": "Paracetamol", "ingredients": ["Paracetamol"],
             "dosage_value": 500, "dosage_unit": "mg", "frequency_per_day": 3,
             "is_as_needed": False, "date": "2026-01-01", "source_file": "a.pdf",
             "prescription_group": "rx-0"},
            {"name": "Paracetamol", "ingredients": ["Paracetamol"],
             "dosage_value": 500, "dosage_unit": "mg", "frequency_per_day": 3,
             "is_as_needed": False, "date": "2026-04-01", "source_file": "b.pdf",
             "prescription_group": "rx-1"},
        ],
        "lab_results_timeline": [],
        "known_allergies": [],
    }
    llm_json = (
        '{"potential_drug_interactions": [{"medications_involved": ["A", "B"], '
        '"explanation": "x", "severity": "moderate", "confidence": 0.9}], '
        '"duplicate_prescriptions": [], "conflicting_dosage_instructions": [], '
        '"allergy_conflicts": [], "overall_recommendation": "Ask a pharmacist."}'
    )
    with mock.patch.object(medical_extractor, "_completion_resilient", return_value=llm_json):
        result = medical_extractor.cross_check_prescriptions(timeline)

    # The deterministic duplicate was merged in and kept its grade.
    dups = result["duplicate_prescriptions"]
    assert len(dups) == 1
    assert dups[0]["evidence_source"] == "deterministic"
    assert dups[0]["confidence"] == 0.95

    # The LLM interaction was capped as model knowledge.
    interaction = result["potential_drug_interactions"][0]
    assert interaction["evidence_source"] == "model_knowledge"
    assert interaction["confidence"] == 0.6
    assert interaction["model_reported_confidence"] == 0.9

    # Timing was applied to every finding list.
    assert "timing" in interaction
    assert "timing" in dups[0]
    assert "timing_summary" in result
    assert "evidence_summary" in result
    assert "concurrent_exposure" in result


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
