# Lab trends

`lab_trends.py` is deterministic. No LLM. It reads `timeline["lab_results_timeline"]` and, per test name, describes how the number moved.

The explanation is a **template filled from computed facts**. It cannot invent a clinical story the numbers do not support.

## When a trend is produced

Group by lowercased `test_name` (display casing = first seen).

A point is usable only if the date parses (`dateutil` fuzzy) **and** the value parses as a number. Need **≥ 2** usable points. Otherwise the test goes to `insufficient_data` with a reason.

## Parsing

`_parse_value` consumes thousands separators. A bare `\d+(\.\d+)?` used to stop at the first comma:

| Printed | Parsed |
|---|---|
| `150,000` | 150000 (not 150) |
| `1.234,56` | 1234.56 (EU) |
| `5,3` | 5.3 (decimal comma) |
| `<5` | 5.0 (flag carries the censoring) |
| `true` / `false` | rejected (`bool` is an `int` subclass) |

`_parse_range` accepts `70-99`, `70 - 99 mg/dL`, `Reference: 0.74-1.35`, `70 to 99`, en/em dashes, and `150,000-450,000`. Single-bounded (`<5`, `>10`) returns `None` so we do not invent a second side for “approaching” math.

## Direction and crossings

- Net change vs 10% of range width → `stable`, else `increasing` / `decreasing`, or `fluctuating (net …)` if the steps disagree in sign.
- Crossing = first chronological `normal → not-normal`. Already-abnormal at the first reading is not a crossing.
- Approaching = last flag is `normal` and the last value sits within 15% of the boundary the series is moving toward.

Boundary wording uses **`"increasing" in direction`**, not `startswith("increasing")`. A noisy climb is `fluctuating (net increasing)` — the old check fell through and told the patient a rising glucose was heading for the **lower** bound.

## Recovery vs ongoing

`normal → high → normal` is a recovery.

| Field | Meaning |
|---|---|
| `crossed_into_abnormal_at` | still recorded — the excursion happened |
| `returned_to_normal` | `true` when a crossing exists and the **latest** flag is `normal` |
| explanation | “back within the normal range”, **not** “has stayed there since” |

The UI shows a **success** chip (`returned to normal (was high on DATE)`), not a red “crossed to high”. Old snapshots that omit `returned_to_normal` are recomputed on `GET /lab-trends` and `GET /patient-snapshot` (`api._lab_trends_for_snapshot`). The frontend also falls back to “last flag is normal”.

## Incompatible units

`95 mg/dL` then `5.3 mmol/L` is the same glucose. Subtracting them looked like a crash, and the template relabelled every point with the last unit (`from 95 mmol/L`) — a number in no source document.

If normalized units (case/whitespace-insensitive) disagree, the test is **declined** as `insufficient_data` with both units named. Cosmetic `mg/dL` vs `mg/dl ` still trends. A missing unit is unknown, not a conflict.

This branch does **not** convert `mg/dL` ↔ `mmol/L`. Conversion needs a per-analyte table; guessing is worse than declining.

## Output shape

```jsonc
{
  "trends": [{
    "test_name": "Fasting Glucose",
    "unit": "mg/dL",
    "reference_range": "70-99",
    "data_points": [{ "date", "value", "flag", "source_file" }],
    "direction": "increasing | decreasing | stable | fluctuating (net increasing|decreasing)",
    "flag_sequence": "normal → high → normal",
    "crossed_into_abnormal_at": { "date": "…", "flag": "high" } | null,
    "returned_to_normal": true,
    "approaching_threshold": false,
    "confidence": 0.9,
    "explanation": "template prose"
  }],
  "insufficient_data": [{ "test_name": "", "reason": "" }],
  "note": "not a diagnosis …"
}
```

Confidence is the mean of source confidences, discounted for dropped points and for disagreeing printed units/ranges (even when we still emit a trend).

## UI

`LabTrendsView` sparkline uses the same thousands-aware parse. Direction chips use `includes("increasing")` so fluctuating-up series share the rising tone.

## Fixtures

`generate_lab_test_data.py` builds `process_document()`-shaped pages with `_source.method = "synthetic"` (so `_is_demo_document` can drop them in folder grouping). `shape="fluctuating-rising"` is the boundary-wording regression.
