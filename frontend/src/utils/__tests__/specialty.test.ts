/**
 * Covers the specialty suggestion chain: keyword → potential specialty →
 * professional verification. Nothing here may invent a specialty when the
 * record contains no signal.
 *
 * Run with: npm run test:specialty
 */
import assert from "node:assert/strict";

import type { PatientSnapshot, Visit } from "../../types/api";
import { SPECIALTY_OPTIONS, specialtyLabel, suggestSpecialty } from "../specialty";

function visit(partial: Partial<Visit>): Visit {
  return {
    document_type: "other",
    date: "2026-01-01",
    provider_or_doctor: null,
    patient_name: "Arun Kumar",
    medications: [],
    lab_results: [],
    allergies_noted: [],
    clinical_notes: null,
    illegible_or_low_confidence_fields: [],
    overall_confidence: 0.9,
    _source: { file: "Arun (2).jpg", method: "vision_ocr" },
    ...partial,
  };
}

function snapshot(visits: Visit[]): PatientSnapshot {
  return {
    user_id: "arun",
    patient_timeline: {
      visits,
      medications_timeline: [],
      lab_results_timeline: [],
      known_allergies: [],
    },
    cross_check_report: {} as PatientSnapshot["cross_check_report"],
    lab_trends: {} as PatientSnapshot["lab_trends"],
    updated_at: null,
  };
}

const tests: Array<[string, () => void]> = [
  [
    "an abdominal note suggests gastroenterology with its evidence",
    () => {
      const result = suggestSpecialty(
        snapshot([
          visit({
            clinical_notes: "Patient reports abdominal discomfort after meals.",
            overall_confidence: 0.4,
            _source: { file: "Arun (2).jpg", method: "vision_ocr" },
          }),
        ])
      );
      assert.ok(result);
      assert.equal(result.specialty, "gastroenterologist");
      assert.equal(result.label, "Gastroenterologist");
      assert.equal(result.keyword, "abdominal");
      assert.deepEqual(result.evidence, ["Arun (2).jpg"]);
      assert.equal(result.lowConfidenceCount, 1);
    },
  ],
  [
    "no keyword in the record means no suggestion is fabricated",
    () => {
      const result = suggestSpecialty(
        snapshot([visit({ clinical_notes: "Routine annual check-up. All well." })])
      );
      assert.equal(result, null);
    },
  ],
  [
    "an empty or missing snapshot yields no suggestion",
    () => {
      assert.equal(suggestSpecialty(null), null);
      assert.equal(suggestSpecialty(snapshot([])), null);
    },
  ],
  [
    "lab names are also a valid signal",
    () => {
      const result = suggestSpecialty(
        snapshot([
          visit({
            lab_results: [
              {
                test_name: "HbA1c",
                value: "8.1",
                unit: "%",
                reference_range: "<5.7",
                flag: "high",
                confidence: 0.95,
              },
            ],
          }),
        ])
      );
      assert.ok(result);
      assert.equal(result.specialty, "endocrinologist");
      assert.equal(result.lowConfidenceCount, 0);
    },
  ],
  [
    "every option carries a human label and the labels round-trip",
    () => {
      for (const option of SPECIALTY_OPTIONS) {
        assert.ok(option.label.length > 0, option.value);
        assert.equal(specialtyLabel(option.value), option.label);
      }
      assert.equal(specialtyLabel("hepatologist"), "Hepatologist");
      assert.equal(specialtyLabel(""), "");
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
