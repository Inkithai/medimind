"""Offline tests for document deduplication (feature: CBC_Report.pdf /
CBC_Report (1).pdf re-upload detection).

Two layers are covered:
  1. document_dedup.py — same-PRESCRIPTION grouping (semantic fingerprint),
     so one prescription uploaded twice counts once in duplicate detection.
  2. api.py upload pipeline — byte-for-byte re-upload detection via
     content_sha256, which skips an identical file BEFORE any LLM
     extraction call and never adds it a second time.

Mocks the ML pipeline, storage and Supabase so no network is involved.
"""

import hashlib
import os
import sys
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ["GROQ_API_KEY"] = "gsk_test_123"
os.environ["SUPABASE_URL"] = "https://dummy.supabase.co"
os.environ["SUPABASE_SERVICE_ROLE_KEY"] = "dummy"
os.environ["CLOUDINARY_CLOUD_NAME"] = "dummy"
os.environ["CLOUDINARY_API_KEY"] = "dummy"
os.environ["CLOUDINARY_API_SECRET"] = "dummy"
os.environ["JWT_SECRET"] = "dummy"
os.environ.pop("VECTOR_STORE", None)

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402
import document_dedup  # noqa: E402
from medical_extractor import (  # noqa: E402
    build_patient_timeline,
    detect_exact_duplicate_medications,
)

# ---------------------------------------------------------------------------
# 1. Same-prescription grouping (document_dedup.py)
# ---------------------------------------------------------------------------


def _rx(source, date, patient="RAMESH", doctor="Dr. K. Jayasuriya"):
    return {
        "document_type": "prescription",
        "date": date,
        "patient_name": patient,
        "provider_or_doctor": doctor,
        "medications": [
            {
                "name": "Paracetamol",
                "ingredients": ["Paracetamol"],
                "dosage_value": 1000,
                "dosage_unit": "mg",
                "frequency_per_day": 3,
                "is_as_needed": False,
            },
            {
                "name": "Omeprazole",
                "ingredients": ["Omeprazole"],
                "dosage_value": 20,
                "dosage_unit": "mg",
                "frequency_per_day": 1,
                "is_as_needed": False,
            },
        ],
        "_source": {"file": source},
    }


def test_reuploaded_prescription_groups_together():
    a = _rx("scan.png", "09/11/2025")
    b = _rx("phone_photo.jpeg", "2025-11-09")  # same date, different format
    document_dedup.annotate_prescription_groups([a, b])
    assert a["prescription_group"] == b["prescription_group"]


def test_repeat_prescription_months_later_stays_separate():
    a = _rx("scan.png", "09/11/2025")
    b = _rx("repeat.png", "26/02/2026")
    document_dedup.annotate_prescription_groups([a, b])
    assert a["prescription_group"] != b["prescription_group"]


def test_salt_forms_do_not_split_one_prescription():
    a = _rx("scan.png", "09/11/2025")
    a["medications"][0]["ingredients"] = ["Paracetamol"]
    b = _rx("photo.jpeg", "09/11/2025")
    b["medications"][0] = {
        **b["medications"][0],
        "name": "Paracetamol sodium",
        "ingredients": ["Paracetamol sodium"],
    }
    document_dedup.annotate_prescription_groups([a, b])
    assert a["prescription_group"] == b["prescription_group"]


def test_lab_reports_never_merge_on_empty_medication_set():
    a = {
        "document_type": "lab_report",
        "date": "01/01/2026",
        "patient_name": "R",
        "medications": [],
        "_source": {"file": "CBC_Report.pdf"},
    }
    b = {
        "document_type": "lab_report",
        "date": "01/01/2026",
        "patient_name": "R",
        "medications": [],
        "_source": {"file": "CBC_Report (1).pdf"},
    }
    document_dedup.annotate_prescription_groups([a, b])
    assert a["prescription_group"] != b["prescription_group"]
    assert document_dedup.find_duplicate_document_groups([a, b]) == []


def test_timeline_reupload_does_not_flag_duplicate_medication():
    """The clinically-consequential case: one prescription uploaded twice
    must not make its drugs look 'prescribed twice' to the deterministic
    duplicate detector."""
    timeline = build_patient_timeline(
        [_rx("scan.png", "2025-11-09"), _rx("scan (1).png", "2025-11-09")]
    )
    assert timeline["medications_timeline"], "timeline keeps every entry"
    assert len(timeline["duplicate_document_groups"]) == 1, (
        "the two files are reported as one prescription for review"
    )
    assert detect_exact_duplicate_medications(timeline) == [], (
        "no duplicate-prescription finding may be manufactured by a re-upload"
    )


def test_genuine_repeat_still_flagged_deterministically():
    timeline = build_patient_timeline(
        [_rx("scan.png", "2025-11-09"), _rx("repeat.png", "2026-02-26")]
    )
    dups = detect_exact_duplicate_medications(timeline)
    # One finding per duplicated ingredient (both drugs were re-prescribed).
    assert len(dups) == 2
    for dup in dups:
        assert dup["evidence_source"] == "deterministic"
        assert dup["confidence"] == 0.95


# ---------------------------------------------------------------------------
# 2. Byte-for-byte re-upload detection at upload time (api.py)
# ---------------------------------------------------------------------------

EXTRACTED_DOC = {
    "document_type": "lab_report",
    "date": "2024-03-15",
    "provider_or_doctor": "Dr. Smith",
    "patient_name": "John Doe",
    "medications": [],
    "lab_results": [
        {
            "test_name": "Hemoglobin",
            "value": "13.2",
            "unit": "g/dL",
            "reference_range": "13-17",
            "flag": "normal",
            "confidence": 0.95,
        }
    ],
    "allergies_noted": [],
    "clinical_notes": None,
    "illegible_or_low_confidence_fields": [],
    "overall_confidence": 0.92,
}


def _make_client(existing_docs, process_document_mock, insert_side_effect=None):
    app = api.app

    async def override_user():
        return "anon_dedup_user"

    app.dependency_overrides[api.get_current_user] = override_user

    patchers = [
        mock.patch.object(
            api.storage,
            "upload_patient_document",
            return_value={"document_url": "https://cloud/x.pdf", "cloudinary_public_id": "x"},
        ),
        mock.patch.object(api.db, "load_documents", return_value=list(existing_docs)),
        mock.patch.object(
            api.db,
            "insert_documents",
            **({"side_effect": insert_side_effect} if insert_side_effect else {}),
        ),
        mock.patch.object(api.db, "save_patient_snapshot"),
        mock.patch.object(
            api.db,
            "load_patient_snapshot",
            return_value={
                "patient_timeline": {"visits": []},
                "cross_check_report": {},
                "lab_trends": {"trends": [], "insufficient_data": []},
            },
        ),
        mock.patch.object(api, "process_document", side_effect=process_document_mock),
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
    for p in patchers:
        p.start()
    return app, patchers


def test_identical_reupload_skipped_before_extraction():
    """Uploading a file whose bytes match one already on file must add
    nothing, call the extractor zero times, and explain itself."""
    content = b"%PDF-1.4 the exact same CBC report bytes"
    existing = [
        {
            **EXTRACTED_DOC,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "_source": {"file": "CBC_Report.pdf"},
            "uploaded_at": "2026-08-01T00:00:00+00:00",
        }
    ]
    process_document = mock.MagicMock()
    app, patchers = _make_client(existing, process_document)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("CBC_Report (1).pdf", content, "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents_added"] == 0
        assert body["files_added"] == 0
        assert body["all_files_duplicate"] is True
        skipped = body["duplicate_files_skipped"]
        assert len(skipped) == 1
        assert skipped[0]["filename"] == "CBC_Report (1).pdf"
        assert skipped[0]["previously_uploaded_as"] == "CBC_Report.pdf"
        assert "already in your records" in skipped[0]["message"]
        process_document.assert_not_called()  # no LLM call wasted
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_same_file_twice_in_one_batch_processed_once():
    content = b"%PDF-1.4 one file sent twice in the same request"
    process_document = mock.MagicMock(return_value=dict(EXTRACTED_DOC, _source={"file": "ignored"}))
    app, patchers = _make_client([], process_document)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[
                    ("files", ("CBC_Report.pdf", content, "application/pdf")),
                    ("files", ("CBC_Report (1).pdf", content, "application/pdf")),
                ],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents_added"] == 1
        assert len(body["duplicate_files_skipped"]) == 1
        assert process_document.call_count == 1
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_new_upload_persists_content_sha256():
    """Every saved page must carry its content hash so the NEXT upload can
    recognise it."""
    content = b"%PDF-1.4 brand new report bytes"
    inserted = {}

    def capture_insert(user_id, docs):
        inserted["docs"] = docs

    process_document = mock.MagicMock(return_value=dict(EXTRACTED_DOC))
    app, patchers = _make_client([], process_document, insert_side_effect=capture_insert)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("CBC_Report.pdf", content, "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        docs = inserted["docs"]
        assert len(docs) == 1
        assert docs[0]["content_sha256"] == hashlib.sha256(content).hexdigest()
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


def test_different_bytes_same_name_not_treated_as_duplicate():
    """A same-named file with different content is a genuine new document."""
    existing = [
        {
            **EXTRACTED_DOC,
            "content_sha256": hashlib.sha256(b"old bytes").hexdigest(),
            "_source": {"file": "CBC_Report.pdf"},
            "uploaded_at": "2026-08-01T00:00:00+00:00",
        }
    ]
    process_document = mock.MagicMock(return_value=dict(EXTRACTED_DOC))
    app, patchers = _make_client(existing, process_document)
    try:
        with TestClient(app) as client:
            resp = client.post(
                "/api/v1/documents",
                files=[("files", ("CBC_Report.pdf", b"%PDF-1.4 new bytes", "application/pdf"))],
            )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["documents_added"] == 1
        assert body["duplicate_files_skipped"] == []
        assert process_document.call_count == 1
    finally:
        for p in patchers:
            p.stop()
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Regression: ISO dates are NOT day/month-ambiguous. dateutil's dayfirst=True
# reads "2025-11-09" as 11 September, which used to give every ISO date a
# phantom second reading — so two ISO prescription dates two months apart
# ("2025-11-09" vs "2025-09-11") intersected on the phantom day and could
# merge two genuinely separate repeat prescriptions into one group.
# ---------------------------------------------------------------------------


def test_iso_dates_have_a_single_reading():
    assert sorted(str(d) for d in document_dedup.plausible_dates("2025-11-09")) == ["2025-11-09"]


def test_distinct_iso_prescription_dates_do_not_merge():
    a = _rx("scan.png", "2025-11-09")
    b = _rx("photo.jpeg", "2025-09-11")
    document_dedup.annotate_prescription_groups([a, b])
    assert a["prescription_group"] != b["prescription_group"]


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")
