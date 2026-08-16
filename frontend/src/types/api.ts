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

export interface CrossCheckReport {
  potential_drug_interactions: DrugInteraction[];
  duplicate_prescriptions: DuplicatePrescription[];
  conflicting_dosage_instructions: ConflictingDosage[];
  allergy_conflicts: AllergyConflict[];
  overall_recommendation: string;
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

// ---- Deterministic record changes (change_detection.py) ------------------

export interface ChangeEvidence {
  date: string | null;
  source_file: string | null;
  document_url?: string | null;
}

export interface RecordChange {
  category: "lab" | "medication" | "allergy";
  kind: "status_changed" | "value_changed" | "newly_measured" | "instruction_changed" | "newly_documented";
  importance: "attention" | "review" | "info";
  title: string;
  description: string;
  before: string | null;
  after: string | null;
  evidence: ChangeEvidence[];
}

export interface RecordComparison {
  from_date: string;
  to_date: string;
  from_source: ChangeEvidence;
  to_source: ChangeEvidence;
  changes: RecordChange[];
  change_count: number;
}

export interface RecordChangesReport {
  latest: RecordComparison | null;
  comparisons: RecordComparison[];
  summary: {
    dated_records: number;
    comparisons: number;
    changes_found: number;
    attention_items: number;
  };
  method: string;
  note: string;
}

// ---- Cross-document record integrity (record_integrity.py) ---------------

export interface IntegrityEvidence {
  date: string | null;
  source_file: string | null;
  document_url?: string | null;
}

export interface IntegrityVariant {
  label: string;
  value: string;
  evidence: IntegrityEvidence[];
}

export interface IntegrityIssue {
  id: string;
  category: "identity" | "allergy" | "medication" | "lab";
  severity: "important" | "review";
  title: string;
  explanation: string;
  variants: IntegrityVariant[];
  suggested_action: string;
  confidence: number;
}

export interface RecordIntegrityReport {
  status: "needs_verification" | "no_discrepancies_found";
  summary: {
    records_checked: number;
    issues_found: number;
    important_issues: number;
  };
  issues: IntegrityIssue[];
  checks_performed: string[];
  method: string;
  note: string;
}

// ---- Appointment preparation (appointment_prep.py) -----------------------

export interface AppointmentEvidence {
  date: string | null;
  source_file: string | null;
  document_url?: string | null;
}

export interface AppointmentPriority {
  id: string;
  level: "important" | "review" | "routine";
  category: string;
  title: string;
  question: string;
  rationale: string;
  evidence: AppointmentEvidence[];
}

export interface HandoffMedication {
  name: string;
  ingredients: string[];
  dosage: string | null;
  frequency: string | null;
  source: AppointmentEvidence;
}

export interface AppointmentPrepReport {
  handoff: {
    record_count: number;
    record_period: { from: string | null; to: string | null };
    providers_documented: string[];
    known_allergies: string[];
    latest_medication_record: AppointmentEvidence | null;
    latest_documented_medications: HandoffMedication[];
    key_findings: Array<{
      level: "important" | "review" | "routine";
      text: string;
      evidence: AppointmentEvidence[];
    }>;
  };
  priorities: AppointmentPriority[];
  checklist: Array<{ id: string; text: string }>;
  method: string;
  note: string;
}

// ---- Q&A / conversation (retrieval.py, conversation.py) ------------------

export interface QASource {
  date: string;
  source_file: string;
}

export interface QAResponse {
  answer: string;
  confidence: number;
  sources: QASource[];
  recommend_professional_consult: boolean;
  question_intent?: {
    key: string;
    label: string;
    retrieval_types: string[];
    safety_sensitive: boolean;
  };
  evidence_sufficiency?: {
    level: "sufficient" | "limited" | "insufficient";
    reason: string;
    retrieved_chunks: number;
    distinct_sources: number;
    expected_minimum: number;
    evidence_types: string[];
    citation_validation?: "passed" | "no_valid_citations";
  };
  rewritten_query?: string;
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
