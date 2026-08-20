"""
Cloudinary storage (Phase 4)
=========================================
Uploads the original file a patient's document was extracted from (not the
per-page rendered images used for vision OCR) to Cloudinary, so the
extracted structured data can link back to the source document. One upload
per uploaded file, under a per-user folder:

    mediscan/<user_id>/<sanitized_filename>_<random8>

Env:
    CLOUDINARY_CLOUD_NAME
    CLOUDINARY_API_KEY
    CLOUDINARY_API_SECRET
"""

import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict

import cloudinary
import cloudinary.uploader

logger = logging.getLogger("storage")

_configured = False


def _configure() -> None:
    global _configured
    if _configured:
        return
    cloud_name = os.environ.get("CLOUDINARY_CLOUD_NAME")
    api_key = os.environ.get("CLOUDINARY_API_KEY")
    api_secret = os.environ.get("CLOUDINARY_API_SECRET")

    if (
        not cloud_name
        or not api_key
        or not api_secret
        or cloud_name.strip() in ("", "your-cloudinary-cloud-name")
        or api_key.strip() in ("", "your-cloudinary-api-key")
        or api_secret.strip() in ("", "your-cloudinary-api-secret")
    ):
        raise RuntimeError(
            "Cloudinary keys must be set and cannot be placeholders — "
            "copy .env.example to .env and add your actual Cloudinary "
            "configuration (cloud name, API key, and API secret)."
        )

    cloudinary.config(
        cloud_name=cloud_name,
        api_key=api_key,
        api_secret=api_secret,
        secure=True,
    )
    _configured = True


def _sanitize_public_id(filename: str) -> str:
    stem = re.sub(r"[^a-zA-Z0-9_-]+", "_", filename).strip("_") or "file"
    return f"{stem}_{uuid.uuid4().hex[:8]}"


def _storage_backend() -> str:
    return (
        os.environ.get(
            "MEDIMIND_DOCUMENT_STORAGE_BACKEND",
            os.environ.get("DOCUMENT_STORAGE_BACKEND", "cloudinary"),
        )
        .strip()
        .lower()
    )


def _supabase_storage_client():
    from supabase import create_client

    url = os.environ.get("SUPABASE_URL")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
    )
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and a server-side Supabase key are required for Supabase document storage."  # noqa: E501
        )
    return create_client(url, key)


def _supabase_bucket() -> str:
    return os.environ.get(
        "SUPABASE_DOCUMENT_BUCKET", os.environ.get("SUPABASE_STORAGE_BUCKET", "medical-documents")
    )


def _upload_to_supabase(user_id: str, file_path: str, original_filename: str) -> Dict[str, str]:
    client = _supabase_storage_client()
    bucket = _supabase_bucket()
    try:
        client.storage.get_bucket(bucket)
    except Exception:
        try:
            client.storage.create_bucket(bucket, options={"public": False})
        except Exception:
            # Bucket may already exist but be inaccessible to list/get; upload below
            # will produce the actionable provider error if it is truly unusable.
            pass
    suffix = Path(original_filename).suffix.lower() or Path(file_path).suffix.lower()
    safe_name = (
        _sanitize_public_id(Path(original_filename).stem or Path(original_filename).name) + suffix
    )
    storage_path = f"{user_id}/{uuid.uuid4().hex}/{safe_name}"
    content_type = "application/pdf" if suffix == ".pdf" else "application/octet-stream"
    if suffix in {".jpg", ".jpeg"}:
        content_type = "image/jpeg"
    elif suffix == ".png":
        content_type = "image/png"
    with open(file_path, "rb") as handle:
        data = handle.read()
    options = {"content-type": content_type, "upsert": "false"}
    storage_api = client.storage.from_(bucket)
    try:
        storage_api.upload(path=storage_path, file=data, file_options=options)
    except TypeError:
        storage_api.upload(storage_path, data, options)
    return {
        "document_url": "",
        "cloudinary_public_id": "",
        "storage_backend": "supabase",
        "storage_bucket": bucket,
        "storage_path": storage_path,
    }


def upload_patient_document(user_id: str, file_path: str, original_filename: str) -> Dict[str, str]:
    """Uploads one original document.

    Default is existing Cloudinary storage. Set MEDIMIND_DOCUMENT_STORAGE_BACKEND=supabase
    to store originals in a private Supabase bucket and access them through signed URLs.
    """
    if _storage_backend() == "supabase":
        return _upload_to_supabase(user_id, file_path, original_filename)
    _configure()
    result = cloudinary.uploader.upload(
        file_path,
        folder=f"mediscan/{user_id}",
        public_id=_sanitize_public_id(original_filename),
        resource_type="auto",  # PDFs and images both need to round-trip as the original file
        overwrite=False,
    )
    return {
        "document_url": result["secure_url"],
        "cloudinary_public_id": result["public_id"],
        "storage_backend": "cloudinary",
    }


class StorageDeletionError(RuntimeError):
    """A stored original could not be permanently removed."""


def delete_patient_document(public_id: str) -> None:
    """Permanently remove one original from Cloudinary.

    Older rows do not store Cloudinary's resource type, so try the supported
    upload categories. A fully missing asset is treated as already deleted.
    """
    if not public_id or not public_id.strip():
        return
    _configure()
    outcomes = []
    errors = []
    for resource_type in ("image", "raw", "video"):
        try:
            result = cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                invalidate=True,
            )
            outcomes.append(str((result or {}).get("result") or "").lower())
        except Exception as exc:
            errors.append(exc)
    if "ok" in outcomes or (
        outcomes and all(value in {"not found", "not_found"} for value in outcomes)
    ):
        return
    logger.error(
        "storage: deletion failed for public id %s: outcomes=%s errors=%s",
        public_id,
        outcomes,
        errors,
    )
    raise StorageDeletionError(
        "The original file could not be removed from secure storage. Nothing was deleted; please try again."  # noqa: E501
    )


def delete_workspace_documents(public_ids: Any) -> None:
    """Remove every distinct Cloudinary original owned by a workspace."""
    for public_id in sorted(
        {str(value).strip() for value in public_ids if value and str(value).strip()}
    ):
        delete_patient_document(public_id)


def delete_workspace_originals(documents: Any) -> None:
    """Remove every distinct original, Cloudinary or private Supabase storage.

    Workspace deletion used to pass only ``cloudinary_public_id`` values, so
    documents stored in a private Supabase bucket were left behind.
    """
    seen = set()
    for doc in documents or []:
        if not isinstance(doc, dict):
            continue
        if doc.get("storage_backend") == "supabase" and doc.get("storage_path"):
            key = ("supabase", str(doc.get("storage_path")))
        else:
            public_id = str(doc.get("cloudinary_public_id") or "").strip()
            if not public_id:
                continue
            key = ("cloudinary", public_id)
        if key in seen:
            continue
        seen.add(key)
        delete_uploaded_document(doc)


class StorageDownloadError(RuntimeError):
    """The stored original could not be fetched for reprocessing."""


def download_document_bytes(doc: Dict[str, Any], timeout: int = 60) -> bytes:
    """Fetches a stored document's original bytes from its saved
    `document_url` (Cloudinary secure URLs are public, so no signing is
    needed). Raises StorageDownloadError with a patient-safe message when
    the URL is missing or the fetch fails — never leaks provider details.
    """
    url = doc.get("document_url")
    if not url or not str(url).startswith("https://"):
        raise StorageDownloadError(
            "The original file for this document is not available for reprocessing."
        )
    import urllib.request

    try:
        with urllib.request.urlopen(str(url), timeout=timeout) as response:
            return response.read()
    except Exception as exc:
        logger.warning("storage: download failed for '%s': %s", url, exc)
        raise StorageDownloadError(
            "The original file could not be fetched right now. Please try again later."
        ) from exc


def create_signed_storage_url(doc: Dict[str, Any], expires_in_seconds: int = 900) -> str:
    """Create an expiring provider URL for private Supabase-stored originals."""
    if doc.get("storage_backend") != "supabase" or not doc.get("storage_path"):
        raise StorageDownloadError("This document is not stored in private Supabase storage.")
    client = _supabase_storage_client()
    bucket = str(doc.get("storage_bucket") or _supabase_bucket())
    api = client.storage.from_(bucket)
    ttl = max(60, min(int(expires_in_seconds), 3600))
    try:
        result = api.create_signed_url(path=str(doc["storage_path"]), expires_in=ttl)
    except TypeError:
        result = api.create_signed_url(str(doc["storage_path"]), ttl)
    signed = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
    if not signed:
        raise StorageDownloadError("Could not create a signed document URL.")
    return str(signed)


def download_private_storage_bytes(doc: Dict[str, Any]) -> bytes:
    if doc.get("storage_backend") != "supabase" or not doc.get("storage_path"):
        raise StorageDownloadError("This document is not stored in private Supabase storage.")
    try:
        client = _supabase_storage_client()
        bucket = str(doc.get("storage_bucket") or _supabase_bucket())
        data = client.storage.from_(bucket).download(str(doc["storage_path"]))
        if data is None:
            raise StorageDownloadError("The original file is not available in private storage.")
        return data
    except StorageDownloadError:
        raise
    except Exception as exc:
        logger.warning("storage: private download failed for %s: %s", doc.get("storage_path"), exc)
        raise StorageDownloadError(
            "The original file could not be fetched right now. Please try again later."
        ) from exc


def download_original_bytes(doc: Dict[str, Any], timeout: int = 60) -> bytes:
    """Fetch either a private Supabase original or the legacy Cloudinary original."""
    if doc.get("storage_backend") == "supabase":
        return download_private_storage_bytes(doc)
    return download_document_bytes(doc, timeout=timeout)


def delete_uploaded_document(doc: Dict[str, Any]) -> None:
    """Delete a stored original from its configured backend."""
    if doc.get("storage_backend") == "supabase" and doc.get("storage_path"):
        try:
            client = _supabase_storage_client()
            bucket = str(doc.get("storage_bucket") or _supabase_bucket())
            client.storage.from_(bucket).remove([str(doc["storage_path"])])
            return
        except Exception as exc:
            logger.error(
                "storage: private deletion failed for %s: %s", doc.get("storage_path"), exc
            )
            raise StorageDeletionError(
                "The original file could not be removed from secure storage. Nothing was deleted; please try again."  # noqa: E501
            ) from exc
    delete_patient_document(str(doc.get("cloudinary_public_id") or ""))
