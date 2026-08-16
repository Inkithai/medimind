"""
Consult Triage — deterministic clinical routing layer
=====================================================
Routes every finding the pipeline already produced (cross-check report,
deterministic dosage findings, lab trends) to WHO should review it — a
pharmacist or a doctor — with what urgency, what confidence, and for a
doctor, which specialty. It adds no clinical judgment of its own: routing
is a question of SCOPE OF PRACTICE (who is allowed/equipped to resolve
this kind of finding), which is a table, not a model call.

Pipeline position (the decision layer between analysis and care search):

    safety rules -> risk assessment -> CONSULT TRIAGE -> pharmacist/doctor
                                                              -> specialty
                                                              -> care provider search

Routing table:

    Finding                          Route       Urgency   Why
    ------------------------------- ----------- --------- -------------------------------
    Allergy conflict                 doctor      urgent    Prescription must change — a
                                                           prescribing decision
    Drug interaction (high)          doctor      urgent    The combination itself needs
                                                           reconsidering
    Drug interaction (moderate/low)  pharmacist  soon/routine  Managed by timing, spacing,
                                                           monitoring
    Dosage above max (single/daily/  doctor      urgent    Changing a dose is a
      frequency)                                           prescribing decision
    Dosage below min (informational) pharmacist  routine   Data-quality check against the
                                                           dispensing record
    Duplicate prescription           pharmacist  soon      Medication reconciliation is a
                                                           pharmacist's core competency
    Conflicting dosage instructions  pharmacist  soon      They hold the dispensing record
    Lab crossed out of range         doctor      soon      Interpreting a result is a
                                                           diagnostic act
    Lab approaching a boundary       doctor      routine   Nothing abnormal yet — raise at
                                                           the next appointment

Safety properties (hold regardless of what was found):
  * NEVER de-escalates. consult_needed=false means these specific checks
    found no trigger — not "you're fine". The summary says so explicitly.
  * LOW CONFIDENCE NEVER LOWERS URGENCY. confidence describes how sure the
    pipeline is the finding is REAL — not how safely it can be ignored. An
    uncertain allergy conflict is a reason to confirm it, not to ignore
    it. Low-confidence items carry a confidence_caveat instead.
  * No "emergency" urgency exists: every finding here comes from uploaded
    documents, which describe the past. The standing emergency_advice
    field covers anything happening right now.

Specialty selection is the only part needing medical knowledge, so it is
resolved deterministically from a lab-test keyword map, falling back to
general practitioner — never from an LLM, so a failed API call can never
cost a referral.

Deterministic, no LLM calls.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

URGENCY_ORDER = {"routine": 0, "soon": 1, "urgent": 2}

URGENCY_MEANING = {
    "urgent": "make contact today or tomorrow, and do not wait for a scheduled appointment",
    "soon": "arrange a conversation within the next week or so",
    "routine": "raise this at your next planned appointment or pharmacy visit",
}

LOW_CONFIDENCE_AT_OR_BELOW = 0.6

EMERGENCY_ADVICE = (
    "These findings come from uploaded documents, which describe the past. "
    "Anyone with severe or sudden symptoms right now — difficulty breathing, "
    "chest pain, sudden weakness, severe allergic reaction — should seek "
    "emergency care immediately rather than waiting for any appointment."
)

STANDING_NOTE = (
    "This is a routing suggestion — who is best placed to resolve each finding "
    "and how soon to make contact — not a diagnosis. 'No consult needed' means "
    "these specific automated checks found no trigger; it is not a clean bill "
    "of health and never a reason to skip care you were already advised to seek."
)

# Lab-test keyword -> (specialty_key, patient-facing specialty). Keys are
# matched on case-insensitive WORD boundaries against the test name — plain
# substring matching routes any test whose name contains the letters to the
# wrong clinic ("f-ast-ing glucose" contains "ast", "hemoglobin a1c" reached
# the hematologist row before endocrinology). First match wins; order groups
# related tests together.
_LAB_SPECIALTY_MAP: List[Dict[str, str]] = [
    {"keyword": "hba1c", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "a1c", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "glucose", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "insulin", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "tsh", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "t3", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "t4", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "ft3", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "ft4", "key": "endocrinologist", "specialty": "Endocrinologist"},
    {"keyword": "creatinine", "key": "nephrologist", "specialty": "Nephrologist"},
    {"keyword": "egfr", "key": "nephrologist", "specialty": "Nephrologist"},
    {"keyword": "urea", "key": "nephrologist", "specialty": "Nephrologist"},
    {"keyword": "albumin/creatinine", "key": "nephrologist", "specialty": "Nephrologist"},
    {"keyword": "alt", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "ast", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "alp", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "alkaline phosphatase", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "bilirubin", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "ggt", "key": "gastroenterologist", "specialty": "Gastroenterologist / Hepatologist"},
    {"keyword": "cholesterol", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "lipid", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "ldl", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "hdl", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "triglycer", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "troponin", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "bnp", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "probnp", "key": "cardiologist", "specialty": "Cardiologist"},
    {"keyword": "hemoglobin", "key": "hematologist", "specialty": "Hematologist"},
    {"keyword": "haemoglobin", "key": "hematologist", "specialty": "Hematologist"},
    {"keyword": "platelet", "key": "hematologist", "specialty": "Hematologist"},
    {"keyword": "wbc", "key": "hematologist", "specialty": "Hematologist"},
    {"keyword": "ferritin", "key": "hematologist", "specialty": "Hematologist"},
    {"keyword": "inr", "key": "hematologist", "specialty": "Hematologist"},
]

_GP_SPECIALTY = {
    "specialty": "General practitioner (family doctor)",
    "key": "general_physician",
    "reason": (
        "A general practitioner is the right first contact — they hold the whole "
        "record, can treat this directly if it is straightforward, and can refer "
        "on to a specialist if it is not."
    ),
    "basis": "default",
}


def _keyword_matches(keyword: str, test_name_lower: str) -> bool:
    """Match a keyword against a lowercased test name.

    Short keywords (<= 4 chars: "alt", "ast", "tsh", ...) are matched on word
    boundaries — plain substring matching routes any test whose name merely
    *contains* the letters to the wrong clinic ("f-ast-ing lipid profile"
    contains "ast" and used to send a cholesterol work-up to a hepatologist,
    and "hemoglobin a1c" reached the hematologist row before the a1c row it
    never matched). Longer keywords/phrases ("bilirubin", "triglycer",
    "albumin/creatinine") are distinctive enough to match as substrings, and
    must: "triglycer" has to catch "triglycerides", and 3-char forms like
    "ft4" cover the common "FT4" spelling that a bare word boundary on "t4"
    would miss. Consistent with care/recommendation.py's own matcher.
    """
    if len(keyword) <= 4:
        return re.search(rf"\b{re.escape(keyword)}\b", test_name_lower) is not None
    return keyword in test_name_lower


def _specialty_for_lab(test_name: str) -> Dict[str, str]:
    name_lower = (test_name or "").lower()
    for entry in _LAB_SPECIALTY_MAP:
        if _keyword_matches(entry["keyword"], name_lower):
            return {
                "specialty": entry["specialty"],
                "key": entry["key"],
                "reason": f"{test_name} falls within this specialty's area.",
                "basis": "lab_test_map",
            }
    return dict(_GP_SPECIALTY)


def _confidence_caveat(confidence: Optional[float]) -> Optional[str]:
    if isinstance(confidence, (int, float)) and confidence <= LOW_CONFIDENCE_AT_OR_BELOW:
        return (
            "The pipeline is not certain this finding is real (it may stem from a "
            "hard-to-read document). That is a reason to check the original "
            "document and confirm — not to ignore it. The urgency is unchanged."
        )
    return None


def _item(
    trigger: str,
    subject: str,
    detail: str,
    route: str,
    urgency: str,
    why_this_route: str,
    confidence: Optional[float],
    specialty: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "trigger": trigger,
        "subject": subject,
        "detail": detail,
        "route": route,
        "urgency": urgency,
        "urgency_meaning": URGENCY_MEANING[urgency],
        "why_this_route": why_this_route,
        "confidence": confidence if isinstance(confidence, (int, float)) else None,
    }
    caveat = _confidence_caveat(entry["confidence"])
    if caveat:
        entry["confidence_caveat"] = caveat
    if route == "doctor":
        entry["specialty"] = specialty or dict(_GP_SPECIALTY)
    return entry


def generate_consult_triage(
    cross_check: Optional[Dict[str, Any]],
    lab_trends: Optional[Dict[str, Any]] = None,
    dosage_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Builds the full triage report from findings that already exist.
    Returns consult_needed, consult_type ("doctor" wins over "pharmacist"
    when both are needed), overall urgency (max of items), pharmacist_actions,
    doctor_actions, referral_items (all items, most urgent first),
    recommended_specialties, summary, emergency_advice, note.
    """
    items: List[Dict[str, Any]] = []
    cross_check = cross_check or {}
    lab_trends = lab_trends or {}
    dosage_report = dosage_report or {}

    # --- Cross-check findings ---------------------------------------------
    for conflict in cross_check.get("allergy_conflicts") or []:
        subject = f"{conflict.get('medication')} vs allergy '{conflict.get('allergy')}'"
        items.append(_item(
            trigger="allergy_conflict",
            subject=subject,
            detail=conflict.get("explanation") or "",
            route="doctor",
            urgency="urgent",
            why_this_route=(
                "A medication on file conflicts with an allergy recorded in these "
                "same documents. Resolving it means changing or substituting the "
                "prescription, which is a prescribing decision."
            ),
            confidence=conflict.get("confidence"),
        ))

    for interaction in cross_check.get("potential_drug_interactions") or []:
        meds = interaction.get("medications_involved") or []
        subject = " + ".join(str(m) for m in meds) or "drug interaction"
        severity = str(interaction.get("severity") or "moderate").lower()
        if severity == "high":
            items.append(_item(
                trigger="drug_interaction_high",
                subject=subject,
                detail=interaction.get("explanation") or "",
                route="doctor",
                urgency="urgent",
                why_this_route=(
                    "A high-severity interaction means the combination itself needs "
                    "reconsidering — a prescribing decision."
                ),
                confidence=interaction.get("confidence"),
            ))
        else:
            items.append(_item(
                trigger=f"drug_interaction_{severity}",
                subject=subject,
                detail=interaction.get("explanation") or "",
                route="pharmacist",
                urgency="soon" if severity == "moderate" else "routine",
                why_this_route=(
                    "Lower-severity interactions are typically managed by timing, "
                    "spacing, or monitoring — a pharmacist can advise without an "
                    "appointment."
                ),
                confidence=interaction.get("confidence"),
            ))

    for duplicate in cross_check.get("duplicate_prescriptions") or []:
        items.append(_item(
            trigger="duplicate_prescription",
            subject=str(duplicate.get("medication") or "duplicate prescription"),
            detail=duplicate.get("explanation") or "",
            route="pharmacist",
            urgency="soon",
            why_this_route=(
                "Medication reconciliation — confirming what should actually be "
                "taken when the same drug appears twice — is a pharmacist's core "
                "competency."
            ),
            confidence=duplicate.get("confidence"),
        ))

    for conflict in cross_check.get("conflicting_dosage_instructions") or []:
        items.append(_item(
            trigger="conflicting_dosage_instructions",
            subject=str(conflict.get("medication") or "conflicting instructions"),
            detail=conflict.get("explanation") or "",
            route="pharmacist",
            urgency="soon",
            why_this_route=(
                "The pharmacist holds the dispensing record and can check which "
                "instruction stands."
            ),
            confidence=conflict.get("confidence"),
        ))

    # --- Deterministic dosage findings -------------------------------------
    for finding in dosage_report.get("findings") or []:
        kind = finding.get("kind")
        if kind in ("above_max_single_dose", "above_max_daily_dose", "above_max_frequency"):
            items.append(_item(
                trigger=f"dosage_{kind}",
                subject=str(finding.get("medication") or finding.get("ingredient") or "dosage"),
                detail=finding.get("explanation") or "",
                route="doctor",
                urgency="urgent",
                why_this_route=(
                    "A dose above a published adult ceiling can only be changed by "
                    "the prescriber — a prescribing decision."
                ),
                confidence=finding.get("confidence"),
            ))
        elif kind == "below_min_single_dose":
            items.append(_item(
                trigger="dosage_below_min_single_dose",
                subject=str(finding.get("medication") or finding.get("ingredient") or "dosage"),
                detail=finding.get("explanation") or "",
                route="pharmacist",
                urgency="routine",
                why_this_route=(
                    "An unusually low printed dose is most often a reading or "
                    "transcription issue — the pharmacist can confirm it against "
                    "the dispensing record."
                ),
                confidence=finding.get("confidence"),
            ))

    # --- Lab trend findings -------------------------------------------------
    for trend in lab_trends.get("trends") or []:
        test_name = str(trend.get("test_name") or "lab test")
        specialty = _specialty_for_lab(test_name)
        if trend.get("crossed_into_abnormal_at"):
            crossing = trend["crossed_into_abnormal_at"]
            items.append(_item(
                trigger="lab_crossed_out_of_range",
                subject=test_name,
                detail=(
                    f"{test_name} moved outside its normal range at the "
                    f"{crossing.get('date')} test ({crossing.get('flag')})."
                ),
                route="doctor",
                urgency="soon",
                why_this_route=(
                    "Interpreting a result that has left its normal range is a "
                    "diagnostic act only a doctor can perform."
                ),
                confidence=trend.get("confidence"),
                specialty=specialty,
            ))
        elif trend.get("approaching_threshold"):
            items.append(_item(
                trigger="lab_approaching_boundary",
                subject=test_name,
                detail=(
                    f"{test_name} is still within its normal range but has been "
                    "drifting toward the boundary across visits."
                ),
                route="doctor",
                urgency="routine",
                why_this_route=(
                    "Nothing is abnormal yet — this is worth raising at the next "
                    "planned appointment rather than making a special one."
                ),
                confidence=trend.get("confidence"),
                specialty=specialty,
            ))

    # --- Assemble the report -------------------------------------------------
    items.sort(key=lambda item: URGENCY_ORDER[item["urgency"]], reverse=True)
    pharmacist_actions = [item for item in items if item["route"] == "pharmacist"]
    doctor_actions = [item for item in items if item["route"] == "doctor"]

    consult_needed = bool(items)
    consult_type: Optional[str] = None
    if doctor_actions:
        consult_type = "doctor"
    elif pharmacist_actions:
        consult_type = "pharmacist"

    overall_urgency: Optional[str] = items[0]["urgency"] if items else None

    # Distinct specialties across doctor items, most urgent first, GP last.
    recommended_specialties: List[Dict[str, Any]] = []
    seen_keys = set()
    for item in doctor_actions:
        spec = item.get("specialty") or dict(_GP_SPECIALTY)
        key = spec.get("key", "general_physician")
        if key in seen_keys:
            for existing in recommended_specialties:
                if existing["key"] == key:
                    existing["triggered_by"].append(item["subject"])
            continue
        seen_keys.add(key)
        recommended_specialties.append({
            "specialty": spec["specialty"],
            "key": key,
            "reason": spec["reason"],
            "basis": spec.get("basis", "default"),
            "urgency": item["urgency"],
            "confidence": item.get("confidence"),
            "triggered_by": [item["subject"]],
        })
    recommended_specialties.sort(
        key=lambda s: (URGENCY_ORDER[s["urgency"]], s["key"] != "general_physician"),
        reverse=True,
    )

    if consult_needed:
        summary = (
            f"A {consult_type} should be consulted — "
            f"{URGENCY_MEANING[overall_urgency]}. "
            f"{len(items)} finding(s) were routed: {len(doctor_actions)} to a doctor, "
            f"{len(pharmacist_actions)} to a pharmacist. This is a routing "
            "suggestion, not a diagnosis."
        )
    else:
        summary = (
            "These automated checks found no trigger for a consult. That is not a "
            "clean bill of health — it only means nothing in the uploaded documents "
            "fired these specific checks. Keep any care you were already advised "
            "to seek."
        )

    return {
        "consult_needed": consult_needed,
        "consult_type": consult_type,
        "urgency": overall_urgency,
        "urgency_meaning": URGENCY_MEANING.get(overall_urgency) if overall_urgency else None,
        "confidence": max((i["confidence"] or 0.0) for i in items) if items else None,
        "recommended_specialties": recommended_specialties,
        "pharmacist_actions": pharmacist_actions,
        "doctor_actions": doctor_actions,
        "referral_items": items,
        "summary": summary,
        "emergency_advice": EMERGENCY_ADVICE,
        "note": STANDING_NOTE,
    }
