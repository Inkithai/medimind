// TypeScript types that mirror the backend API schemas exactly.
// Source of truth: medical_extractor.py (EXTRACTION_JSON_SCHEMA,
// CROSS_CHECK_JSON_SCHEMA), lab_trends.py, retrieval.py, conversation.py,
// and api.py response shapes.

export type DocumentType = "prescription" | "lab_report" | "discharge_summary" | "other";

export interface Medication {
  name: string;
  ingredients: string[];
  dosage: string;
  frequency: string;
  duration: string | null;
  dosage_value: number | null;
  dosage_unit: string | null;
  frequency_per_day: number | null;
  is_as_needed: boolean;
  confidence: number;
}

export interface LabResult {
  test_name: string;
  value: string;
  unit: string | null;
  reference_range: string | null;
  flag: "normal" | "high" | "low" | "unknown";
  confidence: number;
}

export interface DocumentSource {
  file: string;
  method: "text_layer" | "vision_ocr";
  page?: number;
}

// A single extracted page/document (one entry in timeline.visits).
export interface Visit {
  document_type: DocumentType;
  date: string | null;
  provider_or_doctor: string | null;
  patient_name: string | null;
  medications: Medication[];
  lab_results: LabResult[];
  allergies_noted: string[];
  clinical_notes: string | null;
  illegible_or_low_confidence_fields: string[];
  overall_confidence: number;
  _source: DocumentSource;
  document_url?: string;
  cloudinary_public_id?: string;
}

export interface MedicationTimelineEntry extends Medication {
  date: string | null;
  source_file: string | null;
  // Documents recording the SAME physical prescription share a group id
  // (document_dedup.py) so re-uploads don't count as repeat prescriptions.
  prescription_group?: string | null;
}

export interface LabResultTimelineEntry extends LabResult {
  date: string | null;
  source_file: string | null;
}

export interface Timeline {
  visits: Visit[];
  medications_timeline: MedicationTimelineEntry[];
  lab_results_timeline: LabResultTimelineEntry[];
  known_allergies: string[];
  // Files recognised as re-uploads of the same physical prescription.
  // Absent on snapshots built before deduplication existed.
  duplicate_document_groups?: DuplicateDocumentGroup[];
}

// ---- Cross-check (medical_extractor.py CROSS_CHECK_JSON_SCHEMA) ----------

export interface DrugInteraction {
  medications_involved: string[];
  explanation: string;
  severity: "low" | "moderate" | "high";
  confidence: number;
}

export interface DuplicateOccurrence {
  date: string | null;
  source_file: string | null;
  dosage: string | null;
}

export interface DuplicatePrescription {
  medication: string;
  occurrences: DuplicateOccurrence[];
  explanation: string;
  confidence: number;
}

export interface ConflictingInstruction {
  date: string | null;
  source_file: string | null;
  dosage: string | null;
  frequency: string | null;
}

export interface ConflictingDosage {
  medication: string;
  conflicting_instructions: ConflictingInstruction[];
  explanation: string;
  confidence: number;
}

export interface AllergyConflict {
  medication: string;
  allergy: string;
  explanation: string;
  confidence: number;
}

// Evidence grading + timing (evidence_grading.py, risk_timeline.py) -------

export type EvidenceSource = "deterministic" | "reference_graph" | "model_knowledge";

export interface FindingTiming {
  status: "concurrent" | "possible" | "not_concurrent" | "unknown";
  window_start: string | null;
  window_end: string | null;
  overlap_days: number;
  gap_days: number | null;
  note: string;
}

// Every finding list item may carry these graded/timed fields.
export interface GradedFinding {
  evidence_source?: EvidenceSource;
  grounded?: boolean;
  evidence_note?: string;
  model_reported_confidence?: number;
  timing?: FindingTiming;
}

export interface CrossCheckReport {
  potential_drug_interactions: (DrugInteraction & GradedFinding)[];
  duplicate_prescriptions: (DuplicatePrescription & GradedFinding)[];
  conflicting_dosage_instructions: (ConflictingDosage & GradedFinding)[];
  allergy_conflicts: (AllergyConflict & GradedFinding)[];
  overall_recommendation: string;
  concurrent_exposure?: ConcurrentExposure[];
  timing_summary?: {
    concurrent: number;
    possible: number;
    not_concurrent: number;
    unknown: number;
    note: string;
  };
  evidence_summary?: {
    total_findings: number;
    deterministic: number;
    reference_graph: number;
    model_knowledge: number;
    model_knowledge_confidence_ceiling: number;
    note: string;
  };
}

// ---- Risk timeline (risk_timeline.py) -------------------------------------

export interface ConcurrentExposureSource {
  name: string | null;
  date: string | null;
  source_file: string | null;
  daily_dose: number | null;
}

export interface ConcurrentExposure {
  ingredient: string;
  status: "concurrent" | "possible";
  window_start: string | null;
  window_end: string | null;
  overlap_days: number;
  sources: ConcurrentExposureSource[];
  cumulative_daily_dose: number | null;
  dosage_unit: string | null;
  note: string;
}

export interface RiskCalendarPeriod {
  window_start: string | null;
  window_end: string | null;
  overlap_days: number;
  label: string;
  risks: {
    kind: "drug_interaction" | "duplicate_prescription" | "dosage_conflict";
    subjects: string[];
    severity: string | null;
    confidence: number | null;
    status: string;
    evidence_source?: EvidenceSource | null;
  }[];
}

export interface TreatmentWindow {
  ingredients: string[];
  name: string | null;
  date: string | null;
  start: string | null;
  end: string | null;
  duration_days: number | null;
  duration_known: boolean;
  daily_dose: number | null;
  dosage_unit: string | null;
  source_file: string | null;
  prescription_group: string | null;
}

export interface RiskTimelineReport {
  calendar: RiskCalendarPeriod[];
  concurrent_exposure: ConcurrentExposure[];
  treatment_windows: TreatmentWindow[];
  timing_summary: CrossCheckReport["timing_summary"];
  evidence_summary: CrossCheckReport["evidence_summary"];
}

// ---- Document deduplication (document_dedup.py) ---------------------------

export interface DuplicateDocumentInfo {
  source_file: string | null;
  date: string | null;
  uploaded_at: string | null;
  document_url?: string | null;
  content_sha256?: string | null;
}

export interface DuplicateDocumentGroup {
  prescription_group: string;
  identical_files: boolean;
  medications: string[];
  documents: DuplicateDocumentInfo[];
}

export interface DuplicateFileSkipped {
  filename: string;
  reason: string;
  previously_uploaded_as?: string | null;
  previously_uploaded_at?: string | null;
  message: string;
}

// ---- Lab trends (lab_trends.py) ------------------------------------------

export interface LabDataPoint {
  date: string | null;
  value: string;
  flag: "normal" | "high" | "low" | "unknown";
  source_file: string | null;
}

export interface LabTrend {
  test_name: string;
  unit: string;
  reference_range: string | null;
  data_points: LabDataPoint[];
  direction:
    | "stable"
    | "increasing"
    | "decreasing"
    | "fluctuating (net increasing)"
    | "fluctuating (net decreasing)";
  flag_sequence: string;
  crossed_into_abnormal_at: { date: string | null; flag: string } | null;
  approaching_threshold: boolean;
  confidence: number;
  explanation: string;
}

export interface InsufficientData {
  test_name: string;
  reason: string;
}

export interface LabTrendsReport {
  trends: LabTrend[];
  insufficient_data: InsufficientData[];
  note: string;
}

// ---- Q&A / conversation (retrieval.py, conversation.py) ------------------

export interface QASource {
  date: string;
  source_file: string;
  // Enriched in code from the timeline (never invented by the model).
  document_type?: DocumentType | string | null;
  document_url?: string;
}

export interface QAResponse {
  answer: string;
  confidence: number;
  sources: QASource[];
  // True when the answer combined facts from more than one source document.
  cross_document: boolean;
  recommend_professional_consult: boolean;
  // True when confidence <= 0.6; the consult guard always escalates these.
  low_confidence?: boolean;
  // Deterministic explanation of why a professional consult was forced.
  consult_reason?: string;
  rewritten_query?: string;
  // Entities this turn was resolved against (conversational focus).
  focus?: {
    medications: string[];
    lab_tests: string[];
    source_files: string[];
  };
}

export interface ChatHistoryEntry {
  role: "user" | "assistant" | "system";
  content: string;
}

// ---- Patient snapshot (api.py GET /api/v1/patient-snapshot) --------------
// One request that returns everything the dashboard needs, instead of three
// separate calls to /timeline + /cross-check + /lab-trends.

export interface PatientSnapshot {
  user_id: string;
  patient_timeline: Timeline;
  cross_check_report: CrossCheckReport;
  lab_trends: LabTrendsReport;
  updated_at: string | null;
}

// ---- Upload response (api.py) --------------------------------------------

export interface FailedFile {
  file: string;
  file_id?: string;
  file_index?: number;
  error: string;
  kind?:
    | "not_medical"
    | "transient"
    | "invalid"
    | "unsupported"
    | "rate_limited"
    | "provider_unavailable";
  code?: string;
  retryable?: boolean;
  retry_after_seconds?: number | null;
}

export interface UploadResponse {
  user_id: string;
  // Page/document counts retained for backward compatibility.
  documents_added: number;
  documents_total: number;
  // File counts make multi-page upload summaries unambiguous.
  files_received?: number;
  files_added?: number;
  timeline: Timeline;
  cross_check_report: CrossCheckReport;
  lab_trends: LabTrendsReport;
  indexed: boolean;
  index_error?: string;
  // Files that failed while the rest of the batch succeeded (partial upload).
  failed_files?: FailedFile[];
  // Re-uploads recognised as byte-for-byte duplicates and not added again.
  duplicate_files_skipped?: DuplicateFileSkipped[];
  // True when every file in the batch was an already-uploaded duplicate.
  all_files_duplicate?: boolean;
}

// ---- Sessions ------------------------------------------------------------

export interface SessionInfo {
  user_id: string;
  session_id: string;
}

export interface SessionTurn {
  role: "user" | "assistant";
  content: string;
  timestamp: string;
}

export interface SessionHistory {
  user_id: string;
  session_id: string;
  turns: SessionTurn[];
}

// ---- Health --------------------------------------------------------------

export interface HealthResponse {
  status: string;
}
