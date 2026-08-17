"""
Offline Tesseract OCR text layer (optional pre-pass)
====================================================
Produces a free, offline text transcript (with per-page confidence) for
images and scanned PDF pages, as a PRE-PASS feeding the existing text
extraction path. The vision-LLM interpretation layer remains the
higher-level extractor; this layer exists so that:

  * a cleanly scanned document can be digitized for zero token cost and
    extracted with the (cheaper, faster) text model when the OCR is
    confident;
  * there is always an independent machine-readable transcript for
    indexing/evidence even when no vision model is available;
  * per-page OCR confidence is captured as metadata, so the pipeline can
    refuse the text path when the read is not trustworthy.

Availability is auto-detected. When Tesseract is not installed, every
public function reports unavailable/raises TesseractNotFoundError rather
than failing the pipeline — callers must always keep the vision path as
the fallback (see medical_extractor.process_document).

Env:
    MEDIMIND_OCR_MIN_CONFIDENCE  average word confidence (0-100) required
                                 to trust the OCR transcript (default 60)
    MEDIMIND_OCR_DPI             render DPI for PDF pages (default 200)
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

logger = logging.getLogger("ocr_service")


class OCRError(Exception):
    """Base class for OCR-layer errors."""


class TesseractNotFoundError(OCRError):
    """Tesseract (or the pytesseract binding) is not installed."""


class InvalidImageError(OCRError):
    """Bytes are not a readable image."""


class InvalidPDFError(OCRError):
    """Bytes/path is not a readable PDF."""


def _min_confidence() -> float:
    try:
        return max(0.0, min(100.0, float(os.environ.get("MEDIMIND_OCR_MIN_CONFIDENCE", "60"))))
    except ValueError:
        return 60.0


def _dpi() -> int:
    try:
        return max(72, min(600, int(os.environ.get("MEDIMIND_OCR_DPI", "200"))))
    except ValueError:
        return 200


def is_tesseract_available() -> bool:
    """True when the tesseract binary AND the pytesseract binding are usable.

    Never raises — availability is a deployment property, not an error."""
    if shutil.which("tesseract") is None:
        return False
    try:
        import pytesseract  # noqa: F401
        pytesseract.get_tesseract_version()
        return True
    except Exception as exc:
        logger.debug("ocr: pytesseract binding unusable: %s", exc)
        return False


@dataclass(frozen=True)
class OCRPageResult:
    """OCR output for one page."""

    page: int
    text: str
    # Average word confidence 0-100, or None when Tesseract reported none.
    confidence: Optional[float]


def _require_tesseract() -> Any:
    if not shutil.which("tesseract"):
        raise TesseractNotFoundError(
            "Tesseract OCR is not installed on this server (no 'tesseract' "
            "binary on PATH). Scanned documents continue to use vision "
            "extraction."
        )
    try:
        import pytesseract
        return pytesseract
    except ImportError as exc:
        raise TesseractNotFoundError(
            "The pytesseract binding is not installed on this server. "
            "Scanned documents continue to use vision extraction."
        ) from exc


def ocr_image(image: Image.Image, page: int = 1, dpi: int = 200) -> OCRPageResult:
    """OCR one in-memory PIL image. Raises TesseractNotFoundError when the
    engine is missing; returns a result with empty text when nothing is
    readable (blank scan, junk image)."""
    pytesseract = _require_tesseract()
    try:
        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT, config=f"--dpi {dpi}")
    except Exception as exc:
        # The engine exists but failed on this image — treat as unreadable
        # rather than crashing the caller's extraction path.
        logger.warning("ocr: page %d failed to OCR: %s", page, exc)
        return OCRPageResult(page=page, text="", confidence=None)

    words = data.get("text") or []
    confidences = data.get("conf") or []
    line_parts: List[str] = []
    last_block = last_par = last_line = -1
    for i, word in enumerate(words):
        word = str(word).strip()
        if not word:
            continue
        block, par, line = (
            int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]),
        )
        if (block, par, line) != (last_block, last_par, last_line):
            line_parts.append(word)
        else:
            line_parts[-1] += " " + word
        last_block, last_par, last_line = block, par, line

    numeric_conf = [
        float(c) for c in confidences
        if isinstance(c, (int, float)) or (isinstance(c, str) and c.strip().lstrip("-").isdigit())
    ]
    numeric_conf = [c for c in numeric_conf if c >= 0]
    mean_conf = round(sum(numeric_conf) / len(numeric_conf), 1) if numeric_conf else None
    return OCRPageResult(page=page, text="\n".join(line_parts), confidence=mean_conf)


def ocr_image_bytes(image_bytes: bytes, page: int = 1, dpi: Optional[int] = None) -> OCRPageResult:
    """OCR one image from raw bytes. Raises InvalidImageError for
    unreadable bytes, TesseractNotFoundError when the engine is missing."""
    _require_tesseract()  # fail fast with a clear error before PIL parsing
    try:
        img = Image.open(__import__("io").BytesIO(image_bytes))
        transposed = ImageOps.exif_transpose(img)
        return ocr_image(transposed if transposed is not None else img, page=page, dpi=dpi or _dpi())
    except UnidentifiedImageError as exc:
        raise InvalidImageError("OCR received bytes that are not a readable image.") from exc


def ocr_pdf_pages(pdf_path: str, page_indices: List[int], dpi: Optional[int] = None) -> List[OCRPageResult]:
    """OCR selected 0-indexed pages of a PDF by rendering them to images
    first. Raises InvalidPDFError for an unreadable PDF and
    TesseractNotFoundError when the engine is missing."""
    _require_tesseract()
    import fitz as pymupdf

    try:
        doc = pymupdf.open(pdf_path)
    except Exception as exc:
        raise InvalidPDFError(f"OCR cannot open the PDF: {exc}") from exc

    results: List[OCRPageResult] = []
    try:
        for index in page_indices:
            if index < 0 or index >= len(doc):
                continue
            page = doc[index]
            pix = page.get_pixmap(dpi=dpi or _dpi())
            img = Image.open(__import__("io").BytesIO(pix.tobytes("png")))
            results.append(ocr_image(img, page=index + 1, dpi=dpi or _dpi()))
    finally:
        doc.close()
    return results


def transcript_is_usable(results: List[OCRPageResult], min_chars: int = 80) -> Tuple[bool, str, Optional[float]]:
    """Decides whether a set of OCR pages is trustworthy enough to feed the
    text extraction path. Returns (usable, joined_text, avg_confidence).

    Unusable means the caller must keep its existing vision path — this
    layer never blocks an extraction, it only declines to replace it."""
    with_text = [r for r in results if r.text and r.text.strip()]
    if not with_text:
        return False, "", None
    joined = "\n\n".join(
        f"--- Page {r.page} ---\n{r.text.strip()}" for r in with_text
    )
    if len(joined.strip()) < min_chars:
        return False, joined, None
    confidences = [r.confidence for r in with_text if r.confidence is not None]
    avg = round(sum(confidences) / len(confidences), 1) if confidences else None
    if avg is not None and avg < _min_confidence():
        return False, joined, avg
    return True, joined, avg
