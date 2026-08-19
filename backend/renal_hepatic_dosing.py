"""
Renal / Hepatic Patient-Specific Dosing Engine (deterministic)
==============================================================
dosage_rules.py checks a dose against a PUBLISHED adult maximum — and its own
docstring states the honest limit: it "does not account for this patient's
age, weight, kidney/liver function". This module closes that gap for the two
organ systems whose function most often forces a dose change.

It connects a medication that is renally or hepatically sensitive to the
patient's OWN most-recent kidney- or liver-function markers, and flags the
combination when organ function is reduced — so the record can say
"this medicine commonly needs a lower dose or closer monitoring when kidney
function is reduced, and your results suggest reduced kidney function", rather
than silently approving a full adult dose.

CRITICAL SCOPE RULE — it does NOT recommend a replacement dose. Choosing a
dose for an individual patient is a prescribing decision. It surfaces the
reason a prescriber or pharmacist should look again, and stops there. Every
finding keeps the "consult a professional" framing.

Abnormality is decided on POSITIVE evidence only (clinical_lab_values): a
reduced eGFR, a raised creatinine/ALT/AST/bilirubin, or a low albumin in a
recognised unit. A missing, censored, or wrong-unit value never produces a
finding. This is a reasoning layer over extracted text, NOT a validated
dosing calculator. Findings carry `source: curated_knowledge_base` and grade
`deterministic`.
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

try:
    from drug_interactions import _CLASS_MEMBERS
except Exception:  # pragma: no cover
    _CLASS_MEMBERS = {}


# --------------------------------------------------------------------------- #
# Drug sets. Each entry: ingredients (generics) that are sensitive to reduced
# function of the named organ. Conservative, textbook-level only.
# --------------------------------------------------------------------------- #

RENAL_SENSITIVE: Dict[str, str] = {
    # ingredient -> plain-language note about WHY renal function matters here
    "metformin": "Metformin is cleared by the kidneys and can rarely cause a serious build-up of lactic acid (lactic acidosis) when kidney function is reduced.",  # noqa: E501
    "dabigatran": "Dabigatran is largely cleared by the kidneys; reduced kidney function raises bleeding risk and usually requires a dose change.",  # noqa: E501
    "rivaroxaban": "Rivaroxaban levels are affected by kidney function; reduced function can raise bleeding risk.",  # noqa: E501
    "apixaban": "Apixaban is partly cleared by the kidneys; reduced function may require a dose review.",  # noqa: E501
    "edoxaban": "Edoxaban is cleared by the kidneys and is not used when kidney function is very low; a dose review is needed.",  # noqa: E501
    "lithium": "Lithium is cleared by the kidneys; reduced function can cause lithium to build up to toxic levels.",  # noqa: E501
    "digoxin": "Digoxin is cleared by the kidneys; reduced function can cause it to build up to toxic levels.",  # noqa: E501
    "allopurinol": "Allopurinol is cleared by the kidneys; a lower dose is usually needed when kidney function is reduced.",  # noqa: E501
    "gabapentin": "Gabapentin is cleared by the kidneys; the dose is normally reduced when kidney function is reduced.",  # noqa: E501
    "pregabalin": "Pregabalin is cleared by the kidneys; the dose is normally reduced when kidney function is reduced.",  # noqa: E501
    "vancomycin": "Vancomycin dosing is driven by kidney function; reduced function requires dose and level monitoring.",  # noqa: E501
    "nitrofurantoin": "Nitrofurantoin is avoided when kidney function is significantly reduced, as it can be ineffective and cause harm; ask your doctor for an alternative.",  # noqa: E501
    "trimethoprim": "Trimethoprim is cleared by the kidneys and can raise potassium and worsen kidney function when renal function is reduced.",  # noqa: E501
    "ciprofloxacin": "Ciprofloxacin is partly cleared by the kidneys; the dose is usually reduced when kidney function is reduced.",  # noqa: E501
    "levofloxacin": "Levofloxacin is largely cleared by the kidneys; the dose is usually reduced when kidney function is reduced.",  # noqa: E501
    "enoxaparin": "Enoxaparin (low-molecular-weight heparin) builds up when kidney function is reduced, raising bleeding risk; dose adjustment is needed.",  # noqa: E501
    "dalteparin": "Dalteparin (low-molecular-weight heparin) can build up when kidney function is reduced; dose adjustment may be needed.",  # noqa: E501
    "atenolol": "Atenolol is cleared by the kidneys; the dose is usually reduced when kidney function is reduced.",  # noqa: E501
    "sotalol": "Sotalol is cleared by the kidneys; reduced function raises the risk of dangerous heart-rhythm problems and requires dose adjustment.",  # noqa: E501
    "dofetilide": "Dofetilide dosing is driven by kidney function; reduced function markedly raises rhythm risk and requires specialist dose adjustment.",  # noqa: E501
    "baclofen": "Baclofen is cleared by the kidneys and can build up causing drowsiness and confusion when kidney function is reduced.",  # noqa: E501
    "colchicine": "Colchicine is affected by kidney function; a lower dose is needed when kidney function is reduced to avoid toxicity.",  # noqa: E501
    "morphine": "Morphine's active by-products are cleared by the kidneys; reduced function can cause them to build up, causing drowsiness and slow breathing.",  # noqa: E501
    "oxycodone": "Oxycodone levels are affected by kidney function; reduced function can increase side effects and require a lower dose.",  # noqa: E501
    "tramadol": "Tramadol is partly cleared by the kidneys; reduced function can increase side effects and require a lower dose.",  # noqa: E501
    "sitagliptin": "Sitagliptin is cleared by the kidneys; the dose is reduced when kidney function is reduced.",  # noqa: E501
    "empagliflozin": "SGLT2 medicines (e.g. empagliflozin) are cleared by the kidneys and become less effective as kidney function falls; they need review.",  # noqa: E501
    "dapagliflozin": "SGLT2 medicines (e.g. dapagliflozin) are cleared by the kidneys and need review when kidney function is reduced.",  # noqa: E501
    "canagliflozin": "Canagliflozin is affected by kidney function and is dose-limited when kidney function is reduced.",  # noqa: E501
    "famotidine": "Famotidine is cleared by the kidneys; the dose is usually reduced when kidney function is reduced.",  # noqa: E501
    "ranitidine": "Ranitidine is cleared by the kidneys; the dose is usually reduced when kidney function is reduced.",  # noqa: E501
}
RENAL_SENSITIVE_CLASSES = {
    "nsaid": "NSAIDs can further reduce kidney function and can cause fluid retention; they are often avoided or limited when kidney function is already reduced.",  # noqa: E501
}

HEPATIC_SENSITIVE: Dict[str, str] = {
    "simvastatin": "Statins can affect the liver; when liver tests are already raised, the medicine usually needs reviewing.",  # noqa: E501
    "atorvastatin": "Statins can affect the liver; when liver tests are already raised, the medicine usually needs reviewing.",  # noqa: E501
    "lovastatin": "Statins can affect the liver; when liver tests are already raised, the medicine usually needs reviewing.",  # noqa: E501
    "rosuvastatin": "Statins can affect the liver; when liver tests are already raised, the medicine usually needs reviewing.",  # noqa: E501
    "fluvastatin": "Statins can affect the liver; when liver tests are already raised, the medicine usually needs reviewing.",  # noqa: E501
    "valproate": "Valproate (valproic acid) can injure the liver; raised liver tests mean it should be reviewed promptly.",  # noqa: E501
    "valproic acid": "Valproate (valproic acid) can injure the liver; raised liver tests mean it should be reviewed promptly.",  # noqa: E501
    "amiodarone": "Amiodarone can injure the liver; raised liver tests mean it should be reviewed.",
    "methotrexate": "Methotrexate can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "isoniazid": "Isoniazid can injure the liver; raised liver tests mean it should be reviewed.",
    "paracetamol": "Paracetamol (acetaminophen) is processed by the liver; at higher doses or with raised liver tests it should be reviewed.",  # noqa: E501
    "acetaminophen": "Paracetamol (acetaminophen) is processed by the liver; at higher doses or with raised liver tests it should be reviewed.",  # noqa: E501
    "azathioprine": "Azathioprine can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "mercaptopurine": "Mercaptopurine can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "fluconazole": "Fluconazole can affect the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "itraconazole": "Itraconazole can affect the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "ketoconazole": "Ketoconazole can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "rifampin": "Rifampicin can affect the liver; raised liver tests mean it should be reviewed.",
    "rifampicin": "Rifampicin can affect the liver; raised liver tests mean it should be reviewed.",
    "phenytoin": "Phenytoin is processed by the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "carbamazepine": "Carbamazepine can affect the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "methyldopa": "Methyldopa can injure the liver; raised liver tests mean it should be reviewed.",
    "terbinafine": "Terbinafine can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "leflunomide": "Leflunomide can injure the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "tetracycline": "Tetracyclines can affect the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "doxycycline": "Tetracyclines can affect the liver; raised liver tests mean it should be reviewed.",  # noqa: E501
    "niacin": "Niacin can affect the liver; raised liver tests mean it should be reviewed.",
}

# --------------------------------------------------------------------------- #
# Organ-function thresholds (canonical units, matched as substrings).
# --------------------------------------------------------------------------- #

_EGFR_LOW = 45.0  # mL/min — reduced; <30 is severely reduced
_EGCR_MGDL_HIGH = 1.5  # mg/dL
_EGCR_UMOL_HIGH = 130.0  # µmol/L
_BUN_HIGH = 40.0  # mg/dL
_UREA_HIGH = 17.0  # mmol/L
_ALT_HIGH = 50.0  # U/L (rough ~upper; flag-based when unit unknown)
_AST_HIGH = 50.0
_BILI_MGDL_HIGH = 1.5
_BILI_UMOL_HIGH = 26.0
_ALB_GDL_LOW = 3.5
_ALB_GL_LOW = 35.0


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown medication"


def _med_ingredients(med: Dict[str, Any]) -> Set[str]:
    return {str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()}


def _assess_renal(labs: Dict[str, LabValue]) -> Tuple[bool, List[LabValue], bool]:
    """Return (reduced, markers, severe). `markers` are the readings that
    establish reduced function, for citation."""
    markers: List[LabValue] = []
    severe = False
    egfr = labs.get("egfr")
    if egfr is not None and egfr.present:
        # eGFR is almost always mL/min; trust value when unit absent or matches.
        if egfr.unit is None or "ml" in (egfr.unit or "") or "min" in (egfr.unit or ""):
            if egfr.value <= _EGFR_LOW:
                markers.append(egfr)
                if egfr.value < 30.0:
                    severe = True
    creat = labs.get("creatinine")
    if creat is not None and creat.present:
        if (
            is_high(creat, _EGCR_MGDL_HIGH, ("mg", "mg/dl"))
            or is_high(creat, _EGCR_UMOL_HIGH, ("umol", "µmol", "micro"))
            or (flagged_high(creat) and not creat.unit)
        ):
            markers.append(creat)
    bun = labs.get("bun")
    if bun is not None and bun.present:
        if is_high(bun, _BUN_HIGH, ("mg",)) or (flagged_high(bun) and not bun.unit):
            markers.append(bun)
    urea = labs.get("urea")
    if urea is not None and urea.present:
        if is_high(urea, _UREA_HIGH, ("mmol",)) or (flagged_high(urea) and not urea.unit):
            markers.append(urea)
    return (bool(markers), markers, severe)


def _assess_hepatic(labs: Dict[str, LabValue]) -> Tuple[bool, List[LabValue], bool]:
    markers: List[LabValue] = []
    severe = False
    for key, thr, units_low in (
        ("alt", _ALT_HIGH, ("u/l", "u", "iu", "/l")),
        ("ast", _AST_HIGH, ("u/l", "u", "iu", "/l")),
    ):
        lv = labs.get(key)
        if lv is None or not lv.present:
            continue
        if is_high(lv, thr, units_low) or (flagged_high(lv) and not lv.unit):
            markers.append(lv)
            if lv.value is not None and lv.value >= thr * 3:
                severe = True
    bili = labs.get("bilirubin")
    if bili is not None and bili.present:
        if (
            is_high(bili, _BILI_MGDL_HIGH, ("mg", "mg/dl"))
            or is_high(bili, _BILI_UMOL_HIGH, ("umol", "µmol", "micro"))
            or (flagged_high(bili) and not bili.unit)
        ):
            markers.append(bili)
            severe = True
    alb = labs.get("albumin")
    if alb is not None and alb.present:
        if (
            is_low(alb, _ALB_GDL_LOW, ("g/dl", "g/d", "g dl"))
            or is_low(alb, _ALB_GL_LOW, ("g/l",))
            or (flagged_low(alb) and not alb.unit)
        ):
            markers.append(alb)
    return (bool(markers), markers, severe)


def _finding(
    rule: str,
    organ: str,
    meds: List[Dict[str, Any]],
    markers: List[LabValue],
    severity: str,
    explanation: str,
) -> Dict[str, Any]:
    return {
        "medications_involved": [_med_display(m) for m in meds],
        "organ": organ,
        "lab_markers": [
            {"test": m.analyte, "value": m.value, "unit": m.unit, "flag": m.flag} for m in markers
        ],
        "explanation": explanation,
        "severity": severity,
        "confidence": 0.85,
        "source": "curated_knowledge_base",
        "rule": rule,
        "finding_kind": "renal_hepatic",
    }


def check_renal_hepatic_findings(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Scan active medications against kidney/liver markers and return one
    finding per organ per sensitive drug set that is exposed to reduced
    function."""
    meds = list(timeline.get("medications_timeline") or [])
    if not meds:
        return []

    renal_labs = collect_lab_values(timeline, ["egfr", "creatinine", "bun", "urea"])
    hepatic_labs = collect_lab_values(timeline, ["alt", "ast", "bilirubin", "albumin"])

    renal_reduced, renal_markers, renal_severe = _assess_renal(renal_labs)
    hepatic_reduced, hepatic_markers, hepatic_severe = _assess_hepatic(hepatic_labs)

    if not renal_reduced and not hepatic_reduced:
        return []

    marker_phrase = ", ".join(summarise_lab(m) for m in (renal_markers or hepatic_markers))
    findings: List[Dict[str, Any]] = []

    if renal_reduced:
        matched_meds: List[Dict[str, Any]] = []
        notes: List[str] = []
        for med in meds:
            ing = _med_ingredients(med)
            hit_ing = ing & set(RENAL_SENSITIVE)
            hit_cls = {
                c: note
                for c, note in RENAL_SENSITIVE_CLASSES.items()
                if ing & _CLASS_MEMBERS.get(c, set())
            }
            if hit_ing or hit_cls:
                matched_meds.append(med)
                if hit_ing:
                    notes.append(next(RENAL_SENSITIVE[i] for i in hit_ing))
                if hit_cls:
                    notes.append(next(iter(hit_cls.values())))
        if matched_meds:
            severity = (
                "high"
                if (
                    renal_severe
                    and any(
                        _med_ingredients(m) & {"metformin", "lithium", "dabigatran"}
                        for m in matched_meds
                    )
                )
                else "moderate"
            )
            findings.append(
                _finding(
                    "renal_sensitive_drug + reduced_renal_function",
                    "renal",
                    matched_meds,
                    renal_markers,
                    severity,
                    "Your kidney-function results suggest reduced kidney function "
                    f"({marker_phrase}). "
                    + " ".join(dict.fromkeys(notes))
                    + " Ask your doctor or pharmacist whether the dose needs lowering or the "
                    "medicine needs changing — do not adjust it yourself.",
                )
            )

    if hepatic_reduced:
        matched_meds = []
        notes = []
        for med in meds:
            ing = _med_ingredients(med)
            hit_ing = ing & set(HEPATIC_SENSITIVE)
            if hit_ing:
                matched_meds.append(med)
                notes.append(next(HEPATIC_SENSITIVE[i] for i in hit_ing))
        if matched_meds:
            severity = "high" if hepatic_severe else "moderate"
            h_phrase = ", ".join(summarise_lab(m) for m in hepatic_markers)
            findings.append(
                _finding(
                    "hepatic_sensitive_drug + reduced_hepatic_function",
                    "hepatic",
                    matched_meds,
                    hepatic_markers,
                    severity,
                    f"Your liver-function results are raised ({h_phrase}). "
                    + " ".join(dict.fromkeys(notes))
                    + " Ask your doctor whether this medicine should be reviewed or the dose "
                    "adjusted.",
                )
            )

    return findings


_LIST_KEY = "renal_hepatic_findings"


def merge_renal_hepatic_findings(
    report: Dict[str, Any], findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    existing = report.setdefault(_LIST_KEY, [])
    sigs = {
        (f.get("rule"), f.get("organ"), tuple(f.get("medications_involved") or []))
        for f in existing
    }
    for finding in findings:
        sig = (
            finding.get("rule"),
            finding.get("organ"),
            tuple(finding.get("medications_involved") or []),
        )
        if sig in sigs:
            continue
        sigs.add(sig)
        existing.append(finding)
    return report
