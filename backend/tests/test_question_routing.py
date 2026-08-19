"""Offline tests for deterministic Q&A intent routing and evidence coverage."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from question_routing import assess_evidence, classify_question, route_chunks


def test_classifies_supported_question_intents():
    cases = {
        "Are these medications safe together?": "medication_safety",
        "Is aspirin safe for me?": "medication_safety",
        "Has my glucose increased over time?": "lab_trend",
        "What was my latest HbA1c result?": "lab_result",
        "What allergies are in my records?": "allergy",
        "What dose of metformin was prescribed?": "medication",
        "What happened at my last visit?": "timeline",
        "What changed since my last report?": "record_change",
        "Summarize my records": "general",
    }
    for question, expected in cases.items():
        assert classify_question(question)["key"] == expected, question


def test_routes_lab_question_away_from_unrelated_medication_chunks():
    docs = ["metformin", "glucose 90", "clinical note", "glucose 110"]
    metas = [
        {"chunk_type": "medication", "source_file": "rx.pdf"},
        {"chunk_type": "lab_result", "source_file": "lab1.pdf"},
        {"chunk_type": "clinical_note", "source_file": "visit.pdf"},
        {"chunk_type": "lab_result", "source_file": "lab2.pdf"},
    ]
    intent = classify_question("Has glucose changed over time?")
    routed_docs, routed_meta = route_chunks(docs, metas, intent, limit=8)
    assert routed_docs == ["glucose 90", "glucose 110"]
    assert {item["chunk_type"] for item in routed_meta} == {"lab_result"}


def test_preserves_vector_order_and_applies_limit():
    docs = ["first", "second", "third"]
    metas = [{"chunk_type": "medication"} for _ in docs]
    routed, _ = route_chunks(
        docs, metas, classify_question("What medicines were prescribed?"), limit=2
    )
    assert routed == ["first", "second"]


def test_trend_question_requires_multiple_evidence_items():
    intent = classify_question("Has my glucose improved over time?")
    limited = assess_evidence(
        intent, [{"chunk_type": "lab_result", "source_file": "one.pdf", "date": "2025-01-01"}]
    )
    assert limited["level"] == "limited"
    assert limited["expected_minimum"] == 2
    sufficient = assess_evidence(
        intent,
        [
            {"chunk_type": "lab_result", "source_file": "one.pdf", "date": "2025-01-01"},
            {"chunk_type": "lab_result", "source_file": "two.pdf", "date": "2025-02-01"},
        ],
    )
    assert sufficient["level"] == "sufficient"
    assert sufficient["distinct_sources"] == 2


def test_multiple_chunks_from_one_date_do_not_establish_a_trend():
    intent = classify_question("Has my glucose changed over time?")
    evidence = assess_evidence(
        intent,
        [
            {"chunk_type": "lab_result", "source_file": "one.pdf", "date": "2025-01-01"},
            {"chunk_type": "lab_result", "source_file": "one.pdf", "date": "2025-01-01"},
        ],
    )
    assert evidence["level"] == "limited"
    assert evidence["distinct_sources"] == 1


def test_no_matching_evidence_is_explicitly_insufficient():
    evidence = assess_evidence(classify_question("What allergies do I have?"), [])
    assert evidence["level"] == "insufficient"
    assert evidence["retrieved_chunks"] == 0
    assert "No allergy evidence" in evidence["reason"]


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
