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
  returned_to_normal?: boolean;
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
}

export interface QAResponse {
  answer: string;
  confidence: number;
  sources: QASource[];
  recommend_professional_consult: boolean;
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
