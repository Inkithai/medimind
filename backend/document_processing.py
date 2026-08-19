"""Reusable raw document text/OCR processing lifecycle.

This module persists an inspection-friendly text layer separately from the
higher-level AI medical extraction. It deliberately performs no clinical
interpretation: the output is raw text, page count, method, confidence and
status so it can be reused or audited before structured extraction.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def process_raw_text(file_path: str) -> Dict[str, Any]:
    """Extract raw text/OCR metadata from a supported uploaded document.

    Returns a stable lifecycle object:
      {processing_status, extracted_text, page_count, extraction_method,
       has_text, confidence, processed_at, error_message}

    The function is best-effort and never calls an LLM. A FAILED result means
    the raw text layer could not be produced; the existing vision extraction
    path may still be able to read the document.
    """
    path = Path(file_path)
    try:
        from medical_extractor import (
            classify_pdf_pages,
            extract_text_from_pdf,
            pdf_pages_to_images,
            _ocr_image_file,
            _ocr_scan_pdf_pages,
            _pdf_page_texts,
        )

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            page_texts = _pdf_page_texts(str(path))
            page_count = len(page_texts)
            text_idx, image_idx = classify_pdf_pages(page_texts)
            parts = []
            confidences = []
            methods = []
            if text_idx:
                if image_idx:
                    text = "\n\n".join(
                        f"--- Page {i + 1} ---\n{page_texts[i]}" for i in text_idx
                    ).strip()
                else:
                    text = extract_text_from_pdf(str(path)).strip()
                if text:
                    parts.append(text)
                    methods.append("text_layer")
            if image_idx:
                ocr_text, ocr_conf, _ocr_pages = _ocr_scan_pdf_pages(str(path), image_idx, None)
                if ocr_text:
                    parts.append(ocr_text.strip())
                    methods.append("ocr_text_layer")
                    if isinstance(ocr_conf, (int, float)):
                        confidences.append(float(ocr_conf))
            extracted = "\n\n".join(p for p in parts if p).strip()
            method = "+".join(dict.fromkeys(methods)) or "none"
            return {
                "processing_status": "COMPLETED" if extracted else "FAILED",
                "extracted_text": extracted,
                "page_count": page_count,
                "extraction_method": method,
                "has_text": bool(extracted),
                "confidence": round(sum(confidences) / len(confidences), 2) if confidences else None,
                "processed_at": _now_iso(),
                "error_message": None if extracted else "No raw text layer could be extracted without AI vision.",
            }

        if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
            ocr_text, ocr_conf = _ocr_image_file(str(path))
            text = (ocr_text or "").strip()
            return {
                "processing_status": "COMPLETED" if text else "FAILED",
                "extracted_text": text,
                "page_count": 1,
                "extraction_method": "ocr_text_layer" if text else "none",
                "has_text": bool(text),
                "confidence": ocr_conf,
                "processed_at": _now_iso(),
                "error_message": None if text else "No OCR text could be extracted without AI vision.",
            }

        return {
            "processing_status": "FAILED",
            "extracted_text": "",
            "page_count": 0,
            "extraction_method": "unsupported",
            "has_text": False,
            "confidence": None,
            "processed_at": _now_iso(),
            "error_message": f"Unsupported file type: {suffix or '(none)'}",
        }
    except Exception as exc:
        return {
            "processing_status": "FAILED",
            "extracted_text": "",
            "page_count": 0,
            "extraction_method": "error",
            "has_text": False,
            "confidence": None,
            "processed_at": _now_iso(),
            "error_message": str(exc),
        }
