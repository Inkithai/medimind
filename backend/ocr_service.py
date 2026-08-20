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
    MEDIMIND_TESSERACT_CMD       explicit path to the tesseract executable,
                                 for installs that are not on PATH
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

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


# Paths already reported as unusable, so a misconfiguration is logged once
# rather than on every page of every upload.
_WARNED_BAD_CMD: set = set()


def tesseract_cmd() -> Optional[str]:
    """Path to the tesseract executable, or None when it cannot be found.

    Resolution order:

      1. ``MEDIMIND_TESSERACT_CMD`` / ``TESSERACT_CMD`` — an explicit path.
         The Windows installer does not put tesseract on PATH (it lands in
         ``C:\\Program Files\\Tesseract-OCR\\tesseract.exe``), and some
         container images install it outside the default search path, so a
         PATH-only lookup silently disables OCR on a machine that has it.
      2. ``shutil.which`` — the normal Linux/macOS/Render case.

    An explicit path that does not exist is reported (once, as a warning)
    and treated as "not installed" rather than raising: OCR is an optional
    pre-pass, and a typo in a deployment variable must not break uploads.
    """
    configured = (
        (os.environ.get("MEDIMIND_TESSERACT_CMD") or os.environ.get("TESSERACT_CMD") or "")
        .strip()
        .strip('"')
    )
    if configured:
        # An absolute/relative path to the binary, or a bare name to look up.
        if os.path.isfile(configured) and os.access(configured, os.X_OK):
            return configured
        resolved = shutil.which(configured)
        if resolved:
            return resolved
        if configured not in _WARNED_BAD_CMD:
            _WARNED_BAD_CMD.add(configured)
            logger.warning(
                "ocr: MEDIMIND_TESSERACT_CMD=%r is not an executable tesseract binary; "
                "falling back to PATH lookup.",
                configured,
            )
    return shutil.which("tesseract")


def is_tesseract_available() -> bool:
    """True when the tesseract binary AND the pytesseract binding are usable.

    Never raises — availability is a deployment property, not an error."""
    command = tesseract_cmd()
    if command is None:
        return False
    try:
        import pytesseract  # noqa: F401

        pytesseract.pytesseract.tesseract_cmd = command
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
    command = tesseract_cmd()
    if not command:
        raise TesseractNotFoundError(
            "Tesseract OCR is not installed on this server (no 'tesseract' "
            "binary on PATH, and MEDIMIND_TESSERACT_CMD is unset or does not "
            "point at an executable). Scanned documents continue to use "
            "vision extraction."
        )
    try:
        import pytesseract

        # Point the binding at the resolved binary every time: the env var
        # may name a path that is not on PATH, and pytesseract defaults to a
        # bare "tesseract" lookup.
        pytesseract.pytesseract.tesseract_cmd = command
        return pytesseract
    except ImportError as exc:
        raise TesseractNotFoundError(
            "The pytesseract binding is not installed on this server. "
            "Scanned documents continue to use vision extraction."
        ) from exc


def ocr_image(image: Image.Image, page: int = 1, dpi: int = 200) -> OCRPageResult:
    """OCR one in-memory PIL image. Raises TesseractNotFoundError when the
    engine is missing; returns a result with empty text when nothing is
    readable (blank scan, junk image).

    Single-pass: ``image_to_data`` yields both the transcript and per-word
    confidence, so ``image_to_string`` is never called.
    """
    pytesseract = _require_tesseract()
    if image.mode not in ("RGB", "L"):
        try:
            image = image.convert("RGB")
        except Exception:
            pass
    try:
        data = pytesseract.image_to_data(
            image, output_type=pytesseract.Output.DICT, config=f"--dpi {dpi}"
        )
    except Exception as exc:
        # The engine exists but failed on this image — treat as unreadable
        # rather than crashing the caller's extraction path.
        logger.warning("ocr: page %d failed to OCR: %s", page, exc)
        return OCRPageResult(page=page, text="", confidence=None)

    words = data.get("text") or []
    confidences = data.get("conf") or []
    blocks = data.get("block_num") or []
    pars = data.get("par_num") or []
    lines = data.get("line_num") or []

    def _safe_int(values: List[Any], index: int) -> int:
        try:
            return int(values[index])
        except (IndexError, TypeError, ValueError):
            return -1

    def _safe_conf(index: int) -> float:
        try:
            return float(confidences[index])
        except (IndexError, TypeError, ValueError):
            return -1.0

    line_parts: List[str] = []
    last_block = last_par = last_line = -1
    numeric_conf: List[float] = []
    for i, word in enumerate(words):
        word = str(word).strip() if word is not None else ""
        if not word:
            continue
        # Only words with real text contribute to confidence — empty Tesseract
        # rows often carry a dummy high score that inflated the page average.
        conf = _safe_conf(i)
        if conf >= 0:
            numeric_conf.append(conf)
        block, par, line = _safe_int(blocks, i), _safe_int(pars, i), _safe_int(lines, i)
        if (block, par, line) != (last_block, last_par, last_line):
            line_parts.append(word)
        else:
            line_parts[-1] += " " + word
        last_block, last_par, last_line = block, par, line

    mean_conf = round(sum(numeric_conf) / len(numeric_conf), 1) if numeric_conf else None
    return OCRPageResult(page=page, text="\n".join(line_parts), confidence=mean_conf)


def ocr_image_bytes(image_bytes: bytes, page: int = 1, dpi: Optional[int] = None) -> OCRPageResult:
    """OCR one image from raw bytes. Raises InvalidImageError for
    unreadable bytes, TesseractNotFoundError when the engine is missing."""
    _require_tesseract()  # fail fast with a clear error before PIL parsing
    try:
        img = Image.open(__import__("io").BytesIO(image_bytes))
        img.load()
        transposed = ImageOps.exif_transpose(img)
        return ocr_image(
            transposed if transposed is not None else img, page=page, dpi=dpi or _dpi()
        )
    except UnidentifiedImageError as exc:
        raise InvalidImageError("OCR received bytes that are not a readable image.") from exc


def ocr_pdf_pages(
    pdf_path: str, page_indices: List[int], dpi: Optional[int] = None
) -> List[OCRPageResult]:
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


def transcript_is_usable(
    results: List[OCRPageResult], min_chars: int = 80
) -> Tuple[bool, str, Optional[float]]:
    """Decides whether a set of OCR pages is trustworthy enough to feed the
    text extraction path. Returns (usable, joined_text, avg_confidence).

    Unusable means the caller must keep its existing vision path — this
    layer never blocks an extraction, it only declines to replace it."""
    with_text = [r for r in results if r.text and r.text.strip()]
    if not with_text:
        return False, "", None
    joined = "\n\n".join(f"--- Page {r.page} ---\n{r.text.strip()}" for r in with_text)
    if len(joined.strip()) < min_chars:
        return False, joined, None
    confidences = [r.confidence for r in with_text if r.confidence is not None]
    avg = round(sum(confidences) / len(confidences), 1) if confidences else None
    if avg is not None and avg < _min_confidence():
        return False, joined, avg
    return True, joined, avg
