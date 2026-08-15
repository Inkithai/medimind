# ② Detect — lab trends

**No language model. No diagnosis.**

This is the decision worth putting on a slide.

```text
Raw lab values
     ↓
Deterministic computation
     ↓
Direction
Crossing
Recovery
Threshold
     ↓
Explanation
   (filled from the numbers only)
```

MediMind does **not** ask a model “what does this glucose trend mean?” It computes the trend, then writes a constrained sentence from those facts.

| UI | Backend |
|---|---|
| `/labs` | `GET /api/v1/lab-trends` (dashboard uses the snapshot) |

---

## What the patient sees

For each test with at least two dated numeric points:

- direction — rising, falling, stable, or fluctuating
- flag sequence — e.g. normal → high → normal
- whether it crossed out of range
- whether it later **returned to normal** (shown as recovery, not a red alarm)
- whether a still-normal value is approaching a boundary

The page always states this is not a diagnosis.

---

## Honesty rules

- A noisy climb is heading toward the **upper** bound, not the lower one.
- Mixed units (`mg/dL` then `mmol/L`) produce **no** trend. Subtracting them would invent a crash.
- `150,000` is one hundred fifty thousand, not 150.
- `mg/dL` and `mg/dl` are the same unit. A missing unit is unknown, not a conflict.

---

## Engineering notes (appendix)

Dates are parsed fuzzily. Ranges accept `70-99` and `70 to 99`. A one-sided range (`<5`) disables boundary math.

`returned_to_normal` is stored on each trend. Older snapshots that omit it are recomputed when labs or the dashboard load, so a recovery does not stay a red badge.
