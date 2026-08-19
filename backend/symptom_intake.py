"""
Patient Symptom Intake & Cross-Record Reasoning (deterministic)
================================================================
MediMind is document-centric. This module adds the missing patient-facing
input: a patient-reported symptom (free text + duration), which it then
CROSS-REFERENCES against the patient's own extracted record to surface
relevant context — medications that can be associated with that symptom,
related conditions already on record, and recent abnormal lab results.

It is explicitly NOT a diagnosis engine. It never states that a medicine
caused the symptom. It produces a short, neutral "context to discuss with your
clinician" summary: "you reported X; your record also shows Y and Z, which are
relevant to that symptom." The clinician makes the judgement.

Matching is deterministic keyword → drug-class / lab mapping, on the same
normalized ingredient list the rest of the pipeline uses.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from clinical_lab_values import collect_lab_values, flagged_high, flagged_low

try:
    from drug_interactions import _CLASS_MEMBERS
except Exception:  # pragma: no cover
    _CLASS_MEMBERS = {}

# symptom key -> (display, keyword phrases to match in patient text)
_SYMPTOMS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "dizziness": (
        "dizziness or light-headedness",
        ("dizz", "lighthead", "light-headed", "faint", "woozy"),
    ),
    "bleeding_bruising": (
        "unusual bleeding or bruising",
        ("bleed", "bruis", "nosebleed", "blood in"),
    ),
    "muscle_pain": ("muscle aches or weakness", ("muscle", "myalgia", "weakness", "cramp")),
    "nausea_vomiting": ("nausea or vomiting", ("nausea", "vomit", "throwing up", "sick to")),
    "dry_cough": ("persistent dry cough", ("cough",)),
    "swelling": ("swelling", ("swell", "oedema", "edema", "puffy")),
    "shortness_of_breath": (
        "shortness of breath",
        ("shortness of breath", "breathless", "can't breathe", "wheeze"),
    ),
    "fatigue": (
        "unusual tiredness / fatigue",
        ("tired", "fatigue", "exhaust", "no energy", "letharg"),
    ),
    "increased_thirst_urination": (
        "increased thirst or urination",
        ("thirst", "urinat", "pee", "drinking a lot"),
    ),
    "abdominal_pain": ("abdominal pain", ("abdom", "stomach pain", "tummy", "belly")),
    "headache": ("headache", ("headache", "head pain", "migraine")),
    "rash": ("skin rash", ("rash", "itch", "hives")),
    "constipation": ("constipation", ("constipat", "hard stools", "unable to pass")),
    "diarrhoea": ("diarrhoea", ("diarrh", "loose stool", "runny stool")),
    "neuropathy": ("numbness or tingling", ("numb", "tingl", "pins and needles", "neuropathy")),
    "palpitations": (
        "palpitations / racing heartbeat",
        ("palpitat", "racing heart", "fast heartbeat", "flutter"),
    ),
    "joint_pain": ("joint pain", ("joint pain", "arthralgia", "joint ache", "stiff joints")),
    "frequent_infections": (
        "frequent infections",
        (
            "frequent infection",
            "repeated infection",
            "recurrent infection",
            "keep getting sick",
            "getting infections",
        ),
    ),
    "chest_pain": ("chest pain or tightness", ("chest pain", "chest tight", "pressure in chest")),
    "urinary_symptoms": (
        "urinary symptoms",
        ("burning urine", "painful urinat", "blood in urine", "frequent urinat"),
    ),
    "vision_changes": ("vision changes", ("blurred vision", "vision change", "double vision")),
}

# symptom -> drug classes/ingredients that are RELEVANT (can be associated).
# Neutral: "is relevant", never "is the cause".
_RELEVANT_DRUGS: Dict[str, Dict[str, Any]] = {
    "dizziness": {
        "classes": ("ace_inhibitor", "arb"),
        "ingredients": {"amlodipine", "furosemide", "doxazosin", "tamsulosin"},
    },
    "bleeding_bruising": {
        "classes": ("anticoagulant", "nsaid", "ssri"),
        "ingredients": {"clopidogrel"},
    },
    "muscle_pain": {
        "classes": ("cyp3a4_statin",),
        "ingredients": {"simvastatin", "atorvastatin", "rosuvastatin"},
    },
    "nausea_vomiting": {
        "classes": (),
        "ingredients": {"metformin", "digoxin", "tramadol", "morphine", "erythromycin"},
    },
    "dry_cough": {"classes": ("ace_inhibitor",), "ingredients": set()},
    "swelling": {"classes": ("nsaid",), "ingredients": {"amlodipine", "nifedipine"}},
    "shortness_of_breath": {
        "classes": (),
        "ingredients": {"propranolol", "atenolol", "metoprolol", "carvedilol"},
    },
    "fatigue": {"classes": (), "ingredients": {"metoprolol", "atenolol", "bisoprolol"}},
    "increased_thirst_urination": {"classes": (), "ingredients": set()},
    "headache": {"classes": (), "ingredients": set()},
    "rash": {
        "classes": (),
        "ingredients": {"amoxicillin", "ampicillin", "allopurinol", "sulfamethoxazole"},
    },
    "abdominal_pain": {"classes": ("nsaid",), "ingredients": {"metformin"}},
    "constipation": {
        "classes": (),
        "ingredients": {
            "codeine",
            "morphine",
            "tramadol",
            "oxycodone",
            "amitriptyline",
            "nortriptyline",
            "verapamil",
            "diltiazem",
            "iron",
            "ferrous",
            "aluminium hydroxide",
        },
    },
    "diarrhoea": {
        "classes": (),
        "ingredients": {
            "metformin",
            "clarithromycin",
            "amoxicillin",
            "azithromycin",
            "omeprazole",
            "esomeprazole",
            "magnesium hydroxide",
        },
    },
    "neuropathy": {
        "classes": (),
        "ingredients": {
            "metformin",
            "phenytoin",
            "isoniazid",
            "vincristine",
            "amiodarone",
            "hydroxychloroquine",
        },
    },
    "palpitations": {
        "classes": (),
        "ingredients": {
            "salbutamol",
            "salmetarol",
            "salmeterol",
            "terbutaline",
            "levothyroxine",
            "thyroxine",
            "theophylline",
            "amlodipine",
        },
    },
    "joint_pain": {
        "classes": ("cyp3a4_statin",),
        "ingredients": {
            "simvastatin",
            "atorvastatin",
            "rosuvastatin",
            "furosemide",
            "hydrochlorothiazide",
        },
    },
    "frequent_infections": {
        "classes": (),
        "ingredients": {
            "prednisolone",
            "prednisone",
            "dexamethasone",
            "hydrocortisone",
            "methylprednisolone",
            "azathioprine",
            "methotrexate",
            "ciclosporin",
            "tacrolimus",
            "mycophenolate",
        },
    },
    "chest_pain": {
        "classes": (),
        "ingredients": {
            "sumatriptan",
            "rizatriptan",
            "salbutamol",
            "sildenafil",
            "tadalafil",
            "vardenafil",
            "levothyroxine",
            "erythropoietin",
        },
    },
    "urinary_symptoms": {
        "classes": (),
        "ingredients": {"nitrofurantoin", "trimethoprim", "ciprofloxacin"},
    },
    "vision_changes": {
        "classes": (),
        "ingredients": {
            "amiodarone",
            "hydroxychloroquine",
            "sildenafil",
            "tadalafil",
            "topiramate",
            "prednisolone",
            "prednisone",
        },
    },
}

# symptom -> documented conditions relevant to that symptom (cross-reference only).
_RELEVANT_CONDITIONS: Dict[str, List[str]] = {
    "chest_pain": ["heart", "angina", "coronary", "ischaem", "ischem"],
    "shortness_of_breath": ["asthma", "copd", "heart failure", "cardiac failure", "pulmonary"],
    "swelling": [
        "heart failure",
        "cardiac failure",
        "chronic kidney",
        "renal failure",
        "cirrhosis",
        "liver",
    ],
    "increased_thirst_urination": ["diabetes"],
    "fatigue": ["diabetes", "hypothyroid", "anaemia", "anemia", "heart failure", "depression"],
    "dizziness": ["hypertension", "diabetes", "arrhythmia", "atrial fibrillation"],
    "palpitations": ["atrial fibrillation", "arrhythmia", "hyperthyroid", "thyroid"],
    "constipation": ["hypothyroid", "diabetes"],
    "neuropathy": ["diabetes"],
    "frequent_infections": ["diabetes", "chronic kidney"],
}

# symptom -> lab analytes relevant to that symptom (for cross-reference)
_RELEVANT_LABS: Dict[str, List[str]] = {
    "dizziness": ["sodium", "potassium"],
    "fatigue": ["hemoglobin", "potassium", "sodium", "glucose"],
    "bleeding_bruising": ["platelet", "hemoglobin", "inr"],
    "muscle_pain": ["alt", "ast"],
    "increased_thirst_urination": ["glucose"],
    "shortness_of_breath": ["hemoglobin"],
    "constipation": ["calcium", "sodium"],
    "neuropathy": ["glucose"],
    "palpitations": ["potassium"],
}


def _match_symptom(text: str) -> List[str]:
    t = (text or "").lower()
    return [key for key, (_, phrases) in _SYMPTOMS.items() if any(p in t for p in phrases)]


def _relevant_conditions_for(key: str, conditions: List[str]) -> List[str]:
    """Documented conditions relevant to a symptom (substring match on the
    condition-relevance phrases). Returns the matching condition display names."""
    phrases = _RELEVANT_CONDITIONS.get(key, [])
    if not phrases or not conditions:
        return []
    matched: List[str] = []
    for cond in conditions:
        cl = (cond or "").lower()
        if any(p in cl for p in phrases) and cond not in matched:
            matched.append(cond)
    return matched


def _med_relevant(med: Dict[str, Any], spec: Dict[str, Any]) -> bool:
    ing = {str(i).strip().lower() for i in (med.get("ingredients") or []) if str(i).strip()}
    if ing & spec["ingredients"]:
        return True
    return any(ing & _CLASS_MEMBERS.get(c, set()) for c in spec["classes"])


def _relevant_lab_signal(timeline: Dict[str, Any], analyte: str) -> Optional[str]:
    lv = collect_lab_values(timeline, [analyte]).get(analyte)
    if lv is None or lv.value is None:
        return None
    if flagged_high(lv) or flagged_low(lv):
        return f"{lv.analyte} {lv.value:g} {lv.unit or ''}".strip() + f" (flagged {lv.flag})"
    return None


def analyse_symptom(
    timeline: Dict[str, Any],
    symptom_text: str,
    duration: Optional[str] = None,
) -> Dict[str, Any]:
    """Cross-reference a patient-reported symptom against their record."""
    keys = _match_symptom(symptom_text)
    meds = list(timeline.get("medications_timeline") or [])
    conditions = [
        str(e.get("name"))
        for e in (timeline.get("diagnoses_timeline") or [])
        if isinstance(e, dict) and e.get("name")
    ]
    findings: List[Dict[str, Any]] = []
    for key in keys:
        display = _SYMPTOMS[key][0]
        rel_meds = [
            _med_display(m)
            for m in meds
            if _med_relevant(m, _RELEVANT_DRUGS.get(key, {"classes": (), "ingredients": set()}))
        ]
        rel_labs: List[str] = []
        for analyte in _RELEVANT_LABS.get(key, []):
            sig = _relevant_lab_signal(timeline, analyte)
            if sig:
                rel_labs.append(sig)
        rel_conds = _relevant_conditions_for(key, conditions)
        findings.append(
            {
                "symptom": display,
                "relevant_medications_on_record": rel_meds,
                "relevant_abnormal_labs": rel_labs,
                "relevant_conditions_on_record": rel_conds,
            }
        )
    if not findings:
        return {
            "analysed": False,
            "note": (
                "No standard symptom keyword was recognised in what you entered, so the "
                "record was not cross-referenced. Describe the symptom in your own words "
                "(e.g. 'dizzy', 'muscle pain', 'cough', 'rash') and try again."
            ),
        }
    summary_lines: List[str] = []
    for f in findings:
        parts = [f"You reported: {f['symptom']}"]
        if duration:
            parts.append(f"(duration: {duration})")
        if f["relevant_medications_on_record"]:
            parts.append(
                "Your record includes medicines that can be associated with this symptom: "
                + ", ".join(f["relevant_medications_on_record"])
            )
        if f["relevant_abnormal_labs"]:
            parts.append(
                "Your recent lab results include abnormal readings relevant to this symptom: "
                + ", ".join(f["relevant_abnormal_labs"])
            )
        if f.get("relevant_conditions_on_record"):
            parts.append(
                "Your record also lists conditions that can be associated with this symptom: "
                + ", ".join(f["relevant_conditions_on_record"])
            )
        parts.append(
            "This is context to discuss with your clinician — it is not a diagnosis, and the "
            "medicines above are not necessarily the cause."
        )
        summary_lines.append(" ".join(parts))
    return {
        "analysed": True,
        "matched_symptoms": [f["symptom"] for f in findings],
        "findings": findings,
        "summary": "\n\n".join(summary_lines),
    }


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown medication"
