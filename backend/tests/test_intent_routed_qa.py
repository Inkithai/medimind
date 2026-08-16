"""Offline integration tests for intent-routed Q&A and evidence gates."""

import json
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

import retrieval


class FakeCollection:
    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def query(self, query_embeddings, n_results):
        selected = self.rows[:n_results]
        return {
            "documents": [[row[0] for row in selected]],
            "metadatas": [[row[1] for row in selected]],
        }


def _answer(sources, confidence=0.95):
    return json.dumps({
        "answer": "A grounded answer.",
        "confidence": confidence,
        "sources": sources,
        "recommend_professional_consult": False,
    })


def test_lab_trend_routes_out_medication_context_and_reports_sufficient_evidence():
    rows = [
        ("Medication: Metformin", {"chunk_type": "medication", "date": "2025-01-01", "source_file": "rx.pdf"}),
        ("Lab result: Glucose = 90", {"chunk_type": "lab_result", "date": "2025-01-01", "source_file": "lab1.pdf"}),
        ("Lab result: Glucose = 120", {"chunk_type": "lab_result", "date": "2025-03-01", "source_file": "lab2.pdf"}),
    ]
    raw = _answer([
        {"date": "2025-01-01", "source_file": "lab1.pdf"},
        {"date": "2025-03-01", "source_file": "lab2.pdf"},
    ])
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection(rows)), \
         mock.patch.object(retrieval, "embed_texts", return_value=[[0.1, 0.2]]), \
         mock.patch.object(retrieval, "_completion_resilient", return_value=raw) as completion:
        result = retrieval.answer_question("patient-1", "Has my glucose changed over time?")

    prompt = completion.call_args.kwargs["user_content"]
    assert "Glucose = 90" in prompt and "Glucose = 120" in prompt
    assert "Medication: Metformin" not in prompt
    assert result["question_intent"]["key"] == "lab_trend"
    assert result["evidence_sufficiency"]["level"] == "sufficient"
    assert result["evidence_sufficiency"]["citation_validation"] == "passed"
    assert result["confidence"] == 0.95


def test_no_matching_intent_evidence_returns_without_calling_llm():
    rows = [("Medication: Metformin", {"chunk_type": "medication", "date": "2025-01-01", "source_file": "rx.pdf"})]
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection(rows)), \
         mock.patch.object(retrieval, "embed_texts", return_value=[[0.1, 0.2]]), \
         mock.patch.object(retrieval, "_completion_resilient") as completion:
        result = retrieval.answer_question("patient-1", "What was my latest HbA1c result?")
    completion.assert_not_called()
    assert result["evidence_sufficiency"]["level"] == "insufficient"
    assert result["confidence"] == 0.0
    assert result["sources"] == []


def test_single_dated_result_caps_trend_answer_confidence():
    rows = [("Lab result: Glucose = 90", {"chunk_type": "lab_result", "date": "2025-01-01", "source_file": "lab.pdf"})]
    raw = _answer([{"date": "2025-01-01", "source_file": "lab.pdf"}], confidence=0.98)
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection(rows)), \
         mock.patch.object(retrieval, "embed_texts", return_value=[[0.1, 0.2]]), \
         mock.patch.object(retrieval, "_completion_resilient", return_value=raw):
        result = retrieval.answer_question("patient-1", "Has my glucose improved over time?")
    assert result["evidence_sufficiency"]["level"] == "limited"
    assert result["confidence"] == 0.65


def test_hallucinated_citation_is_removed_and_confidence_is_capped():
    rows = [("Lab result: HbA1c = 6.1", {"chunk_type": "lab_result", "date": "2025-01-01", "source_file": "real.pdf"})]
    raw = _answer([{"date": "2025-01-01", "source_file": "invented.pdf"}], confidence=0.99)
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection(rows)), \
         mock.patch.object(retrieval, "embed_texts", return_value=[[0.1, 0.2]]), \
         mock.patch.object(retrieval, "_completion_resilient", return_value=raw):
        result = retrieval.answer_question("patient-1", "What was my HbA1c result?")
    assert result["sources"] == []
    assert result["evidence_sufficiency"]["citation_validation"] == "no_valid_citations"
    assert result["evidence_sufficiency"]["level"] == "limited"
    # The upstream groundedness validator applies the stricter no-citation
    # ceiling (0.5) before the intent-aware evidence cap.
    assert result["confidence"] == 0.5


def test_safety_intent_enforces_professional_consult_even_if_model_does_not():
    rows = [("Medication: Aspirin", {"chunk_type": "medication", "date": "2025-01-01", "source_file": "rx.pdf"})]
    raw = _answer([{"date": "2025-01-01", "source_file": "rx.pdf"}])
    with mock.patch.object(retrieval, "_get_patient_collection", return_value=FakeCollection(rows)), \
         mock.patch.object(retrieval, "embed_texts", return_value=[[0.1, 0.2]]), \
         mock.patch.object(retrieval, "_completion_resilient", return_value=raw):
        result = retrieval.answer_question("patient-1", "Is aspirin safe for me?")
    assert result["question_intent"]["safety_sensitive"] is True
    assert result["recommend_professional_consult"] is True


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
