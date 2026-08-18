"""
Medication Adherence Intelligence (deterministic)
=================================================
medication_activity.py decides whether a prescription is still ACTIVE based on
dates/durations. This module sits one layer up: from the DATING of the
prescriptions on record, it estimates whether a medicine is being supplied on
a schedule consistent with continuous use — i.e. it surfaces POSSIBLE
non-adherence signals such as refill gaps and apparent discontinuations.

It is deliberately conservative about what it claims. Prescription dates are
evidence of SUPPLY, not of whether the patient actually took the medicine.
Every finding says exactly that, and distinguishes:

  * refill_gap      — a gap between consecutive supplies longer than the
                      course length suggests, so the medicine may have lapsed
  * apparent_stop   — a medicine that was active then never re-supplied, with
                      no later discontinuation note
  * late_refill     — a supply that arrived only after the previous course
                      would have run out

No claim of "the patient did/did not take it" is made — only "the supply
pattern is worth asking about". Deterministic, no LLM.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

try:
    from medication_activity import analyze_medication_activity
except Exception:  # pragma: no cover
    analyze_medication_activity = None

try:
    from lab_trends import _parse_date as _lt_parse_date
except Exception:  # pragma: no cover
    _lt_parse_date = None


def _as_date(value: Any) -> Optional[date]:
    """Normalize lab_trends datetimes and ISO strings to date.

    lab_trends._parse_date returns a datetime. Mixing that with date.today()
    (the HTTP default when no reference_date is passed) raised
    TypeError: can't compare datetime.datetime to datetime.date and 500'd
    GET /api/v1/adherence on any workspace with dated medications.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


def _parse_date(raw: Any) -> Optional[date]:
    if not raw:
        return None
    if isinstance(raw, (date, datetime)):
        return _as_date(raw)
    if _lt_parse_date is not None:
        try:
            parsed = _as_date(_lt_parse_date(raw))
            if parsed is not None:
                return parsed
        except Exception:
            pass
    try:
        return datetime.fromisoformat(str(raw)[:10]).date()
    except Exception:
        return None


def _duration_days(med: Dict[str, Any]) -> Optional[int]:
    d = med.get("duration_days") or med.get("duration")
    if isinstance(d, (int, float)) and d > 0:
        return int(d)
    if isinstance(d, str):
        import re
        m = re.search(r"\d+", d)
        if m:
            return int(m.group())
    return None


def analyse_adherence(timeline: Dict[str, Any], reference_date: Any = None) -> Dict[str, Any]:
    meds = list(timeline.get("medications_timeline") or [])
    if not meds:
        return {"signals": [], "summary": {"medications_reviewed": 0}, "note": _NOTE}

    ref = _parse_date(reference_date) or date.today()
    # group prescription lines by normalized ingredient
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for med in meds:
        for ing in (med.get("ingredients") or [med.get("name")]):
            key = str(ing or "").strip().lower()
            if key:
                groups.setdefault(key, []).append(med)

    signals: List[Dict[str, Any]] = []
    for key, entries in groups.items():
        dated = []
        for e in entries:
            d = _parse_date(e.get("date"))
            if d:
                dated.append((d, e))
        dated.sort(key=lambda x: x[0])
        if len(dated) < 1:
            continue

        # refill gap detection between consecutive supplies
        for i in range(1, len(dated)):
            prev_date, prev_med = dated[i - 1]
            cur_date, cur_med = dated[i]
            prev_dur = _duration_days(prev_med) or 30
            gap_days = (cur_date - prev_date).days - prev_dur
            if gap_days > 7:  # tolerated overlap/slack of a week
                sig = "refill_gap" if gap_days <= prev_dur else "late_refill"
                signals.append({
                    "ingredient": key,
                    "signal": sig,
                    "gap_days": gap_days,
                    "between": [str(prev_date), str(cur_date)],
                    "detail": (
                        f"There is a ~{gap_days}-day gap between consecutive supplies of "
                        f"'{key}' (after the previous ~{prev_dur}-day course would have "
                        "run out). This may mean the medicine lapsed — ask whether it was "
                        "taken continuously."
                    ),
                })

        # apparent stop: last supply's course ended well before reference, no re-supply
        last_date, last_med = dated[-1]
        last_dur = _duration_days(last_med) or 30
        end = last_date + timedelta(days=last_dur)
        if len(dated) >= 1 and end < ref - timedelta(days=last_dur):
            signals.append({
                "ingredient": key,
                "signal": "apparent_stop",
                "last_supply": str(last_date),
                "estimated_end": str(end),
                "detail": (
                    f"'{key}' was last supplied around {last_date}; the course would have "
                    f"ended ~{end}, and nothing later is in the record. Check whether this "
                    "medicine was stopped deliberately or has lapsed."
                ),
            })

    return {
        "reference_date": str(ref),
        "signals": signals,
        "summary": {
            "medications_reviewed": len(groups),
            "signal_count": len(signals),
        },
        "note": _NOTE,
    }


_NOTE = (
    "Prescription dates are evidence of SUPPLY, not proof that a medicine was taken. "
    "These signals flag supply patterns worth asking about — they do not assert that "
    "the patient did or did not adhere."
)
