"""
Patient-Generated Health Data (PGHD) intake
===========================================
Lets a patient record measurements and observations the documents did not
contain — home blood pressure, weight, glucose, pulse, SpO2, symptoms — and
have them folded into the SAME longitudinal analysis (vital_trends,
early_warning, lab logic) as the extracted record.

Stored per workspace, anonymous-friendly (no account). Deterministic.
`augment_timeline(timeline, user_id)` returns a copy of the timeline with the
patient-entered vital_signs / lab_results injected, so any analysis that
already reads the timeline picks them up without code changes. The original
extracted timeline is never mutated, and every injected point is tagged
`source: patient_reported` so the UI can distinguish measured from
patient-reported data.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_lock = threading.RLock()
_store: Dict[str, List[Dict[str, Any]]] = {}

_VITAL_NAMES = {"blood_pressure", "heart_rate", "pulse", "oxygen_saturation", "spo2",
                "weight", "temperature", "respiratory_rate", "glucose"}
_LAB_HINTS = {"creatinine", "egfr", "potassium", "sodium", "hemoglobin", "hba1c",
              "cholesterol", "ldl", "hdl", "alt", "ast", "inr", "glucose"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_measurement(
    user_id: str,
    name: str,
    value: str,
    *,
    unit: str = "",
    measured_at: Optional[str] = None,
    kind: Optional[str] = None,
    note: str = "",
) -> Dict[str, Any]:
    name_norm = (name or "").strip().lower()
    entry = {
        "name": (name or "").strip(),
        "value": str(value),
        "unit": (unit or "").strip(),
        "measured_at": measured_at or datetime.now(timezone.utc).date().isoformat(),
        "kind": kind or ("lab" if any(h in name_norm for h in _LAB_HINTS) and "pressure" not in name_norm else "vital"),
        "note": (note or "").strip(),
        "source": "patient_reported",
        "recorded_at": _now(),
    }
    with _lock:
        _store.setdefault(user_id, []).append(entry)
    return entry


def record_symptom(user_id: str, symptom: str, *, duration: str = "", note: str = "") -> Dict[str, Any]:
    entry = {
        "name": "symptom",
        "value": symptom,
        "unit": "",
        "measured_at": datetime.now(timezone.utc).date().isoformat(),
        "kind": "symptom",
        "duration": duration,
        "note": note,
        "source": "patient_reported",
        "recorded_at": _now(),
    }
    with _lock:
        _store.setdefault(user_id, []).append(entry)
    return entry


def list_measurements(user_id: str, kind: Optional[str] = None) -> List[Dict[str, Any]]:
    with _lock:
        rows = list(_store.get(user_id, []))
    if kind:
        rows = [r for r in rows if r.get("kind") == kind]
    return rows


def augment_timeline(timeline: Dict[str, Any], user_id: str) -> Dict[str, Any]:
    """Return a shallow-copied timeline with patient-reported vitals/labs
    injected so downstream analyses see them. Never mutates the original."""
    out = dict(timeline)
    vitals = list(out.get("vital_signs_timeline") or [])
    labs = list(out.get("lab_results_timeline") or [])
    for r in list_measurements(user_id):
        if r.get("kind") == "vital":
            vitals.append({
                "name": r["name"], "value": r["value"], "unit": r.get("unit") or "",
                "measured_at": r.get("measured_at"),
                "_source": {"file": "patient_reported", "method": "manual"},
                "source_file": "patient_reported",
            })
        elif r.get("kind") == "lab":
            labs.append({
                "test_name": r["name"], "value": r["value"], "unit": r.get("unit") or "",
                "reference_range": None, "flag": "unknown", "confidence": 0.9,
                "date": r.get("measured_at"), "source_file": "patient_reported",
            })
    out["vital_signs_timeline"] = vitals
    out["lab_results_timeline"] = labs
    return out


def reset(user_id: Optional[str] = None) -> None:
    with _lock:
        if user_id is None:
            _store.clear()
        else:
            _store.pop(user_id, None)
