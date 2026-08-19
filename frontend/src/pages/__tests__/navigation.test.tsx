/**
 * Navigation contract tests.
 *
 * The information architecture makes one promise: the sidebar shrank from
 * nineteen rows to ten, but the app did not lose a single capability.
 * Every merged screen is a tab, every old path still resolves, and the two
 * pages that are meant to be private stay unlisted.
 *
 * These are source-level assertions on purpose. A rendered smoke test would
 * not catch the regression that actually hurts — someone quietly dropping a
 * redirect while tidying the route table, so a URL on a slide 404s on stage.
 *
 * Run with: npm run test:navigation
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import assert from "node:assert/strict";

const here = dirname(fileURLToPath(import.meta.url));
const read = (relative: string) => readFileSync(resolve(here, relative), "utf8");

const appSource = read("../../App.tsx");
const layoutSource = read("../../components/Layout.tsx");
const tabBarSource = read("../../components/TabBar.tsx");

const navArray = layoutSource.slice(
  layoutSource.indexOf("const NAV:"),
  layoutSource.indexOf("const NAV_GROUPS"),
);

/** Every `<Route path="X" element={<Navigate to="Y" ... />} />` in App.tsx. */
function redirects(): Map<string, string> {
  const found = new Map<string, string>();
  const pattern = /path="([^"]+)"\s+element=\{<Navigate\s+to="([^"]+)"/g;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(appSource)) !== null) found.set(match[1], match[2]);
  // Multi-line formatting puts the element on its own line.
  const multiline = /path="([^"]+)"\s*\n\s*element=\{<Navigate to="([^"]+)"/g;
  while ((match = multiline.exec(appSource)) !== null) found.set(match[1], match[2]);
  return found;
}

const REDIRECTS = redirects();

function routeExists(path: string): boolean {
  return appSource.includes(`path="${path}"`);
}

const tests: Array<[string, () => void]> = [
  [
    "the sidebar lists exactly ten destinations, plus the Upload button",
    () => {
      const entries = navArray.match(/to: "([^"]+)"/g) || [];
      assert.equal(entries.length, 10, `expected 10 sidebar entries, found ${entries.length}`);
      const expected = [
        "/dashboard",
        "/documents",
        "/medicines",
        "/labs",
        "/safety",
        "/record-check",
        "/ask",
        "/care",
        "/appointment-prep",
        "/about",
      ];
      assert.deepEqual(
        entries.map((entry) => entry.slice('to: "'.length, -1)),
        expected,
        "sidebar order tells the story: put records in → read them → check → ask → act → trust",
      );
    },
  ],

  [
    "browse nearby is the default Find care tab, and the scored flow keeps its own tab",
    () => {
      // /care is a sidebar destination; the map directory leads because it
      // works with or without a safety flag, and the flag → specialty → live
      // listing flow stays one tab over instead of unreachable.
      assert.ok(navArray.includes('to: "/care"'), "/care is a sidebar destination");
      const hub = read("../GetCareHubPage.tsx");
      const firstTab = hub.slice(hub.indexOf("const tabs")).match(/id: "([^"]+)"/);
      assert.equal(firstTab?.[1], "map", "Browse nearby is the first (default) tab");
      assert.ok(
        hub.includes("<CareRecommendationsPage embedded />"),
        "the flag → specialty → live listing flow is still a tab of the hub",
      );
      assert.ok(routeExists("/care"), "/care still resolves");
      assert.ok(routeExists("/find-care"), "/find-care still resolves");
    },
  ],

  [
    "what changed is the default Record check tab",
    () => {
      const hub = read("../RecordCheckHubPage.tsx");
      const firstTab = hub.slice(hub.indexOf("const tabs")).match(/id: "([^"]+)"/);
      assert.equal(firstTab?.[1], "changes", "What changed is the first (default) tab");
    },
  ],

  [
    "/record-integrity is a redirect, not a second door to the Record check screen",
    () => {
      assert.ok(
        appSource.includes('path="/record-integrity" element={<RecordIntegrityRedirect />}'),
        "/record-integrity must redirect onto /record-check",
      );
      assert.ok(
        appSource.includes('params.get("tab") === "conflicts"'),
        "the old ?tab=conflicts contract is preserved by the redirect",
      );
    },
  ],

  [
    "every merged screen keeps a working URL that lands on its tab",
    () => {
      const expected: Record<string, string> = {
        // Safety told three times → one page, three tabs.
        "/clinical-safety": "/safety?tab=clinical",
        "/risk-timeline": "/safety?tab=timeline",
        "/cross-check": "/safety",
        // Getting a clinician told three times → one page, three tabs.
        "/who-to-see": "/care?tab=who",
        "/location-picker": "/care?tab=map",
        // Asking AI told twice → one page, three tabs.
        "/conversations": "/ask?tab=chat",
        "/sessions": "/ask?tab=chat",
        "/symptoms": "/ask?tab=symptoms",
        "/qa": "/ask",
        // Record quality told twice → one page, three tabs.
        "/changes": "/record-check?tab=changes",
        "/review": "/record-check?tab=conflicts",
        // "What do I do next" told twice, plus the two restored features.
        "/follow-up": "/appointment-prep?tab=queue",
        "/preventive-care": "/appointment-prep?tab=preventive",
        "/messages": "/appointment-prep?tab=messages",
        // Built, but not a patient job in the sidebar.
        "/import": "/upload?tab=fhir",
        "/vitals": "/labs?tab=vitals",
        "/lab-trends": "/labs",
        "/history": "/documents?tab=timeline",
        "/timeline": "/documents?tab=timeline",
      };
      for (const [from, to] of Object.entries(expected)) {
        assert.equal(REDIRECTS.get(from), to, `${from} must redirect to ${to}`);
      }
    },
  ],

  [
    "no capability was deleted — every merged screen is still mounted somewhere",
    () => {
      // If a page component stops being referenced by App.tsx or a hub, the
      // feature is gone no matter what the sidebar says.
      const hubSources = [
        "GetCareHubPage",
        "SafetyHubPage",
        "RecordsHubPage",
        "LabsHubPage",
        "RecordCheckHubPage",
        "NextStepsHubPage",
        "UploadHubPage",
        "TrustHubPage",
      ]
        .map((name) => read(`../${name}.tsx`))
        .join("\n");
      const all = appSource + hubSources + read("../QAPage.tsx");
      const mustRender = [
        "CrossCheckPage",
        "ClinicalSafetyPage",
        "RiskTimelinePage",
        "RecordIntegrityPage",
        "ChangesPage",
        "DocumentsPage",
        "HistoryPage",
        "LabTrendsPage",
        "VitalsPage",
        "FhirImportPage",
        "UploadPage",
        "CareRecommendationsPage",
        "WhoToSeePage",
        "FindCarePage",
        "AppointmentPrepPage",
        "FollowUpPage",
        "PreventiveCarePage",
        "ProviderMessagesPage",
        "SessionPage",
        "QAPage",
        "GuidelinesPage",
        "SettingsPage",
        "AboutPage",
        "AnalysesPage",
        "MedicinesPage",
        "DashboardPage",
        "JudgePrepPage",
      ];
      for (const page of mustRender) {
        assert.ok(all.includes(`<${page}`), `${page} is no longer rendered anywhere`);
      }
    },
  ],

  [
    "preventive care and provider messages are real screens again",
    () => {
      // Both had backend endpoints and product copy while their routes
      // redirected away, which made shipped features look deleted.
      assert.notEqual(
        REDIRECTS.get("/preventive-care"),
        "/dashboard",
        "preventive care must not dead-end on the dashboard",
      );
      assert.notEqual(
        REDIRECTS.get("/messages"),
        "/dashboard",
        "provider messages must not dead-end on the dashboard",
      );
      const nextSteps = read("../NextStepsHubPage.tsx");
      assert.ok(nextSteps.includes("<PreventiveCarePage embedded />"), "preventive tab exists");
      assert.ok(nextSteps.includes("<ProviderMessagesPage embedded />"), "messages tab exists");
      assert.ok(
        read("../PreventiveCarePage.tsx").includes("/api/v1/preventive-care") ||
          read("../PreventiveCarePage.tsx").includes("getPreventiveCare"),
        "preventive screen calls the real endpoint",
      );
      assert.ok(
        read("../ProviderMessagesPage.tsx").includes("sendProviderMessage"),
        "messages screen calls the real endpoint",
      );
    },
  ],

  [
    "the audit log and the speaker sheet stay reachable but unlisted",
    () => {
      assert.ok(routeExists("/analyses"), "/analyses still resolves for a judge who asks");
      assert.ok(routeExists("/ygc-prep"), "/ygc-prep still resolves");
      assert.ok(!navArray.includes("/analyses"), "the audit log is not a sidebar item");
      assert.ok(!navArray.includes("/ygc-prep"), "the speaker sheet is not a sidebar item");
      assert.ok(
        read("../TrustHubPage.tsx").includes("<AnalysesPage embedded />"),
        "the audit log is reachable from About → Advanced",
      );
    },
  ],

  [
    "an unknown path still lands on the dashboard rather than a blank screen",
    () => {
      assert.ok(
        appSource.includes('path="*" element={<Navigate to="/dashboard" replace />}'),
        "a typo mid-demo must not blank the screen",
      );
    },
  ],

  [
    "the default tab is the absence of the parameter, so hub URLs stay clean",
    () => {
      assert.ok(
        tabBarSource.includes("if (next === fallback) params.delete(param);"),
        "selecting the first tab removes ?tab= instead of writing it",
      );
      assert.ok(
        tabBarSource.includes("const params = new URLSearchParams(searchParams);"),
        "other query parameters survive a tab change",
      );
    },
  ],

  [
    "an unknown ?tab= value falls back instead of rendering nothing",
    () => {
      assert.ok(
        tabBarSource.includes(
          "const active = tabs.some((tab) => tab.id === requested) ? (requested as string) : fallback;",
        ),
        "a misspelled tab must not blank the page",
      );
    },
  ],

  [
    "tabs follow the WAI-ARIA tabs pattern",
    () => {
      for (const attribute of [
        'role="tablist"',
        'role="tab"',
        'role="tabpanel"',
        "aria-selected={selected}",
        "aria-controls={selected ? panelId(group, tab.id) : undefined}",
        "aria-labelledby={tabId(group, id)}",
        "tabIndex={selected ? 0 : -1}",
      ]) {
        assert.ok(tabBarSource.includes(attribute), `tab chrome is missing ${attribute}`);
      }
      for (const key of ["ArrowRight", "ArrowLeft", "Home", "End"]) {
        assert.ok(tabBarSource.includes(`case "${key}"`), `keyboard support missing for ${key}`);
      }
    },
  ],

  [
    "a hidden tab never fires its data request",
    () => {
      // Opening Safety must not also download the Leaflet map bundle or hit
      // the provider directory; only the active panel is mounted.
      assert.ok(
        tabBarSource.includes("if (id !== active) return null;"),
        "inactive panels must not mount",
      );
      assert.ok(
        read("../GetCareHubPage.tsx").includes("lazy(() =>"),
        "the map bundle stays lazily loaded",
      );
    },
  ],

  [
    "hub pages do not print two page titles",
    () => {
      // Each hub prints one <h1>; the screens inside drop theirs via the
      // shared `embedded` prop.
      const embeddedPages = [
        "CrossCheckPage",
        "ClinicalSafetyPage",
        "RiskTimelinePage",
        "DocumentsPage",
        "HistoryPage",
        "LabTrendsPage",
        "VitalsPage",
        "ChangesPage",
        "RecordIntegrityPage",
        "AppointmentPrepPage",
        "FollowUpPage",
        "PreventiveCarePage",
        "ProviderMessagesPage",
        "WhoToSeePage",
        "CareRecommendationsPage",
        "FindCarePage",
        "SessionPage",
        "GuidelinesPage",
        "SettingsPage",
        "FhirImportPage",
        "UploadPage",
        "AnalysesPage",
      ];
      for (const page of embeddedPages) {
        const source = read(`../${page}.tsx`);
        assert.ok(
          source.includes("EmbeddedPageProps"),
          `${page} must accept the embedded prop so a hub can host it`,
        );
        assert.ok(source.includes("embedded"), `${page} must react to the embedded prop`);
      }
    },
  ],

  [
    "Upload is the green button, not a duplicate nav row",
    () => {
      assert.ok(
        !navArray.includes('to: "/upload"'),
        "Upload must not appear both as the CTA button and as a nav row",
      );
      const cta = layoutSource.slice(layoutSource.indexOf("{isConfigured && ("));
      assert.ok(cta.includes('to="/upload"'), "the prominent Upload button is still rendered");
      assert.ok(cta.includes("bg-brand-600"), "Upload keeps its primary-button treatment");
    },
  ],

  [
    "About MediMind is named in the sidebar and Settings stays one click away",
    () => {
      // The transparency page is the one judges hunt for, so it keeps its
      // own name in the nav rather than sitting behind a gear icon.
      assert.ok(navArray.includes('labelKey: "about.nav"'), "About row is named About MediMind");
      assert.ok(navArray.includes("icon: InfoIcon"), "About row uses the info icon");
      // Settings is a utility rather than one of the ten jobs, so it
      // lives in the footer strip — still one click, still an active state.
      const footer = layoutSource.slice(layoutSource.indexOf("border-t border-[#e5ebe9]"));
      assert.ok(footer.includes('to="/settings"'), "Settings is reachable from the sidebar footer");
      assert.ok(footer.includes("min-h-[44px]"), "the Settings row keeps a 44px touch target");
      assert.ok(
        !navArray.includes('to: "/settings"'),
        "Settings is not counted among the workflow destinations",
      );
      // ...and it is still a tab inside About, so nothing is lost either way.
      assert.ok(
        read("../TrustHubPage.tsx").includes("<SettingsPage embedded />"),
        "Settings is also a tab inside About",
      );
    },
  ],

  [
    "the mobile bar and route announcer point at the new parents",
    () => {
      const announcer = read("../../components/RouteAnnouncer.tsx");
      for (const path of ["/record-check", "/care", "/appointment-prep", "/about"]) {
        assert.ok(announcer.includes(`"${path}"`), `${path} has no announced title`);
      }
      const mobile = layoutSource.slice(layoutSource.indexOf("Mobile primary navigation"));
      for (const dead of ['to: "/settings"', 'to: "/history"']) {
        assert.ok(!mobile.includes(dead), `mobile bar still points at ${dead}`);
      }
    },
  ],
];

let passed = 0;
for (const [name, run] of tests) {
  try {
    run();
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    console.error(error);
  }
}

console.log(`\n${passed}/${tests.length} tests passed`);
if (passed !== tests.length) process.exitCode = 1;
