/**
 * Date and lab-value formatting.
 *
 * A record dated 2026-08-07 must read "Aug 7" for every user on earth.
 * `new Date("2026-08-07")` parses as UTC midnight, so west of UTC it
 * rendered as Aug 6 — a wrong date on a medical record.
 *
 * Run with: npm run test:format  (or via `npm test`, which sweeps timezones)
 */
import assert from "node:assert/strict";

import { formatDate } from "../format";

const TZ = process.env.TZ || "(system)";

const tests: Array<[string, () => void]> = [
  [
    "a date-only record keeps its calendar day in this timezone",
    () => {
      assert.equal(formatDate("2026-08-07"), "Aug 7, 2026", `wrong day in ${TZ}`);
      assert.equal(formatDate("2026-01-01"), "Jan 1, 2026");
      assert.equal(formatDate("2026-12-31"), "Dec 31, 2026");
    },
  ],
  [
    "a leap day survives the round trip",
    () => {
      assert.equal(formatDate("2024-02-29"), "Feb 29, 2024");
    },
  ],
  [
    "a full timestamp is still interpreted with its own offset",
    () => {
      // Explicitly zoned, so the local rendering is expected to shift.
      const rendered = formatDate("2026-08-07T22:30:00Z");
      assert.ok(/Aug (7|8), 2026/.test(rendered), rendered);
    },
  ],
  [
    "empty and unparseable values degrade gracefully",
    () => {
      assert.equal(formatDate(null), "—");
      assert.equal(formatDate(undefined), "—");
      assert.equal(formatDate(""), "—");
      assert.equal(formatDate("   "), "—");
      // Non-ISO text is passed through rather than mangled into a wrong date.
      assert.equal(formatDate("05 Jan 2026"), "05 Jan 2026");
      assert.equal(formatDate("unknown"), "unknown");
    },
  ],
  [
    "an impossible ISO date is not silently rolled over",
    () => {
      // JS would roll 2026-02-30 into March; better to show it verbatim than
      // to invent a date the record does not contain.
      const rendered = formatDate("2026-02-30");
      assert.ok(rendered === "2026-02-30" || rendered.includes("Feb"), rendered);
    },
  ],
];

let failures = 0;
for (const [name, run] of tests) {
  try {
    run();
    console.log(`PASS [${TZ}] ${name}`);
  } catch (error) {
    failures += 1;
    console.error(`FAIL [${TZ}] ${name}`);
    console.error(error);
  }
}
console.log(`\n${tests.length - failures}/${tests.length} tests passed in ${TZ}`);
if (failures) process.exit(1);

// --- locale consistency ------------------------------------------------------
// A calendar date and a timestamp shown side by side must be formatted in the
// SAME language. formatDate's date-only branch used the browser locale while
// its timestamp branch used the app's selected language, so switching the app
// to Sinhala or Tamil left plain dates in English.
{
  const { setRuntimeLanguage } = await import("../../i18n/runtime");
  try {
    setRuntimeLanguage("ta");
    const calendarDate = formatDate("2026-08-07");
    const timestamp = formatDate("2026-08-07T09:30:00Z");
    assert.notEqual(calendarDate, "Aug 7, 2026", "a Tamil user should not see an English date");
    assert.equal(
      calendarDate.replace(/[\d\s,]/g, "") === timestamp.replace(/[\d\s,]/g, ""),
      true,
      "calendar dates and timestamps use the same language",
    );
  } finally {
    setRuntimeLanguage("en");
  }
  assert.equal(formatDate("2026-08-07"), "Aug 7, 2026", "English output is unchanged");
  console.log("PASS: dates follow the selected language");
}
