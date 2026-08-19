import assert from "node:assert/strict";
import type { CrossCheckReport, DosageReport } from "../../types/api";
import { collectSafetyAlerts } from "../safety";

const empty: CrossCheckReport = {
  potential_drug_interactions: [],
  duplicate_prescriptions: [],
  conflicting_dosage_instructions: [],
  allergy_conflicts: [],
  overall_recommendation: "",
};

function test(name: string, fn: () => void) {
  fn();
  console.log(`PASS ${name}`);
}

test("counts every active safety category used by dashboard and safety page", () => {
  const report: CrossCheckReport = {
    ...empty,
    allergy_conflicts: [{ medication: "A", allergy: "B", explanation: "x", confidence: 0.9 }],
    concurrent_exposure: [
      {
        ingredient: "paracetamol",
        status: "concurrent",
        window_start: null,
        window_end: null,
        overlap_days: 1,
        sources: [],
        cumulative_daily_dose: null,
        dosage_unit: null,
        note: "overlap",
      },
    ],
    eml_age_conflicts: [{ medication: "C", explanation: "age", confidence: 0.95 }],
  };
  const dosage: DosageReport = {
    findings: [{ kind: "above_max_daily_dose", medication: "D", explanation: "high" }],
  };
  assert.equal(collectSafetyAlerts(report, dosage).length, 4);
});

test("does not mislabel medication changes as safety alerts", () => {
  const report: CrossCheckReport = {
    ...empty,
    medication_changes: [
      {
        medication: "A",
        previous: {
          date: null,
          source_file: null,
          dosage: "5mg",
          dosage_value: 5,
          dosage_unit: "mg",
          frequency: null,
          frequency_per_day: null,
          is_as_needed: false,
        },
        current: {
          date: null,
          source_file: null,
          dosage: "10mg",
          dosage_value: 10,
          dosage_unit: "mg",
          frequency: null,
          frequency_per_day: null,
          is_as_needed: false,
        },
        sources: [],
        explanation: "changed",
        confidence: 0.9,
      },
    ],
  };
  assert.equal(collectSafetyAlerts(report).length, 0);
});

test("excludes historical non-concurrent interactions", () => {
  const report: CrossCheckReport = {
    ...empty,
    potential_drug_interactions: [
      {
        medications_involved: ["A", "B"],
        explanation: "history",
        severity: "high",
        confidence: 0.9,
        timing: {
          status: "not_concurrent",
          window_start: null,
          window_end: null,
          overlap_days: 0,
          gap_days: 100,
          note: "apart",
        },
      },
    ],
  };
  assert.equal(collectSafetyAlerts(report).length, 0);
});

test("prefers cited guidance over a duplicate model finding for the same pair", () => {
  const report: CrossCheckReport = {
    ...empty,
    guideline_flagged_combinations: [
      { opioid: "Oxycodone", depressant: "Diazepam", plain: "warning" },
    ],
    potential_drug_interactions: [
      {
        medications_involved: ["Diazepam", "Oxycodone"],
        explanation: "model",
        severity: "high",
        confidence: 0.6,
      },
    ],
  };
  const alerts = collectSafetyAlerts(report);
  assert.equal(alerts.length, 1);
  assert.equal(alerts[0].evidenceSource, "published_reference");
});

console.log("All safety-summary tests passed.");
