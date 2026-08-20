"""
Evidence Grading for Safety Findings
=========================================
Separates safety findings the system can actually EVIDENCE from ones that are
only the language model's recollection, and scores them accordingly.

THE PROBLEM THIS FIXES
----------------------
cross_check_prescriptions() returns interactions, allergy conflicts and dosage
conflicts with confidence scores the model assigns itself. Those scores read
as if they were all the same kind of claim, and they are not:

  * "Cetirizine 10 mg appears on two separate prescriptions" is arithmetic
    over the patient's own extracted records. It is checkable, repeatable,
    and either true or false.
  * "Fluconazole inhibits CYP2C9, raising montelukast levels" is the model
    recalling pharmacology from training. It may well be right — but nothing
    in this system verifies it, and the model has no way to distinguish a
    fact it knows from one it has confabulated.

Both used to arrive at 0.65, 0.95, whatever the model felt, with no way for a
reader to tell which was which. This module makes the difference explicit and
caps ungrounded claims, so a confident-sounding interaction cannot outrank a
finding that was actually verified.

That is not a hedge, it is what the pipeline already tells users: the
cross-check prompt itself states it is "a reasoning layer over extracted
text, NOT a validated clinical drug-interaction database". This grading makes
the scores honour that sentence instead of contradicting it.

FOUR GRADES
-----------
  deterministic     Computed in code from the patient's own extracted data
                    (e.g. detect_exact_duplicate_medications). Highest trust —
                    no model judgment involved.
  reference_graph   Backed by an ingested reference source passed in via
                    `graph_backed_findings`, or by a claim-level citation
                    returned from a `claim_reference` hook (see
                    reference_library.samhsa_claim_reference and
                    openfda_reference.openfda_claim_reference). Trusted, and
                    cites the source document. The WHO antidote graph, the
                    optional openFDA Structured Product Labels and the FDA
                    enzyme-role table's quoted statements fill this grade
                    today; the grade stays so more reference data can be
                    wired in without another contract change.
  derived_reference A pair DERIVED by joining two separately-quoted reference
                    statements — "drug A is a CYP3A substrate" and "drug B is
                    a strong CYP3A inhibitor" (interactions_kg.potential_
                    interactions). Sits between the other grades because that
                    is honestly where it belongs: the mechanism is quoted,
                    the pairing is inferred. Higher ceiling than
                    model_knowledge because two verbatim FDA rows stand behind
                    the mechanism, lower than reference_graph because no
                    document states that these two drugs interact. Shared
                    enzymes are common and most theoretical pairs are
                    clinically unremarkable, so the finding also carries
                    requires_clinical_review.
  model_knowledge   The model's own pharmacological knowledge, with nothing
                    behind it. Capped, flagged, and told to be confirmed.
"""

from typing import Any, Callable, Dict, List, Optional, Sequence, Set, Union

ClaimReferenceFn = Callable[[Dict[str, Any]], Optional[Dict[str, Any]]]

# Ungrounded findings are capped here. Matches retrieval.LOW_CONFIDENCE_THRESHOLD
# so "low confidence" means one thing across the product — and so the QA
# consult guard, which escalates at or below this value, fires on answers
# built mostly from capped findings.
MODEL_KNOWLEDGE_CONFIDENCE_CEILING = 0.6

DETERMINISTIC = "deterministic"
REFERENCE_GRAPH = "reference_graph"
# A pair DERIVED by joining two separately-quoted reference statements
# (interactions_kg.potential_interactions) rather than a source stating the
# two drugs interact. Higher ceiling than model_knowledge, lower than
# reference_graph, and always flagged for clinical review.
DERIVED_REFERENCE = "derived_reference"
DERIVED_REFERENCE_CONFIDENCE_CEILING = 0.75
MODEL_KNOWLEDGE = "model_knowledge"

# Finding lists in a cross_check report, and whether each is about drugs whose
# names can be matched against the reference graph.
FINDING_LISTS = (
    "potential_drug_interactions",
    "duplicate_prescriptions",
    "conflicting_dosage_instructions",
    "allergy_conflicts",
)

MODEL_KNOWLEDGE_NOTE = (
    "This comes from the language model's own pharmacological knowledge — no "
    "reference source in this system confirms it. It may be correct, but it has "
    "not been checked against a drug-interaction database. Treat it as a prompt "
    "to ask a pharmacist, not as an established fact."
)

DETERMINISTIC_NOTE = (
    "Computed directly from the patient's own extracted records, not from model "
    "knowledge — this one is checkable against the source documents."
)

REFERENCE_GRAPH_NOTE = (
    "Backed by a reference document ingested into the knowledge graph, cited below."
)


def _claim_reference_chain(
    claim_reference: Optional[Any],
) -> tuple:
    """Normalize the `claim_reference` argument to a tuple of callables.

    Accepts a single callable (the original contract) or a sequence of them,
    so several evidence sources (curated SAMHSA guidance, openFDA labels) can
    each get a chance to corroborate a finding without every source living in
    one function.
    """
    if claim_reference is None:
        return ()
    if callable(claim_reference):
        return (claim_reference,)
    return tuple(claim_reference)


def _finding_drug_names(finding: Dict[str, Any]) -> Set[str]:
    """Every drug name a finding refers to, lowercased."""
    names: Set[str] = set()
    for key in ("medication", "allergy"):
        value = finding.get(key)
        if isinstance(value, str) and value.strip():
            names.add(value.strip().lower())
    for value in finding.get("medications_involved") or []:
        if isinstance(value, str) and value.strip():
            names.add(value.strip().lower())
    return names


def _pair_key(names: Sequence[str]) -> Optional[str]:
    """Order-independent key for a two-drug finding."""
    unique = sorted({(n or "").strip().lower() for n in names if n and n.strip()})
    return "|".join(unique) if len(unique) == 2 else None


def grade_finding(
    finding: Dict[str, Any],
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
    claim_reference: Optional[Union[ClaimReferenceFn, Sequence[ClaimReferenceFn]]] = None,
    derived_references: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Grades one finding in place and returns it.

    Adds:
      evidence_source : "deterministic" | "reference_graph" | "derived_reference"
                        | "model_knowledge"
      grounded        : bool  (False only for model_knowledge)
      evidence_note   : str   plain-language explanation of the grade
      reference       : dict  present for reference_graph and derived_reference
                        findings

    A finding that already declares `evidence_source` (as the deterministic
    duplicate detector does) keeps it — this never downgrades a finding that
    code produced into one that looks like model output. Findings produced
    by other deterministic passes (e.g. the curated drug-interaction
    knowledge base, which tags itself `source: curated_knowledge_base`) are
    likewise graded deterministic rather than capped as model recall.
    """
    existing = finding.get("evidence_source")
    if existing == DETERMINISTIC:
        finding["grounded"] = True
        finding.setdefault("evidence_note", DETERMINISTIC_NOTE)
        return finding
    if finding.get("source") == "curated_knowledge_base":
        finding["evidence_source"] = DETERMINISTIC
        finding["grounded"] = True
        finding.setdefault("evidence_note", DETERMINISTIC_NOTE)
        return finding

    # A source that makes this exact claim is stronger evidence than a graph
    # merely showing that one named drug appears in a reference document.
    # `claim_reference` may be one callable or a sequence of them; the first
    # that corroborates the finding wins. A citation may carry its own
    # `note` (e.g. an FDA label quote, which has no page number), which
    # overrides the default evidence_note for that finding only.
    for ref_fn in _claim_reference_chain(claim_reference):
        citation = ref_fn(finding)
        if not citation:
            continue
        note = None
        if isinstance(citation, dict) and "note" in citation:
            note = citation.get("note")
            citation = {key: value for key, value in citation.items() if key != "note"}
        finding["evidence_source"] = REFERENCE_GRAPH
        finding["grounded"] = True
        finding["reference"] = citation
        finding["evidence_note"] = note or (
            "Backed by published clinical guidance, with source and page — "
            "not the model's own recollection."
        )
        return finding

    graph_backed_findings = graph_backed_findings or {}
    matched = {
        name: graph_backed_findings[name]
        for name in _finding_drug_names(finding)
        if name in graph_backed_findings
    }

    if matched:
        finding["evidence_source"] = REFERENCE_GRAPH
        finding["grounded"] = True
        finding["reference"] = matched
        finding["evidence_note"] = REFERENCE_GRAPH_NOTE
        return finding

    # Checked only after the per-drug graph hit and the claim citations, so
    # nothing that already grades reference_graph is downgraded by adding
    # this tier: a source that states the pairing beats one that merely
    # implies it.
    pair = _pair_key(_finding_drug_names(finding))
    derived = (derived_references or {}).get(pair) if pair else None
    if derived:
        finding["evidence_source"] = DERIVED_REFERENCE
        finding["grounded"] = True
        finding["reference"] = derived
        finding["requires_clinical_review"] = True
        finding["evidence_note"] = (
            "The mechanism is quoted from a published reference — each drug's "
            "enzyme role is recorded there — but the source does not state that "
            "these two drugs interact; that pairing is derived from the shared "
            "pathway and needs clinical confirmation."
        )
        raw = finding.get("confidence")
        ceiling = DERIVED_REFERENCE_CONFIDENCE_CEILING
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            if float(raw) > ceiling:
                finding["model_reported_confidence"] = round(float(raw), 2)
            finding["confidence"] = round(min(float(raw), ceiling), 2)
        else:
            finding["confidence"] = ceiling
        return finding

    finding["evidence_source"] = MODEL_KNOWLEDGE
    finding["grounded"] = False
    finding["evidence_note"] = MODEL_KNOWLEDGE_NOTE

    raw = finding.get("confidence")
    if isinstance(raw, (int, float)) and not isinstance(raw, bool):
        capped = min(float(raw), MODEL_KNOWLEDGE_CONFIDENCE_CEILING)
        if capped < raw:
            # Keep what the model claimed. Silently overwriting it would hide
            # that the cap was applied, and the gap between the two is useful
            # signal — a model asserting 0.95 for something nothing can verify
            # is worth being able to see.
            finding["model_reported_confidence"] = round(float(raw), 2)
        finding["confidence"] = round(capped, 2)
    else:
        finding["confidence"] = MODEL_KNOWLEDGE_CONFIDENCE_CEILING

    return finding


def grade_cross_check(
    cross_check: Dict[str, Any],
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
    claim_reference: Optional[Union[ClaimReferenceFn, Sequence[ClaimReferenceFn]]] = None,
    derived_references: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Grades every finding in a cross_check report, in place, and adds an
    `evidence_summary` describing the mix.

    `graph_backed_findings` optionally maps a lowercased drug name to whatever
    reference record supports it. Any finding naming one of those drugs is
    graded `reference_graph` and keeps its confidence uncapped. When no
    reference graph is configured (the default), every non-deterministic
    finding grades as model_knowledge — the honest answer.

    `claim_reference` optionally corroborates findings at the claim level:
    it may be a single callable or a sequence of callables, each returning a
    citation dict for a finding it actually supports (else None). The first
    citation wins, and a citation may carry its own `note` for the
    evidence_note.

    `derived_references` optionally maps an order-independent drug-pair key
    ("a|b") to the derived pharmacokinetic pairing behind it (see
    interactions_kg.potential_interactions and
    derived_references_from_interactions). A finding naming exactly that pair
    grades `derived_reference` — above the model-knowledge cap, below a
    stated citation — and is flagged for clinical review.
    """
    counts = {
        DETERMINISTIC: 0,
        REFERENCE_GRAPH: 0,
        DERIVED_REFERENCE: 0,
        MODEL_KNOWLEDGE: 0,
    }

    for list_name in FINDING_LISTS:
        for finding in cross_check.get(list_name) or []:
            if not isinstance(finding, dict):
                continue
            grade_finding(finding, graph_backed_findings, claim_reference,
                          derived_references)
            counts[finding["evidence_source"]] += 1

    total = sum(counts.values())
    cross_check["evidence_summary"] = {
        "total_findings": total,
        "deterministic": counts[DETERMINISTIC],
        "reference_graph": counts[REFERENCE_GRAPH],
        "derived_reference": counts[DERIVED_REFERENCE],
        "model_knowledge": counts[MODEL_KNOWLEDGE],
        "model_knowledge_confidence_ceiling": MODEL_KNOWLEDGE_CONFIDENCE_CEILING,
        "note": (
            f"{counts[DETERMINISTIC] + counts[REFERENCE_GRAPH] + counts[DERIVED_REFERENCE]} "
            f"of {total} finding(s) are backed by the patient's own records or by an "
            "ingested reference document. "
            f"The other {counts[MODEL_KNOWLEDGE]} come from the language model's own "
            f"knowledge with nothing in this system confirming them, so their confidence "
            f"is capped at {MODEL_KNOWLEDGE_CONFIDENCE_CEILING} and each is flagged. "
            "A pharmacist can confirm any of them."
        )
        if total
        else ("No safety findings were reported, so there is nothing to grade."),
    }
    return cross_check


def graph_backed_findings_from_antidotes(
    antidote_references: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Adapts poisoning_kg.lookup_antidote_references() output into the
    `graph_backed_findings` shape consumed by grade_finding()/grade_cross_check().

    Deliberately narrow: being WHO-listed as an antidote evidences that the
    DRUG is in a reference document, not that any particular interaction claim
    about it is true. It is used here to cite a real source alongside a finding
    — never to imply the graph confirmed an interaction it has no data about.
    """
    backed: Dict[str, Dict[str, Any]] = {}
    for name, ref in (antidote_references or {}).items():
        if not name:
            continue
        backed[name.strip().lower()] = {
            "source": "WHO Model List of Essential Medicines (antidotes section)",
            "display_name": ref.get("display_name"),
            "listings": ref.get("listings", []),
        }
    return backed


def derived_references_from_interactions(
    pairs: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Adapts interactions_kg.potential_interactions() output into the
    `derived_references` shape keyed by drug pair.

    Deliberately NOT routed through `graph_backed_findings`, which grades
    reference_graph and leaves confidence uncapped. Nothing in the FDA table
    says these two drugs interact — it records each drug's enzyme role
    separately, and the pairing is a join. Grading that as a citation would
    make an inference indistinguishable from a quote.
    """
    backed: Dict[str, Dict[str, Any]] = {}
    for pair in pairs or []:
        key = _pair_key([pair.get("affecting_drug"), pair.get("affected_drug")])
        if not key:
            continue
        backed[key] = {
            "source": pair.get("source"),
            "source_url": pair.get("source_url"),
            "shared_pathways": pair.get("shared_pathways"),
            "mechanism": pair.get("mechanism"),
            "strength": pair.get("strength"),
            "derivation": pair.get("derivation"),
            "pathways": pair.get("pathways", []),
            "requires_clinical_review": True,
        }
    return backed


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # Findings shaped like a real cross_check_report.
    report = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Fluconazole", "Montelukast"],
                "explanation": "Fluconazole inhibits CYP enzymes...",
                "severity": "moderate",
                "confidence": 0.65,
            },
            {
                "medications_involved": ["Cetirizine", "Chlorpheniramine"],
                "explanation": "Additive sedation.",
                "severity": "moderate",
                "confidence": 0.95,
            },
            {
                "medications_involved": ["Fluconazole", "Omeprazole"],
                "explanation": "Both affect CYP2C19; clinical impact usually small.",
                "severity": "low",
                "confidence": 0.45,
            },
        ],
        "duplicate_prescriptions": [
            {
                "medication": "Cetirizine",
                "occurrences": [],
                "confidence": 0.95,
                "explanation": "Deterministic check: identical active ingredient(s)...",
                "evidence_source": DETERMINISTIC,
            },
            {
                "medication": "Paracetamol",
                "occurrences": [],
                "confidence": 0.9,
                "explanation": "Model spotted these look similar.",
            },
        ],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [
            {
                "medication": "Amoxicillin",
                "allergy": "Penicillin",
                "explanation": "Amoxicillin is a penicillin-class antibiotic.",
                "confidence": 0.93,
            },
        ],
    }

    grade_cross_check(report)

    # Model-knowledge findings are capped and flagged, and what the model
    # originally claimed is preserved.
    interaction = report["potential_drug_interactions"][1]
    assert interaction["evidence_source"] == MODEL_KNOWLEDGE
    assert interaction["grounded"] is False
    assert interaction["confidence"] == 0.6, interaction["confidence"]
    assert interaction["model_reported_confidence"] == 0.95
    assert "pharmacist" in interaction["evidence_note"]

    # 0.65 sits just above the ceiling, so it is capped too — the cap is not
    # only for the loudly-overconfident ones.
    just_over = report["potential_drug_interactions"][0]
    assert just_over["confidence"] == 0.6, just_over["confidence"]
    assert just_over["model_reported_confidence"] == 0.65

    # A model finding already BELOW the ceiling keeps its own value and gains
    # no misleading "was capped" marker — capping must never inflate a score.
    low = report["potential_drug_interactions"][2]
    assert low["confidence"] == 0.45, low["confidence"]
    assert "model_reported_confidence" not in low

    # The deterministic duplicate is NOT capped or downgraded.
    deterministic = report["duplicate_prescriptions"][0]
    assert deterministic["evidence_source"] == DETERMINISTIC
    assert deterministic["grounded"] is True
    assert deterministic["confidence"] == 0.95, "verifiable findings must keep their score"
    assert "model_reported_confidence" not in deterministic

    # An LLM-authored duplicate IS capped, even in the same list.
    assert report["duplicate_prescriptions"][1]["confidence"] == 0.6

    # The allergy claim is model knowledge (nothing in this system holds
    # penicillin cross-reactivity data) and is capped accordingly.
    allergy = report["allergy_conflicts"][0]
    assert allergy["evidence_source"] == MODEL_KNOWLEDGE
    assert allergy["confidence"] == 0.6
    assert allergy["model_reported_confidence"] == 0.93

    summary = report["evidence_summary"]
    assert summary["total_findings"] == 6
    assert summary["deterministic"] == 1
    assert summary["model_knowledge"] == 5
    assert summary["reference_graph"] == 0
    assert summary["derived_reference"] == 0

    # --- Reference-graph grounding raises a finding above the cap ----------
    backed = {
        "naloxone": {
            "source": "WHO Model List of Essential Medicines (antidotes section)",
            "display_name": "naloxone",
            "listings": [{"population": "adult", "source_document": "WHO.pdf"}],
        },
    }
    graph_report = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Naloxone", "Morphine"],
                "explanation": "Naloxone reverses opioid effects.",
                "severity": "high",
                "confidence": 0.9,
            },
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }
    grade_cross_check(graph_report, backed)
    grounded = graph_report["potential_drug_interactions"][0]
    assert grounded["evidence_source"] == REFERENCE_GRAPH
    assert grounded["grounded"] is True
    assert grounded["confidence"] == 0.9, "a graph-backed finding is not capped"
    assert "naloxone" in grounded["reference"]

    # --- A derived shared-enzyme pair sits between the other grades --------
    # The FDA table quotes each drug's role separately; the pairing is a
    # join. It must never be dressed up as a stated citation (uncapped
    # reference_graph), but it does stand on quoted mechanism rows, so it
    # clears the model-knowledge cap and is flagged for clinical review.
    derived_pairs = derived_references_from_interactions([
        {
            "affecting_drug": "clarithromycin",
            "affected_drug": "simvastatin",
            "source": "fda-cyp-transporter-examples",
            "source_url": "https://www.fda.gov/...",
            "shared_pathways": "3A, OATP1B1, OATP1B3",
            "mechanism": "INHIBITS",
            "strength": "strong",
            "derivation": "Clarithromycin is recorded as ... and simvastatin as ...",
            "pathways": [],
        },
    ])
    assert set(derived_pairs) == {"clarithromycin|simvastatin"}, derived_pairs
    derived_report = {
        "potential_drug_interactions": [
            {
                "medications_involved": ["Simvastatin", "Clarithromycin"],
                "explanation": "Clarithromycin inhibits CYP3A4, raising simvastatin levels.",
                "severity": "high",
                "confidence": 0.95,
            },
            {
                "medications_involved": ["Simvastatin", "Clarithromycin"],
                "explanation": "Same pair, model confidence already below the ceiling.",
                "severity": "high",
                "confidence": 0.5,
            },
        ],
        "duplicate_prescriptions": [],
        "conflicting_dosage_instructions": [],
        "allergy_conflicts": [],
    }
    grade_cross_check(derived_report, derived_references=derived_pairs)
    capped = derived_report["potential_drug_interactions"][0]
    assert capped["evidence_source"] == DERIVED_REFERENCE
    assert capped["grounded"] is True
    assert capped["requires_clinical_review"] is True
    assert capped["confidence"] == 0.75, capped["confidence"]
    assert capped["model_reported_confidence"] == 0.95
    below = derived_report["potential_drug_interactions"][1]
    assert below["confidence"] == 0.5, "a below-ceiling derived finding keeps its score"
    assert "model_reported_confidence" not in below
    assert derived_report["evidence_summary"]["derived_reference"] == 2

    # --- An empty report grades cleanly ------------------------------------
    empty = grade_cross_check(
        {
            "potential_drug_interactions": [],
            "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [],
            "allergy_conflicts": [],
        }
    )
    assert empty["evidence_summary"]["total_findings"] == 0
    assert "nothing to grade" in empty["evidence_summary"]["note"]

    print("Graded findings from the sample report:")
    for name in FINDING_LISTS:
        for f in report.get(name) or []:
            label = f.get("medication") or " + ".join(f.get("medications_involved") or [])
            was = f.get("model_reported_confidence")
            print(
                f"  [{f['evidence_source']:16}] {label:28} confidence={f['confidence']}"
                + (f"  (model claimed {was})" if was else "")
            )
    print("\n" + report["evidence_summary"]["note"])
    print("\nAll checks passed.")
