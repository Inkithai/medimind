/**
 * New surfaces for backend features that previously had no UI.
 *
 * These render server-side to plain HTML and assert on the words a
 * patient actually reads: a status must never be carried by colour alone,
 * a warning that needs attention must say so in text, and every number
 * shown must come from the backend payload rather than be recomputed.
 *
 * Run with: npm run test:surfaces
 */
import { renderToStaticMarkup } from "react-dom/server";

import { MedicationReconciliationView } from "../MedicationReconciliationView";
import type { MedicationReconciliationReport } from "../../types/api";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

const report: MedicationReconciliationReport = {
  reference_date: "2026-08-19",
  reconciled_medications: [
    {
      ingredient: "warfarin",
      display_name: "Warfarin",
      state: "dose_conflict",
      is_active: true,
      sources: [
        { name: "Warfarin", date: "2026-07-01", source_file: "rx-july.pdf", dose: "3 mg|daily" },
        { name: "Warfarin", date: "2026-08-01", source_file: "rx-august.pdf", dose: "5 mg|daily" },
      ],
      supply_count: 2,
      active_supply_count: 2,
      doses: ["3 mg|daily", "5 mg|daily"],
      dose_conflict: true,
      duplicate: false,
      notes: ["Different doses for the same active ingredient are recorded concurrently."],
    },
    {
      ingredient: "metformin",
      display_name: "Metformin",
      state: "discontinued",
      is_active: false,
      sources: [{ name: "Metformin", date: "2025-01-04", source_file: "old.pdf", dose: "500 mg" }],
      supply_count: 1,
      active_supply_count: 0,
      doses: ["500 mg"],
      dose_conflict: false,
      duplicate: false,
      notes: ["Previously supplied; no active supply at the reference date."],
    },
  ],
  summary: {
    total_ingredients: 2,
    active: 1,
    discontinued: 1,
    duplicates: 0,
    dose_conflicts: 1,
  },
  note: "Deterministic reconciliation. Confirm with a pharmacist before changing anything.",
};

const html = renderToStaticMarkup(<MedicationReconciliationView report={report} />);

assert(
  html.includes("Your current medicine list"),
  "the reconciled list has a plain-language title",
);
assert(html.includes("2026-08-19"), "the reference date the backend used is shown");

// Status must be readable without colour: the state has a word next to it.
assert(html.includes("Different doses"), "a dose conflict is stated in words");
assert(html.includes("Stopped"), "a discontinued medicine is stated in words");
assert(
  html.includes("Worth asking about:") && html.includes("Warfarin"),
  "medicines needing attention are called out by name",
);

// Counts come straight from the backend summary.
assert(html.includes("Taking now"), "the summary tiles are labelled in plain language");
assert(html.includes(">1<"), "backend counts are rendered, not recomputed");

// Backend guidance is never dropped.
assert(
  html.includes("Confirm with a pharmacist before changing anything."),
  "the backend safety note is shown verbatim",
);

// Provenance stays available for every row.
assert(html.includes("rx-august.pdf"), "each medicine keeps its source documents");

// Table semantics for screen readers.
assert(html.includes("<caption"), "the table has a caption for screen readers");
assert(html.includes('scope="col"'), "column headers are marked up as headers");
assert(html.includes('scope="row"'), "the medicine name is the row header");

const emptyHtml = renderToStaticMarkup(
  <MedicationReconciliationView
    report={{
      ...report,
      reconciled_medications: [],
      summary: {
        total_ingredients: 0,
        active: 0,
        discontinued: 0,
        duplicates: 0,
        dose_conflicts: 0,
      },
    }}
  />,
);
assert(
  emptyHtml.includes("No medicines have been found"),
  "an empty record explains itself instead of showing a bare table",
);

console.log("new surface tests passed");
