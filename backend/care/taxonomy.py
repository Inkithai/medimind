"""Healthcare taxonomy and *explicit* specialty matching for care listings.

Google Places returns coarse types (``hospital``, ``doctor``,
``medical_clinic`` ...) plus a free-text business name. This module turns
those into one stable MediMind taxonomy and decides whether a listing is
relevant to a requested specialty.

Design rule (do not violate):
    We never infer a specialty a listing does not actually state. A
    specialty match requires either (a) a recognized Google specialist
    type, or (b) a specialty keyword appearing in the listing's own name.
    A generic "doctor" or "clinic" is presented as *specialty not listed*,
    never as a gastroenterologist.
"""

import re
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Normalized facility kinds
# ---------------------------------------------------------------------------

HOSPITAL = "hospital"
CLINIC = "clinic"
DOCTOR = "doctor"
PHARMACY = "pharmacy"
LABORATORY = "laboratory"
OTHER = "other"

ALL_KINDS = (HOSPITAL, CLINIC, DOCTOR, PHARMACY, LABORATORY, OTHER)

# Google Place ``primaryType`` / ``types`` values -> normalized kind.
_GOOGLE_TYPE_KIND: Dict[str, str] = {
    # Facilities
    "hospital": HOSPITAL,
    "general_hospital": HOSPITAL,
    "specialized_hospital": HOSPITAL,
    "medical_clinic": CLINIC,
    "medical_center": CLINIC,
    "clinic": CLINIC,
    "urgent_care": CLINIC,
    "walk_in_clinic": CLINIC,
    "mental_health_clinic": CLINIC,
    "pharmacy": PHARMACY,
    "drugstore": PHARMACY,
    "medical_lab": LABORATORY,
    "diagnostic_center": LABORATORY,
    "blood_bank": LABORATORY,
    # Individual practitioners / medical specialists -> "doctor"
    "doctor": DOCTOR,
    "family_practice_physician": DOCTOR,
    "general_practitioner": DOCTOR,
    "internist": DOCTOR,
    "physician_assistant": DOCTOR,
    "nurse_practitioner": DOCTOR,
    # Other licensed healthcare that is not a hospital/clinic/doctor/lab/pharmacy
    "eye_care": OTHER,
    "optician": OTHER,
    "optical": OTHER,
    "optometrist": OTHER,
    "dentist": OTHER,
    "dental_clinic": OTHER,
    "physical_therapist": OTHER,
    "physiotherapist": OTHER,
    "occupational_therapist": OTHER,
    "speech_pathologist": OTHER,
    "audiologist": OTHER,
    "psychologist": OTHER,
    "nutritionist": OTHER,
    "dietitian": OTHER,
    "chiropractor": OTHER,
    "acupuncturist": OTHER,
    "midwife": OTHER,
    "podiatrist": OTHER,
    "home_health_care_service": OTHER,
    "nursing_agency": OTHER,
    "hospice": OTHER,
    "ambulance": OTHER,
    "dialysis_center": OTHER,
    "rehabilitation_center": OTHER,
    "addiction_treatment_center": OTHER,
    "wellness_center": OTHER,
}

# Google specialist types that ALSO tell us the specialty outright. Mapped
# to a specialty key below. (These are still normalized to kind == "doctor"
# by the table above.)
_GOOGLE_TYPE_SPECIALTY: Dict[str, str] = {
    "cardiologist": "cardiology",
    "dermatologist": "dermatology",
    "pediatrician": "pediatrics",
    "psychiatrist": "mental_health",
    "neurologist": "neurology",
    "nephrologist": "nephrology",
    "endocrinologist": "endocrinology",
    "oncologist": "oncology",
    "pulmonologist": "pulmonology",
    "rheumatologist": "rheumatology",
    "urologist": "urology",
    "anesthesiologist": "anesthesiology",
    "radiologist": "radiology",
    "surgeon": "surgery",
    "plastic_surgeon": "surgery",
    "orthopedic_surgeon": "orthopedics",
    "obstetrician_gynecologist": "obgyn",
    "gynecologist": "obgyn",
    "dentist": "dentistry",
    "dental_clinic": "dentistry",
    "eye_care": "eye",
    "optometrist": "eye",
    "optician": "eye",
    "optical": "eye",
    "podiatrist": "podiatry",
}

# Priority used when a place has no primaryType and several recognized
# types. More specific provider kinds win over generic ones.
_KIND_PRIORITY = {DOCTOR: 0, HOSPITAL: 1, PHARMACY: 2, LABORATORY: 3, CLINIC: 4, OTHER: 5}


# ---------------------------------------------------------------------------
# Specialty catalog
# ---------------------------------------------------------------------------
#
# ``patterns`` are matched against the lower-cased listing name as regex.
# They deliberately favour multi-character stems and word boundaries to avoid
# false positives (e.g. ``\\bgastro\\b`` does not match "gastronomy").

_SPECIALTIES: Dict[str, Dict[str, object]] = {
    "gastroenterology": {
        "label": "Gastroenterology / digestive health",
        "patterns": [
            r"\bgastro\b",
            r"gastroenter",
            r"gastrointest",
            r"digestive",
            r"\bgi\b",
            r"endoscopy",
            r"colonoscopy",
            r"hepatolog",
            r"\bliver\b",
            r"\bgut\b",
        ],
    },
    "cardiology": {
        "label": "Cardiology / heart",
        "patterns": [r"cardio", r"cardiac", r"\bheart\b"],
    },
    "dermatology": {
        "label": "Dermatology / skin",
        "patterns": [r"dermatolog", r"\bskin clinic\b", r"\bskin centre\b", r"\bskin center\b"],
    },
    "pediatrics": {
        "label": "Pediatrics / children",
        "patterns": [r"pediatr", r"children'?s hospital", r"\bchild clinic\b"],
    },
    "neurology": {
        "label": "Neurology / brain & nerves",
        "patterns": [r"neurolog", r"\bbrain\b", r"\bspine\b", r"\bneuro\b"],
    },
    "orthopedics": {
        "label": "Orthopedics / bones & joints",
        "patterns": [r"orthop", r"orthopaed", r"\bbone\b", r"\bjoint\b"],
    },
    "mental_health": {
        "label": "Mental health",
        "patterns": [r"psychiatr", r"psycholog", r"mental health", r"counsell?ing"],
    },
    "dentistry": {
        "label": "Dentistry / dental",
        "patterns": [r"dental", r"dentist", r"orthodont"],
    },
    "eye": {
        "label": "Eye care / vision",
        "patterns": [r"\beye\b", r"optical", r"optician", r"optometr", r"vision"],
    },
    "obgyn": {
        "label": "Obstetrics & gynecology / women's health",
        "patterns": [r"gyn", r"obstetric", r"maternity", r"women'?s health", r"\bfertility\b"],
    },
    "internal_medicine": {
        "label": "Internal medicine / general physician",
        "patterns": [
            r"internal medicine",
            r"general physician",
            r"general practice",
            r"family medicine",
            r"family practice",
        ],
    },
    "ent": {
        "label": "ENT / ear, nose & throat",
        "patterns": [r"\bent\b", r"ear.?nose.?throat", r"otorhinolaryng"],
    },
    "oncology": {
        "label": "Oncology / cancer",
        "patterns": [r"oncolog", r"\bcancer\b"],
    },
    "nephrology": {
        "label": "Nephrology / kidney",
        "patterns": [r"nephro", r"\bkidney\b", r"\brenal\b"],
    },
    "endocrinology": {
        "label": "Endocrinology / diabetes & thyroid",
        "patterns": [r"endocrinol", r"\bdiabetes\b", r"\bthyroid\b"],
    },
    "pulmonology": {
        "label": "Pulmonology / chest & lungs",
        "patterns": [r"pulmon", r"respiratory", r"chest clinic"],
    },
    "urology": {
        "label": "Urology",
        "patterns": [r"\burolog"],
    },
    "rheumatology": {
        "label": "Rheumatology",
        "patterns": [r"rheumatolog"],
    },
}

SPECIALTY_KEYS = frozenset(_SPECIALTIES)

# Public catalog served by GET /api/v1/care/specialties.
SPECIALTY_CATALOG: List[Dict[str, object]] = [
    {"key": key, "label": spec["label"]}  # type: ignore[index]
    for key, spec in _SPECIALTIES.items()
]

_COMPILED_PATTERNS = {
    key: [re.compile(pattern, re.IGNORECASE) for pattern in spec["patterns"]]
    for key, spec in _SPECIALTIES.items()
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def kind_label(kind: str) -> str:
    labels = {
        HOSPITAL: "Hospital",
        CLINIC: "Clinic",
        DOCTOR: "Doctor",
        PHARMACY: "Pharmacy",
        LABORATORY: "Laboratory",
        OTHER: "Other healthcare",
    }
    return labels.get(kind, "Healthcare")


def specialty_label(key: str) -> Optional[str]:
    spec = _SPECIALTIES.get(key)
    return spec["label"] if spec else None  # type: ignore[return-value]


def classify(
    primary_type: Optional[str],
    google_types: Optional[List[str]],
    name: str,
) -> Optional[Dict[str, object]]:
    """Classify a Google Place into the MediMind taxonomy.

    Returns ``None`` when the place is not a recognized healthcare entity at
    all (a university committee, a government department, etc.) so the caller
    can drop it instead of showing it as a doctor or clinic.
    """
    types_list = google_types if isinstance(google_types, list) else []

    kind: Optional[str] = None
    if isinstance(primary_type, str):
        kind = _GOOGLE_TYPE_KIND.get(primary_type)
    if kind is None:
        recognized = [_GOOGLE_TYPE_KIND[t] for t in types_list if t in _GOOGLE_TYPE_KIND]
        if recognized:
            kind = min(recognized, key=lambda k: _KIND_PRIORITY.get(k, 99))
    if kind is None:
        return None

    # Explicit specialties only — derived from a Google specialist type or
    # from the listing's own name. Never from the query or from "doctor".
    specialties: List[str] = []
    for gtype in types_list:
        spec_key = _GOOGLE_TYPE_SPECIALTY.get(gtype)
        if spec_key and spec_key not in specialties:
            specialties.append(spec_key)
    name_lc = (name or "").lower()
    for spec_key, patterns in _COMPILED_PATTERNS.items():
        if spec_key in specialties:
            continue
        if any(pattern.search(name_lc) for pattern in patterns):
            specialties.append(spec_key)

    entity_type = "practitioner" if kind == DOCTOR else "facility"

    return {
        "kind": kind,
        "entity_type": entity_type,
        "primary_type": primary_type if isinstance(primary_type, str) else None,
        "specialties": specialties,
    }


# Match tiers — lower ranks first in results.
TIER_EXACT = 0
TIER_PHYSICIAN = 1
TIER_HOSPITAL = 2
TIER_GENERAL = 3
TIER_UNRELATED = 4

# Grouped match level used by the UI to separate true matches from
# nearby alternatives and clearly-different specialties.
LEVEL_EXACT = "exact"
LEVEL_RELATED = "related"
LEVEL_OTHER = "other"


def score_match(
    kind: str,
    specialties: List[str],
    specialty_key: Optional[str],
) -> Optional[Tuple[int, str, str]]:
    """Score a classified listing against a requested specialty.

    Returns ``(tier, human_reason, match_level)`` or ``None`` when no
    specialty was requested (every listing is then a generic nearby result).

    We never claim a specialty the listing does not state: an exact match
    requires the requested specialty in the listing's own name/type. A
    generic doctor/hospital/clinic is shown as a *related* alternative with
    a reason such as "specialty not stated", and a listing that names a
    *different* specialty is marked as "other".
    """
    if not specialty_key:
        return None

    label = specialty_label(specialty_key) or specialty_key

    if specialty_key in specialties:
        return TIER_EXACT, f"{label} is mentioned in this listing", LEVEL_EXACT

    competing = [s for s in specialties if s != specialty_key]
    if competing:
        other_label = specialty_label(competing[0]) or competing[0]
        return TIER_UNRELATED, f"{other_label} — a different specialty", LEVEL_OTHER

    if kind == DOCTOR:
        return TIER_PHYSICIAN, "Doctor — specialty not stated in this listing", LEVEL_RELATED
    if kind == HOSPITAL:
        return TIER_HOSPITAL, f"Hospital — ask whether it has a {label} department", LEVEL_RELATED
    return TIER_GENERAL, "General healthcare listing — specialty not stated", LEVEL_RELATED
