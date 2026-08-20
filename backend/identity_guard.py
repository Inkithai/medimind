"""
Identity Guard — different-patient / mismatched-document detection
==================================================================
This app is one patient per account. A caregiver uploading a family
member's report into the wrong workspace would silently corrupt the
timeline, the cross-check, lab trends, and every Q&A answer built on them.
This module detects that BEFORE persistence and holds the mismatched
documents for explicit confirmation — never silently merging, never
silently discarding.

Design decisions (each is a deliberate safety choice):

* Compare against the account's DOCUMENT HISTORY, not the registered
  profile name. Account names are set at signup and frequently aren't the
  patient's own name (caregiver accounts, nicknames, transliterations).
  The identity that matters is the one on the documents already trusted
  into this record.
* Names are FUZZY matched. OCR, handwriting, and transliteration introduce
  spelling variance a genuine same-person upload must not be penalized
  for ("Ramesh Kumar" vs "Ramesh Kumaar").
* Ages are never compared directly — a document from 2020 and one from
  2024 legitimately disagree on age. Each document's printed age is
  combined with its date to estimate a BIRTH YEAR, and birth years are
  compared with tolerance for rounding.
* Gender is compared directly when present on both sides.
* No single weak signal holds a document back alone. It takes one strong
  signal (very dissimilar name) or two corroborating weaker signals
  (borderline name + conflicting birth year) to hold a document.
* PARTIAL acceptance: matching documents in a batch proceed immediately;
  only the mismatched ones are held. One wrong file never blocks a whole
  upload.
* A brand-new account has no history, so the first batch is only checked
  against ITSELF: if it disagrees internally, the larger name-group is
  the baseline and the rest are held.

Deterministic, no LLM calls, no network.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Scoring thresholds (named so the rule is auditable)
# ---------------------------------------------------------------------------

# Name similarity below this is a STRONG mismatch signal on its own.
NAME_STRONG_MISMATCH_BELOW = 0.55
# Name similarity below this (but >= strong threshold) is a WEAK signal.
NAME_WEAK_MISMATCH_BELOW = 0.80
# Birth-year estimates further apart than this are a WEAK signal.
BIRTH_YEAR_TOLERANCE = 2
# Conflicting gender (both present, different) is a WEAK signal.

STRONG_SIGNAL_SCORE = 2
WEAK_SIGNAL_SCORE = 1
# A document is held when its total score reaches this.
HOLD_THRESHOLD = 2


def _normalize_name(name: Optional[str]) -> str:
    """Lowercase, strip accents/punctuation/honorifics, collapse spaces."""
    if not name or not str(name).strip():
        return ""
    # A demo/placeholder name is not a different patient's name — it is the
    # absence of a name, and it is treated the same as a blank one.
    #
    # Comparing "DEMO PATIENT" against the real patient on file produced a
    # confident mismatch and held the document back, which meant a sample
    # document could never be added to an account that already had real
    # records. That reading is wrong on its own terms: a placeholder carries
    # no identity information, so it is no evidence that the document belongs
    # to someone else. Returning "" here lets the age/gender corroboration
    # decide on its own merits, exactly as it does for a document whose name
    # could not be read at all.
    try:
        from medical_extractor import _has_demo_marker

        if _has_demo_marker(name):
            return ""
    except Exception:
        pass
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower()
    text = re.sub(r"\b(mr|mrs|ms|miss|dr|master|baby|b/o|shri|smt)\.?\s+", " ", text)
    text = re.sub(r"[^a-z\u0080-\uffff ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _name_similarity(a: str, b: str) -> float:
    """Order-insensitive fuzzy similarity: best of direct ratio and
    token-sorted ratio, so "Kumar Ramesh" matches "Ramesh Kumar"."""
    na, nb = _normalize_name(a), _normalize_name(b)
    if not na or not nb:
        return 1.0  # a missing name is not evidence of a mismatch
    direct = SequenceMatcher(None, na, nb).ratio()
    sorted_a = " ".join(sorted(na.split()))
    sorted_b = " ".join(sorted(nb.split()))
    token_sorted = SequenceMatcher(None, sorted_a, sorted_b).ratio()
    return max(direct, token_sorted)


def _estimate_birth_year(doc: Dict[str, Any]) -> Optional[int]:
    """Combines a document's printed patient_age with its date to estimate
    a birth year. Age alone is meaningless across documents years apart;
    birth year is stable."""
    age = doc.get("patient_age")
    if not isinstance(age, (int, float)) or age <= 0 or age > 130:
        return None
    doc_year: Optional[int] = None
    date_str = doc.get("date")
    if isinstance(date_str, str):
        match = re.search(r"\b(19\d{2}|20\d{2})\b", date_str)
        if match:
            doc_year = int(match.group(1))
    if doc_year is None:
        uploaded = doc.get("uploaded_at")
        if isinstance(uploaded, str):
            match = re.match(r"(\d{4})-", uploaded)
            if match:
                doc_year = int(match.group(1))
    if doc_year is None:
        doc_year = datetime.now().year
    return doc_year - int(age)


def _normalize_gender(value: Optional[str]) -> Optional[str]:
    if not value or not isinstance(value, str):
        return None
    v = value.strip().lower()
    if v in ("m", "male", "man", "boy"):
        return "male"
    if v in ("f", "female", "woman", "girl"):
        return "female"
    return None


def build_known_identity(existing_docs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Derives the account's known patient identity from its document
    history: every distinct patient name seen, the most common birth-year
    estimate, and the most common gender. Returns None when there is no
    usable history (new account)."""
    names: List[str] = []
    birth_years: List[int] = []
    genders: List[str] = []
    for doc in existing_docs:
        name = doc.get("patient_name")
        if name and _normalize_name(name):
            names.append(str(name))
        by = _estimate_birth_year(doc)
        if by is not None:
            birth_years.append(by)
        g = _normalize_gender(doc.get("patient_gender"))
        if g:
            genders.append(g)
    if not names and not birth_years and not genders:
        return None

    distinct_names: List[str] = []
    for name in names:
        if not any(
            _name_similarity(name, seen) >= NAME_WEAK_MISMATCH_BELOW for seen in distinct_names
        ):
            distinct_names.append(name)

    def _mode(values: List[Any]) -> Optional[Any]:
        if not values:
            return None
        counts: Dict[Any, int] = {}
        for v in values:
            counts[v] = counts.get(v, 0) + 1
        return max(counts, key=lambda k: counts[k])

    return {
        "document_patient_names": distinct_names,
        "estimated_birth_year": _mode(birth_years),
        "gender": _mode(genders),
    }


def _score_document(doc: Dict[str, Any], known: Dict[str, Any]) -> Tuple[int, List[Dict[str, Any]]]:
    """Scores one document against a known identity. Returns (score,
    signals). Signals list every mismatch found with an explanation, so
    the caller can show the user exactly why a document was held."""
    score = 0
    signals: List[Dict[str, Any]] = []

    doc_name = doc.get("patient_name")
    known_names = known.get("document_patient_names") or []
    if doc_name and _normalize_name(doc_name) and known_names:
        best_similarity = max(_name_similarity(doc_name, kn) for kn in known_names)
        if best_similarity < NAME_STRONG_MISMATCH_BELOW:
            score += STRONG_SIGNAL_SCORE
            signals.append(
                {
                    "field": "name",
                    "extracted_value": doc_name,
                    "known_value": known_names[0],
                    "similarity": round(best_similarity, 2),
                    "severity": "strong",
                    "explanation": (
                        f'"{doc_name}" is only {round(best_similarity * 100)}% similar to the '
                        "patient name on your other document(s)."
                    ),
                }
            )
        elif best_similarity < NAME_WEAK_MISMATCH_BELOW:
            score += WEAK_SIGNAL_SCORE
            signals.append(
                {
                    "field": "name",
                    "extracted_value": doc_name,
                    "known_value": known_names[0],
                    "similarity": round(best_similarity, 2),
                    "severity": "weak",
                    "explanation": (
                        f'"{doc_name}" is close to, but not clearly the same as, the patient '
                        "name on your other document(s)."
                    ),
                }
            )

    doc_by = _estimate_birth_year(doc)
    known_by = known.get("estimated_birth_year")
    if (
        doc_by is not None
        and known_by is not None
        and abs(doc_by - known_by) > BIRTH_YEAR_TOLERANCE
    ):
        score += WEAK_SIGNAL_SCORE
        signals.append(
            {
                "field": "birth_year",
                "extracted_value": doc_by,
                "known_value": known_by,
                "severity": "weak",
                "explanation": (
                    f"This document suggests the patient was born around {doc_by}, but your "
                    f"other document(s) suggest around {known_by}."
                ),
            }
        )

    doc_gender = _normalize_gender(doc.get("patient_gender"))
    known_gender = known.get("gender")
    if doc_gender and known_gender and doc_gender != known_gender:
        score += WEAK_SIGNAL_SCORE
        signals.append(
            {
                "field": "gender",
                "extracted_value": doc_gender,
                "known_value": known_gender,
                "severity": "weak",
                "explanation": (
                    f"This document lists the patient as {doc_gender}, but your other "
                    f"document(s) list {known_gender}."
                ),
            }
        )

    return score, signals


def check_batch_identity(
    new_docs_by_file: Dict[str, List[Dict[str, Any]]],
    existing_docs: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Checks a batch of newly-extracted documents (grouped per uploaded file:
    {source_file_name: [page dicts]}) against the account's document
    history.

    Returns {"accepted_files": [...], "held": [...], "known_identity": ...}.
    Each `held` entry carries the file names, the extracted identity, the
    mismatch signals, and the score/threshold, so the API can return a
    self-explanatory identity_review_needed block.

    New account with no history: the batch is checked against itself — the
    largest same-name group of files becomes the baseline and the rest are
    held, exactly like a history mismatch.
    """
    known = build_known_identity(existing_docs)

    if known is None:
        # Self-consistency check within the batch: group files by patient name.
        groups: List[Tuple[str, List[str]]] = []  # (representative name, [file names])
        unnamed: List[str] = []
        for file_name, pages in new_docs_by_file.items():
            name = next(
                (
                    p.get("patient_name")
                    for p in pages
                    if p.get("patient_name") and _normalize_name(p.get("patient_name"))
                ),
                None,
            )
            if not name:
                unnamed.append(file_name)
                continue
            for group in groups:
                if _name_similarity(name, group[0]) >= NAME_WEAK_MISMATCH_BELOW:
                    group[1].append(file_name)
                    break
            else:
                groups.append((str(name), [file_name]))

        if len(groups) <= 1:
            # Whole batch agrees (or has no names at all) — accept everything.
            return {
                "accepted_files": list(new_docs_by_file.keys()),
                "held": [],
                "known_identity": None,
            }

        # Batch disagrees: largest group is the baseline.
        groups.sort(key=lambda g: len(g[1]), reverse=True)
        baseline_name, baseline_files = groups[0]
        accepted = list(baseline_files) + unnamed
        held = []
        for name, files in groups[1:]:
            held.append(
                {
                    "patient_name": name,
                    "estimated_birth_year": None,
                    "gender": None,
                    "source_files": files,
                    "message": (
                        f'"{name}" doesn\'t match the patient on the other document(s) in this '
                        "upload."
                    ),
                    "signals": [
                        {
                            "field": "name",
                            "extracted_value": name,
                            "known_value": baseline_name,
                            "similarity": round(_name_similarity(name, baseline_name), 2),
                            "severity": "strong",
                            "explanation": (
                                f'"{name}" doesn\'t match "{baseline_name}", the patient on most '
                                "documents in this upload."
                            ),
                        }
                    ],
                    "score": STRONG_SIGNAL_SCORE,
                    "threshold": HOLD_THRESHOLD,
                }
            )
        return {
            "accepted_files": accepted,
            "held": held,
            "known_identity": {
                "document_patient_names": [baseline_name],
                "estimated_birth_year": None,
                "gender": None,
            },
        }

    # Normal path: compare each file against the account's known identity.
    accepted: List[str] = []
    held: List[Dict[str, Any]] = []
    for file_name, pages in new_docs_by_file.items():
        # A file is held if ANY of its pages mismatches (pages share one patient).
        worst_score = 0
        worst_signals: List[Dict[str, Any]] = []
        identity_page: Dict[str, Any] = {}
        for page in pages:
            score, signals = _score_document(page, known)
            if score > worst_score:
                worst_score, worst_signals = score, signals
                identity_page = page
        if worst_score >= HOLD_THRESHOLD:
            held.append(
                {
                    "patient_name": identity_page.get("patient_name"),
                    "estimated_birth_year": _estimate_birth_year(identity_page),
                    "gender": _normalize_gender(identity_page.get("patient_gender")),
                    "source_files": [file_name],
                    "message": (
                        f'"{identity_page.get("patient_name") or file_name}" doesn\'t match the '
                        "patient on your other document(s)."
                    ),
                    "signals": worst_signals,
                    "score": worst_score,
                    "threshold": HOLD_THRESHOLD,
                }
            )
        else:
            accepted.append(file_name)

    return {"accepted_files": accepted, "held": held, "known_identity": known}


def build_identity_review(
    held: List[Dict[str, Any]], known: Optional[Dict[str, Any]]
) -> Dict[str, Any]:
    """Formats the identity_review_needed response block."""
    total_held = len(held)
    names = ", ".join(sorted({str(h.get("patient_name") or "unknown") for h in held}))
    return {
        "error": "patient_name_mismatch",
        "message": (
            f"{total_held} uploaded document(s) ({names}) don't match the patient on "
            "your other document(s) and were not added. Resubmit just those file(s) "
            "with confirm_identity_mismatch=true to add them anyway, or leave them out."
        ),
        "known_identity": known,
        "held_documents": held,
    }
