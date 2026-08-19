"""Deterministic appointment-preparation and clinician handoff builder.

The output is assembled only from structured patient records and existing
safety/trend analyses. It asks clinicians to review findings; it does not
recommend treatment, infer diagnoses, or claim that historical medication
mentions are a current medication list.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

from change_detection import detect_record_changes


def _key(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _source(date: Any = None, source_file: Any = None, document_url: Any = None) -> Dict[str, Any]:
    return {"date": date, "source_file": source_file, "document_url": document_url}


def _visit_source(visit: Dict[str, Any]) -> Dict[str, Any]:
    raw = visit.get("_source") or {}
    return _source(visit.get("date"), raw.get("file"), visit.get("document_url"))


def _dedupe_sources(items: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    result = []
    for item in items:
        marker = (item.get("date"), item.get("source_file"), item.get("document_url"))
        if marker in seen or marker == (None, None, None):
            continue
        seen.add(marker)
        result.append(item)
    return result


def _medication_sources(timeline: Dict[str, Any], names: Iterable[str]) -> List[Dict[str, Any]]:
    wanted = [_key(name) for name in names if _key(name)]
    sources = []
    for visit in timeline.get("visits", []):
        for med in visit.get("medications", []):
            haystack = " ".join(
                [
                    _key(med.get("name")),
                    *[_key(item) for item in med.get("ingredients", [])],
                ]
            )
            if any(name in haystack or haystack in name for name in wanted):
                sources.append(_visit_source(visit))
                break
    return _dedupe_sources(sources)


def _latest_medication_record(timeline: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # build_patient_timeline already orders visits chronologically, with
    # undated visits last. Prefer the latest dated medication-containing visit.
    candidates = [
        visit
        for visit in timeline.get("visits", [])
        if visit.get("medications") and visit.get("date")
    ]
    if not candidates:
        candidates = [visit for visit in timeline.get("visits", []) if visit.get("medications")]
    return candidates[-1] if candidates else None


def _priority(
    priority_id: str,
    level: str,
    category: str,
    title: str,
    question: str,
    rationale: str,
    evidence: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    return {
        "id": priority_id,
        "level": level,
        "category": category,
        "title": title,
        "question": question,
        "rationale": rationale,
        "evidence": _dedupe_sources(evidence),
    }


def _safety_priorities(
    timeline: Dict[str, Any], cross_check: Dict[str, Any]
) -> List[Dict[str, Any]]:
    priorities = []
    for index, item in enumerate(cross_check.get("allergy_conflicts", []) or []):
        med = item.get("medication") or "this medication"
        allergy = item.get("allergy") or "my documented allergy"
        priorities.append(
            _priority(
                f"allergy-{index}",
                "important",
                "Medication safety",
                f"Review {med} against the documented {allergy} allergy",
                f"My records flag {med} against my {allergy} allergy. Is it appropriate and safe for me?",  # noqa: E501
                item.get("explanation")
                or "A medication–allergy conflict was flagged in the record review.",
                _medication_sources(timeline, [med]),
            )
        )

    for index, item in enumerate(cross_check.get("potential_drug_interactions", []) or []):
        meds = item.get("medications_involved", []) or []
        label = " and ".join(meds) or "the flagged medicines"
        level = "important" if item.get("severity") == "high" else "review"
        priorities.append(
            _priority(
                f"interaction-{index}",
                level,
                "Medication safety",
                f"Review the {label} interaction",
                f"Could you review whether {label} are safe to use together in my situation?",
                item.get("explanation") or "A potential medication interaction was flagged.",
                _medication_sources(timeline, meds),
            )
        )

    for index, item in enumerate(cross_check.get("conflicting_dosage_instructions", []) or []):
        med = item.get("medication") or "this medication"
        evidence = [
            _source(entry.get("date"), entry.get("source_file"))
            for entry in item.get("conflicting_instructions", []) or []
        ]
        priorities.append(
            _priority(
                f"dosage-{index}",
                "important",
                "Medication safety",
                f"Clarify the instructions for {med}",
                f"My records contain different instructions for {med}. Which instruction should I follow?",  # noqa: E501
                item.get("explanation")
                or "Different dosage or frequency instructions were extracted across records.",
                evidence,
            )
        )

    for index, item in enumerate(cross_check.get("duplicate_prescriptions", []) or []):
        med = item.get("medication") or "this medication"
        evidence = [
            _source(entry.get("date"), entry.get("source_file"))
            for entry in item.get("occurrences", []) or []
        ]
        priorities.append(
            _priority(
                f"duplicate-{index}",
                "review",
                "Medication safety",
                f"Reconcile repeated prescriptions for {med}",
                f"{med} appears more than once in my records. Are these duplicates or intended renewals?",  # noqa: E501
                item.get("explanation")
                or "The medicine appeared in multiple prescription entries.",
                evidence,
            )
        )
    return priorities


def _trend_priorities(lab_trends: Dict[str, Any]) -> List[Dict[str, Any]]:
    priorities = []
    for index, trend in enumerate(lab_trends.get("trends", []) or []):
        points = trend.get("data_points", []) or []
        latest = points[-1] if points else {}
        latest_flag = _key(latest.get("flag"))
        is_abnormal = latest_flag in {"high", "low"}
        approaching = bool(trend.get("approaching_threshold"))
        crossing = trend.get("crossed_into_abnormal_at")
        if not (is_abnormal or approaching or crossing):
            continue
        name = trend.get("test_name") or "This lab result"
        direction = trend.get("direction") or "changed"
        if crossing:
            title = f"Discuss {name} crossing outside its reference range"
            question = f"{name} moved outside its reported reference range. What might explain this, and does it need follow-up?"  # noqa: E501
            level = "important"
        elif is_abnormal:
            title = f"Review the {latest_flag} {name} result"
            question = f"My latest {name} result is marked {latest_flag} and the overall direction is {direction}. What does this mean for me?"  # noqa: E501
            level = "review"
        else:
            title = f"Ask whether {name} needs monitoring"
            question = f"{name} is still in range but trending toward a boundary. When, if at all, should it be checked again?"  # noqa: E501
            level = "review"
        evidence = [_source(point.get("date"), point.get("source_file")) for point in points]
        priorities.append(
            _priority(
                f"trend-{index}",
                level,
                "Lab trend",
                title,
                question,
                trend.get("explanation") or f"The structured trend direction is {direction}.",
                evidence,
            )
        )
    return priorities


def _change_priorities(changes: Dict[str, Any]) -> List[Dict[str, Any]]:
    latest = changes.get("latest") or {}
    priorities = []
    for index, change in enumerate(latest.get("changes", []) or []):
        if change.get("importance") != "attention" or change.get("category") == "lab":
            # Lab crossings are explained more completely by the trend engine.
            continue
        title = change.get("title") or "Review a recent record change"
        priorities.append(
            _priority(
                f"change-{index}",
                "review",
                "Recent change",
                title,
                f"My two most recent records show: {title}. Can we confirm what this means for my care?",  # noqa: E501
                change.get("description")
                or "A structured field changed between the two most recent dated records.",
                change.get("evidence", []) or [],
            )
        )
    return priorities


def _latest_medications(visit: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not visit:
        return []
    source = _visit_source(visit)
    return [
        {
            "name": med.get("name") or "Unnamed medication",
            "ingredients": med.get("ingredients", []) or [],
            "dosage": med.get("dosage") or None,
            "frequency": med.get("frequency") or None,
            "source": source,
        }
        for med in visit.get("medications", [])
    ]


def build_appointment_prep(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a printable, source-grounded appointment preparation packet."""
    visits = timeline.get("visits", []) or []
    dated_visits = [visit for visit in visits if visit.get("date")]
    latest_med_record = _latest_medication_record(timeline)
    changes = detect_record_changes(timeline)

    priorities = (
        _safety_priorities(timeline, cross_check)
        + _trend_priorities(lab_trends)
        + _change_priorities(changes)
    )
    level_order = {"important": 0, "review": 1, "routine": 2}
    priorities.sort(
        key=lambda item: (level_order.get(item["level"], 9), item["category"], item["title"])
    )

    if not priorities:
        latest_sources = [_visit_source(visit) for visit in dated_visits[-2:]]
        priorities.append(
            _priority(
                "record-review",
                "routine",
                "Record review",
                "Confirm that the medical record is complete",
                "Could we review whether my medication list, allergies, and recent results are complete and up to date?",  # noqa: E501
                "No specific safety conflict or out-of-range longitudinal trend was available to prioritize.",  # noqa: E501
                latest_sources,
            )
        )

    key_findings = [
        {
            "level": item["level"],
            "text": item["title"],
            "evidence": item["evidence"],
        }
        for item in priorities[:6]
    ]

    providers = sorted(
        {
            str(visit.get("provider_or_doctor")).strip()
            for visit in visits
            if visit.get("provider_or_doctor")
        }
    )
    dates = [visit.get("date") for visit in dated_visits]

    return {
        "handoff": {
            "record_count": len(visits),
            "record_period": {
                "from": dates[0] if dates else None,
                "to": dates[-1] if dates else None,
            },
            "providers_documented": providers,
            "known_allergies": timeline.get("known_allergies", []) or [],
            "latest_medication_record": _visit_source(latest_med_record)
            if latest_med_record
            else None,
            "latest_documented_medications": _latest_medications(latest_med_record),
            "key_findings": key_findings,
        },
        "priorities": priorities[:10],
        "checklist": [
            {
                "id": "medications",
                "text": "Bring medication packaging or a verified list, including supplements.",
            },
            {
                "id": "symptoms",
                "text": "Write down symptoms, when they started, and what makes them better or worse.",  # noqa: E501
            },
            {"id": "questions", "text": "Choose the three questions you most want answered."},
            {
                "id": "follow-up",
                "text": "Before leaving, confirm next steps, warning signs, and whether follow-up tests are needed.",  # noqa: E501
            },
        ],
        "method": "Prepared deterministically from structured records, safety checks, lab trends, and record changes.",  # noqa: E501
        "note": (
            "This packet helps organize a clinician conversation. It is not a diagnosis or treatment plan. "  # noqa: E501
            "The medication section is from the latest medication-containing record and may not represent everything currently taken."  # noqa: E501
        ),
    }
