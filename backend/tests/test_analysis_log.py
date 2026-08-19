"""Analysis log grouping — one entry per uploaded document, not per page.

Documents are persisted one row per extracted page, so a three-page scan
used to render as three "Document extraction" analyses of the same file
with its medications counted three times. These tests pin the grouping,
the closed-vocabulary document type, and the conservative (lowest-page)
confidence.

Run with: pytest tests/test_analysis_log.py
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

from analysis_log import build_extraction_analyses, upload_group_key  # noqa: E402


def page(
    *,
    document_id,
    file="scan.pdf",
    page_no=1,
    content_sha256="hash-1",
    document_type="prescription",
    medications=0,
    labs=0,
    diagnoses=0,
    confidence=0.9,
    clinical_notes=None,
    uploaded_at="2026-08-19T10:00:00Z",
):
    return {
        "_document_id": document_id,
        "content_sha256": content_sha256,
        "document_type": document_type,
        "medications": [{"name": f"Med {i}"} for i in range(medications)],
        "lab_results": [{"test_name": f"Test {i}"} for i in range(labs)],
        "diagnoses": [{"name": f"Dx {i}"} for i in range(diagnoses)],
        "symptoms": [],
        "procedures": [],
        "vital_signs": [],
        "imaging_results": [],
        "allergies_noted": [],
        "clinical_notes": clinical_notes,
        "overall_confidence": confidence,
        "uploaded_at": uploaded_at,
        "_source": {"file": file, "method": "vision_ocr", "page": page_no},
    }


def test_pages_of_one_document_collapse_into_one_entry():
    docs = [
        page(document_id="doc_a", page_no=1, medications=2, labs=1),
        page(document_id="doc_b", page_no=2, medications=1, labs=3),
        page(document_id="doc_c", page_no=3, diagnoses=2),
    ]

    entries = build_extraction_analyses(docs)

    assert len(entries) == 1
    result = entries[0]["result"]
    assert result["page_count"] == 3
    assert result["persisted_counts"]["medications"] == 3
    assert result["persisted_counts"]["lab_results"] == 4
    assert result["persisted_counts"]["findings"] == 2
    assert result["document_ids"] == ["doc_a", "doc_b", "doc_c"]
    # The first page is the one the "open source document" link points at.
    assert result["document_id"] == "doc_a"
    assert entries[0]["id"] == "document_extraction:doc_a"


def test_separate_uploads_stay_separate():
    docs = [
        page(document_id="doc_a", file="rx.pdf", content_sha256="hash-1"),
        page(document_id="doc_b", file="labs.pdf", content_sha256="hash-2"),
    ]

    entries = build_extraction_analyses(docs)

    assert len(entries) == 2
    assert {e["result"]["source_file"] for e in entries} == {"rx.pdf", "labs.pdf"}


def test_legacy_rows_without_hash_group_by_filename():
    docs = [
        page(document_id="doc_a", content_sha256=None, page_no=1),
        page(document_id="doc_b", content_sha256=None, page_no=2),
    ]

    assert upload_group_key(docs[0]) == upload_group_key(docs[1]) == "file:scan.pdf"
    assert len(build_extraction_analyses(docs)) == 1


def test_row_without_any_identity_still_reported():
    orphan = page(document_id="doc_orphan", content_sha256=None)
    orphan["_source"] = {}

    entries = build_extraction_analyses([orphan])

    assert len(entries) == 1
    assert entries[0]["result"]["source_file"] == "uploaded document"


def test_confidence_is_the_weakest_page_not_the_average():
    docs = [
        page(document_id="doc_a", page_no=1, confidence=0.95),
        page(document_id="doc_b", page_no=2, confidence=0.41),
    ]

    entry = build_extraction_analyses(docs)[0]

    assert entry["confidence"] == 0.41
    assert entry["result"]["confidence_score"] == 0.41


def test_missing_confidence_is_none_not_zero():
    row = page(document_id="doc_a", confidence=None)
    row.pop("overall_confidence")

    entry = build_extraction_analyses([row])[0]

    assert entry["confidence"] is None
    assert entry["result"]["confidence_score"] is None


def test_document_type_is_pinned_to_the_closed_vocabulary():
    docs = [
        page(document_id="doc_a", page_no=1, document_type="Laboratory Report"),
        page(document_id="doc_b", page_no=2, document_type="Laboratory Report"),
    ]

    assert build_extraction_analyses(docs)[0]["result"]["document_type_detected"] == "lab_report"


def test_unknown_or_missing_document_type_never_leaks():
    docs = [page(document_id="doc_a", document_type=None)]

    assert build_extraction_analyses(docs)[0]["result"]["document_type_detected"] == "other"


def test_summary_prefers_clinical_notes_and_is_never_empty():
    with_notes = build_extraction_analyses(
        [page(document_id="doc_a", clinical_notes="Reviewed for dengue fever.")]
    )[0]
    assert with_notes["summary"] == "Reviewed for dengue fever."
    assert with_notes["result"]["summary"] == with_notes["summary"]

    without_notes = build_extraction_analyses(
        [
            page(document_id="doc_a", page_no=1, medications=2),
            page(document_id="doc_b", page_no=2, labs=1),
        ]
    )[0]
    assert without_notes["summary"]
    assert "2 medication(s)" in without_notes["summary"]
    assert "across 2 pages" in without_notes["summary"]


def test_created_at_is_the_latest_page_write():
    docs = [
        page(document_id="doc_a", page_no=1, uploaded_at="2026-08-01T00:00:00Z"),
        page(document_id="doc_b", page_no=2, uploaded_at="2026-08-05T00:00:00Z"),
    ]

    assert build_extraction_analyses(docs)[0]["created_at"] == "2026-08-05T00:00:00Z"


def test_analyses_endpoint_returns_one_card_per_document():
    from fastapi.testclient import TestClient

    import api

    docs = [
        page(document_id="doc_a", page_no=1, medications=2),
        page(document_id="doc_b", page_no=2, medications=1),
    ]

    async def override_user():
        return "anon_test_user"

    api.app.dependency_overrides[api.get_current_user] = override_user
    try:
        with (
            mock.patch.object(api.db, "load_documents", return_value=docs),
            mock.patch.object(
                api.db, "_get_client", side_effect=RuntimeError("no conversation table")
            ),
        ):
            with TestClient(api.app) as client:
                resp = client.get("/api/v1/analyses")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["total"] == 1
        assert len(body["analyses"]) == 1
        entry = body["analyses"][0]
        assert entry["analysis_type"] == "document_extraction"
        assert entry["result"]["persisted_counts"]["medications"] == 3
        # Ids must stay unique — the frontend keys its cards on them.
        assert len({item["id"] for item in body["analyses"]}) == len(body["analyses"])
    finally:
        api.app.dependency_overrides.clear()
