"""
Curated Medication-Allergy Contraindication Rules (deterministic)
================================================================
A code-verifiable safety layer that runs alongside the LLM cross-check in
medical_extractor.cross_check_prescriptions(). The LLM pass is broad but
probabilistic; this module deterministically matches each medication's
normalized active ingredients against the patient's recorded allergies, so
catching "amoxicillin prescribed; penicillin allergy on record" never
depends on the model noticing on any given run — the same philosophy as
detect_exact_duplicate_medications() and drug_interactions.py.

Matching philosophy:

  * Medication side — matched on the normalized `ingredients` list the
    extractor already produces (English generic names), never on brand
    names or printed dosage text, so it is language-independent.

  * Allergy side — matched on the `known_allergies` strings from the
    timeline (free text such as "Penicillin", "Sulfa Drugs", "Brufen").
    Each allergy string is resolved to zero or more *allergen classes* by
    phrase matching against class names, class-member generics, and a
    small set of common brand names. A medication matches when any of its
    ingredients belongs to a class the allergy resolves to, or when an
    ingredient is literally named in the allergy text.

  * Negative statements ("no known allergies", "NKDA", "none") are
    recognized and never match.

Scope discipline: only allergen classes with clinically standard
cross-reactivity within the class (penicillins, cephalosporins,
sulfonamides, NSAIDs, opioids, macrolides, tetracyclines, quinolones,
ACE inhibitors) plus direct ingredient-name matches. Class-crossing
signals (e.g. penicillin -> cephalosporin cross-reactivity, which is real
but rare and disputed) and anything patient-specific are deliberately
left to the LLM pass. This is NOT a comprehensive allergy database, and
the output always carries the same "consult a professional" framing as
the rest of the report.
"""

import re
from typing import Any, Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# 1. Allergen classes — groups of generics that share a clinically
#    standard cross-reactivity within the class.
# ---------------------------------------------------------------------------

_CLASS_MEMBERS: Dict[str, Set[str]] = {
    "penicillin": {
        "penicillin", "penicillin g", "penicillin v", "benzylpenicillin",
        "amoxicillin", "ampicillin", "amoxicillin and clavulanate potassium",
        "amoxicillin and clavulanic acid", "flucloxacillin", "dicloxacillin",
        "cloxacillin", "piperacillin", "piperacillin and tazobactam",
    },
    "cephalosporin": {
        "cephalexin", "cefuroxime", "cefixime", "ceftriaxone", "cefotaxime",
        "cefpodoxime", "cefadroxil", "cefazolin", "cefdinir", "ceftazidime",
        "cefaclor",
    },
    "sulfonamide": {
        "sulfamethoxazole", "trimethoprim and sulfamethoxazole",
        "sulfamethoxazole and trimethoprim", "co-trimoxazole",
        "sulfadiazine", "sulfasalazine", "sulfisoxazole",
    },
    "nsaid": {
        "ibuprofen", "naproxen", "diclofenac", "aspirin", "ketorolac",
        "indomethacin", "celecoxib", "mefenamic acid", "piroxicam",
        "etoricoxib", "meloxicam",
    },
    "opioid": {
        "morphine", "codeine", "tramadol", "oxycodone", "hydrocodone",
        "fentanyl", "methadone", "buprenorphine", "pethidine",
        "dihydrocodeine", "hydromorphone", "tapentadol",
    },
    "macrolide": {
        "azithromycin", "clarithromycin", "erythromycin", "roxithromycin",
    },
    "tetracycline": {
        "doxycycline", "tetracycline", "minocycline", "lymecycline",
    },
    "quinolone": {
        "ciprofloxacin", "levofloxacin", "moxifloxacin", "norfloxacin",
        "ofloxacin",
    },
    "ace_inhibitor": {
        "lisinopril", "enalapril", "ramipril", "captopril", "perindopril",
        "benazepril", "quinapril",
    },
}

# ---------------------------------------------------------------------------
# 2. Allergy-text aliases per class — beyond the class name and its member
#    generics (which are always recognized), these are the words patients
#    and clinicians actually write: class name variants, abbreviations,
#    and a few common brand names.
# ---------------------------------------------------------------------------

_CLASS_ALIASES: Dict[str, Tuple[str, ...]] = {
    "penicillin": (
        "penicillin", "penicillins", "amoxicillin", "amoxil", "ampicillin",
        "augmentin", "amoxiclav",
    ),
    "cephalosporin": (
        "cephalosporin", "cephalosporins", "ceph", "cef",
    ),
    "sulfonamide": (
        "sulfa", "sulpha", "sulphonamide", "sulfonamide", "sulphonamides",
        "sulfonamides", "co-trimoxazole", "cotrimoxazole", "bactrim", "septrin",
    ),
    "nsaid": (
        "nsaid", "nsaids", "anti-inflammatory", "antiinflammatory",
        "brufen", "voltaren", "naprosyn", "advil", "motrin", "nurofen", "ponstan",
    ),
    "opioid": (
        "opioid", "opioids", "opiate", "opiates", "narcotic", "narcotics",
        "morphine", "codeine", "tramadol",
    ),
    "macrolide": (
        "macrolide", "macrolides", "azithromycin", "zithromax",
        "erythromycin", "clarithromycin", "klacid",
    ),
    "tetracycline": (
        "tetracycline", "tetracyclines", "doxycycline", "minocycline",
    ),
    "quinolone": (
        "quinolone", "quinolones", "fluoroquinolone", "fluoroquinolones",
        "ciprofloxacin", "cipro", "levofloxacin", "norfloxacin",
    ),
    "ace_inhibitor": (
        "ace inhibitor", "ace inhibitors", "lisinopril", "enalapril",
        "ramipril", "captopril", "perindopril",
    ),
}

# ---------------------------------------------------------------------------
# 3. Plain-language explanation per match kind.
# ---------------------------------------------------------------------------

_CLASS_EXPLANATIONS: Dict[str, str] = {
    "penicillin": (
        "Medications in the penicillin class are contraindicated in patients "
        "with a recorded penicillin allergy; re-exposure can trigger a severe "
        "allergic reaction, including anaphylaxis."
    ),
    "cephalosporin": (
        "Cephalosporin antibiotics carry a known risk of allergic reaction in "
        "patients with a recorded cephalosporin allergy."
    ),
    "sulfonamide": (
        "Sulfonamide ('sulfa') medications can cause severe reactions — "
        "including serious skin reactions — in patients with a recorded "
        "sulfa allergy."
    ),
    "nsaid": (
        "NSAIDs can trigger bronchospasm, angioedema, or anaphylaxis in "
        "patients with a recorded NSAID allergy."
    ),
    "opioid": (
        "Opioid medications can cause true allergic reactions (rash, "
        "anaphylaxis) in patients with a recorded opioid allergy."
    ),
    "macrolide": (
        "Macrolide antibiotics can trigger allergic reactions in patients "
        "with a recorded macrolide allergy."
    ),
    "tetracycline": (
        "Tetracycline antibiotics can trigger allergic reactions in patients "
        "with a recorded tetracycline allergy."
    ),
    "quinolone": (
        "Quinolone (fluoroquinolone) antibiotics can trigger allergic "
        "reactions in patients with a recorded quinolone allergy."
    ),
    "ace_inhibitor": (
        "ACE inhibitors can cause angioedema and other hypersensitivity "
        "reactions in patients with a recorded ACE-inhibitor allergy."
    ),
}

KB_CONFIDENCE = 0.95  # exact ingredient-class match against an established rule

# Statements that mean "no allergies" rather than naming an allergen. Only
# treated as negative when no allergen class/ingredient resolves from the
# same text, so "no known drug allergies except penicillin" still matches
# penicillin.
_NEGATIVE_MARKERS = (
    "no known allergies", "no known drug allergies",
    "no known medication allergies", "no known medicine allergies",
    "nkda", "nka", "not known", "none", "nil",
)

# ---------------------------------------------------------------------------
# 4. Matching helpers.
# ---------------------------------------------------------------------------


def _contains_phrase(text: str, phrase: str) -> bool:
    """Word-boundary phrase containment, so 'cef' never matches inside
    'cefaclor' and 'amox' never matches inside 'amoxicillin'."""
    if not phrase:
        return False
    return re.search(rf"\b{re.escape(phrase)}\b", text, flags=re.IGNORECASE) is not None


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown"


def _med_identity(med: Dict[str, Any]) -> Tuple[Any, ...]:
    """Identity key so the same prescription line repeated across documents
    never produces duplicate findings."""
    return (
        (med.get("name") or "").strip().lower(),
        med.get("date"),
        med.get("source_file"),
    )


def _resolve_allergy_classes(allergy: str) -> Set[str]:
    """Resolves one free-text allergy string to the allergen classes it
    refers to. Returns an empty set for negative statements, unknown
    substances, and empty strings."""
    if not allergy or not isinstance(allergy, str) or not allergy.strip():
        return set()
    text = allergy.strip().lower()

    resolved: Set[str] = set()
    for class_key, members in _CLASS_MEMBERS.items():
        aliases = _CLASS_ALIASES.get(class_key, ())
        named = any(_contains_phrase(text, alias) for alias in aliases)
        member_named = any(_contains_phrase(text, member) for member in members)
        if named or member_named:
            resolved.add(class_key)

    if not resolved and any(_contains_phrase(text, marker) for marker in _NEGATIVE_MARKERS):
        # A negative statement that names no allergen ("no known allergies").
        # Phrase-matched with word boundaries so a real drug name that merely
        # CONTAINS a marker (e.g. "sulfanilamide" contains "nil") is never
        # misread as a negative statement.
        return set()
    return resolved


def check_allergy_conflicts(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Scans timeline["medications_timeline"] against timeline["known_allergies"].
    Returns entries in the SAME shape as the LLM cross-check's
    allergy_conflicts items (medication, allergy, explanation, confidence),
    plus a "source" marker so the report (and UI) can distinguish
    knowledge-base findings from model inferences. Emits at most one
    finding per (allergy, medication-line) pair.
    """
    meds = timeline.get("medications_timeline", []) or []
    allergies = [
        a for a in (timeline.get("known_allergies", []) or [])
        if isinstance(a, str) and a.strip()
    ]
    if not meds or not allergies:
        return []

    findings: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, Tuple[Any, ...]]] = set()

    for allergy in allergies:
        allergy_lower = allergy.strip().lower()
        classes = _resolve_allergy_classes(allergy)

        for med in meds:
            ingredients = [str(i).strip().lower() for i in (med.get("ingredients") or [])]
            ingredients = [i for i in ingredients if i]

            class_members = {
                member for c in classes for member in _CLASS_MEMBERS.get(c, set())
            }
            class_hits = sorted(
                c for c in classes
                if any(i in _CLASS_MEMBERS[c] for i in ingredients)
            )
            direct_hits = sorted(
                i for i in ingredients
                if _contains_phrase(allergy_lower, i) and i not in class_members
            )
            if not class_hits and not direct_hits:
                continue

            pair_key = (allergy.strip().lower(), _med_identity(med))
            if pair_key in seen:
                continue
            seen.add(pair_key)

            if class_hits:
                rule_label = f"{' + '.join(class_hits)} allergy"
                explanation = " ".join(_CLASS_EXPLANATIONS[c] for c in class_hits)
                matched_ingredient = next(
                    i for i in ingredients if i in _CLASS_MEMBERS[class_hits[0]]
                )
            else:
                rule_label = "exact allergen match"
                explanation = (
                    "The medication's active ingredient is named in the "
                    "patient's recorded allergy."
                )
                matched_ingredient = direct_hits[0]

            findings.append({
                "medication": _med_display(med),
                "allergy": allergy.strip(),
                "explanation": (
                    f"Deterministic knowledge-base check ({rule_label}): "
                    f"{explanation} Matched on active ingredient "
                    f"'{matched_ingredient}'. Consult a doctor or pharmacist "
                    "before making any changes."
                ),
                "severity": "high",
                "confidence": KB_CONFIDENCE,
                "source": "curated_knowledge_base",
                "rule": rule_label,
            })
    return findings


def merge_allergy_findings(
    report: Dict[str, Any], kb_findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Merges knowledge-base allergy findings into an existing cross-check
    report (in place), skipping any finding the LLM already flagged for
    the same medication/allergy pair — the deterministic entry is only
    added when the model missed it, so the report never shows obvious
    duplicates. Two pairs count as the same when both fields are equal
    or one text contains the other (e.g. "Penicillin" vs "penicillin
    allergy").
    """
    existing = report.setdefault("allergy_conflicts", [])

    def _norm(value: Any) -> str:
        return (value or "").strip().lower()

    existing_pairs = [
        (_norm(item.get("medication")), _norm(item.get("allergy")))
        for item in existing
    ]

    def _same_pair(a: str, b: str) -> bool:
        if not a or not b:
            return a == b
        return a == b or a in b or b in a

    for finding in kb_findings:
        med = _norm(finding.get("medication"))
        allergy = _norm(finding.get("allergy"))
        duplicate = any(
            _same_pair(med, m) and _same_pair(allergy, a)
            for m, a in existing_pairs
        )
        if not duplicate:
            existing.append(finding)
            existing_pairs.append((med, allergy))
    return report
