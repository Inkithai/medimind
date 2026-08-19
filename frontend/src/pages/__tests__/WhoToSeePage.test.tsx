/**
 * "Who should I talk to?" page — the consult triage the backend already
 * computed but that had no screen until now.
 *
 * These tests render the real page against a stubbed API and assert the
 * things a worried, non-technical reader depends on:
 *   * the answer (pharmacist vs doctor) is stated as a heading, first;
 *   * urgency is written in words, not implied by colour;
 *   * "no trigger found" is never rendered as "you are fine";
 *   * a fresh workspace (404) sees an invitation to upload, not an error.
 *
 * Run with: tsx src/pages/__tests__/WhoToSeePage.test.tsx
 */
import { StrictMode, act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { JSDOM } from "jsdom";
import { MemoryRouter } from "react-router-dom";

import { ApiError, api } from "../../api/client";
import { AuthProvider } from "../../context/AuthContext";
import { I18nProvider } from "../../i18n/I18nContext";
import { ToastProvider } from "../../components/Toast";
import { WhoToSeePage } from "../WhoToSeePage";
import type { ConsultTriageReport } from "../../types/api";

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

const REPORT: ConsultTriageReport = {
  output_version: "1",
  consult_needed: true,
  consult_type: "doctor",
  urgency: "urgent",
  urgency_meaning: "This should be looked at within 24 hours.",
  confidence: 0.82,
  recommended_specialties: [
    { key: "cardiology", label: "Heart specialist", urgency: "urgent", triggered_by: ["Warfarin"] },
  ],
  pharmacist_actions: [
    {
      trigger: "duplicate_prescription",
      subject: "Paracetamol",
      detail: "Two active supplies of the same ingredient were found.",
      route: "pharmacist",
      urgency: "soon",
      why_this_route: "A pharmacist can confirm which supply to keep.",
      confidence: 0.7,
    },
  ],
  doctor_actions: [
    {
      trigger: "drug_interaction",
      subject: "Warfarin + Ibuprofen",
      detail: "These two together raise the risk of bleeding.",
      route: "doctor",
      urgency: "urgent",
      why_this_route: "Changing either medicine needs a prescriber.",
      confidence: 0.82,
      specialty: { key: "cardiology", label: "Heart specialist" },
    },
  ],
  referral_items: [],
  document_quality_notices: [],
  document_quality_note: "1 uploaded document needs source verification.",
  summary: "A doctor should be consulted — this should be looked at within 24 hours.",
  emergency_advice: "If you have chest pain or heavy bleeding, seek emergency care now.",
  note: "This is a routing suggestion, not a diagnosis.",
};

async function renderPage(): Promise<string> {
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
                <WhoToSeePage />
              </ToastProvider>
            </AuthProvider>
          </I18nProvider>
        </MemoryRouter>
      </StrictMode>,
    );
    await new Promise((resolve) => window.setTimeout(resolve, 10));
  });
  const html = container.innerHTML;
  act(() => root.unmount());
  container.remove();
  return html;
}

async function main() {
  const originalHealth = api.healthUnauthenticated;
  const originalCreate = api.createAnonymousSession;
  const originalTriage = api.getConsultTriage;

  try {
    localStorage.clear();
    api.healthUnauthenticated = async () => ({ status: "ok" });
    api.createAnonymousSession = async () => ({
      user_id: "anon_test",
      token: "token",
      session_id: "session",
    });

    // --- a report that needs a doctor ---------------------------------
    api.getConsultTriage = async () => REPORT;
    const html = await renderPage();

    assert(html.includes("Talk to a doctor"), "the answer is stated as the main heading");
    assert(
      html.includes("Urgent — within 24 hours"),
      "urgency is written in words, not colour alone",
    );
    assert(
      html.includes("This should be looked at within 24 hours."),
      "the backend's urgency meaning is shown",
    );
    assert(
      html.includes("If you have chest pain or heavy bleeding"),
      "emergency advice from the backend is always visible",
    );
    assert(
      html.includes("Warfarin + Ibuprofen") &&
        html.includes("These two together raise the risk of bleeding."),
      "each doctor action shows its subject and plain explanation",
    );
    assert(
      html.includes("Paracetamol") && html.includes("Ask a pharmacist about"),
      "pharmacist items are listed separately from doctor items",
    );
    assert(html.includes("Heart specialist"), "the recommended specialty is named");
    assert(
      html.includes("This is a routing suggestion, not a diagnosis."),
      "the backend's standing note is never dropped",
    );
    assert(
      html.includes("needs source verification"),
      "document-quality notices are surfaced, not hidden",
    );

    // --- nothing triggered: must not read as a clean bill of health ----
    api.getConsultTriage = async () => ({
      ...REPORT,
      consult_needed: false,
      consult_type: null,
      urgency: null,
      urgency_meaning: null,
      confidence: null,
      recommended_specialties: [],
      pharmacist_actions: [],
      doctor_actions: [],
      document_quality_note: null,
      summary:
        "These automated checks found no trigger for a consult. That is not a clean bill of health.",
    });
    const calmHtml = await renderPage();
    assert(
      calmHtml.includes("No reason to book an appointment was found"),
      "a clear answer is given when nothing was triggered",
    );
    assert(
      calmHtml.includes("not a clean bill of health"),
      "the safety caveat from the backend is shown verbatim",
    );

    // --- fresh workspace ------------------------------------------------
    api.getConsultTriage = async () => {
      throw new ApiError(404, "No records found for this user.");
    };
    const emptyHtml = await renderPage();
    assert(
      emptyHtml.includes("There are no records to check yet"),
      "a fresh workspace sees an empty state, not an error",
    );
    assert(emptyHtml.includes("Upload a document"), "the empty state offers the next step");
    assert(
      !emptyHtml.includes("Something went wrong"),
      "a 404 never renders the generic error screen",
    );

    console.log("All Who-to-see page tests passed.");
  } finally {
    api.healthUnauthenticated = originalHealth;
    api.createAnonymousSession = originalCreate;
    api.getConsultTriage = originalTriage;
  }
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
