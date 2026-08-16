"""
Care-recommendation engine.

Analyses a patient's medical records (timeline, cross-check report,
lab trends) and produces a ranked list of care-recommendation objects
that the frontend renders as actionable cards.

Each recommendation has:
  - specialty: patient-facing specialty name (e.g. "Allergist / Immunologist")
  - relevance: "high" | "moderate" | "possible" | "needs_clinical_review"
  - title: short label (e.g. "Medication reconciliation")
  - explanation: one-sentence why
  - evidence: list of evidence strings (source file, date, etc.)
  - source_records: number of relevant documents

This module is pure logic — no LLM calls. It reads structured data
already extracted by medical_extractor.py and lab_trends.py.
"""

from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Optional

logger = logging.getLogger(__name__)

# ─── Specialty taxonomy (patient-facing) ────────────────────────────────────

SPECIALTY_MAP: Dict[str, str] = {
    "general_physician": "General Physician / Primary Care",
    "allergist": "Allergist / Immunologist",
    "endocrinologist": "Endocrinologist",
    "nephrologist": "Nephrologist",
    "cardiologist": "Cardiologist",
    "dermatologist": "Dermatologist",
    "gastroenterologist": "Gastroenterologist",
    "hematologist": "Hematologist",
    "neurologist": "Neurologist",
    "oncologist": "Oncologist",
    "ophthalmologist": "Ophthalmologist",
    "orthopedic": "Orthopedic Specialist",
    "psychiatrist": "Psychiatrist",
    "pulmonologist": "Pulmonologist",
    "rheumatologist": "Rheumatologist",
    "clinical_pharmacist": "Clinical Pharmacist",
}

# ─── Data classes ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class EvidenceItem:
    """One piece of supporting evidence for a recommendation."""
    date: Optional[str] = None
    source_file: Optional[str] = None
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CareRecommendation:
    """A single care-recommendation derived from patient records."""
    specialty: str          # patient-facing name
    specialty_key: str      # internal key (e.g. "allergist")
    relevance: str          # "high" | "moderate" | "possible" | "needs_clinical_review"
    title: str              # short label
    explanation: str        # one-sentence why
    evidence: List[EvidenceItem] = field(default_factory=list)
    source_records: int = 0  # how many documents contributed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "specialty": self.specialty,
            "specialty_key": self.specialty_key,
            "relevance": self.relevance,
            "title": self.title,
            "explanation": self.explanation,
            "evidence": [e.to_dict() for e in self.evidence],
            "source_records": self.source_records,
        }


# ─── Recommendation engine ──────────────────────────────────────────────────

def _contains_word(text: str, keyword: str) -> bool:
    """True if `keyword` appears in `text` as a whole word/token.

    Plain substring matching caused clinically wrong recommendations:
    "ast" matched "F-AST-ing Glucose" (liver referral for a glucose test),
    "alt" matched "Cholesterol, Total" via other substrings, "bp" matched
    unrelated names, etc. Word-boundary matching keeps "AST", "ALT",
    "eGFR", "LDL" working while rejecting accidental substrings.
    """
    return re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", text) is not None


def _matches_any_word(text: str, keywords: Iterable[str]) -> bool:
    return any(_contains_word(text, kw) for kw in keywords)


def _collect_allergy_conflicts(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract allergy conflicts from cross-check report."""
    return cross_check.get("allergy_conflicts", []) or []


def _collect_drug_interactions(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return cross_check.get("potential_drug_interactions", []) or []


def _collect_duplicate_prescriptions(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return cross_check.get("duplicate_prescriptions", []) or []


def _collect_conflicting_dosage(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return cross_check.get("conflicting_dosage_instructions", []) or []


def _collect_allergies(timeline: Dict[str, Any]) -> List[str]:
    return timeline.get("known_allergies", []) or []


def _collect_medications(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    return timeline.get("medications_timeline", []) or []


def _collect_lab_trends(lab_trends: Dict[str, Any]) -> List[Dict[str, Any]]:
    return lab_trends.get("trends", []) or []


def _collect_visits(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    return timeline.get("visits", []) or []


def generate_care_recommendations(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Analyze patient records and produce care recommendations.

    Returns a list of recommendation dicts sorted by relevance
    (high first), each with specialty, relevance, title, explanation,
    evidence, and source_records.
    """
    recommendations: Dict[str, CareRecommendation] = {}

    # ── Helper to upsert recommendation ──────────────────────────────────
    def _upsert(
        specialty_key: str,
        relevance: str,
        title: str,
        explanation: str,
        evidence_items: List[EvidenceItem],
        record_count: int = 1,
    ) -> None:
        specialty = SPECIALTY_MAP.get(specialty_key, specialty_key)
        existing = recommendations.get(specialty_key)
        if existing:
            # Keep the higher relevance
            rank = {"high": 0, "moderate": 1, "possible": 2, "needs_clinical_review": 3}
            if rank.get(relevance, 99) < rank.get(existing.relevance, 99):
                recommendations[specialty_key] = CareRecommendation(
                    specialty=specialty,
                    specialty_key=specialty_key,
                    relevance=relevance,
                    title=title,
                    explanation=explanation,
                    evidence=existing.evidence + evidence_items,
                    source_records=existing.source_records + record_count,
                )
            else:
                recommendations[specialty_key] = CareRecommendation(
                    specialty=specialty,
                    specialty_key=specialty_key,
                    relevance=existing.relevance,
                    title=existing.title,
                    explanation=existing.explanation,
                    evidence=existing.evidence + evidence_items,
                    source_records=existing.source_records + record_count,
                )
        else:
            recommendations[specialty_key] = CareRecommendation(
                specialty=specialty,
                specialty_key=specialty_key,
                relevance=relevance,
                title=title,
                explanation=explanation,
                evidence=evidence_items,
                source_records=record_count,
            )

    # ── 1. Allergy conflicts → Allergist ────────────────────────────────
    allergy_conflicts = _collect_allergy_conflicts(cross_check)
    if allergy_conflicts:
        evidence_items: List[EvidenceItem] = []
        for conflict in allergy_conflicts:
            med = conflict.get("medication", "")
            allergy = conflict.get("allergy", "")
            explanation = conflict.get("explanation", "")
            evidence_items.append(EvidenceItem(
                description=f"Medication allergy conflict: {med} ↔ {allergy}. {explanation}",
            ))
        _upsert(
            "allergist",
            "high" if len(allergy_conflicts) >= 2 else "moderate",
            "Allergy history review",
            f"MediMind found {len(allergy_conflicts)} allergy conflict(s) in your medication records that may require specialist review.",
            evidence_items,
            record_count=len(allergy_conflicts),
        )

    # ── 2. Drug interactions / duplicates / dosage conflicts → General Physician ──
    drug_interactions = _collect_drug_interactions(cross_check)
    duplicates = _collect_duplicate_prescriptions(cross_check)
    conflicting_dosage = _collect_conflicting_dosage(cross_check)
    med_safety_issues = len(drug_interactions) + len(duplicates) + len(conflicting_dosage)
    if med_safety_issues > 0:
        evidence_items = []
        for di in drug_interactions:
            meds = ", ".join(di.get("medications_involved", []))
            evidence_items.append(EvidenceItem(
                description=f"Drug interaction: {meds}. {di.get('explanation', '')}",
            ))
        for dup in duplicates:
            evidence_items.append(EvidenceItem(
                description=f"Duplicate prescription: {dup.get('medication', '')}. {dup.get('explanation', '')}",
            ))
        for cd in conflicting_dosage:
            evidence_items.append(EvidenceItem(
                description=f"Conflicting dosage: {cd.get('medication', '')}. {cd.get('explanation', '')}",
            ))
        relevance = "high" if med_safety_issues >= 3 else "moderate"
        _upsert(
            "general_physician",
            relevance,
            "Medication reconciliation",
            f"{med_safety_issues} medication safety issue(s) detected — a clinician should review your medication list.",
            evidence_items,
            record_count=med_safety_issues,
        )

    # ── 3. Known allergies without specialist mention → Allergist (moderate) ──
    known_allergies = _collect_allergies(timeline)
    if known_allergies and not allergy_conflicts:
        evidence_items = [EvidenceItem(description=f"Known allergy: {a}") for a in known_allergies]
        _upsert(
            "allergist",
            "moderate",
            "Allergy history review",
            f"Your records document {len(known_allergies)} known allergy/allergies.",
            evidence_items,
            record_count=len(known_allergies),
        )
    elif known_allergies and allergy_conflicts:
        # Already have high from conflicts — add moderate evidence for allergies
        evidence_items = [EvidenceItem(description=f"Known allergy: {a}") for a in known_allergies]
        _upsert(
            "allergist",
            "moderate",
            "Allergy history review",
            f"Your records document {len(known_allergies)} known allergy/allergies.",
            evidence_items,
            record_count=len(known_allergies),
        )

    # ── 4. Diabetes medications → Endocrinologist ────────────────────────
    medications = _collect_medications(timeline)
    # Antidiabetic agents only. Atorvastatin (a statin, previously listed
    # here by mistake) treats cholesterol, not diabetes — a patient on a
    # statin alone must not be told their records contain diabetes drugs.
    diabetes_keywords = {
        "metformin", "insulin", "glipizide", "glyburide", "gliclazide",
        "glimepiride", "pioglitazone", "sitagliptin", "linagliptin",
        "vildagliptin", "empagliflozin", "dapagliflozin", "canagliflozin",
        "semaglutide", "liraglutide", "dulaglutide", "acarbose",
    }
    diabetes_meds = [
        m for m in medications
        if _matches_any_word((m.get("name") or "").lower(), diabetes_keywords)
        or any(
            _matches_any_word((ing or "").lower(), diabetes_keywords)
            for ing in (m.get("ingredients") or [])
        )
    ]
    if diabetes_meds:
        evidence_items = [EvidenceItem(
            date=m.get("date"),
            source_file=m.get("source_file"),
            description=f"Medication: {m.get('name', '')} ({m.get('dosage', '')})",
        ) for m in diabetes_meds]
        _upsert(
            "endocrinologist",
            "moderate",
            "Diabetes management",
            f"Your records contain {len(diabetes_meds)} diabetes-related medication(s) that may benefit from specialist monitoring.",
            evidence_items,
            record_count=len(diabetes_meds),
        )

    # ── 5. Lab trends → various specialists ──────────────────────────────
    lab_trend_list = _collect_lab_trends(lab_trends)
    for trend in lab_trend_list:
        test_name = (trend.get("test_name", "") or "").lower()
        direction = (trend.get("direction", "") or "").lower()
        explanation = trend.get("explanation", "")

        # Kidney function. Directionality differs per marker: a FALLING
        # eGFR/GFR means declining filtration, while RISING creatinine/
        # urea/BUN means declining clearance. The concerning direction gets
        # "moderate"; the opposite (usually improvement) gets "possible".
        is_egfr = _matches_any_word(test_name, ("egfr", "gfr"))
        is_kidney_waste = _matches_any_word(test_name, ("creatinine", "urea", "bun", "kidney"))
        if is_egfr or is_kidney_waste:
            concerning = (
                direction in ("decreasing", "fluctuating (net decreasing)")
                if is_egfr
                else direction in ("increasing", "fluctuating (net increasing)")
            )
            if concerning:
                _upsert(
                    "nephrologist",
                    "moderate",
                    "Kidney function monitoring",
                    f"Your {trend.get('test_name', '')} trend ({direction}) may warrant specialist review. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )
            elif direction not in ("stable", ""):
                _upsert(
                    "nephrologist",
                    "possible",
                    "Kidney function monitoring",
                    f"Your {trend.get('test_name', '')} trend ({direction}) is noted. Continued monitoring may determine if specialist review is appropriate. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )

        # HbA1c / glucose / diabetes labs
        if _matches_any_word(test_name, ("hba1c", "a1c", "glucose", "glycated")):
            if direction in ("increasing", "fluctuating (net increasing)"):
                _upsert(
                    "endocrinologist",
                    "moderate",
                    "Diabetes management",
                    f"Your {trend.get('test_name', '')} trend ({direction}) indicates ongoing diabetes management needs. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )
            elif direction in ("decreasing", "fluctuating (net decreasing)"):
                _upsert(
                    "endocrinologist",
                    "possible",
                    "Diabetes management",
                    f"Your {trend.get('test_name', '')} trend ({direction}) suggests improvement but continued monitoring is recommended. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )

        # Lipid / cholesterol / cardiovascular. HDL is the protective
        # ("good") cholesterol: RISING HDL is an improvement and must not
        # be flagged as risk — only a FALLING HDL is concerning. For LDL /
        # total cholesterol / triglycerides, rising is the risk direction.
        is_hdl = _contains_word(test_name, "hdl")
        is_other_lipid = _matches_any_word(test_name, ("cholesterol", "lipid", "triglyceride", "triglycerides", "ldl", "vldl")) and not is_hdl
        lipid_concerning = (
            (is_hdl and direction in ("decreasing", "fluctuating (net decreasing)"))
            or (is_other_lipid and direction in ("increasing", "fluctuating (net increasing)"))
        )
        if lipid_concerning:
            _upsert(
                "cardiologist",
                "possible",
                "Cardiovascular monitoring",
                f"Your {trend.get('test_name', '')} trend ({direction}) may indicate cardiovascular risk factors. {explanation}",
                [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                record_count=1,
            )

        # Blood pressure / hypertension
        if _matches_any_word(test_name, ("blood pressure", "bp", "hypertension", "systolic", "diastolic")):
            if direction in ("increasing", "fluctuating (net increasing)"):
                _upsert(
                    "cardiologist",
                    "possible",
                    "Cardiovascular monitoring",
                    f"Your {trend.get('test_name', '')} trend ({direction}) may warrant cardiovascular evaluation. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )

        # Liver function. Word-boundary matching is essential here: plain
        # substring "ast" matched "Fasting Glucose" and produced a liver
        # recommendation for a rising glucose reading.
        if _matches_any_word(test_name, ("alt", "ast", "sgpt", "sgot", "ggt", "alp", "liver", "bilirubin", "hepatic", "transaminase")):
            if direction in ("increasing", "fluctuating (net increasing)"):
                _upsert(
                    "gastroenterologist",
                    "possible",
                    "Liver function monitoring",
                    f"Your {trend.get('test_name', '')} trend ({direction}) may require specialist evaluation. {explanation}",
                    [EvidenceItem(description=f"{trend.get('test_name', '')}: direction={direction}, explanation={explanation}")],
                    record_count=1,
                )

    # ── 6. General Physician — always a baseline recommendation if any data exists ──
    visit_count = len(_collect_visits(timeline))
    med_count = len(medications)
    if visit_count > 0 and med_count > 0 and "general_physician" not in recommendations:
        _upsert(
            "general_physician",
            "possible",
            "General health check",
            f"You have {visit_count} recorded visit(s) and {med_count} medication(s). A general physician can coordinate ongoing care.",
            [EvidenceItem(description=f"{visit_count} visits, {med_count} medications in records")],
            record_count=visit_count,
        )

    # ── 7. If no recommendations at all, create a generic one ────────────
    if not recommendations:
        _upsert(
            "general_physician",
            "possible",
            "General health check",
            "No specific care needs detected. A general physician can help maintain your health.",
            [],
            record_count=0,
        )

    # ── Sort by relevance (high first), then most supporting records ────
    relevance_order = {"high": 0, "moderate": 1, "possible": 2, "needs_clinical_review": 3}
    sorted_recs = sorted(
        recommendations.values(),
        key=lambda r: (relevance_order.get(r.relevance, 99), -r.source_records),
    )

    return [r.to_dict() for r in sorted_recs]
