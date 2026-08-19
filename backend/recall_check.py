"""
US FDA Recall Check (deterministic, openFDA-backed)
====================================================
Answers a question MediMind could not previously ask: "has any medicine on
this record been the subject of a US FDA recall?"

WHERE IT SITS
-------------
A deterministic safety layer, like drug_lab_interactions.py and
condition_contraindications.py: it runs over the ACTIVE medication set during
cross_check_prescriptions(), merges its findings into the report, and the
findings then flow through the same lifecycle every other finding has —
alert management (override / near-duplicate collapse), reviewer feedback,
finding lifecycle states, consult triage and the follow-up action queue.

DISCIPLINE
----------
* US-MARKET DATA. openFDA enforcement records describe US recalls. A match
  means "the FDA has an enforcement record naming this ingredient", NOT that
  the patient's own supply is affected. Every finding says this, and routes
  to a pharmacist — the professional who can compare a dispensed batch/lot
  against the recall.
* ABSENCE IS NOT EVIDENCE OF SAFETY. No match produces NO finding, never a
  "not recalled" reassurance. An unmatched ingredient is simply not checked.
* ONE FINDING PER INGREDIENT. The most actionable record (ongoing first,
  then highest FDA class, then most recent) is surfaced with a count of any
  others, so alert fatigue is not imported wholesale from a noisy feed.
* CACHE-ONLY. check_recalls() reads only the in-process cache warmed by the
  record/upload path (openfda_reference.prefetch_recalls). It performs no
  network I/O, and a cold cache simply means no recall findings this run.

Severity follows the FDA class: Class I high, Class II moderate, Class III
low. The class describes the *potential* seriousness of the recalled product,
so it is the right patient-facing ordering; the status and date are kept in
the explanation so an old, completed recall reads as old and completed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

LIST_KEY = "openfda_recalls"

# The recall is a deterministic match against the FDA enforcement feed, not a
# model judgement, so it carries the same kind of score as the other
# deterministic layers (and is never run through evidence grading, which only
# touches the model-authored finding lists).
CONFIDENCE = 0.9

_CLASS_SEVERITY = {
    "class i": "high",
    "class ii": "moderate",
    "class iii": "low",
}

_US_MARKET_CAVEAT = (
    "This is a US FDA enforcement record, not confirmation that your own "
    "medicine was affected. Ask a pharmacist to compare your medicine's "
    "batch or lot number against this recall before doing anything different."
)


def _med_display(med: Dict[str, Any]) -> str:
    return med.get("name") or " / ".join(med.get("ingredients") or []) or "unknown medication"


def _med_ingredients(med: Dict[str, Any]) -> Set[str]:
    from document_dedup import _base_ingredient

    return {
        _base_ingredient(str(ingredient))
        for ingredient in (med.get("ingredients") or [])
        if str(ingredient).strip()
    }


def _findings_for_ingredient(
    ingredient: str, recalls: List[Dict[str, Any]], display: str
) -> List[Dict[str, Any]]:
    """One finding per ingredient, from its most actionable recall record."""
    if not recalls:
        return []
    top = recalls[0]
    classification = str(top.get("classification") or "Class II")
    severity = _CLASS_SEVERITY.get(classification.lower(), "moderate")
    status = str(top.get("status") or "").strip()
    when = top.get("recall_initiation_date") or "date not reported"
    status_phrase = "an ongoing recall" if top.get("ongoing") else f"a {status.lower()} recall"
    extra = ""
    if len(recalls) > 1:
        extra = (
            f" The FDA lists {len(recalls)} enforcement record(s) for this "
            "ingredient; the most actionable one is shown."
        )
    explanation = (
        f"{display} has {status_phrase} in the US market ({classification}, "
        f"initiated {when}): {top.get('reason_for_recall') or 'reason not reported'}. "
        f"{_US_MARKET_CAVEAT}{extra}"
    )
    return [
        {
            "medications_involved": [display],
            "ingredient": ingredient,
            "explanation": explanation,
            "severity": severity,
            "confidence": CONFIDENCE,
            "source": "openfda_enforcement",
            "rule": f"recall:{top.get('recall_number') or ingredient}",
            "finding_kind": "openfda_recall",
            "reference": {
                "source": top.get("source"),
                "publisher": top.get("publisher"),
                "recall_number": top.get("recall_number"),
                "classification": top.get("classification"),
                "status": top.get("status"),
                "recall_initiation_date": top.get("recall_initiation_date"),
                "reason_for_recall": top.get("reason_for_recall"),
                "product_description": top.get("product_description"),
            },
            "recall_count": len(recalls),
        }
    ]


def check_recalls(
    timeline: Dict[str, Any],
    references: Optional[Dict[str, List[Dict[str, Any]]]] = None,
) -> List[Dict[str, Any]]:
    """Return recall findings for the active medications, one per ingredient.

    `references` lets a caller pass pre-fetched recall records; when omitted
    the check reads only the cache (no network) — the record/upload path
    warms it first via openfda_reference.prefetch_recalls().
    """
    from openfda_reference import lookup_recall_references

    meds = list(timeline.get("medications_timeline") or [])
    if not meds:
        return []

    wanted: Set[str] = set()
    display_by_ingredient: Dict[str, str] = {}
    for med in meds:
        display = _med_display(med)
        for ingredient in _med_ingredients(med):
            if not ingredient:
                continue
            wanted.add(ingredient)
            display_by_ingredient.setdefault(ingredient, display)

    if not wanted:
        return []

    if references is None:
        references = lookup_recall_references(sorted(wanted), fetch_missing=False)

    findings: List[Dict[str, Any]] = []
    for ingredient in sorted(wanted):
        recalls = (references or {}).get(ingredient)
        if not recalls:
            continue
        findings.extend(
            _findings_for_ingredient(ingredient, recalls, display_by_ingredient[ingredient])
        )
    return findings


def merge_recall_findings(
    report: Dict[str, Any], findings: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Append recall findings to the report, skipping an exact duplicate
    (same ingredient + same recall number)."""
    existing = report.setdefault(LIST_KEY, [])
    sigs = {
        (f.get("ingredient"), (f.get("reference") or {}).get("recall_number")) for f in existing
    }
    for finding in findings:
        sig = (finding.get("ingredient"), (finding.get("reference") or {}).get("recall_number"))
        if sig in sigs:
            continue
        sigs.add(sig)
        existing.append(finding)
    return report


if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    recalls = [
        {
            "source": "FDA Enforcement Report (openFDA drug/enforcement)",
            "publisher": "test",
            "recall_number": "D-1234-2024",
            "classification": "Class II",
            "status": "Ongoing",
            "recall_initiation_date": "2024-01-05",
            "reason_for_recall": "Microbial contamination",
            "product_description": "Losartan tablets",
            "ongoing": True,
        },
        {
            "source": "FDA Enforcement Report (openFDA drug/enforcement)",
            "publisher": "test",
            "recall_number": "D-0001-2020",
            "classification": "Class III",
            "status": "Completed",
            "recall_initiation_date": "2020-02-02",
            "reason_for_recall": "Labeling",
            "product_description": "Losartan tablets",
            "ongoing": False,
        },
    ]

    timeline = {
        "medications_timeline": [
            {"name": "Losartan", "ingredients": ["Losartan potassium"]},
            {"name": "Paracetamol", "ingredients": ["Paracetamol"]},
        ]
    }
    findings = check_recalls(timeline, references={"losartan": recalls})
    assert len(findings) == 1, findings
    f = findings[0]
    assert f["ingredient"] == "losartan"
    assert f["severity"] == "moderate"
    assert f["finding_kind"] == "openfda_recall"
    assert f["recall_count"] == 2
    assert "ongoing recall" in f["explanation"]
    assert "pharmacist" in f["explanation"]
    assert f["reference"]["recall_number"] == "D-1234-2024"

    # No records -> no findings, and never a reassuring negative.
    assert check_recalls({"medications_timeline": []}) == []
    assert check_recalls(timeline, references={}) == []

    # Merge dedupes by (ingredient, recall_number).
    report: Dict[str, Any] = {}
    merge_recall_findings(report, findings)
    merge_recall_findings(report, findings)
    assert len(report[LIST_KEY]) == 1

    print("recall_check self-checks passed.")
