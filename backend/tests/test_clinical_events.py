"""Regression tests for longitudinal diagnoses, symptoms, procedures, vitals, and imaging."""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GROQ_API_KEY"] = "gsk_test_123"

import pymupdf

from document_filter import looks_like_medical_document
from evidence import locate_pdf_text_evidence, normalize_document_evidence
from medical_extractor import EXTRACTION_JSON_SCHEMA, build_patient_timeline
from record_trust import (
    apply_conflict_quarantine,
    apply_correction_events,
    build_correction_events,
    detect_conflicts,
)
from retrieval import build_chunks_from_timeline


def _region(quote, page=1, bbox=None):
    return {"page": page, "quote": quote, "bbox": bbox, "confidence": 0.94}


def _document(doc_id="doc-clinical", vital_value="120/80", source="consult.pdf"):
    return {
        "_document_id": doc_id,
        "document_type": "consultation_note",
        "date": "2025-05-20",
        "provider_or_doctor": "Dr. Silva",
        "patient_name": "Jane Doe",
        "medications": [],
        "lab_results": [],
        "diagnoses": [{
            "name": "Essential hypertension", "code": "I10", "status": "active",
            "onset_date": "2024-01-10", "confidence": 0.93,
            "evidence": [_region("Assessment: Essential hypertension (I10)")],
        }],
        "symptoms": [{
            "name": "Headache", "severity": "moderate", "status": "current",
            "onset_date": "2025-05-18", "confidence": 0.9,
            "evidence": [_region("moderate headache since 18 May")],
        }],
        "procedures": [{
            "name": "Appendectomy", "procedure_date": "2018-06-01", "body_site": "appendix",
            "status": "historical", "outcome": "No documented complications", "confidence": 0.88,
            "evidence": [_region("Past surgery: appendectomy in 2018")],
        }],
        "vital_signs": [{
            "name": "Blood pressure", "value": vital_value, "unit": "mmHg",
            "measured_at": "2025-05-20", "confidence": 0.97,
            "evidence": [_region(f"BP {vital_value} mmHg")],
        }],
        "imaging_results": [{
            "study_type": "Chest X-ray", "body_site": "chest", "study_date": "2025-05-19",
            "findings": "No focal airspace opacity", "impression": "No acute cardiopulmonary abnormality",
            "confidence": 0.95,
            "evidence": [_region("Chest X-ray: No acute cardiopulmonary abnormality")],
        }],
        "allergies_noted": [],
        "clinical_notes": None,
        "field_evidence": {
            "date": [_region("Date: 2025-05-20")],
            "provider_or_doctor": [_region("Dr. Silva")],
            "patient_name": [_region("Jane Doe")],
            "allergies_noted": [],
            "clinical_notes": [],
        },
        "illegible_or_low_confidence_fields": [],
        "overall_confidence": 0.94,
        "_source": {"file": source, "method": "text_layer", "page": 1},
    }


def test_strict_extraction_schema_requires_all_longitudinal_collections():
    required = set(EXTRACTION_JSON_SCHEMA["required"])
    assert {"diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results"} <= required
    properties = EXTRACTION_JSON_SCHEMA["properties"]
    for key in ("diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results"):
        assert properties[key]["type"] == "array"
        item = properties[key]["items"]
        assert "evidence" in item["properties"]
        assert item["properties"]["evidence"]["minItems"] == 1
        assert "evidence" in item["required"]
    assert {"imaging_report", "consultation_note", "procedure_report"} <= set(
        properties["document_type"]["enum"]
    )


def test_legacy_documents_receive_empty_longitudinal_collections():
    legacy = normalize_document_evidence({
        "document_type": "lab_report",
        "medications": [],
        "lab_results": [],
        "_source": {"file": "legacy.pdf", "method": "text_layer", "page": 1},
    })

    for collection in ("diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results"):
        assert legacy[collection] == []


def test_vision_evidence_is_normalized_for_every_clinical_collection():
    document = _document()
    for collection in ("diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results"):
        document[collection][0]["evidence"][0]["bbox"] = [100, 200, 800, 280]
    normalized = normalize_document_evidence(document, default_page=4, vision=True)

    for collection in ("diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results"):
        region = normalized[collection][0]["evidence"][0]
        assert region["page"] == 4
        assert region["bbox"] == [0.1, 0.2, 0.8, 0.28]
        assert region["field_path"] == f"/{collection}/0"
        assert region["locator"] == "vision_model"


def test_digital_pdf_search_locates_diagnosis_evidence_exactly():
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        pdf = pymupdf.open()
        page = pdf.new_page(width=500, height=300)
        page.insert_text((50, 100), "Assessment: Essential hypertension (I10)")
        pdf.save(handle.name)
        pdf.close()

        document = normalize_document_evidence(_document(), default_page=1)
        located = locate_pdf_text_evidence(handle.name, document)

    region = located["diagnoses"][0]["evidence"][0]
    assert region["page"] == 1
    assert region["quote"] == "Assessment: Essential hypertension (I10)"
    assert region["locator"] == "pdf_text_search"
    assert region["confidence"] == 1.0
    assert region["bbox"] and all(0 <= value <= 1 for value in region["bbox"])


def test_timeline_rollups_use_event_dates_and_keep_source_provenance():
    document = normalize_document_evidence(_document(), default_page=1)
    timeline = build_patient_timeline([document])

    assert timeline["diagnoses_timeline"][0]["date"] == "2024-01-10"
    assert timeline["symptoms_timeline"][0]["date"] == "2025-05-18"
    assert timeline["procedures_timeline"][0]["date"] == "2018-06-01"
    assert timeline["vital_signs_timeline"][0]["date"] == "2025-05-20"
    assert timeline["imaging_results_timeline"][0]["date"] == "2025-05-19"
    for key in (
        "diagnoses_timeline", "symptoms_timeline", "procedures_timeline",
        "vital_signs_timeline", "imaging_results_timeline",
    ):
        fact = timeline[key][0]
        assert fact["document_date"] == "2025-05-20"
        assert fact["document_id"] == "doc-clinical"
        assert fact["source_file"] == "consult.pdf"
        assert fact["source_page"] == 1
        assert fact["fact_path"].startswith("/")


def test_document_date_fallback_is_not_mislabeled_as_event_date():
    document = normalize_document_evidence(_document(), default_page=1)
    document["diagnoses"][0]["onset_date"] = None
    timeline = build_patient_timeline([document])
    diagnosis = timeline["diagnoses_timeline"][0]

    assert diagnosis["date"] is None
    assert diagnosis["document_date"] == "2025-05-20"
    chunks = build_chunks_from_timeline("anon-undated-event", timeline)
    diagnosis_chunk = next(
        chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "diagnosis"
    )
    assert "Onset/event date: not specified" in diagnosis_chunk["text"]
    assert diagnosis_chunk["metadata"]["date"] == ""


def test_timeline_sorts_date_only_and_timezone_aware_event_dates_together():
    older = _document("doc-older", source="older.pdf")
    older["diagnoses"][0]["onset_date"] = "2024-01-09T23:30:00Z"
    newer = _document("doc-newer", source="newer.pdf")
    newer["diagnoses"][0]["onset_date"] = "2024-01-10"

    timeline = build_patient_timeline([older, newer])

    assert [item["document_id"] for item in timeline["diagnoses_timeline"]] == ["doc-older", "doc-newer"]


def test_all_clinical_events_are_retrievable_with_evidence_metadata():
    timeline = build_patient_timeline([normalize_document_evidence(_document(), default_page=1)])
    chunks = build_chunks_from_timeline("anon-clinical", timeline)
    clinical = [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] in {
        "diagnosis", "symptom", "procedure", "vital_sign", "imaging_result",
    }]

    assert {chunk["metadata"]["chunk_type"] for chunk in clinical} == {
        "diagnosis", "symptom", "procedure", "vital_sign", "imaging_result",
    }
    assert len(clinical) == 5
    for chunk in clinical:
        assert chunk["metadata"]["document_id"] == "doc-clinical"
        assert chunk["metadata"]["evidence_id"].startswith("ev_")
        assert chunk["metadata"]["evidence_quote"]
        assert chunk["metadata"]["fact_path"]


def test_diagnosis_only_document_is_recognized_as_structured_medical_content():
    document = {
        "document_type": "other",
        "medications": [], "lab_results": [], "allergies_noted": [],
        "diagnoses": [{"name": "Asthma"}],
        "symptoms": [], "procedures": [], "vital_signs": [], "imaging_results": [],
        "overall_confidence": 0.7,
    }
    assert looks_like_medical_document(document) is True


def test_clinical_event_correction_preserves_original_and_annotates_evidence():
    original = normalize_document_evidence(_document(), default_page=1)
    events = build_correction_events(
        original,
        original,
        [
            {
                "field_path": "/diagnoses/0/status",
                "corrected_value": "history",
                "expected_previous_value": "active",
            },
            {
                "field_path": "/symptoms/0/severity",
                "corrected_value": "mild",
                "expected_previous_value": "moderate",
            },
            {
                "field_path": "/procedures/0/outcome",
                "corrected_value": "Recovered",
                "expected_previous_value": "No documented complications",
            },
            {
                "field_path": "/vital_signs/0/value",
                "corrected_value": "118/78",
                "expected_previous_value": "120/80",
            },
            {
                "field_path": "/imaging_results/0/impression",
                "corrected_value": "No acute abnormality",
                "expected_previous_value": "No acute cardiopulmonary abnormality",
            },
        ],
        user_id="anon-clinical",
        correction_batch_id="correction-clinical",
        reason="Verified against the problem history section",
        created_at="2026-08-16T00:00:00+00:00",
    )
    effective = apply_correction_events([original], events)[0]

    assert original["diagnoses"][0]["status"] == "active"
    assert original["symptoms"][0]["severity"] == "moderate"
    assert original["procedures"][0]["outcome"] == "No documented complications"
    assert original["vital_signs"][0]["value"] == "120/80"
    assert original["imaging_results"][0]["impression"] == "No acute cardiopulmonary abnormality"
    assert effective["diagnoses"][0]["status"] == "history"
    assert effective["symptoms"][0]["severity"] == "mild"
    assert effective["procedures"][0]["outcome"] == "Recovered"
    assert effective["vital_signs"][0]["value"] == "118/78"
    assert effective["imaging_results"][0]["impression"] == "No acute abnormality"
    assert all(
        effective[collection][0]["_trust"]["status"] == "user_corrected"
        for collection in ("diagnoses", "symptoms", "procedures", "vital_signs", "imaging_results")
    )
    region = effective["diagnoses"][0]["evidence"][0]
    assert region["verification_status"] == "user_corrected"
    assert region["original_extracted_value"] == "active"
    assert region["corrected_value"] == "history"


def test_undated_serial_vitals_are_not_quarantined_as_same_measurement():
    first = _document("doc-a", "120/80", "a.pdf")
    second = _document("doc-b", "160/100", "b.pdf")
    first["vital_signs"][0]["measured_at"] = None
    second["vital_signs"][0]["measured_at"] = None

    conflicts = detect_conflicts([first, second])

    assert not [item for item in conflicts if item["kind"] == "vital_sign"]


def test_conflicting_vitals_are_quarantined_from_timeline_and_retrieval():
    first = normalize_document_evidence(_document("doc-a", "120/80", "a.pdf"), default_page=1)
    second = normalize_document_evidence(_document("doc-b", "160/100", "b.pdf"), default_page=1)
    # Keep this fixture focused on the vital conflict rather than duplicating
    # all the other longitudinal assertions in two sources.
    for document in (first, second):
        document["diagnoses"] = []
        document["symptoms"] = []
        document["procedures"] = []
        document["imaging_results"] = []

    conflicts = detect_conflicts([first, second])
    vital_conflicts = [item for item in conflicts if item["kind"] == "vital_sign"]
    assert len(vital_conflicts) == 1

    quarantined, summary = apply_conflict_quarantine([first, second], conflicts)
    timeline = build_patient_timeline(quarantined)
    chunks = build_chunks_from_timeline("anon-vital-conflict", timeline)

    assert summary["quarantined_facts"] == 2
    assert timeline["vital_signs_timeline"] == []
    assert not [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "vital_sign"]
    assert all(
        doc["vital_signs"][0]["evidence"][0]["verification_status"] == "quarantined"
        for doc in quarantined
    )


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests passed")
