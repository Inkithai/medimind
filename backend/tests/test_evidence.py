"""Offline regression coverage for page-level source evidence."""

import copy
import json
import os
import sys
import tempfile
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GROQ_API_KEY"] = "gsk_test_123"

import pymupdf

import retrieval
from evidence import locate_pdf_text_evidence, normalize_document_evidence
from record_trust import (
    apply_conflict_quarantine,
    apply_correction_events,
    build_correction_events,
    detect_conflicts,
)


def _document():
    return {
        "document_type": "lab_report",
        "date": "2025-02-03",
        "provider_or_doctor": "Dr. Silva",
        "patient_name": "Jane Doe",
        "medications": [
            {
                "name": "Metformin",
                "ingredients": ["Metformin"],
                "dosage": "500 mg",
                "frequency": "twice daily",
                "duration": None,
                "dosage_value": 500,
                "dosage_unit": "mg",
                "frequency_per_day": 2,
                "is_as_needed": False,
                "confidence": 0.92,
            }
        ],
        "lab_results": [
            {
                "test_name": "HbA1c",
                "value": "6.1",
                "unit": "%",
                "reference_range": "4.0-5.6",
                "flag": "high",
                "confidence": 0.9,
                "evidence": [
                    {
                        "page": 1,
                        "quote": "HbA1c 6.1 %",
                        "bbox": None,
                        "confidence": 0.93,
                    }
                ],
            }
        ],
        "allergies_noted": ["Penicillin"],
        "clinical_notes": None,
        "field_evidence": {
            "date": [
                {
                    "page": 1,
                    "quote": "Date: 2025-02-03",
                    "bbox": [100, 200, 500, 260],
                    "confidence": 0.91,
                }
            ],
            "provider_or_doctor": [],
            "patient_name": [],
            "allergies_noted": [],
            "clinical_notes": [],
        },
        "overall_confidence": 0.9,
    }


def test_vision_coordinates_are_normalized_and_source_page_is_remapped():
    document = normalize_document_evidence(_document(), default_page=3, vision=True)
    date_region = document["field_evidence"]["date"][0]

    assert date_region["page"] == 3
    assert date_region["bbox"] == [0.1, 0.2, 0.5, 0.26]
    assert date_region["locator"] == "vision_model"
    # Legacy/model-omitted evidence gets an honest page-only link. The
    # extracted value is not misrepresented as a verbatim quotation.
    patient_region = document["field_evidence"]["patient_name"][0]
    assert patient_region["page"] == 3
    assert patient_region["quote"] == ""
    assert patient_region["bbox"] is None
    assert patient_region["locator"] == "page_only"


def test_persisted_ids_locators_and_verification_annotations_survive_normalization():
    document = normalize_document_evidence(_document(), default_page=1)
    region = document["lab_results"][0]["evidence"][0]
    evidence_id = region["evidence_id"]
    region.update(
        {
            "locator": "pdf_text_search",
            "verification_status": "user_corrected",
            "original_extracted_value": "8.1",
            "corrected_value": "6.1",
        }
    )

    reloaded = normalize_document_evidence(copy.deepcopy(document), default_page=1)
    persisted = reloaded["lab_results"][0]["evidence"][0]
    assert persisted["evidence_id"] == evidence_id
    assert persisted["locator"] == "pdf_text_search"
    assert persisted["verification_status"] == "user_corrected"
    assert persisted["original_extracted_value"] == "8.1"
    assert persisted["corrected_value"] == "6.1"


def test_correction_replay_annotates_linked_evidence_without_replacing_provenance():
    original = normalize_document_evidence(_document(), default_page=1)
    original["_document_id"] = "doc-lab"
    original_region = copy.deepcopy(original["lab_results"][0]["evidence"][0])
    events = build_correction_events(
        original,
        original,
        [
            {
                "field_path": "/lab_results/0/value",
                "corrected_value": "6.0",
                "expected_previous_value": "6.1",
            }
        ],
        user_id="anon-evidence",
        correction_batch_id="correction-evidence",
        reason="Checked the source row",
        created_at="2026-08-16T00:00:00+00:00",
    )

    effective = apply_correction_events([original], events)[0]
    linked = effective["lab_results"][0]["evidence"][0]
    assert effective["lab_results"][0]["value"] == "6.0"
    assert original["lab_results"][0]["evidence"][0] == original_region
    assert linked["evidence_id"] == original_region["evidence_id"]
    assert linked["quote"] == original_region["quote"]
    assert linked["verification_status"] == "user_corrected"
    assert linked["original_extracted_value"] == "6.1"
    assert linked["corrected_value"] == "6.0"


def test_conflict_quarantine_marks_each_competing_source_region():
    first = normalize_document_evidence(_document(), default_page=1)
    first.update(
        {"_document_id": "doc-first", "_source": {"file": "first.pdf", "method": "text_layer"}}
    )
    second = copy.deepcopy(_document())
    second["lab_results"][0]["value"] = "8.1"
    second["lab_results"][0]["evidence"][0]["quote"] = "HbA1c 8.1 %"
    second = normalize_document_evidence(second, default_page=1)
    second.update(
        {"_document_id": "doc-second", "_source": {"file": "second.pdf", "method": "text_layer"}}
    )

    conflicts = detect_conflicts([first, second])
    quarantined, _summary = apply_conflict_quarantine([first, second], conflicts)

    regions = [doc["lab_results"][0]["evidence"][0] for doc in quarantined]
    assert all(region["verification_status"] == "quarantined" for region in regions)
    assert regions[0]["conflict_id"] == regions[1]["conflict_id"] == conflicts[0]["conflict_id"]
    assert first["lab_results"][0]["evidence"][0].get("verification_status") is None


def test_pdf_search_moves_to_the_real_page_and_returns_normalized_rectangle():
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        pdf = pymupdf.open()
        first = pdf.new_page(width=400, height=300)
        first.insert_text((40, 70), "Patient: Jane Doe")
        second = pdf.new_page(width=400, height=300)
        second.insert_text((50, 100), "HbA1c 6.1 %")
        pdf.save(handle.name)
        pdf.close()

        document = normalize_document_evidence(_document(), default_page=1)
        evidence_id = document["lab_results"][0]["evidence"][0]["evidence_id"]
        located = locate_pdf_text_evidence(handle.name, document)

    region = located["lab_results"][0]["evidence"][0]
    assert region["evidence_id"] == evidence_id
    assert region["page"] == 2
    assert region["locator"] == "pdf_text_search"
    assert region["quote"] == "HbA1c 6.1 %"
    assert region["confidence"] == 1.0
    assert region["bbox"] is not None
    left, top, right, bottom = region["bbox"]
    assert 0 <= left < right <= 1
    assert 0 <= top < bottom <= 1


def test_unmatched_pdf_evidence_keeps_quote_and_page_without_fabricating_geometry():
    with tempfile.NamedTemporaryFile(suffix=".pdf") as handle:
        pdf = pymupdf.open()
        pdf.new_page().insert_text((50, 80), "Unrelated medical document")
        pdf.save(handle.name)
        pdf.close()

        document = normalize_document_evidence(_document(), default_page=1)
        located = locate_pdf_text_evidence(handle.name, document)

    region = located["field_evidence"]["date"][0]
    assert region["page"] == 1
    assert region["quote"] == "Date: 2025-02-03"
    assert region["bbox"] is None
    assert region["locator"] == "page_quote"


def test_retrieval_metadata_carries_exact_evidence_and_keeps_allergy_sources_separate():
    region_a = {
        "evidence_id": "ev_med",
        "field_path": "/medications/0",
        "page": 2,
        "quote": "Metformin 500 mg twice daily",
        "bbox": [0.1, 0.2, 0.7, 0.3],
        "confidence": 1.0,
        "locator": "pdf_text_search",
    }
    timeline = {
        "visits": [],
        "medications_timeline": [
            {
                "name": "Metformin",
                "ingredients": ["Metformin"],
                "dosage": "500 mg",
                "frequency": "twice daily",
                "duration": None,
                "dosage_value": 500,
                "dosage_unit": "mg",
                "frequency_per_day": 2,
                "is_as_needed": False,
                "confidence": 0.92,
                "date": "2025-02-03",
                "source_file": "rx.pdf",
                "source_page": 2,
                "source_method": "text_layer",
                "document_id": "doc-rx",
                "fact_path": "/medications/0",
                "document_type": "prescription",
                "evidence": [region_a],
            }
        ],
        "lab_results_timeline": [],
        "known_allergies": ["Penicillin", "Sulfa"],
        "allergy_evidence": [
            {
                "allergy": "Penicillin",
                "document_id": "doc-a",
                "source_file": "a.pdf",
                "source_method": "text_layer",
                "document_type": "lab_report",
                "confidence": 0.9,
                "evidence": [
                    {
                        **region_a,
                        "evidence_id": "ev_allergy_a",
                        "page": 1,
                        "quote": "Allergy: Penicillin",
                    }
                ],
            },
            {
                "allergy": "Sulfa",
                "document_id": "doc-b",
                "source_file": "b.pdf",
                "source_method": "vision_ocr",
                "document_type": "prescription",
                "confidence": 0.8,
                "evidence": [
                    {
                        **region_a,
                        "evidence_id": "ev_allergy_b",
                        "page": 4,
                        "quote": "Allergy: Sulfa",
                    }
                ],
            },
        ],
    }

    chunks = retrieval.build_chunks_from_timeline("anon-evidence", timeline)
    medication = next(chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "medication")
    assert medication["metadata"]["evidence_id"] == "ev_med"
    assert medication["metadata"]["evidence_quote"] == "Metformin 500 mg twice daily"
    assert json.loads(medication["metadata"]["evidence_bbox"]) == [0.1, 0.2, 0.7, 0.3]

    allergy_chunks = [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "allergy"]
    assert len(allergy_chunks) == 2
    assert {chunk["metadata"]["document_id"] for chunk in allergy_chunks} == {"doc-a", "doc-b"}
    assert {chunk["metadata"]["evidence_id"] for chunk in allergy_chunks} == {
        "ev_allergy_a",
        "ev_allergy_b",
    }


def test_qa_citation_is_normalized_by_evidence_id_not_first_fact_in_document():
    metadatas = [
        {
            "date": "2025-02-03",
            "source_file": "same.pdf",
            "source_page": 1,
            "document_id": "doc-same",
            "chunk_type": "medication",
            "evidence_id": "ev_first",
            "evidence_quote": "First fact",
            "evidence_bbox": "[0.1, 0.1, 0.2, 0.2]",
            "verification_status": "extracted",
            "evidence_tier": "B",
            "evidence_score": 0.8,
        },
        {
            "date": "2025-02-03",
            "source_file": "same.pdf",
            "source_page": 3,
            "document_id": "doc-same",
            "chunk_type": "lab_result",
            "evidence_id": "ev_target",
            "evidence_quote": "HbA1c 6.1 %",
            "evidence_bbox": "[0.2, 0.3, 0.6, 0.4]",
            "verification_status": "source_confirmed",
            "evidence_tier": "A",
            "evidence_score": 0.95,
        },
    ]

    class FakeCollection:
        def count(self):
            return 2

        def query(self, **_kwargs):
            return {"documents": [["first", "target"]], "metadatas": [metadatas]}

    answer = json.dumps(
        {
            "answer": "The HbA1c was 6.1%.",
            "confidence": 0.95,
            "sources": [
                {
                    "date": "invented",
                    "source_file": "same.pdf",
                    "page": 999,
                    "document_id": "doc-same",
                    "evidence_id": "ev_target",
                    "quote": "invented",
                    "bbox": None,
                    "verification_status": "invented",
                    "evidence_tier": "C",
                }
            ],
            "recommend_professional_consult": False,
        }
    )

    with (
        mock.patch.object(
            retrieval, "_trusted_timeline_from_persisted_documents", return_value=(None, [{}])
        ),
        mock.patch.object(retrieval.vector_store, "count", return_value=2),
        mock.patch.object(retrieval.vector_store, "get_store_name", return_value="chroma"),
        mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection()),
        mock.patch.object(retrieval, "embed_texts", return_value=[[0.1] * 8]),
        mock.patch.object(retrieval, "_completion_resilient", return_value=answer),
    ):
        result = retrieval.answer_question("anon-evidence", "What was my HbA1c?")

    assert result["sources"] == [
        {
            "date": "2025-02-03",
            "dates": ["2025-02-03"],
            "source_file": "same.pdf",
            "page": 3,
            "document_id": "doc-same",
            "evidence_id": "ev_target",
            "quote": "HbA1c 6.1 %",
            "bbox": [0.2, 0.3, 0.6, 0.4],
            "verification_status": "source_confirmed",
            "evidence_tier": "A",
        }
    ]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests passed")
