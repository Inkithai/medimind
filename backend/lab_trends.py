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

# Molecular weights (g/mol) for analytes commonly reported in both a
# mass/volume unit (mg/dL, g/L, …) and a molar unit (mmol/L, µmol/L).
# Conversion uses C(mmol/L) = C(g/L) * 1000 / MW, which is the same
# identity as the familiar clinical shortcuts:
#   glucose mg/dL / 18.02 = mmol/L
#   creatinine mg/dL * 88.4 = µmol/L
#   bilirubin mg/dL * 17.1 = µmol/L
#   cholesterol mg/dL / 38.67 = mmol/L
_ANALYTE_MOLAR_MASS: Dict[str, float] = {
    "glucose": 180.156,
    "creatinine": 113.118,
    "urea": 60.056,
    "bun": 28.014,  # urea nitrogen, not urea
    "uric_acid": 168.112,
    "cholesterol": 386.654,
    "triglycerides": 885.4,  # conventional triolein equivalent
    "bilirubin": 584.662,
    "calcium": 40.078,
    "magnesium": 24.305,
    "phosphorus": 30.974,
    "iron": 55.845,
}

# Lowercased, punctuation-stripped test-name phrases → analyte key.
# Longer phrases are matched first so "blood urea nitrogen" wins over "urea".
_ANALYTE_ALIASES: Dict[str, str] = {
    "glucose": "glucose",
    "fasting glucose": "glucose",
    "random glucose": "glucose",
    "blood glucose": "glucose",
    "plasma glucose": "glucose",
    "serum glucose": "glucose",
    "fasting blood glucose": "glucose",
    "fasting plasma glucose": "glucose",
    "fbs": "glucose",
    "fbg": "glucose",
    "fpg": "glucose",
    "rbs": "glucose",
    "rbg": "glucose",
    "ppbs": "glucose",
    "ppbg": "glucose",
    "creatinine": "creatinine",
    "serum creatinine": "creatinine",
    "s creatinine": "creatinine",
    "sr creatinine": "creatinine",
    "urea": "urea",
    "blood urea": "urea",
    "serum urea": "urea",
    "bun": "bun",
    "blood urea nitrogen": "bun",
    "urea nitrogen": "bun",
    "uric acid": "uric_acid",
    "serum uric acid": "uric_acid",
    "cholesterol": "cholesterol",
    "total cholesterol": "cholesterol",
    "hdl": "cholesterol",
    "hdl cholesterol": "cholesterol",
    "ldl": "cholesterol",
    "ldl cholesterol": "cholesterol",
    "vldl": "cholesterol",
    "vldl cholesterol": "cholesterol",
    "non hdl cholesterol": "cholesterol",
    "triglycerides": "triglycerides",
    "triglyceride": "triglycerides",
    "bilirubin": "bilirubin",
    "total bilirubin": "bilirubin",
    "direct bilirubin": "bilirubin",
    "indirect bilirubin": "bilirubin",
    "calcium": "calcium",
    "serum calcium": "calcium",
    "magnesium": "magnesium",
    "serum magnesium": "magnesium",
    "phosphorus": "phosphorus",
    "phosphate": "phosphorus",
    "inorganic phosphorus": "phosphorus",
    "inorganic phosphate": "phosphorus",
    "iron": "iron",
    "serum iron": "iron",
}

# Canonical unit key → (family, multiplier-to-base).
# mass family base = g/L; molar family base = mmol/L.
# Same-family conversions (g/dL ↔ g/L, mmol/L ↔ µmol/L) need no MW.
# Cross-family conversions (mg/dL ↔ mmol/L) need the analyte MW.
_UNIT_TO_BASE: Dict[str, Tuple[str, float]] = {
    "g/l": ("mass", 1.0),
    "g/dl": ("mass", 10.0),
    "mg/dl": ("mass", 0.01),
    "mg/l": ("mass", 0.001),
    "mmol/l": ("molar", 1.0),
    "umol/l": ("molar", 0.001),
    "nmol/l": ("molar", 1e-6),
}

_UNIT_KEY_ALIASES = {
    "mg/100ml": "mg/dl",
    "mg%": "mg/dl",
    "gm/dl": "g/dl",
    "gm/l": "g/l",
    "mmoll": "mmol/l",
    "mmol/lt": "mmol/l",
    "mcmol/l": "umol/l",
    "micromol/l": "umol/l",
}


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


def _last_crossing_point(points: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Most recent normal → abnormal transition. Used for relapse wording
    so a high → normal → high series names the recrossing, not an earlier
    excursion."""
    found: Optional[Dict[str, Any]] = None
    for i in range(1, len(points)):
        if points[i - 1]["flag"] == "normal" and points[i]["flag"] != "normal":
            found = points[i]
    return found


def _returned_to_normal(points: List[Dict[str, Any]], crossing: Optional[Dict[str, Any]] = None) -> bool:
    """True when the series was abnormal at some point and the most
    recent reading is back to normal.

    _explain() used to append 'and has stayed there since' to every
    crossing unconditionally, which is false for the single most
    encouraging pattern in the data: abnormal result, treatment, recovery
    (normal -> high -> normal). Distinguishing the two also lets the
    explanation lead with the recovery instead of the crossing.

    A crossing during the window is sufficient but not required: a series
    that was already abnormal at the first reading and then recovered
    (high -> normal) is the same clinical pattern.
    """
    if not points or points[-1]["flag"] != "normal":
        return False
    if crossing is not None:
        return True
    return any(p["flag"] != "normal" for p in points[:-1])


def _relapsed(points: List[Dict[str, Any]]) -> bool:
    """True when the series was abnormal, returned to normal, then is
    abnormal again (high → normal → high). The 'has remained' branch
    only looks at the first and last flags, so a relapse used to fall
    through with no narrative at all — or, if a later crossing was
    found, was described as having 'stayed there since'."""
    if not points or points[-1]["flag"] == "normal":
        return False
    saw_abnormal = False
    recovered = False
    for point in points:
        if point["flag"] != "normal":
            if recovered:
                return True
            saw_abnormal = True
        elif saw_abnormal:
            recovered = True
    return False


def _normalize_test_name(test_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (test_name or "").strip().lower()).strip()


def _analyte_key(test_name: str) -> Optional[str]:
    collapsed = _normalize_test_name(test_name)
    if not collapsed:
        return None
    if collapsed in _ANALYTE_ALIASES:
        return _ANALYTE_ALIASES[collapsed]
    for alias in sorted(_ANALYTE_ALIASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", collapsed):
            return _ANALYTE_ALIASES[alias]
    return None


def _molar_mass_for(test_name: str) -> Optional[float]:
    key = _analyte_key(test_name)
    if key is None:
        return None
    return _ANALYTE_MOLAR_MASS.get(key)


def _canonical_unit_key(unit: str) -> str:
    raw = re.sub(r"\s+", "", (unit or "")).lower()
    raw = raw.replace("µ", "u").replace("μ", "u")
    return _UNIT_KEY_ALIASES.get(raw, raw)


def _unit_spec(unit: str) -> Tuple[Optional[str], Optional[float], str]:
    key = _canonical_unit_key(unit)
    spec = _UNIT_TO_BASE.get(key)
    if spec is None:
        return None, None, key
    return spec[0], spec[1], key


def _convert_value(
    value: float,
    from_unit: str,
    to_unit: str,
    molar_mass: Optional[float],
) -> Optional[float]:
    """Convert `value` from `from_unit` to `to_unit`.

    Same-family conversions (g/dL ↔ g/L, mmol/L ↔ µmol/L) are exact
    scale factors. Mass ↔ molar needs the analyte molecular weight.
    Empty units are treated as already in the target unit (unknown, not
    conflicting). Unrecognised or inconvertible pairs return None.
    """
    if not (from_unit or "").strip() or not (to_unit or "").strip():
        return value
    from_fam, from_mul, from_key = _unit_spec(from_unit)
    to_fam, to_mul, to_key = _unit_spec(to_unit)
    if from_key == to_key:
        return value
    if from_fam is None or to_fam is None or from_mul is None or to_mul is None:
        return None
    if from_fam == to_fam:
        return value * from_mul / to_mul
    if molar_mass is None or molar_mass <= 0:
        return None
    if from_fam == "mass" and to_fam == "molar":
        mmol_per_l = (value * from_mul) * 1000.0 / molar_mass
        return mmol_per_l / to_mul
    if from_fam == "molar" and to_fam == "mass":
        g_per_l = (value * from_mul) * molar_mass / 1000.0
        return g_per_l / to_mul
    return None


def _format_lab_number(value: float) -> str:
    """Compact display for a converted magnitude."""
    if abs(value) >= 100:
        return f"{round(value, 1):g}"
    if abs(value) >= 10:
        return f"{round(value, 2):g}"
    return f"{round(value, 3):g}"


def _harmonize_units(test_name: str, usable: List[Dict[str, Any]]) -> Tuple[bool, Optional[str]]:
    """Convert every point onto the last reading's unit when possible.

    Returns (did_convert, error_reason). On error the series should be
    declined as insufficient_data rather than trended on mixed scales.
    Cosmetic spelling differences (mg/dL vs mg/dl) are not conversions.
    """
    present = [(p.get("unit") or "").strip() for p in usable]
    present = [u for u in present if u]
    distinct = {_canonical_unit_key(u) for u in present}
    if len(distinct) <= 1:
        return False, None

    target = ""
    for point in reversed(usable):
        unit = (point.get("unit") or "").strip()
        if unit:
            target = unit
            break

    molar_mass = _molar_mass_for(test_name)
    converted = False
    for point in usable:
        src = (point.get("unit") or "").strip()
        if not src:
            continue
        new_val = _convert_value(point["_value"], src, target, molar_mass)
        if new_val is None:
            listed = ", ".join(sorted({u for u in present}))
            return False, (
                f"readings use {len(distinct)} different units ({listed}) — "
                "values are not directly comparable, so no trend was computed. "
                "Re-check the source reports or record these under separate test names."
            )
        if _canonical_unit_key(src) != _canonical_unit_key(target):
            point["_original_value"] = point.get("value")
            point["_original_unit"] = src
            point["_value"] = new_val
            point["unit"] = target
            converted = True
    return converted, None


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

    recovered = _returned_to_normal(points, crossing)
    if recovered:
        # Crossed out of range (or started abnormal), but the latest
        # reading is back to normal. Reporting this as an ongoing
        # excursion ("has stayed there since") misrepresents a recovery.
        if crossing is not None:
            base += (
                f" It moved out of the normal range into the '{crossing['flag']}' range "
                f"at the {crossing.get('date', 'interim')} test, but the most recent reading is "
                f"back within the normal range."
            )
        else:
            base += (
                " It was outside the normal range earlier, but the most recent reading is "
                "back within the normal range."
            )
    elif _relapsed(points):
        last_cross = _last_crossing_point(points) or points[-1]
        base += (
            f" It was outside the normal range, returned to normal, then crossed back into "
            f"the '{last_cross['flag']}' range starting with the "
            f"{last_cross.get('date', 'most recent')} test."
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

    converted_from = sorted({
        str(p["_original_unit"]) for p in points if p.get("_original_unit")
    })
    if converted_from:
        base += (
            f" Some readings were converted to {unit} (from {', '.join(converted_from)}) "
            "so the series could be compared."
        )

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
            "returned_to_normal": bool,
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

        converted, unit_error = _harmonize_units(test_name, usable)
        if unit_error:
            insufficient.append({"test_name": test_name, "reason": unit_error})
            continue

        unit = usable[-1]["unit"]
        range_bounds = _parse_range(usable[-1]["reference_range"])

        direction = _direction([p["_value"] for p in usable], range_bounds)
        crossing = _crossing_point(usable)
        approaching = _approaching_boundary(usable[-1]["_value"], usable[-1]["flag"], range_bounds, direction)
        recovered = _returned_to_normal(usable, crossing)

        # Confidence: average of the source extraction confidences, discounted
        # for dropped/unusable readings, converted units, or disagreeing
        # reference ranges across visits.
        confidences = [p["confidence"] for p in usable if isinstance(p["confidence"], (int, float))]
        base_confidence = sum(confidences) / len(confidences) if confidences else 0.7
        if dropped:
            base_confidence *= max(0.5, 1 - 0.15 * dropped)
        if converted:
            base_confidence *= 0.9
        if len(ranges_seen) > 1:
            base_confidence *= 0.7

        data_points: List[Dict[str, Any]] = []
        for p in usable:
            point: Dict[str, Any] = {
                "date": p["date"],
                "value": (
                    _format_lab_number(p["_value"]) if p.get("_original_unit") else p["value"]
                ),
                "flag": p["flag"],
                "source_file": p["source_file"],
            }
            if p.get("_original_unit"):
                point["original_value"] = p.get("_original_value")
                point["original_unit"] = p["_original_unit"]
            data_points.append(point)

        trends.append({
            "test_name": test_name,
            "unit": unit,
            "reference_range": usable[-1]["reference_range"],
            "data_points": data_points,
            "direction": direction,
            "flag_sequence": _flag_sequence_phrase([p["flag"] for p in usable]),
            "crossed_into_abnormal_at": (
                {"date": crossing["date"], "flag": crossing["flag"]} if crossing else None
            ),
            "returned_to_normal": recovered,
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


def lab_trends_payload_is_stale(payload: Any) -> bool:
    """True when a persisted lab_trends blob predates returned_to_normal
    or still declines a series that unit conversion can now analyse."""
    if not isinstance(payload, dict):
        return True
    trends = payload.get("trends")
    if not isinstance(trends, list):
        return True
    for trend in trends:
        if not isinstance(trend, dict) or "returned_to_normal" not in trend:
            return True
    for item in payload.get("insufficient_data") or []:
        if not isinstance(item, dict):
            continue
        reason = (item.get("reason") or "").lower()
        if "different units" in reason or "not directly comparable" in reason:
            return True
    return False


def resolve_lab_trends(timeline: Dict[str, Any], saved: Any = None) -> Dict[str, Any]:
    """Return a trends report, recomputing when the saved payload is stale.

    GET /lab-trends used to return the snapshot as stored, so a recovery
    that was analysed before `returned_to_normal` existed kept serving a
    red-alarm payload even after the wording fix shipped.
    """
    if saved is None or lab_trends_payload_is_stale(saved):
        return track_lab_trends(timeline)
    return saved


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
    assert by_name["Fasting Glucose"]["returned_to_normal"] is False

    assert by_name["ALT"]["direction"] == "increasing"
    assert by_name["ALT"]["crossed_into_abnormal_at"]["date"] == "30 Aug 2026"

    assert by_name["Creatinine"]["direction"] == "increasing"
    assert by_name["Creatinine"]["crossed_into_abnormal_at"] is None
    assert by_name["Creatinine"]["approaching_threshold"] is True

    # Regression check for the reference-range parsing bug (hyphen
    # mis-read as a negative sign): must render as "70-99", not "-99-70".
    assert "70-99 mg/dL" in by_name["Fasting Glucose"]["explanation"], by_name["Fasting Glucose"]["explanation"]

    for t in result["trends"]:
        print(f"--- {t['test_name']} ---")
        print(" direction:", t["direction"], "| flags:", t["flag_sequence"], "| confidence:", t["confidence"])
        print(" ", t["explanation"])
        print()

    print("All checks passed.")
