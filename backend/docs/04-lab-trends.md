# Patient intelligence — lab trends

How values move across visits. No language model. No diagnosis.

```text
Lab results on the timeline
            │
            ▼
   Group by test name
            │
            ▼
   Direction · crossing · recovery
            │
            ▼
   Plain-language explanation
   filled from the numbers only
```

Module: `lab_trends.py`. Shown on `/labs`.

---

## What the patient sees

For each test with at least two dated numeric points:

- direction — rising, falling, stable, or fluctuating
- flag sequence — e.g. normal → high → normal
- whether it crossed out of range, and whether it later **returned to normal**
- whether a still-normal value is approaching a boundary
- a short explanation that can only say what the numbers support

A recovery is shown as a recovery (green “returned to normal”), not as an ongoing red alarm. The date of the excursion is still kept — it happened.

The page always states this is not a diagnosis.

---

## Honesty rules

- If the series is noisy but climbing, the wording must say it is heading toward the **upper** bound — not the lower one.
- If units disagree (`mg/dL` then `mmol/L`), no trend is computed. Subtracting them would invent a crash. A missing unit is not a conflict; `mg/dL` vs `mg/dl` is the same unit.
- Grouped numbers such as `150,000` are the full magnitude, not `150`.

---

## Engineering notes (not the main slide)

Dates are parsed fuzzily. Ranges accept `70-99`, `70 to 99`, and values with thousands separators. A one-sided range (`<5`) disables boundary math instead of inventing a second side.

`returned_to_normal` is stored on each trend. Older snapshots that lack the field are recomputed when the labs page or dashboard loads, so a recovered series does not stay a red badge.

The sparkline uses the same number parsing as the engine.
