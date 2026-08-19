/**
 * Judge Q&A prep page: hidden route, scannable structure, honest copy.
 *
 * Run with: npm run test:judge-prep
 */
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import { JudgePrepPage } from "../JudgePrepPage";
import { PREP_CATEGORIES, PREP_ITEMS } from "../judgePrepData";

const dom = new JSDOM("<!DOCTYPE html><html><body><div id='root'></div></body></html>", {
  url: "http://localhost/ygc-prep",
});
(globalThis as Record<string, unknown>).window = dom.window;
(globalThis as Record<string, unknown>).document = dom.window.document;
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node may already expose navigator.
}

const appSource = readFileSync(new URL("../../App.tsx", import.meta.url), "utf8");
const layoutSource = readFileSync(new URL("../../components/Layout.tsx", import.meta.url), "utf8");
const landingSource = readFileSync(new URL("../LandingPage.tsx", import.meta.url), "utf8");

function mount(): { container: HTMLElement; root: Root } {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  act(() => {
    root.render(
      <MemoryRouter>
        <JudgePrepPage />
      </MemoryRouter>,
    );
  });
  return { container, root };
}

function unmount(root: Root, container: HTMLElement) {
  act(() => root.unmount());
  container.remove();
}

const tests: Array<[string, () => void]> = [
  [
    "is registered as a top-level /ygc-prep route outside Layout",
    () => {
      assert.match(appSource, /path="\/ygc-prep"/);
      assert.match(appSource, /element=\{<JudgePrepPage \/>\}/);
      const beforeLayout = appSource.slice(0, appSource.indexOf("<Route element={<Layout />}"));
      assert.match(beforeLayout, /path="\/ygc-prep"/, "route must sit outside the Layout wrapper");
    },
  ],
  [
    "is not linked from the sidebar, landing page, or workflow NAV",
    () => {
      assert.doesNotMatch(layoutSource, /ygc-prep/);
      assert.doesNotMatch(landingSource, /ygc-prep/);
      const navArray = layoutSource.slice(
        layoutSource.indexOf("const NAV:"),
        layoutSource.indexOf("export function Layout"),
      );
      assert.doesNotMatch(navArray, /ygc-prep/);
      assert.doesNotMatch(navArray, /JudgePrep/);
    },
  ],
  [
    "renders the speaker-notes banner, title, and category chips",
    () => {
      const { container, root } = mount();
      const html = container.innerHTML;
      assert.match(html, /Hidden route/);
      assert.match(html, /\/ygc-prep/);
      assert.match(html, /Judge Q&amp;A prep/);
      assert.equal(container.querySelectorAll("h1").length, 1);
      for (const group of PREP_CATEGORIES) {
        assert.ok(html.includes(group.label), `missing category ${group.label}`);
      }
      unmount(root, container);
    },
  ],
  [
    "lists every prepared question collapsed by default",
    () => {
      const { container, root } = mount();
      const html = container.innerHTML;
      assert.match(html, new RegExp(`${PREP_ITEMS.length} / ${PREP_ITEMS.length} questions`));
      for (const item of PREP_ITEMS) {
        assert.ok(html.includes(item.q), `missing question ${item.id}`);
      }
      assert.equal(
        container.querySelectorAll('button[aria-expanded="true"]').length,
        0,
        "answers stay collapsed",
      );
      assert.ok(!html.includes("tracking-wider text-teal-300"), "spoken-line chip stays hidden");
      unmount(root, container);
    },
  ],
  [
    "expanding a question reveals the spoken line and backup answer",
    () => {
      const { container, root } = mount();
      const first = PREP_ITEMS[0];
      const button = Array.from(container.querySelectorAll("button")).find((el) =>
        el.textContent?.includes(first.q),
      );
      assert.ok(button, "question button exists");
      act(() => {
        button!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
      });
      assert.ok(container.innerHTML.includes(first.say), "spoken line shown");
      assert.ok(container.innerHTML.includes(first.answer.slice(0, 40)), "backup answer shown");
      unmount(root, container);
    },
  ],
  [
    "category chips and search data filter without inventing extras",
    () => {
      const needle = "hipaa";
      const matches = PREP_ITEMS.filter(
        (item) =>
          item.q.toLowerCase().includes(needle) ||
          item.say.toLowerCase().includes(needle) ||
          item.answer.toLowerCase().includes(needle),
      );
      assert.ok(
        matches.some((item) => item.id === "v3"),
        "HIPAA question exists",
      );
      assert.ok(
        matches.every(
          (item) =>
            item.q.toLowerCase().includes(needle) ||
            item.say.toLowerCase().includes(needle) ||
            item.answer.toLowerCase().includes(needle),
        ),
      );
      assert.ok(
        !matches.some((item) => item.id === "p1"),
        "unrelated product cards are not in the HIPAA set",
      );

      const { container, root } = mount();
      assert.ok(container.querySelector("input"), "search field present");
      const privacy = Array.from(container.querySelectorAll("button")).find((el) =>
        el.textContent?.startsWith("Privacy"),
      );
      assert.ok(privacy, "privacy category chip exists");
      act(() => {
        privacy!.dispatchEvent(new dom.window.MouseEvent("click", { bubbles: true }));
      });
      const privacyItems = PREP_ITEMS.filter((item) => item.category === "privacy");
      assert.match(
        container.innerHTML,
        new RegExp(`${privacyItems.length} / ${PREP_ITEMS.length} questions`),
      );
      for (const item of privacyItems) {
        assert.ok(container.innerHTML.includes(item.q), `privacy card ${item.id} stays visible`);
      }
      assert.ok(
        !container.innerHTML.includes("What is MediMind, in one sentence?"),
        "other categories hide when a chip is selected",
      );
      unmount(root, container);
    },
  ],
  [
    "marks hard questions and refuses diagnosis / fake-clinic claims",
    () => {
      const hard = PREP_ITEMS.filter((item) => item.hard);
      assert.ok(hard.length >= 6, "includes challenging judge questions");
      const diagnosis = PREP_ITEMS.find((item) => item.id === "c1");
      assert.ok(diagnosis);
      assert.match(diagnosis!.say, /No\. We flag/i);
      const fake = PREP_ITEMS.find((item) => item.id === "k3");
      assert.ok(fake);
      assert.match(fake!.say, /No fake doctors/i);
      const { container, root } = mount();
      assert.match(container.innerHTML, />Hard</);
      unmount(root, container);
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
