"""
AI analysis log grouping (one entry per uploaded document)
==========================================================
The analysis log (`GET /api/v1/analyses`) is an audit/display surface that
reconstructs "what the AI did to my records" from the durable document
rows. Those rows are stored per EXTRACTED PAGE: a three-page scanned PDF
is persisted as three rows, each with its own `_document_id`, and a page
that is re-extracted (reprocess, correction replay) can add further rows
for the same physical file.

Rendered one row per card, that reads as three or four separate
"Document extraction" analyses of the same file — the log claims work
that never happened and the counts underneath it (medications, labs,
findings) look duplicated. On a medical record, a display that implies
the same prescription was extracted three times is the same class of
error as a duplicate-prescription false alarm: it makes a storage detail
look like a clinical fact.

This module collapses page rows back into the physical upload they came
from, so the log shows exactly one extraction entry per document:

  * pages are grouped by upload identity — content hash first, then the
    storage identifiers, then the source filename, and finally the
    document id (the same precedence db.delete_document_group uses, so a
    group here is always deletable/reprocessable as a unit);
  * counts are summed across the group's pages;
  * the document type is pinned to the closed vocabulary and the group's
    dominant type is reported, never a raw/legacy free-form value and
    never null;
  * confidence is the LOWEST page confidence in the group, not the mean —
    a document is only as trustworthy as its least legible page, and
    averaging would hide a page the model could barely read;
  * nothing is dropped: every page's document id stays on the entry, and
    a row that cannot be associated with any group still yields its own
    entry rather than disappearing from the audit trail.

Pure functions only — no network, no Supabase — so the grouping rules are
directly testable (see tests/test_analysis_log.py).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from document_types import normalize_document_type, summarize_document_types
from record_trust import document_id as trust_document_id

# Upload identity fields, most trustworthy first. content_sha256 is shared
# by every page of one physical file; the storage ids are shared by uploads
# that predate the hash; the filename is the last resort for legacy rows.
_GROUP_FIELDS = ("content_sha256", "cloudinary_public_id", "storage_path")


def _source_block(doc: Dict[str, Any]) -> Dict[str, Any]:
    source = doc.get("_source")
    return source if isinstance(source, dict) else {}


def upload_group_key(doc: Dict[str, Any]) -> str:
    """Identity of the physical upload one extracted page row belongs to.

    Returns a namespaced key so two documents cannot collide across
    different identity kinds (a filename that happens to equal a hash).
    """
    data = doc or {}
    for field in _GROUP_FIELDS:
        value = str(data.get(field) or "").strip()
        if value:
            return f"{field}:{value}"
    source_file = str(_source_block(data).get("file") or "").strip()
    if source_file:
        return f"file:{source_file}"
    # No shared identity at all: the row is its own group, so it is still
    # reported instead of being folded into an unrelated document.
    return f"document:{trust_document_id(data)}"


def _page_number(doc: Dict[str, Any]) -> int:
    try:
        return int(_source_block(doc).get("page") or 1)
    except (TypeError, ValueError):
        return 1


def _count_entities(doc: Dict[str, Any]) -> Dict[str, int]:
    return {
        "medications": len(doc.get("medications") or []),
        "lab_results": len(doc.get("lab_results") or []),
        "allergies": len(doc.get("allergies_noted") or []),
        "findings": len(doc.get("diagnoses") or []) + len(doc.get("symptoms") or []),
        "events": len(doc.get("procedures") or [])
        + len(doc.get("vital_signs") or [])
        + len(doc.get("imaging_results") or []),
    }


def _group_confidence(pages: Sequence[Dict[str, Any]]) -> Optional[float]:
    """Lowest page confidence in the group (the weakest link), or None."""
    values = [
        float(page.get("overall_confidence"))
        for page in pages
        if isinstance(page.get("overall_confidence"), (int, float))
        and not isinstance(page.get("overall_confidence"), bool)
    ]
    return min(values) if values else None


def _group_summary(
    pages: Sequence[Dict[str, Any]], counts: Dict[str, int], source_file: str
) -> str:
    """Human summary of the extraction: the document's own clinical notes
    when it has them, otherwise a plain statement of what was extracted.

    Never returns an empty string — an analysis card with no summary reads
    as a failed extraction even when the extraction succeeded.
    """
    notes: List[str] = []
    for page in pages:
        note = str(page.get("clinical_notes") or "").strip()
        if note and note not in notes:
            notes.append(note)
    if notes:
        return " ".join(notes)
    pages_suffix = f" across {len(pages)} pages" if len(pages) > 1 else ""
    return (
        f"Extracted {counts['medications']} medication(s), {counts['lab_results']} lab result(s), "
        f"and {counts['findings']} clinical finding(s) from {source_file}{pages_suffix}."
    )


def _summarize_group(pages: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    ordered = sorted(pages, key=lambda page: (_page_number(page), trust_document_id(page)))
    primary = ordered[0]
    source_file = str(_source_block(primary).get("file") or "").strip() or "uploaded document"

    counts: Dict[str, int] = {
        "medications": 0,
        "lab_results": 0,
        "allergies": 0,
        "findings": 0,
        "events": 0,
    }
    for page in ordered:
        for key, value in _count_entities(page).items():
            counts[key] += value

    # summarize_document_types() normalizes legacy/free-form values onto the
    # closed vocabulary, so the card can never show null or a model phrase.
    document_type = summarize_document_types(list(ordered))["dominant"]
    confidence = _group_confidence(ordered)
    summary = _group_summary(ordered, counts, source_file)
    document_ids = [trust_document_id(page) for page in ordered if trust_document_id(page)]
    primary_id = document_ids[0] if document_ids else ""
    created_at = max(
        (str(page.get("uploaded_at") or page.get("date") or "") for page in ordered),
        default="",
    )
    raw_text_processing = next(
        (page.get("raw_text_processing") for page in ordered if page.get("raw_text_processing")),
        None,
    )

    return {
        "id": f"document_extraction:{primary_id or upload_group_key(primary)}",
        "analysis_type": "document_extraction",
        "result": {
            "summary": summary,
            "document_type_detected": document_type,
            "confidence_score": confidence,
            "persisted_counts": counts,
            "source_file": source_file,
            "document_id": primary_id,
            "document_ids": document_ids,
            "page_count": len(ordered),
            "raw_text_processing": raw_text_processing,
        },
        "confidence": confidence,
        "summary": summary,
        "created_at": created_at,
    }


def build_extraction_analyses(docs: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One `document_extraction` log entry per physical uploaded document.

    Page rows of the same file are merged; ordering follows first
    appearance of each group in `docs` (callers sort by created_at).
    """
    groups: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for doc in docs or []:
        if not isinstance(doc, dict):
            continue
        key = upload_group_key(doc)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(doc)
    return [_summarize_group(groups[key]) for key in order]


__all__ = [
    "build_extraction_analyses",
    "normalize_document_type",
    "upload_group_key",
]
