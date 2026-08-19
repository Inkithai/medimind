"""Regression: filename 'cv' must not reject real medical documents.

looks_like_medical_text() used `\"cv\" in filename`, which is True for
recovery.pdf and cardiovascular.pdf. Combined with a sparse-text lab
report that has fewer than 3 medical keyword hits, those files were
rejected before the LLM ever ran.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")

from medical_extractor import looks_like_medical_text  # noqa: E402

SPARSE_LAB = "Patient: Jane Doe\nGlucose 95 mg/dL\n"


def test_recovery_filename_is_not_treated_as_a_cv():
    assert looks_like_medical_text(SPARSE_LAB, "recovery.pdf") is True


def test_cardiovascular_filename_is_not_treated_as_a_cv():
    assert looks_like_medical_text(SPARSE_LAB, "cardiovascular_report.pdf") is True


def test_actual_cv_filename_still_rejected():
    resume = "Curriculum Vitae\nEducation\nExperience\nSkills\nProjects\n"
    assert looks_like_medical_text(resume, "jane_doe_cv.pdf") is False


def test_resume_filename_still_rejected():
    resume = "Curriculum Vitae\nEducation\nExperience\nSkills\n"
    assert looks_like_medical_text(resume, "resume.pdf") is False
