"""Evidence-graded specialty suggestion for care navigation.

Core safety principle
=====================
Low-confidence or ambiguous evidence must REDUCE the specificity of what
MediMind surfaces, never increase it:

    weak / ambiguous evidence   -> NO specific specialty
                                   (offer General Medicine as a broad
                                   search option, not a recommendation)
    moderate evidence           -> a POSSIBLE directory-search category,
                                   explicitly not a recommendation,
                                   user chooses
    strong, explicit evidence   -> a possible relevant specialty may be
                                   surfaced, still never medical advice

A single isolated word such as "digest" is weak evidence and must never
produce "Gastroenterology". An explicit documented referral ("referred to
gastroenterology") is strong evidence and may surface that specialty as a
possible search category — still with user confirmation and never as a
claim that the user *needs* that specialist.

The output is a *directory-search category*, not a diagnosis, referral,
or medical recommendation, and the wording constants below keep it that
way. Do not add imperative phrasing ("you need", "go to", "we recommend")
to any string in this module.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Documents below this extraction confidence cannot contribute anything
# stronger than weak evidence (mirrors document_filter.LOW_CONFIDENCE_THRESHOLD).
LOW_CONFIDENCE = 0.35
# Documents need at least this confidence for their signals to count fully.
FULL_CONFIDENCE = 0.6

GENERAL_MEDICINE = "General Medicine"

# Per-specialty signal vocabulary.
#   strong:   explicit diagnoses/procedures that clearly belong to the specialty
#   moderate: clinically meaningful symptoms — one alone is not enough
#   weak:     ambiguous fragments ("digest", "stomach") — NEVER sufficient
# topic: plain-language description used in user-facing explanations.
_SPECIALTY_SIGNALS: Dict[str, Dict[str, Any]] = {
    "Gastroenterology": {
        "topic": "digestive health",
        "strong": [
            "gastritis", "peptic ulcer", "gastric ulcer", "duodenal ulcer",
            "ulcerative colitis", "crohn", "hepatitis", "cirrhosis",
            "gerd", "gastroesophageal reflux", "irritable bowel",
            "gi bleed", "gastrointestinal bleed", "endoscopy", "colonoscopy",
            "pancreatitis", "gallstone", "celiac", "coeliac",
        ],
        "moderate": [
            "abdominal pain", "stomach pain", "epigastric pain",
            "chronic diarrhea", "chronic diarrhoea", "persistent diarrhea",
            "persistent diarrhoea", "blood in stool", "melena", "melaena",
            "heartburn", "acid reflux", "persistent vomiting",
            "difficulty swallowing", "dysphagia", "jaundice",
        ],
        "weak": ["digest", "digestive", "digestion", "stomach", "gastro", "gastric", "bowel", "gut", "indigestion"],
    },
    "Cardiology": {
        "topic": "heart health",
        "strong": [
            "myocardial infarction", "heart attack", "atrial fibrillation",
            "heart failure", "coronary artery disease", "angina",
            "arrhythmia", "cardiomyopathy", "echocardiogram", "angiogram",
        ],
        "moderate": [
            "chest pain", "palpitations", "shortness of breath on exertion",
            "irregular heartbeat", "elevated troponin",
        ],
        "weak": ["heart", "cardiac", "cardio"],
    },
    "Nephrology": {
        "topic": "kidney health",
        "strong": [
            "chronic kidney disease", "renal failure", "kidney failure",
            "dialysis", "glomerulonephritis", "nephrotic",
        ],
        "moderate": ["elevated creatinine", "proteinuria", "reduced egfr", "kidney stone"],
        "weak": ["kidney", "renal"],
    },
    "Endocrinology": {
        "topic": "hormonal and metabolic health",
        "strong": [
            "diabetes mellitus", "type 1 diabetes", "type 2 diabetes",
            "hyperthyroid", "hypothyroid", "thyroiditis", "goitre", "goiter",
            "hba1c elevated",
        ],
        "moderate": ["elevated blood sugar", "high hba1c", "abnormal thyroid", "elevated tsh"],
        "weak": ["sugar", "thyroid", "hormone"],
    },
    "Pulmonology": {
        "topic": "respiratory health",
        "strong": ["asthma", "copd", "chronic obstructive pulmonary", "pulmonary fibrosis", "tuberculosis", "spirometry"],
        "moderate": ["chronic cough", "persistent cough", "wheezing", "hemoptysis", "haemoptysis"],
        "weak": ["lung", "breath", "respiratory", "cough"],
    },
    "Neurology": {
        "topic": "neurological health",
        "strong": ["epilepsy", "seizure disorder", "stroke", "parkinson", "multiple sclerosis", "neuropathy"],
        "moderate": ["recurrent headache", "chronic migraine", "numbness", "tremor", "seizure"],
        "weak": ["head", "nerve", "brain"],
    },
    "Dermatology": {
        "topic": "skin health",
        "strong": ["psoriasis", "eczema", "atopic dermatitis", "melanoma", "skin biopsy"],
        "moderate": ["persistent rash", "chronic itching", "skin lesion", "changing mole"],
        "weak": ["skin", "rash", "itch"],
    },
}

# Explicit referral phrasing is the strongest signal a record can carry.
_REFERRAL_PATTERNS: Dict[str, re.Pattern] = {
    specialty: re.compile(
        r"refer(?:red|ral|s)?\s+(?:\w+\s+){0,3}?" + stem, re.IGNORECASE
    )
    for specialty, stem in {
        "Gastroenterology": r"gastroenterolog",
        "Cardiology": r"cardiolog",
        "Nephrology": r"nephrolog",
        "Endocrinology": r"endocrinolog",
        "Pulmonology": r"(?:pulmonolog|chest\s+clinic)",
        "Neurology": r"neurolog",
        "Dermatology": r"dermatolog",
    }.items()
}

EVIDENCE_NONE = "none"
EVIDENCE_WEAK = "weak"
EVIDENCE_MODERATE = "moderate"
EVIDENCE_STRONG = "strong"

DISCLAIMER = (
    "This is a directory-search aid, not a diagnosis, medical recommendation, "
    "or referral. If you are unsure, consider discussing your records with a "
    "qualified healthcare professional."
)

GENERAL_MEDICINE_NOTE = (
    "General Medicine is a broad search option, not a medical recommendation."
)


@dataclass
class SpecialtySuggestion:
    """What the Find Care page may show about specialty."""

    evidence_level: str
    specialty: Optional[str]
    headline: str
    explanation: str
    search_options: List[str] = field(default_factory=list)
    hint: Optional[str] = None
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        return {
            "evidence_level": self.evidence_level,
            "specialty": self.specialty,
            "headline": self.headline,
            "explanation": self.explanation,
            "search_options": self.search_options,
            "hint": self.hint,
            "disclaimer": self.disclaimer,
        }


def _visit_confidence(visit: Dict[str, Any]) -> float:
    value = visit.get("overall_confidence")
    if isinstance(value, (int, float)) and 0.0 <= float(value) <= 1.0:
        return float(value)
    # Unknown confidence is treated cautiously, not optimistically.
    return 0.5


def _visit_text(visit: Dict[str, Any]) -> str:
    parts: List[str] = []
    for key in ("clinical_notes", "document_type", "provider_or_doctor"):
        value = visit.get(key)
        if isinstance(value, str):
            parts.append(value)
    for lab in visit.get("lab_results") or []:
        if isinstance(lab, dict):
            name = lab.get("test_name") or lab.get("name")
            if isinstance(name, str):
                parts.append(name)
    return " ".join(parts).lower()


def _count_terms(text: str, terms: List[str]) -> List[str]:
    found = []
    for term in terms:
        if term in text:
            found.append(term)
    return found


def suggest_specialty(visits: List[Dict[str, Any]]) -> SpecialtySuggestion:
    """Grade the evidence in a patient's extracted records.

    Evidence gathered from a low-confidence document (< LOW_CONFIDENCE) is
    capped at weak no matter how specific the wording looks — OCR noise
    must not become a specialist suggestion.
    """
    # score per specialty: {"strong": set, "moderate": set, "weak": set}
    evidence: Dict[str, Dict[str, set]] = {
        name: {"strong": set(), "moderate": set(), "weak": set()} for name in _SPECIALTY_SIGNALS
    }
    referral_for: set = set()

    for visit in visits or []:
        if not isinstance(visit, dict):
            continue
        text = _visit_text(visit)
        if not text:
            continue
        confidence = _visit_confidence(visit)
        low_confidence_doc = confidence < LOW_CONFIDENCE

        for specialty, pattern in _REFERRAL_PATTERNS.items():
            if pattern.search(text) and not low_confidence_doc:
                referral_for.add(specialty)

        for specialty, signals in _SPECIALTY_SIGNALS.items():
            strong_hits = _count_terms(text, signals["strong"])
            moderate_hits = _count_terms(text, signals["moderate"])
            weak_hits = _count_terms(text, signals["weak"])
            if low_confidence_doc:
                # Everything from a low-confidence document is weak evidence.
                for hit in strong_hits + moderate_hits + weak_hits:
                    evidence[specialty]["weak"].add(hit)
                continue
            if confidence < FULL_CONFIDENCE:
                # Mid-confidence documents: strong terms count as moderate,
                # moderate terms count as weak.
                for hit in strong_hits:
                    evidence[specialty]["moderate"].add(hit)
                for hit in moderate_hits + weak_hits:
                    evidence[specialty]["weak"].add(hit)
                continue
            for hit in strong_hits:
                evidence[specialty]["strong"].add(hit)
            for hit in moderate_hits:
                evidence[specialty]["moderate"].add(hit)
            for hit in weak_hits:
                evidence[specialty]["weak"].add(hit)

    # Grade each specialty.
    graded: Dict[str, str] = {}
    for specialty, buckets in evidence.items():
        if specialty in referral_for or buckets["strong"]:
            graded[specialty] = EVIDENCE_STRONG
        elif len(buckets["moderate"]) >= 2:
            graded[specialty] = EVIDENCE_MODERATE
        elif buckets["moderate"] or buckets["weak"]:
            graded[specialty] = EVIDENCE_WEAK
        else:
            graded[specialty] = EVIDENCE_NONE

    strong = [s for s, level in graded.items() if level == EVIDENCE_STRONG]
    moderate = [s for s, level in graded.items() if level == EVIDENCE_MODERATE]
    weak = [s for s, level in graded.items() if level == EVIDENCE_WEAK]

    if strong:
        # Conflicting strong evidence for many specialties is unusual;
        # surface the first deterministically but list all as options.
        primary = sorted(strong)[0]
        topic = _SPECIALTY_SIGNALS[primary]["topic"]
        return SpecialtySuggestion(
            evidence_level=EVIDENCE_STRONG,
            specialty=primary,
            headline=f"Possible relevant specialty: {primary}",
            explanation=(
                f"The uploaded records explicitly reference {topic} findings "
                f"(for example a documented diagnosis or referral). MediMind "
                f"surfaces {primary} only as a possible directory-search "
                f"category — it is not a diagnosis or a confirmed medical need. "
                f"Verify with your clinician before acting on it."
            ),
            search_options=_options(sorted(strong)),
            hint=GENERAL_MEDICINE_NOTE,
        )

    if len(moderate) == 1:
        primary = moderate[0]
        topic = _SPECIALTY_SIGNALS[primary]["topic"]
        return SpecialtySuggestion(
            evidence_level=EVIDENCE_MODERATE,
            specialty=primary,
            headline=f"Possible specialty match: {primary}",
            explanation=(
                f"The uploaded records contain several terms related to {topic}. "
                f"MediMind identified {primary} as a possible directory-search "
                f"category, not as a diagnosis or confirmed medical need. "
                f"Starting with General Medicine is also reasonable."
            ),
            search_options=_options([primary]),
            hint=GENERAL_MEDICINE_NOTE,
        )

    if len(moderate) > 1:
        # Conflicting moderate evidence — reduce specificity, don't pick one.
        return SpecialtySuggestion(
            evidence_level=EVIDENCE_WEAK,
            specialty=None,
            headline="No specific specialty identified",
            explanation=(
                "The uploaded records contain signals pointing to more than one "
                "possible specialty, which is not sufficient to single one out. "
                "Not sure which specialist you need? Start with General Medicine."
            ),
            search_options=_options(sorted(moderate)),
            hint=GENERAL_MEDICINE_NOTE,
        )

    if weak:
        primary = sorted(weak)[0]
        topic = _SPECIALTY_SIGNALS[primary]["topic"]
        return SpecialtySuggestion(
            evidence_level=EVIDENCE_WEAK,
            specialty=None,
            headline="No specific specialty identified",
            explanation=(
                f"MediMind found a low-confidence {topic}-related term in the "
                f"uploaded record. This information alone is not sufficient to "
                f"determine which medical specialty is appropriate. "
                f"Not sure which specialist you need? Start with General Medicine."
            ),
            search_options=_options(sorted(weak)),
            hint=GENERAL_MEDICINE_NOTE,
        )

    return SpecialtySuggestion(
        evidence_level=EVIDENCE_NONE,
        specialty=None,
        headline="No specialty signals found",
        explanation=(
            "The uploaded records do not contain signals that map to a "
            "particular specialty search category. You can search all "
            "publicly listed healthcare locations, or start with General Medicine."
        ),
        search_options=[GENERAL_MEDICINE, "Other specialty", "I'm not sure"],
        hint=GENERAL_MEDICINE_NOTE,
    )


def _options(specialties: List[str]) -> List[str]:
    options = [GENERAL_MEDICINE]
    options.extend(s for s in specialties if s != GENERAL_MEDICINE)
    options.extend(["Other specialty", "I'm not sure"])
    return options
