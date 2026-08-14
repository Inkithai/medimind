import { renderToStaticMarkup } from "react-dom/server";
import { I18nProvider } from "../../i18n/I18nContext";

import { CareEvidencePanel } from "../CareEvidencePanel";
import type { ClinicalFlag } from "../../types/api";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

const completeFlag: ClinicalFlag = {
  id: "interaction-0",
  issue_type: "high_severity_interaction",
  trigger: "high_risk",
  risk_level: "high",
  title: "Potential high-severity medication interaction",
  evidence: "Medication A; Medication B; potential interaction detected.",
  source: "Medication safety cross-check",
  confidence: 0.91,
  specialty: {
    id: "pharmacy",
    label: "Pharmacist / prescribing doctor",
    provider_query: "pharmacy",
    reason: "Medication safety concerns are best reviewed by a pharmacist or prescribing clinician.",
    matched_terms: [],
    primary: { id: "pharmacy", label: "Pharmacist / prescribing doctor", provider_query: "pharmacy" },
    alternative: { id: "general_practice", label: "General Physician", provider_query: "general practitioner" },
  },
  care_route_explanation: "MediMind identified a potential medication-safety issue from 2 medication record(s).",
  pathway_evidence: [
    {
      kind: "medication",
      label: "Medication A",
      source_file: "Prescription_01.pdf",
      date: "2026-08-04",
      document_url: "https://files.example.test/prescription-01.pdf",
      confidence: 0.94,
      details: "500 mg · twice daily",
    },
    {
      kind: "cross_check",
      label: "Potential interaction detected",
      confidence: 0.91,
      details: "Potential interaction requires professional review.",
    },
  ],
};

const completeMarkup = renderToStaticMarkup(<I18nProvider><CareEvidencePanel flag={completeFlag} /></I18nProvider>);
assert(completeMarkup.includes("Why MediMind suggests this care route"), "renders the care-route title");
assert(completeMarkup.includes("Medication A"), "renders source-linked medication evidence");
assert(completeMarkup.includes("Prescription_01.pdf"), "renders the actual source filename");
assert(completeMarkup.includes("View source document"), "renders a source link only for the existing URL");
assert(completeMarkup.includes("91%"), "renders actual available confidence");
assert(completeMarkup.includes("General Physician"), "renders the broader alternative route");

const sparseFlag: ClinicalFlag = {
  ...completeFlag,
  confidence: null,
  specialty: {
    ...completeFlag.specialty,
    alternative: null,
  },
  pathway_evidence: [
    {
      kind: "document",
      label: "Original_Prescription.pdf",
      source_file: "Original_Prescription.pdf",
    },
  ],
};

const sparseMarkup = renderToStaticMarkup(<I18nProvider><CareEvidencePanel flag={sparseFlag} /></I18nProvider>);
assert(!sparseMarkup.includes("91%"), "does not fabricate a missing flag confidence");
assert(!sparseMarkup.includes("View source document"), "does not render a source link without a valid URL");
assert(!sparseMarkup.includes("General Physician"), "does not fabricate an absent broader alternative");
assert(sparseMarkup.includes("Original_Prescription.pdf"), "renders source filename when a URL is unavailable");

console.log("\nAll CareEvidencePanel tests passed.");
