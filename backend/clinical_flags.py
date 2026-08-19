"""Derive care-navigation flags from MediMind's existing Round 1 outputs.

This is intentionally a deterministic adapter over the saved timeline,
cross-check report, and lab-trend report. It does not diagnose a patient and
does not replace the existing extractor or safety checker. Its responsibility
is limited to identifying when existing high-risk or low-confidence signals
should unlock the optional local-provider search.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from specialty_mapping import match_specialty

LOW_CONFIDENCE_THRESHOLD = 0.60


def _confidence(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, min(1.0, float(value)))
    return None


def _text(value: Any) -> str:
    return str(value or "").strip()


def _append_flag(
    flags: List[Dict[str, Any]],
    *,
    flag_id: str,
    issue_type: str,
    trigger: str,
    risk_level: str,
    title: str,
    evidence: str,
    source: str,
    confidence: Optional[float] = None,
) -> None:
    # Every selected specialty is derived from exactly the evidence returned
    # to the user, making the specialty recommendation reviewable.
    specialty = match_specialty(issue_type, evidence)
    flags.append(
        {
            "id": flag_id,
            "issue_type": issue_type,
            "trigger": trigger,  # high_risk | low_confidence
            "risk_level": risk_level,  # high | review
            "title": title,
            "evidence": evidence,
            "source": source,
            "confidence": confidence,
            "specialty": specialty,
        }
    )


def _visit_evidence(visit: Dict[str, Any]) -> str:
    medications = ", ".join(
        _text(m.get("name")) for m in visit.get("medications", []) if _text(m.get("name"))
    )
    labs = ", ".join(
        _text(lab.get("test_name"))
        for lab in visit.get("lab_results", [])
        if _text(lab.get("test_name"))  # noqa: E501
    )
    pieces = [
        _text(visit.get("document_type")),
        _text(visit.get("clinical_notes")),
        medications,
        labs,
        ", ".join(
            _text(x) for x in visit.get("illegible_or_low_confidence_fields", []) if _text(x)
        ),
    ]
    return (
        "; ".join(piece for piece in pieces if piece)
        or "A document extraction was marked low confidence."
    )


def derive_clinical_flags(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return only qualifying high-risk or low-confidence navigation flags.

    High-risk signals are intentionally limited to the existing safety
    report's explicit `high` interaction severity and medication allergy
    conflicts. All other eligible flags are explicitly labelled
    low-confidence, rather than turning a lab value into a diagnosis or
    inventing a risk severity that the existing system did not provide.
    """
    flags: List[Dict[str, Any]] = []

    for index, issue in enumerate(cross_check.get("potential_drug_interactions", []) or []):
        if _text(issue.get("severity")).lower() != "high":
            continue
        meds = ", ".join(
            _text(name) for name in issue.get("medications_involved", []) if _text(name)
        )
        explanation = _text(issue.get("explanation"))
        evidence = "; ".join(part for part in [meds, explanation] if part)
        _append_flag(
            flags,
            flag_id=f"interaction-{index}",
            issue_type="high_severity_interaction",
            trigger="high_risk",
            risk_level="high",
            title="Potential high-severity medication interaction",
            evidence=evidence
            or "The safety cross-check marked a medication interaction as high severity.",
            source="Medication safety cross-check",
            confidence=_confidence(issue.get("confidence")),
        )

    for index, issue in enumerate(cross_check.get("allergy_conflicts", []) or []):
        medication = _text(issue.get("medication"))
        allergy = _text(issue.get("allergy"))
        explanation = _text(issue.get("explanation"))
        evidence = "; ".join(
            part
            for part in [
                f"Medication: {medication}" if medication else "",
                f"Recorded allergy: {allergy}" if allergy else "",
                explanation,
            ]
            if part
        )
        _append_flag(
            flags,
            flag_id=f"allergy-{index}",
            issue_type="allergy_conflict",
            trigger="high_risk",
            risk_level="high",
            title="Potential medication and allergy conflict",
            evidence=evidence
            or "The medication safety cross-check found a potential allergy conflict.",
            source="Medication safety cross-check",
            confidence=_confidence(issue.get("confidence")),
        )

    # Low-confidence document-level extraction flags.
    for index, visit in enumerate(timeline.get("visits", []) or []):
        confidence = _confidence(visit.get("overall_confidence"))
        if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        filename = _text((visit.get("_source") or {}).get("file"))
        _append_flag(
            flags,
            flag_id=f"visit-confidence-{index}",
            issue_type="low_confidence_document",
            trigger="low_confidence",
            risk_level="review",
            title="Low-confidence medical document extraction",
            evidence=_visit_evidence(visit),
            source=f"Document extraction{f' — {filename}' if filename else ''}",
            confidence=confidence,
        )

    # Low-confidence medication entries can be clinically relevant even if
    # the containing document's overall confidence was higher.
    for index, medication in enumerate(timeline.get("medications_timeline", []) or []):
        confidence = _confidence(medication.get("confidence"))
        if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        evidence = "; ".join(
            part
            for part in [
                _text(medication.get("name")),
                _text(medication.get("dosage")),
                _text(medication.get("frequency")),
                _text(medication.get("source_file")),
            ]
            if part
        )
        _append_flag(
            flags,
            flag_id=f"medication-confidence-{index}",
            issue_type="low_confidence_medication",
            trigger="low_confidence",
            risk_level="review",
            title="Low-confidence medication extraction",
            evidence=evidence or "A medication field was extracted with low confidence.",
            source="Medication extraction",
            confidence=confidence,
        )

    for index, lab in enumerate(timeline.get("lab_results_timeline", []) or []):
        confidence = _confidence(lab.get("confidence"))
        if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        evidence = "; ".join(
            part
            for part in [
                _text(lab.get("test_name")),
                _text(lab.get("value")),
                _text(lab.get("unit")),
                _text(lab.get("source_file")),
            ]
            if part
        )
        _append_flag(
            flags,
            flag_id=f"lab-confidence-{index}",
            issue_type="low_confidence_lab_result",
            trigger="low_confidence",
            risk_level="review",
            title="Low-confidence lab result extraction",
            evidence=evidence or "A lab result was extracted with low confidence.",
            source="Lab result extraction",
            confidence=confidence,
        )

    for index, trend in enumerate(lab_trends.get("trends", []) or []):
        confidence = _confidence(trend.get("confidence"))
        if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
            continue
        evidence = "; ".join(
            part
            for part in [
                _text(trend.get("test_name")),
                _text(trend.get("explanation")),
                _text(trend.get("reference_range")),
            ]
            if part
        )
        _append_flag(
            flags,
            flag_id=f"trend-confidence-{index}",
            issue_type="low_confidence_lab_trend",
            trigger="low_confidence",
            risk_level="review",
            title="Low-confidence lab trend analysis",
            evidence=evidence or "A lab trend was computed from low-confidence source values.",
            source="Lab trend analysis",
            confidence=confidence,
        )

    # Retain only low-confidence safety observations; the high-risk
    # interaction/allergy cases were handled separately above.
    for collection_name, title, issue_type in [
        (
            "potential_drug_interactions",
            "Low-confidence medication interaction signal",
            "low_confidence_interaction",
        ),
        (
            "duplicate_prescriptions",
            "Low-confidence duplicate prescription signal",
            "low_confidence_duplicate",
        ),
        (
            "conflicting_dosage_instructions",
            "Low-confidence dosage-conflict signal",
            "low_confidence_dosage",
        ),
    ]:
        for index, issue in enumerate(cross_check.get(collection_name, []) or []):
            confidence = _confidence(issue.get("confidence"))
            if confidence is None or confidence >= LOW_CONFIDENCE_THRESHOLD:
                continue
            evidence = "; ".join(
                part
                for part in [
                    ", ".join(_text(x) for x in issue.get("medications_involved", []) if _text(x)),
                    _text(issue.get("medication")),
                    _text(issue.get("explanation")),
                ]
                if part
            )
            _append_flag(
                flags,
                flag_id=f"{collection_name}-confidence-{index}",
                issue_type=issue_type,
                trigger="low_confidence",
                risk_level="review",
                title=title,
                evidence=evidence or "A medication safety result had low confidence.",
                source="Medication safety cross-check",
                confidence=confidence,
            )

    # Stable ordering: high-risk first, then lowest confidence first.
    return sorted(
        flags,
        key=lambda item: (
            0 if item["trigger"] == "high_risk" else 1,
            item["confidence"] if item["confidence"] is not None else 1.0,
            item["id"],
        ),
    )


def find_flag(flags: List[Dict[str, Any]], flag_id: str) -> Optional[Dict[str, Any]]:
    """Find only a flag freshly derived from the authenticated snapshot."""
    return next((flag for flag in flags if flag["id"] == flag_id), None)
