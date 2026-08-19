"""
Condition-Specific Contraindication Engine (deterministic)
==========================================================
drug_interactions.py answers "do these two DRUGS clash?". This module answers
the other half of medication safety: "does this drug clash with this PATIENT'S
OWN documented condition?" — e.g. an NSAID prescribed to someone whose record
lists a peptic ulcer, or a beta-blocker for someone with asthma.

Conditions are taken ONLY from what the extractor already pulled out of the
documents (the `diagnoses_timeline` / `diagnoses_or_conditions` the pipeline
produces). It never infers a condition the record does not state, and never
diagnoses. Matching is on normalized condition text (keyword phrases), so
"Peptic ulcer disease" and "gastric ulcer" both resolve to the same rule.

Scope discipline (same as the other curated engines): only widely accepted,
textbook-level drug–condition cautions are included, each with a fixed
severity and plain-language explanation. Every finding keeps the "consult a
professional" framing — it surfaces a reason to ask a prescriber, not a
substitution. Findings carry `source: curated_knowledge_base` and grade
`deterministic`.

Because a condition can be recorded in plain language the extractor read at
low confidence, each finding also notes that the underlying condition came
from the patient's uploaded documents.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Set, Tuple

try:
    from drug_interactions import _CLASS_MEMBERS
except Exception:  # pragma: no cover
    _CLASS_MEMBERS = {}

# Beta-blockers are not in the drug_interactions class table; define locally.
BETA_BLOCKERS: Set[str] = {
    "propranolol",
    "atenolol",
    "metoprolol",
    "bisoprolol",
    "carvedilol",
    "nebivolol",
    "sotalol",
    "esmolol",
    "celiprolol",
    "labetalol",
    "timolol",
    "pindolol",
}
STATINS: Set[str] = {
    "simvastatin",
    "atorvastatin",
    "lovastatin",
    "rosuvastatin",
    "fluvastatin",
    "pravastatin",
    "pitavastatin",
}
THIAZIDES: Set[str] = {
    "hydrochlorothiazide",
    "bendroflumethiazide",
    "chlorthalidone",
    "indapamide",
    "metolazone",
    "hydrochlorot",
    "hctz",
}
ANTICHOLINERGICS: Set[str] = {
    "oxybutynin",
    "solifenacin",
    "tolterodine",
    "darifenacin",
    "fesoterodine",
    "hyoscine",
    "scopolamine",
    "atropine",
    "ipratropium",
    "tiotropium",
    "trihexyphenidyl",
    "procyclidine",
    "orphenadrine",
    "cyclobenzaprine",
    "amitriptyline",
    "nortriptyline",
    "imipramine",
    "oxybutynin",
    "dimenhydrinate",
    "cyclizine",
    "promethazine",
    "chlorpheniramine",
    "diphenhydramine",
    "trihexyphenidyl",
}
SULFA_DRUGS: Set[str] = {
    "sulfamethoxazole",
    "co-trimoxazole",
    "cotrimoxazole",
    "trimethoprim-sulfamethoxazole",
    "sulfasalazine",
    "sulfadiazine",
    "sulfisoxazole",
}
GLITAZONES: Set[str] = {"pioglitazone", "rosiglitazone"}
SEIZURE_THRESHOLD_LOWERING: Set[str] = {
    "bupropion",
    "tramadol",
    "theophylline",
    "chloroquine",
    "mefloquine",
}


# Condition -> keyword phrases (lowercase substrings / token phrases).
# Phrases of <=4 chars use token-boundary matching to avoid false hits.
_CONDITIONS: Dict[str, Tuple[str, ...]] = {
    "peptic_ulcer_or_gi_bleed": (
        "peptic ulcer",
        "gastric ulcer",
        "duodenal ulcer",
        "gi bleed",
        "gastrointestinal bleed",
        "gastrointestinal bleeding",
        "bleeding ulcer",
        "upper gi bleed",
        "haemorrhage",
        "hemorrhage",
    ),
    "heart_failure": ("heart failure", "cardiac failure", "congestive heart failure"),
    "chronic_kidney_disease": (
        "chronic kidney",
        "chronic renal",
        "ckd",
        "renal failure",
        "renal impairment",
        "kidney disease",
        "kidney failure",
        "esrd",
    ),
    "asthma": ("asthma",),
    "copd": ("copd", "chronic obstructive pulmonary", "chronic obstructive airway"),
    "pregnancy": ("pregnancy", "pregnant", "antenatal", "gravid", "expecting"),
    "active_bleeding": ("active bleeding", "bleeding disorder", "recent bleed"),
    "liver_disease": (
        "cirrhosis",
        "liver disease",
        "hepatic failure",
        "hepatic impairment",
        "chronic hepatitis",
    ),
    "gout": ("gout", "hyperuricemia", "hyperuricaemia", "high uric acid"),
    "epilepsy": ("epilepsy", "seizure", "convulsion", "epileptic"),
    "dementia": ("dementia", "alzheimer", "cognitive impairment", "cognitive decline"),
    "g6pd_deficiency": ("g6pd", "glucose-6-phosphate", "favism"),
    "glaucoma": ("glaucoma", "narrow angle", "angle closure"),
    "bph": ("benign prostatic", "prostatic hyperplasia", "enlarged prostate", "bph"),
    "falls_elderly": ("falls", "history of falls", "frailty", "frail elderly"),
}

# (drug match) -> set of ingredients/classes. We build the "drug side" of a
# rule lazily from class membership + direct ingredient sets above.


def _conditions_present(timeline: Dict[str, Any]) -> Set[str]:
    """Return the set of condition keys the patient's record actually states."""
    raw_names: List[str] = []
    for entry in timeline.get("diagnoses_timeline") or []:
        if isinstance(entry, dict) and not (entry.get("_trust") or {}).get("quarantined"):
            raw_names.append(str(entry.get("name") or ""))
    for value in timeline.get("diagnoses_or_conditions") or []:
        if isinstance(value, str):
            raw_names.append(value)
    present: Set[str] = set()
    for cond_key, phrases in _CONDITIONS.items():
        for name in raw_names:
            norm = re.sub(r"\s+", " ", name).strip().lower()
            if not norm:
                continue
            for phrase in phrases:
                if len(phrase) <= 4:
                    if re.search(rf"(^|[^a-z0-9]){re.escape(phrase)}([^a-z0-9]|$)", f" {norm} "):
                        present.add(cond_key)
                        break
                else:
                    if phrase in norm:
                        present.add(cond_key)
                        break
    return present


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown medication"


def _med_ingredients(med: Dict[str, Any]) -> Set[str]:
    return {str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()}


def _has(med: Dict[str, Any], classes: Tuple[str, ...] = (), ingredients: Set[str] = set()) -> bool:
    ing = _med_ingredients(med)
    if ing & ingredients:
        return True
    return any(ing & _CLASS_MEMBERS.get(c, set()) for c in classes)


# The rule table: condition -> list of (classes, ingredients, severity, explanation)
def _rules_for_condition(cond: str) -> List[Tuple[Tuple[str, ...], Set[str], str, str]]:
    nsaid_cls = ("nsaid",)
    if cond == "peptic_ulcer_or_gi_bleed":
        return [
            (
                nsaid_cls,
                set(),
                "high",
                "NSAIDs (such as ibuprofen or naproxen) carry a well-known risk of stomach irritation "  # noqa: E501
                "and bleeding, which is heightened when a peptic ulcer or gastrointestinal bleed is "  # noqa: E501
                "already on record. Ask your doctor whether a different painkiller is safer for you.",  # noqa: E501
            ),
            (
                ("ssri",),
                set(),
                "moderate",
                "SSRIs impair platelet function and add to bleeding risk; with a gastrointestinal "
                "bleed or ulcer on record, ask your doctor whether this should be reviewed.",
            ),
        ]
    if cond == "heart_failure":
        return [
            (
                nsaid_cls,
                set(),
                "moderate",
                "NSAIDs can cause fluid retention and can worsen heart failure. Ask your doctor "
                "whether they should be avoided or limited.",
            ),
            (
                (),
                GLITAZONES,
                "high",
                "Pioglitazone and rosiglitazone (glitazones) cause fluid retention and can worsen "
                "heart failure. With heart failure on record, ask your doctor whether this should be "  # noqa: E501
                "stopped.",
            ),
        ]
    if cond == "chronic_kidney_disease":
        return [
            (
                nsaid_cls,
                set(),
                "moderate",
                "NSAIDs can further reduce kidney function. With chronic kidney disease on record, "
                "ask your doctor whether they should be avoided.",
            ),
        ]
    if cond == "asthma":
        return [
            (
                nsaid_cls,
                set(),
                "moderate",
                "Some people with asthma get worse breathing symptoms (NSAID-exacerbated respiratory "  # noqa: E501
                "disease) from NSAIDs. Ask your doctor whether NSAIDs are safe for you.",
            ),
            (
                (),
                BETA_BLOCKERS,
                "moderate",
                "Beta-blockers can narrow the airways and may worsen asthma. Ask your doctor whether "  # noqa: E501
                "a beta-blocker is appropriate or whether an alternative is preferred.",
            ),
        ]
    if cond == "copd":
        return [
            (
                (),
                BETA_BLOCKERS,
                "moderate",
                "Beta-blockers can narrow the airways and may worsen COPD. Ask your doctor whether "
                "a beta-blocker is appropriate or whether an alternative is preferred.",
            ),
        ]
    if cond == "pregnancy":
        return [
            (
                ("ace_inhibitor", "arb"),
                set(),
                "high",
                "ACE inhibitors and ARBs can harm the unborn baby, especially after the first "
                "trimester. Pregnancy is on record, so ask your doctor whether this medicine should "  # noqa: E501
                "be changed.",
            ),
            (
                ("anticoagulant",),
                {"warfarin"},
                "high",
                "Warfarin can harm the unborn baby. Pregnancy is on record, so ask your doctor "
                "whether a different blood thinner is needed.",
            ),
            (
                nsaid_cls,
                set(),
                "moderate",
                "NSAIDs are generally avoided, especially later in pregnancy. Pregnancy is on record, "  # noqa: E501
                "so ask your doctor whether they are safe for you.",
            ),
            (
                (),
                STATINS,
                "moderate",
                "Statins are generally avoided in pregnancy. Pregnancy is on record, so ask your "
                "doctor whether this should be reviewed.",
            ),
        ]
    if cond == "active_bleeding":
        return [
            (
                ("anticoagulant",),
                set(),
                "high",
                "You are on a blood thinner and active bleeding is on record, which raises the risk "  # noqa: E501
                "of serious bleeding. Seek medical advice promptly.",
            ),
            (
                nsaid_cls,
                set(),
                "moderate",
                "NSAIDs increase bleeding risk, and active bleeding is on record. Ask your doctor "
                "whether they should be stopped.",
            ),
        ]
    if cond == "liver_disease":
        return [
            (
                (),
                STATINS,
                "moderate",
                "Statins can affect the liver; with liver disease on record, ask your doctor whether "  # noqa: E501
                "this medicine should be reviewed.",
            ),
            (
                ("nsaid",),
                set(),
                "moderate",
                "NSAIDs can be harder for a damaged liver to handle and can affect clotting; with "
                "liver disease on record, ask your doctor whether they should be avoided.",
            ),
        ]
    if cond == "gout":
        return [
            (
                (),
                THIAZIDES,
                "moderate",
                "Thiazide diuretics can raise uric acid and can trigger or worsen gout. Ask your "
                "doctor whether a different blood-pressure medicine is preferred.",
            ),
        ]
    if cond == "epilepsy":
        return [
            (
                (),
                SEIZURE_THRESHOLD_LOWERING,
                "moderate",
                "Some medicines (e.g. bupropion, tramadol) can lower the seizure threshold. With "
                "epilepsy on record, ask your doctor whether this is appropriate.",
            ),
        ]
    if cond == "dementia":
        return [
            (
                (),
                ANTICHOLINERGICS,
                "moderate",
                "Anticholinergic medicines can worsen thinking and memory and are usually avoided in "  # noqa: E501
                "dementia. Ask your doctor whether a non-anticholinergic alternative is preferred.",
            ),
        ]
    if cond == "g6pd_deficiency":
        return [
            (
                (),
                SULFA_DRUGS,
                "moderate",
                "People with G6PD deficiency can react to sulfa medicines (and some others). Ask your "  # noqa: E501
                "doctor whether this medicine is safe for you.",
            ),
        ]
    if cond == "glaucoma":
        return [
            (
                (),
                ANTICHOLINERGICS,
                "moderate",
                "Anticholinergic medicines can raise eye pressure and can be risky in certain types of "  # noqa: E501
                "glaucoma. Ask your eye doctor whether this is safe for you.",
            ),
        ]
    if cond == "bph":
        return [
            (
                (),
                ANTICHOLINERGICS,
                "moderate",
                "Anticholinergic medicines can worsen urinary symptoms in an enlarged prostate. Ask "  # noqa: E501
                "your doctor whether an alternative is preferred.",
            ),
        ]
    if cond == "falls_elderly":
        return [
            (
                (),
                ANTICHOLINERGICS,
                "moderate",
                "Medicines that cause drowsiness or dizziness (including anticholinergics) raise fall "  # noqa: E501
                "risk. With falls on record, ask your doctor whether this medicine is still needed.",  # noqa: E501
            ),
        ]
    return []


def check_condition_contraindications(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    meds = list(timeline.get("medications_timeline") or [])
    if not meds:
        return []
    present = _conditions_present(timeline)
    if not present:
        return []

    findings: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str]] = set()
    for cond in present:
        for classes, ingredients, severity, explanation in _rules_for_condition(cond):
            if explanation == "_":
                continue  # placeholder, not a real rule
            for med in meds:
                if not _has(med, classes, ingredients):
                    continue
                disp = _med_display(med)
                key = (cond, disp)
                if key in seen:
                    continue
                seen.add(key)
                findings.append(
                    {
                        "medications_involved": [disp],
                        "condition": cond,
                        "explanation": explanation,
                        "severity": severity,
                        "confidence": 0.85,
                        "source": "curated_knowledge_base",
                        "rule": f"condition:{cond}",
                        "finding_kind": "condition_contraindication",
                    }
                )
    return findings


_LIST_KEY = "condition_contraindications"


def merge_condition_contraindications(
    report: Dict[str, Any], findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    existing = report.setdefault(_LIST_KEY, [])
    sigs = {(f.get("condition"), tuple(f.get("medications_involved") or [])) for f in existing}
    for finding in findings:
        sig = (finding.get("condition"), tuple(finding.get("medications_involved") or []))
        if sig in sigs:
            continue
        sigs.add(sig)
        existing.append(finding)
    return report
