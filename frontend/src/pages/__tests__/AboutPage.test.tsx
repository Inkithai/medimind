/**
 * About page: structure, accessibility, in-app navigation, and i18n discipline.
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
        ["how-it-works", about.howTitle],
        ["safety-intelligence", about.safetyIntelligenceTitle],
        ["security", about.secTitle],
        ["interoperability", about.interoperabilityTitle],
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
    "uses a sticky horizontal section bar, not a side contents column",
    () => {
      // Desktop bar: labelled nav with one in-page anchor per section.
      assert.ok(
        html.includes(`aria-label="${escapeHtml(about.sectionNav)}"`),
        "section nav has an accessible name"
      );
      for (const id of ["overview", "features", "how-it-works", "safety-intelligence", "security", "interoperability", "api"]) {
        assert.ok(html.includes(`href="#${id}"`), `missing section anchor #${id}`);
      }
      assert.ok(pageSource.includes("sticky top-0"), "the section bar is sticky");
      // The old left-hand contents column is gone.
      assert.ok(
        !pageSource.includes("lg:grid-cols-[15rem"),
        "no secondary side contents column"
      );
      // Mobile gets an "On this page" select instead of the bar.
      assert.ok(html.includes(escapeHtml(about.onThisPage)), "mobile dropdown labelled");
      assert.ok(html.includes("<select"), "mobile section control is a select");
    },
  ],
  [
    "in-app navigation only: no Back to dashboard, no account actions",
    () => {
      assert.ok(!html.includes('href="/dashboard"'), "no dashboard link");
      assert.ok(
        !html.includes(escapeHtml("Back to dashboard")),
        "back-to-dashboard copy removed"
      );
      const lowered = html.toLowerCase();
      for (const banned of ["sign in", "log in", "create account", "register", "start free trial"]) {
        assert.ok(!lowered.includes(banned), `account-pattern text present: ${banned}`);
      }
      // The anonymous-workspace trust statement is present instead.
      assert.ok(html.includes(escapeHtml(about.fact1)), "no-account fact chip present");
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
    "how it works defaults to five steps with technical detail collapsed",
    () => {
      for (const key of [about.hw1Title, about.hw2Title, about.hw3Title, about.hw4Title, about.hw5Title]) {
        assert.ok(html.includes(escapeHtml(key)), `missing step ${key}`);
      }
      // The deep dives render inside collapsed <details> blocks…
      assert.ok(occurrences(html, "<details") >= 7, "technical details are collapsible");
      // …and none of them is open by default.
      assert.ok(!html.includes("<details open"), "all details collapse by default");
      for (const label of [about.techDocs, about.techData, about.techRet, about.techAns]) {
        assert.ok(html.includes(escapeHtml(label)), `missing expandable ${label}`);
      }
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
      // Each collapsed group shows its endpoint count.
      assert.ok(
        html.includes(escapeHtml(translate("en", "about.apiEndpoints", { count: 3 }))),
        "endpoint counts rendered"
      );
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
      // The safety section carries its own prominent boundary statement.
      assert.ok(html.includes(escapeHtml(about.safetyBoundary)), "safety boundary visible");
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
    "safety principles render at full contrast",
    () => {
      // The six lanes sit on light cards with dark text (the old slate-900
      // panel washed the copy out); the boundary note is doubled-bordered.
      for (const key of [about.sl1Title, about.sl6Title]) {
        assert.ok(html.includes(escapeHtml(key)), `missing safety lane ${key}`);
      }
      const lane = html.slice(html.indexOf(escapeHtml(about.sl1Title)) - 400);
      assert.ok(lane.includes("bg-slate-50"), "safety cards use a light surface");
      assert.ok(lane.includes("text-slate-700"), "safety body text is dark on light");
      assert.ok(html.includes("border-amber-300"), "boundary note is visually prominent");
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
      // The workspace-limitation list covers browser-data loss and
      // cross-browser access — requirements for the anonymous model.
      assert.ok(html.includes(escapeHtml(about.n5)), "browser-key limitation documented");
    },
  ],
  [
    "no visible copy is hardcoded in the component",
    () => {
      // Long prose in JSX text position would bypass the i18n dictionary.
      const jsxText = pageSource.match(/>[^<>\{\}\n]{25,}</g) || [];
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
      assert.equal((navArray.match(/to: "/g) || []).length, 21, "all 21 workflow items are present");
      // The tagline is the only content the sidebar redesign removes.
      assert.ok(
        !layoutSource.includes('t("common.tagline")'),
        "sidebar header no longer renders the tagline"
      );
    },
  ],
  [
    "the sidebar entry is keyboard accessible and labelled",
    () => {
      const linkBlock = layoutSource.slice(layoutSource.indexOf('to="/about"'));
      assert.ok(linkBlock.includes("focus-visible:ring"), "visible focus state");
      assert.ok(linkBlock.includes('aria-label={collapsed ? t("about.nav")'), "accessible label from i18n");
      assert.ok(linkBlock.includes('t("nav.descriptions.about")'), "collapsed tooltip explains the destination");
      assert.ok(linkBlock.includes("min-h-[44px]"), "44px touch target");
      // Collapses to an icon on main's desktop rail, like the other items.
      assert.ok(linkBlock.includes('collapsed && "lg:hidden"'), "label hides when collapsed");
    },
  ],
  [
    "the sidebar uses the pale-teal active treatment shared by all rows",
    () => {
      // Selection is signalled by background + weight/color + edge marker,
      // never by color alone (the old gray About style is gone).
      const activeClass = "bg-[#eaf6f4]";
      assert.ok(
        occurrences(layoutSource, activeClass) >= 2,
        "nav rows and About row share the active treatment"
      );
      assert.ok(layoutSource.includes("shadow-[inset_3px_0_0_#0F766E]"), "teal edge marker");
      // Destructive deletion no longer sits beside New workspace in the
      // sidebar; it lives behind the explicit confirmation flow in Settings.
      assert.ok(!layoutSource.includes('t("nav.resetData")'), "no casual destructive sidebar action");
      assert.ok(layoutSource.includes("Permanent deletion is available in Settings"), "points to safe deletion flow");
    },
  ],
  [
    "the sidebar can always be expanded again after collapsing",
    () => {
      // Regression: the collapse toggle once gained `collapsed && "lg:hidden"`,
      // so a persisted collapse removed the ONLY expand control — the rail
      // could never be opened again. The toggle must stay mounted in every
      // state; only the logo/name block may hide.
      const toggleBlock = layoutSource.slice(
        layoutSource.indexOf("setCollapsed((value) => !value)") - 200,
        layoutSource.indexOf("setCollapsed((value) => !value)") + 700
      );
      assert.ok(toggleBlock.includes("nav.expandSidebar"), "toggle carries the expand label");
      assert.ok(
        !toggleBlock.includes("lg:hidden"),
        "the expand/collapse toggle must never hide when collapsed"
      );
      const brandBlock = layoutSource.slice(layoutSource.indexOf("<Logo />") - 200, layoutSource.indexOf("<Logo />") + 300);
      assert.ok(
        brandBlock.includes('collapsed && "lg:hidden"'),
        "the logo/name block hides on the collapsed rail instead"
      );
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
        // The safety section must not ship English copy in si/ta.
        assert.notEqual(
          translate(language, "about.safetyIntelligenceTitle"),
          translate("en", "about.safetyIntelligenceTitle"),
          `${language} safety title is untranslated`
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
