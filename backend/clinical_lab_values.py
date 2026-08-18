"""
Shared lab-value lookup helpers for the deterministic clinical-safety engines
================================================================================
The renal/hepatic and drug-lab engines both need the same primitive: "what is
this patient's most recent numeric value for a given lab test, and is it
abnormal?" This module centralizes that so both engines share one tolerant
parser and one definition of "high"/"low", instead of each re-implementing it
(and silently disagreeing).

Design mirrors lab_trends.py: values are parsed defensively (censored markers
like "<0.01" and ranges in the value column are rejected, not guessed), and a
lab is called abnormal only on POSITIVE evidence — either a published clinical
threshold is crossed, or the extractor's own `flag` field says high/low. A
missing or unparsable value is never treated as abnormal.

This is a reasoning layer over extracted text, NOT a validated clinical
database. Every caller keeps the "consult a professional" framing.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:  # reuse the already-hardened parser from lab_trends
    from lab_trends import _parse_value as _lt_parse_value, _parse_date as _lt_parse_date
except Exception:  # pragma: no cover - lab_trends always present in-tree
    _lt_parse_value = None
    _lt_parse_date = None


# --------------------------------------------------------------------------- #
# Aliases — the many ways the same analyte is printed on a report.
# Matched as whole-word, case-insensitive substrings of the normalized test
# name. Kept deliberately specific so "K" does not match "CK" or "potassium".
# --------------------------------------------------------------------------- #

_LAB_ALIASES: Dict[str, Tuple[str, ...]] = {
    "potassium": ("potassium", "k+", " k ", "k (serum)", "serum k"),
    "sodium": ("sodium", "na+", "serum sodium", "na (serum)"),
    "creatinine": ("creatinine", "serum creatinine", "creat"),
    "egfr": ("egfr", "e-gfr", "e.g.f.r", "estimated glomerular", "glomerular filtration"),
    "bun": ("bun", "blood urea nitrogen", "urea nitrogen"),
    "urea": ("urea", "blood urea"),
    "inr": ("inr", "international normalized ratio"),
    "alt": ("alt", "alanine aminotransferase", "alanine transaminase", "sgpt"),
    "ast": ("ast", "aspartate aminotransferase", "aspartate transaminase", "sgot"),
    "bilirubin": ("bilirubin", "total bilirubin", "serum bilirubin"),
    "albumin": ("albumin", "serum albumin"),
    "platelet": ("platelet", "platelets", "plt"),
    "hemoglobin": ("hemoglobin", "haemoglobin", "hgb", "hb"),
    "magnesium": ("magnesium", "mg", "serum magnesium"),
    "glucose": ("glucose", "blood glucose", "fasting glucose", "fbs", "rbs"),
}


def _norm_test_name(name: Any) -> str:
    return re.sub(r"\s+", " ", str(name or "")).strip().lower()


def _matches_alias(name_norm: str, aliases: Tuple[str, ...]) -> bool:
    # exact short symbols ("k", "na") must be whole-token matches to avoid
    # colliding with substrings; long phrases can be substring matches.
    for alias in aliases:
        alias = alias.strip().lower()
        if not alias:
            continue
        if len(alias) <= 3:
            # token-boundary match
            if re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", f" {name_norm} "):
                return True
        else:
            if alias in name_norm:
                return True
    return False


def _parse_numeric(value: Any) -> Optional[float]:
    if _lt_parse_value is not None:
        try:
            return _lt_parse_value(value)
        except Exception:
            return None
    # fallback minimal parser
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str):
        return None
    m = re.search(r"[-+]?(?:\d+(?:\.\d+)?|\.\d+)", value)
    return float(m.group()) if m else None


def _parse_lab_date(entry: Dict[str, Any]) -> Optional[datetime]:
    for key in ("date", "measured_at", "result_date", "document_date"):
        raw = entry.get(key)
        if not raw:
            continue
        if _lt_parse_date is not None:
            try:
                d = _lt_parse_date(raw)
                if d is not None:
                    return d
            except Exception:
                pass
        try:
            return datetime.fromisoformat(str(raw)[:19])
        except Exception:
            continue
    return None


@staticmethod
def _static_noop() -> None:  # pragma: no cover - keeps flake quiet
    return None


class LabValue:
    """Most-recent numeric reading of one analyte for one patient."""

    __slots__ = ("analyte", "value", "unit", "flag", "entry", "date")

    def __init__(
        self,
        analyte: str,
        value: Optional[float],
        unit: Optional[str],
        flag: Optional[str],
        entry: Optional[Dict[str, Any]] = None,
        date: Optional[datetime] = None,
    ) -> None:
        self.analyte = analyte
        self.value = value
        self.unit = (unit or "").strip().lower() or None
        self.flag = (str(flag or "")).strip().lower() or None
        self.entry = entry
        self.date = date

    @property
    def present(self) -> bool:
        return self.value is not None

    def unit_has(self, *fragments: str) -> bool:
        if not self.unit:
            return False
        return any(f in self.unit for f in fragments)


def latest_lab_value(timeline: Dict[str, Any], analyte: str) -> Optional[LabValue]:
    """Return the most recent numeric reading for `analyte` (one of the keys in
    _LAB_ALIASES), or None if the patient has no parseable reading."""
    aliases = _LAB_ALIASES.get(analyte)
    if aliases is None:
        return None
    labs: List[Dict[str, Any]] = (
        list(timeline.get("lab_results_timeline") or [])
        + list(timeline.get("lab_results") or [])
    )

    best: Optional[Tuple[Optional[datetime], LabValue]] = None
    for entry in labs:
        if not isinstance(entry, dict):
            continue
        if (entry.get("_trust") or {}).get("quarantined"):
            continue
        name_norm = _norm_test_name(entry.get("test_name") or entry.get("name"))
        if not _matches_alias(name_norm, aliases):
            continue
        value = _parse_numeric(entry.get("value"))
        if value is None:
            continue
        date = _parse_lab_date(entry)
        candidate = LabValue(
            analyte, value, entry.get("unit"), entry.get("flag"), entry, date
        )
        # most recent wins; undated entries are kept only if nothing dated exists
        if best is None:
            best = (date, candidate)
        else:
            prev_date = best[0]
            if date is not None and (prev_date is None or date > prev_date):
                best = (date, candidate)
    return best[1] if best else None


def collect_lab_values(timeline: Dict[str, Any], analytes: List[str]) -> Dict[str, LabValue]:
    out: Dict[str, LabValue] = {}
    for analyte in analytes:
        lv = latest_lab_value(timeline, analyte)
        if lv is not None and lv.present:
            out[analyte] = lv
    return out


# --------------------------------------------------------------------------- #
# Abnormality: a lab is abnormal on POSITIVE evidence only.
#   1. A fixed clinical threshold (in a known unit) is crossed, OR
#   2. the extractor's `flag` field is high/low.
# Both must be satisfied conservatively where a unit is ambiguous.
# --------------------------------------------------------------------------- #

def is_high(lv: LabValue, threshold: Optional[float], unit_fragments: Tuple[str, ...] = ()) -> bool:
    """True if the value provably exceeds `threshold` (when the unit is known
    to match `unit_fragments`, or when the unit is absent AND the flag is high)."""
    if lv.value is None or threshold is None:
        return False
    if lv.unit_has(*unit_fragments):
        return lv.value >= threshold
    if not lv.unit and lv.flag == "high":
        return lv.value >= threshold
    if lv.flag == "high" and not unit_fragments:
        return lv.value >= threshold
    return False


def is_low(lv: LabValue, threshold: Optional[float], unit_fragments: Tuple[str, ...] = ()) -> bool:
    if lv.value is None or threshold is None:
        return False
    if lv.unit_has(*unit_fragments):
        return lv.value <= threshold
    if not lv.unit and lv.flag == "low":
        return lv.value <= threshold
    if lv.flag == "low" and not unit_fragments:
        return lv.value <= threshold
    return False


def flagged_high(lv: LabValue) -> bool:
    """The extractor itself reported this reading as high (independent of any
    locally-coded threshold). Used when no canonical threshold applies."""
    return lv.flag == "high"


def flagged_low(lv: LabValue) -> bool:
    return lv.flag == "low"


def summarise_lab(lv: Optional[LabValue]) -> str:
    if lv is None or lv.value is None:
        return ""
    unit = lv.unit or ""
    date = lv.date.strftime("%Y-%m-%d") if lv.date else ""
    return f"{lv.analyte} {lv.value:g} {unit}".strip() + (f" ({date})" if date else "")
