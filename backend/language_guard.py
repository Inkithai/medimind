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

1. DEGRADED ACCEPTANCE (apply_language_degradation), used by the upload
   pipeline: the same positive evidence that assert_language_normalized
   refuses on instead marks the affected medications
   `cross_check_eligible: False`, caps the document's confidence, and
   reports what will not take part in cross-checking. The usable half of a
   partially-translated prescription is kept rather than discarded.

2. HARD REJECTION (assert_language_normalized): fires only on POSITIVE
   evidence that normalization failed — an `ingredients` entry still in
   non-Latin script (an INN is always Latin), or a medication whose name
   is non-Latin with no ingredient resolved at all. An unfamiliar language
   that normalized correctly always passes; a document with no language
   metadata at all passes (no evidence of failure). No extra model call —
   it re-reads the extraction that already ran.

3. GRADED RISK (assess_translation_risk / assess_documents_translation_risk):
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


def _document_languages(doc: Dict[str, Any]) -> set:
    """Every language the extraction reported for this document."""
    languages = set()
    if doc.get("document_language"):
        languages.add(str(doc["document_language"]))
    for lang in doc.get("additional_languages") or []:
        languages.add(str(lang))
    return languages


def detect_normalization_failures(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Every medication on this document whose drug name demonstrably did
    NOT normalize into the English form cross-document matching needs.

    Two failure shapes, both positive evidence rather than suspicion:

      * an `ingredients` entry still in non-Latin script — an INN generic
        name is always Latin, so a non-Latin "ingredient" means the source
        text was copied through untranslated;
      * a medication whose printed name is non-Latin and whose ingredients
        list is empty — normalization produced nothing to match on.

    Returned entries carry the medication dict itself, so callers can both
    report the problem and mark the affected medication. This is the single
    source of truth for both assert_language_normalized() (which refuses)
    and apply_language_degradation() (which accepts and marks); keeping one
    detector means the two can never disagree about what failed.
    """
    failures: List[Dict[str, Any]] = []
    for med in doc.get("medications") or []:
        if not isinstance(med, dict):
            continue
        name = str(med.get("name") or "")
        ingredients = [str(i) for i in (med.get("ingredients") or []) if str(i).strip()]
        for ingredient in ingredients:
            if _has_letters(ingredient) and not _is_latin(ingredient):
                failures.append(
                    {
                        "medication": med,
                        "name": name,
                        "description": f"ingredients ({ingredient!r})",
                    }
                )
        if not ingredients and _has_letters(name) and not _is_latin(name):
            failures.append(
                {
                    "medication": med,
                    "name": name,
                    "description": f"medication name ({name!r}) with no resolved ingredient",
                }
            )
    return failures


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
    affected = [problem["description"] for problem in detect_normalization_failures(doc)]
    languages = _document_languages(doc)

    if affected:
        lang_note = (
            f"This document is in {', '.join(sorted(languages))}, and some" if languages else "Some"
        )
        raise LanguageNormalizationError(
            file_label,
            f"{lang_note} details could not be converted into the standard "
            "English form your records are matched on",
            affected,
        )


# A document whose drug names could not all be normalized is ACCEPTED at a
# confidence that says so, rather than refused. These ceilings sit below
# REVIEW_RISK_BELOW so the document is visibly flagged everywhere confidence
# is displayed, and above document_filter.LOW_CONFIDENCE_THRESHOLD (0.35) so
# degrading a document can never make a later stage throw it out as
# non-medical — a document must not disappear as a side effect of being
# marked uncertain.
UNTRANSLATED_DOC_CONFIDENCE = 0.4
UNTRANSLATED_MED_CONFIDENCE = 0.3


def _lowered(current: Any, ceiling: float) -> float:
    """Confidence capped at `ceiling`, never raised. A missing or
    non-numeric score is treated as the ceiling rather than as 0.0: the
    document was read, only its drug names failed to convert."""
    if isinstance(current, bool) or not isinstance(current, (int, float)):
        return ceiling
    return min(float(current), ceiling)


def apply_language_degradation(doc: Dict[str, Any], file_label: str = "") -> Dict[str, Any]:
    """
    Accept a partially-translated document, marking what could not be
    matched and lowering its confidence to match. Mutates `doc` in place and
    returns a summary of what was degraded (``{"degraded": False, ...}``
    when nothing failed).

    WHY ACCEPT RATHER THAN REJECT
    -----------------------------
    Refusing the whole file was the previous behaviour and it was too blunt.
    A Sinhala prescription listing Metformin (which resolved cleanly to its
    INN) beside one Sinhala-script name the model could not map was thrown
    away in full, taking the medication that WAS usable with it. For a
    photographed non-English prescription, partial translation is the normal
    outcome rather than an exceptional one, so rejecting made the common
    case the failing case — and the user was left with no record at all,
    which is strictly worse than a record with a marked gap in it.

    The original concern still stands: an unmatched drug name cannot be
    keyed against the rest of the record, so it silently drops out of
    duplicate and interaction checking. That is why this is a degradation
    and not a shrug. Every affected medication is marked
    ``cross_check_eligible: False`` with the reason attached, so the gap is
    visible in the record instead of being implied by absence, and the
    document's confidence states plainly that part of it could not be read
    into the standard form.

    Deterministic; no model call — it re-reads the extraction that already
    ran, exactly like assert_language_normalized().
    """
    failures = detect_normalization_failures(doc)
    if not failures:
        return {"degraded": False, "problems": [], "unmatched_medications": []}

    unmatched: List[str] = []
    seen_medications: List[int] = []
    for failure in failures:
        med = failure["medication"]
        # One medication can fail on several ingredients; mark it once.
        if id(med) in seen_medications:
            continue
        seen_medications.append(id(med))
        med["cross_check_eligible"] = False
        med["unmatched_reason"] = (
            "This drug name could not be converted to its standard English name, "
            "so it cannot be compared against your other records."
        )
        med["confidence"] = _lowered(med.get("confidence"), UNTRANSLATED_MED_CONFIDENCE)
        unmatched.append(failure["name"] or "unnamed medication")

    doc["overall_confidence"] = _lowered(doc.get("overall_confidence"), UNTRANSLATED_DOC_CONFIDENCE)
    doc["translation_incomplete"] = True
    doc["translation_problems"] = [failure["description"] for failure in failures]

    languages = sorted(_document_languages(doc))
    return {
        "degraded": True,
        "file": file_label,
        "problems": doc["translation_problems"],
        "unmatched_medications": unmatched,
        "languages": languages,
        "confidence": doc["overall_confidence"],
        "message": (
            f"{len(unmatched)} medicine name(s) on this document could not be converted "
            "to their standard English names. They are saved with your records, but they "
            "cannot be compared against your other medicines for duplicates or "
            "interactions. The rest of the document was read normally."
        ),
        "advice": (
            "Ask your pharmacist or doctor for a copy that also lists the generic "
            "(non-brand) drug names, then upload that."
        ),
    }


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

    A document that apply_language_degradation() marked
    `translation_incomplete` is always "high", whatever the model reported.
    These two signals disagree in a very specific and dangerous way: the
    model can be perfectly confident about a translation it never performed,
    so a document with one drug name left in its source script routinely
    self-reports translation_confidence ~0.9. Demonstrated failure has to
    outrank a self-assessment, or the record-wide banner would quietly say
    "no translation risk" about a document whose medicines cannot be
    safety-checked at all.
    """
    ocr = doc.get("ocr_confidence")
    translation = doc.get("translation_confidence")
    incomplete = bool(doc.get("translation_incomplete"))
    if ocr is None and translation is None and not incomplete:
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

    if incomplete or effective < HIGH_RISK_BELOW:
        flag = "high"
    elif effective < REVIEW_RISK_BELOW:
        flag = "review"
    else:
        flag = "none"

    advice: Optional[str] = None
    if incomplete:
        advice = (
            "Some drug names on this document could not be converted into their "
            "standard English names, so those medicines are not compared against "
            "your other records. Ask your pharmacist or doctor for a copy that "
            "also lists the generic (non-brand) drug names."
        )
    elif flag != "none":
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
            flagged.append(
                {
                    "source_file": source,
                    "document_language": doc.get("document_language"),
                    "translation_incomplete": bool(doc.get("translation_incomplete")),
                    **risk,
                }
            )
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
            if flagged
            else None
        ),
    }
