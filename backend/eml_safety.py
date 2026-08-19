"""Conservative runtime evaluation of published EML age restrictions."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional


def patient_age_from_timeline(timeline: Dict[str, Any]) -> Optional[float]:
    ages = [
        float(visit["patient_age"])
        for visit in timeline.get("visits") or []
        if isinstance(visit, dict)
        and isinstance(visit.get("patient_age"), (int, float))
        and 0 <= float(visit["patient_age"]) <= 130
    ]
    return ages[-1] if ages else None


def _threshold_years(text: str) -> Optional[tuple[str, float]]:
    lowered = text.lower()
    unit_factor = 1.0
    if "month" in lowered:
        unit_factor = 1 / 12
    elif "week" in lowered:
        unit_factor = 1 / 52
    elif "day" in lowered:
        unit_factor = 1 / 365
    number = re.search(r"(?:<|under|below|younger than|less than)\s*(\d+(?:\.\d+)?)", lowered)
    if number:
        return "minimum", float(number.group(1)) * unit_factor
    number = re.search(r"(?:>|over|above|older than|more than)\s*(\d+(?:\.\d+)?)", lowered)
    if number:
        return "maximum", float(number.group(1)) * unit_factor
    return None


def evaluate_age_restrictions(
    age_years: Optional[float], rows: Iterable[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Flag only restrictions whose threshold syntax can be read unambiguously."""
    findings: List[Dict[str, Any]] = []
    if age_years is None:
        return findings
    for row in rows:
        restriction = str(row.get("restriction") or "")
        parsed = _threshold_years(restriction)
        if parsed is None:
            continue
        kind, threshold = parsed
        conflicts = age_years < threshold if kind == "minimum" else age_years > threshold
        if not conflicts:
            continue
        findings.append(
            {
                "medication": row.get("display_name") or row.get("wanted"),
                "patient_age_years": round(age_years, 2),
                "restriction": restriction,
                "source_page": row.get("source_page"),
                "population": row.get("population"),
                "severity": "high",
                "confidence": 0.95,
                "evidence_source": "reference_graph",
                "grounded": True,
                "explanation": (
                    f"The published essential-medicines list records this age restriction: "
                    f"{restriction}. Confirm the prescription with a doctor or pharmacist."
                ),
            }
        )
    return findings
