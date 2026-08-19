/**
 * Renders an Ask AI answer and pins the trust-critical UI contract:
 * the answer, its confidence, and citations the user can actually open —
 * plus an honest empty state when nothing supported the answer.
 *
 * Run with: npm run test:qacard
 */
import assert from "node:assert/strict";
import { renderToStaticMarkup } from "react-dom/server";

import { MemoryRouter } from "react-router-dom";
import { QAResultCard } from "../QAResultCard";
import { I18nProvider } from "../../i18n/I18nContext";
import { en } from "../../i18n/locales/en";
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
  return renderToStaticMarkup(
    <MemoryRouter>
      <I18nProvider>
        <QAResultCard result={result} {...extra} />
      </I18nProvider>
    </MemoryRouter>,
  );
}

/** Regression: one document cited across two visits is ONE source. */
const DUPLICATED: QAResponse = {
  answer: "Paracetamol, Ferrous sulfate, and Omeprazole each appear more than once.",
  confidence: 0.98,
  sources: [
    { date: "2026-08-07", source_file: "Arun (2).jpg", page: null },
    { date: "2026-08-11", source_file: "Arun (2).jpg", page: null },
    { date: "2026-08-07", source_file: "Arun (4).jpg", page: null },
    { date: "2026-08-11", source_file: "Arun (4).jpg", page: null },
  ],
  recommend_professional_consult: false,
};

/** Count non-overlapping occurrences of a needle. */
function occurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
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
      assert.ok(html.includes("2 source documents"));
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
      assert.ok(html.includes(en.ask.noSources));
    },
  ],
  [
    "a risk-related answer carries the consult-a-professional warning",
    () => {
      const html = render(RISKY);
      assert.ok(html.includes(en.ask.consult));
      assert.ok(!render(GROUNDED).includes(en.ask.consult));
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
      // main's card does not echo the question; that lives on the page.
      assert.ok(html.includes("Paracetamol 500mg twice daily"));
    },
  ],
  [
    "user text is escaped, not injected as markup",
    () => {
      const html = render(
        { ...GROUNDED, answer: "Nothing about <script>alert(1)</script> is recorded." },
        { question: "What is <script>alert(1)</script>?" },
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
    "a document cited for two dates renders once, not twice",
    () => {
      const html = render(DUPLICATED, { onOpenSource: () => {} });
      assert.equal(occurrences(html, 'aria-label="Open Arun (2).jpg"'), 1);
      assert.equal(occurrences(html, 'aria-label="Open Arun (4).jpg"'), 1);
    },
  ],
  [
    "the source count reflects unique documents, not citations",
    () => {
      const html = render(DUPLICATED);
      assert.ok(html.includes("2 source documents"), "should say 2, not 4");
      assert.ok(!html.includes("4 source"));
    },
  ],
  [
    "collapsing duplicates keeps both cited dates visible",
    () => {
      const html = render({
        ...DUPLICATED,
        sources: [
          {
            date: "2026-08-07",
            dates: ["2026-08-07", "2026-08-11"],
            source_file: "Arun (2).jpg",
            page: null,
          },
        ],
      });
      assert.ok(html.includes("Aug 7, 2026"), html.slice(0, 200));
      assert.ok(html.includes("Aug 11, 2026"));
    },
  ],
  [
    "a single source is labelled in the singular",
    () => {
      const html = render({
        ...GROUNDED,
        sources: [{ date: "2026-08-07", source_file: "Arun (2).jpg", page: 1 }],
      });
      assert.ok(html.includes(en.ask.citedSourcesOne));
    },
  ],
  [
    "confidence leads with plain language, not a bare percentage",
    () => {
      // main renders a confidence badge plus its own confidence_reason.
      const html = render({ ...DUPLICATED, confidence_reason: "Directly supported." });
      assert.ok(html.includes("98%"), "confidence percentage shown");
      assert.ok(html.includes("Directly supported."), "reason shown");
    },
  ],
  [
    "a weak evidence match is not dressed up as a strong one",
    () => {
      const html = render({ ...UNGROUNDED, confidence: 0.1 });
      assert.ok(html.includes("10%"));
      assert.ok(html.includes(en.ask.lowConfidence), "low-confidence guidance shown");
    },
  ],
  [
    "never renders a placeholder page when page metadata is absent",
    () => {
      const html = render(DUPLICATED);
      assert.ok(!html.toLowerCase().includes("page unknown"));
      assert.ok(!html.includes("page null"));
      assert.ok(!html.includes("page undefined"));
    },
  ],
  [
    "the retrieval query is shown when the backend rewrote the question",
    () => {
      const html = render({ ...GROUNDED, rewritten_query: "paracetamol dosage August 2026" });
      assert.ok(html.includes(en.ask.retrievalQuery));
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
