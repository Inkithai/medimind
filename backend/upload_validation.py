"""
Upload content validation — magic-byte checks
=============================================
Extension strings lie; file headers don't. This module sniffs the
content's magic bytes so a renamed `.pdf` containing arbitrary data (or a
renamed image) is rejected before it ever costs an extraction call.

Returns are diagnostic strings (None = pass) rather than exceptions, so
the per-file upload loop can record one failed file and keep processing
the rest of the batch — one bad file must never discard a valid
prescription sitting next to it.
"""

from __future__ import annotations

from typing import Optional

_KIND_LABELS = {
    "pdf": "PDF",
    "png": "PNG",
    "jpeg": "JPEG",
    "webp": "WEBP",
}

_EXTENSION_TO_KIND = {
    ".pdf": "pdf",
    ".png": "png",
    ".jpg": "jpeg",
    ".jpeg": "jpeg",
    ".webp": "webp",
}


def detect_content_kind(content: bytes) -> Optional[str]:
    """The sniffed file kind ('pdf' | 'png' | 'jpeg' | 'webp'), or None when
    the content matches no supported magic."""
    if not content:
        return None
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return "webp"
    # PDF header may be preceded by a BOM or junk per the spec (the "%PDF"
    # header must appear within the first 1024 bytes), so search instead of
    # requiring byte 0 — real-world PDFs with a leading BOM are common.
    if b"%PDF" in content[:1024]:
        return "pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if content.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    return None


def validate_upload_content(content: bytes, filename: str) -> Optional[str]:
    """Returns a patient-facing failure message, or None when the file
    passes. Extension and content are checked together: a supported
    extension whose content doesn't match is a specific, actionable error.
    """
    if not content:
        return f"'{filename}' is empty — nothing to read."

    kind = detect_content_kind(content)
    if kind is None:
        return (
            f"'{filename}' does not contain a supported document type. "
            "Uploaded files must actually be PDF, JPEG, PNG, or WEBP files."
        )

    suffix = filename.lower()
    # Find the extension: last dot that is preceded by a non-empty stem.
    dot = suffix.rfind(".")
    extension = suffix[dot:] if dot > 0 else ""
    expected = _EXTENSION_TO_KIND.get(extension)
    if expected is None:
        return (
            f"'{filename}' uses an unsupported file extension "
            f"({extension or 'none'})."
        )
    if expected != kind:
        return (
            f"'{filename}' is labeled {extension.upper()}, but its content is "
            f"actually {_KIND_LABELS.get(kind, kind.upper())}. The file extension "
            "and its content must match."
        )
    return None
