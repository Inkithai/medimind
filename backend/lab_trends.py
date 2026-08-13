"""
Lab Result Trend Tracking
=========================================
Takes a patient's `lab_results_timeline` (the flattened, already-merged
list build_patient_timeline() produces — one entry per lab value per
visit, each with test_name/value/unit/reference_range/flag/date/
source_file) and, per test, tracks how the value moved across visits:
direction of drift, whether/when it crossed out of the reference range,
and whether it's approaching a boundary even while still "normal".

Deliberately deterministic, no LLM call: direction and threshold-crossing
are arithmetic facts about the extracted numbers, not something that
benefits from probabilistic reasoning — matching the same "compute what
code can determine for certain" philosophy medical_extractor.py already
uses for detect_exact_duplicate_medications() alongside the LLM cross-
check. The "plain language" explanation is a template filled from those
computed facts, not a generated summary, so it can't say anything the
numbers don't support.

Dates in this pipeline arrive in wildly inconsistent formats (mixed
languages, "02-Jan-2020, 03:26 PM" vs "04-07-2019" vs "05 Jan 2026") —
see the varied `date` fields real extractions produce. dateutil.parser is
used with best-effort fuzzy parsing; anything unparseable is dropped from
the trend (noted in confidence) rather than mis-sorted.
"""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from dateutil import parser as dateutil_parser

# A value within this fraction of the reference range width, relative to
# the boundary it's moving toward, counts as "approaching" that boundary
# even though it hasn't crossed yet.
APPROACHING_THRESHOLD_FRACTION = 0.15

# Net change smaller than this fraction of the range width is "stable"
# rather than a real directional trend (guards against noise/rounding).
STABLE_CHANGE_FRACTION = 0.10


def _parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str or not isinstance(date_str, str):
        return None
    try:
        return dateutil_parser.parse(date_str, fuzzy=True)
    except (ValueError, OverflowError):
        return None


def _parse_value(value: Any) -> Optional[float]:
    """Extracts the numeric magnitude from an extracted lab value.

    Thousands separators must be consumed as part of the number. A bare
    `\\d+(\\.\\d+)?` search stops at the first comma, so a platelet count of
    "150,000" parsed as 150 — a ~1000x understatement that silently
    inverts trend direction and reads as a critical thrombocytopenia
    rather than a normal count. Same class of error for WBC/RBC counts
    and any lab reported in the hundreds of thousands.

    Both conventions appear in real reports, so the separator is
    disambiguated by grouping rather than assumed:
      * "150,000"    -> 150000.0  (comma = thousands, groups of 3)
      * "1.234,56"   -> 1234.56   (European: dot thousands, comma decimal)
      * "5,3"        -> 5.3       (comma decimal, no 3-digit group)
    Qualifiers are dropped ("<5" -> 5.0), matching prior behavior: the
    magnitude is what trends, and the flag field carries the censoring.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; not a lab value
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None

    # Grab a numeric run that may contain , and . as group/decimal marks.
    match = re.search(r"-?\d[\d,.]*", text)
    if not match:
        return None
    token = match.group().rstrip(".,")
    if not token or token in ("-",):
        return None

    has_comma, has_dot = "," in token, "." in token
    if has_comma and has_dot:
        # Whichever separator appears last is the decimal mark.
        if token.rfind(",") > token.rfind("."):
            token = token.replace(".", "").replace(",", ".")   # 1.234,56
        else:
            token = token.replace(",", "")                     # 1,234.56
    elif has_comma:
        parts = token.lstrip("-").split(",")
        # Thousands grouping iff every group after the first is exactly 3
        # digits ("150,000", "1,234,567"); otherwise a decimal comma.
        if len(parts) > 1 and all(len(p) == 3 and p.isdigit() for p in parts[1:]):
            token = token.replace(",", "")
        else:
            token = token.replace(",", ".", 1).replace(",", "")

    try:
        return float(token)
    except ValueError:
        return None


def _parse_range(reference_range: Optional[str]) -> Optional[Tuple[float, float]]:
    if not reference_range or not isinstance(reference_range, str):
        return None
    # Robust parsing for real-world ranges that may include units or extra text:
    # e.g. "70-99", "70 - 99 mg/dL", "Reference: 0.74-1.35 mg/dL", "7-56 U/L"
    # Avoid naive findall on "70-99" which can mis-read as [70, -99] if hyphen
    # is treated as sign. Search for explicit low-high pattern anywhere in string.
    # The pattern looks for number, optional spaces, hyphen, optional spaces, number.
    # This works even when units follow, e.g. "70-99 mg/dL" -> 70,99.
    s = reference_range.strip()

    # A number may carry thousands separators ("150,000-450,000") and an
    # explicit leading sign. The separator between low and high is a
    # hyphen, an en/em dash, or the word "to" — real reports use all three.
    num = r"[+-]?\d[\d,]*(?:\.\d+)?"
    sep = r"(?:\s*(?:[-–—]|to)\s*|\s+-\s+)"

    m = re.search(rf"({num}){sep}({num})", s, flags=re.IGNORECASE)
    if m:
        low, high = _parse_value(m.group(1)), _parse_value(m.group(2))
        if low is not None and high is not None:
            return (low, high) if low <= high else (high, low)

    # Single-bounded ranges ("<5", "≤5", ">10", "up to 40") are common for
    # markers with only one clinically meaningful limit. Returning None
    # here (rather than a bogus two-sided range) is deliberate: it
    # disables boundary/width math for this test instead of computing
    # "approaching" against a limit that was never stated.
    return None


def _group_by_test(lab_results_timeline: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for entry in lab_results_timeline:
        name = (entry.get("test_name") or "").strip()
        if not name:
            continue
        groups.setdefault(name.lower(), []).append(entry)
    # Use the most common casing seen for display, keyed by lowercase for grouping.
    display_names: Dict[str, str] = {}
    for entry in lab_results_timeline:
        name = (entry.get("test_name") or "").strip()
        if name:
            display_names.setdefault(name.lower(), name)
    return {display_names[k]: v for k, v in groups.items()}


def _flag_sequence_phrase(flags: List[str]) -> str:
    return " → ".join(flags)


def _direction(values: List[float], range_bounds: Optional[Tuple[float, float]]) -> str:
    net_change = values[-1] - values[0]
    width = (range_bounds[1] - range_bounds[0]) if range_bounds else max(abs(v) for v in values) or 1.0
    if width == 0:
        width = 1.0

    if abs(net_change) < STABLE_CHANGE_FRACTION * width:
        return "stable"

    deltas = [values[i + 1] - values[i] for i in range(len(values) - 1)]
    same_sign_as_net = all((d >= 0) == (net_change >= 0) or d == 0 for d in deltas)
    base = "increasing" if net_change > 0 else "decreasing"
    return base if same_sign_as_net else f"fluctuating (net {base})"


def _approaching_boundary(
    last_value: float, last_flag: str, range_bounds: Optional[Tuple[float, float]], direction: str
) -> bool:
    if last_flag != "normal" or not range_bounds:
        return False
    low, high = range_bounds
    width = high - low
    if width <= 0:
        return False
    if "increasing" in direction and (high - last_value) <= APPROACHING_THRESHOLD_FRACTION * width:
        return True
    if "decreasing" in direction and (last_value - low) <= APPROACHING_THRESHOLD_FRACTION * width:
        return True
    return False


def _crossing_point(points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """First point where the flag changed from 'normal' to something else,
    scanning chronologically. Returns None if it never crossed, or if it
    was already abnormal at the first available reading (nothing to
    pinpoint — it didn't drift there during the observed window)."""
    for i in range(1, len(points)):
        if points[i - 1]["flag"] == "normal" and points[i]["flag"] != "normal":
            return points[i]
    return None


def _returned_to_normal(points: List[Dict[str, Any]], crossing: Optional[Dict[str, Any]]) -> bool:
    """True when the series crossed into an abnormal range but the most
    recent reading is back to normal.

    _explain() used to append 'and has stayed there since' to every
    crossing unconditionally, which is false for the single most
    encouraging pattern in the data: abnormal result, treatment, recovery
    (normal -> high -> normal). The patient was told a resolved excursion
    was ongoing. Distinguishing the two also lets the explanation lead
    with the recovery instead of the crossing."""
    return crossing is not None and points[-1]["flag"] == "normal"


def _explain(
    test_name: str,
    unit: str,
    points: List[Dict[str, Any]],
    direction: str,
    range_bounds: Optional[Tuple[float, float]],
    crossing: Optional[Dict[str, Any]],
    approaching: bool,
) -> str:
    values = [p["_value"] for p in points]
    dates = [p.get("date") or "an unspecified date" for p in points]
    trail = " → ".join(f"{v:g} {unit}".strip() + f" ({d})" for v, d in zip(values, dates))
    net_change = values[-1] - values[0]
    range_phrase = f" (reference range {range_bounds[0]:g}-{range_bounds[1]:g} {unit})" if range_bounds else ""

    if direction == "stable":
        base = (
            f"{test_name} has stayed roughly stable across {len(points)} tests{range_phrase}: {trail}."
        )
    else:
        verb = "risen" if net_change > 0 else "fallen"
        base = (
            f"{test_name} has {verb} across {len(points)} tests{range_phrase}, from {values[0]:g} {unit} "
            f"to {values[-1]:g} {unit} ({trail})."
        )

    if crossing is not None and points[-1]["flag"] == "normal":
        # Crossed out of range, but the latest reading is back to normal.
        # Reporting this as an ongoing excursion ("has stayed there since")
        # misrepresents a recovery — the most reassuring pattern in the data.
        base += (
            f" It moved out of the normal range into the '{crossing['flag']}' range "
            f"at the {crossing.get('date', 'interim')} test, but the most recent reading is "
            f"back within the normal range."
        )
    elif crossing is not None:
        base += (
            f" It moved from within the normal range into the '{crossing['flag']}' range "
            f"starting with the {crossing.get('date', 'most recent')} test, and has stayed there since."
        )
    elif points[-1]["flag"] != "normal" and points[0]["flag"] != "normal":
        base += f" It was already outside the normal range at the earliest available test and has remained '{points[-1]['flag']}'."
    elif approaching:
        # Use the same substring test as _approaching_boundary() above, NOT
        # direction.startswith("increasing"). _direction() can return
        # "fluctuating (net increasing)" for a noisy-but-climbing series —
        # that string does not *start* with "increasing", so startswith()
        # fell through to "lower" and told the patient a rising value was
        # drifting toward the BOTTOM of its reference range. Medically
        # inverted advice, emitted silently with HTTP 200, and only on the
        # approaching_threshold early-warning path — i.e. exactly when the
        # feature matters most. Noisy series are the common case in real
        # lab data, so this fired often.
        base += (
            f" It's still within the normal range but has been trending toward the "
            f"{'upper' if 'increasing' in direction else 'lower'} boundary — worth watching even "
            "though it hasn't been flagged abnormal yet."
        )
    elif direction == "stable":
        base += " No concerning drift observed."

    return base


def track_lab_trends(timeline: Dict[str, Any]) -> Dict[str, Any]:
    """
    Groups `timeline["lab_results_timeline"]` by test_name and analyzes
    each test with 2+ usable (dated, numeric) data points for directional
    drift and reference-range crossings.

    Returns:
      {
        "trends": [
          {
            "test_name": str, "unit": str, "reference_range": "low-high" | None,
            "data_points": [{"date", "value", "flag", "source_file"}, ...]  # chronological
            "direction": "increasing" | "decreasing" | "stable" | "fluctuating (net increasing/decreasing)",
            "flag_sequence": "normal → normal → high",
            "crossed_into_abnormal_at": {"date":..., "flag":...} | None,
            "approaching_threshold": bool,
            "confidence": float,   # lower if dates/values had to be dropped, or reference ranges disagreed
            "explanation": str,    # plain-language, template-generated from the numbers above
          }, ...
        ],
        "insufficient_data": [{"test_name": str, "reason": str}, ...],
        "note": "... not a diagnosis, consult a clinician/pharmacist ..."
      }
    """
    lab_results_timeline = timeline.get("lab_results_timeline", [])
    grouped = _group_by_test(lab_results_timeline)

    trends: List[Dict[str, Any]] = []
    insufficient: List[Dict[str, Any]] = []

    for test_name, entries in grouped.items():
        usable = []
        dropped = 0
        units_seen = set()
        ranges_seen = set()
        for e in entries:
            dt = _parse_date(e.get("date"))
            val = _parse_value(e.get("value"))
            if dt is None or val is None:
                dropped += 1
                continue
            usable.append({
                "_dt": dt, "_value": val,
                "date": e.get("date"), "value": e.get("value"),
                "flag": e.get("flag") or "unknown",
                "unit": e.get("unit") or "",
                "reference_range": e.get("reference_range"),
                "source_file": e.get("source_file"),
                "confidence": e.get("confidence", 1.0),
            })
            if e.get("unit"):
                units_seen.add(e["unit"])
            if e.get("reference_range"):
                ranges_seen.add(e["reference_range"])

        if len(usable) < 2:
            insufficient.append({
                "test_name": test_name,
                "reason": (
                    f"only {len(usable)} usable data point(s) with a parseable date and numeric value "
                    f"(need at least 2 to establish a trend); {dropped} entrie(s) were dropped."
                    if usable else
                    f"no entries had both a parseable date and a numeric value ({dropped} dropped)."
                ),
            })
            continue

        usable.sort(key=lambda p: p["_dt"])

        # Refuse to trend across incompatible units. Values in mg/dL and
        # mmol/L (or g/L vs g/dL) live on different scales, so subtracting
        # them is meaningless: Glucose 95 mg/dL -> 5.3 mmol/L is the SAME
        # clinical value, but the raw arithmetic reported it as a steep
        # fall, and _explain() then relabelled every point with the last
        # visit's unit ("from 95 mmol/L") — a fabricated number that reads
        # as a hypoglycemic crash. Unit conversion needs a per-analyte
        # molar-mass table we don't have, so the honest output is to
        # decline the trend and say why, rather than emit a confident
        # wrong direction. Comparison is case/whitespace-insensitive so
        # "mg/dL" and "mg/dl " don't count as a real disagreement.
        distinct_units = {
            re.sub(r"\s+", "", p["unit"]).lower() for p in usable if p.get("unit")
        }
        if len(distinct_units) > 1:
            insufficient.append({
                "test_name": test_name,
                "reason": (
                    f"readings use {len(distinct_units)} different units "
                    f"({', '.join(sorted(p['unit'] for p in usable if p.get('unit')))}) — "
                    "values are not directly comparable, so no trend was computed. "
                    "Re-check the source reports or record these under separate test names."
                ),
            })
            continue

        unit = usable[-1]["unit"]
        range_bounds = _parse_range(usable[-1]["reference_range"])

        direction = _direction([p["_value"] for p in usable], range_bounds)
        crossing = _crossing_point(usable)
        approaching = _approaching_boundary(usable[-1]["_value"], usable[-1]["flag"], range_bounds, direction)

        # Confidence: average of the source extraction confidences, discounted
        # for dropped/unusable readings and for disagreeing units or reference
        # ranges across visits (both make the trend less trustworthy).
        confidences = [p["confidence"] for p in usable if isinstance(p["confidence"], (int, float))]
        base_confidence = sum(confidences) / len(confidences) if confidences else 0.7
        if dropped:
            base_confidence *= max(0.5, 1 - 0.15 * dropped)
        if len(units_seen) > 1 or len(ranges_seen) > 1:
            base_confidence *= 0.7

        trends.append({
            "test_name": test_name,
            "unit": unit,
            "reference_range": usable[-1]["reference_range"],
            "data_points": [
                {"date": p["date"], "value": p["value"], "flag": p["flag"], "source_file": p["source_file"]}
                for p in usable
            ],
            "direction": direction,
            "flag_sequence": _flag_sequence_phrase([p["flag"] for p in usable]),
            "crossed_into_abnormal_at": (
                {"date": crossing["date"], "flag": crossing["flag"]} if crossing else None
            ),
            "approaching_threshold": approaching,
            "confidence": round(min(base_confidence, 0.97), 2),
            "explanation": _explain(test_name, unit, usable, direction, range_bounds, crossing, approaching),
        })

    return {
        "trends": trends,
        "insufficient_data": insufficient,
        "note": (
            "This trend analysis is computed directly from the extracted lab values and reference "
            "ranges — it is not a diagnosis and does not account for clinical context beyond the "
            "numbers shown. Consult the patient's doctor or a pharmacist to interpret what any trend "
            "means for their care."
        ),
    }


if __name__ == "__main__":
    # Self-test using John's three real lab reports from this project's
    # test data: Fasting Glucose drifts from normal into high, ALT jumps
    # into high only at the last test, Creatinine rises but stays just
    # inside the normal range (approaching the upper boundary).
    demo_timeline = {
        "lab_results_timeline": [
            {"test_name": "Fasting Glucose", "value": "91", "unit": "mg/dL", "reference_range": "70-99", "flag": "normal", "confidence": 0.95, "date": "05 Jan 2026", "source_file": "John_Lab_Report_1.pdf"},
            {"test_name": "ALT", "value": "24", "unit": "U/L", "reference_range": "7-56", "flag": "normal", "confidence": 0.95, "date": "05 Jan 2026", "source_file": "John_Lab_Report_1.pdf"},
            {"test_name": "Creatinine", "value": "0.92", "unit": "mg/dL", "reference_range": "0.74-1.35", "flag": "normal", "confidence": 0.95, "date": "05 Jan 2026", "source_file": "John_Lab_Report_1.pdf"},
            {"test_name": "Fasting Glucose", "value": "103", "unit": "mg/dL", "reference_range": "70-99", "flag": "high", "confidence": 0.95, "date": "20 Apr 2026", "source_file": "John_Lab_Report_2.pdf"},
            {"test_name": "ALT", "value": "41", "unit": "U/L", "reference_range": "7-56", "flag": "normal", "confidence": 0.95, "date": "20 Apr 2026", "source_file": "John_Lab_Report_2.pdf"},
            {"test_name": "Creatinine", "value": "1.08", "unit": "mg/dL", "reference_range": "0.74-1.35", "flag": "normal", "confidence": 0.95, "date": "20 Apr 2026", "source_file": "John_Lab_Report_2.pdf"},
            {"test_name": "Fasting Glucose", "value": "118", "unit": "mg/dL", "reference_range": "70-99", "flag": "high", "confidence": 0.95, "date": "30 Aug 2026", "source_file": "John_Lab_Report_3.pdf"},
            {"test_name": "ALT", "value": "82", "unit": "U/L", "reference_range": "7-56", "flag": "high", "confidence": 0.95, "date": "30 Aug 2026", "source_file": "John_Lab_Report_3.pdf"},
            {"test_name": "Creatinine", "value": "1.32", "unit": "mg/dL", "reference_range": "0.74-1.35", "flag": "normal", "confidence": 0.95, "date": "30 Aug 2026", "source_file": "John_Lab_Report_3.pdf"},
        ]
    }
    result = track_lab_trends(demo_timeline)
    by_name = {t["test_name"]: t for t in result["trends"]}

    assert by_name["Fasting Glucose"]["direction"] == "increasing"
    assert by_name["Fasting Glucose"]["crossed_into_abnormal_at"]["date"] == "20 Apr 2026"

    assert by_name["ALT"]["direction"] == "increasing"
    assert by_name["ALT"]["crossed_into_abnormal_at"]["date"] == "30 Aug 2026"

    assert by_name["Creatinine"]["direction"] == "increasing"
    assert by_name["Creatinine"]["crossed_into_abnormal_at"] is None
    assert by_name["Creatinine"]["approaching_threshold"] is True

    # Regression check for the reference-range parsing bug (hyphen
    # mis-read as a negative sign): must render as "70-99", not "-99-70".
    assert "70-99 mg/dL" in by_name["Fasting Glucose"]["explanation"], by_name["Fasting Glucose"]["explanation"]

    # Thousand-separated lab values (WBC, platelets) must not be truncated
    # at the first comma: "12,500" used to parse as 12.
    assert _parse_value("12,500") == 12500.0
    assert _parse_value("1,234.5") == 1234.5
    assert _parse_value("6.1") == 6.1
    assert _parse_value("<5.7") == 5.7
    assert _parse_value("1,5") == 1.5

    for t in result["trends"]:
        print(f"--- {t['test_name']} ---")
        print(" direction:", t["direction"], "| flags:", t["flag_sequence"], "| confidence:", t["confidence"])
        print(" ", t["explanation"])
        print()

    print("All checks passed.")
