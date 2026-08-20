"""Offline regression tests for document and workspace deletion flows."""

import asyncio
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
os.environ.setdefault("JWT_SECRET", "test-secret-for-document-deletion")

import api  # noqa: E402


def _doc(document_id, page, *, content_hash="same-hash", public_id="mediscan/user/report"):
    return {
        "_document_id": document_id,
        "_source": {"file": "report.pdf", "page": page},
        "content_sha256": content_hash,
        "cloudinary_public_id": public_id,
        "medications": [],
        "lab_results": [],
    }


def test_delete_document_removes_every_page_and_rebuilds_without_the_upload():
    deleted_pages = [_doc("doc-1", 1), _doc("doc-2", 2)]
    remaining = _doc("doc-3", 1, content_hash="other-hash", public_id="mediscan/user/other")
    rebuild = {
        "documents_remaining": 1,
        "timeline": {},
        "indexed": True,
        "index_error": None,
    }
    with (
        mock.patch.object(api.jobs, "list_jobs", return_value=[]),
        mock.patch.object(api.db, "load_documents", return_value=[*deleted_pages, remaining]),
        mock.patch.object(api.storage, "delete_patient_document") as delete_original,
        mock.patch.object(api.db, "delete_document_group", return_value=2) as delete_rows,
        mock.patch.object(api.db, "delete_document_corrections") as delete_corrections,
        mock.patch.object(api.db, "clear_document_derived_history") as clear_history,
        mock.patch.object(api.jobs, "delete_user_jobs") as clear_jobs,
        mock.patch.object(api.conversation, "delete_patient_sessions") as clear_sessions,
        mock.patch.object(
            api, "_rebuild_after_document_deletion", new=mock.AsyncMock(return_value=rebuild)
        ) as rebuild_record,
        mock.patch.object(api.audit, "record"),
    ):
        response = asyncio.run(api.delete_document("doc-1", "user"))

    assert response["deleted"] is True
    assert response["pages_deleted"] == 2
    assert response["documents_remaining"] == 1
    delete_original.assert_called_once_with("mediscan/user/report")
    assert delete_rows.call_args.kwargs["content_sha256"] == "same-hash"
    assert delete_corrections.call_args.args == ("user", ["doc-1", "doc-2"])
    clear_history.assert_called_once_with("user")
    clear_jobs.assert_called_once_with("user")
    clear_sessions.assert_called_once_with("user")
    passed_remaining = rebuild_record.call_args.args[1]
    assert [item["_document_id"] for item in passed_remaining] == ["doc-3"]


def test_delete_document_waits_for_an_active_reprocess():
    import routes.upload as upload_routes

    upload_routes._active_document_jobs.clear()
    try:
        assert upload_routes.register_document_job("user", "doc-1") is True
        with (
            mock.patch.object(api.jobs, "list_jobs", return_value=[]),
            mock.patch.object(api.db, "delete_document_group") as delete_rows,
        ):
            try:
                asyncio.run(api.delete_document("doc-1", "user"))
            except api.HTTPException as exc:
                assert exc.status_code == 409
            else:
                raise AssertionError("an in-flight reprocess must block document deletion")
        delete_rows.assert_not_called()
    finally:
        upload_routes.unregister_document_job("user", "doc-1")


def test_delete_document_waits_for_an_active_upload():
    with (
        mock.patch.object(api.jobs, "list_jobs", return_value=[{"status": "pending"}]),
        mock.patch.object(api.db, "delete_document_group") as delete_rows,
    ):
        try:
            asyncio.run(api.delete_document("doc-1", "user"))
        except api.HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("an active upload must block document deletion")
    delete_rows.assert_not_called()


def test_delete_workspace_waits_for_an_active_upload():
    with (
        mock.patch.object(api.jobs, "list_jobs", return_value=[{"status": "processing"}]),
        mock.patch.object(api.db, "delete_workspace_data") as delete_data,
    ):
        try:
            asyncio.run(api.delete_workspace("user"))
        except api.HTTPException as exc:
            assert exc.status_code == 409
        else:
            raise AssertionError("an active upload must block workspace deletion")
    delete_data.assert_not_called()


def test_delete_workspace_removes_originals_durable_data_and_memory_caches():
    docs = [_doc("doc-1", 1), _doc("doc-2", 2)]
    with (
        mock.patch.object(api.jobs, "list_jobs", return_value=[]),
        mock.patch.object(api.db, "load_documents", return_value=docs),
        mock.patch.object(api.storage, "delete_workspace_originals") as delete_originals,
        mock.patch.object(
            api.db, "delete_workspace_data", return_value={"documents": 2}
        ) as delete_data,
        mock.patch.object(api.jobs, "delete_user_jobs") as delete_jobs,
        mock.patch.object(api.conversation, "delete_patient_sessions") as delete_sessions,
        mock.patch.object(api.vector_store, "delete_collection") as delete_index,
    ):
        response = asyncio.run(api.delete_workspace("user"))

    assert response == {"deleted": True}
    delete_originals.assert_called_once_with(docs)
    delete_data.assert_called_once_with("user")
    delete_jobs.assert_called_once_with("user")
    delete_sessions.assert_called_once_with("user")
    delete_index.assert_called_once_with("user")


def test_rebuild_after_last_document_clears_clinical_projection():
    """Deleting the last source must wipe derived medications/labs/events,
    not just the snapshot cache — otherwise GET /clinical-entities still
    returns facts from a document that no longer exists."""
    with (
        mock.patch.object(api.db, "clear_conflict_history") as clear_conflicts,
        mock.patch.object(api.db, "delete_patient_snapshot") as delete_snap,
        mock.patch.object(api.db, "clear_clinical_projection") as clear_proj,
        mock.patch.object(api.vector_store, "delete_collection") as delete_index,
    ):
        result = asyncio.run(api._rebuild_after_document_deletion("user", []))

    assert result["documents_remaining"] == 0
    assert result["timeline"] is None
    clear_conflicts.assert_called_once_with("user")
    delete_snap.assert_called_once_with("user")
    clear_proj.assert_called_once_with("user")
    delete_index.assert_called_once_with("user")


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
