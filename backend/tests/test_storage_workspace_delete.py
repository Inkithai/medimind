"""Workspace original deletion must cover private Supabase storage too."""

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

import storage  # noqa: E402


def test_delete_workspace_originals_dedupes_and_covers_both_backends():
    docs = [
        {
            "cloudinary_public_id": "mediscan/user/report",
            "storage_backend": "cloudinary",
        },
        {
            "cloudinary_public_id": "mediscan/user/report",
            "storage_backend": "cloudinary",
        },
        {
            "storage_backend": "supabase",
            "storage_path": "user/abc/lab.pdf",
            "storage_bucket": "medical-documents",
        },
        {
            "storage_backend": "supabase",
            "storage_path": "user/abc/lab.pdf",
            "storage_bucket": "medical-documents",
        },
        {"storage_backend": "cloudinary", "cloudinary_public_id": ""},
    ]
    with mock.patch.object(storage, "delete_uploaded_document") as delete_one:
        storage.delete_workspace_originals(docs)
    assert delete_one.call_count == 2
    deleted = [call.args[0] for call in delete_one.call_args_list]
    assert deleted[0]["cloudinary_public_id"] == "mediscan/user/report"
    assert deleted[1]["storage_path"] == "user/abc/lab.pdf"


if __name__ == "__main__":
    tests = [value for name, value in sorted(globals().items()) if name.startswith("test_")]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"\n{len(tests)} tests passed")
