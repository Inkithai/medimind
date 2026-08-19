import { act } from "react";
import { createRoot } from "react-dom/client";
import { JSDOM } from "jsdom";
import { Alert } from "../../components/Alert";
import { DocumentViewer } from "../../components/DocumentViewer";
import { LanguageSelector } from "../../components/LanguageSelector";
import { LoadingState } from "../../components/Spinner";
import { ConsultationPack } from "../../components/ConsultationPack";
import { ProviderResultCard } from "../../components/ProviderResultCard";
import { TabBar, TabPanel } from "../../components/TabBar";
import { I18nProvider } from "../../i18n/I18nContext";
import type {
  ConsultationPack as ConsultationPackData,
  LiveProvider,
  Visit,
} from "../../types/api";

const dom = new JSDOM(
  "<!doctype html><html lang='en'><head><title>Accessibility test</title></head><body><main id='root'></main></body></html>",
  {
    url: "https://medimind.test/",
  },
);
Object.assign(globalThis, {
  window: dom.window,
  document: dom.window.document,
  localStorage: dom.window.localStorage,
  Node: dom.window.Node,
  Element: dom.window.Element,
  HTMLElement: dom.window.HTMLElement,
  getComputedStyle: dom.window.getComputedStyle,
  IS_REACT_ACT_ENVIRONMENT: true,
});
Object.defineProperty(globalThis, "navigator", { value: dom.window.navigator, configurable: true });

const visit: Visit = {
  _document_id: "doc-accessibility-test",
  document_type: "prescription",
  date: "2026-08-14",
  provider_or_doctor: "Dr. Test",
  patient_name: "Test Patient",
  medications: [],
  lab_results: [],
  diagnoses: [],
  symptoms: [],
  procedures: [],
  vital_signs: [],
  imaging_results: [],
  allergies_noted: [],
  clinical_notes: "Follow-up note",
  illegible_or_low_confidence_fields: [],
  overall_confidence: 0.9,
  _source: { file: "record.pdf", method: "text_layer" },
};

const consultationPack: ConsultationPackData = {
  documents_to_bring: [],
  medication_records_to_discuss: [],
  allergies: [],
  relevant_lab_points: [
    { test: "Creatinine", value: "1.2", unit: "mg/dL", source_file: "labs.pdf" },
  ],
  low_confidence_items: [],
  clinician_questions: ["What should I verify?"],
  disclaimer: "Review original information with a qualified clinician.",
};

const provider: LiveProvider = {
  source_provider_id: "test-provider",
  name: "Directory result",
  provider_type: "clinic",
  source_specialties: [],
  address: "Test address",
  latitude: null,
  longitude: null,
  distance_km: 2.4,
  rating: null,
  rating_count: null,
  phone: null,
  opening_hours: [],
  open_now: null,
  map_url: null,
  website_url: null,
  source: "Test directory",
  ranking: {
    score: 70,
    specialty_relevance: "Category match",
    distance: "Nearby",
    rating: "No rating supplied",
    availability: "Not confirmed",
    availability_preference: "Any time",
  },
};

const HUB_TABS = [
  { id: "alerts", label: "Alerts", badge: 2 },
  { id: "clinical", label: "Clinical" },
  { id: "timeline", label: "Over time" },
];

async function main() {
  const { default: axe } = await import("axe-core");
  const root = createRoot(document.getElementById("root")!);
  await act(async () => {
    root.render(
      <I18nProvider>
        <h1>Accessibility test</h1>
        <LanguageSelector />
        <Alert variant="danger" title="Error">
          Example error
        </Alert>
        <LoadingState label="Loading records" />
        <DocumentViewer visit={visit} onClose={() => undefined} />
        <ConsultationPack pack={consultationPack} />
        <section>
          <h2>Test provider results</h2>
          <ProviderResultCard provider={provider} index={0} />
        </section>
        {/* Hub tab chrome. Only the selected panel is mounted, which is why
            aria-controls is advertised for the selected tab alone — axe
            fails a control that points at an element not in the document. */}
        <section>
          <h2>Test hub tabs</h2>
          <TabBar
            tabs={HUB_TABS}
            active="clinical"
            onSelect={() => undefined}
            group="axe"
            label="Safety views"
          />
          <TabPanel group="axe" id="clinical" active="clinical">
            <p>Clinical findings panel</p>
          </TabPanel>
        </section>
      </I18nProvider>,
    );
  });

  const results = await axe.run(document, {
    rules: {
      // JSDOM does not calculate rendered colors/layout. Contrast is covered
      // by the checked design tokens and browser/manual audit.
      "color-contrast": { enabled: false },
    },
  });
  if (results.violations.length) {
    throw new Error(
      results.violations.map((violation) => `${violation.id}: ${violation.help}`).join("\n"),
    );
  }

  const tablists = document.querySelectorAll<HTMLElement>('[role="tablist"]');
  if (tablists.length !== 2)
    throw new Error(`Expected the document and hub tablists, found ${tablists.length}`);

  let tabs = Array.from(tablists[0].querySelectorAll<HTMLElement>('[role="tab"]'));
  if (tabs.length !== 3) throw new Error(`Expected 3 accessible tabs, found ${tabs.length}`);
  await act(async () => {
    tabs[1].dispatchEvent(
      new dom.window.KeyboardEvent("keydown", { key: "ArrowLeft", bubbles: true }),
    );
  });
  tabs = Array.from(tablists[0].querySelectorAll<HTMLElement>('[role="tab"]'));
  if (tabs[0].getAttribute("aria-selected") !== "true") {
    throw new Error("Document tabs must support arrow-key navigation");
  }

  // Hub tabs: exactly one selected, and only it claims a panel.
  const hubTabs = Array.from(tablists[1].querySelectorAll<HTMLElement>('[role="tab"]'));
  const selectedHubTabs = hubTabs.filter((tab) => tab.getAttribute("aria-selected") === "true");
  if (selectedHubTabs.length !== 1)
    throw new Error(`Expected exactly one selected hub tab, found ${selectedHubTabs.length}`);
  for (const tab of hubTabs) {
    const controls = tab.getAttribute("aria-controls");
    if (!controls) continue;
    if (!document.getElementById(controls))
      throw new Error(`Tab "${tab.textContent}" points at a panel that is not rendered`);
  }
  if (selectedHubTabs[0].getAttribute("tabindex") === "-1")
    throw new Error("The selected hub tab must be the one in the tab order");
  if (!document.querySelector("select[aria-label]"))
    throw new Error("Language selector needs an accessible name");
  if (!document.querySelector('[role="alert"]'))
    throw new Error("Error alert needs assertive semantics");
  if (!document.querySelector('[aria-busy="true"]'))
    throw new Error("Loading state needs aria-busy");

  act(() => root.unmount());
  console.log("PASS: axe found no WCAG violations in shared interactive components");
}

void main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
