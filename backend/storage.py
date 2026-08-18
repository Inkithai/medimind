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
    
    if (not cloud_name or not api_key or not api_secret or
            cloud_name.strip() in ("", "your-cloudinary-cloud-name") or
            api_key.strip() in ("", "your-cloudinary-api-key") or
            api_secret.strip() in ("", "your-cloudinary-api-secret")):
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


def upload_patient_document(user_id: str, file_path: str, original_filename: str) -> Dict[str, str]:
    """Uploads one file to Cloudinary under mediscan/<user_id>/. Returns
    {"document_url": secure_url, "cloudinary_public_id": public_id}."""
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
    if "ok" in outcomes or (outcomes and all(value in {"not found", "not_found"} for value in outcomes)):
        return
    logger.error("storage: deletion failed for public id %s: outcomes=%s errors=%s", public_id, outcomes, errors)
    raise StorageDeletionError(
        "The original file could not be removed from secure storage. Nothing was deleted; please try again."
    )


def delete_workspace_documents(public_ids: Any) -> None:
    """Remove every distinct original owned by a workspace."""
    for public_id in sorted({str(value).strip() for value in public_ids if value and str(value).strip()}):
        delete_patient_document(public_id)


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
