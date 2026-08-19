"""Offline trust-boundary tests: immutable corrections and RAG quarantine."""

import copy
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["GROQ_API_KEY"] = "gsk_test_123"

from medical_extractor import build_patient_timeline
from record_trust import (
    apply_conflict_quarantine,
    apply_correction_events,
    build_correction_events,
    detect_conflicts,
    merge_conflict_state,
)
from retrieval import build_chunks_from_timeline


def _doc(doc_id, file_name, patient="Jane Doe", date="2025-01-10", meds=None, labs=None):
    return {
        "_document_id": doc_id,
        "document_type": "lab_report" if labs else "prescription",
        "date": date,
        "provider_or_doctor": "Dr Test",
        "patient_name": patient,
        "medications": meds or [],
        "lab_results": labs or [],
        "allergies_noted": [],
        "clinical_notes": None,
        "illegible_or_low_confidence_fields": [],
        "overall_confidence": 0.91,
        "_source": {"file": file_name, "method": "text_layer", "page": 1},
    }


def _lab(value):
    return {
        "test_name": "HbA1c",
        "value": value,
        "unit": "%",
        "reference_range": "4.0-5.6",
        "flag": "high",
        "confidence": 0.9,
    }


def _med(dose, raw):
    return {
        "name": "Metformin",
        "ingredients": ["Metformin"],
        "dosage": raw,
        "frequency": "twice daily",
        "duration": None,
        "dosage_value": dose,
        "dosage_unit": "mg",
        "frequency_per_day": 2,
        "is_as_needed": False,
        "confidence": 0.92,
    }


def test_correction_replay_preserves_original_and_audit_values():
    original = _doc("doc-a", "lab-a.pdf", labs=[_lab("8.1")])
    untouched = copy.deepcopy(original)
    batch = "correction_" + uuid.uuid4().hex
    events = build_correction_events(
        original,
        original,
        [
            {
                "field_path": "/lab_results/0/value",
                "corrected_value": "6.1",
                "expected_previous_value": "8.1",
            }
        ],
        user_id="anon-test",
        correction_batch_id=batch,
        reason="Verified against the printed row",
        created_at="2026-01-01T00:00:00+00:00",
    )
    effective = apply_correction_events([original], events)[0]

    assert original == untouched, "immutable source extraction must never be mutated"
    assert effective["lab_results"][0]["value"] == "6.1"
    assert events[0]["original_value"] == "8.1"
    assert events[0]["previous_value"] == "8.1"
    assert effective["_corrections"]["paths"] == ["/lab_results/0/value"]
    assert effective["lab_results"][0]["_trust"]["status"] == "user_corrected"


def test_unresolved_lab_conflict_is_visible_but_absent_from_analytics_and_rag():
    docs = [
        _doc("doc-a", "lab-a.pdf", labs=[_lab("6.1")]),
        _doc("doc-b", "lab-b.pdf", labs=[_lab("8.1")]),
    ]
    conflicts = detect_conflicts(docs)
    assert len(conflicts) == 1 and conflicts[0]["kind"] == "lab_result"

    quarantined, summary = apply_conflict_quarantine(docs, conflicts)
    timeline = build_patient_timeline(quarantined)
    timeline["trust_summary"] = summary
    chunks = build_chunks_from_timeline("anon-test", timeline)

    assert len(timeline["visits"]) == 2, "sources must stay visible for correction"
    assert timeline["lab_results_timeline"] == [], "analytics must fail closed"
    assert not [chunk for chunk in chunks if chunk["metadata"]["chunk_type"] == "lab_result"]
    assert summary["unresolved_conflicts"] == 1
    assert summary["quarantined_facts"] == 2


def test_quarantined_value_cannot_leak_through_duplicate_free_text():
    docs = [
        _doc("doc-a", "lab-a.pdf", labs=[_lab("6.1")]),
        _doc("doc-b", "lab-b.pdf", labs=[_lab("8.1")]),
    ]
    docs[0]["clinical_notes"] = "HbA1c 6.1 percent"
    docs[1]["clinical_notes"] = "HbA1c 8.1 percent"
    docs[0]["diagnoses_or_conditions"] = ["HbA1c 6.1 percent"]
    docs[1]["diagnoses_or_conditions"] = ["HbA1c 8.1 percent"]

    quarantined, _ = apply_conflict_quarantine(docs, detect_conflicts(docs))
    timeline = build_patient_timeline(quarantined)
    chunks = build_chunks_from_timeline("anon-free-text", timeline)
    corpus = " ".join(chunk["text"] for chunk in chunks)

    assert "6.1" not in corpus and "8.1" not in corpus
    assert all(visit["clinical_notes"] is None for visit in timeline["visits"])
    assert timeline["diagnoses_timeline"] == []


def test_resolved_conflict_admits_only_authoritative_source():
    docs = [
        _doc("doc-a", "lab-a.pdf", labs=[_lab("6.1")]),
        _doc("doc-b", "lab-b.pdf", labs=[_lab("8.1")]),
    ]
    detected = detect_conflicts(docs)
    persisted = [
        {
            **detected[0],
            "status": "resolved",
            "authoritative_document_id": "doc-a",
            "resolution_note": "Checked the signed original",
        }
    ]
    conflicts = merge_conflict_state(detected, persisted)
    quarantined, summary = apply_conflict_quarantine(docs, conflicts)
    timeline = build_patient_timeline(quarantined)

    assert summary["unresolved_conflicts"] == 0
    assert summary["resolved_conflicts"] == 1
    assert [item["value"] for item in timeline["lab_results_timeline"]] == ["6.1"]
    assert quarantined[1]["lab_results"][0]["_trust"]["quarantined"] is True
    assert quarantined[0]["lab_results"][0]["_trust"]["status"] == "source_confirmed"


def test_identity_conflict_quarantines_whole_workspace_until_reviewed():
    docs = [
        _doc("doc-a", "jane.pdf", patient="Jane Doe", meds=[_med(500, "500 mg")]),
        _doc("doc-b", "john.pdf", patient="John Doe", meds=[_med(500, "500 mg")]),
    ]
    conflicts = detect_conflicts(docs)
    assert any(item["kind"] == "identity" for item in conflicts)
    quarantined, summary = apply_conflict_quarantine(docs, conflicts)
    timeline = build_patient_timeline(quarantined)

    assert summary["quarantined_documents"] == 2
    assert timeline["visits"] == [], (
        "quarantined identities must not appear in the clinical timeline"
    )
    assert len(timeline["documents"]) == 2, "sources must remain available for correction/audit"
    assert timeline["medications_timeline"] == []


def test_normalized_equivalent_doses_do_not_create_false_conflict():
    docs = [
        _doc("doc-a", "a.pdf", meds=[_med(500, "500 mg")]),
        _doc("doc-b", "b.pdf", meds=[_med(500, "0.5 g")]),
    ]
    assert not [item for item in detect_conflicts(docs) if item["kind"] == "medication"]


def test_identity_format_variants_do_not_quarantine_the_workspace():
    """Regression (production, 2026-08-17): one patient's records extracted
    patient_name in two legitimate formats — "PERERA, Anjali (Mrs.)" on the
    lab reports and "Anjali Perera" elsewhere. Raw normalized strings made
    those two DIFFERENT identities, firing a critical identity conflict that
    quarantined all 7 documents: the dashboard then showed 0 medications,
    0 lab results, 0 clinical events and "No records yet" after a successful
    upload. Honorifics, punctuation, and surname-first printing are not
    identity differences."""
    docs = [
        _doc(
            "doc-1",
            "anjali-1.jpg",
            patient="PERERA, Anjali (Mrs.)",
            date="2026-06-10",
            labs=[
                {
                    "test_name": "Hemoglobin",
                    "value": 10.2,
                    "unit": "g/dL",
                    "reference_range": "12-16",
                    "flag": "low",
                    "confidence": 0.9,
                }
            ],
        ),
        _doc(
            "doc-2",
            "anjali-2.jpg",
            patient="Anjali Perera",
            date="2026-03-20",
            meds=[_med(500, "500 mg")],
        ),
        _doc(
            "doc-3",
            "anjali-3.png",
            patient="Anjali Perera",
            date="2026-01-15",
            labs=[
                {
                    "test_name": "Hemoglobin",
                    "value": 11.0,
                    "unit": "g/dL",
                    "reference_range": "12-16",
                    "flag": "low",
                    "confidence": 0.88,
                }
            ],
        ),
        _doc(
            "doc-4",
            "anjali-4.png",
            patient="PERERA, Anjali",
            date="2026-04-02",
            meds=[_med(850, "850 mg")],
        ),
    ]
    conflicts = detect_conflicts(docs)
    assert not [item for item in conflicts if item["kind"] == "identity"], conflicts

    trusted, summary = apply_conflict_quarantine(docs, conflicts)
    assert summary["quarantined_documents"] == 0, summary
    timeline = build_patient_timeline(trusted)
    assert len(timeline["medications_timeline"]) == 2
    assert len(timeline["lab_results_timeline"]) == 2
    assert len(timeline["visits"]) == 4, "all four documents must enter the timeline"


def test_genuinely_different_identities_still_quarantine():
    """The fail-closed guarantee survives the format-variant fix: two really
    different patients (different name token sets) still conflict."""
    docs = [
        _doc("doc-a", "jane.pdf", patient="PERERA, Anjali (Mrs.)", meds=[_med(500, "500 mg")]),
        _doc("doc-b", "john.pdf", patient="Nimal Fernando", meds=[_med(500, "500 mg")]),
    ]
    conflicts = detect_conflicts(docs)
    identity = next(item for item in conflicts if item["kind"] == "identity")
    quarantined, summary = apply_conflict_quarantine(docs, conflicts)
    assert summary["quarantined_documents"] == 2
    assert len(identity["items"]) == 2


def test_resolved_identity_unquarantines_format_variants():
    """After resolving an identity conflict by picking an authoritative
    source, documents whose patient_name is merely a FORMAT VARIANT of the
    authoritative name must be un-quarantined — exact-string matching kept
    "PERERA, Anjali (Mrs.)" quarantined forever after "Anjali Perera" was
    confirmed authoritative."""
    docs = [
        _doc("doc-a", "a.pdf", patient="Anjali Perera", meds=[_med(500, "500 mg")]),
        _doc("doc-b", "b.pdf", patient="PERERA, Anjali (Mrs.)", meds=[_med(500, "500 mg")]),
        _doc("doc-c", "c.pdf", patient="Nimal Fernando", meds=[_med(500, "500 mg")]),
    ]
    conflicts = detect_conflicts(docs)
    identity = next(item for item in conflicts if item["kind"] == "identity")
    resolved = [
        {**identity, "status": "resolved", "authoritative_document_id": "doc-a"},
        *[item for item in conflicts if item is not identity],
    ]
    trusted, summary = apply_conflict_quarantine(docs, resolved)
    quarantined_ids = {
        doc["_document_id"] for doc in trusted if (doc.get("_trust") or {}).get("quarantined")
    }
    assert quarantined_ids == {"doc-c"}, quarantined_ids
    timeline = build_patient_timeline(trusted)
    assert len(timeline["visits"]) == 2, "both Anjali format variants must be admitted"


def test_merge_conflict_state_drops_stale_persisted_identity_conflict():
    """Reads re-detect conflicts every time; a persisted conflict that is no
    longer detected must not keep quarantining the workspace (this is what
    un-bricks a workspace like the production one after the fix deploys)."""
    docs = [
        _doc("doc-a", "a.pdf", patient="PERERA, Anjali (Mrs.)", meds=[_med(500, "500 mg")]),
        _doc("doc-b", "b.pdf", patient="Anjali Perera", meds=[_med(500, "500 mg")]),
    ]
    stale = [
        {
            "conflict_id": "conflict_stale_identity",
            "kind": "identity",
            "status": "unresolved",
            "items": [],
        }
    ]
    merged = merge_conflict_state(detect_conflicts(docs), stale)
    assert merged == [], merged
    trusted, summary = apply_conflict_quarantine(docs, merged)
    assert summary["quarantined_documents"] == 0


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"{len(tests)} tests passed")
