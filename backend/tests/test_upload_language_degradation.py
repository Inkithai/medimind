"""A partially-translated prescription is kept, not refused.

The upload pipeline used to reject the whole file when any drug name failed
to normalize into its English (INN) form. A photographed non-English
prescription usually normalizes partially, so that rule discarded the
medications that HAD resolved along with the one that had not, and left the
user with no record at all.

The file is now accepted at a reduced confidence with the unmatchable
medications marked `cross_check_eligible: False`, and the response says
which medicines will not take part in duplicate/interaction checking.

Run with: pytest tests/test_upload_language_degradation.py
"""

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GROQ_API_KEY", "gsk_test_123")
os.environ.setdefault("SUPABASE_URL", "https://dummy.supabase.co")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_CLOUD_NAME", "dummy")
os.environ.setdefault("CLOUDINARY_API_KEY", "dummy")
os.environ.setdefault("CLOUDINARY_API_SECRET", "dummy")
os.environ.setdefault("JWT_SECRET", "dummy")

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402

# One medicine resolved to its INN, one did not — the normal outcome for a
# photographed non-English prescription.
MIXED_TRANSLATION_DOC = {
    "document_type": "prescription",
    "date": "2026-08-15",
    "provider_or_doctor": "Dr. Perera",
    "patient_name": "Nimal Silva",
    "document_language": "Sinhala",
    "additional_languages": [],
    "medications": [
        {
            "name": "Metformin",
            "ingredients": ["Metformin"],
            "dosage": "500 mg",
            "frequency": "twice daily",
            "confidence": 0.95,
        },
        {
            "name": "ලොසාටන්",
            "ingredients": [],
            "dosage": "50 mg",
            "frequency": "daily",
            "confidence": 0.9,
        },
    ],
    "lab_results": [],
    "allergies_noted": [],
    "clinical_notes": None,
    "illegible_or_low_confidence_fields": [],
    "overall_confidence": 0.93,
}


def _client():
    app = api.app

    async def override_user():
        return "anon_language_user"

    app.dependency_overrides[api.get_current_user] = override_user
    saved = {}

    def _capture(user_id, docs):
        saved["docs"] = docs

    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.jpg", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=[]),
        mock.patch.object(api.db, "insert_documents", side_effect=_capture),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(api, "process_document", return_value=dict(MIXED_TRANSLATION_DOC)),
        # The safety analysis is the only LLM call left in the pipeline; the
        # route resolves it through api.cross_check_prescriptions at call
        # time, which is what makes this patch effective.
        mock.patch.object(
            api,
            "cross_check_prescriptions",
            return_value={
                "potential_drug_interactions": [],
                "duplicate_prescriptions": [],
                "conflicting_dosage_instructions": [],
                "allergy_conflicts": [],
                "overall_recommendation": "Consult a professional.",
            },
        ),
        mock.patch.object(api, "index_patient_timeline", return_value=2),
    ]
    for patcher in patchers:
        patcher.start()
    return app, patchers, saved


def test_partially_translated_upload_is_accepted_and_reported():
    app, patchers, saved = _client()
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.jpg", b"\xff\xd8\xff" + b"a", "image/jpeg"))],
            )

        # Accepted, not refused with 422.
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents_added"] == 1

        degradations = body["language_degradations"]
        assert len(degradations) == 1
        entry = degradations[0]
        assert entry["file"] == "rx.jpg"
        assert entry["unmatched_medications"] == ["ලොසාටන්"]
        assert entry["languages"] == ["Sinhala"]
        assert "cannot be compared" in entry["message"]

        # The document persisted carries the marking, so the gap is visible
        # in the record rather than implied by the document's absence.
        stored = saved["docs"][0]
        assert stored["translation_incomplete"] is True
        assert stored["overall_confidence"] == 0.4
        resolved, unmatched = stored["medications"]
        assert resolved["name"] == "Metformin"
        assert "cross_check_eligible" not in resolved
        assert unmatched["cross_check_eligible"] is False
        assert unmatched["confidence"] == 0.3
    finally:
        for patcher in patchers:
            patcher.stop()
        app.dependency_overrides.clear()


def test_fully_translated_upload_reports_no_degradation():
    app, patchers, _ = _client()
    try:
        clean = dict(MIXED_TRANSLATION_DOC)
        clean["medications"] = [
            {
                "name": "ලොසාටන්",
                "ingredients": ["Losartan"],
                "dosage": "50 mg",
                "frequency": "daily",
                "confidence": 0.9,
            }
        ]
        api.process_document.return_value = clean
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("rx.jpg", b"\xff\xd8\xff" + b"a", "image/jpeg"))],
            )
        assert resp.status_code == 201, resp.text
        assert resp.json()["language_degradations"] == []
    finally:
        for patcher in patchers:
            patcher.stop()
        app.dependency_overrides.clear()
