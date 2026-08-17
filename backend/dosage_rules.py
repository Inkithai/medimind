"""
Deterministic Dosage Rules
=========================================
Validates each extracted medication's NORMALIZED dose (dosage_value,
dosage_unit, frequency_per_day — fields the extractor already produces)
against a curated table of well-established adult dosing limits. The LLM
can explain a finding; it must never be the source of the dosage rule
itself — "is this dose safe?" is a lookup, not a judgment call.

Rule shape per ingredient (all optional except max_single_dose_mg or
max_daily_dose_mg):
    max_single_dose_mg   largest routinely-used single adult dose
    max_daily_dose_mg    ceiling for total daily intake
    max_frequency_per_day
    min_single_dose_mg   below this a dose is flagged sub-therapeutic
                         (informational — underdosing is a data-quality
                         signal, not an emergency)
    notes                plain-language context included in findings

Scope discipline, mirroring drug_interactions.py:
  * Only unambiguous, widely documented ADULT limits are included. Weight-
    based, pediatric, renal-adjusted, and indication-specific dosing are
    deliberately out of scope — flagging those deterministically would be
    guessing, which is the LLM cross-check's job to reason about, not ours
    to hard-code wrong.
  * Doses are compared after conversion to mg. Exact mass conversions
    (g/mcg -> mg) need no assumption. Tablet and liquid (mL) doses are
    converted only when the rule documents a standard adult strength, and
    IU doses only via an exact IU->mg factor — every such finding carries
    the assumption in its explanation and a lower confidence. A dose whose
    unit cannot be converted is reported as NOT EVALUATED, never guessed.
  * PRN / as-needed medications are not checked against daily ceilings
    (frequency_per_day is null by construction); their single-dose limit
    still applies.
  * Activity scoping (medication_activity.py): only prescriptions still
    active at the reference date (default today) are checked. Entries whose
    course provably ended earlier are listed under `excluded_inactive`
    with reasons — historical, never silently dropped from the report.
  * Every finding always carries the standing consult-a-professional
    framing. The check NEVER says a dose is "safe" — absence of a finding
    means "no rule fired", not an endorsement.

Deterministic, no LLM calls.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

DOSAGE_CHECK_CONFIDENCE = 0.95  # arithmetic against a published limit
# Findings whose dose was converted through a documented standard strength
# (tablet / mL) rather than an exact mass conversion are still arithmetic
# checks, but the underlying assumption deserves a lower confidence than a
# direct mg comparison.
ASSUMED_STRENGTH_CONFIDENCE = 0.85

# ---------------------------------------------------------------------------
# Rule table — keyed by lowercase INN ingredient name.
# Values in mg for a routine ADULT. Sources: widely published maximum-dose
# references (product labeling ceilings).
# ---------------------------------------------------------------------------

DOSAGE_RULES: Dict[str, Dict[str, Any]] = {
    "paracetamol": {
        "max_single_dose_mg": 1000, "max_daily_dose_mg": 4000, "max_frequency_per_day": 4,
        "standard_tablet_strength_mg": 500,       # routine adult 500 mg tablet
        "standard_liquid_strength_mg_per_ml": 50,  # 250 mg/5 mL standard adult syrup
        "notes": "Exceeding 4 g/day risks severe liver injury. Tablet/liquid checks assume "
                 "the standard adult strengths (500 mg tablets, 250 mg/5 mL syrup) — confirm "
                 "the strength printed on the pack.",
    },
    "acetaminophen": {  # alias spelling
        "max_single_dose_mg": 1000, "max_daily_dose_mg": 4000, "max_frequency_per_day": 4,
        "standard_tablet_strength_mg": 500,
        "standard_liquid_strength_mg_per_ml": 50,
        "notes": "Exceeding 4 g/day risks severe liver injury. Tablet/liquid checks assume "
                 "the standard adult strengths (500 mg tablets, 250 mg/5 mL syrup) — confirm "
                 "the strength printed on the pack.",
    },
    "ibuprofen": {
        "max_single_dose_mg": 800, "max_daily_dose_mg": 3200, "max_frequency_per_day": 4,
        "standard_liquid_strength_mg_per_ml": 20,  # 100 mg/5 mL standard adult suspension
        "notes": "Prescription ceiling; OTC self-medication ceiling is lower (1200 mg/day). "
                 "Liquid checks assume the standard 100 mg/5 mL adult suspension.",
    },
    "naproxen": {
        "max_single_dose_mg": 500, "max_daily_dose_mg": 1250,
        "notes": "1250 mg on day one of acute pain; 1000 mg/day maintenance.",
    },
    "diclofenac": {"max_single_dose_mg": 75, "max_daily_dose_mg": 150},
    "aspirin": {
        "max_single_dose_mg": 1000, "max_daily_dose_mg": 4000, "max_frequency_per_day": 4,
        "notes": "Analgesic dosing; low-dose (75-325 mg) antiplatelet use is far below this.",
        "min_single_dose_mg": 50,
    },
    "amoxicillin": {
        "max_single_dose_mg": 1000, "max_daily_dose_mg": 3000,
        "standard_liquid_strength_mg_per_ml": 50,  # 250 mg/5 mL standard adult suspension
        "notes": "Liquid checks assume the standard 250 mg/5 mL adult suspension.",
    },
    "metformin": {
        "max_single_dose_mg": 1000, "max_daily_dose_mg": 2550,
        "notes": "Common ceiling 2550 mg/day (850 mg three times daily); some references allow 3000 mg/day extended-release.",
    },
    "atorvastatin": {"max_single_dose_mg": 80, "max_daily_dose_mg": 80, "max_frequency_per_day": 1},
    "simvastatin": {
        "max_single_dose_mg": 40, "max_daily_dose_mg": 40, "max_frequency_per_day": 1,
        "notes": "80 mg restricted to long-tolerant patients due to myopathy risk.",
    },
    "omeprazole": {"max_single_dose_mg": 40, "max_daily_dose_mg": 120,
                   "notes": "Routine ceiling 40 mg/day; higher divided doses only in hypersecretory conditions."},
    "amlodipine": {"max_single_dose_mg": 10, "max_daily_dose_mg": 10, "max_frequency_per_day": 1},
    "lisinopril": {"max_single_dose_mg": 40, "max_daily_dose_mg": 80},
    "losartan": {"max_single_dose_mg": 100, "max_daily_dose_mg": 100},
    "metoprolol": {"max_single_dose_mg": 200, "max_daily_dose_mg": 400},
    "sertraline": {"max_single_dose_mg": 200, "max_daily_dose_mg": 200, "max_frequency_per_day": 1},
    "fluoxetine": {"max_single_dose_mg": 80, "max_daily_dose_mg": 80},
    "tramadol": {
        "max_single_dose_mg": 100, "max_daily_dose_mg": 400, "max_frequency_per_day": 4,
        "notes": "Seizure risk rises with dose; 400 mg/day ceiling for immediate release.",
    },
    "cetirizine": {"max_single_dose_mg": 10, "max_daily_dose_mg": 10, "max_frequency_per_day": 1},
    "loratadine": {"max_single_dose_mg": 10, "max_daily_dose_mg": 10, "max_frequency_per_day": 1},
    "prednisolone": {"max_single_dose_mg": 60, "max_daily_dose_mg": 80,
                     "notes": "Routine adult ceiling; short high-dose bursts exist but warrant review."},
    "ciprofloxacin": {"max_single_dose_mg": 750, "max_daily_dose_mg": 1500},
    "azithromycin": {"max_single_dose_mg": 500, "max_daily_dose_mg": 500, "max_frequency_per_day": 1,
                     "notes": "Typical regimens: 500 mg day one then 250 mg, or 500 mg/day for 3 days."},
    "warfarin": {"max_single_dose_mg": 10, "max_daily_dose_mg": 10, "max_frequency_per_day": 1,
                 "notes": "Highly individualized by INR; doses above 10 mg/day are unusual and worth confirming."},
    "levothyroxine": {"max_single_dose_mg": 0.3, "max_daily_dose_mg": 0.3, "max_frequency_per_day": 1,
                      "notes": "300 micrograms/day is an unusual ceiling — most adults need 50-200 micrograms."},
    "gliclazide": {"max_single_dose_mg": 160, "max_daily_dose_mg": 320},
    "glimepiride": {"max_single_dose_mg": 8, "max_daily_dose_mg": 8, "max_frequency_per_day": 1},
    "cholecalciferol": {  # vitamin D3
        "max_daily_dose_mg": 0.1,  # 4000 IU/day routine adult upper limit
        "iu_to_mg": 0.000025,       # exact: 1 IU cholecalciferol = 0.025 mcg
        "notes": "Routine adult supplementation ceiling is 4000 IU (100 mcg)/day. "
                 "Intentional prescription-strength bolus regimens (e.g. 50,000 IU once "
                 "weekly) exceed this by design — confirm with the prescriber before "
                 "treating the finding as an error.",
    },
    "ergocalciferol": {  # vitamin D2
        "max_daily_dose_mg": 0.1,
        "iu_to_mg": 0.000025,
        "notes": "Same routine 4000 IU (100 mcg)/day adult ceiling as cholecalciferol; "
                 "prescription bolus regimens are a recognized exception.",
    },
}


def _to_mg(value: float, unit: str) -> Optional[float]:
    """Converts a normalized dose to mg. Returns None for units that are
    not mass-based (mL, IU, drops, puffs...) — those are skipped, not guessed."""
    unit_lower = unit.strip().lower()
    if unit_lower == "mg":
        return value
    if unit_lower in ("g", "gram", "grams"):
        return value * 1000.0
    if unit_lower in ("mcg", "ug", "µg", "microgram", "micrograms"):
        return value / 1000.0
    return None


def _dose_to_mg(
    value: float, unit: str, rule: Dict[str, Any]
) -> Tuple[Optional[float], Optional[str]]:
    """Converts a normalized dose to mg, returning (mg, assumption_note).

    Exact mass conversions (mg/g/mcg) need no assumption. Tablet and
    liquid (mL) doses are converted only when the rule documents a
    standard adult strength, and IU doses only via an exact IU->mg
    factor; the assumption is returned so the finding can state it
    plainly and carry a lower confidence. Returns (None, None) when the
    unit cannot be converted — the dose is reported as not evaluated,
    never guessed.
    """
    unit_lower = unit.strip().lower()

    exact = _to_mg(value, unit_lower)
    if exact is not None:
        return exact, None

    if unit_lower in ("tablet", "tab", "tablets"):
        strength = rule.get("standard_tablet_strength_mg")
        if strength is not None:
            return value * float(strength), f"assuming {strength:g} mg tablets"
    if unit_lower in ("ml", "millilitre", "milliliter", "millilitres", "milliliters"):
        per_ml = rule.get("standard_liquid_strength_mg_per_ml")
        if per_ml is not None:
            return value * float(per_ml), (
                f"assuming a standard {per_ml:g} mg/mL adult liquid strength"
            )
    if unit_lower in ("iu", "international unit", "international units"):
        factor = rule.get("iu_to_mg")
        if factor is not None:
            return value * float(factor), (
                f"converted exactly at {float(factor):g} mg per IU"
            )
    return None, None


def check_dosages(
    timeline: Dict[str, Any], reference_date: Optional[str] = None
) -> Dict[str, Any]:
    """
    Validates every medication still active at the reference date in
    timeline["medications_timeline"] against the rule table. Returns:
        {"findings": [...], "skipped": [...], "excluded_inactive": [...],
         "reference_date": "YYYY-MM-DD", "note": standing consult framing}

    Finding kinds:
        above_max_single_dose   dose per administration exceeds the ceiling
        above_max_daily_dose    dose x frequency exceeds the daily ceiling
        above_max_frequency     more administrations/day than the ceiling
        below_min_single_dose   sub-therapeutic single dose (informational)

    Skip reasons (transparency, not errors): no rule for the ingredient,
    dose not normalized, dose unit not convertible to mg (not evaluated),
    combination product (multiple ingredients — a per-ingredient dose
    can't be attributed safely).

    `excluded_inactive` lists medications whose course provably ended
    before the reference date (medication_activity.py) — they are history
    and are not part of the live dosage check.
    """
    from medication_activity import analyze_medication_activity, filter_active_timeline

    activity = analyze_medication_activity(timeline, reference_date)
    scoped = filter_active_timeline(timeline, reference_date)

    findings: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for med in scoped.get("medications_timeline", []) or []:
        display = med.get("name") or "unknown"
        source = {"date": med.get("date"), "source_file": med.get("source_file")}
        ingredients = [str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()]

        if not ingredients:
            skipped.append({**source, "medication": display, "reason": "no normalized ingredient"})
            continue
        if len(ingredients) > 1:
            skipped.append({
                **source, "medication": display,
                "reason": "combination product — per-ingredient dose cannot be attributed deterministically",
            })
            continue

        ingredient = ingredients[0]
        rule = DOSAGE_RULES.get(ingredient)
        if rule is None:
            skipped.append({**source, "medication": display, "reason": f"no dosage rule for '{ingredient}'"})
            continue

        dosage_value = med.get("dosage_value")
        dosage_unit = med.get("dosage_unit")
        if not isinstance(dosage_value, (int, float)) or not dosage_unit:
            skipped.append({**source, "medication": display, "reason": "dose not normalized to value+unit"})
            continue
        dose_mg, unit_assumption = _dose_to_mg(float(dosage_value), str(dosage_unit), rule)
        if dose_mg is None:
            skipped.append({
                **source, "medication": display,
                "reason": (
                    f"dose unit '{dosage_unit}' cannot be converted to mg for '{ingredient}' "
                    "— not evaluated (no exact conversion or documented standard strength)"
                ),
            })
            continue

        frequency = med.get("frequency_per_day")
        frequency_val = float(frequency) if isinstance(frequency, (int, float)) else None
        is_prn = bool(med.get("is_as_needed"))

        def _finding(kind: str, explanation: str) -> Dict[str, Any]:
            assumption_clause = (
                f" Dose interpreted as {dose_mg:g} mg ({unit_assumption})."
                if unit_assumption else ""
            )
            return {
                "kind": kind,
                "medication": display,
                "ingredient": ingredient,
                "dose_mg": dose_mg,
                "frequency_per_day": frequency_val,
                "as_needed": is_prn,
                **source,
                "unit_assumption": unit_assumption,
                "rule": {k: v for k, v in rule.items() if k != "notes"},
                "rule_notes": rule.get("notes"),
                "explanation": explanation + assumption_clause + (
                    " This is an arithmetic check against a published adult limit — it does "
                    "not account for this patient's age, weight, kidney/liver function, or "
                    "indication. Consult a doctor or pharmacist before making any changes."
                ),
                "confidence": (
                    DOSAGE_CHECK_CONFIDENCE if not unit_assumption
                    else ASSUMED_STRENGTH_CONFIDENCE
                ),
                "source": "dosage_rules",
            }

        max_single = rule.get("max_single_dose_mg")
        if max_single is not None and dose_mg > max_single:
            findings.append(_finding(
                "above_max_single_dose",
                f"{display}: a single dose of {dose_mg:g} mg exceeds the routine adult "
                f"single-dose ceiling of {max_single:g} mg for {ingredient}.",
            ))

        max_daily = rule.get("max_daily_dose_mg")
        if max_daily is not None and frequency_val and not is_prn:
            daily_mg = dose_mg * frequency_val
            if daily_mg > max_daily:
                findings.append(_finding(
                    "above_max_daily_dose",
                    f"{display}: {dose_mg:g} mg x {frequency_val:g} times daily = "
                    f"{daily_mg:g} mg/day, above the routine adult daily ceiling of "
                    f"{max_daily:g} mg for {ingredient}.",
                ))

        max_freq = rule.get("max_frequency_per_day")
        if max_freq is not None and frequency_val and not is_prn and frequency_val > max_freq:
            findings.append(_finding(
                "above_max_frequency",
                f"{display}: {frequency_val:g} administrations per day exceeds the routine "
                f"ceiling of {max_freq:g} per day for {ingredient}.",
            ))

        min_single = rule.get("min_single_dose_mg")
        if min_single is not None and dose_mg < min_single:
            findings.append(_finding(
                "below_min_single_dose",
                f"{display}: a single dose of {dose_mg:g} mg is below the usual minimum of "
                f"{min_single:g} mg for {ingredient} — worth confirming the printed dose "
                "was read correctly.",
            ))

    return {
        "findings": findings,
        "skipped": skipped,
        "excluded_inactive": activity["inactive_medications"],
        "reference_date": activity["reference_date"],
        "note": (
            "These checks compare each currently active prescription's normalized dose "
            "against widely published routine adult limits. A finding is a prompt to "
            "confirm with a doctor or pharmacist — not a diagnosis. No finding does NOT "
            "mean a dose is safe: many medications have no rule here, and individual "
            "factors (age, weight, kidney or liver function) are not visible to this "
            "check. Medications whose documented course has ended are excluded and "
            "listed under excluded_inactive."
        ),
    }
