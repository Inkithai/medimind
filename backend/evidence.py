"""Page-level evidence normalization and deterministic PDF text location.

Extraction models identify a short verbatim quote and (for vision input) a
normalized bounding box.  Digital PDFs get a stronger guarantee: PyMuPDF
searches the original page text for that quote/value and replaces the model's
box with the exact text coordinates.

Bounding boxes use ``[left, top, right, bottom]`` normalized to 0..1 so the
frontend can draw the same overlay at any rendered size.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

try:
    import pymupdf
except ImportError:  # pragma: no cover - older PyMuPDF
    import fitz as pymupdf

from clinical_events import CLINICAL_EVENT_SEARCH_FIELDS


FIELD_EVIDENCE_KEYS = (
    "date",
    "provider_or_doctor",
    "patient_name",
    "allergies_noted",
    "clinical_notes",
)


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item) for item in value if item is not None)
    return str(value).strip()


def _normalize_bbox(value: Any) -> Optional[List[float]]:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        box = [float(item) for item in value]
    except (TypeError, ValueError):
        return None
    # Vision models are more reliable with an integer 0..1000 coordinate
    # frame. Accept that and convert to the public normalized contract. Tiny
    # floating-point overshoots around 1 are clamped as already-normalized
    # geometry rather than accidentally divided by 1000.
    magnitude = max(abs(item) for item in box)
    if magnitude > 1.5:
        box = [item / 1000.0 for item in box]
    left, top, right, bottom = [max(0.0, min(1.0, item)) for item in box]
    if right <= left or bottom <= top:
        return None
    return [round(left, 6), round(top, 6), round(right, 6), round(bottom, 6)]


def _evidence_id(path: str, page: int, quote: str, index: int) -> str:
    raw = f"{path}|{page}|{quote}|{index}"
    return "ev_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def _normalize_regions(
    raw_regions: Any,
    *,
    path: str,
    fallback_quote: str,
    default_page: int,
    vision: bool,
) -> List[Dict[str, Any]]:
    values = raw_regions if isinstance(raw_regions, list) else []
    if not values and fallback_quote:
        # Legacy records still get a truthful page link, but their extracted
        # value is not presented as a verbatim quotation. A digital PDF can
        # later promote this to exact text only when deterministic search
        # actually finds it.
        values = [{"page": default_page, "quote": "", "bbox": None, "confidence": 0.5}]
    normalized: List[Dict[str, Any]] = []
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            continue
        try:
            page = max(1, int(raw.get("page") or default_page))
        except (TypeError, ValueError):
            page = default_page
        # A vision call sees exactly one rendered page. Its local page 1 must
        # be remapped to the source PDF page supplied by the caller.
        if vision:
            page = default_page
        quote = _text(raw.get("quote"))
        bbox = _normalize_bbox(raw.get("bbox"))
        confidence = raw.get("confidence")
        try:
            confidence = max(0.0, min(1.0, float(confidence)))
        except (TypeError, ValueError):
            confidence = 0.6 if bbox else 0.5
        existing_id = _text(raw.get("evidence_id"))
        existing_locator = _text(raw.get("locator"))
        region = {
            # Preserve IDs generated during the original extraction. This is
            # essential for old Q&A links to survive a database reload.
            "evidence_id": existing_id if existing_id.startswith("ev_") else _evidence_id(path, page, quote, index),
            "field_path": path,
            "page": page,
            "quote": quote,
            "bbox": bbox,
            "confidence": round(confidence, 4),
            "locator": existing_locator or (
                "vision_model" if bbox and vision else "model_quote" if quote else "page_only"
            ),
        }
        # Correction/conflict annotations are server-owned provenance. Keep
        # them when dynamically normalizing persisted records.
        for key in (
            "verification_status",
            "conflict_id",
            "original_extracted_value",
            "corrected_value",
        ):
            if key in raw:
                region[key] = raw[key]
        normalized.append(region)
    return normalized


def normalize_document_evidence(
    document: Dict[str, Any],
    *,
    default_page: int = 1,
    vision: bool = False,
) -> Dict[str, Any]:
    """Normalize model output and guarantee an evidence container per fact."""
    field_evidence = document.get("field_evidence")
    if not isinstance(field_evidence, dict):
        field_evidence = {}
    for key in FIELD_EVIDENCE_KEYS:
        fallback = _text(document.get(key))
        field_evidence[key] = _normalize_regions(
            field_evidence.get(key),
            path=f"/{key}",
            fallback_quote=fallback,
            default_page=default_page,
            vision=vision,
        )
    document["field_evidence"] = field_evidence

    # Legacy documents predate some structured collections. Normalize them to
    # empty arrays so every API consumer receives a stable shape.
    for collection in ("medications", "lab_results", *CLINICAL_EVENT_SEARCH_FIELDS):
        if not isinstance(document.get(collection), list):
            document[collection] = []

    for index, medication in enumerate(document.get("medications") or []):
        if not isinstance(medication, dict):
            continue
        fallback = " ".join(
            part for part in (
                _text(medication.get("name")),
                _text(medication.get("dosage")),
                _text(medication.get("frequency")),
            ) if part
        )
        medication["evidence"] = _normalize_regions(
            medication.get("evidence"),
            path=f"/medications/{index}",
            fallback_quote=fallback,
            default_page=default_page,
            vision=vision,
        )

    for index, lab in enumerate(document.get("lab_results") or []):
        if not isinstance(lab, dict):
            continue
        fallback = " ".join(
            part for part in (
                _text(lab.get("test_name")),
                _text(lab.get("value")),
                _text(lab.get("unit")),
            ) if part
        )
        lab["evidence"] = _normalize_regions(
            lab.get("evidence"),
            path=f"/lab_results/{index}",
            fallback_quote=fallback,
            default_page=default_page,
            vision=vision,
        )

    for collection, search_fields in CLINICAL_EVENT_SEARCH_FIELDS.items():
        for index, fact in enumerate(document.get(collection) or []):
            if not isinstance(fact, dict):
                continue
            fallback = " ".join(
                value for value in (_text(fact.get(field)) for field in search_fields) if value
            )
            fact["evidence"] = _normalize_regions(
                fact.get("evidence"),
                path=f"/{collection}/{index}",
                fallback_quote=fallback,
                default_page=default_page,
                vision=vision,
            )
    return document


def iter_document_evidence(document: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], List[str]]]:
    """Yield each mutable evidence region plus progressively looser searches."""
    fields = document.get("field_evidence") or {}
    for key in FIELD_EVIDENCE_KEYS:
        fallback = _text(document.get(key))
        for region in fields.get(key) or []:
            if isinstance(region, dict):
                yield region, [region.get("quote") or "", fallback]

    for medication in document.get("medications") or []:
        if not isinstance(medication, dict):
            continue
        fallbacks = [
            _text(medication.get("name")),
            _text(medication.get("dosage")),
            _text(medication.get("frequency")),
        ]
        for region in medication.get("evidence") or []:
            if isinstance(region, dict):
                yield region, [region.get("quote") or "", *fallbacks]

    for lab in document.get("lab_results") or []:
        if not isinstance(lab, dict):
            continue
        fallbacks = [
            _text(lab.get("test_name")),
            _text(lab.get("value")),
            _text(lab.get("unit")),
        ]
        for region in lab.get("evidence") or []:
            if isinstance(region, dict):
                yield region, [region.get("quote") or "", *fallbacks]

    for collection, search_fields in CLINICAL_EVENT_SEARCH_FIELDS.items():
        for fact in document.get(collection) or []:
            if not isinstance(fact, dict):
                continue
            fallbacks = [_text(fact.get(field)) for field in search_fields]
            for region in fact.get("evidence") or []:
                if isinstance(region, dict):
                    yield region, [region.get("quote") or "", *fallbacks]


def _search_variants(value: str) -> Iterable[str]:
    value = re.sub(r"\s+", " ", value or "").strip()
    if not value:
        return []
    variants = [value]
    words = value.split()
    # Exact table rows often gain/loss whitespace in PDF extraction. Search a
    # distinctive shorter phrase if the full quote is not contiguous.
    if len(words) > 6:
        variants.append(" ".join(words[:6]))
    if len(words) > 3:
        variants.append(" ".join(words[:3]))
    variants.extend(word for word in words if len(word) >= 5)
    seen = set()
    unique = []
    for item in variants:
        key = item.casefold()
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def locate_pdf_text_evidence(pdf_path: str, document: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve evidence quotes/values to exact normalized PyMuPDF rectangles."""
    pdf = pymupdf.open(pdf_path)
    try:
        page_count = len(pdf)
        for region, candidates in iter_document_evidence(document):
            requested_page = max(1, min(page_count, int(region.get("page") or 1)))
            page_order = [requested_page] + [page for page in range(1, page_count + 1) if page != requested_page]
            found = None
            matched_quote = ""
            matched_page = requested_page
            exact_match = False
            for page_number in page_order:
                page = pdf.load_page(page_number - 1)
                for candidate in candidates:
                    normalized_candidate = re.sub(r"\s+", " ", _text(candidate)).strip()
                    for variant in _search_variants(normalized_candidate):
                        rectangles = page.search_for(variant)
                        if rectangles:
                            found = rectangles[0]
                            matched_quote = variant
                            matched_page = page_number
                            exact_match = variant.casefold() == normalized_candidate.casefold()
                            break
                    if found is not None:
                        break
                if found is not None:
                    break
            if found is None:
                region["bbox"] = None
                region["locator"] = "page_quote" if region.get("quote") else "page_only"
                continue
            page = pdf.load_page(matched_page - 1)
            # Search coordinates are unrotated. Cloudinary/browser previews
            # render the page rotation, so transform before normalizing.
            display_rect = found * page.rotation_matrix
            page_rect = page.rect
            width, height = float(page_rect.width), float(page_rect.height)
            region["page"] = matched_page
            region["bbox"] = _normalize_bbox([
                (display_rect.x0 - page_rect.x0) / width,
                (display_rect.y0 - page_rect.y0) / height,
                (display_rect.x1 - page_rect.x0) / width,
                (display_rect.y1 - page_rect.y0) / height,
            ])
            # The displayed quotation must be exactly the text covered by the
            # rectangle, especially when a shorter whitespace-tolerant search
            # was needed for a table row.
            region["quote"] = matched_quote
            region["locator"] = "pdf_text_search"
            region["confidence"] = 1.0 if exact_match else 0.85
    finally:
        pdf.close()
    return document


def first_evidence(fact: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    values = fact.get("evidence")
    if isinstance(values, list):
        return next((item for item in values if isinstance(item, dict)), None)
    return None
