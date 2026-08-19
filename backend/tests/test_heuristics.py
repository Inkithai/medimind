"""Regression tests for extraction heuristics that used to drop real records.

* Filename "cv" substring matched cardiovascular / recovery / coverage.
* Hybrid PDFs were classified from the first 3 pages only.
* Conversation rewrite/summarize crashed on ProviderRateLimitError
  instead of falling back as documented.
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"

import conversation
from medical_extractor import (
    ProviderRateLimitError,
    classify_pdf_pages,
    looks_like_medical_text,
)


def test_cardiovascular_filename_is_not_a_cv():
    text = "Patient name: Jane Doe\nDate: 2024-01-01\nImpression: stable."
    assert looks_like_medical_text(text, "cardiovascular_note.pdf") is True
    assert looks_like_medical_text(text, "recovery_plan.pdf") is True
    assert looks_like_medical_text(text, "coverage_summary.pdf") is True


def test_actual_cv_filename_still_rejected():
    text = "Curriculum vitae\nEducation\nExperience\nSkills\nProjects"
    assert looks_like_medical_text(text, "john_cv.pdf") is False
    assert looks_like_medical_text(text, "jane-resume.pdf") is False


def test_classify_pdf_pages_splits_hybrid_packets():
    pages = [
        "City General Hospital\n123 Main Street\nConfidential patient packet",
        "",  # scanned lab image, no text layer
        "x",  # junk OCR crumbs, below the usable-text threshold
        "Prescription\nAmoxicillin 500 mg three times daily for 7 days",
    ]
    text_idx, image_idx = classify_pdf_pages(pages)
    assert text_idx == [0, 3]
    assert image_idx == [1, 2]


def test_rewrite_falls_back_on_provider_rate_limit():
    error = ProviderRateLimitError(provider="gemini", model="gemini-3.6-flash", hard_quota=True)
    with mock.patch.object(conversation, "_chat_completion", side_effect=error):
        out = conversation.rewrite_query_with_context(
            "was that safe?",
            [{"role": "user", "content": "what medication am I on?"}],
        )
    assert out == "was that safe?"


def test_summarize_falls_back_on_provider_rate_limit():
    error = ProviderRateLimitError(provider="gemini", model="gemini-3.6-flash", hard_quota=True)
    turns = [
        {"role": "user", "content": "what medication am I on?"},
        {"role": "assistant", "content": "Paracetamol 500 mg."},
    ]
    with mock.patch.object(conversation, "_chat_completion", side_effect=error):
        out = conversation.summarize_old_turns(turns)
    assert "Paracetamol" in out


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
