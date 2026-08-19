/**
 * AI analysis log helpers.
 *
 * A confidence badge that silently disappears (because the score lives in
 * the result payload rather than on the record) reads as "the AI did not
 * score this", and a percentage rendered as a fraction reads as a
 * catastrophically low score. Both are misreadings of a medical record, so
 * they are pinned here.
 *
 * Run with: npm run test:analyses
 */
import assert from "node:assert/strict";

import type { AnalysisLogRecord } from "../../types/api";
import { analysisConfidence, analysisCounts, analysisPageCount, dedupeAnalyses } from "../analyses";

function record(partial: Partial<AnalysisLogRecord> = {}): AnalysisLogRecord {
  return {
    id: "document_extraction:doc_a",
    analysis_type: "document_extraction",
    result: {},
    confidence: null,
    summary: null,
    created_at: "2026-08-19T10:00:00Z",
    ...partial,
  };
}

// --- confidence ------------------------------------------------------------

assert.equal(analysisConfidence(record({ confidence: 0.92 })), 0.92);

// Falls back to the result payload (QA answers only carry it there).
assert.equal(
  analysisConfidence(record({ analysis_type: "qa", result: { confidence: 0.71 } })),
  0.71,
);
assert.equal(analysisConfidence(record({ result: { confidence_score: 0.44 } })), 0.44);

// A percentage-shaped value is normalized instead of rendering as 9200%.
assert.equal(analysisConfidence(record({ confidence: 92 })), 0.92);

// Unscored stays unscored — never 0, which would read as "no confidence".
assert.equal(analysisConfidence(record()), null);
assert.equal(analysisConfidence(record({ confidence: Number.NaN })), null);
assert.equal(analysisConfidence(record({ result: { confidence_score: null } })), null);

// The record's own score wins over the payload copy.
assert.equal(
  analysisConfidence(record({ confidence: 0.5, result: { confidence_score: 0.9 } })),
  0.5,
);

// --- counts ----------------------------------------------------------------

assert.deepEqual(
  analysisCounts(record({ result: { persisted_counts: { medications: 3, lab_results: 0 } } })),
  { medications: 3, lab_results: 0 },
);
assert.deepEqual(analysisCounts(record()), {});
assert.deepEqual(
  analysisCounts(record({ result: { persisted_counts: { medications: "x" } } as never })),
  { medications: 0 },
);

// --- page count ------------------------------------------------------------

assert.equal(analysisPageCount(record()), 1);
assert.equal(analysisPageCount(record({ result: { page_count: 3 } })), 3);
assert.equal(analysisPageCount(record({ result: { page_count: 0 } })), 1);

// --- de-duplication --------------------------------------------------------

const duplicated = [
  record({ id: "document_extraction:doc_a" }),
  record({ id: "document_extraction:doc_a" }),
  record({ id: "qa:session:1", analysis_type: "qa" }),
];
assert.deepEqual(
  dedupeAnalyses(duplicated).map((item) => item.id),
  ["document_extraction:doc_a", "qa:session:1"],
);

// Entries without an id are never merged together.
assert.equal(dedupeAnalyses([record({ id: "" }), record({ id: "" })]).length, 2);

console.log("analyses helper tests passed");
