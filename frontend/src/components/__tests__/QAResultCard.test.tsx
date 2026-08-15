/**
 * Renders an Ask AI answer and pins the trust-critical UI contract:
 * the answer, its confidence, and citations the user can actually open —
 * plus an honest empty state when nothing supported the answer.
 *
 * Run with: npm run test:qacard
 */
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";

import { QAResultCard } from "../QAResultCard";
import type { QAResponse } from "../../types/api";

const GROUNDED: QAResponse = {
  answer: "You are taking Paracetamol 500mg twice daily.",
  confidence: 0.92,
  sources: [
    { date: "2026-08-07", source_file: "Arun (2).jpg", page: 1 },
    { date: "2026-08-11", source_file: "Arun (4).jpg", page: null },
  ],
  recommend_professional_consult: false,
};

const UNGROUNDED: QAResponse = {
  answer: "I couldn't find a blood pressure reading in your uploaded records.",
  confidence: 0.1,
  sources: [],
  recommend_professional_consult: false,
};

const RISKY: QAResponse = {
  answer: "Your records list Ferrous sulfate. Whether to stop it is a decision for your doctor.",
  confidence: 0.8,
  sources: [{ date: "2026-08-07", source_file: "Arun (2).jpg", page: 1 }],
  recommend_professional_consult: true,
};

function render(result: QAResponse, extra: Record<string, unknown> = {}): string {
  return renderToStaticMarkup(<QAResultCard result={result} {...extra} />);
}

const tests: Array<[string, () => void]> = [
  [
    "shows the answer, its confidence, and every cited source",
    () => {
      const html = render(GROUNDED);
      assert.ok(html.includes("Paracetamol 500mg twice daily"));
      assert.ok(html.includes("92%"), "confidence percentage");
      assert.ok(html.includes("Arun (2).jpg"));
      assert.ok(html.includes("Arun (4).jpg"));
      assert.ok(html.includes("2 sources"));
    },
  ],
  [
    "shows a page number only when the citation has one",
    () => {
      const html = render(GROUNDED);
      assert.ok(html.includes("page 1"), "page shown for the page-1 citation");
      assert.ok(!html.includes("page null"));
      assert.ok(!html.includes("page undefined"));
    },
  ],
  [
    "an answer with no sources says so instead of looking authoritative",
    () => {
      const html = render(UNGROUNDED);
      assert.ok(html.includes("No sources cited"));
      assert.ok(html.includes("treat it with care"));
    },
  ],
  [
    "a risk-related answer carries the consult-a-professional warning",
    () => {
      const html = render(RISKY);
      assert.ok(html.includes("Check with a healthcare professional"));
      assert.ok(!render(GROUNDED).includes("Check with a healthcare professional"));
    },
  ],
  [
    "citations are buttons with accessible names when navigation is wired up",
    () => {
      const html = render(GROUNDED, { onOpenSource: () => {} });
      assert.ok(html.includes('aria-label="Open Arun (2).jpg"'));
      assert.ok(html.includes("<button"));
    },
  ],
  [
    "citations stay plain text when there is nowhere to navigate",
    () => {
      const html = render(GROUNDED);
      assert.ok(!html.includes("<button"), "no dead buttons without a handler");
      assert.ok(html.includes("Arun (2).jpg"), "the filename is still shown");
    },
  ],
  [
    "the asked question is echoed back with the answer",
    () => {
      const html = render(GROUNDED, { question: "What medications am I taking?" });
      assert.ok(html.includes("You asked"));
      assert.ok(html.includes("What medications am I taking?"));
    },
  ],
  [
    "user text is escaped, not injected as markup",
    () => {
      const html = render(
        { ...GROUNDED, answer: "Nothing about <script>alert(1)</script> is recorded." },
        { question: "What is <script>alert(1)</script>?" }
      );
      assert.ok(!html.includes("<script>"), "script tags must be escaped");
      assert.ok(html.includes("&lt;script&gt;"));
    },
  ],
  [
    "long unbroken text is allowed to wrap rather than widen the card",
    () => {
      const html = render({ ...GROUNDED, answer: "A".repeat(400) });
      assert.ok(html.includes("break-words"), "wrapping class present");
    },
  ],
  [
    "the retrieval query is shown when the backend rewrote the question",
    () => {
      const html = render({ ...GROUNDED, rewritten_query: "paracetamol dosage August 2026" });
      assert.ok(html.includes("Records searched for"));
      assert.ok(html.includes("paracetamol dosage August 2026"));
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
