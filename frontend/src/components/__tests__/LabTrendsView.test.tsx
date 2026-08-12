/**
 * The recovery badge used to be an unconditional red "crossed to high on
 * DATE" chip rendered from `crossed_into_abnormal_at`, even when the
 * latest reading was back to normal. The paragraph below said the
 * patient had recovered; the badge — what gets read first — still
 * screamed alarm.
 *
 * Run via `npm test` / `npm run test:labs`.
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";

import type { LabTrend, LabTrendsReport } from "../../types/api";
import { LabTrendsView } from "../LabTrendsView";
import { isRecoveredTrend, trendAlertBadges } from "../labTrendBadges";

const dom = new JSDOM("<!DOCTYPE html><html><body><div id='root'></div></body></html>");
(globalThis as Record<string, unknown>).window = dom.window;
(globalThis as Record<string, unknown>).document = dom.window.document;
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node 22 already exposes a read-only navigator.
}

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(`FAIL: ${msg}`);
  console.log(`PASS: ${msg}`);
}

function baseTrend(overrides: Partial<LabTrend> = {}): LabTrend {
  return {
    test_name: "Glucose",
    unit: "mg/dL",
    reference_range: "70-99",
    data_points: [
      { date: "2024-01-01", value: "91", flag: "normal", source_file: "a.pdf" },
      { date: "2024-03-11", value: "130", flag: "high", source_file: "b.pdf" },
      { date: "2024-06-01", value: "88", flag: "normal", source_file: "c.pdf" },
    ],
    direction: "fluctuating (net decreasing)",
    flag_sequence: "normal → high → normal",
    crossed_into_abnormal_at: { date: "2024-03-11", flag: "high" },
    returned_to_normal: true,
    approaching_threshold: false,
    confidence: 0.9,
    explanation: "the most recent reading is back within the normal range",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Pure badge logic — the bug lives here even before React renders.
// ---------------------------------------------------------------------------

{
  const badges = trendAlertBadges(baseTrend());
  assert(badges.length === 1, `recovery has one alert badge (got ${badges.length})`);
  assert(badges[0].tone === "success", `recovery badge is success, not ${badges[0].tone}`);
  assert(
    badges[0].label.includes("returned to normal"),
    `recovery badge says returned to normal (got ${badges[0].label})`
  );
  assert(
    !badges.some((b) => b.tone === "danger"),
    "recovery must not render a danger badge"
  );
}

{
  const ongoing = baseTrend({
    returned_to_normal: false,
    data_points: [
      { date: "2024-01-01", value: "91", flag: "normal", source_file: "a.pdf" },
      { date: "2024-03-11", value: "130", flag: "high", source_file: "b.pdf" },
    ],
    explanation: "has stayed there since",
  });
  const badges = trendAlertBadges(ongoing);
  assert(badges[0].tone === "danger", "ongoing crossing stays danger");
  assert(
    badges[0].label === "crossed to high on 2024-03-11",
    `ongoing label is the red alarm (got ${badges[0].label})`
  );
}

{
  // Persisted snapshot from before returned_to_normal existed.
  const legacy = baseTrend({ returned_to_normal: undefined });
  assert(isRecoveredTrend(legacy) === true, "legacy payload with last flag normal is treated as recovered");
  const badges = trendAlertBadges(legacy);
  assert(badges[0].tone === "success", "legacy recovery is not a red badge");
}

{
  const approaching = baseTrend({
    crossed_into_abnormal_at: null,
    returned_to_normal: false,
    approaching_threshold: true,
    data_points: [
      { date: "2024-01-01", value: "75", flag: "normal", source_file: "a.pdf" },
      { date: "2024-03-11", value: "97", flag: "normal", source_file: "b.pdf" },
    ],
  });
  const badges = trendAlertBadges(approaching);
  assert(badges.length === 1 && badges[0].tone === "warning", "approaching-only is a warning badge");
}

{
  const relapse = baseTrend({
    returned_to_normal: false,
    data_points: [
      { date: "2024-01-01", value: "130", flag: "high", source_file: "a.pdf" },
      { date: "2024-03-11", value: "88", flag: "normal", source_file: "b.pdf" },
      { date: "2024-06-01", value: "125", flag: "high", source_file: "c.pdf" },
    ],
    flag_sequence: "high → normal → high",
    explanation: "returned to normal, then crossed back",
  });
  const badges = trendAlertBadges(relapse);
  assert(badges[0].tone === "danger", "relapse keeps the danger badge");
}

// ---------------------------------------------------------------------------
// Render: the red chip must not sit above the recovery paragraph.
// ---------------------------------------------------------------------------

function renderReport(report: LabTrendsReport): { html: string; unmount: () => void } {
  const container = document.getElementById("root")!;
  container.innerHTML = "";
  let root!: Root;
  act(() => {
    root = createRoot(container);
    root.render(
      <StrictMode>
        <LabTrendsView report={report} />
      </StrictMode>
    );
  });
  return {
    html: container.innerHTML,
    unmount: () => {
      act(() => {
        root.unmount();
      });
    },
  };
}

{
  const { html, unmount } = renderReport({
    trends: [baseTrend()],
    insufficient_data: [],
    note: "Not a diagnosis.",
  });
  assert(html.includes("returned to normal"), "rendered recovery badge text");
  assert(html.includes("back within the normal range"), "rendered recovery paragraph");
  const dangerChips = Array.from(document.querySelectorAll('[data-tone="danger"]')).map(
    (el) => el.textContent || ""
  );
  assert(
    dangerChips.every((text) => !text.includes("crossed to")),
    `no danger 'crossed to' chip on recovery (saw ${JSON.stringify(dangerChips)})`
  );
  const successChips = Array.from(document.querySelectorAll('[data-tone="success"]')).map(
    (el) => el.textContent || ""
  );
  assert(
    successChips.some((text) => text.includes("returned to normal")),
    `success chip carries the recovery label (saw ${JSON.stringify(successChips)})`
  );
  unmount();
}

{
  const { html, unmount } = renderReport({
    trends: [
      baseTrend({
        returned_to_normal: undefined,
      }),
    ],
    insufficient_data: [],
    note: "Not a diagnosis.",
  });
  assert(html.includes("returned to normal"), "legacy snapshot still renders recovery, not a red alarm");
  assert(
    !Array.from(document.querySelectorAll('[data-tone="danger"]')).some((el) =>
      (el.textContent || "").includes("crossed to")
    ),
    "legacy recovery does not render a danger crossing chip"
  );
  unmount();
}

{
  const { html, unmount } = renderReport({
    trends: [
      baseTrend({
        data_points: [
          {
            date: "2024-01-01",
            value: "5.27",
            flag: "normal",
            source_file: "a.pdf",
            original_value: "95",
            original_unit: "mg/dL",
          },
          { date: "2024-04-01", value: "5.3", flag: "normal", source_file: "b.pdf" },
        ],
        unit: "mmol/L",
        reference_range: "3.9-5.5",
        crossed_into_abnormal_at: null,
        returned_to_normal: false,
        direction: "stable",
        explanation: "Some readings were converted to mmol/L",
      }),
    ],
    insufficient_data: [],
    note: "Not a diagnosis.",
  });
  assert(html.includes("from 95 mg/dL"), "converted readings show the source value in the table");
  unmount();
}

console.log("\nAll LabTrendsView tests passed.");
