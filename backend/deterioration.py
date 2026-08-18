"""
Longitudinal Deterioration Detection (deterministic)
====================================================
early_warning.py computes a single National-Early-Warning-style score from the
MOST RECENT readings. This module computes that score at EVERY dated time point
in the record and asks whether the patient is getting BETTER or WORSE over time
— the longitudinal question single-snapshot scoring cannot answer.

For each date on which a vital or key lab was recorded, it assembles each
signal's most recent reading AS OF that date, scores it (NEWS2-style sub-scoring
reused from early_warning), and builds a trajectory. From the trajectory it
flags:

  * trend              — improving / stable / worsening across the series
  * sustained_high     — two or more consecutive points in the medium/high band
  * latest_band        — the risk band of the most recent point
  * worsening_signals  — individual signals whose points increased over time

Deterministic, no LLM, no diagnosis. Sparse records (one reading) still yield
a single point; the trajectory is then just that point, honestly labelled.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from clinical_lab_values import _parse_numeric, latest_lab_value
from vital_trends import _series_for, _VITALS
from early_warning import _points_for, _latest_numeric_vital  # reuse bands + helpers


def _vital_series_dates(timeline: Dict[str, Any]) -> Dict[str, List[Tuple[Optional[date], Optional[float]]]]:
    """For each vital type, a chronological list of (date, numeric value)."""
    out: Dict[str, List[Tuple[Optional[date], Optional[float]]]] = {}
    for key in ("respiratory_rate", "oxygen_saturation", "heart_rate", "blood_pressure", "temperature"):
        series = _series_for(timeline, key, _VITALS[key][1])
        pts: List[Tuple[Optional[date], Optional[float]]] = []
        for r in series:
            d = _to_date(r.get("date"))
            val = r.get("systolic") if key == "blood_pressure" else r.get("numeric")
            pts.append((d, val))
        if pts:
            out[key] = pts
    return out


def _lab_series_dates(timeline: Dict[str, Any], analyte: str) -> List[Tuple[Optional[date], Optional[float]]]:
    labs = list(timeline.get("lab_results_timeline") or []) + list(timeline.get("lab_results") or [])
    pts: List[Tuple[Optional[date], Optional[float]]] = []
    aliases = ("potassium",)  # only K+ used in the score
    for entry in labs:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("test_name") or entry.get("name") or "").lower()
        if analyte not in name:
            continue
        d = _to_date(entry.get("date"))
        v = _parse_numeric(entry.get("value"))
        pts.append((d, v))
    return pts


def _to_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw)[:10]).date()
    except Exception:
        return None


def _value_as_of(series: List[Tuple[Optional[date], Optional[float]]], as_of: Optional[date]) -> Optional[float]:
    """Most recent value on or before `as_of` (inclusive)."""
    candidate = None
    cand_date = None
    for d, v in series:
        if v is None:
            continue
        if as_of is None or d is None or d <= as_of:
            if candidate is None or (d is not None and (cand_date is None or d >= cand_date)):
                candidate = v
                cand_date = d
    return candidate


# Signal -> NEWS2-style bands (mirrors early_warning.compute_early_warning_score)
_BANDS = {
    "respiratory_rate": [(0, 8, 3), (8, 12, 1), (12, 21, 0), (21, 25, 2), (25, 10_000, 3)],
    "oxygen_saturation": [(0, 92, 3), (92, 94, 2), (94, 96, 1), (96, 101, 0)],
    "heart_rate": [(0, 41, 3), (41, 51, 1), (51, 91, 0), (91, 111, 1), (111, 131, 2), (131, 10_000, 3)],
    "systolic_bp": [(0, 91, 3), (91, 101, 2), (101, 111, 1), (111, 220, 0), (220, 10_000, 3)],
    "temperature": [(0, 35.0, 3), (35.0, 36.0, 1), (36.0, 38.0, 0), (38.0, 39.0, 1), (39.0, 100, 2)],
    "potassium": [(0, 3.0, 3), (3.0, 3.5, 2), (3.5, 5.5, 0), (5.5, 6.0, 1), (6.0, 100, 3)],
}


def _band_for(score: int) -> str:
    if score >= 7:
        return "high"
    if score >= 5:
        return "medium"
    if score >= 1:
        return "low"
    return "none"


def deterioration_trajectory(timeline: Dict[str, Any]) -> Dict[str, Any]:
    vital_series = _vital_series_dates(timeline)
    k_series = _lab_series_dates(timeline, "potassium")

    # Collect every date a relevant reading exists.
    dates: set = set()
    for s in list(vital_series.values()) + [k_series]:
        for d, _v in s:
            if d is not None:
                dates.add(d)
    if not dates:
        # fall back to undated single-point using early_warning
        return _single_point_fallback(timeline)
    ordered_dates = sorted(dates)

    points: List[Dict[str, Any]] = []
    per_signal_history: Dict[str, List[int]] = {k: [] for k in _BANDS}
    for as_of in ordered_dates:
        comps: Dict[str, Optional[float]] = {}
        total = 0
        for signal, series in {
            "respiratory_rate": vital_series.get("respiratory_rate", []),
            "oxygen_saturation": vital_series.get("oxygen_saturation", []),
            "heart_rate": vital_series.get("heart_rate", []),
            "systolic_bp": vital_series.get("blood_pressure", []),
            "temperature": vital_series.get("temperature", []),
            "potassium": k_series,
        }.items():
            val = _value_as_of(series, as_of)
            comps[signal] = val
            pts = _points_for(val, _BANDS[signal])
            total += pts
            per_signal_history[signal].append(pts)
        points.append({
            "date": as_of.isoformat(),
            "score": total,
            "risk_band": _band_for(total),
            "components": {k: v for k, v in comps.items() if v is not None},
        })

    scores = [p["score"] for p in points]
    latest = points[-1] if points else None
    prev = points[-2] if len(points) >= 2 else None

    # trend across the whole series
    if len(scores) >= 2:
        first_half = sum(scores[: len(scores) // 2 or 1]) / max(1, len(scores) // 2 or 1)
        second_half = sum(scores[len(scores) // 2 or 1:]) / max(1, len(scores) - (len(scores) // 2 or 1))
        if second_half - first_half >= 1.5:
            trend = "worsening"
        elif first_half - second_half >= 1.5:
            trend = "improving"
        else:
            trend = "stable"
    else:
        trend = "insufficient_data"

    # sustained high: any run of >=2 consecutive points >= 5
    sustained_high = False
    run = 0
    for s in scores:
        run = run + 1 if s >= 5 else 0
        if run >= 2:
            sustained_high = True
            break

    # worsening signals: any signal whose points strictly increased across history
    worsening_signals = []
    for signal, hist in per_signal_history.items():
        hist = [h for h in hist if True]
        if len(hist) >= 2 and hist[-1] > hist[0] and hist[-1] > 0:
            worsening_signals.append(signal)

    peak = max(scores) if scores else 0
    return {
        "trajectory": points,
        "point_count": len(points),
        "latest_score": latest["score"] if latest else 0,
        "latest_band": latest["risk_band"] if latest else "none",
        "previous_score": prev["score"] if prev else None,
        "peak_score": peak,
        "trend": trend,
        "sustained_high": sustained_high,
        "worsening_signals": worsening_signals,
        "deteriorating": trend == "worsening" or sustained_high,
        "note": (
            "A worsening trajectory or two or more consecutive medium/high points suggests the "
            "patient may be deteriorating across readings. This is a screening aid from dated "
            "vitals and potassium, not a diagnosis; consciousness level is not included."
        ),
    }


def _single_point_fallback(timeline: Dict[str, Any]) -> Dict[str, Any]:
    score = 0
    comps: Dict[str, Optional[float]] = {}
    for key, signal in (("respiratory_rate", "respiratory_rate"), ("oxygen_saturation", "oxygen_saturation"),
                        ("heart_rate", "heart_rate"), ("blood_pressure", "systolic_bp"),
                        ("temperature", "temperature")):
        v = _latest_numeric_vital(timeline, key)
        comps[signal] = v
        score += _points_for(v, _BANDS[signal])
    k = latest_lab_value(timeline, "potassium")
    kv = k.value if k else None
    comps["potassium"] = kv
    score += _points_for(kv, _BANDS["potassium"])
    return {
        "trajectory": [],
        "point_count": 0,
        "latest_score": score,
        "latest_band": _band_for(score),
        "previous_score": None,
        "peak_score": score,
        "trend": "insufficient_data",
        "sustained_high": False,
        "worsening_signals": [],
        "deteriorating": False,
        "note": "Only undated or single readings were available, so no trajectory could be built.",
    }
