"""
Alert-Fatigue Management
========================
A safety pipeline that fires a warning on every plausible risk quickly becomes
noise a user stops reading. This module applies two standard mitigations on
top of an assembled cross-check report:

1. OVERRIDE SUPPRESSION — findings a reviewer already dismissed (verdict
   `overridden`) are moved into a separate `suppressed_findings` list rather
   than presented as live alerts. Nothing is deleted; they stay visible on
   demand and the override reason travels with them.

2. NEAR-DUPLICATE COLLAPSE — findings that describe the same clinical signal
   (same rule + same medication set, e.g. the deterministic KB and the LLM
   both flag warfarin+ibuprofen) are collapsed into one, with a count of how
   many were merged, so the user sees one alert, not N.

The output keeps `active_findings` (what to show), `suppressed_findings`
(overridden, available on request), and `merge_log` (what was collapsed).
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from clinician_feedback import finding_key, is_overridden

FINDING_LISTS = (
    "potential_drug_interactions",
    "duplicate_prescriptions",
    "conflicting_dosage_instructions",
    "allergy_conflicts",
    "drug_lab_findings",
    "renal_hepatic_findings",
    "condition_contraindications",
    "guideline_flagged_combinations",
)


def _dedup_sig(finding: Dict[str, Any]) -> Tuple[Any, ...]:
    """Signature for near-duplicate collapse: rule + sorted medications +
    finding_kind. Lab value / condition are included so two genuinely
    different findings on the same drug are NOT collapsed."""
    meds = tuple(sorted(str(m).lower() for m in (finding.get("medications_involved") or [])))
    lab = finding.get("lab") or {}
    cond = str(finding.get("condition") or "").lower()
    organ = str(finding.get("organ") or "").lower()
    lab_sig = (lab.get("test"), lab.get("value")) if isinstance(lab, dict) else ()
    return (
        finding.get("finding_kind") or "finding",
        finding.get("rule") or "",
        meds,
        cond,
        organ,
        lab_sig,
    )


def manage_alerts(report: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Return a view of the report with overridden alerts suppressed and
    near-duplicates collapsed, per workspace."""
    active: List[Dict[str, Any]] = []
    suppressed: List[Dict[str, Any]] = []
    seen: Dict[Tuple[Any, ...], Dict[str, Any]] = {}
    merge_log: List[Dict[str, Any]] = []

    for list_key in FINDING_LISTS:
        for finding in report.get(list_key) or []:
            finding = dict(finding)
            finding["_source_list"] = list_key
            fkey = finding_key(finding)
            finding["finding_key"] = fkey
            if is_overridden(user_id, fkey):
                finding["suppressed_reason"] = "reviewer_override"
                suppressed.append(finding)
                continue
            sig = _dedup_sig(finding)
            if sig in seen:
                master = seen[sig]
                master["_merged_count"] = master.get("_merged_count", 1) + 1
                merge_log.append(
                    {"collapsed_into": master["finding_key"], "rule": finding.get("rule")}
                )
                continue
            finding["_merged_count"] = 1
            seen[sig] = finding
            active.append(finding)

    # rank: high > moderate > low, then overridden-last already removed
    rank = {"high": 0, "moderate": 1, "low": 2}
    active.sort(
        key=lambda f: (
            rank.get(str(f.get("severity") or "moderate"), 1),
            -(f.get("_merged_count") or 1),
        )
    )

    return {
        "active_findings": active,
        "active_count": len(active),
        "suppressed_findings": suppressed,
        "suppressed_count": len(suppressed),
        "collapsed_duplicates": len(merge_log),
        "merge_log": merge_log,
    }
