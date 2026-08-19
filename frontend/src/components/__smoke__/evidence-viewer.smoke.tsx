import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { DocumentViewer } from "../DocumentViewer";
import { EvidenceViewer } from "../EvidenceViewer";
import { QAResultCard } from "../QAResultCard";
import { I18nProvider } from "../../i18n/I18nContext";
import type { EvidenceRegion, Visit } from "../../types/api";

const evidence: EvidenceRegion = {
  evidence_id: "ev_hba1c",
  field_path: "/lab_results/0",
  page: 2,
  quote: "HbA1c 6.1 %",
  bbox: [0.1, 0.2, 0.7, 0.3],
  confidence: 1,
  locator: "pdf_text_search",
};

const visit: Visit = {
  _document_id: "doc_lab",
  document_type: "lab_report",
  date: "2025-02-03",
  provider_or_doctor: "Dr. Silva",
  patient_name: "Jane Doe",
  medications: [],
  lab_results: [
    {
      test_name: "HbA1c",
      value: "6.1",
      unit: "%",
      reference_range: "4.0-5.6",
      flag: "high",
      confidence: 0.9,
      evidence: [evidence],
    },
  ],
  diagnoses: [],
  symptoms: [],
  procedures: [],
  vital_signs: [],
  imaging_results: [],
  allergies_noted: [],
  clinical_notes: null,
  field_evidence: {
    date: [{ ...evidence, evidence_id: "ev_date", field_path: "/date", quote: "Date: 2025-02-03" }],
    provider_or_doctor: [],
    patient_name: [],
    allergies_noted: [],
    clinical_notes: [],
  },
  illegible_or_low_confidence_fields: [],
  overall_confidence: 0.9,
  _source: { file: "lab.pdf", method: "text_layer" },
  document_url: "https://res.cloudinary.com/demo/image/upload/mediscan/lab.pdf",
};

function assertIncludes(markup: string, expected: string, label: string) {
  if (!markup.includes(expected)) {
    throw new Error(`FAIL: ${label}\nExpected markup to include: ${expected}\n${markup}`);
  }
  console.log(`PASS: ${label}`);
}

const viewer = renderToStaticMarkup(<EvidenceViewer visit={visit} evidence={evidence} />);
assertIncludes(viewer, "f_jpg,pg_2", "PDF evidence renders the cited Cloudinary page");
assertIncludes(
  viewer,
  'aria-label="Highlighted evidence region"',
  "normalized evidence renders a visual overlay",
);
assertIncludes(viewer, "left:10%", "overlay uses normalized horizontal coordinates");
assertIncludes(viewer, "HbA1c 6.1 %", "viewer displays the exact supporting quote");

const unavailable = renderToStaticMarkup(
  <EvidenceViewer
    visit={{ ...visit, document_url: undefined }}
    evidence={{ ...evidence, bbox: null }}
  />,
);
assertIncludes(
  unavailable,
  "original file is unavailable",
  "missing originals have an honest fallback",
);
assertIncludes(
  unavailable,
  "HbA1c 6.1 %",
  "quote remains visible when the original is unavailable",
);

const documentMarkup = renderToStaticMarkup(
  <I18nProvider>
    <DocumentViewer visit={visit} />
  </I18nProvider>,
);
assertIncludes(
  documentMarkup,
  "Page 2 · View evidence",
  "structured facts expose evidence controls",
);
assertIncludes(documentMarkup, "Page 2 · View evidence", "lab rows link back to source evidence");

const qaMarkup = renderToStaticMarkup(
  <I18nProvider>
    <MemoryRouter>
      <QAResultCard
        result={{
          answer: "It was 6.1%.",
          confidence: 0.95,
          sources: [
            {
              date: "2025-02-03",
              source_file: "lab.pdf",
              page: 2,
              document_id: "doc_lab",
              evidence_id: "ev_hba1c",
              quote: "HbA1c 6.1 %",
              bbox: [0.1, 0.2, 0.7, 0.3],
              verification_status: "extracted",
              evidence_tier: "A",
            },
          ],
          recommend_professional_consult: false,
        }}
      />
    </MemoryRouter>
  </I18nProvider>,
);
assertIncludes(
  qaMarkup,
  "/documents?document=doc_lab&amp;evidence=ev_hba1c",
  "Q&A citations deep-link to the exact document evidence",
);
assertIncludes(qaMarkup, "HbA1c 6.1 %", "Q&A citations show their verbatim quote");

console.log("\nAll evidence viewer smoke assertions passed.");
