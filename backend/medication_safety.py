"""Dedicated medication-safety service.

This is NOT part of document extraction. Extraction (`medical_extractor.py`)
turns files into a timeline. This module then *reads that timeline* and
writes a structured safety analysis:

    timeline
      → activity scoping
      → LLM broad pass (optional)
      → deterministic interaction KB
      → deterministic allergy KB
      → drug–lab / renal-hepatic / condition engines
      → duplicate detection
      → evidence grading (numeric confidence per flag)
      → timing / concurrent-exposure windows

The HTTP surface is `GET /api/v1/medication-safety` and
`POST /api/v1/medication-safety/reanalyze`. The Safety page (`/safety`)
is the dedicated frontend view.

`cross_check_prescriptions` is kept as the public function name so existing
callers keep working; `analyze_medication_safety` is the explicit alias.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("medication_safety")


CROSS_CHECK_PROMPT = """
You are a clinical safety cross-checking assistant. You are given a
patient's full medication timeline (medications prescribed across multiple
visits, each with a date and source document) and their known allergies.

Analyze the list and return STRICT JSON (no markdown, no commentary) in
this shape:

{
  "potential_drug_interactions": [
    {
      "medications_involved": ["Drug A", "Drug B"],
      "explanation": "plain language explanation of the interaction risk",
      "severity": "low | moderate | high",
      "confidence": 0.0-1.0
    }
  ],
  "duplicate_prescriptions": [
    {
      "medication": "string",
      "occurrences": [{"date": "YYYY-MM-DD", "source_file": "string", "dosage": "string"}],
      "explanation": "why this looks like a duplicate",
      "confidence": 0.0-1.0
    }
  ],
  "conflicting_dosage_instructions": [
    {
      "medication": "string",
      "conflicting_instructions": [{"date": "YYYY-MM-DD", "source_file": "string", "dosage": "string", "frequency": "string"}],
      "explanation": "what conflicts and why it matters",
      "confidence": 0.0-1.0
    }
  ],
  "allergy_conflicts": [
    {
      "medication": "string",
      "allergy": "string",
      "explanation": "string",
      "confidence": 0.0-1.0
    }
  ],
  "overall_recommendation": "1-2 sentence plain-language summary that ALWAYS recommends the patient consult a doctor or pharmacist before making any changes. Never present this as a diagnosis."
}

CONFIDENCE SCORING — anchor every confidence value to these bands. Do not
default to a high score:
- 0.90-1.00: the interaction/conflict/duplicate is well-established,
  unambiguous clinical knowledge (e.g. a textbook contraindicated pairing,
  an exact-ingredient duplicate).
- 0.60-0.89: plausible and worth surfacing, but depends on dose, timing, or
  patient-specific factors you cannot verify from this data alone.
- Below 0.60: a weak or speculative signal — include it only if omitting it
  would be the more dangerous error, and mark it clearly as low-confidence.

Rules:
- The payload you receive is already scoped to the patient's CURRENTLY
  ACTIVE medications. `reference_date` is the analysis date, and
  `excluded_inactive_medications` lists courses whose explicit duration had
  ended before that date — they are history, not live exposure, and must
  not be flagged as live interactions or conflicts. An open-ended or
  undated prescription is treated as active: flag it normally.
- Every medication entry carries a `prescription_group`. Entries sharing a
  prescription_group came from THE SAME physical prescription, uploaded more
  than once (e.g. a scan and a phone photo of one page). Count them as ONE
  prescription — a drug does not interact with itself, and the same
  prescription appearing in two files is not a duplicate prescription.
  Compare entries ACROSS different prescription_group values. Note that the
  printed `date` and `source_file` can differ between copies of one
  prescription (the same date gets extracted in different formats);
  prescription_group is the authority, not those.
- Compare medications by their active ingredients (not just brand names) —
  two different brand names with the same active ingredient is a likely
  duplicate.
- Medications are the SAME regardless of source language or printed
  wording — compare using ingredients (already normalized to English
  generic names), dosage_value + dosage_unit, and frequency_per_day
  (already normalized numeric fields), NOT the original dosage/frequency
  text. Do not flag something as a conflict or a difference if it is only
  a translation or unit-formatting difference — e.g. "500 mg" and "0.5 g"
  that both normalized to dosage_value=500/dosage_unit="mg" are the SAME
  dose, not a conflict. Only flag genuine differences in the normalized
  values.
- Only flag interactions you have reasonable clinical confidence about;
  lower the confidence score rather than omitting a plausible risk.
- Do not diagnose. Do not tell the patient to stop or start any medication.
  Always defer to a licensed professional.
- You are a reasoning layer over extracted text, NOT a validated clinical
  drug-interaction database. overall_recommendation must state plainly that
  this analysis is not a substitute for a pharmacist or a licensed
  drug-interaction checking tool, in addition to recommending consultation.
"""  # noqa: E501


CROSS_CHECK_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "potential_drug_interactions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medications_involved": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                    "severity": {"type": "string", "enum": ["low", "moderate", "high"]},
                    "confidence": {"type": "number"},
                },
                "required": ["medications_involved", "explanation", "severity", "confidence"],
                "additionalProperties": False,
            },
        },
        "duplicate_prescriptions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "occurrences": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": ["string", "null"]},
                                "source_file": {"type": ["string", "null"]},
                                "dosage": {"type": ["string", "null"]},
                            },
                            "required": ["date", "source_file", "dosage"],
                            "additionalProperties": False,
                        },
                    },
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "occurrences", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "conflicting_dosage_instructions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "conflicting_instructions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "date": {"type": ["string", "null"]},
                                "source_file": {"type": ["string", "null"]},
                                "dosage": {"type": ["string", "null"]},
                                "frequency": {"type": ["string", "null"]},
                            },
                            "required": ["date", "source_file", "dosage", "frequency"],
                            "additionalProperties": False,
                        },
                    },
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "conflicting_instructions", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "allergy_conflicts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "medication": {"type": "string"},
                    "allergy": {"type": "string"},
                    "explanation": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["medication", "allergy", "explanation", "confidence"],
                "additionalProperties": False,
            },
        },
        "overall_recommendation": {"type": "string"},
    },
    "required": [
        "potential_drug_interactions",
        "duplicate_prescriptions",
        "conflicting_dosage_instructions",
        "allergy_conflicts",
        "overall_recommendation",
    ],
    "additionalProperties": False,
}

CROSS_CHECK_RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "medical_cross_check",
        "strict": True,
        "schema": CROSS_CHECK_JSON_SCHEMA,
    },
}


def detect_exact_duplicate_medications(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Deterministic (non-LLM) duplicate detection using the normalized
    ingredients + dosage_value + dosage_unit fields set during extraction.

    Why this exists alongside the LLM cross-check: the LLM pass is
    instructed to compare medications via normalized fields rather than
    raw printed text, but it's still a probabilistic reasoning step run
    once per patient. An exact match on ingredient set + numeric dose,
    across two different source documents, is something code can determine
    for certain — independent of what language either document was
    written in — and shouldn't depend on the model reliably catching it
    every single time. This function only flags matches it can verify
    exactly; anything looser (different doses that might still interact,
    brand-name-only duplicates with no normalized dose available) is left
    to the LLM pass, which remains the primary check.
    """
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for med in timeline.get("medications_timeline", []):
        ingredients = tuple(sorted(med.get("ingredients") or []))
        dosage_value = med.get("dosage_value")
        dosage_unit = med.get("dosage_unit")
        if not ingredients or dosage_value is None or not dosage_unit:
            continue  # nothing normalized to compare — leave this one to the LLM pass
        key = (ingredients, dosage_value, dosage_unit)
        groups.setdefault(key, []).append(med)

    duplicates: List[Dict[str, Any]] = []
    for (ingredients, dosage_value, dosage_unit), meds in groups.items():
        # Counted by PRESCRIPTION, not by file. One prescription uploaded as
        # both a scan and a phone photo yields two (date, source_file) pairs
        # for every drug on it, which the old check read as "prescribed
        # twice" — reporting a double-dosing risk that came from the upload
        # history rather than the patient's medication history. Documents
        # recording the same prescription share a prescription_group (see
        # document_dedup.py), so they collapse to one here. Entries without a
        # group tag (older timelines) fall back to the (date, source_file)
        # identity, matching the historical behaviour.
        distinct_prescriptions = {
            m.get("prescription_group") or (m.get("date"), m.get("source_file")) for m in meds
        }
        if len(distinct_prescriptions) < 2:
            continue  # same medication on one prescription is not a duplicate
        duplicates.append(
            {
                "medication": " / ".join(ingredients),
                "occurrences": [
                    {
                        "date": m.get("date"),
                        "source_file": m.get("source_file"),
                        "dosage": m.get("dosage"),
                    }
                    for m in meds
                ],
                "explanation": (
                    f"Deterministic check: identical active ingredient(s) ({', '.join(ingredients)}) "  # noqa: E501
                    f"at the same normalized dose ({dosage_value} {dosage_unit}) appear on "
                    f"{len(distinct_prescriptions)} separate prescriptions, regardless of source "
                    "language or printed wording."
                ),
                "confidence": 0.95,  # exact numeric/ingredient match, not model inference
                "evidence_source": "deterministic",
            }
        )
    return duplicates


def cross_check_prescriptions(
    timeline: Dict[str, Any],
    model: Optional[str] = None,
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
    reference_date: Optional[str] = None,
    derived_references: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Runs interaction / duplicate / dosage-conflict / allergy cross-checking
    over a patient's merged medication timeline (output of
    build_patient_timeline). Merges in a deterministic, language-
    independent duplicate check (see detect_exact_duplicate_medications)
    alongside the LLM's own duplicate detection, rather than relying on
    the LLM pass alone to catch exact cross-language matches.

    Activity scoping (medication_activity.py): the live safety checks —
    the LLM cross-check and every deterministic pass — run only against
    medications whose courses are still active at `reference_date`
    (default today). Entries whose course provably ended earlier are
    excluded and listed with reasons in the report's `medication_activity`
    block, so nothing is silently dropped; medication history and change
    detection still cover the full record.

    After the findings are merged they are post-processed deterministically:
      * evidence grading (evidence_grading.py) — each finding is tagged by
        what actually backs it (computed-from-records vs model knowledge),
        and ungrounded model claims get their confidence capped. The optional
        `derived_references` (shared-enzyme pairs from interactions_kg) lets
        a two-drug finding that no source states but a reference table implies
        grade as `derived_reference` — above the model-knowledge cap, flagged
        for clinical review, rather than either a stated citation or a bare
        model recollection;
      * timing (risk_timeline.py) — each finding is placed in time using the
        prescription dates/durations;
      * concurrent_exposure — periods where two live prescriptions supplied
        the same ingredient (double-dosing arithmetic over the active set).
    """
    from medication_activity import analyze_medication_activity, filter_active_timeline

    activity = analyze_medication_activity(timeline, reference_date)
    active_timeline = filter_active_timeline(timeline, reference_date)

    if active_timeline.get("medications_timeline"):
        from medical_extractor import MODEL, _completion_resilient, _parse_json_object

        if model is None:
            model = MODEL
        payload = {
            "medications_timeline": active_timeline["medications_timeline"],
            "known_allergies": timeline["known_allergies"],
            "reference_date": activity["reference_date"],
            "excluded_inactive_medications": activity["inactive_medications"],
        }
        raw = _completion_resilient(
            model=model,
            system_prompt=CROSS_CHECK_PROMPT,
            user_content=f"Patient medication data:\n\n{json.dumps(payload, indent=2)}",
            strict_format=CROSS_CHECK_RESPONSE_FORMAT,
        )
        result = _parse_json_object(raw)
    else:
        # Every documented course provably ended before the reference date
        # (or the timeline has no medications at all). There is no live
        # exposure to analyze — skip the LLM call entirely and say why.
        if timeline.get("medications_timeline"):
            recommendation = (
                "No currently active prescriptions were found for safety analysis: "
                "every documented medication course ended before the reference date "
                f"({activity['reference_date']}). Historical courses remain listed in "
                "your record, and any current medications should be uploaded. Consult a "
                "doctor or pharmacist before making changes."
            )
        else:
            recommendation = (
                "No medications are documented in this record yet, so there is no "
                "prescription safety analysis to run. Upload your prescriptions to "
                "enable interaction, allergy, duplicate, and dosage checks."
            )
        result = {
            "potential_drug_interactions": [],
            "duplicate_prescriptions": [],
            "conflicting_dosage_instructions": [],
            "allergy_conflicts": [],
            "overall_recommendation": recommendation,
        }

    deterministic_duplicates = detect_exact_duplicate_medications(active_timeline)
    existing = result.setdefault("duplicate_prescriptions", [])
    existing_source_sets = [
        frozenset((occ.get("date"), occ.get("source_file")) for occ in d.get("occurrences", []))
        for d in existing
    ]
    for dup in deterministic_duplicates:
        dup_sources = frozenset((occ["date"], occ["source_file"]) for occ in dup["occurrences"])
        if dup_sources not in existing_source_sets:
            existing.append(dup)

    # Deterministic curated drug-interaction pass (never LLM-dependent):
    # well-established, textbook-level interaction pairs are matched on
    # normalized ingredients in code, so catching them never depends on the
    # LLM noticing on any given run. The LLM remains the broad-coverage
    # pass; the KB is the guaranteed floor. Scoped to active prescriptions.
    try:
        from drug_interactions import check_known_interactions, merge_into_report

        merge_into_report(result, check_known_interactions(active_timeline))
    except Exception as e:
        # A KB failure must never take down the whole safety report — the
        # LLM findings above are still valid on their own.
        logger.warning("Deterministic interaction check failed (LLM findings kept): %s", e)

    # Deterministic curated medication-allergy pass (never LLM-dependent):
    # each medication's normalized ingredients are matched in code against
    # the patient's recorded allergies (allergen classes + direct ingredient
    # names), so catching e.g. "amoxicillin prescribed; penicillin allergy
    # on record" never depends on the model noticing on any given run.
    # Scoped to active prescriptions.
    try:
        from drug_allergy_rules import check_allergy_conflicts, merge_allergy_findings

        merge_allergy_findings(result, check_allergy_conflicts(active_timeline))
    except Exception as e:
        logger.warning("Deterministic allergy check failed (LLM findings kept): %s", e)

    # Deterministic drug-LAB interaction pass: connects each active medication
    # to the patient's OWN most-recent lab value and flags dangerous
    # combinations (e.g. ACE inhibitor + potassium 5.9 mmol/L). Never
    # LLM-dependent; danger decided on positive evidence only.
    try:
        from drug_lab_interactions import check_drug_lab_findings, merge_drug_lab_findings

        merge_drug_lab_findings(result, check_drug_lab_findings(active_timeline))
    except Exception as e:
        logger.warning("Deterministic drug-lab check failed (LLM findings kept): %s", e)

    # Deterministic renal/hepatic dosing pass: flags medicines that commonly
    # need a lower dose or closer monitoring when kidney or liver function is
    # reduced, against this patient's own organ-function markers. Does NOT
    # recommend a dose — only surfaces the reason to ask a prescriber.
    try:
        from renal_hepatic_dosing import check_renal_hepatic_findings, merge_renal_hepatic_findings

        merge_renal_hepatic_findings(result, check_renal_hepatic_findings(active_timeline))
    except Exception as e:
        logger.warning("Deterministic renal/hepatic check failed (LLM findings kept): %s", e)

    # Deterministic condition-contraindication pass: flags medicines that
    # clash with conditions explicitly documented in this record (e.g. NSAID
    # + peptic ulcer, beta-blocker + asthma, ACE inhibitor + pregnancy).
    try:
        from condition_contraindications import (
            check_condition_contraindications,
            merge_condition_contraindications,
        )

        merge_condition_contraindications(
            result, check_condition_contraindications(active_timeline)
        )
    except Exception as e:
        logger.warning("Deterministic condition check failed (LLM findings kept): %s", e)

    # Deterministic US FDA recall pass: matches each active medication's
    # ingredients against openFDA enforcement records. Reads only the cache
    # warmed by the record/upload path (never network during this check), so
    # a cold cache or an unconfigured key simply means no recall findings
    # this run — the finding is never invented, and absence is never
    # rendered as "not recalled".
    try:
        from recall_check import check_recalls, merge_recall_findings

        merge_recall_findings(result, check_recalls(active_timeline))
    except Exception as e:
        logger.warning("Deterministic recall check failed (other findings kept): %s", e)

    from medication_history import detect_medication_transitions, enrich_cross_check_sources

    result.update(detect_medication_transitions(timeline))
    enrich_cross_check_sources(result, timeline)

    # Grade every finding by what actually backs it. The model scores its own
    # findings, and it scores a verifiable arithmetic fact and a half-recalled
    # pharmacology claim on the same scale — so an ungrounded interaction can
    # arrive at 0.95 and outrank a duplicate that was genuinely computed.
    # Grading caps and flags the ungrounded ones, which is what this pipeline
    # already tells users it is (a reasoning layer, not a validated
    # drug-interaction database).
    from evidence_grading import grade_cross_check
    from openfda_reference import openfda_claim_reference
    from reference_library import samhsa_claim_reference

    grade_cross_check(
        result,
        graph_backed_findings,
        claim_reference=(samhsa_claim_reference, openfda_claim_reference),
        derived_references=derived_references,
    )

    # Place every finding in time. Within the active set all courses overlap
    # at the reference date; timing still documents each finding's window
    # from the record's dates/durations.
    from risk_timeline import annotate_findings_with_timing, concurrent_exposure

    annotate_findings_with_timing(result, timeline)
    result["concurrent_exposure"] = concurrent_exposure(active_timeline)

    # Published opioid safety guidance is matched deterministically against
    # dated treatment windows. This produces a separately cited finding only
    # when an opioid and depressant course actually overlap.
    from reference_library import find_concurrent_depressant_risk, find_relevant_guidance

    result["guideline_flagged_combinations"] = find_concurrent_depressant_risk(timeline)
    result["published_guidance"] = find_relevant_guidance(active_timeline)

    result["reference_date"] = activity["reference_date"]
    result["medication_activity"] = activity
    return result


def analyze_medication_safety(
    timeline: Dict[str, Any],
    model: Optional[str] = None,
    graph_backed_findings: Optional[Dict[str, Dict[str, Any]]] = None,
    reference_date: Optional[str] = None,
    derived_references: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Public name for the dedicated medication-safety analysis."""
    return cross_check_prescriptions(
        timeline,
        model=model,
        graph_backed_findings=graph_backed_findings,
        reference_date=reference_date,
        derived_references=derived_references,
    )


__all__ = [
    "CROSS_CHECK_PROMPT",
    "CROSS_CHECK_JSON_SCHEMA",
    "CROSS_CHECK_RESPONSE_FORMAT",
    "detect_exact_duplicate_medications",
    "cross_check_prescriptions",
    "analyze_medication_safety",
]
