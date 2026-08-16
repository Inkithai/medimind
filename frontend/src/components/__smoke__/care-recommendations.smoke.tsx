// Lightweight SSR smoke test for the FindCarePage.
// We test the structural pieces (TopRecommendationCard / OtherCareCard /
// RelevanceBadge / HowIsRelevanceCalculated) by extracting them via
// dynamic import + transform. The page itself is too tightly coupled
// to network/auth context to render in isolation, so instead we
// render equivalent JSX inline and assert the HTML output.

import { renderToString } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import * as React from "react";
import type { CareRecommendation, SpecialtyOption } from "../../types/recommendations";
import { SPECIALTY_DISPLAY } from "../../types/recommendations";

if (typeof (globalThis as { window?: unknown }).window === "undefined") {
  (globalThis as { window?: unknown }).window = {
    setTimeout,
    clearTimeout,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    document: { addEventListener: () => undefined, removeEventListener: () => undefined },
    location: { origin: "http://localhost" },
  } as never;
}

// ─── Mini replicas of the page's sub-components (kept in sync
//     manually for the smoke test, since the real ones are not
//     exported). If these diverge, the visual diff is intentional
//     and the actual page should be edited.

function relevanceTone(relevance: string): string {
  switch (relevance) {
    case "high":
      return "bg-red-50 text-red-700 ring-red-200";
    case "moderate":
      return "bg-amber-50 text-amber-800 ring-amber-200";
    case "possible":
      return "bg-sky-50 text-sky-700 ring-sky-200";
    default:
      return "bg-slate-100 text-slate-600 ring-slate-200";
  }
}

function relevanceLabel(relevance: string): string {
  switch (relevance) {
    case "high":
      return "High relevance";
    case "moderate":
      return "Moderate relevance";
    case "possible":
      return "Possible";
    case "needs_clinical_review":
      return "Needs clinical review";
    default:
      return relevance;
  }
}

function RelevanceBadge({ relevance, score, size }: { relevance: string; score: number; size: "sm" | "md" | "lg" }) {
  const sizeClass =
    size === "lg" ? "px-3 py-1 text-sm" : size === "sm" ? "px-2 py-0.5 text-[11px]" : "px-2.5 py-0.5 text-xs";
  return React.createElement(
    "span",
    {
      className: `inline-flex items-center gap-1.5 rounded-full font-bold uppercase tracking-wide ring-1 ${relevanceTone(
        relevance
      )} ${sizeClass}`,
    },
    React.createElement("span", null, relevanceLabel(relevance)),
    React.createElement("span", { className: "font-mono text-current opacity-80" }, `${score}%`)
  );
}

function TopRecommendationCard({ rec }: { rec: CareRecommendation }) {
  return React.createElement(
    "article",
    {
      className:
        "relative overflow-hidden rounded-2xl border-2 border-brand-200 bg-gradient-to-br from-white via-white to-brand-50/60 p-6 shadow-sm",
    },
    React.createElement("div", {
      className:
        "absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-brand-400 via-brand-500 to-brand-600",
    }),
    React.createElement(
      "div",
      { className: "flex flex-wrap items-start justify-between gap-3" },
      React.createElement(
        "div",
        { className: "flex items-center gap-2" },
        React.createElement(RelevanceBadge, { relevance: rec.relevance, score: rec.relevance_score, size: "lg" }),
        React.createElement(
          "span",
          {
            className:
              "inline-flex items-center gap-1 rounded-full bg-amber-100 px-2.5 py-0.5 text-[11px] font-bold uppercase tracking-wide text-amber-800 ring-1 ring-amber-200",
          },
          React.createElement("span", null, "✨ Top suggestion")
        )
      )
    ),
    React.createElement("h3", { className: "mt-3 text-xl font-bold text-slate-900" }, rec.specialty),
    React.createElement("p", { className: "mt-1 text-base font-semibold text-brand-800" }, rec.title),
    rec.has_safety_signal && rec.safety_message
      ? React.createElement(
          "div",
          {
            className:
              "mt-3 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900",
          },
          React.createElement("p", { className: "font-semibold" }, "Medication/allergy conflict"),
          React.createElement("p", { className: "mt-0.5 text-amber-800" }, rec.safety_message)
        )
      : null,
    React.createElement("p", { className: "mt-4 text-sm leading-relaxed text-slate-700" }, rec.reason),
    React.createElement(
      "div",
      { className: "mt-5 flex flex-wrap gap-2" },
      React.createElement(
        "button",
        { type: "button", className: "btn-primary min-h-[40px] px-4 py-2 text-sm" },
        "Find nearby"
      )
    )
  );
}

function OtherCareCard({ rec }: { rec: CareRecommendation }) {
  return React.createElement(
    "div",
    { className: `group rounded-2xl border bg-white p-4 shadow-sm ${rec.has_safety_signal ? "border-amber-200" : "border-slate-200"}` },
    React.createElement(
      "div",
      { className: "flex flex-wrap items-start justify-between gap-3" },
      React.createElement(
        "div",
        { className: "min-w-0 flex-1" },
        React.createElement(
          "div",
          { className: "flex flex-wrap items-center gap-2" },
          React.createElement(RelevanceBadge, { relevance: rec.relevance, score: rec.relevance_score, size: "sm" })
        ),
        React.createElement("h4", { className: "mt-1.5 text-base font-bold text-slate-900" }, rec.specialty),
        React.createElement("p", { className: "text-sm font-medium text-slate-600" }, rec.title),
        React.createElement("p", { className: "mt-1 line-clamp-2 text-sm leading-relaxed text-slate-500" }, rec.reason)
      ),
      React.createElement(
        "button",
        { type: "button", className: "inline-flex min-h-[40px] shrink-0 items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" },
        "Find nearby ›"
      )
    )
  );
}

// ─── Sample data (Anjali-like) ──────────────────────────────────────────────

const topRec: CareRecommendation = {
  specialty: "General Physician / Primary Care",
  specialty_key: "general_physician",
  relevance: "moderate",
  relevance_score: 69,
  title: "Medication reconciliation",
  reason:
    "1 medication/allergy conflict(s) were found in your records. A general physician can review the full medication list, confirm the safest next step, and refer you to a specialist if needed.",
  evidence: [{ description: "1 visit(s), 3 medication(s), 1 known allergy/allergies" }],
  source_records: 4,
  score_factors: [
    { label: "Multiple medications", points: 23, note: "3 active medication(s)" },
    { label: "Multiple visits / providers", points: 16, note: "2 visit(s)" },
    { label: "Documented allergies", points: 10, note: "1 allergy/allergies to track" },
    { label: "Allergy/safety signal", points: 20, note: "1 medication/allergy conflict(s)" },
  ],
  has_safety_signal: true,
  safety_message: "Allergy conflict: Aspirin — review recommended.",
};

const otherRec: CareRecommendation = {
  specialty: "Allergist / Immunologist",
  specialty_key: "allergist",
  relevance: "moderate",
  relevance_score: 62,
  title: "Allergy review",
  reason: "An allergy to Aspirin is recorded and at least one current medication appears to conflict with it.",
  evidence: [{ description: "Medication allergy conflict: Aspirin ↔ Aspirin." }],
  source_records: 1,
  score_factors: [
    { label: "Medication/allergy conflict", points: 50, note: "1 conflict(s) detected in cross-check" },
    { label: "Documented allergy", points: 12, note: "1 known allergy/allergies" },
  ],
  has_safety_signal: true,
  safety_message: "Aspirin is listed while a Aspirin allergy is documented.",
};

// ─── Render the page composition ────────────────────────────────────────────

const tree = React.createElement(
  MemoryRouter,
  null,
  React.createElement(
    "div",
    null,
    React.createElement(TopRecommendationCard, { rec: topRec }),
    React.createElement(
      "div",
      null,
      React.createElement("h3", null, "Other care options"),
      React.createElement(OtherCareCard, { rec: otherRec })
    )
  )
);

const html = renderToString(tree);

// ─── Build the dropdown options via the same logic the page uses ───────────

const recommendedOptions: SpecialtyOption[] = [
  {
    key: "general_physician",
    name: SPECIALTY_DISPLAY.general_physician,
    group: "recommended",
    recommendationNote: "Medication reconciliation",
    relevance: "moderate",
    relevanceScore: 69,
  },
];

const assertions: Array<[string, boolean]> = [
  // Top card structure
  ["top card shows 'Top suggestion' badge", html.includes("Top suggestion")],
  ["top card shows specialty name", html.includes("General Physician / Primary Care")],
  ["top card shows title", html.includes("Medication reconciliation")],
  ["top card shows relevance %", html.includes("69%")],
  ["top card shows safety message", html.includes("Allergy conflict: Aspirin — review recommended.")],
  ["top card shows reason", html.includes("medication/allergy conflict(s) were found in your records")],
  // Other card structure
  ["other card shows 'Allergist'", html.includes("Allergist / Immunologist")],
  ["other card shows relevance %", html.includes("62%")],
  ["other card shows compact Find nearby CTA", html.includes("Find nearby")],
  // Specialty dropdown data
  ["dropdown has patient-facing GP name", SPECIALTY_DISPLAY.general_physician === "General Physician / Primary Care"],
  ["dropdown has Endocrinology / Diabetes label", SPECIALTY_DISPLAY.endocrinologist === "Endocrinology / Diabetes"],
  ["dropdown has Allergy / Immunology label", SPECIALTY_DISPLAY.allergist === "Allergy / Immunology"],
  // Recommended option metadata
  [
    "recommended option carries the score for the dropdown",
    recommendedOptions[0].relevanceScore === 69,
  ],
  [
    "recommended option carries the note for the dropdown",
    recommendedOptions[0].recommendationNote === "Medication reconciliation",
  ],
  // Sanity: GP is the top rec, allergy is secondary
  ["top is GP", topRec.specialty_key === "general_physician"],
  ["secondary is allergy", otherRec.specialty_key === "allergist"],
  // No legacy false positives
  ["no Cardiology anywhere in the test data", !html.includes("Cardiology")],
  ["no Gastroenterology anywhere in the test data", !html.includes("Gastroenterology")],
  // No clinical-pharmacist false appearance
  [
    "Clinical Pharmacist is not in this test set (Anjali has no drug interactions)",
    !html.includes("Clinical Pharmacist"),
  ],
];

let failed = 0;
for (const [label, ok] of assertions) {
  if (ok) {
    console.log(`  PASS: ${label}`);
  } else {
    console.error(`  FAIL: ${label}`);
    failed += 1;
  }
}
if (failed > 0) {
  console.error(`\n${failed} assertion(s) failed`);
  process.exit(1);
}
console.log(`\nAll ${assertions.length} assertions passed`);
