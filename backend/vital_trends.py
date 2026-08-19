"""
Vital-Sign Longitudinal Intelligence (deterministic)
====================================================
lab_trends.py reasons over laboratory results; until now vital signs were
extracted but never analysed across time. This module applies the same
deterministic, no-LLM, no-diagnosis philosophy to the vital_signs_timeline:
blood pressure, heart/pulse rate, oxygen saturation, weight, temperature,
respiratory rate and glucose.

For each vital type present it reports: the chronological series, the
direction of drift, the most recent reading, and whether the latest reading
crosses a widely used adult threshold (e.g. BP >= 140/90, SpO2 < 92%, pulse
< 60 or > 100). It produces a plain-language sentence from those numbers and
flags anything abnormal for "raise with your clinician" — it never diagnoses.

Blood pressure is parsed specially because it is two numbers ("130/86"): both
systolic and diastolic are tracked, and the hypertension signal fires when
either crosses its threshold.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from lab_trends import _parse_date as _lt_parse_date
except Exception:  # pragma: no cover
    _lt_parse_date = None
from datetime import datetime

# vital canonical key -> (display name, aliases matched against the printed name)
_VITALS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "blood_pressure": ("Blood pressure", ("blood pressure", "bp")),
    "heart_rate": ("Heart rate", ("heart rate", "pulse", "hr")),
    "oxygen_saturation": (
        "Oxygen saturation",
        ("oxygen saturation", "spo2", "o2 sat", "saturation"),
    ),
    "weight": ("Weight", ("weight",)),
    "temperature": ("Temperature", ("temperature", "temp")),
    "respiratory_rate": (
        "Respiratory rate",
        ("respiratory rate", "respiration rate", "rr", "breathing rate"),
    ),
    "glucose": ("Glucose", ("glucose", "blood sugar", "random glucose")),
}

# Latest-reading thresholds (adult, widely used screening cut-offs). These are
# screening signals, NOT diagnoses. None where not applicable.
_THRESHOLDS = {
    "blood_pressure": (140, 90),  # (systolic_high, diastolic_high)
    "heart_rate": (60, 100),  # (low, high)
    "oxygen_saturation": (92, None),  # (low, _)
    "temperature": (None, 38.0),  # (_, high) Celsius
    "respiratory_rate": (12, 20),  # (low, high)
    "glucose": (None, 11.1),  # (_, high) mmol/L random
}

STABLE_CHANGE = 0.10


def _norm(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def _parse_date(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    if _lt_parse_date is not None:
        try:
            return _lt_parse_date(raw)
        except Exception:
            pass
    try:
        return datetime.fromisoformat(str(raw)[:19])
    except Exception:
        return None


def _parse_number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    m = re.search(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", value)
    return float(m.group()) if m else None


def _classify_bp(value: Any) -> Optional[Tuple[float, float]]:
    """Return (systolic, diastolic) for a BP value like '130/86' or '130 / 86'."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return (float(value), 0.0)
    if not isinstance(value, str):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*[/\\]\s*(\d+(?:\.\d+)?)", value)
    if not m:
        single = _parse_number(value)
        return (single, 0.0) if single is not None else None
    return (float(m.group(1)), float(m.group(2)))


def _series_for(
    timeline: Dict[str, Any], key: str, aliases: Tuple[str, ...]
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in timeline.get("vital_signs_timeline") or []:
        if not isinstance(entry, dict) or (entry.get("_trust") or {}).get("quarantined"):
            continue
        name = _norm(entry.get("name"))
        if not any(a in name for a in aliases):
            continue
        date = _parse_date(entry.get("measured_at") or entry.get("date"))
        unit = (str(entry.get("unit") or "")).strip().lower() or None
        if key == "blood_pressure":
            bp = _classify_bp(entry.get("value"))
            if bp is None:
                continue
            rows.append(
                {
                    "date": date,
                    "value": entry.get("value"),
                    "systolic": bp[0],
                    "diastolic": bp[1],
                    "unit": unit,
                    "entry": entry,
                }
            )
        else:
            num = _parse_number(entry.get("value"))
            if num is None:
                continue
            rows.append(
                {
                    "date": date,
                    "value": entry.get("value"),
                    "numeric": num,
                    "unit": unit,
                    "entry": entry,
                }
            )
    rows.sort(key=lambda r: (r["date"] is None, r["date"] or datetime.min))
    return rows


def _direction(nums: List[float]) -> str:
    if len(nums) < 2:
        return "insufficient_data"
    first, last = nums[0], nums[-1]
    span = max(abs(first), abs(last), 1e-9)
    change = (last - first) / span
    if abs(change) < STABLE_CHANGE:
        return "stable"
    return "increasing" if change > 0 else "decreasing"


def _latest_signal(key: str, latest: Dict[str, Any]) -> Tuple[Optional[str], str]:
    """Return (abnormal_flag, plain-language note) for the most recent reading."""
    if key == "blood_pressure":
        s, d = latest["systolic"], latest["diastolic"]
        sh, dh = _THRESHOLDS["blood_pressure"]
        if s >= sh or d >= dh:
            return "high", (
                f"Your most recent blood pressure is "
                f"{s:g}/{d:g} mmHg, which is at or above the "
                f"{sh}/{dh} stage-2 hypertension screening range. "
                "This is worth raising with your clinician."
            )
        if s >= 130 or d >= 80:
            return "borderline", (
                f"Your most recent blood pressure is {s:g}/{d:g} "
                "mmHg, which is in the elevated/borderline range."
            )
        return (
            None,
            f"Your most recent blood pressure is {s:g}/{d:g} mmHg, within the normal screening range.",  # noqa: E501
        )
    lo, hi = _THRESHOLDS.get(key, (None, None))
    num = latest["numeric"]
    unit = f" {latest['unit']}" if latest.get("unit") else ""
    disp = _VITALS[key][0]
    if hi is not None and num >= hi:
        return "high", f"Your most recent {disp} is {num:g}{unit}, at or above {hi:g}{unit}."
    if lo is not None and num <= lo:
        return "low", f"Your most recent {disp} is {num:g}{unit}, at or below {lo:g}{unit}."
    return None, f"Your most recent {disp} is {num:g}{unit}, within the normal screening range."


def track_vital_trends(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """Analyse every vital-sign type present in the record."""
    trends: List[Dict[str, Any]] = []
    insufficient: List[Dict[str, Any]] = []
    for key, (display, aliases) in _VITALS.items():
        series = _series_for(timeline, key, aliases)
        if not series:
            continue
        latest = series[-1]
        if key == "blood_pressure":
            nums = [r["systolic"] for r in series]
        else:
            nums = [r["numeric"] for r in series]
        direction = _direction(nums)
        flag, note = _latest_signal(key, latest)
        risk_level = "none"
        if flag in ("high", "low"):
            risk_level = "abnormal"
        elif flag == "borderline":
            risk_level = "borderline"
        entry = {
            "vital": key,
            "display_name": display,
            "data_points": [
                {"date": (r["date"].isoformat() if r["date"] else None), "value": r["value"]}
                for r in series
            ],
            "direction": direction,
            "latest": latest["value"],
            "unit": latest.get("unit"),
            "latest_flag": flag,
            "risk_level": risk_level,
            "explanation": note,
        }
        if risk_level == "abnormal" or len(series) >= 1:
            trends.append(entry)
        else:
            insufficient.append({"vital": key, "reason": "only one reading"})
    return {
        "trends": trends,
        "insufficient_data": insufficient,
        "summary": {
            "vital_types": len(trends),
            "abnormal_latest": sum(1 for t in trends if t["risk_level"] == "abnormal"),
        },
    }
