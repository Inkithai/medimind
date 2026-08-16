/**
 * Citation → document resolution.
 *
 * A citation that opens the WRONG document is worse than one that opens
 * nothing: it makes an unsupported claim look verified. These tests pin
 * exact-filename matching and page/date disambiguation.
 *
 * Run with: npm run test:sources
 */
import assert from "node:assert/strict";

import type { QASource, Timeline, Visit } from "../../types/api";
import { findVisitForSource } from "../sources";

function visit(file: string, partial: Partial<Visit> = {}): Visit {
  return {
    _document_id: `doc-${file}`,
    document_type: "prescription",
    date: "2026-08-07",
    provider_or_doctor: null,
    patient_name: "Arun Kumar",
    medications: [],
    lab_results: [],
    diagnoses: [],
    symptoms: [],
    procedures: [],
    vital_signs: [],
    imaging_results: [],
    allergies_noted: [],
    clinical_notes: null,
    illegible_or_low_confidence_fields: [],
    overall_confidence: 0.9,
    _source: { file, method: "vision_ocr" },
    ...partial,
  };
}

function timeline(visits: Visit[]): Timeline {
  return {
    visits,
    medications_timeline: [],
    lab_results_timeline: [],
    known_allergies: [],
  };
}

function source(partial: Partial<QASource> & { source_file: string }): QASource {
  return { date: "", ...partial };
}

const tests: Array<[string, () => void]> = [
  [
    "resolves a citation to its document",
    () => {
      const target = visit("Arun (2).jpg");
      const found = findVisitForSource(
        timeline([visit("Arun (1).jpg"), target, visit("Arun (4).jpg")]),
        source({ source_file: "Arun (2).jpg" })
      );
      assert.equal(found, target);
    },
  ],
  [
    "never resolves to a different document (no fuzzy matching)",
    () => {
      const found = findVisitForSource(
        timeline([visit("Arun (4).jpg")]),
        source({ source_file: "Arun (2).jpg" })
      );
      assert.equal(found, null, "a near-miss filename must not open another record");
    },
  ],
  [
    "a substring filename does not match",
    () => {
      assert.equal(
        findVisitForSource(
          timeline([visit("Arun (2).jpg extra.pdf")]),
          source({ source_file: "Arun (2).jpg" })
        ),
        null
      );
    },
  ],
  [
    "page disambiguates a multi-page document",
    () => {
      const page1 = visit("scan.pdf", { _source: { file: "scan.pdf", method: "text_layer", page: 1 } });
      const page2 = visit("scan.pdf", { _source: { file: "scan.pdf", method: "text_layer", page: 2 } });
      const found = findVisitForSource(
        timeline([page1, page2]),
        source({ source_file: "scan.pdf", page: 2 })
      );
      assert.equal(found, page2);
    },
  ],
  [
    "date disambiguates when no page is available",
    () => {
      const august = visit("repeat.jpg", { date: "2026-08-07" });
      const september = visit("repeat.jpg", { date: "2026-09-02" });
      const found = findVisitForSource(
        timeline([august, september]),
        source({ source_file: "repeat.jpg", date: "2026-09-02" })
      );
      assert.equal(found, september);
    },
  ],
  [
    "falls back to the first matching page rather than nothing",
    () => {
      const first = visit("scan.pdf", { _source: { file: "scan.pdf", method: "text_layer", page: 1 } });
      const second = visit("scan.pdf", { _source: { file: "scan.pdf", method: "text_layer", page: 2 } });
      const found = findVisitForSource(
        timeline([first, second]),
        source({ source_file: "scan.pdf", page: 99 })
      );
      assert.equal(found, first);
    },
  ],
  [
    "surrounding whitespace is tolerated on both sides",
    () => {
      const target = visit("  Arun (2).jpg  ");
      assert.equal(
        findVisitForSource(timeline([target]), source({ source_file: " Arun (2).jpg " })),
        target
      );
    },
  ],
  [
    "missing or empty inputs return null instead of throwing",
    () => {
      assert.equal(findVisitForSource(null, source({ source_file: "a.jpg" })), null);
      assert.equal(findVisitForSource(undefined, source({ source_file: "a.jpg" })), null);
      assert.equal(findVisitForSource(timeline([]), source({ source_file: "a.jpg" })), null);
      assert.equal(findVisitForSource(timeline([visit("a.jpg")]), null), null);
      assert.equal(findVisitForSource(timeline([visit("a.jpg")]), source({ source_file: "  " })), null);
    },
  ],
];

let failures = 0;
for (const [name, run] of tests) {
  try {
    run();
    console.log(`PASS ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`FAIL ${name}`);
    console.error(error);
  }
}
console.log(`\n${tests.length - failures}/${tests.length} tests passed`);
if (failures) process.exit(1);
