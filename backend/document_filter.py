"""
Non-Medical Document Filter
=========================================
Guards against files that pass the extension check in medical_extractor.py
(.pdf/.png/.jpg/.jpeg/.webp) but aren't actually medical documents — a
boarding pass, a receipt, a screenshot, a random photo. Nothing upstream
rejects them: process_document() will happily run OCR/vision extraction on
any image or PDF and hand back a structurally-valid (if empty/junk) result,
because the extraction JSON schema's document_type enum includes "other" as
a catch-all rather than failing.

Efficiency: this filter does NOT make a second model call. It re-uses the
document_type / medications / lab_results / allergies_noted / clinical_notes
fields already produced by process_document()'s single extraction call, and
applies cheap, local, deterministic checks on that structure. So the cost of
filtering is O(1) dict lookups — no extra OCR, no extra OpenAI request, no
added latency — and it runs *before* the expensive downstream work (timeline
rebuild, cross-check LLM call, Chroma re-indexing), so a rejected file never
pays for any of that either.
"""

from typing import Any, Dict, List, Tuple

from clinical_events import CLINICAL_EVENT_COLLECTIONS

# document_type values the extraction schema recognizes as genuinely
# clinical. "other" is the extractor's catch-all for anything that isn't
# one of these — which is exactly what a boarding pass / receipt / random
# photo will come back as.
RECOGNIZED_MEDICAL_TYPES = frozenset(
    {
        "prescription",
        "lab_report",
        "discharge_summary",
        "imaging_report",
        "consultation_note",
        "procedure_report",
    }
)

# Below this, an "other"-typed extraction with no clinical content is
# treated as noise rather than a low-confidence-but-real medical document.
LOW_CONFIDENCE_THRESHOLD = 0.35


class NonMedicalDocumentError(ValueError):
    """Raised when an uploaded file's extraction result doesn't look like
    a medical document. Carries the filename so callers can build a clear,
    per-file error message without re-deriving context."""

    def __init__(self, filename: str, reason: str):
        self.filename = filename
        self.reason = reason
        super().__init__(f"'{filename}' does not appear to be a medical document: {reason}")


def _has_medical_content(doc: Dict[str, Any]) -> bool:
    """True if the extraction actually pulled out *structured* clinical
    substance — at least one medication, lab result, or noted allergy.

    Deliberately does NOT treat a non-empty clinical_notes string as
    evidence on its own: unlike medications/lab_results/allergies_noted,
    clinical_notes is populated generically with whatever text the vision
    model transcribes off the page — a conference-slide screenshot or a
    Zoom participant list produces a perfectly non-empty, well-formed
    clinical_notes description with zero clinical content in it. The
    structured fields only get populated when the model recognizes an
    actual medication/lab/allergy entity, so they're the reliable signal."""
    if doc.get("medications"):
        return True
    if doc.get("lab_results"):
        return True
    if doc.get("allergies_noted"):
        return True
    if doc.get("diagnoses_or_conditions"):
        return True
    return any(doc.get(collection) for collection in CLINICAL_EVENT_COLLECTIONS)


# Sentinel distinguishing "the extraction reported no score at all" from
# "it reported one and the value happened to be 0.0". The DECISION treats
# both as 0.0; only the wording of the rejection message tells them apart.
_CONFIDENCE_MISSING = object()


def _confidence_value(doc: Dict[str, Any]) -> float:
    """The confidence used for the accept/reject DECISION.

    Anything missing or non-numeric counts as 0.0 — an unreported score is
    not evidence of a good read, and a document typed as clinical with no
    content and no score is exactly the shape a mistagged screenshot has.
    """
    raw = doc.get("overall_confidence", _CONFIDENCE_MISSING)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    return float(raw)


def _describe_confidence(doc: Dict[str, Any]) -> str:
    """How to TALK about that confidence in a message the user reads.

    The decision coerces a missing or non-numeric score to 0.0, but saying
    so verbatim produced messages that were plainly untrue: a document with
    no score at all was reported as "overall_confidence=0.0" — implying the
    model read it and had zero confidence — and a string score produced the
    nonsense "overall_confidence=high is below 0.35". Telling someone their
    prescription scored zero when nothing scored it at all sends them off to
    re-photograph a perfectly good document.

    The decision is unchanged; only the description is honest about which
    case it actually hit.
    """
    raw = doc.get("overall_confidence", _CONFIDENCE_MISSING)
    if raw is _CONFIDENCE_MISSING:
        return "no confidence score was reported for it"
    if raw is None:
        return "its confidence score came back empty"
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return f"its confidence score was {raw!r}, which is not a number"
    return f"its confidence score of {raw} is below {LOW_CONFIDENCE_THRESHOLD}"


def looks_like_medical_document(doc: Dict[str, Any]) -> bool:
    """
    Decides whether one extraction result (the dict returned by
    process_document() for a single file/page) represents a real medical
    document.

    A document passes if either:
      - it actually contains *structured* medical content (medications,
        lab results, or allergies) — regardless of what document_type got
        assigned, e.g. an intake note typed "other" that still mentions
        an allergy, OR
      - its document_type is one of the recognized clinical types
        (prescription / lab_report / discharge_summary) AND its
        overall_confidence meets LOW_CONFIDENCE_THRESHOLD.

    The document_type label alone is NOT sufficient: a vision model can
    mistag a non-medical image (screenshot, boarding pass, receipt) as a
    recognized clinical type while extracting no actual clinical content
    and reporting low confidence. Requiring confidence too closes that
    hole — content is the strong signal, a merely-labeled-but-unconfident
    "prescription" with nothing in it is not.

    A document typed "other" with no clinical content is rejected outright.
    """
    doc_type = doc.get("document_type")

    if _has_medical_content(doc):
        return True

    if doc_type in RECOGNIZED_MEDICAL_TYPES:
        return _confidence_value(doc) >= LOW_CONFIDENCE_THRESHOLD

    return False


def rejection_reason(doc: Dict[str, Any]) -> str:
    """Human-readable explanation for why a document was rejected, for use
    in API error messages / logs.

    The wording is derived from _describe_confidence() rather than printed
    straight from the raw field, so the message can never claim something
    the extraction did not say (see that function).
    """
    doc_type = doc.get("document_type", "unknown")
    if doc_type not in RECOGNIZED_MEDICAL_TYPES:
        return (
            f"it was classified as '{doc_type}' and no medications, lab results, "
            f"allergies, or structured clinical events were found in it."
        )
    return (
        f"it was classified as '{doc_type}', but {_describe_confidence(doc)} and no "
        f"medications, lab results, allergies, or structured clinical events were "
        f"found to support that label."
    )


def filter_non_medical_documents(
    docs: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Splits a list of extraction results into (kept, rejected) without any
    additional model calls. `kept` preserves order; `rejected` entries keep
    the original dict so a caller can still log/inspect what was thrown out.
    """
    kept: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for doc in docs:
        if looks_like_medical_document(doc):
            kept.append(doc)
        else:
            rejected.append(doc)
    return kept, rejected


def assert_medical_document(doc: Dict[str, Any], filename: str) -> None:
    """Raises NonMedicalDocumentError if `doc` (one file's extraction
    result) doesn't look medical. Intended to be called once per uploaded
    file, right after process_document(), before the result is merged into
    the patient's timeline."""
    if not looks_like_medical_document(doc):
        raise NonMedicalDocumentError(filename, rejection_reason(doc))


if __name__ == "__main__":
    # Lightweight self-test, no pytest dependency needed.
    real_prescription = {
        "document_type": "prescription",
        "medications": [{"name": "Amoxicillin", "confidence": 0.9}],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "overall_confidence": 0.9,
    }
    empty_other = {
        "document_type": "other",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "overall_confidence": 0.4,
    }
    unusual_but_real = {
        "document_type": "other",
        "medications": [],
        "lab_results": [],
        "allergies_noted": ["Penicillin"],
        "clinical_notes": "Patient noted a penicillin allergy on intake form.",
        "overall_confidence": 0.6,
    }
    mistagged_screenshot = {
        # what a non-medical screenshot can look like when the vision
        # model mistags document_type instead of picking "other"
        "document_type": "lab_report",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": None,
        "overall_confidence": 0.2,
    }
    conference_slide_screenshot = {
        # real observed case: document_type correctly "other", but
        # clinical_notes is a non-empty verbatim OCR transcription of a
        # conference slide / Zoom window — no structured medical content
        "document_type": "other",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": "Presentation slide: 'Welcome Note VarDial 2026'. Zoom meeting participant panel visible.",  # noqa: E501
        "overall_confidence": 0.78,
    }

    tamil_prescription = {
        # non-English document in Tamil script, but the structured medication
        # field IS populated — the content path accepts it regardless of what
        # language the page happens to be in
        "document_type": "prescription",
        "medications": [{"name": "Metformin", "confidence": 0.88}],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": "மருந்துச்சீட்டு: மெட்ஃபோர்மின் 500 மி.கி., காலை மற்றும் இரவு உணவுடன் ஒரு மாத்திரை.",
        "overall_confidence": 0.92,
    }
    arabic_lab_report = {
        # non-English document in Arabic script — passes via structured
        # lab_results even though the free-text notes are entirely Arabic
        "document_type": "lab_report",
        "medications": [],
        "lab_results": [{"test_name": "HbA1c", "value": "7.2", "unit": "%"}],
        "allergies_noted": [],
        "clinical_notes": "تقرير المختبر: الهيموغلوبين السكري HbA1c بنسبة 7.2٪.",
        "overall_confidence": 0.9,
    }
    tamil_bus_ticket = {
        # non-English NON-medical document: a non-empty Tamil transcription
        # with zero structured clinical content, typed "other" — must be
        # rejected, proving a non-English OCR dump alone can't slip past the
        # filter (the Tamil analogue of conference_slide_screenshot)
        "document_type": "other",
        "medications": [],
        "lab_results": [],
        "allergies_noted": [],
        "clinical_notes": "பேருந்து முன்பதிவு: சென்னையிலிருந்து மதுரைக்கு, இருக்கை 12, விலை ₹450.",
        "overall_confidence": 0.71,
    }

    kept, rejected = filter_non_medical_documents(
        [
            real_prescription,
            empty_other,
            unusual_but_real,
            mistagged_screenshot,
            conference_slide_screenshot,
            tamil_prescription,
            arabic_lab_report,
            tamil_bus_ticket,
        ]
    )
    assert len(kept) == 4, f"expected 4 kept, got {len(kept)}"
    assert len(rejected) == 4, f"expected 4 rejected, got {len(rejected)}"

    try:
        assert_medical_document(empty_other, "boarding_pass.jpg")
        raise SystemExit("expected NonMedicalDocumentError to be raised")
    except NonMedicalDocumentError as e:
        print("OK — correctly rejected:", e)

    print("All checks passed.")
