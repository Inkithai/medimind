"""
Language / Translation Guard
=========================================
Everything downstream of extraction is built on NORMALIZED English fields:
`ingredients` as INN generic names, numeric dosage_value/dosage_unit,
frequency_per_day. Cross-document duplicate detection, the interaction
knowledge base, dosage rules, and retrieval grouping all key on them.

When that normalization silently fails on one document, the damage is
invisible and lands exactly where it matters: the same drug under two
scripts produces two different keys, so a duplicate is never spotted and
the interaction check never sees both halves. Nothing errors, and the
record LOOKS complete.

This module turns that silent failure into an explicit outcome, in two
graduated layers (allow / warn / hold):

1. HARD REJECTION (assert_language_normalized): fires only on POSITIVE
   evidence that normalization failed — an `ingredients` entry still in
   non-Latin script (an INN is always Latin), or a medication whose name
   is non-Latin with no ingredient resolved at all. An unfamiliar language
   that normalized correctly always passes; a document with no language
   metadata at all passes (no evidence of failure). No extra model call —
   it re-reads the extraction that already ran.

2. GRADED RISK (assess_translation_risk / assess_documents_translation_risk):
   grades ocr_confidence and translation_confidence into a flag of
   "none" / "review" / "high". The two axes are MULTIPLIED into
   effective_confidence, because a perfect conversion of a misread word is
   still wrong — that catches documents where each axis clears its own
   threshold but the pair doesn't (0.65 x 0.75 = 0.49). The flag never
   blocks an upload; it's the graduated half. Documents that report no
   confidence fields at all stay silent — "we don't know" isn't evidence.

OCR confidence and translation confidence are independent risks with
different fixes:
    ocr_confidence low          -> upload a clearer scan
    translation_confidence low  -> have a pharmacist confirm generic names

Deterministic, no LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# effective_confidence (ocr * translation) below this => "high" risk flag
HIGH_RISK_BELOW = 0.55
# effective_confidence below this (but >= high) => "review" flag
REVIEW_RISK_BELOW = 0.75


class LanguageNormalizationError(ValueError):
    """Raised when a document's normalization into the English fields that
    cross-document matching depends on demonstrably failed."""

    def __init__(self, file_label: str, reason: str, affected_fields: List[str]):
        self.file_label = file_label
        self.reason = reason
        self.affected_fields = affected_fields
        super().__init__(
            f"'{file_label}' could not be processed reliably: {reason} "
            f"({len(affected_fields)} field(s) affected). Uploading a clearer scan "
            "or photo usually fixes this. If the document is correct as-is, ask "
            "your pharmacist or doctor for a copy that also lists the generic "
            "(non-brand) drug names."
        )


_LATIN_RE = re.compile(r"^[\x00-\x7F\u00C0-\u024F\u1E00-\u1EFF\s\d\W]+$")


def _is_latin(text: str) -> bool:
    """True if the string contains only Latin-script letters (with accents),
    digits, and punctuation. An INN generic name is always Latin."""
    return bool(_LATIN_RE.match(text))


def _has_letters(text: str) -> bool:
    return any(c.isalpha() for c in text)


def assert_language_normalized(doc: Dict[str, Any], file_label: str) -> None:
    """
    Raises LanguageNormalizationError when there is positive evidence that
    ingredient normalization failed:

      * an `ingredients` entry that is non-Latin script (INN names are
        always Latin — a non-Latin "ingredient" means the source text was
        copied through untranslated), or
      * a medication whose printed name is non-Latin AND whose ingredients
        list is empty (the normalization step produced nothing to match on).

    Never fires on an unfamiliar language whose fields normalized fine, and
    never on documents without language metadata — only demonstrated
    failure. Documents with no medications at all always pass.
    """
    affected: List[str] = []
    languages = set()
    if doc.get("document_language"):
        languages.add(str(doc["document_language"]))
    for lang in doc.get("additional_languages") or []:
        languages.add(str(lang))

    for med in doc.get("medications") or []:
        name = str(med.get("name") or "")
        ingredients = [str(i) for i in (med.get("ingredients") or []) if str(i).strip()]
        for ingredient in ingredients:
            if _has_letters(ingredient) and not _is_latin(ingredient):
                affected.append(f"ingredients ({ingredient!r})")
        if not ingredients and _has_letters(name) and not _is_latin(name):
            affected.append(f"medication name ({name!r}) with no resolved ingredient")

    if affected:
        lang_note = (
            f"This document is in {', '.join(sorted(languages))}, and some"
            if languages
            else "Some"
        )
        raise LanguageNormalizationError(
            file_label,
            f"{lang_note} details could not be converted into the standard "
            "English form your records are matched on",
            affected,
        )


def assess_translation_risk(doc: Dict[str, Any]) -> Dict[str, Any]:
    """
    Grades one document's independent OCR / translation confidence scores
    into a risk flag. Returns:
        {"flag": "none"|"review"|"high",
         "ocr_confidence": ..., "translation_confidence": ...,
         "effective_confidence": ...,  # product of the two
         "advice": ... or None}
    Stays silent (flag "none", no advice) when a document reports neither
    confidence field — absence of metadata is not evidence of risk.
    """
    ocr = doc.get("ocr_confidence")
    translation = doc.get("translation_confidence")
    if ocr is None and translation is None:
        return {
            "flag": "none",
            "ocr_confidence": None,
            "translation_confidence": None,
            "effective_confidence": None,
            "advice": None,
        }

    ocr_val = float(ocr) if isinstance(ocr, (int, float)) else 1.0
    translation_val = float(translation) if isinstance(translation, (int, float)) else 1.0
    effective = round(ocr_val * translation_val, 3)

    if effective < HIGH_RISK_BELOW:
        flag = "high"
    elif effective < REVIEW_RISK_BELOW:
        flag = "review"
    else:
        flag = "none"

    advice: Optional[str] = None
    if flag != "none":
        # The dominant (lower) axis determines the actionable advice.
        if ocr_val <= translation_val:
            advice = (
                "Parts of this document were hard to read. Uploading a clearer "
                "scan or photo usually fixes this."
            )
        else:
            advice = (
                "Some drug names or dosing phrases on this document had to be "
                "converted into standard English form and that conversion is "
                "uncertain. A pharmacist can confirm the generic names against "
                "the original document."
            )

    return {
        "flag": flag,
        "ocr_confidence": ocr_val if ocr is not None else None,
        "translation_confidence": translation_val if translation is not None else None,
        "effective_confidence": effective,
        "advice": advice,
    }


def assess_documents_translation_risk(docs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Rolls per-document risk up into one banner for the whole upload/record:
        {"flag": worst flag seen, "documents": [per-doc entries that flagged],
         "note": standing explanation or None}
    Only flagged documents are listed — a clean record returns
    {"flag": "none", "documents": [], "note": None}.
    """
    order = {"none": 0, "review": 1, "high": 2}
    worst = "none"
    flagged: List[Dict[str, Any]] = []
    for doc in docs:
        risk = assess_translation_risk(doc)
        if risk["flag"] != "none":
            source = (doc.get("_source") or {}).get("file") or doc.get("source_file")
            flagged.append({
                "source_file": source,
                "document_language": doc.get("document_language"),
                **risk,
            })
            if order[risk["flag"]] > order[worst]:
                worst = risk["flag"]
    return {
        "flag": worst,
        "documents": flagged,
        "note": (
            "Reading confidence and translation confidence are graded separately "
            "because they fail differently: low reading confidence means the scan "
            "was hard to read (fix: a clearer photo); low translation confidence "
            "means converting drug names or dosing phrases into standard English "
            "form was uncertain (fix: a pharmacist can confirm the generic names)."
            if flagged else None
        ),
    }
