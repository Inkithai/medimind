"""
Drug–Laboratory Interaction Engine (deterministic)
==================================================
A code-verifiable safety layer that the LLM cross-check cannot be relied on to
catch every time: it connects a medication the patient is taking to the
patient's OWN most-recent measured laboratory value, and flags the combination
when the lab is in a danger zone.

This is a distinct category from drug–DRUG interactions. The question here is
not "do these two drugs clash?" but "does this drug become dangerous because of
this patient's actual lab result?" — e.g. an ACE inhibitor on the same record
as a potassium of 5.9 mmol/L (hyperkalemia risk), or digoxin with a potassium
of 3.1 mmol/L (digoxin-toxicity risk).

Scope discipline (same as drug_interactions.py): only well-established,
textbook-level drug–electrolyte/drug–INR relationships are included, each with
a fixed danger threshold in canonical units and a plain-language explanation.
Anything speculative is left out. Danger is decided on POSITIVE evidence only
(see clinical_lab_values.is_high/is_low): a censored, missing, or
wrong-unit value never produces a finding. This is a reasoning layer over
extracted text, NOT a validated clinical database; every finding keeps the
"consult a professional" framing.

Output findings carry `source: curated_knowledge_base`, so evidence_grading
grades them `deterministic` (computed from the patient's own data + a curated
rule) rather than capping them as model recall.
"""

from __future__ import annotations

from typing import Any, Dict, List, Set, Tuple

from clinical_lab_values import (
    LabValue,
    collect_lab_values,
    flagged_high,
    flagged_low,
    is_high,
    is_low,
    summarise_lab,
)

# Reuse the ingredient-class table so one rule covers every member of a class
# (e.g. every ACE inhibitor) without re-listing each generic.
try:
    from drug_interactions import _CLASS_MEMBERS
except Exception:  # pragma: no cover
    _CLASS_MEMBERS = {}

POTASSIUM_RAISING_CLASSES = (
    "ace_inhibitor",
    "arb",
    "potassium_sparing_diuretic",
    "potassium_supplement",
)
# Heparins also raise potassium (via aldosterone suppression) — listed directly.
POTASSIUM_RAISING_INGREDIENTS: Set[str] = {"heparin", "enoxaparin", "dalteparin"}
SODIUM_LOWERING_INGREDIENTS: Set[str] = {
    "carbamazepine",
    "oxcarbazepine",
    "desmopressin",
}
SODIUM_LOWERING_CLASSES = ("ssri", "thiazide")  # thiazide added below if present
DIGOXIN = "digoxin"
LITHIUM = "lithium"
# Drugs that add bleeding risk independent of the anticoagulant class.
BLEEDING_RISK_CLASSES = ("anticoagulant", "nsaid", "ssri")
BLEEDING_RISK_INGREDIENTS: Set[str] = {"clopidogrel", "prasugrel", "ticagrelor", "dipyridamole"}

# Canonical danger thresholds. Units are matched as substrings of the stored
# unit so "mmol/L", "meq/l", "mmol/l" all match. INR is unitless.
POTASSIUM_UNITS = ("mmol", "meq")
POTASSIUM_HIGH_MOD = 5.5  # >= 5.5 moderate, >= 6.0 high
POTASSIUM_HIGH_HIGH = 6.0
POTASSIUM_LOW = 3.5  # <= 3.5
SODIUM_UNITS = ("mmol", "meq")
SODIUM_LOW_MOD = 135  # <= 135 moderate (flag), <= 130 high
SODIUM_LOW_HIGH = 130
INR_HIGH = 4.0
# Platelets (10^9/L) — low raises bleeding risk with anticoagulants/NSAIDs/SSRIs.
PLATELET_LOW_MOD = 150  # <= 150 thrombocytopenia; <= 100 higher risk
PLATELET_LOW_HIGH = 100
# Magnesium (mmol/L) — low increases digoxin toxicity and arrhythmia risk.
MAGNESIUM_LOW = 0.7
# Hemoglobin (g/dL) — anaemia adds to bleeding risk with anticoagulants/NSAIDs.
HEMOGLOBIN_LOW = 10.0

CONFIDENCE = 0.9


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown medication"


def _med_ingredients(med: Dict[str, Any]) -> Set[str]:
    return {str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()}


def _active_meds(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(timeline.get("medications_timeline") or [])


def _has_class_or_ingredient(
    med: Dict[str, Any], classes: Tuple[str, ...], ingredients: Set[str]
) -> bool:
    meds_ing = _med_ingredients(med)
    for cls in classes:
        if meds_ing & _CLASS_MEMBERS.get(cls, set()):
            return True
    return bool(meds_ing & ingredients)


def _finding(
    rule: str,
    meds: List[Dict[str, Any]],
    lab: LabValue,
    severity: str,
    explanation: str,
) -> Dict[str, Any]:
    return {
        "medications_involved": [_med_display(m) for m in meds],
        "lab": {
            "test": lab.analyte,
            "value": lab.value,
            "unit": lab.unit,
            "flag": lab.flag,
        },
        "explanation": explanation,
        "severity": severity,
        "confidence": CONFIDENCE,
        "source": "curated_knowledge_base",
        "rule": rule,
        "finding_kind": "drug_lab",
    }


def check_drug_lab_findings(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scan the patient's active medications against their most-recent lab
    values and return one finding per dangerous drug–lab combination."""
    meds = _active_meds(timeline)
    if not meds:
        return []
    labs = collect_lab_values(
        timeline,
        ["potassium", "sodium", "inr", "platelet", "magnesium", "hemoglobin"],
    )

    findings: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()

    potassium = labs.get("potassium")
    if potassium is not None and potassium.present:
        # tier the severity
        k_high = is_high(potassium, POTASSIUM_HIGH_MOD, POTASSIUM_UNITS)
        k_high_severe = is_high(potassium, POTASSIUM_HIGH_HIGH, POTASSIUM_UNITS)
        k_low = is_low(potassium, POTASSIUM_LOW, POTASSIUM_UNITS)

        if k_high:
            for med in meds:
                if not _has_class_or_ingredient(
                    med, POTASSIUM_RAISING_CLASSES, POTASSIUM_RAISING_INGREDIENTS
                ):
                    continue
                key = ("k_high_raising", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if k_high_severe else "moderate"
                findings.append(
                    _finding(
                        "potassium_raising_drug + high_potassium",
                        [med],
                        potassium,
                        severity,
                        f"{_med_display(med)} can raise blood potassium. Your most recent potassium "  # noqa: E501
                        f"reading is high ({summarise_lab(potassium)}), which increases the risk of "  # noqa: E501
                        "a dangerous heart rhythm. Do not stop any medicine on your own — ask your "
                        "doctor or pharmacist whether the dose or combination needs reviewing.",
                    )
                )
        if k_low:
            for med in meds:
                if DIGOXIN not in _med_ingredients(med):
                    continue
                key = ("digoxin_low_k", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    _finding(
                        "digoxin + low_potassium",
                        [med],
                        potassium,
                        "moderate",
                        f"Low potassium ({summarise_lab(potassium)}) makes the heart more sensitive to "  # noqa: E501
                        f"digoxin and raises the risk of digoxin toxicity. Ask your doctor whether your "  # noqa: E501
                        "potassium needs correcting or the digoxin dose needs reviewing.",
                    )
                )

    sodium = labs.get("sodium")
    if sodium is not None and sodium.present:
        na_low = is_low(sodium, SODIUM_LOW_MOD, SODIUM_UNITS)
        na_low_severe = is_low(sodium, SODIUM_LOW_HIGH, SODIUM_UNITS)
        if na_low:
            for med in meds:
                ing = _med_ingredients(med)
                hit = _has_class_or_ingredient(
                    med, SODIUM_LOWERING_CLASSES, SODIUM_LOWERING_INGREDIENTS
                )
                if not hit:
                    continue
                key = ("na_lowering_low_na", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if na_low_severe else "moderate"
                findings.append(
                    _finding(
                        "sodium_lowering_drug + low_sodium",
                        [med],
                        sodium,
                        severity,
                        f"{_med_display(med)} can lower blood sodium. Your most recent sodium is low "  # noqa: E501
                        f"({summarise_lab(sodium)}), which can cause confusion, drowsiness or seizures. "  # noqa: E501
                        "Ask your doctor whether this medicine or your fluid intake needs adjusting.",  # noqa: E501
                    )
                )

    inr = labs.get("inr")
    if inr is not None and inr.present:
        # INR is unitless; trust the value when no unit is present or flag is high.
        inr_high = (inr.unit is None and (inr.value or 0) >= INR_HIGH) or (
            flagged_high(inr) and (inr.value or 0) >= INR_HIGH
        )
        if inr_high:
            for med in meds:
                ing = _med_ingredients(med)
                if not (ing & _CLASS_MEMBERS.get("anticoagulant", set())):
                    continue
                key = ("anticoagulant_high_inr", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    _finding(
                        "anticoagulant + high_inr",
                        [med],
                        inr,
                        "high",
                        f"Your INR is high ({summarise_lab(inr)}), meaning your blood is thinner than "  # noqa: E501
                        "the intended range, and you are taking a blood thinner. This raises the risk "  # noqa: E501
                        "of serious bleeding. Contact your doctor or prescriber promptly — do not "
                        "change the dose yourself.",
                    )
                )

    platelet = labs.get("platelet")
    if platelet is not None and platelet.present:
        pl_low = is_low(platelet, PLATELET_LOW_MOD, ("x 10", "10^9", "/l", "/nl")) or (
            flagged_low(platelet) and not platelet.unit
        )
        pl_severe = is_low(platelet, PLATELET_LOW_HIGH, ("x 10", "10^9", "/l", "/nl"))
        if pl_low:
            for med in meds:
                ing = _med_ingredients(med)
                hit = _has_class_or_ingredient(
                    med, BLEEDING_RISK_CLASSES, BLEEDING_RISK_INGREDIENTS
                )
                if not hit:
                    continue
                key = ("low_platelet_bleeding", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                severity = (
                    "high"
                    if (pl_severe or ing & _CLASS_MEMBERS.get("anticoagulant", set()))
                    else "moderate"
                )
                findings.append(
                    _finding(
                        "bleeding_risk_drug + low_platelets",
                        [med],
                        platelet,
                        severity,
                        f"Your platelet count is low ({summarise_lab(platelet)}), which already raises "  # noqa: E501
                        f"bleeding risk, and {_med_display(med)} also increases bleeding. Together the "  # noqa: E501
                        "risk is higher — ask your doctor whether this combination or dose is right for you.",  # noqa: E501
                    )
                )

    magnesium = labs.get("magnesium")
    if (
        magnesium is not None
        and magnesium.present
        and DIGOXIN in {i for m in meds for i in _med_ingredients(m)}
    ):
        mg_low = is_low(magnesium, MAGNESIUM_LOW, ("mmol",)) or (
            flagged_low(magnesium) and not magnesium.unit
        )
        if mg_low:
            for med in meds:
                if DIGOXIN not in _med_ingredients(med):
                    continue
                key = ("digoxin_low_mg", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    _finding(
                        "digoxin + low_magnesium",
                        [med],
                        magnesium,
                        "moderate",
                        f"Low magnesium ({summarise_lab(magnesium)}) — like low potassium — increases "  # noqa: E501
                        "sensitivity to digoxin and the risk of toxicity. Ask your doctor whether your "  # noqa: E501
                        "magnesium needs correcting.",
                    )
                )

    hemoglobin = labs.get("hemoglobin")
    if hemoglobin is not None and hemoglobin.present:
        hb_low = is_low(hemoglobin, HEMOGLOBIN_LOW, ("g/dl", "g/d", "g dl")) or (
            flagged_low(hemoglobin) and not hemoglobin.unit
        )
        if hb_low:
            for med in meds:
                if not _has_class_or_ingredient(
                    med, BLEEDING_RISK_CLASSES, BLEEDING_RISK_INGREDIENTS
                ):
                    continue
                key = ("low_hb_bleeding", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    _finding(
                        "bleeding_risk_drug + low_hemoglobin",
                        [med],
                        hemoglobin,
                        "moderate",
                        f"Your haemoglobin is low ({summarise_lab(hemoglobin)}, suggesting anaemia) and "  # noqa: E501
                        f"{_med_display(med)} can cause or worsen bleeding/anaemia. Ask your doctor "  # noqa: E501
                        "whether this medicine is contributing and should be reviewed.",
                    )
                )

    # Lithium + low sodium: sodium depletion reduces lithium clearance -> toxicity.
    if sodium is not None and sodium.present:
        na_low = is_low(sodium, SODIUM_LOW_MOD, SODIUM_UNITS)
        if na_low:
            for med in meds:
                if LITHIUM not in _med_ingredients(med):
                    continue
                key = ("lithium_low_na", _med_display(med))
                if key in seen:
                    continue
                seen.add(key)
                severity = "high" if is_low(sodium, SODIUM_LOW_HIGH, SODIUM_UNITS) else "moderate"
                findings.append(
                    _finding(
                        "lithium + low_sodium",
                        [med],
                        sodium,
                        severity,
                        f"Low sodium ({summarise_lab(sodium)}) reduces the kidneys' ability to clear "  # noqa: E501
                        "lithium, which can cause lithium to build up to toxic levels. Ask your doctor "  # noqa: E501
                        "to check your lithium level and sodium.",
                    )
                )

    return findings


_LIST_KEY = "drug_lab_findings"


def merge_drug_lab_findings(
    report: Dict[str, Any], findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Append new drug–lab findings to the report, skipping an exact duplicate
    (same rule + same medication display + same lab value)."""
    existing = report.setdefault(_LIST_KEY, [])
    sigs = {
        (
            f.get("rule"),
            tuple(f.get("medications_involved") or []),
            (f.get("lab") or {}).get("value"),
        )
        for f in existing
    }
    for finding in findings:
        sig = (
            finding.get("rule"),
            tuple(finding.get("medications_involved") or []),
            (finding.get("lab") or {}).get("value"),
        )
        if sig in sigs:
            continue
        sigs.add(sig)
        existing.append(finding)
    return report
