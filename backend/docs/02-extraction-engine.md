# Patient data pipeline

How a file becomes a patient record.

```text
Upload
  │
  ▼
PDF / Image
  │
  ├── Digital PDF → text layer
  │
  └── Scanned / photo → vision OCR
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

Modules: `medical_extractor.py`, `document_filter.py`.

---

## What extraction produces

One structured page (or one page per scanned-PDF leaf):

- document type (prescription, lab report, discharge summary, other)
- date, provider, patient name
- medications with English generic ingredients and a normalized dose / frequency
- lab results with value, unit, range, and flag
- allergies and clinical notes
- confidence on the document and on each item

Printed wording is kept for audit. Ingredients are normalized to English generic names so two languages can still be compared.

Vision reads are never scored as fully certain. A digital text layer can be.

---

## Validation

After extraction, a cheap local filter decides whether the page is medical.

Kept if it has structured medications, labs, or allergies — or if it is labelled as a clinical type with enough confidence.

A non-empty clinical note alone is not enough. A screenshot can produce a note with no clinical content.

On HTTP upload, a page the user chose is not silently discarded as a “demo”. Folder / CLI grouping still drops template pages so a mixed sample folder cannot pollute a real timeline.

---

## Timeline and safety

Documents for one workspace are merged into one chronological record:

- visits
- medications timeline (date + source file)
- lab results timeline
- known allergies

Safety review then looks for:

- potential drug interactions
- duplicate prescriptions (same ingredient and dose on two documents)
- conflicting dosage instructions
- allergy conflicts

The written recommendation always defers to a clinician and states this is not a validated interaction database.

Lab trends and search indexing are the other two branches of the same record. See [04-lab-trends.md](04-lab-trends.md) and [03-retrieval-and-qa.md](03-retrieval-and-qa.md).

---

## Engineering notes (not the main slide)

Provider is selected with `LLM_PROVIDER` (Groq, Gemini, or any OpenAI-compatible endpoint). Gemini 2.0 Flash is retired — do not configure it.

Structured calls walk a fallback ladder (strict schema where the provider supports it → JSON object → plain text) and strip reasoning tags before parse. Transient rate limits are paced; a hard quota or retired model fails immediately so a batch does not retry into a dead account.

Digital PDFs use the embedded text layer. Images and scanned pages go through vision. Phone photos have orientation applied before the model sees them.

Template-page detection is multilingual and word-anchored so a real name such as Sampleton is not rejected.

CLI: `python medical_extractor.py <files|folder> [--chat]`. The HTTP API persists to Supabase instead of local JSON reports.
