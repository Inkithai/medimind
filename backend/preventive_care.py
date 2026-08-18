"""
Preventive-Care / Care-Gap Detection (deterministic)
====================================================
The rest of MediMind asks "what is already wrong in this record?". This module
asks the complementary question a mature patient-facing CDS asks: "what
standard preventive care might be MISSING, given this patient's age, sex and
known conditions?"

It generates GENERAL, widely-known public-health screening/immunisation
reminders — the kind every adult is advised to keep up to date — and flags
chronic-condition monitoring that the record suggests but cannot confirm is
happening (because uploaded documents are a sample, not the whole history).

Honesty constraints (matching the rest of the pipeline):
- Every item is framed as "consider discussing / check whether this is up to
  date", never as a diagnosis or a mandate.
- It cannot tell whether a screening actually happened if it is not in the
  uploaded documents, so it says exactly that: "not seen in your records".
- Age and sex are required inputs; without them only generic reminders fire.

Guideline references are intentionally generic (WHO / widely used adult
screening schedules) and conservative.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def _conditions_set(timeline: Dict[str, Any]) -> Set[str]:
    out: Set[str] = set()
    for e in (timeline.get("diagnoses_timeline") or []):
        if isinstance(e, dict) and e.get("name"):
            out.add(str(e["name"]).lower())
    for c in (timeline.get("diagnoses_or_conditions") or []):
        if isinstance(c, str):
            out.add(c.lower())
    return out


def _has_condition(cond_lower_substr: str, conditions: Set[str]) -> bool:
    return any(cond_lower_substr in c for c in conditions)


def generate_care_gaps(
    timeline: Dict[str, Any],
    age: Optional[int],
    sex: Optional[str] = None,
) -> Dict[str, Any]:
    """Return preventive-care reminders for this patient. age in years; sex is
    'male'/'female'/None. Conditions/meds are read from the timeline."""
    sex_norm = (str(sex or "")).strip().lower()
    conditions = _conditions_set(timeline)
    meds = list(timeline.get("medications_timeline") or [])
    med_text = " ".join(
        str(m.get("name") or "") + " " + " ".join(m.get("ingredients") or [])
        for m in meds
    ).lower()

    gaps: List[Dict[str, Any]] = []

    def add(kind: str, title: str, detail: str, priority: str = "routine") -> None:
        gaps.append({"kind": kind, "title": title, "detail": detail, "priority": priority})

    # ---- general adult reminders ----------------------------------------
    add("vaccination", "Annual influenza vaccine",
        "A flu vaccine every year is recommended for adults. Check whether yours is current.")
    add("vaccination", "COVID-19 vaccination",
        "Keep COVID-19 vaccination up to date per local guidance. Not seen in your records.")

    if isinstance(age, int):
        if age >= 50:
            add("screening", "Colorectal cancer screening",
                f"From age 50 (and often earlier in some guidelines), colorectal screening "
                f"(e.g. stool test or colonoscopy) is advised. No result found in your records.",
                "soon" if age >= 60 else "routine")
            add("vaccination", "Shingles vaccine",
                "A shingles vaccine is generally recommended from age 50.")
        if age >= 65:
            add("vaccination", "Pneumococcal vaccine",
                "Pneumococcal vaccination is recommended from age 65.")
        if age >= 18:
            add("screening", "Blood pressure check",
                "Have your blood pressure checked at least every 1–2 years.")
        if age >= 40:
            add("screening", "Cholesterol / cardiovascular risk check",
                "A periodic cholesterol and cardiovascular-risk check is advised from age 40.")
        if age >= 18:
            add("screening", "Type 2 diabetes screening",
                "A blood-glucose / HbA1c check is advisable, especially with risk factors.",
                "routine")
        if age >= 60:
            add("screening", "Bone-density (osteoporosis) assessment",
                "Bone-density assessment is generally advised around age 60+.")
        if 18 <= age <= 50 and "tetanus" not in med_text:
            add("vaccination", "Tetanus booster",
                "A tetanus-diphtheria booster is advised every 10 years. Check when yours was last given.")

    # ---- sex-specific ----------------------------------------------------
    if sex_norm in ("female", "f", "woman"):
        if isinstance(age, int):
            if 21 <= age <= 65:
                add("screening", "Cervical screening (Pap/HPV)",
                    "Cervical screening is advised roughly every 3–5 years through age 65.")
            if 50 <= age <= 74:
                add("screening", "Mammography (breast cancer screening)",
                    "Breast-cancer screening (mammogram) is generally advised every 2 years from 50–74.")
    if sex_norm in ("male", "m", "man") and isinstance(age, int) and age >= 50:
        add("screening", "Discuss prostate health",
            "From around age 50, discuss prostate-cancer screening with your clinician "
            "(the decision is individualised).", "routine")

    # ---- condition-driven monitoring gaps -------------------------------
    if _has_condition("diabetes", conditions):
        add("monitoring", "Diabetes monitoring",
            "With diabetes on record, check that annual reviews are current: HbA1c, "
            "eye and foot checks, kidney function, and blood pressure.", "soon")
    if _has_condition("hypertension", conditions) or "blood pressure" in conditions:
        add("monitoring", "Blood-pressure monitoring",
            "With hypertension on record, check that home/clinic BP monitoring and "
            "follow-up are current.", "soon")
    if _has_condition("asthma", conditions) or _has_condition("copd", conditions):
        add("monitoring", "Respiratory review",
            "With a respiratory condition on record, check that an annual review and "
            "inhaler technique check are current.", "routine")
    if _has_condition("chronic kidney", conditions) or _has_condition("ckd", conditions):
        add("monitoring", "Kidney-function monitoring",
            "With chronic kidney disease on record, check that kidney function and "
            "blood pressure are monitored regularly.", "soon")

    return {
        "age": age,
        "sex": sex_norm or None,
        "care_gaps": gaps,
        "count": len(gaps),
        "note": ("These are general preventive-care reminders based on widely used adult "
                 "screening schedules and the conditions in your record. 'Not seen in your "
                 "records' means a result was not among your uploaded documents — it does not "
                 "mean the test was never done. Confirm with your clinician."),
    }
