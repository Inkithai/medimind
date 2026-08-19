"""
Care-recommendation engine.

Analyses a patient's medical records (timeline, cross-check report,
lab trends) and produces a ranked list of care-recommendation objects
that the frontend renders as actionable cards.

Each recommendation has:
  - specialty: patient-facing specialty name
    (e.g. "General Physician / Primary Care")
  - specialty_key: stable identifier (e.g. "general_physician")
  - relevance: "high" | "moderate" | "possible"
  - relevance_score: 0–100 number representing how strongly the
    patient's records support searching for this type of care.
    This is an *informational ranking*, not a clinical probability
    or diagnosis.
  - score_factors: list of {label, points, evidence} explaining the
    numerical score in a transparent way.
  - title: short label (e.g. "Medication reconciliation")
  - reason: one-sentence patient-friendly explanation
  - evidence: list of evidence strings (source file, date, etc.)
  - source_records: number of relevant documents
  - has_safety_signal: True when the recommendation was driven by
    a safety-relevant finding (allergy conflict, drug interaction,
    duplicate, dosage conflict). The frontend uses this to render
    a compact "Medication/allergy conflict" indicator inline.
  - safety_message: optional one-liner shown next to the safety
    indicator.

This module is pure logic — no LLM calls. It reads structured data
already extracted by medical_extractor.py and lab_trends.py.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── Specialty taxonomy (patient-facing) ────────────────────────────────────

SPECIALTY_MAP: Dict[str, str] = {
    "general_physician": "General Physician / Primary Care",
    "clinical_pharmacist": "Clinical Pharmacist",
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
}

# Patient-facing display name for the "Find nearby" / search label.
SPECIALTY_DISPLAY: Dict[str, str] = {
    "general_physician": "General Physician / Primary Care",
    "clinical_pharmacist": "Clinical Pharmacist",
    "allergist": "Allergy / Immunology",
    "endocrinologist": "Endocrinology / Diabetes",
    "nephrologist": "Nephrology",
    "cardiologist": "Cardiology",
    "dermatologist": "Dermatology",
    "gastroenterologist": "Gastroenterology",
    "hematologist": "Hematology",
    "neurologist": "Neurology",
    "oncologist": "Oncology",
    "ophthalmologist": "Ophthalmology",
    "orthopedic": "Orthopedic Specialist",
    "psychiatrist": "Psychiatry",
    "pulmonologist": "Pulmonology",
    "rheumatologist": "Rheumatology",
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
class ScoreFactor:
    """One factor that contributed to a recommendation's score.

    The frontend renders this as a transparent "what contributed to
    this percentage" disclosure so the score is not a black box.
    """

    label: str
    points: int
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CareRecommendation:
    """A single care-recommendation derived from patient records."""

    specialty: str
    specialty_key: str
    relevance: str  # "high" | "moderate" | "possible"
    relevance_score: int  # 0..100
    title: str
    reason: str  # one-sentence patient-friendly why
    evidence: List[EvidenceItem] = field(default_factory=list)
    source_records: int = 0  # how many documents contributed
    score_factors: List[ScoreFactor] = field(default_factory=list)
    has_safety_signal: bool = False
    safety_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "specialty": self.specialty,
            "specialty_key": self.specialty_key,
            "relevance": self.relevance,
            "relevance_score": self.relevance_score,
            "title": self.title,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "source_records": self.source_records,
            "score_factors": [f.to_dict() for f in self.score_factors],
            "has_safety_signal": self.has_safety_signal,
            "safety_message": self.safety_message,
        }


# ─── Relevance / scoring constants ──────────────────────────────────────────

# Score thresholds. The engine adds up points from contributing factors
# and clamps to [0, 100]. The thresholds are tuned so that, for the
# typical patient with a real medical history, the top specialty lands
# in the "high" band (>=75) and supporting specialties in the
# "moderate" (>=55) or "possible" (>=35) bands. "possible" is a
# soft mention only — the frontend hides it under "Show all".
SCORE_HIGH = 75
SCORE_MODERATE = 55
SCORE_POSSIBLE = 30
SCORE_MIN_TO_SHOW = 25

# Maximum points any single category can contribute to a single
# recommendation. This prevents one very long medication list from
# overwhelming a strong safety signal. We allow generous caps so
# that a single very strong finding (e.g. a confirmed diabetes
# diagnosis with multiple medications and a worsening HbA1c trend)
# can carry a recommendation into the high band on its own — the
# factors are still listed transparently for the user to see.
MAX_FACTOR_POINTS = 50

# Safety signal weight: when a recommendation is driven primarily by
# a safety finding (allergy conflict, drug interaction, duplicate,
# dosage conflict), boost the floor of the score so it never gets
# pushed below the "moderate" band — a safety concern should always
# be at least visible.
SAFETY_FLOOR = 55


# ─── Helpers ────────────────────────────────────────────────────────────────


def _evidence_from_visit(visit: Dict[str, Any]) -> List[EvidenceItem]:
    """Build evidence items from a visit/visit page."""
    items: List[EvidenceItem] = []
    date = visit.get("date")
    source = visit.get("_source", {})
    source_file = source.get("file") if isinstance(source, dict) else None

    for med in visit.get("medications", []):
        items.append(
            EvidenceItem(
                date=date,
                source_file=source_file,
                description=f"Medication: {med.get('name', 'unknown')} ({med.get('dosage', '')})",
            )
        )
    for lr in visit.get("lab_results", []):
        flag = lr.get("flag", "unknown")
        items.append(
            EvidenceItem(
                date=date,
                source_file=source_file,
                description=f"Lab result: {lr.get('test_name', '')} = {lr.get('value', '')} {lr.get('unit', '')} [{flag}]",  # noqa: E501
            )
        )
    for allergy in visit.get("allergies_noted", []):
        items.append(
            EvidenceItem(
                date=date,
                source_file=source_file,
                description=f"Allergy noted: {allergy}",
            )
        )
    return items


def _collect_allergy_conflicts(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (cross_check or {}).get("allergy_conflicts", []) or []


def _collect_drug_interactions(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (cross_check or {}).get("potential_drug_interactions", []) or []


def _collect_duplicate_prescriptions(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (cross_check or {}).get("duplicate_prescriptions", []) or []


def _collect_conflicting_dosage(cross_check: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (cross_check or {}).get("conflicting_dosage_instructions", []) or []


def _collect_allergies(timeline: Dict[str, Any]) -> List[str]:
    raw = (timeline or {}).get("known_allergies", []) or []
    # Defensive: known_allergies should be a list of strings, but a malformed
    # timeline (e.g. a single string from a DB bug) would otherwise iterate
    # over characters. Coerce to a clean list of unique strings.
    if isinstance(raw, str):
        return [raw] if raw else []
    if not isinstance(raw, list):
        return []
    return [str(a) for a in raw if isinstance(a, (str, int, float)) and str(a)]


def _collect_medications(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (timeline or {}).get("medications_timeline", []) or []
    return raw if isinstance(raw, list) else []


def _collect_lab_trends(lab_trends: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (lab_trends or {}).get("trends", []) or []
    return raw if isinstance(raw, list) else []


def _collect_visits(timeline: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = (timeline or {}).get("visits", []) or []
    return raw if isinstance(raw, list) else []


def _bucket_for_score(score: int) -> str:
    if score >= SCORE_HIGH:
        return "high"
    if score >= SCORE_MODERATE:
        return "moderate"
    return "possible"


def _cap_points(points: int) -> int:
    """Cap a single factor's contribution to MAX_FACTOR_POINTS."""
    return max(0, min(MAX_FACTOR_POINTS, points))


# ─── Diabetes / endocrine keyword set ───────────────────────────────────────

_DIABETES_MED_KEYWORDS = (
    "metformin",
    "insulin",
    "glipizide",
    "glyburide",
    "pioglitazone",
    "sitagliptin",
    "empagliflozin",
    "dapagliflozin",
    "semaglutide",
    "liraglutide",
    "canagliflozin",
)

_DIABETES_LAB_KEYWORDS = ("hba1c", "a1c", "glucose", "fasting glucose")

# Note: atorvastatin/lipid keywords are intentionally NOT in the
# diabetes set. Statins are commonly prescribed for cardiovascular
# risk; their presence alone should not trigger an endocrinology
# recommendation. HbA1c / glucose labs and explicit diabetes
# medications are the endocrine signal.


# ─── Recommendation engine ──────────────────────────────────────────────────


def generate_care_recommendations(
    timeline: Dict[str, Any],
    cross_check: Dict[str, Any],
    lab_trends: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Analyze patient records and produce care recommendations.

    Returns a list of recommendation dicts sorted by score (high
    first), each with specialty, relevance, relevance_score, title,
    reason, evidence, score_factors, and source_records.
    """
    recommendations: Dict[str, CareRecommendation] = {}

    medications = _collect_medications(timeline)
    visits = _collect_visits(timeline)
    known_allergies = _collect_allergies(timeline)
    allergy_conflicts = _collect_allergy_conflicts(cross_check)
    drug_interactions = _collect_drug_interactions(cross_check)
    duplicates = _collect_duplicate_prescriptions(cross_check)
    conflicting_dosage = _collect_conflicting_dosage(cross_check)
    lab_trend_list = _collect_lab_trends(lab_trends)

    def _upsert(rec: CareRecommendation) -> None:
        existing = recommendations.get(rec.specialty_key)
        if not existing:
            recommendations[rec.specialty_key] = rec
            return
        # If both fire, keep the higher score and merge factors.
        if rec.relevance_score > existing.relevance_score:
            merged_factors = list(existing.score_factors) + list(rec.score_factors)
            merged_evidence = list(existing.evidence) + list(rec.evidence)
            recommendations[rec.specialty_key] = CareRecommendation(
                specialty=rec.specialty,
                specialty_key=rec.specialty_key,
                relevance=rec.relevance,
                relevance_score=rec.relevance_score,
                title=rec.title,
                reason=rec.reason,
                evidence=merged_evidence,
                source_records=existing.source_records + rec.source_records,
                score_factors=merged_factors,
                has_safety_signal=existing.has_safety_signal or rec.has_safety_signal,
                safety_message=existing.safety_message or rec.safety_message,
            )
        else:
            # Keep the existing recommendation but accumulate factors
            # and evidence so the score breakdown is complete.
            merged_factors = list(existing.score_factors) + list(rec.score_factors)
            merged_evidence = list(existing.evidence) + list(rec.evidence)
            recommendations[rec.specialty_key] = CareRecommendation(
                specialty=existing.specialty,
                specialty_key=existing.specialty_key,
                relevance=existing.relevance,
                relevance_score=existing.relevance_score,
                title=existing.title,
                reason=existing.reason,
                evidence=merged_evidence,
                source_records=existing.source_records + rec.source_records,
                score_factors=merged_factors,
                has_safety_signal=existing.has_safety_signal or rec.has_safety_signal,
                safety_message=existing.safety_message or rec.safety_message,
            )

    # ── 1. Allergy conflicts → Allergist (high signal) ─────────────────
    if allergy_conflicts:
        evidence_items: List[EvidenceItem] = []
        score_factors: List[ScoreFactor] = []
        safety_messages: List[str] = []
        for conflict in allergy_conflicts:
            med = conflict.get("medication", "")
            allergy = conflict.get("allergy", "")
            explanation = conflict.get("explanation", "")
            evidence_items.append(
                EvidenceItem(
                    description=f"Medication allergy conflict: {med} ↔ {allergy}. {explanation}",
                )
            )
            safety_messages.append(f"{med} is listed while a {allergy} allergy is documented.")

        # An explicit allergy conflict is a strong safety signal and a
        # near-direct indication for an allergy specialist. A single
        # documented conflict already warrants a high relevance score;
        # multiple conflicts push the score into the "high" band.
        conflict_points = _cap_points(55 + 8 * max(0, len(allergy_conflicts) - 1))
        score_factors.append(
            ScoreFactor(
                label="Medication/allergy conflict",
                points=conflict_points,
                note=f"{len(allergy_conflicts)} conflict(s) detected in cross-check",
            )
        )
        if known_allergies:
            score_factors.append(
                ScoreFactor(
                    label="Documented allergy",
                    points=12,
                    note=f"{len(known_allergies)} known allergy/allergies in records",
                )
            )

        score = max(SAFETY_FLOOR, conflict_points + (12 if known_allergies else 0))
        title = "Allergy review"
        reason = (
            f"An allergy to {' / '.join({c.get('allergy', '') for c in allergy_conflicts} or ['a documented allergen'])} "  # noqa: E501
            f"is recorded and at least one current medication appears to conflict with it. "
            f"An allergy specialist can clarify the safest options."
        )

        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["allergist"],
                specialty_key="allergist",
                relevance=_bucket_for_score(score),
                relevance_score=score,
                title=title,
                reason=reason,
                evidence=evidence_items,
                source_records=len(allergy_conflicts),
                score_factors=score_factors,
                has_safety_signal=True,
                safety_message="; ".join(safety_messages),
            )
        )

    # ── 2. Drug interactions / duplicates / dosage conflicts ────────────
    #    → primarily General Physician + Clinical Pharmacist
    med_safety_issues: List[Tuple[str, EvidenceItem, str]] = []
    for di in drug_interactions:
        meds = ", ".join(di.get("medications_involved", []))
        med_safety_issues.append(
            (
                "Drug interaction",
                EvidenceItem(description=f"Drug interaction: {meds}. {di.get('explanation', '')}"),
                meds,
            )
        )
    for dup in duplicates:
        med_safety_issues.append(
            (
                "Duplicate prescription",
                EvidenceItem(
                    description=f"Duplicate prescription: {dup.get('medication', '')}. {dup.get('explanation', '')}"  # noqa: E501
                ),
                dup.get("medication", ""),
            )
        )
    for cd in conflicting_dosage:
        med_safety_issues.append(
            (
                "Conflicting dosage",
                EvidenceItem(
                    description=f"Conflicting dosage: {cd.get('medication', '')}. {cd.get('explanation', '')}"  # noqa: E501
                ),
                cd.get("medication", ""),
            )
        )

    if med_safety_issues:
        # 2a. General Physician (coordinates the reconciliation)
        # When there are medication safety findings, a primary-care
        # physician is almost always the right place to start — they
        # own the full medication list, can refer to specialists, and
        # can order the lab follow-up. We boost the score to reflect
        # that, but keep the factors transparent.
        gp_factors: List[ScoreFactor] = []
        gp_evidence: List[EvidenceItem] = []
        issue_count = len(med_safety_issues)
        gp_safety_points = min(35, 22 + 5 * max(0, issue_count - 1))
        gp_factors.append(
            ScoreFactor(
                label="Medication safety issues",
                points=gp_safety_points,
                note=f"{issue_count} interaction/duplicate/dosage issue(s) detected",
            )
        )
        if len(medications) >= 3:
            gp_factors.append(
                ScoreFactor(
                    label="Multiple medications",
                    points=min(15, 8 + max(0, len(medications) - 3)),
                    note=f"{len(medications)} active medication(s) in records",
                )
            )
        if len(visits) >= 2:
            gp_factors.append(
                ScoreFactor(
                    label="Multiple care encounters",
                    points=min(10, 4 + max(0, len(visits) - 2)),
                    note=f"{len(visits)} visit(s) across providers",
                )
            )
        if known_allergies:
            gp_factors.append(
                ScoreFactor(
                    label="Known allergies to track",
                    points=min(8, 4 + max(0, len(known_allergies) - 1)),
                    note=f"{len(known_allergies)} allergy/allergies",
                )
            )
        gp_score = max(SAFETY_FLOOR, sum(f.points for f in gp_factors))
        # Cap at 95 so a primary care recommendation never claims
        # absolute certainty; it leaves room for stronger specialist
        # signals (e.g. confirmed T2DM with HbA1c 9.2%).
        gp_score = min(gp_score, 95)
        for _, ev, _ in med_safety_issues:
            gp_evidence.append(ev)

        gp_title = "Medication reconciliation"
        gp_reason = (
            f"{issue_count} medication safety finding(s) — including possible drug interactions, "
            f"duplicate prescriptions, or conflicting instructions — were detected across your records. "  # noqa: E501
            f"A general physician can review the full medication list and reconcile any discrepancies."  # noqa: E501
        )
        # Build a single short safety message for the card badge. If there
        # is also an allergy conflict, surface it too — allergy conflicts
        # are the most urgent signal and should never be hidden behind a
        # drug-interaction message.
        safety_msgs: List[str] = []
        if issue_count == 1:
            safety_msgs.append(
                f"{med_safety_issues[0][0].lower()} found in your medication list — review recommended."  # noqa: E501
            )
        else:
            safety_msgs.append(f"{issue_count} medication safety findings — review recommended.")
        if allergy_conflicts:
            allergy_names = sorted(
                {c.get("allergy", "") for c in allergy_conflicts if c.get("allergy")}
            )
            safety_msgs.insert(
                0,
                f"Allergy conflict: {', '.join(allergy_names)} — review recommended.",
            )
        safety_msg = " ".join(safety_msgs)
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["general_physician"],
                specialty_key="general_physician",
                relevance=_bucket_for_score(gp_score),
                relevance_score=gp_score,
                title=gp_title,
                reason=gp_reason,
                evidence=gp_evidence,
                source_records=issue_count,
                score_factors=gp_factors,
                has_safety_signal=True,
                safety_message=safety_msg,
            )
        )

        # 2b. Clinical Pharmacist (specialist perspective on meds)
        cp_factors: List[ScoreFactor] = []
        cp_evidence: List[EvidenceItem] = []
        cp_points = min(28, 18 + 3 * max(0, issue_count - 1))
        cp_factors.append(
            ScoreFactor(
                label="Medication safety issues",
                points=cp_points,
                note=f"{issue_count} interaction/duplicate/dosage issue(s)",
            )
        )
        if len(medications) >= 4:
            cp_factors.append(
                ScoreFactor(
                    label="Polypharmacy",
                    points=min(12, 6 + max(0, len(medications) - 4)),
                    note=f"{len(medications)} active medication(s)",
                )
            )
        cp_score = max(50, sum(f.points for f in cp_factors))
        for _, ev, _ in med_safety_issues:
            cp_evidence.append(ev)
        cp_title = "Medication review"
        cp_reason = (
            f"A clinical pharmacist specialises in reviewing medication lists, identifying interactions, "  # noqa: E501
            f"and simplifying complex regimens. {issue_count} safety finding(s) were found in your records."  # noqa: E501
        )
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["clinical_pharmacist"],
                specialty_key="clinical_pharmacist",
                relevance=_bucket_for_score(cp_score),
                relevance_score=cp_score,
                title=cp_title,
                reason=cp_reason,
                evidence=cp_evidence,
                source_records=issue_count,
                score_factors=cp_factors,
                has_safety_signal=True,
                safety_message=None,
            )
        )

    # ── 3. Known allergies without explicit conflicts → Allergist ───────
    if known_allergies and not allergy_conflicts:
        evidence_items = [EvidenceItem(description=f"Known allergy: {a}") for a in known_allergies]
        score_factors = [
            ScoreFactor(
                label="Documented allergy",
                points=min(30, 18 + 4 * max(0, len(known_allergies) - 1)),
                note=f"{len(known_allergies)} known allergy/allergies",
            )
        ]
        score = sum(f.points for f in score_factors)
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["allergist"],
                specialty_key="allergist",
                relevance=_bucket_for_score(score),
                relevance_score=score,
                title="Allergy history review",
                reason=(
                    f"{len(known_allergies)} allergy/allergies {'is' if len(known_allergies) == 1 else 'are'} "  # noqa: E501
                    f"documented. An allergy specialist can confirm triggers, update your list, and advise on "  # noqa: E501
                    f"safe medication choices."
                ),
                evidence=evidence_items,
                source_records=len(known_allergies),
                score_factors=score_factors,
            )
        )

    # ── 4. Diabetes (meds + labs) → Endocrinologist ────────────────────
    diabetes_meds = [
        m
        for m in medications
        if any(kw in (m.get("name", "").lower()) for kw in _DIABETES_MED_KEYWORDS)
    ]
    endo_factors: List[ScoreFactor] = []
    endo_evidence: List[EvidenceItem] = []
    if diabetes_meds:
        endo_factors.append(
            ScoreFactor(
                label="Diabetes medication",
                points=min(45, 30 + 5 * max(0, len(diabetes_meds) - 1)),
                note=f"{len(diabetes_meds)} diabetes medication(s)",
            )
        )
        for m in diabetes_meds:
            endo_evidence.append(
                EvidenceItem(
                    date=m.get("date"),
                    source_file=m.get("source_file"),
                    description=f"Medication: {m.get('name', '')} ({m.get('dosage', '')})",
                )
            )

    # Lab trends that are diagnostic of diabetes activity. Dedupe by
    # (test_name, direction-bucket) so the same trend contributed by
    # multiple visits does not show up as N identical score factors.
    diabetes_lab_trends = 0
    seen_endo_trends: set = set()
    for trend in lab_trend_list:
        test_name = (trend.get("test_name", "") or "").lower()
        direction = (trend.get("direction", "") or "").lower()
        if not test_name or not any(kw in test_name for kw in _DIABETES_LAB_KEYWORDS):
            continue
        diabetes_lab_trends += 1
        if direction in ("increasing", "fluctuating (net increasing)"):
            bucket = "rising"
        elif direction in ("decreasing", "fluctuating (net decreasing)"):
            bucket = "improving"
        else:
            # Stable direction (e.g. "stable") — not worth a factor, but
            # still count the trend as evidence.
            endo_evidence.append(
                EvidenceItem(
                    description=f"{trend.get('test_name', '')}: {direction or 'stable'} — {trend.get('explanation', '')}",  # noqa: E501
                )
            )
            continue
        dedupe_key = (trend.get("test_name", ""), bucket)
        if dedupe_key in seen_endo_trends:
            # Still record the evidence, but don't add a duplicate factor.
            endo_evidence.append(
                EvidenceItem(
                    description=f"{trend.get('test_name', '')}: {direction} — {trend.get('explanation', '')}",  # noqa: E501
                )
            )
            continue
        seen_endo_trends.add(dedupe_key)
        if bucket == "rising":
            endo_factors.append(
                ScoreFactor(
                    label=f"Lab trend — {trend.get('test_name', '')} rising",
                    points=28,
                    note=trend.get("explanation", "") or "glucose control worsening",
                )
            )
        else:
            endo_factors.append(
                ScoreFactor(
                    label=f"Lab trend — {trend.get('test_name', '')} improving",
                    points=18,
                    note=trend.get("explanation", "") or "glucose control improving",
                )
            )
        endo_evidence.append(
            EvidenceItem(
                description=f"{trend.get('test_name', '')}: {direction} — {trend.get('explanation', '')}",  # noqa: E501
            )
        )

    if endo_factors:
        endo_score = min(sum(f.points for f in endo_factors), 92)
        # Build an honest reason that doesn't oversell what the records
        # contain. Mention trends only when at least one was found;
        # otherwise lead with the medication evidence.
        if diabetes_lab_trends > 0:
            endo_reason = (
                "Your records show diabetes-related medication(s) and glucose/HbA1c trends. "
                "An endocrinologist specialises in long-term diabetes management and treatment "
                "adjustments."
            )
        else:
            endo_reason = (
                "Your records include diabetes medication(s) (e.g. Metformin). An endocrinologist "
                "specialises in long-term diabetes management and can help confirm the diagnosis, "
                "adjust treatment, and order follow-up labs."
            )
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["endocrinologist"],
                specialty_key="endocrinologist",
                relevance=_bucket_for_score(endo_score),
                relevance_score=endo_score,
                title="Ongoing diabetes management",
                reason=endo_reason,
                evidence=endo_evidence,
                source_records=len(diabetes_meds) + diabetes_lab_trends,
                score_factors=endo_factors,
            )
        )

    # ── 5. Kidney lab trends → Nephrologist ────────────────────────────
    kidney_factors: List[ScoreFactor] = []
    kidney_evidence: List[EvidenceItem] = []
    seen_kidney_trends: set = set()
    for trend in lab_trend_list:
        test_name = (trend.get("test_name", "") or "").lower()
        direction = (trend.get("direction", "") or "").lower()
        if not test_name or not (
            "egfr" in test_name or "creatinine" in test_name or "kidney" in test_name
        ):
            continue
        if direction in ("decreasing", "fluctuating (net decreasing)"):
            bucket = "declining"
        elif "creatinine" in test_name and direction in (
            "increasing",
            "fluctuating (net increasing)",
        ):
            bucket = "rising_creatinine"
        elif direction in ("increasing", "fluctuating (net increasing)"):
            bucket = "rising"
        else:
            kidney_evidence.append(
                EvidenceItem(
                    description=f"{trend.get('test_name', '')}: {direction or 'stable'} — {trend.get('explanation', '')}",  # noqa: E501
                )
            )
            continue
        dedupe_key = (trend.get("test_name", ""), bucket)
        if dedupe_key in seen_kidney_trends:
            kidney_evidence.append(
                EvidenceItem(
                    description=f"{trend.get('test_name', '')}: {direction} — {trend.get('explanation', '')}",  # noqa: E501
                )
            )
            continue
        seen_kidney_trends.add(dedupe_key)
        if bucket == "declining":
            kidney_factors.append(
                ScoreFactor(
                    label=f"Lab trend — {trend.get('test_name', '')} declining",
                    points=20,
                    note=trend.get("explanation", "") or "kidney function trending down",
                )
            )
        elif bucket == "rising_creatinine":
            kidney_factors.append(
                ScoreFactor(
                    label=f"Lab trend — {trend.get('test_name', '')} rising",
                    points=18,
                    note=trend.get("explanation", "") or "creatinine trending up",
                )
            )
        else:
            kidney_factors.append(
                ScoreFactor(
                    label=f"Lab trend — {trend.get('test_name', '')} rising",
                    points=10,
                    note=trend.get("explanation", "") or "kidney marker rising",
                )
            )
        kidney_evidence.append(
            EvidenceItem(
                description=f"{trend.get('test_name', '')}: {direction} — {trend.get('explanation', '')}",  # noqa: E501
            )
        )

    if kidney_factors:
        kidney_score = min(sum(f.points for f in kidney_factors), 75)
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["nephrologist"],
                specialty_key="nephrologist",
                relevance=_bucket_for_score(kidney_score),
                relevance_score=kidney_score,
                title="Kidney function monitoring",
                reason=(
                    "Your kidney-function markers (e.g. eGFR, creatinine) show a trend that may benefit "  # noqa: E501
                    "from specialist monitoring. A nephrologist can interpret these patterns in the "  # noqa: E501
                    "context of your other medications."
                ),
                evidence=kidney_evidence,
                source_records=len(kidney_factors),
                score_factors=kidney_factors,
            )
        )

    # ── 6. General Physician baseline ─────────────────────────────────
    #    A primary-care physician is a baseline option whenever the
    #    patient has any meaningful history — they coordinate care,
    #    can refer to specialists, and reconcile medications. We give
    #    the GP a fair score derived from the same evidence the
    #    specialists see; we don't artificially cap it low, because
    #    for a patient with multiple meds + multiple providers + a
    #    safety signal, the GP genuinely *is* the most relevant next
    #    step. This block creates a baseline only if no safety-driven
    #    GP rec already exists.
    if "general_physician" not in recommendations and (visits or medications or known_allergies):
        gp_baseline_factors: List[ScoreFactor] = []

        # Patient-coordination signals (always positive). These
        # alone can push GP into the high band — multiple
        # medications across multiple providers is a strong
        # primary-care case.
        if len(medications) >= 2:
            gp_baseline_factors.append(
                ScoreFactor(
                    label="Multiple medications",
                    points=min(30, 20 + max(0, len(medications) - 2) * 3),
                    note=f"{len(medications)} active medication(s)",
                )
            )
        if len(visits) >= 2:
            gp_baseline_factors.append(
                ScoreFactor(
                    label="Multiple visits / providers",
                    points=min(24, 16 + max(0, len(visits) - 2) * 2),
                    note=f"{len(visits)} visit(s)",
                )
            )
        if known_allergies:
            gp_baseline_factors.append(
                ScoreFactor(
                    label="Documented allergies",
                    points=min(16, 10 + max(0, len(known_allergies) - 1) * 2),
                    note=f"{len(known_allergies)} allergy/allergies to track",
                )
            )

        # Safety signals also drive the GP recommendation — they are
        # often the right person to *review* the safety issue and
        # coordinate the next step, even if a specialist is also
        # warranted.
        if allergy_conflicts:
            gp_baseline_factors.append(
                ScoreFactor(
                    label="Allergy/safety signal",
                    points=min(30, 20 + 5 * max(0, len(allergy_conflicts) - 1)),
                    note=f"{len(allergy_conflicts)} medication/allergy conflict(s)",
                )
            )

        # If we still have no factors (only one med or visit), keep GP as
        # an honest "possible" baseline.
        if not gp_baseline_factors:
            gp_baseline_factors.append(
                ScoreFactor(
                    label="Records present",
                    points=35,
                    note="A general physician can help maintain your overall health.",
                )
            )
        baseline_score = sum(f.points for f in gp_baseline_factors)
        # Cap at 92 so that very strong single-specialist signals
        # (e.g. confirmed worsening T2DM with high HbA1c) can still
        # outrank a general baseline. In typical Anjali-like data the
        # GP lands in the 80s — the natural top of the list.
        baseline_score = min(baseline_score, 92)

        # Title flips to "Medication reconciliation" when there's a
        # safety driver, so the card label reflects the *actual*
        # reason GP is the top pick.
        baseline_title = (
            "Medication reconciliation"
            if (allergy_conflicts or med_safety_issues)
            else "General health overview"
        )
        if allergy_conflicts and not med_safety_issues:
            baseline_reason = (
                f"{len(allergy_conflicts)} medication/allergy conflict(s) were found in your records. "  # noqa: E501
                f"A general physician can review the full medication list, confirm the safest next step, "  # noqa: E501
                f"and refer you to a specialist if needed."
            )
        elif med_safety_issues:
            baseline_reason = (
                f"{len(med_safety_issues)} medication safety finding(s) were detected. A general physician "  # noqa: E501
                f"can review the full medication list, reconcile any discrepancies, and coordinate any "  # noqa: E501
                f"specialist referrals."
            )
        else:
            baseline_reason = (
                "A general physician can coordinate your overall care, review your medication list, "  # noqa: E501
                "and help you decide whether to see any of the specialists suggested above."
            )
        baseline_safety_msg: Optional[str] = None
        # If both allergy and drug-safety signals exist, surface both —
        # allergy is the more urgent message and should not be hidden.
        if allergy_conflicts and med_safety_issues:
            allergy_names = sorted(
                {c.get("allergy", "") for c in allergy_conflicts if c.get("allergy")}
            )
            sample_issue = med_safety_issues[0]
            secondary = (
                f"{sample_issue[0].lower()} found in your medication list — review recommended."
                if len(med_safety_issues) == 1
                else f"{len(med_safety_issues)} medication safety findings — review recommended."
            )
            baseline_safety_msg = (
                f"Allergy conflict: {', '.join(allergy_names)} — review recommended. {secondary}"
            )
        elif allergy_conflicts and not med_safety_issues:
            baseline_safety_msg = f"Allergy conflict: {', '.join({c.get('allergy', '') for c in allergy_conflicts} or ['documented allergen'])} — review recommended."  # noqa: E501
        elif med_safety_issues:
            sample_issue = med_safety_issues[0]
            baseline_safety_msg = (
                f"{sample_issue[0].lower()} found in your medication list — review recommended."
                if len(med_safety_issues) == 1
                else f"{len(med_safety_issues)} medication safety findings — review recommended."
            )

        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["general_physician"],
                specialty_key="general_physician",
                relevance=_bucket_for_score(baseline_score),
                relevance_score=baseline_score,
                title=baseline_title,
                reason=baseline_reason,
                evidence=[
                    EvidenceItem(
                        description=(
                            f"{len(visits)} visit(s), {len(medications)} medication(s), "
                            f"{len(known_allergies)} known allergy/allergies"
                            + (
                                f", {len(allergy_conflicts)} allergy conflict(s)"
                                if allergy_conflicts
                                else ""
                            )
                        ),
                    )
                ],
                source_records=max(1, len(visits) + len(medications)),
                score_factors=gp_baseline_factors,
                has_safety_signal=bool(allergy_conflicts or med_safety_issues),
                safety_message=baseline_safety_msg,
            )
        )

    # ── 7. Fallback when nothing else fired ────────────────────────────
    if not recommendations:
        _upsert(
            CareRecommendation(
                specialty=SPECIALTY_MAP["general_physician"],
                specialty_key="general_physician",
                relevance="possible",
                relevance_score=35,
                title="General health check",
                reason=(
                    "No specific care needs were detected in your records. "
                    "A general physician can help maintain your overall health."
                ),
                evidence=[],
                source_records=0,
                score_factors=[
                    ScoreFactor(
                        label="Default baseline",
                        points=35,
                        note="No specific signals found in records",
                    )
                ],
            )
        )

    # ── Sort by score, with stable tiebreakers ─────────────────────────
    sorted_recs = sorted(
        recommendations.values(),
        key=lambda r: (-r.relevance_score, -(1 if r.has_safety_signal else 0), r.specialty_key),
    )

    return [r.to_dict() for r in sorted_recs]
