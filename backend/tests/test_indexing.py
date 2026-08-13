"""Offline tests for the "no indexable content" indexing fix.

Verifies that index_patient_timeline() returns 0 (and does NOT touch
Chroma) when a timeline has nothing retrievable, so upload callers stop
reporting indexed=True for an empty index.
"""
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"

import retrieval


EMPTY_TIMELINE = {
    "visits": [{"document_type": "other", "clinical_notes": None}],
    "medications_timeline": [],
    "lab_results_timeline": [],
    "known_allergies": [],
}

FULL_TIMELINE = {
    "visits": [],
    "medications_timeline": [
        {"name": "Paracetamol", "ingredients": ["Paracetamol"], "dosage": "500 mg",
         "dosage_value": 500, "dosage_unit": "mg", "frequency": "3x daily",
         "frequency_per_day": 3, "is_as_needed": False, "duration": "5 days",
         "date": "2024-01-01", "source_file": "rx1.pdf", "confidence": 0.95}
    ],
    "lab_results_timeline": [],
    "known_allergies": ["Penicillin"],
}


def test_empty_timeline_returns_zero():
    with mock.patch.object(retrieval, "_get_patient_collection") as get_collection, \
         mock.patch.object(retrieval, "embed_texts") as embed:
        count = retrieval.index_patient_timeline("anon_test", EMPTY_TIMELINE)
    assert count == 0
    get_collection.assert_not_called()
    embed.assert_not_called()


def test_full_timeline_returns_chunk_count():
    collection = mock.Mock()
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=collection), \
         mock.patch.object(retrieval.vector_store, "delete_collection"), \
         mock.patch.object(retrieval, "embed_texts", side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        count = retrieval.index_patient_timeline("anon_test", FULL_TIMELINE)
    # 1 medication chunk + 1 allergy chunk
    assert count == 2, count
    collection.upsert.assert_called_once()
    assert collection.upsert.call_args.kwargs["ids"]
    assert len(collection.upsert.call_args.kwargs["ids"]) == 2


def test_chunk_building_counts():
    chunks = retrieval.build_chunks_from_timeline("anon_test", FULL_TIMELINE)
    types = {c["metadata"]["chunk_type"] for c in chunks}
    assert types == {"medication", "allergy"}


def test_chunk_ids_are_stable_when_timeline_order_changes():
    """IDs must not include the list index — adding an older medication
    used to rename every subsequent chunk and leave the old ids behind."""
    older = {
        "name": "Aspirin", "ingredients": ["Aspirin"], "dosage": "75 mg",
        "dosage_value": 75, "dosage_unit": "mg", "frequency": "daily",
        "frequency_per_day": 1, "is_as_needed": False, "duration": None,
        "date": "2023-01-01", "source_file": "old.pdf", "confidence": 0.9,
    }
    first = retrieval.build_chunks_from_timeline("anon_test", FULL_TIMELINE)
    shifted = {
        **FULL_TIMELINE,
        "medications_timeline": [older, *FULL_TIMELINE["medications_timeline"]],
    }
    second = retrieval.build_chunks_from_timeline("anon_test", shifted)
    first_med_ids = {c["id"] for c in first if c["metadata"]["chunk_type"] == "medication"}
    second_med_ids = {c["id"] for c in second if c["metadata"]["chunk_type"] == "medication"}
    assert first_med_ids <= second_med_ids
    assert len(second_med_ids) == len(first_med_ids) + 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
