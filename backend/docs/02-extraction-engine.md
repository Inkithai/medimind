# ① Understand — file to timeline

```text
PDF / Image
     ↓
Extraction
     ↓
Validation
     ↓
Timeline
```

Upload creates or updates the patient record. Everything else is derived from that timeline.

---

## Data flow

```text
Upload
  │
  ▼
PDF / Image
  │
  ├── Digital PDF → text layer
  │
  └── Scanned / photo → vision extraction
              │
              ▼
        Medical extraction
              │
              ▼
        Document validation
              │
              ▼
        Patient timeline
              │
      ┌───────┼────────┐
      ▼       ▼        ▼
   Safety   Lab      Search index
            trends
```

Text vs vision is a capability split, not a vendor split:

```text
                 LLM provider layer
                        │
             ┌──────────┴──────────┐
             ▼                     ▼
        Text extraction        Vision extraction
```

---

## What the timeline holds

- visits (one extracted page each)
- medications, with source file and date
- lab results, with source file and date
- known allergies

Printed wording is kept for audit. Active ingredients are normalized to English generic names so two languages can still be compared. Vision reads are never treated as fully certain.

---

## Validation

A page is kept if it has structured medications, labs, or allergies — or a clinical document type with enough confidence.

A non-empty note alone is not enough. A screenshot can produce a note with no clinical content.

---

## Detect (same record, next step)

From the timeline, without diagnosing:

```text
Timeline
 ├── Medication safety
 ├── Allergy conflicts
 ├── Duplicate prescriptions
 └── Lab trends
```

Safety always defers to a clinician and states this is not a validated interaction database.

---

## Engineering notes (appendix)

Provider is configured with `LLM_PROVIDER` (Groq, Gemini, or any OpenAI-compatible endpoint). Optional OpenRouter fallback is only for a hard primary-quota failure. Gemini 2.0 Flash is retired — do not configure it.

Structured output walks a fallback ladder and strips reasoning tags. Hard quota fails immediately so a batch does not retry into a dead account.

Phone photos have orientation applied. Images are sent as reasonably sized JPEGs. Template-page detection is multilingual and word-anchored (`Sampleton` is not a demo). On HTTP upload, a file the user chose is not silently dropped as a template.

CLI: `python medical_extractor.py <files|folder> [--chat]`. The API persists to Supabase, not local JSON reports.
