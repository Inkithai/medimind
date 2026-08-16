"""Offline tests for the richer QA response contract and deterministic
entity-focus carry-over.

Feature: QA contract
  - `cross_document`, `low_confidence`, `consult_reason` fields
  - deterministic guard FORCES recommend_professional_consult=true on
    risk / allergy / dosage questions (even if the model said false) and
    on low-confidence answers
  - sources enriched in code with document_type + document_url from the
    timeline

Feature: Entity focus carry-over
  - the session tracks medications/labs/documents under discussion by
    exact matching against the patient's own record vocabulary
  - focus survives an LLM rewrite failure: "what if I take it with this?"
    stays anchored to the earlier subject

Everything is mocked at the model boundary — no network involved.
"""
import os
import sys
import json
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ.pop("VECTOR_STORE", None)

from openai import OpenAIError  # noqa: E402

import retrieval  # noqa: E402
import conversation  # noqa: E402
from conversation import ConversationSession  # noqa: E402


TIMELINE = {
    "visits": [
        {
            "document_type": "prescription",
            "date": "2026-01-01",
            "provider_or_doctor": "Dr. Smith",
            "medications": [{
                "name": "Metformin", "ingredients": ["Metformin"],
                "dosage": "500 mg", "frequency": "2x daily", "duration": None,
                "dosage_value": 500, "dosage_unit": "mg", "frequency_per_day": 2,
                "is_as_needed": False, "confidence": 0.95,
            }],
            "lab_results": [],
            "allergies_noted": [],
            "clinical_notes": None,
            "overall_confidence": 0.92,
            "_source": {"file": "rx_metformin.pdf"},
            "document_url": "https://cloud/rx_metformin.pdf",
        },
        {
            "document_type": "lab_report",
            "date": "2026-02-01",
            "provider_or_doctor": "Lab",
            "medications": [],
            "lab_results": [{
                "test_name": "Fasting Glucose", "value": "105", "unit": "mg/dL",
                "reference_range": "70-99", "flag": "high", "confidence": 0.9,
            }],
            "allergies_noted": ["Penicillin"],
            "clinical_notes": None,
            "overall_confidence": 0.9,
            "_source": {"file": "labs_feb.pdf"},
            "document_url": "https://cloud/labs_feb.pdf",
        },
    ],
    "medications_timeline": [{
        "name": "Metformin", "ingredients": ["Metformin"], "dosage": "500 mg",
        "frequency": "2x daily", "duration": None, "dosage_value": 500,
        "dosage_unit": "mg", "frequency_per_day": 2, "is_as_needed": False,
        "confidence": 0.95, "date": "2026-01-01", "source_file": "rx_metformin.pdf",
        "prescription_group": "rx-0",
    }],
    "lab_results_timeline": [{
        "test_name": "Fasting Glucose", "value": "105", "unit": "mg/dL",
        "reference_range": "70-99", "flag": "high", "confidence": 0.9,
        "date": "2026-02-01", "source_file": "labs_feb.pdf",
    }],
    "known_allergies": ["Penicillin"],
    "duplicate_document_groups": [],
}


# ---------------------------------------------------------------------------
# 1. The deterministic consult guard
# ---------------------------------------------------------------------------

def _result(confidence=0.9, recommend=False):
    return {"answer": "an answer", "confidence": confidence, "sources": [],
            "cross_document": False, "recommend_professional_consult": recommend}


def test_risk_question_forces_consult_even_if_model_said_no():
    out = retrieval._apply_safety_guard(_result(recommend=False),
                                        "is it safe to take it together with alcohol?")
    assert out["recommend_professional_consult"] is True
    assert "safety, interactions, allergies, or a dosage change" in out["consult_reason"]
    assert out["low_confidence"] is False


def test_allergy_question_forces_consult():
    out = retrieval._apply_safety_guard(_result(),
                                        "I am allergic to penicillin — can I take amoxicillin?")
    assert out["recommend_professional_consult"] is True
    assert out["consult_reason"]


def test_dosage_question_forces_consult():
    for q in ("should I double my dose?",
              "can I increase the dosage to twice a day?",
              "is it ok to mix it with my other tablets?"):
        out = retrieval._apply_safety_guard(_result(), q)
        assert out["recommend_professional_consult"] is True, q


def test_low_confidence_forces_consult_and_flags():
    out = retrieval._apply_safety_guard(_result(confidence=0.4), "what is my latest test result?")
    assert out["low_confidence"] is True
    assert out["recommend_professional_consult"] is True
    assert "confidence is low" in out["consult_reason"]


def test_benign_confident_answer_not_escalated():
    out = retrieval._apply_safety_guard(_result(confidence=0.95), "what medication am I on?")
    assert out["recommend_professional_consult"] is False
    assert out["low_confidence"] is False
    assert "consult_reason" not in out


def test_guard_never_deescalates_model_recommendation():
    out = retrieval._apply_safety_guard(_result(recommend=True), "what medication am I on?")
    assert out["recommend_professional_consult"] is True
    assert out["consult_reason"]  # gets a generic reason attached


def test_threshold_boundary_counts_as_low():
    out = retrieval._apply_safety_guard(
        _result(confidence=retrieval.LOW_CONFIDENCE_THRESHOLD), "anything?")
    assert out["low_confidence"] is True
    assert out["recommend_professional_consult"] is True


# ---------------------------------------------------------------------------
# 2. Source enrichment (document_type + document_url from the timeline)
# ---------------------------------------------------------------------------

def test_enrich_sources_adds_type_and_url_in_code():
    sources = [
        {"date": "2026-01-01", "source_file": "rx_metformin.pdf"},
        {"date": "2026-02-01", "source_file": "labs_feb.pdf"},
        {"date": "unknown", "source_file": "not_on_file.pdf"},
    ]
    enriched = retrieval._enrich_sources(sources, TIMELINE)
    assert enriched[0]["document_type"] == "prescription"
    assert enriched[0]["document_url"] == "https://cloud/rx_metformin.pdf"
    assert enriched[1]["document_type"] == "lab_report"
    assert enriched[1]["document_url"] == "https://cloud/labs_feb.pdf"
    # Unknown files pass through without invented fields.
    assert "document_type" not in enriched[2]
    assert "document_url" not in enriched[2]


# ---------------------------------------------------------------------------
# 3. Record vocabulary — deterministic entity matching
# ---------------------------------------------------------------------------

def test_vocabulary_lists_record_entities():
    vocab = retrieval.build_record_vocabulary(TIMELINE)
    assert "Metformin" in vocab["medications"]
    assert "Fasting Glucose" in vocab["lab_tests"]
    assert "rx_metformin.pdf" in vocab["source_files"]
    assert vocab["allergies"] == ["Penicillin"]


def test_match_vocabulary_full_term():
    vocab = retrieval.build_record_vocabulary(TIMELINE)
    matched = retrieval.match_vocabulary("What is Metformin for?", vocab)
    assert matched["medications"] == ["Metformin"]


def test_match_vocabulary_distinctive_word():
    """'my glucose' must find the record's 'Fasting Glucose'."""
    vocab = retrieval.build_record_vocabulary(TIMELINE)
    matched = retrieval.match_vocabulary("how has my glucose been trending?", vocab)
    assert matched["lab_tests"] == ["Fasting Glucose"]


def test_match_vocabulary_short_term_whole_word_only():
    """'ALT' must not fire inside the word 'salt'."""
    vocab = {"medications": [], "lab_tests": ["ALT"], "source_files": []}
    assert retrieval.match_vocabulary("add a pinch of salt", vocab)["lab_tests"] == []
    assert retrieval.match_vocabulary("what was my ALT?", vocab)["lab_tests"] == ["ALT"]


def test_match_vocabulary_cannot_select_unlisted_drugs():
    """Matching is against the patient's closed vocabulary only."""
    vocab = retrieval.build_record_vocabulary(TIMELINE)
    matched = retrieval.match_vocabulary("should I take ibuprofen?", vocab)
    assert matched["medications"] == []


# ---------------------------------------------------------------------------
# 4. Focus context rendering
# ---------------------------------------------------------------------------

def test_focus_context_pins_established_facts():
    block = retrieval._render_focus_context(TIMELINE, {
        "medications": ["Metformin"], "lab_tests": [], "source_files": []})
    assert "Metformin" in block
    assert "500 mg" in block
    assert "rx_metformin.pdf" in block

    block2 = retrieval._render_focus_context(TIMELINE, {
        "medications": [], "lab_tests": ["Fasting Glucose"],
        "source_files": ["labs_feb.pdf"]})
    assert "Fasting Glucose = 105" in block2
    assert "labs_feb.pdf" in block2

    assert retrieval._render_focus_context(TIMELINE, {}) == ""


# ---------------------------------------------------------------------------
# 5. End-to-end answer_question contract (model mocked)
# ---------------------------------------------------------------------------

class FakeCollection:
    """Minimal Chroma stand-in shaped for the merged answer_question flow."""

    def __init__(self, count_value=0):
        self.count_value = count_value

    def count(self):
        return self.count_value

    def upsert(self, ids, embeddings, documents, metadatas):
        self.count_value = len(ids)

    def query(self, query_embeddings, n_results):
        return {
            "documents": [
                "Medication: Metformin 500 mg twice daily. Prescribed on "
                "2026-01-01 (source: rx_metformin.pdf).",
                "Lab result: Fasting Glucose = 105 mg/dL (flag: high). "
                "Recorded on 2026-02-01 (source: labs_feb.pdf).",
            ],
            "metadatas": [[
                {
                    "date": "2026-01-01", "source_file": "rx_metformin.pdf",
                    "source_page": 1, "document_id": "doc_1", "chunk_type": "medication",
                    "evidence_id": "ev_1", "evidence_quote": "Metformin 500 mg",
                    "evidence_bbox": None, "verification_status": "extracted",
                    "evidence_tier": "B",
                },
                {
                    "date": "2026-02-01", "source_file": "labs_feb.pdf",
                    "source_page": 1, "document_id": "doc_2", "chunk_type": "lab_result",
                    "evidence_id": "ev_2", "evidence_quote": "Fasting Glucose 105",
                    "evidence_bbox": None, "verification_status": "extracted",
                    "evidence_tier": "B",
                },
            ]],
        }


def _run_answer(question, answer_json, focus=None):
    captured = {}

    def capture_completion(model, system_prompt, user_content, strict_format=None, **kwargs):
        captured["user_content"] = user_content
        return answer_json

    collection = FakeCollection(
        count_value=len(retrieval.build_chunks_from_timeline("anon_contract", TIMELINE))
    )
    with mock.patch.object(retrieval, "_trusted_timeline_from_persisted_documents",
                           return_value=(TIMELINE, list(TIMELINE["visits"]))), \
         mock.patch.object(retrieval, "_get_patient_collection", return_value=collection), \
         mock.patch.object(retrieval.vector_store, "get_index_fingerprint", return_value=None), \
         mock.patch.object(retrieval, "embed_texts",
                           side_effect=lambda texts: [[0.1] * 384 for _ in texts]), \
         mock.patch.object(retrieval, "_completion_resilient",
                           side_effect=capture_completion):
        out = retrieval.answer_question("anon_contract", question, focus=focus)
    return out, captured


def test_answer_contract_risk_question_end_to_end():
    # The model claims high confidence and says NO consult is needed — the
    # deterministic guard must override it for a risk question.
    answer_json = json.dumps({
        "answer": "Metformin can interact with alcohol.",
        "confidence": 0.9,
        "confidence_reason": "Direct record evidence.",
        "sources": [{"date": "2026-01-01", "source_file": "rx_metformin.pdf"}],
        "cross_document": False,
        "recommend_professional_consult": False,
    })
    out, _ = _run_answer("is it safe to take metformin together with alcohol?", answer_json)
    assert out["recommend_professional_consult"] is True, out
    assert out["consult_reason"]
    assert out["low_confidence"] is False
    # Sources were enriched in code.
    assert out["sources"][0]["document_type"] == "prescription"
    assert out["sources"][0]["document_url"] == "https://cloud/rx_metformin.pdf"


def test_answer_contract_cross_document_passthrough_and_defaults():
    answer_json = json.dumps({
        "answer": "Your glucose was high in the Feb report while Metformin was prescribed in Jan.",
        "confidence": 0.8,
        "confidence_reason": "Combined records.",
        "sources": [
            {"date": "2026-01-01", "source_file": "rx_metformin.pdf"},
        ],
        "cross_document": True,
        "recommend_professional_consult": False,
    })
    out, _ = _run_answer("compare my prescription and my lab report", answer_json)
    assert out["cross_document"] is True

    # A model fallback missing the new field defaults it to False.
    partial = json.dumps({
        "answer": "You are on Metformin.", "confidence": 0.9,
        "sources": [{"date": "2026-01-01", "source_file": "rx_metformin.pdf"}],
        "recommend_professional_consult": False,
    })
    out2, _ = _run_answer("what medication am I on?", partial)
    assert out2["cross_document"] is False
    assert out2["low_confidence"] is False


def test_focus_block_reaches_the_prompt():
    answer_json = json.dumps({
        "answer": "You are on Metformin 500 mg.", "confidence": 0.95,
        "confidence_reason": "Direct record evidence.",
        "sources": [{"date": "2026-01-01", "source_file": "rx_metformin.pdf"}],
        "cross_document": False, "recommend_professional_consult": False,
    })
    _, captured = _run_answer(
        "what if I take it with this?", answer_json,
        focus={"medications": ["Metformin"], "lab_tests": [], "source_files": []})
    assert "Entities this conversation is already about" in captured["user_content"]
    assert "Metformin" in captured["user_content"]


# ---------------------------------------------------------------------------
# 6. Conversation focus carry-over
# ---------------------------------------------------------------------------

CANNED_ANSWER = {
    "answer": "Metformin is prescribed for blood sugar control.",
    "confidence": 0.9,
    "sources": [{"date": "2026-01-01", "source_file": "rx_metformin.pdf",
                 "document_type": "prescription"}],
    "cross_document": False,
    "recommend_professional_consult": False,
    "low_confidence": False,
}


def _ask(session, question):
    """Runs conversation.ask with the model boundary mocked: the rewrite
    call FAILS (OpenAIError), so any focus that survives does so purely by
    the deterministic vocabulary matching."""
    captured = {}

    def capture_answer(**kwargs):
        captured.update(kwargs)
        return dict(CANNED_ANSWER)

    with mock.patch.object(retrieval, "_timeline_for", return_value=TIMELINE), \
         mock.patch.object(retrieval, "answer_question", side_effect=capture_answer), \
         mock.patch.object(conversation, "_chat_completion",
                           side_effect=OpenAIError("rate limited")):
        result = conversation.ask(session, question)
    return result, captured


def test_focus_resolved_against_record_vocabulary():
    session = ConversationSession("anon_focus", "s1")
    result, captured = _ask(session, "What is Metformin for?")
    assert result["focus"]["medications"] == ["Metformin"]
    assert captured["focus"]["medications"] == ["Metformin"]
    # The turn was tagged with the resolved entity.
    assert session.turns[0]["entities"]["medications"] == ["Metformin"]


def test_focus_carries_over_when_rewrite_fails():
    """'what if I take it with this?' names nothing — the subject must come
    from the previous turn's focus, even though the rewrite call failed."""
    session = ConversationSession("anon_focus", "s2")
    _ask(session, "What is Metformin for?")
    result, captured = _ask(session, "what if I take it with this?")

    # Rewrite failure fell back to the raw question...
    assert result["rewritten_query"] == "what if I take it with this?"
    # ...but the subject still survived via deterministic focus.
    assert captured["focus"]["medications"] == ["Metformin"]
    assert result["focus"]["medications"] == ["Metformin"]


def test_focus_merges_cited_documents_from_assistant_turns():
    session = ConversationSession("anon_focus", "s3")
    _ask(session, "What is Metformin for?")
    # The canned answer cites rx_metformin.pdf — that file is now part of
    # what the conversation is "about".
    focus = session.get_focus()
    assert "rx_metformin.pdf" in focus["source_files"]
    _, captured = _ask(session, "and what about my glucose?")
    assert "Fasting Glucose" in captured["focus"]["lab_tests"]
    assert "rx_metformin.pdf" in captured["focus"]["source_files"]


def test_current_turn_outranks_carried_focus():
    """When a turn names a new entity, it leads the focus list ahead of
    whatever was carried over."""
    vocab_timeline = dict(TIMELINE)
    vocab_timeline["medications_timeline"] = list(TIMELINE["medications_timeline"]) + [{
        "name": "Ibuprofen", "ingredients": ["Ibuprofen"], "dosage": "200 mg",
        "frequency": "1x daily", "duration": None, "dosage_value": 200,
        "dosage_unit": "mg", "frequency_per_day": 1, "is_as_needed": True,
        "confidence": 0.9, "date": "2026-03-01", "source_file": "rx_ibuprofen.pdf",
        "prescription_group": "rx-1",
    }]
    session = ConversationSession("anon_focus", "s4")

    def capture_answer(**kwargs):
        capture_answer.kwargs = kwargs
        return dict(CANNED_ANSWER)

    with mock.patch.object(retrieval, "_timeline_for", return_value=vocab_timeline), \
         mock.patch.object(retrieval, "answer_question", side_effect=capture_answer), \
         mock.patch.object(conversation, "_chat_completion",
                           side_effect=OpenAIError("rate limited")):
        conversation.ask(session, "What is Metformin for?")
        conversation.ask(session, "Can I take ibuprofen with it?")

    meds = capture_answer.kwargs["focus"]["medications"]
    assert meds[0] == "Ibuprofen"      # named this turn -> leads
    assert "Metformin" in meds         # carried over -> still present


def test_focus_expires_after_turn_memory():
    session = ConversationSession("anon_focus", "s5")
    session.add_user_turn("What is Metformin for?",
                          entities={"medications": ["Metformin"]})
    for i in range(conversation.FOCUS_TURN_MEMORY):
        session.add_user_turn(f"unrelated chatter {i}", entities={})
    assert session.get_focus()["medications"] == [], (
        "focus must not drag an old subject back after the conversation moved on")


def test_history_shape_unchanged_for_prompting():
    session = ConversationSession("anon_focus", "s6")
    session.add_user_turn("hi", entities={"medications": ["Metformin"]})
    history = session.get_history()
    # Entities are stored per turn but never leak into the prompt history.
    assert history == [{"role": "user", "content": "hi"}]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
