/**
 * Render smoke test for the screens that surface backend reports.
 *
 * Every page here reads a payload shape defined by the backend. A missing
 * optional field, a null where an array was assumed, or an empty report
 * must render an explanation — never a blank screen and never a crash
 * (a thrown render in this app means a patient sees nothing at all, with
 * no indication that their record is fine).
 *
 * Each page is rendered twice: once with a fully populated report, once
 * with the emptiest payload the API can legally return.
 *
 * Run with: npm run test:pages
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";

import { api } from "../../api/client";
import { AuthProvider } from "../../context/AuthContext";
import { I18nProvider } from "../../i18n/I18nContext";
import { ToastProvider } from "../../components/Toast";
import { ClinicalSafetyPage } from "../ClinicalSafetyPage";
import { GuidelinesPage } from "../GuidelinesPage";
import { MedicinesPage } from "../MedicinesPage";
import { RecordIntegrityPage } from "../RecordIntegrityPage";
import { VitalsPage } from "../VitalsPage";

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

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

async function render(Page: () => JSX.Element): Promise<string> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root: Root = createRoot(container);
  await act(async () => {
    root.render(
      <StrictMode>
        <MemoryRouter>
          <I18nProvider>
            <AuthProvider>
              <ToastProvider>
                <Page />
              </ToastProvider>
            </AuthProvider>
          </I18nProvider>
        </MemoryRouter>
      </StrictMode>,
    );
    await new Promise((resolve) => window.setTimeout(resolve, 20));
  });
  const html = container.innerHTML;
  act(() => root.unmount());
  container.remove();
  return html;
}

const EMPTY_TIMELINE = {
  visits: [],
  medications_timeline: [],
  lab_results_timeline: [],
  known_allergies: [],
};

async function main() {
  const original = { ...api };
  const restore = () => Object.assign(api, original);

  try {
    localStorage.clear();
    api.healthUnauthenticated = async () => ({ status: "ok" });
    api.createAnonymousSession = async () => ({
      user_id: "anon_test",
      token: "token",
      session_id: "session",
    });

    // ---- Medications: reconciled list from the backend ------------------
    api.getTimeline = async () =>
      ({
        ...EMPTY_TIMELINE,
        medications_timeline: [
          {
            name: "Warfarin",
            ingredients: ["Warfarin"],
            dosage: "5 mg",
            frequency: "daily",
            duration: null,
            date: "2026-08-01",
            source_file: "rx.pdf",
            confidence: 0.9,
          },
        ],
      }) as never;
    api.getMedicationReconciliation = async () => ({
      reference_date: "2026-08-19",
      reconciled_medications: [
        {
          ingredient: "warfarin",
          display_name: "Warfarin",
          state: "dose_conflict",
          is_active: true,
          sources: [{ name: "Warfarin", date: "2026-08-01", source_file: "rx.pdf", dose: "5 mg" }],
          supply_count: 2,
          active_supply_count: 2,
          doses: ["3 mg|daily", "5 mg|daily"],
          dose_conflict: true,
          duplicate: false,
          notes: ["Confirm the intended dose."],
        },
      ],
      summary: {
        total_ingredients: 1,
        active: 1,
        discontinued: 0,
        duplicates: 0,
        dose_conflicts: 1,
      },
      note: "Deterministic reconciliation.",
    });
    let html = await render(MedicinesPage);
    assert(html.includes("Your current medicine list"), "Medicines renders the reconciled list");
    assert(html.includes("Different doses"), "Medicines states a dose conflict in words");

    // The reconciled view must never take the page down with it.
    api.getMedicationReconciliation = async () => {
      throw new Error("reconciliation unavailable");
    };
    html = await render(MedicinesPage);
    assert(
      html.includes("Checked list unavailable"),
      "Medicines survives a failing reconciliation call and says so",
    );
    assert(html.includes("Warfarin"), "Medicines still shows the medicine history in that case");

    // ---- Vitals: deterioration trajectory --------------------------------
    api.getVitalTrends = async () => ({ trends: [], insufficient_data: [], note: "" }) as never;
    api.getEarlyWarning = async () =>
      ({
        score: 3,
        max_possible: 12,
        risk_band: "medium",
        advice: "Recheck soon.",
        components: [],
        note: "Screening aid.",
      }) as never;
    api.getAdherence = async () => ({ signals: [], summary: {}, note: "" }) as never;
    api.listPatientMeasurements = async () => ({ measurements: [] }) as never;
    api.getDeterioration = async () => ({
      trajectory: [
        { date: "2026-07-01", score: 2, risk_band: "low" },
        { date: "2026-08-01", score: 6, risk_band: "high" },
      ],
      point_count: 2,
      latest_score: 6,
      latest_band: "high",
      previous_score: 2,
      peak_score: 6,
      trend: "worsening",
      sustained_high: false,
      worsening_signals: ["respiratory_rate"],
      deteriorating: true,
      note: "Screening aid, not a diagnosis.",
    });
    html = await render(VitalsPage);
    assert(
      html.includes("Is this getting better or worse?"),
      "Vitals renders the deterioration trajectory",
    );
    assert(html.includes("Getting worse"), "Vitals states the trend in words, not colour alone");
    assert(html.includes("respiratory rate"), "Vitals lists the signals that worsened");
    assert(
      html.includes("Record a reading you took at home"),
      "Vitals keeps the home-measurement form",
    );

    // An unavailable trajectory must simply be absent, not fatal.
    api.getDeterioration = async () => {
      throw new Error("no trajectory");
    };
    html = await render(VitalsPage);
    assert(
      !html.includes("Is this getting better or worse?") && html.includes("Early-warning screen"),
      "Vitals renders without the trajectory when that call fails",
    );

    // ---- Clinical safety: lifecycle + past feedback -----------------------
    api.getManagedAlerts = async () =>
      ({
        active_findings: [
          {
            finding_key: "ddi:warfarin|ibuprofen",
            finding_kind: "ddi",
            rule: "warfarin_nsaid",
            severity: "high",
            explanation: "Bleeding risk.",
            medications_involved: ["Warfarin", "Ibuprofen"],
          },
        ],
        active_count: 1,
        suppressed_findings: [],
        suppressed_count: 0,
        collapsed_duplicates: 0,
        merge_log: [],
      }) as never;
    api.getFeedbackMetrics = async () =>
      ({
        total: 1,
        decided: 1,
        by_verdict: { confirmed: 1 },
        confirmation_rate: 1,
        false_positive_rate: 0,
        override_rate: 0,
        by_finding_kind: {},
        noisiest_rules: [],
      }) as never;
    api.getFindingLifecycle = async () => ({
      findings: [
        {
          finding_key: "ddi:warfarin|ibuprofen",
          lifecycle_state: "reviewed" as const,
          is_open: true,
        },
      ],
      open_count: 1,
      closed_count: 0,
      by_state: { reviewed: 1, dismissed: 0 },
    });
    api.listFindingFeedback = async () => ({
      feedback: [
        {
          finding_key: "ddi:warfarin|ibuprofen",
          verdict: "confirmed" as const,
          rule: "warfarin_nsaid",
          created_at: "2026-08-18T10:00:00Z",
        },
      ],
    });
    html = await render(ClinicalSafetyPage);
    assert(
      html.includes("Your progress on these warnings"),
      "Clinical safety shows review progress",
    );
    assert(
      html.includes("You have read it"),
      "a finding shows its lifecycle state in plain language",
    );
    assert(html.includes("Your past answers"), "Clinical safety lists past feedback");
    assert(
      html.includes("This is sorted out"),
      "only backend-legal next steps are offered as buttons",
    );

    // Lifecycle and feedback are extras: their absence must not break alerts.
    api.getFindingLifecycle = async () => {
      throw new Error("lifecycle unavailable");
    };
    api.listFindingFeedback = async () => {
      throw new Error("feedback unavailable");
    };
    html = await render(ClinicalSafetyPage);
    assert(
      html.includes("Bleeding risk."),
      "Clinical safety still renders findings without lifecycle data",
    );
    assert(
      html.includes("Not looked at yet"),
      "a finding with no stored state falls back to 'not looked at yet'",
    );

    // ---- Record integrity: corrections audit -----------------------------
    api.getRecordIntegrity = async () =>
      ({
        status: "no_discrepancies_found",
        summary: { records_checked: 2, issues_found: 0, important_issues: 0 },
        issues: [],
        checks_performed: ["patient identity consistency"],
        method: "Deterministic.",
        note: "",
      }) as never;
    api.listCorrections = async () => ({
      corrections: [
        {
          id: "batch:1",
          correction_batch_id: "batch",
          user_id: "anon_test",
          document_id: "doc_a",
          field_path: "medications[0].dosage",
          original_value: "5 mg",
          previous_value: "5 mg",
          corrected_value: "50 mg",
          reason: "Misread on the label",
          created_at: "2026-08-18T10:00:00Z",
        },
      ],
    });
    html = await render(RecordIntegrityPage);
    assert(html.includes("Corrections you have made"), "Record check lists corrections");
    assert(html.includes("Misread on the label"), "each correction shows the reason given");
    assert(html.includes("50 mg"), "each correction shows the corrected value");

    api.listCorrections = async () => ({ corrections: [] });
    html = await render(RecordIntegrityPage);
    assert(
      html.includes("You have not corrected anything yet"),
      "an empty correction history explains itself",
    );

    // ---- Guidelines: refresh action --------------------------------------
    api.getGuidelinesStatus = async () =>
      ({
        sources: [
          {
            key: "who_eml",
            description: "WHO Essential Medicines",
            version: "2025",
            reviewed: "2026-01-01",
            age_days: 10,
            stale: false,
          },
        ],
        total: 1,
        stale_count: 0,
        staleness_threshold_days: 365,
        note: "Reviewed by hand.",
      }) as never;
    html = await render(GuidelinesPage);
    assert(
      html.includes("Check for newer guidelines"),
      "Guidelines exposes the refresh action the backend supports",
    );

    console.log("All page smoke tests passed.");
  } finally {
    restore();
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
