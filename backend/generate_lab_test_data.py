"""
Synthetic Lab Report Test Data Generator
=========================================
Produces synthetic, schema-valid `lab_report` documents — the same shape
process_document() returns for a real extraction — without any OCR, LLM,
or network calls. This lets build_patient_timeline(), document_filter.py,
and lab_trends.py be exercised for free, with no provider quota burned and
no real PHI involved.

Each generated document matches the extraction schema in
medical_extractor.py (document_type="lab_report", medications=[], a set of
lab_results with test_name/value/unit/reference_range/flag/confidence,
allergies_noted=[], clinical_notes=None) plus a `_source` block, and always
carries at least one lab_result so it passes document_filter.py's
medical-content check.

Values are generated as a seeded random walk (with a configurable per-test
drift) around the reference range, so a multi-visit run produces a
realistic mix of stable / trending / threshold-crossing / noisy series for
exercising lab_trends.py.

`_source.method` is always "synthetic", which medical_extractor's
_is_demo_document() treats as a structural demo marker — so synthetic
fixtures can never be mistaken for real patient data if one is ever
accidentally fed to the upload pipeline.

Usage:
    python generate_lab_test_data.py --patient "jane doe" --visits 4 \
        --out test_data/lab_results_fixture.json

    # deterministic output for tests
    python generate_lab_test_data.py --patient "jane doe" --visits 4 \
        --seed 42 --out test_data/fixture.json

    # force a specific shape for one test (see SERIES_SHAPES)
    python generate_lab_test_data.py --patient "jane doe" --visits 4 \
        --shape fluctuating-rising --out test_data/noisy.json

Then:
    import json
    from medical_extractor import build_patient_timeline
    from document_filter import filter_non_medical_documents
    from lab_trends import track_lab_trends

    docs = json.load(open("test_data/lab_results_fixture.json"))
    kept, rejected = filter_non_medical_documents(docs)
    timeline = build_patient_timeline(kept)
    trends = track_lab_trends(timeline)
"""

import argparse
import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# name -> (unit, low, high, per-visit drift as a fraction of range width)
DEFAULT_TESTS: Dict[str, Tuple[str, float, float, float]] = {
    "Fasting Glucose": ("mg/dL", 70.0, 99.0, 0.12),
    "Creatinine": ("mg/dL", 0.6, 1.3, 0.10),
    "ALT": ("U/L", 7.0, 56.0, 0.12),
    "Hemoglobin": ("g/dL", 13.0, 17.0, 0.08),
    "LDL Cholesterol": ("mg/dL", 0.0, 129.0, 0.10),
}

DEFAULT_PROVIDERS = ["Dr. S. Perera", "Dr. A. Silva", "Dr. M. Fernando"]

# Series shapes that map onto the branches of lab_trends._direction().
# "fluctuating-rising" is the one that exposed the boundary-wording bug:
# a noisy series with a net upward drift returns
# "fluctuating (net increasing)", which does not start with "increasing".
SERIES_SHAPES = ("random-walk", "stable", "rising", "falling", "fluctuating-rising", "crossing")


def _flag_for(value: float, low: float, high: float) -> str:
    if value < low:
        return "low"
    if value > high:
        return "high"
    return "normal"


def _round_display(value: float) -> str:
    return f"{value:.1f}" if abs(value - round(value)) > 1e-9 else str(int(round(value)))


def _generate_series(
    low: float,
    high: float,
    drift_fraction: float,
    visits: int,
    rng: random.Random,
    start_bias: float = 0.5,
    shape: str = "random-walk",
) -> List[float]:
    """Produce `visits` readings for one test.

    `shape` selects the trajectory so callers can deterministically target a
    specific lab_trends._direction() branch:

      random-walk        slight upward bias, mixed outcomes (default)
      stable             stays within STABLE_CHANGE_FRACTION of the start
      rising / falling   monotonic, stays in range
      fluctuating-rising climbs toward the upper bound but with a dip, so the
                         per-step deltas are not all the same sign ->
                         "fluctuating (net increasing)"
      crossing           starts normal and ends beyond the upper bound
    """
    width = high - low
    step = max(width * drift_fraction, 0.01)
    start = low + start_bias * width

    if shape == "stable":
        return [start + rng.uniform(-0.01, 0.01) * width for _ in range(visits)]

    if shape in ("rising", "falling"):
        sign = 1.0 if shape == "rising" else -1.0
        headroom = (high - start) if sign > 0 else (start - low)
        # Leave a margin so a monotonic run stays inside the range.
        per_step = (headroom * 0.8) / max(visits - 1, 1)
        return [start + sign * per_step * i for i in range(visits)]

    if shape == "fluctuating-rising":
        # Climb to just inside the upper bound, then dip slightly on the
        # final reading. Net change is positive, per-step deltas are not.
        headroom = high - start
        per_step = (headroom * 0.92) / max(visits - 1, 1)
        series = [start + per_step * i for i in range(visits)]
        if visits >= 3:
            series[-1] = series[-2] - per_step * 0.15
        return series

    if shape == "crossing":
        # End clearly above the upper bound to trip a normal -> high crossing.
        overshoot = high + width * 0.15
        per_step = (overshoot - start) / max(visits - 1, 1)
        return [start + per_step * i for i in range(visits)]

    # random-walk (default)
    value = start
    series = [value]
    for _ in range(visits - 1):
        value += rng.uniform(-step, step * 1.6)  # slight upward bias, tunable
        series.append(value)
    return series


def generate_patient_documents(
    patient_name: str,
    visits: int = 3,
    tests: Optional[Dict[str, Tuple[str, float, float, float]]] = None,
    start_date: Optional[datetime] = None,
    interval_days: int = 30,
    seed: Optional[int] = None,
    shape: str = "random-walk",
) -> List[Dict[str, Any]]:
    """
    Builds `visits` synthetic lab_report documents for one patient, each
    dated `interval_days` apart, each carrying a reading for every test in
    `tests` (defaults to DEFAULT_TESTS). Returns a flat list of dicts in
    the same shape process_document() returns — ready to feed straight into
    filter_non_medical_documents() / build_patient_timeline().

    Pass `seed` for reproducible output (required for use in tests) and
    `shape` to force a specific trend trajectory.
    """
    if visits < 1:
        raise ValueError("visits must be >= 1")
    if shape not in SERIES_SHAPES:
        raise ValueError(f"shape must be one of {SERIES_SHAPES}, got {shape!r}")

    rng = random.Random(seed)
    tests = tests or DEFAULT_TESTS
    if start_date is None:
        start_date = datetime.now(timezone.utc) - timedelta(days=interval_days * (visits - 1))

    # One series per test, shared across all visits for this patient.
    series_by_test = {
        name: _generate_series(
            low, high, drift, visits, rng,
            start_bias=rng.uniform(0.35, 0.65),
            shape=shape,
        )
        for name, (unit, low, high, drift) in tests.items()
    }

    documents: List[Dict[str, Any]] = []
    for visit_index in range(visits):
        visit_date = start_date + timedelta(days=interval_days * visit_index)
        date_str = visit_date.strftime("%Y-%m-%d")
        provider = DEFAULT_PROVIDERS[visit_index % len(DEFAULT_PROVIDERS)]

        lab_results = []
        for test_name, (unit, low, high, _drift) in tests.items():
            value = series_by_test[test_name][visit_index]
            lab_results.append({
                "test_name": test_name,
                "value": _round_display(value),
                "unit": unit,
                "reference_range": f"{_round_display(low)}-{_round_display(high)}",
                "flag": _flag_for(value, low, high),
                "confidence": round(rng.uniform(0.9, 0.98), 2),
            })

        filename = f"synthetic_lab_report_{visit_index + 1}.pdf"
        documents.append({
            "document_type": "lab_report",
            "date": date_str,
            "provider_or_doctor": provider,
            "patient_name": patient_name,
            "medications": [],
            "lab_results": lab_results,
            "allergies_noted": [],
            "clinical_notes": None,
            "illegible_or_low_confidence_fields": [],
            "overall_confidence": round(rng.uniform(0.9, 0.98), 2),
            # method="synthetic" is a structural demo marker recognised by
            # medical_extractor._is_demo_document(), so a fixture can never
            # be silently ingested as real patient data.
            "_source": {"file": filename, "method": "synthetic"},
        })

    return documents


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate synthetic, schema-valid lab_report test data (no OCR/LLM calls)."
    )
    parser.add_argument("--patient", required=True, help="Patient name, e.g. \"jane doe\"")
    parser.add_argument("--visits", type=int, default=3, help="Number of dated visits to generate (default: 3)")
    parser.add_argument("--out", required=True, help="Output JSON file path")
    parser.add_argument(
        "--interval-days", type=int, default=30,
        help="Days between consecutive visits (default: 30)",
    )
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible output")
    parser.add_argument(
        "--shape", default="random-walk", choices=SERIES_SHAPES,
        help="Trend trajectory to generate (default: random-walk)",
    )
    args = parser.parse_args()

    documents = generate_patient_documents(
        patient_name=args.patient,
        visits=args.visits,
        interval_days=args.interval_days,
        seed=args.seed,
        shape=args.shape,
    )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(documents, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(documents)} synthetic lab_report document(s) for '{args.patient}' to {out_path}")


if __name__ == "__main__":
    main()
