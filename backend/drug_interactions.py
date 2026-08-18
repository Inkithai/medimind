"""
Curated Drug-Interaction Knowledge Base (deterministic)
=======================================================
A code-verifiable safety layer that runs alongside the LLM cross-check in
medical_extractor.cross_check_prescriptions(). The LLM pass is broad but
probabilistic; this module flags a small set of WELL-ESTABLISHED,
textbook-level interaction pairs deterministically, so catching them never
depends on the model noticing on any given run — the same philosophy as
detect_exact_duplicate_medications().

Matching is done on the normalized `ingredients` list the extractor already
produces (English generic names), never on brand names or printed dosage
text, so it is language-independent.

Scope discipline: only pairings with unambiguous, widely documented risk
are included, each with a fixed severity and plain-language explanation.
Anything dose-dependent, speculative, or patient-specific is deliberately
left to the LLM pass. This is NOT a comprehensive interaction database and
the output always carries the same "consult a professional" framing as the
rest of the report.
"""

from typing import Any, Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# 1. Ingredient classes — groups of generics that share an interaction
#    mechanism, so one rule covers every member without listing each pair.
# ---------------------------------------------------------------------------

_CLASS_MEMBERS: Dict[str, Set[str]] = {
    "nsaid": {
        "ibuprofen", "naproxen", "diclofenac", "aspirin", "ketorolac",
        "indomethacin", "celecoxib", "mefenamic acid", "piroxicam", "etoricoxib",
    },
    "anticoagulant": {
        "warfarin", "apixaban", "rivaroxaban", "dabigatran", "edoxaban",
        "heparin", "enoxaparin",
    },
    "ace_inhibitor": {
        "lisinopril", "enalapril", "ramipril", "captopril", "perindopril",
        "benazepril", "quinapril",
    },
    "arb": {
        "losartan", "valsartan", "telmisartan", "candesartan", "irbesartan",
        "olmesartan",
    },
    "potassium_sparing_diuretic": {
        "spironolactone", "eplerenone", "amiloride", "triamterene",
    },
    "nitrate": {
        "nitroglycerin", "glyceryl trinitrate", "isosorbide dinitrate",
        "isosorbide mononitrate",
    },
    "pde5_inhibitor": {"sildenafil", "tadalafil", "vardenafil", "avanafil"},
    "ssri": {
        "sertraline", "fluoxetine", "paroxetine", "escitalopram",
        "citalopram", "fluvoxamine",
    },
    "triptan": {"sumatriptan", "rizatriptan", "zolmitriptan", "eletriptan"},
    "macrolide": {"clarithromycin", "erythromycin"},
    "cyp3a4_statin": {"simvastatin", "atorvastatin", "lovastatin"},
    "fluoroquinolone": {
        "ciprofloxacin", "levofloxacin", "moxifloxacin", "norfloxacin",
        "ofloxacin",
    },
    "sulfonylurea": {
        "glimepiride", "gliclazide", "glibenclamide", "glyburide", "glipizide",
    },
    "potassium_supplement": {"potassium chloride", "potassium citrate"},
}

# ---------------------------------------------------------------------------
# 2. Interaction rules. Each side names either a class key above or a single
#    generic ingredient. severity: low | moderate | high (same scale the LLM
#    report uses).
# ---------------------------------------------------------------------------

_RULES: List[Tuple[str, str, str, str]] = [
    ("anticoagulant", "nsaid", "high",
     "Combining an anticoagulant (blood thinner) with an NSAID significantly "
     "increases the risk of serious bleeding, including gastrointestinal bleeding."),
    ("methotrexate", "nsaid", "high",
     "NSAIDs can reduce the elimination of methotrexate, which can lead to "
     "methotrexate toxicity (bone marrow suppression, kidney injury)."),
    ("methotrexate", "trimethoprim", "high",
     "Trimethoprim and methotrexate are both folate antagonists; together they "
     "can cause severe bone marrow suppression."),
    ("nitrate", "pde5_inhibitor", "high",
     "Nitrates combined with PDE5 inhibitors (e.g. sildenafil) can cause a "
     "severe, potentially life-threatening drop in blood pressure."),
    ("warfarin", "metronidazole", "high",
     "Metronidazole inhibits warfarin metabolism, which can markedly raise INR "
     "and bleeding risk."),
    ("ace_inhibitor", "potassium_sparing_diuretic", "moderate",
     "ACE inhibitors with potassium-sparing diuretics can raise blood potassium "
     "to dangerous levels (hyperkalemia)."),
    ("arb", "potassium_sparing_diuretic", "moderate",
     "ARBs with potassium-sparing diuretics can raise blood potassium to "
     "dangerous levels (hyperkalemia)."),
    ("ace_inhibitor", "potassium_supplement", "moderate",
     "ACE inhibitors reduce potassium excretion; adding a potassium supplement "
     "can cause hyperkalemia."),
    ("potassium_sparing_diuretic", "potassium_supplement", "moderate",
     "A potassium-sparing diuretic plus a potassium supplement can cause "
     "hyperkalemia."),
    ("ssri", "tramadol", "moderate",
     "SSRIs combined with tramadol increase the risk of serotonin syndrome and "
     "can lower the seizure threshold."),
    ("ssri", "triptan", "moderate",
     "SSRIs combined with triptans carry a risk of serotonin syndrome."),
    ("ssri", "nsaid", "moderate",
     "SSRIs impair platelet function; with an NSAID this increases the risk of "
     "gastrointestinal bleeding."),
    ("macrolide", "cyp3a4_statin", "moderate",
     "Macrolide antibiotics inhibit the metabolism of these statins, raising "
     "the risk of muscle toxicity (myopathy/rhabdomyolysis)."),
    ("macrolide", "digoxin", "moderate",
     "Macrolides can increase digoxin levels, risking digoxin toxicity."),
    ("ace_inhibitor", "lithium", "moderate",
     "ACE inhibitors reduce lithium clearance and can cause lithium toxicity."),
    ("nsaid", "lithium", "moderate",
     "NSAIDs reduce lithium clearance and can cause lithium toxicity."),
    ("fluoroquinolone", "sulfonylurea", "moderate",
     "Fluoroquinolones can potentiate sulfonylureas, increasing the risk of "
     "severe hypoglycemia."),
    ("fluoroquinolone", "theophylline", "moderate",
     "Some fluoroquinolones inhibit theophylline metabolism, risking "
     "theophylline toxicity."),
    ("clopidogrel", "omeprazole", "moderate",
     "Omeprazole can reduce the antiplatelet effect of clopidogrel by "
     "inhibiting its activation."),
    ("warfarin", "ciprofloxacin", "moderate",
     "Ciprofloxacin can increase warfarin's anticoagulant effect, raising INR "
     "and bleeding risk; closer monitoring may be needed."),
    ("lisinopril", "ibuprofen", "moderate",
     "Ibuprofen can reduce lisinopril's blood-pressure-lowering effect and the "
     "combination may impair kidney function."),
    ("digoxin", "furosemide", "moderate",
     "Furosemide-related potassium loss can increase sensitivity to digoxin and "
     "the risk of digoxin toxicity."),
    ("amlodipine", "simvastatin", "moderate",
     "Amlodipine can increase simvastatin exposure; higher simvastatin doses "
     "raise the risk of muscle toxicity."),
]

KB_CONFIDENCE = 0.97  # exact ingredient-set match against an established rule


def _expand(side: str) -> Set[str]:
    """Resolves a rule side to its set of matching generic ingredients."""
    return _CLASS_MEMBERS.get(side, {side})


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown"


def _med_identity(med: Dict[str, Any]) -> Tuple[Any, ...]:
    """Identity key so a single combination product never 'interacts with
    itself' — both sides of a rule must come from distinct medication
    entries (different prescription lines/documents)."""
    return (
        (med.get("name") or "").strip().lower(),
        med.get("date"),
        med.get("source_file"),
    )


def check_known_interactions(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Scans timeline["medications_timeline"] against the curated rule table.
    Returns entries in the SAME shape as the LLM cross-check's
    potential_drug_interactions items, plus a "source" marker so the report
    (and UI) can distinguish knowledge-base findings from model inferences.
    Emits at most one finding per (rule, medication-pair).
    """
    meds = timeline.get("medications_timeline", []) or []

    # ingredient (lowercase) -> list of medication entries containing it
    by_ingredient: Dict[str, List[Dict[str, Any]]] = {}
    for med in meds:
        for ing in med.get("ingredients") or []:
            key = str(ing).strip().lower()
            if key:
                by_ingredient.setdefault(key, []).append(med)

    findings: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, frozenset]] = set()

    for side_a, side_b, severity, explanation in _RULES:
        rule_name = f"{side_a} + {side_b}"
        matches_a = [
            (ing, med)
            for ing in _expand(side_a) if ing in by_ingredient
            for med in by_ingredient[ing]
        ]
        if not matches_a:
            continue
        matches_b = [
            (ing, med)
            for ing in _expand(side_b) if ing in by_ingredient
            for med in by_ingredient[ing]
        ]
        for ing_a, med_a in matches_a:
            for ing_b, med_b in matches_b:
                if _med_identity(med_a) == _med_identity(med_b):
                    continue  # same prescription line — not a co-prescription pair
                pair_key = (rule_name, frozenset((_med_identity(med_a), _med_identity(med_b))))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                findings.append({
                    "medications_involved": [_med_display(med_a), _med_display(med_b)],
                    "explanation": (
                        f"Deterministic knowledge-base check ({rule_name}): "
                        f"{explanation} Matched on active ingredients "
                        f"'{ing_a}' and '{ing_b}'. Consult a doctor or "
                        "pharmacist before making any changes."
                    ),
                    "severity": severity,
                    "confidence": KB_CONFIDENCE,
                    "source": "curated_knowledge_base",
                    "rule": rule_name,
                })
    return findings


def merge_into_report(report: Dict[str, Any], kb_findings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Merges knowledge-base findings into an existing cross-check report
    (in place), skipping any finding whose exact medication set the LLM
    already flagged — the deterministic entry is only added when the model
    missed it, so the report never shows obvious duplicates.
    """
    existing = report.setdefault("potential_drug_interactions", [])
    existing_sets = [
        frozenset((m or "").strip().lower() for m in item.get("medications_involved", []))
        for item in existing
    ]
    for finding in kb_findings:
        key = frozenset(m.strip().lower() for m in finding["medications_involved"])
        if key not in existing_sets:
            existing.append(finding)
            existing_sets.append(key)
    return report
