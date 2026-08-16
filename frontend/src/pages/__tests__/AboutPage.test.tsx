/**
 * About page: structure, accessibility, and i18n discipline.
 *
 * Run with: npm run test:about
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";

import { AboutPage } from "../AboutPage";
import { I18nProvider, missingTranslationKeys, translate } from "../../i18n/I18nContext";
import { en } from "../../i18n/locales/en";

const about = en.about;

const html = renderToStaticMarkup(
  <MemoryRouter>
    <I18nProvider>
      <AboutPage />
    </I18nProvider>
  </MemoryRouter>
);

const pageSource = readFileSync(new URL("../AboutPage.tsx", import.meta.url), "utf8");
const layoutSource = readFileSync(
  new URL("../../components/Layout.tsx", import.meta.url),
  "utf8"
);

/** React escapes text nodes; compare against the escaped form. */
function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#x27;");
}

/** Count non-overlapping occurrences. */
function occurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

const tests: Array<[string, () => void]> = [
  [
    "renders all seven required sections with stable anchors",
    () => {
      const sections: Array<[string, string]> = [
        ["overview", about.overviewTitle],
        ["features", about.featuresTitle],
        ["architecture", about.archTitle],
        ["pipeline", about.pipeTitle],
        ["data-flow", about.flowTitle],
        ["security", about.secTitle],
        ["api", about.apiTitle],
      ];
      for (const [id, title] of sections) {
        assert.ok(html.includes(`id="${id}"`), `missing section ${id}`);
        assert.ok(html.includes(escapeHtml(title)), `missing title ${title}`);
      }
    },
  ],
  [
    "has exactly one h1 and a correct heading hierarchy",
    () => {
      assert.equal(occurrences(html, "<h1"), 1, "exactly one h1");
      // Every section heading is an h2; no level is skipped.
      assert.equal(occurrences(html, "<h2"), 7, "one h2 per section");
      assert.ok(occurrences(html, "<h3") > 0, "h3 used under sections");
      assert.ok(!html.includes("<h5"), "no heading level skipped down to h5");
      assert.ok(!html.includes("<h6"), "no h6");
    },
  ],
  [
    "each section is labelled by its own heading",
    () => {
      for (const id of ["overview", "api"]) {
        assert.ok(html.includes(`aria-labelledby="${id}-heading"`));
        assert.ok(html.includes(`id="${id}-heading"`));
      }
    },
  ],
  [
    "diagrams expose an accessible name and are not image-only",
    () => {
      for (const label of [about.archDiagram, about.pipeDiagram, about.flowDiagram]) {
        assert.ok(
          html.includes(`aria-label="${escapeHtml(label)}"`),
          `missing diagram label: ${label}`
        );
      }
      // The same information exists as real text, not only inside the figure.
      assert.ok(html.includes(escapeHtml(about.l1Body)));
      assert.ok(html.includes(escapeHtml(about.s1Body)));
    },
  ],
  [
    "documents every real endpoint group and method",
    () => {
      for (const name of [
        about.apiDocuments,
        about.apiJobs,
        about.apiClinical,
        about.apiAsk,
        about.apiCare,
        about.apiWorkspace,
      ]) {
        assert.ok(html.includes(escapeHtml(name)), `missing group ${name}`);
      }
      for (const path of [
        "/api/v1/documents",
        "/api/v1/timeline",
        "/api/v1/qa",
        "/api/v1/care/facilities",
        "/api/v1/health",
      ]) {
        assert.ok(html.includes(escapeHtml(path)), `missing path ${path}`);
      }
    },
  ],
  [
    "publishes no secrets, tokens, or credential values",
    () => {
      const forbidden = [
        /gsk_[A-Za-z0-9]{10,}/,
        /AIza[A-Za-z0-9_-]{10,}/,
        /sk-[A-Za-z0-9]{10,}/,
        /eyJ[A-Za-z0-9_-]{10,}/,
        /\.supabase\.co/,
        /GOOGLE_MAPS_API_KEY\s*[:=]\s*["'][^"']+["']/,
      ];
      for (const pattern of forbidden) {
        assert.equal(pattern.exec(html), null, `secret-shaped text rendered: ${pattern}`);
      }
    },
  ],
  [
    "states the medical disclaimer and does not overclaim compliance",
    () => {
      assert.ok(html.includes(escapeHtml(about.disclaimerTitle)));
      assert.ok(/does not diagnose/i.test(html));
      // HIPAA/GDPR may only appear as an explicit disclaimer of certification.
      const lowered = html.toLowerCase();
      for (const term of ["hipaa", "gdpr"]) {
        if (lowered.includes(term)) {
          assert.ok(
            /not hipaa or gdpr certified/i.test(html),
            `${term} mentioned without the "not certified" qualifier`
          );
        }
      }
    },
  ],
  [
    "separates implemented security from planned work",
    () => {
      assert.ok(html.includes(escapeHtml(about.secImplemented)));
      assert.ok(html.includes(escapeHtml(about.secPlanned)));
      assert.ok(html.includes(escapeHtml(about.secNotClaimed)));
      // A planned item must never be rendered inside the implemented list.
      const implementedTitles: string[] = [
        about.i1Title, about.i2Title, about.i3Title,
        about.i4Title, about.i5Title, about.i6Title,
      ];
      for (const planned of [about.pl1, about.pl2, about.pl3] as string[]) {
        assert.ok(!implementedTitles.includes(planned), `"${planned}" listed as implemented`);
      }
    },
  ],
  [
    "no visible copy is hardcoded in the component",
    () => {
      // Long prose in JSX text position would bypass the i18n dictionary.
      const jsxText = pageSource.match(/>[^<>{}\n]{25,}</g) || [];
      const offenders = jsxText.filter((t) => /[a-z]{4,}\s+[a-z]{4,}\s+[a-z]{4,}/i.test(t));
      assert.deepEqual(offenders, [], `hardcoded prose found: ${offenders.join(" | ")}`);
    },
  ],
  [
    "the sidebar entry is secondary and does not join the workflow nav",
    () => {
      assert.ok(layoutSource.includes('to="/about"'), "sidebar links to /about");
      // Patient workflow items live in the NAV array; About must not be there.
      const navArray = layoutSource.slice(
        layoutSource.indexOf("const NAV:"),
        layoutSource.indexOf("export function Layout")
      );
      assert.ok(!navArray.includes("/about"), "About must not be in the workflow NAV array");
      assert.equal((navArray.match(/to: "/g) || []).length, 15, "all 15 workflow items are present");
    },
  ],
  [
    "the sidebar entry is keyboard accessible and labelled",
    () => {
      const linkBlock = layoutSource.slice(layoutSource.indexOf('to="/about"'));
      assert.ok(linkBlock.includes("focus-visible:ring"), "visible focus state");
      assert.ok(linkBlock.includes('title={t("about.nav")}'), "accessible title from i18n");
      assert.ok(linkBlock.includes("min-h-[44px]"), "44px touch target");
      // Collapses to an icon on main's desktop rail, like the other items.
      assert.ok(linkBlock.includes('collapsed && "lg:hidden"'), "label hides when collapsed");
    },
  ],
  [
    "every About string exists in Sinhala and Tamil",
    () => {
      for (const language of ["si", "ta"] as const) {
        const missing = missingTranslationKeys(language).filter((k) => k.startsWith("about."));
        assert.deepEqual(missing, [], `${language} missing: ${missing.join(", ")}`);
        // Spot-check that the value is a real translation, not an echo.
        assert.notEqual(
          translate(language, "about.title"),
          translate("en", "about.title"),
          `${language} about.title is untranslated`
        );
      }
    },
  ],
  [
    "long API paths can wrap rather than overflow on mobile",
    () => {
      assert.ok(html.includes("break-all"), "paths wrap");
      assert.ok(pageSource.includes("min-w-0"), "grid child can shrink below content width");
      assert.ok(!html.includes("overflow-x-scroll"), "no forced horizontal scrolling");
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
