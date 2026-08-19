/**
 * End-to-end render check for the regrouped navigation.
 *
 * The source-level contract lives in navigation.test.tsx; this one actually
 * boots <App /> at each hub URL with a stubbed network and asserts what a
 * judge would see: the right page, exactly one title, the right tabs, the
 * deep-linked tab already selected, and no crash on the way.
 *
 * Run with: npm run test:navigation-render
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";

const dom = new JSDOM("<!DOCTYPE html><html><body><div id='root'></div></body></html>", {
  url: "http://localhost/",
});
(globalThis as Record<string, unknown>).window = dom.window;
(globalThis as Record<string, unknown>).document = dom.window.document;
(globalThis as Record<string, unknown>).localStorage = dom.window.localStorage;
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;
try {
  Object.defineProperty(globalThis, "navigator", {
    value: dom.window.navigator,
    configurable: true,
  });
} catch {
  // Node may expose a read-only navigator; react-dom can use that value.
}
// jsdom has no layout engine; the sidebar asks for a media query on mount.
dom.window.matchMedia =
  dom.window.matchMedia ||
  (((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  })) as unknown as typeof dom.window.matchMedia);
dom.window.scrollTo = dom.window.scrollTo || (() => {});
dom.window.print = dom.window.print || (() => {});

/* ------------------------------------------------------------------ */
/* Stubbed network: empty-but-legal payloads, so every screen reaches   */
/* its empty state instead of an error wall.                            */
/* ------------------------------------------------------------------ */

const EMPTY_TIMELINE = {
  visits: [],
  documents: [],
  medications_timeline: [],
  lab_results_timeline: [],
  conditions_timeline: [],
  allergies: [],
  known_allergies: [],
};

const EMPTY_CROSS_CHECK = {
  potential_drug_interactions: [],
  duplicate_prescriptions: [],
  conflicting_dosage_instructions: [],
  allergy_conflicts: [],
  guideline_flagged_combinations: [],
  eml_age_conflicts: [],
  openfda_recalls: [],
  medication_changes: [],
  medication_continuations: [],
  concurrent_exposure: [],
  overall_recommendation: "",
};

const EMPTY_DOSAGE = { findings: [], checked_medications: 0, note: "" };

/**
 * Exact-path payloads. Keyed on the pathname so that, for example,
 * /api/v1/risk-timeline never accidentally matches a loose /timeline/ rule.
 */
const PAYLOADS: Record<string, unknown> = {
  "/api/v1/anonymous/session": { user_id: "anon_test", token: "t" },
  "/api/v1/workspace/name": { user_id: "anon_test", name: null },
  "/api/v1/patient-snapshot": {
    user_id: "anon_test",
    patient_timeline: EMPTY_TIMELINE,
    cross_check_report: EMPTY_CROSS_CHECK,
    dosage_report: EMPTY_DOSAGE,
    lab_trends: { trends: [], insufficient_data: [], summary: {} },
    rebuilt_from_documents: false,
  },
  "/api/v1/timeline": EMPTY_TIMELINE,
  "/api/v1/documents": { documents: [] },
  "/api/v1/medications/reconciliation": { medications: [], summary: {} },
  "/api/v1/cross-check": EMPTY_CROSS_CHECK,
  "/api/v1/dosage-report": EMPTY_DOSAGE,
  // getMedicationSafety returns the cross-check report itself, with the
  // dosage report attached — not a wrapper object.
  "/api/v1/medication-safety": { ...EMPTY_CROSS_CHECK, dosage_report: EMPTY_DOSAGE },
  "/api/v1/risk-timeline": {
    calendar: [],
    concurrent_exposure: [],
    treatment_windows: [],
    timing_summary: null,
    evidence_summary: null,
  },
  "/api/v1/findings/alerts": {
    active_findings: [],
    active_count: 0,
    suppressed_findings: [],
    suppressed_count: 0,
    collapsed_duplicates: 0,
    merge_log: [],
  },
  "/api/v1/findings/lifecycle": { states: {}, findings: [], summary: null },
  "/api/v1/findings/feedback": { entries: [], feedback: [] },
  "/api/v1/findings/feedback/metrics": { total: 0, by_verdict: {} },
  "/api/v1/record-integrity": {
    status: "no_discrepancies_found",
    summary: { records_checked: 0, issues_found: 0, important_issues: 0 },
    issues: [],
    checks_performed: [],
    method: "",
    note: "",
  },
  "/api/v1/corrections": { corrections: [] },
  "/api/v1/conflicts": { conflicts: [] },
  "/api/v1/changes": {
    comparisons: [],
    periods: [],
    changes: [],
    summary: {},
    note: "",
    method: "",
  },
  "/api/v1/lab-trends": { trends: [], insufficient_data: [], summary: {} },
  "/api/v1/vital-trends": {
    trends: [],
    insufficient_data: [],
    summary: { vital_types: 0, abnormal_latest: 0 },
  },
  "/api/v1/early-warning": { score: 0, components: [], band: null, note: "" },
  "/api/v1/adherence": { signals: [], note: "" },
  "/api/v1/patient-data/measurements": { measurements: [] },
  "/api/v1/appointment-prep": {
    handoff: {
      record_count: 0,
      record_period: { from: null, to: null },
      providers_documented: [],
      known_allergies: [],
      latest_medication_record: null,
      latest_documented_medications: [],
      key_findings: [],
    },
    priorities: [],
    checklist: [],
    questions: [],
    note: "",
    method: "",
  },
  "/api/v1/follow-up": {
    tasks: [],
    summary: { total: 0, record_verification: 0 },
    note: "",
    method: "",
  },
  "/api/v1/preventive-care": { age: null, sex: null, care_gaps: [], count: 0, note: "" },
  "/api/v1/provider-messages": { threads: [], messages: [] },
  "/api/v1/consult-triage": {
    consult_needed: false,
    recommended_specialties: [],
    pharmacist_actions: [],
    doctor_actions: [],
    referral_items: [],
    summary: "",
    emergency_advice: "",
  },
  "/api/v1/care-recommendations": {
    eligible: false,
    flags: [],
    message: "",
    disclaimer: "",
  },
  "/api/v1/care/recommendations": { recommendations: [] },
  "/api/v1/care/suggestion": { suggestion: null, specialties: [] },
  "/api/v1/guidelines/status": { sources: [], checked_at: null, summary: {} },
  "/api/v1/analyses": { analyses: [] },
  "/api/v1/profile": {},
  "/api/v1/sessions": { sessions: [] },
};

(globalThis as Record<string, unknown>).fetch = async (input: unknown) => {
  const url = String(typeof input === "string" ? input : (input as { url?: string }).url || "");
  const path = url.split("?")[0].replace(/^https?:\/\/[^/]+/, "");
  const payload = PAYLOADS[path] ?? {};
  return {
    ok: true,
    status: 200,
    headers: { get: () => "application/json" },
    json: async () => payload,
    text: async () => JSON.stringify(payload),
  };
};

const { default: App } = await import("../../App");
const { AuthProvider } = await import("../../context/AuthContext");
const { I18nProvider } = await import("../../i18n/I18nContext");
const { ToastProvider } = await import("../../components/Toast");

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

interface Rendered {
  container: HTMLElement;
  unmount: () => void;
}

async function renderAt(path: string): Promise<Rendered> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter initialEntries={[path]}>
          <I18nProvider>
            <AuthProvider>
              <ToastProvider>
                <App />
              </ToastProvider>
            </AuthProvider>
          </I18nProvider>
        </MemoryRouter>
      </StrictMode>,
    );
    await new Promise((resolve) => window.setTimeout(resolve, 40));
  });
  return {
    container,
    unmount: () => {
      act(() => root.unmount());
      container.remove();
    },
  };
}

function tabsOf(container: HTMLElement) {
  return Array.from(container.querySelectorAll('[role="tab"]')).map((tab) => ({
    label: (tab.textContent || "").replace(/\s*\(selected\)\s*$/, "").trim(),
    selected: tab.getAttribute("aria-selected") === "true",
  }));
}

/* ------------------------------------------------------------------ */

interface HubCase {
  name: string;
  path: string;
  tabs: string[];
  /** Tab expected to be selected when landing on `path`. */
  selected: string;
}

const HUBS: HubCase[] = [
  {
    name: "Safety",
    path: "/safety",
    tabs: ["Alerts", "Clinical", "Over time"],
    selected: "Alerts",
  },
  {
    name: "Safety (clinical deep link)",
    path: "/safety?tab=clinical",
    tabs: ["Alerts", "Clinical", "Over time"],
    selected: "Clinical",
  },
  {
    name: "Safety (risk timeline deep link)",
    path: "/safety?tab=timeline",
    tabs: ["Alerts", "Clinical", "Over time"],
    selected: "Over time",
  },
  {
    name: "Find care",
    path: "/care",
    tabs: ["Find local care", "Who to see", "Browse nearby"],
    selected: "Find local care",
  },
  {
    name: "Find care (who to see deep link)",
    path: "/care?tab=who",
    tabs: ["Find local care", "Who to see", "Browse nearby"],
    selected: "Who to see",
  },
  {
    name: "Record check",
    path: "/record-check",
    tabs: ["Discrepancies", "Conflicts", "What changed"],
    selected: "Discrepancies",
  },
  {
    name: "Record check (changes deep link)",
    path: "/record-check?tab=changes",
    tabs: ["Discrepancies", "Conflicts", "What changed"],
    selected: "What changed",
  },
  {
    name: "Ask AI",
    path: "/ask",
    tabs: ["Ask a question", "Check a symptom", "Conversation"],
    selected: "Ask a question",
  },
  {
    name: "Ask AI (chat deep link)",
    path: "/ask?tab=chat",
    tabs: ["Ask a question", "Check a symptom", "Conversation"],
    selected: "Conversation",
  },
  {
    name: "Next steps",
    path: "/appointment-prep",
    tabs: ["Appointment prep", "Action Center", "Preventive", "Messages"],
    selected: "Appointment prep",
  },
  {
    name: "Next steps (preventive deep link)",
    path: "/appointment-prep?tab=preventive",
    tabs: ["Appointment prep", "Action Center", "Preventive", "Messages"],
    selected: "Preventive",
  },
  {
    name: "Next steps (messages deep link)",
    path: "/appointment-prep?tab=messages",
    tabs: ["Appointment prep", "Action Center", "Preventive", "Messages"],
    selected: "Messages",
  },
  {
    name: "My record",
    path: "/documents",
    tabs: ["Files", "Timeline"],
    selected: "Files",
  },
  {
    name: "Labs & vitals",
    path: "/labs?tab=vitals",
    tabs: ["Lab trends", "Home vitals"],
    selected: "Home vitals",
  },
  {
    name: "Upload",
    path: "/upload?tab=fhir",
    tabs: ["Photos & PDFs", "FHIR file"],
    selected: "FHIR file",
  },
  {
    name: "About & settings",
    path: "/about?tab=settings",
    tabs: ["How it works", "Guidelines", "Settings", "Advanced"],
    selected: "Settings",
  },
];

let passed = 0;
let total = 0;

async function check(name: string, run: () => Promise<void>) {
  total += 1;
  try {
    await run();
    passed += 1;
    console.log(`PASS ${name}`);
  } catch (error) {
    console.error(`FAIL ${name}`);
    console.error(error instanceof Error ? error.message : error);
  }
}

for (const hub of HUBS) {
  await check(`${hub.name} renders its tabs at ${hub.path}`, async () => {
    const { container, unmount } = await renderAt(hub.path);
    try {
      const tabs = tabsOf(container);
      assert(
        tabs.length === hub.tabs.length,
        `${hub.path}: expected ${hub.tabs.length} tabs, saw ${tabs.length} (${tabs
          .map((tab) => tab.label)
          .join(", ")})`,
      );
      assert(
        tabs.every((tab, index) => tab.label === hub.tabs[index]),
        `${hub.path}: tab labels were ${tabs.map((tab) => tab.label).join(", ")}`,
      );
      const selected = tabs.filter((tab) => tab.selected);
      assert(selected.length === 1, `${hub.path}: expected one selected tab`);
      assert(
        selected[0].label === hub.selected,
        `${hub.path}: expected "${hub.selected}" selected, saw "${selected[0].label}"`,
      );
      // Exactly one panel is mounted, so a hidden tab never loads its data.
      assert(
        container.querySelectorAll('[role="tabpanel"]').length <= 1,
        `${hub.path}: more than one tab panel is mounted`,
      );
    } finally {
      unmount();
    }
  });
}

await check("every hub prints exactly one page title", async () => {
  for (const hub of HUBS) {
    const { container, unmount } = await renderAt(hub.path);
    try {
      const headings = container.querySelectorAll("h1");
      assert(
        headings.length === 1,
        `${hub.path}: expected 1 <h1>, saw ${headings.length} (${Array.from(headings)
          .map((h) => h.textContent)
          .join(" | ")})`,
      );
    } finally {
      unmount();
    }
  }
});

await check("the sidebar shows eleven destinations and no merged leftovers", async () => {
  const { container, unmount } = await renderAt("/dashboard");
  try {
    const nav = container.querySelector("nav[aria-label]");
    assert(nav !== null, "sidebar nav is missing");
    const hrefs = Array.from(nav?.querySelectorAll("a") || []).map((a) => a.getAttribute("href"));
    assert(hrefs.length === 11, `expected 11 sidebar links, saw ${hrefs.length}`);
    for (const gone of [
      "/clinical-safety",
      "/risk-timeline",
      "/changes",
      "/vitals",
      "/import",
      "/who-to-see",
      "/find-care",
      "/follow-up",
      "/guidelines",
      "/analyses",
    ]) {
      assert(!hrefs.includes(gone), `${gone} should not be a sidebar link any more`);
    }
    assert(hrefs.includes("/care"), "Find Local Care must be reachable from the sidebar");
  } finally {
    unmount();
  }
});

await check("old URLs still land on the right screen", async () => {
  const cases: Array<[string, string]> = [
    ["/clinical-safety", "Clinical"],
    ["/risk-timeline", "Over time"],
    ["/who-to-see", "Who to see"],
    ["/conversations", "Conversation"],
    ["/changes", "What changed"],
    ["/follow-up", "Action Center"],
    ["/preventive-care", "Preventive"],
    ["/messages", "Messages"],
    ["/vitals", "Home vitals"],
    ["/import", "FHIR file"],
    ["/history", "Timeline"],
    ["/symptoms", "Check a symptom"],
  ];
  for (const [path, expected] of cases) {
    const { container, unmount } = await renderAt(path);
    try {
      const selected = tabsOf(container).find((tab) => tab.selected);
      assert(
        selected?.label === expected,
        `${path}: expected to land on "${expected}", landed on "${selected?.label}"`,
      );
    } finally {
      unmount();
    }
  }
});

await check("a nonsense ?tab= value falls back to the default tab", async () => {
  const { container, unmount } = await renderAt("/safety?tab=not-a-real-tab");
  try {
    const selected = tabsOf(container).find((tab) => tab.selected);
    assert(selected?.label === "Alerts", `fell back to "${selected?.label}"`);
  } finally {
    unmount();
  }
});

await check("an unknown path lands on the dashboard, not a blank page", async () => {
  const { container, unmount } = await renderAt("/nope");
  try {
    assert(container.textContent!.trim().length > 0, "unknown path rendered nothing");
  } finally {
    unmount();
  }
});

console.log(`\n${passed}/${total} tests passed`);
if (passed !== total) process.exitCode = 1;
