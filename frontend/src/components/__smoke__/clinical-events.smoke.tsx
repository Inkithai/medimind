import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { ClinicalEventsTimeline } from "../ClinicalEventsTimeline";
import { DocumentViewer } from "../DocumentViewer";
import { TimelineView } from "../TimelineView";
import { I18nProvider } from "../../i18n/I18nContext";
import type { EvidenceRegion, Timeline, Visit } from "../../types/api";

function evidence(id: string, path: string, quote: string): EvidenceRegion {
  return {
    evidence_id: id,
    field_path: path,
    page: 2,
    quote,
    bbox: [0.1, 0.2, 0.8, 0.28],
    confidence: 0.95,
    locator: "pdf_text_search",
  };
}

const visit: Visit = {
  _document_id: "doc-clinical",
  document_type: "consultation_note",
  date: "2025-05-20",
  provider_or_doctor: "Dr. Silva",
  patient_name: "Jane Doe",
  medications: [],
  lab_results: [],
  diagnoses: [{
    name: "Essential hypertension",
    code: "I10",
    status: "active",
    onset_date: "2024-01-10",
    confidence: 0.93,
    evidence: [evidence("ev_diagnosis", "/diagnoses/0", "Assessment: Essential hypertension (I10)")],
  }],
  symptoms: [{
    name: "Headache",
    severity: "moderate",
    status: "current",
    onset_date: "2025-05-18",
    confidence: 0.9,
    evidence: [evidence("ev_symptom", "/symptoms/0", "moderate headache")],
  }],
  procedures: [{
    name: "Appendectomy",
    procedure_date: "2018-06-01",
    body_site: "appendix",
    status: "historical",
    outcome: "No documented complications",
    confidence: 0.88,
    evidence: [evidence("ev_procedure", "/procedures/0", "Past surgery: appendectomy")],
  }],
  vital_signs: [{
    name: "Blood pressure",
    value: "120/80",
    unit: "mmHg",
    measured_at: "2025-05-20",
    confidence: 0.97,
    evidence: [evidence("ev_vital", "/vital_signs/0", "BP 120/80 mmHg")],
  }],
  imaging_results: [{
    study_type: "Chest X-ray",
    body_site: "chest",
    study_date: "2025-05-19",
    findings: "No focal airspace opacity",
    impression: "No acute cardiopulmonary abnormality",
    confidence: 0.95,
    evidence: [evidence("ev_imaging", "/imaging_results/0", "No acute cardiopulmonary abnormality")],
  }],
  allergies_noted: [],
  clinical_notes: null,
  field_evidence: {
    date: [],
    provider_or_doctor: [],
    patient_name: [],
    allergies_noted: [],
    clinical_notes: [],
  },
  illegible_or_low_confidence_fields: [],
  overall_confidence: 0.94,
  _source: { file: "consult.pdf", method: "text_layer", page: 2 },
};

const provenance = {
  date: "2025-05-20",
  document_date: "2025-05-20",
  source_file: "consult.pdf",
  source_page: 2,
  source_method: "text_layer" as const,
  document_id: "doc-clinical",
  fact_path: "/clinical/0",
  document_type: "consultation_note" as const,
};

const timeline: Timeline = {
  visits: [visit],
  documents: [visit],
  medications_timeline: [],
  lab_results_timeline: [],
  diagnoses_timeline: [{ ...visit.diagnoses![0], ...provenance, date: "2024-01-10", fact_path: "/diagnoses/0" }],
  symptoms_timeline: [{ ...visit.symptoms![0], ...provenance, date: "2025-05-18", fact_path: "/symptoms/0" }],
  procedures_timeline: [{ ...visit.procedures![0], ...provenance, date: "2018-06-01", fact_path: "/procedures/0" }],
  vital_signs_timeline: [{ ...visit.vital_signs![0], ...provenance, fact_path: "/vital_signs/0" }],
  imaging_results_timeline: [{ ...visit.imaging_results![0], ...provenance, date: "2025-05-19", fact_path: "/imaging_results/0" }],
  known_allergies: [],
};

function assertIncludes(markup: string, expected: string, label: string) {
  if (!markup.includes(expected)) {
    throw new Error(`FAIL: ${label}\nExpected markup to include: ${expected}\n${markup}`);
  }
  console.log(`PASS: ${label}`);
}

const documentMarkup = renderToStaticMarkup(<I18nProvider><DocumentViewer visit={visit} /></I18nProvider>);
assertIncludes(documentMarkup, "Documented diagnoses (1)", "document viewer shows diagnoses");
assertIncludes(documentMarkup, "Symptoms &amp; signs (1)", "document viewer shows symptoms");
assertIncludes(documentMarkup, "Procedures (1)", "document viewer shows procedures");
assertIncludes(documentMarkup, "Vital signs (1)", "document viewer shows vitals");
assertIncludes(documentMarkup, "Imaging (1)", "document viewer shows imaging");
assertIncludes(documentMarkup, "Page 2 · View evidence", "clinical facts link to page evidence");
assertIncludes(documentMarkup, "No acute cardiopulmonary abnormality", "imaging impression remains visible");

const timelineMarkup = renderToStaticMarkup(<I18nProvider><TimelineView timeline={timeline} /></I18nProvider>);
assertIncludes(timelineMarkup, "5 clinical events", "timeline summarizes longitudinal clinical event count");
assertIncludes(timelineMarkup, "Essential hypertension", "timeline renders documented diagnoses");
assertIncludes(timelineMarkup, "120/80", "timeline renders vital values");
assertIncludes(timelineMarkup, "Chest X-ray", "timeline renders imaging studies");

const clinicalTimelineMarkup = renderToStaticMarkup(
  <MemoryRouter>
    <ClinicalEventsTimeline timeline={timeline} />
  </MemoryRouter>
);
assertIncludes(clinicalTimelineMarkup, "Longitudinal clinical events", "history has an event-date-specific clinical timeline");
assertIncludes(clinicalTimelineMarkup, "2018", "historical procedure date is surfaced independently of document date");
assertIncludes(
  clinicalTimelineMarkup,
  "/documents?document=doc-clinical&amp;evidence=ev_diagnosis",
  "clinical timeline events deep-link to exact source evidence"
);

const undatedTimeline: Timeline = {
  ...timeline,
  diagnoses_timeline: [{ ...timeline.diagnoses_timeline![0], name: "First undated", date: null }],
  symptoms_timeline: [{ ...timeline.symptoms_timeline![0], name: "Second undated", date: null }],
  procedures_timeline: [],
  vital_signs_timeline: [],
  imaging_results_timeline: [],
};
const undatedMarkup = renderToStaticMarkup(
  <MemoryRouter><ClinicalEventsTimeline timeline={undatedTimeline} /></MemoryRouter>
);
if (undatedMarkup.indexOf("First undated") >= undatedMarkup.indexOf("Second undated")) {
  throw new Error("FAIL: undated events retain deterministic insertion order");
}
console.log("PASS: undated events retain deterministic insertion order");

console.log("\nAll longitudinal clinical event smoke assertions passed.");
