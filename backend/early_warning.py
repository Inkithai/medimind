"""
Early-Warning Score (deterministic)
===================================
Combines the most recent vital signs and key lab values into a single
deterioration screen, using National Early Warning Score (NEWS2)-style
sub-scoring. This is a SCREENING aid — a high score means "several recent
readings are abnormal, talk to a clinician soon/now", never a diagnosis.

It is fed entirely from the patient's own extracted vitals/labs via
clinical_lab_values and vital_trends parsers. Any missing input simply
contributes 0 (no point), so a sparse record produces a low score rather than
a misleading one. The score is conservative and clearly labelled as
not-validated-for-diagnosis.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from clinical_lab_values import collect_lab_values
from vital_trends import _VITALS, _series_for  # reuse the vital parsers


def _points_for(value: Optional[float], bands: List[Tuple[float, float, int]]) -> int:
    """bands: list of (low_inclusive, high_exclusive, points). Returns points
    for the band the value falls into, else 0."""
    if value is None:
        return 0
    for lo, hi, pts in bands:
        if lo <= value < hi:
            return pts
    # above the top band: take the top band's points (handles open-ended high)
    return bands[-1][2] if bands else 0


def _latest_numeric_vital(timeline: Dict[str, Any], key: str) -> Optional[float]:
    series = _series_for(timeline, key, _VITALS[key][1])
    if not series:
        return None
    last = series[-1]
    if key == "blood_pressure":
        return last["systolic"]
    return last.get("numeric")


def compute_early_warning_score(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Compute an aggregate deterioration-risk score (NEWS2-style)."""
    components: List[Dict[str, Any]] = []
    total = 0

    def add(name: str, value: Optional[float], pts: int, max_pts: int, detail: str) -> None:
        nonlocal total
        components.append(
            {
                "signal": name,
                "value": value,
                "points": pts,
                "max_points": max_pts,
                "detail": detail,
            }
        )
        total += pts

    rr = _latest_numeric_vital(timeline, "respiratory_rate")
    add(
        "respiratory_rate",
        rr,
        _points_for(rr, [(0, 8, 3), (8, 12, 1), (12, 21, 0), (21, 25, 2), (25, 1000, 3)]),
        3,
        "Breaths/min",
    )

    spo2 = _latest_numeric_vital(timeline, "oxygen_saturation")
    add(
        "oxygen_saturation",
        spo2,
        _points_for(spo2, [(0, 92, 3), (92, 94, 2), (94, 96, 1), (96, 101, 0)]),
        3,
        "SpO2 %",
    )

    hr = _latest_numeric_vital(timeline, "heart_rate")
    add(
        "heart_rate",
        hr,
        _points_for(
            hr, [(0, 41, 3), (41, 51, 1), (51, 91, 0), (91, 111, 1), (111, 131, 2), (131, 1000, 3)]
        ),
        3,
        "Beats/min",
    )

    systolic = _latest_numeric_vital(timeline, "blood_pressure")
    add(
        "systolic_bp",
        systolic,
        _points_for(
            systolic, [(0, 91, 3), (91, 101, 2), (101, 111, 1), (111, 220, 0), (220, 1000, 3)]
        ),
        3,
        "mmHg",
    )

    temp = _latest_numeric_vital(timeline, "temperature")
    add(
        "temperature",
        temp,
        _points_for(
            temp, [(0, 35.0, 3), (35.0, 36.0, 1), (36.0, 38.0, 0), (38.0, 39.0, 1), (39.0, 100, 2)]
        ),
        3,
        "°C",
    )

    # consciousness not reliably extracted; AVPU omitted (documented gap).
    labs = collect_lab_values(timeline, ["potassium", "sodium", "glucose"])
    k = labs.get("potassium")
    k_val = k.value if k else None
    add(
        "potassium",
        k_val,
        _points_for(
            k_val, [(0, 3.0, 3), (3.0, 3.5, 2), (3.5, 5.5, 0), (5.5, 6.0, 1), (6.0, 100, 3)]
        ),
        3,
        "mmol/L",
    )

    # risk band (NEWS2 thresholds, applied as a screening aid)
    if total >= 7:
        band, advice = "high", "Several recent readings are abnormal. Contact a clinician promptly."
    elif total >= 5:
        band, advice = (
            "medium",
            "Some recent readings are abnormal. Arrange a clinical review soon.",
        )
    elif total >= 1:
        band, advice = "low", "A reading is slightly off. Mention it at your next appointment."
    else:
        band, advice = "none", "No abnormal screening signals from the available readings."

    available = sum(1 for c in components if c["value"] is not None)
    return {
        "score": total,
        "max_possible": 18,
        "risk_band": band,
        "advice": advice,
        "components": components,
        "inputs_available": available,
        "inputs_total": len(components),
        "note": (
            "This is an automated screening score from your most recent readings (NEWS2-style "
            "sub-scoring). Consciousness level is not extracted, so it is not included. A low "
            "score with few inputs simply means little data — it is not a clean bill of health. "
            "It is not a diagnosis."
        ),
    }
