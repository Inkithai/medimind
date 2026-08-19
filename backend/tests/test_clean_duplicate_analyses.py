"""Duplicate document-row cleanup — what it removes and what it must not.

Deleting a medical record row is irreversible, so these tests pin the
safety rules of clean_duplicate_analyses.py: dry run by default, only
byte-identical re-ingests of the same page are candidates, the newest
copy survives, and anything the script cannot prove is a duplicate
(different pages, changed content, corrected documents, rows with no
upload identity) is preserved.

Run with: pytest tests/test_clean_duplicate_analyses.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from clean_duplicate_analyses import (  # noqa: E402
    clean_duplicate_document_rows,
    plan_duplicate_cleanup,
)


def row(
    row_id,
    *,
    document_id,
    file="rx.pdf",
    page=1,
    content_sha256="hash-1",
    medications=("Paracetamol",),
    uploaded_at="2026-08-01T00:00:00Z",
):
    return {
        "id": row_id,
        "uploaded_at": uploaded_at,
        "data": {
            "_document_id": document_id,
            "content_sha256": content_sha256,
            "document_type": "prescription",
            "medications": [{"name": name} for name in medications],
            "lab_results": [],
            "allergies_noted": [],
            "clinical_notes": None,
            "overall_confidence": 0.9,
            "document_url": f"https://cloud/{document_id}.pdf",
            "_source": {"file": file, "method": "vision_ocr", "page": page},
        },
    }


class FakeDb:
    def __init__(self, rows, correction_events=()):
        self.rows = list(rows)
        self.correction_events = list(correction_events)
        self.deleted = []

    def load_document_rows(self, user_id):
        return self.rows

    def load_correction_events(self, user_id):
        return self.correction_events

    def delete_document_rows(self, user_id, row_ids):
        self.deleted.extend(row_ids)
        return len(row_ids)


def test_identical_reingest_is_a_duplicate_and_newest_survives():
    plan = plan_duplicate_cleanup(
        [
            row(1, document_id="doc_old", uploaded_at="2026-08-01T00:00:00Z"),
            row(2, document_id="doc_new", uploaded_at="2026-08-09T00:00:00Z"),
        ]
    )

    assert plan["duplicates_identified"] == 1
    assert [item["id"] for item in plan["duplicates"]] == [1]
    assert plan["kept_records"] == 1


def test_pages_of_one_document_are_not_duplicates():
    plan = plan_duplicate_cleanup(
        [
            row(1, document_id="doc_p1", page=1),
            row(2, document_id="doc_p2", page=2),
            row(3, document_id="doc_p3", page=3),
        ]
    )

    assert plan["duplicates_identified"] == 0
    assert plan["unique_groups"] == 3


def test_changed_clinical_content_is_never_deleted():
    plan = plan_duplicate_cleanup(
        [
            row(1, document_id="doc_a", medications=("Paracetamol",)),
            row(2, document_id="doc_b", medications=("Paracetamol", "Amoxicillin")),
        ]
    )

    assert plan["duplicates_identified"] == 0


def test_storage_bookkeeping_differences_do_not_block_dedup():
    first = row(1, document_id="doc_a", uploaded_at="2026-08-01T00:00:00Z")
    second = row(2, document_id="doc_b", uploaded_at="2026-08-02T00:00:00Z")
    second["data"]["cloudinary_public_id"] = None
    second["data"]["storage_backend"] = "supabase"
    second["data"]["raw_text_processing"] = {"processing_status": "ok"}

    plan = plan_duplicate_cleanup([first, second])

    assert [item["id"] for item in plan["duplicates"]] == [1]


def test_corrected_document_is_preserved():
    plan = plan_duplicate_cleanup(
        [
            row(1, document_id="doc_old", uploaded_at="2026-08-01T00:00:00Z"),
            row(2, document_id="doc_new", uploaded_at="2026-08-09T00:00:00Z"),
        ],
        corrected_document_ids=["doc_old"],
    )

    assert plan["duplicates_identified"] == 0
    assert plan["corrected_preserved"] == 1


def test_rows_without_upload_identity_are_preserved():
    orphan = row(1, document_id="doc_a", content_sha256=None)
    orphan["data"].pop("content_sha256")
    orphan["data"]["_source"] = {}

    plan = plan_duplicate_cleanup([orphan, orphan])

    assert plan["duplicates_identified"] == 0
    assert plan["unmapped_preserved"] == 2


def test_dry_run_is_the_default_and_deletes_nothing():
    fake = FakeDb(
        [
            row(1, document_id="doc_old", uploaded_at="2026-08-01T00:00:00Z"),
            row(2, document_id="doc_new", uploaded_at="2026-08-09T00:00:00Z"),
        ]
    )

    summary = clean_duplicate_document_rows("user-1", db_module=fake)

    assert summary["dry_run"] is True
    assert summary["duplicates_identified"] == 1
    assert summary["records_deleted"] == 0
    assert fake.deleted == []


def test_execute_deletes_only_the_identified_duplicates():
    fake = FakeDb(
        [
            row(1, document_id="doc_old", uploaded_at="2026-08-01T00:00:00Z"),
            row(2, document_id="doc_new", uploaded_at="2026-08-09T00:00:00Z"),
            row(3, document_id="doc_other", file="labs.pdf", content_sha256="hash-2"),
        ]
    )

    summary = clean_duplicate_document_rows("user-1", dry_run=False, db_module=fake)

    assert fake.deleted == [1]
    assert summary["records_deleted"] == 1
    assert summary["kept_records"] == 2


def test_missing_corrections_table_does_not_widen_deletion():
    class NoCorrections(FakeDb):
        def load_correction_events(self, user_id):
            raise RuntimeError("relation extraction_corrections does not exist")

    fake = NoCorrections(
        [
            row(1, document_id="doc_old", uploaded_at="2026-08-01T00:00:00Z"),
            row(2, document_id="doc_new", uploaded_at="2026-08-09T00:00:00Z"),
        ]
    )

    summary = clean_duplicate_document_rows("user-1", dry_run=False, db_module=fake)

    assert summary["records_deleted"] == 1
    assert fake.deleted == [1]
