import { renderToStaticMarkup } from "react-dom/server";

import { ConsultationPack } from "../ConsultationPack";
import type { ConsultationPack as ConsultationPackData } from "../../types/api";

function assert(condition: boolean, message: string) {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

const completePack: ConsultationPackData = {
  documents_to_bring: [
    {
      source_file: "Prescription_01.pdf",
      reason: "Contains medication record(s) relevant to this concern.",
      date: "2026-08-04",
      document_url: "https://files.example.test/prescription-01.pdf",
    },
  ],
  medication_records_to_discuss: [
    {
      name: "Medication A",
      dose: "500 mg",
      frequency: "twice daily",
      source_file: "Prescription_01.pdf",
      confidence: 0.94,
      document_url: "https://files.example.test/prescription-01.pdf",
    },
  ],
  allergies: [
    {
      allergen: "Penicillin",
      source_file: "Prescription_01.pdf",
      document_url: "https://files.example.test/prescription-01.pdf",
    },
  ],
  relevant_lab_points: [
    {
      test: "Creatinine",
      value: "1.32",
      unit: "mg/dL",
      source_file: "Renal_Labs_02.pdf",
      document_url: "https://files.example.test/renal-labs-02.pdf",
    },
  ],
  low_confidence_items: [
    {
      type: "low_confidence_dosage",
      label: "Dosage or frequency information requires verification",
      reason: "The existing record contains low-confidence information.",
      confidence: 0.46,
      source_file: "Prescription_01.pdf",
      document_url: "https://files.example.test/prescription-01.pdf",
    },
  ],
  clinician_questions: ["Can you confirm the correct dosage and frequency?"],
  disclaimer: "MediMind does not diagnose conditions or replace professional medical advice.",
};

const completeMarkup = renderToStaticMarkup(<ConsultationPack pack={completePack} />);
assert(completeMarkup.includes("Prepare for your consultation"), "renders consultation-pack heading");
assert(completeMarkup.includes("Prescription_01.pdf"), "renders relevant document");
assert(completeMarkup.includes("View document"), "renders valid document link");
assert(completeMarkup.includes("Medication A"), "renders medication record");
assert(completeMarkup.includes("Penicillin"), "renders actual recorded allergy");
assert(completeMarkup.includes("Creatinine"), "renders relevant lab point");
assert(completeMarkup.includes("Dosage or frequency information requires verification"), "renders low-confidence item");
assert(completeMarkup.includes("46%"), "renders existing low-confidence value");
assert(completeMarkup.includes("Can you confirm the correct dosage and frequency?"), "renders clinician question");
assert(completeMarkup.includes("does not diagnose"), "renders medical disclaimer");

const sparsePack: ConsultationPackData = {
  documents_to_bring: [{ source_file: "Original_Prescription.pdf", reason: "Contains information relevant to this concern." }],
  medication_records_to_discuss: [],
  allergies: [],
  relevant_lab_points: [],
  low_confidence_items: [],
  clinician_questions: ["Can you verify the unclear information in the original document?"],
  disclaimer: "MediMind does not diagnose conditions or replace professional medical advice.",
};

const sparseMarkup = renderToStaticMarkup(<ConsultationPack pack={sparsePack} />);
assert(!sparseMarkup.includes("View document"), "does not create a source link without a valid URL");
assert(!sparseMarkup.includes("Medication records to discuss"), "hides empty medication section");
assert(!sparseMarkup.includes("Recorded allergies"), "hides empty allergy section");
assert(!sparseMarkup.includes("Relevant laboratory results"), "hides empty lab section");
assert(!sparseMarkup.includes("Information to verify"), "hides empty verification section");
assert(sparseMarkup.includes("Original_Prescription.pdf"), "keeps filename when URL is unavailable");

console.log("\nAll ConsultationPack tests passed.");
