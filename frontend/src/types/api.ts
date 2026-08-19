export type {
  AvailabilityPreference,
  CareEvidenceKind,
  CarePathwayEvidence,
  CareProviderSearchResponse,
  ConsultationAllergy,
  ConsultationDocument,
  ConsultationLabPoint,
  ConsultationMedication,
  ConsultationPack,
  LowConfidenceItem,
  CareRecommendationContext,
  ClinicalFlag,
  LiveProvider,
  SpecialtyRecommendation,
  SpecialtyRoute,
} from "./care";

// TypeScript types that mirror the backend API schemas exactly.
// Source of truth: medical_extractor.py (EXTRACTION_JSON_SCHEMA,
// CROSS_CHECK_JSON_SCHEMA), lab_trends.py, retrieval.py, conversation.py,
// and api.py response shapes.

export type DocumentType =
  | "prescription"
  | "lab_report"
  | "discharge_summary"
  | "imaging_report"
  | "consultation_note"
  | "procedure_report"
  | "other";

export interface TrustMetadata {
  status: "extracted" | "user_corrected" | "source_confirmed" | "quarantined" | string;
  quarantined: boolean;
  conflict_ids: string[];
  reasons: string[];
}

export interface CorrectionMarker {
  paths: string[];
  event_ids: string[];
  last_corrected_at?: string | null;
}

export interface EvidenceRegion {
  evidence_id: string;
  field_path: string;
  page: number;
  quote: string;
  /** [left, top, right, bottom], normalized to 0..1. */
  bbox: [number, number, number, number] | null;
  confidence: number;
  locator: "pdf_text_search" | "vision_model" | "model_quote" | "page_quote" | "page_only" | string;
  verification_status?: string;
  conflict_id?: string;
  original_extracted_value?: unknown;
  corrected_value?: unknown;
}

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
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
  /**
   * False when the drug name could not be converted to its standard English
   * (INN) name, so this medicine cannot be matched against the rest of the
   * record for duplicates or interactions (see language_guard.py).
   */
  cross_check_eligible?: boolean;
  unmatched_reason?: string;
}

export interface LabResult {
  test_name: string;
  value: string;
  unit: string | null;
  reference_range: string | null;
  flag: "normal" | "high" | "low" | "unknown";
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface Diagnosis {
  name: string;
  code: string | null;
  status: "active" | "confirmed" | "suspected" | "history" | "resolved" | "unknown";
  onset_date: string | null;
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface Symptom {
  name: string;
  severity: "mild" | "moderate" | "severe" | "unknown";
  status: "current" | "resolved" | "intermittent" | "historical" | "unknown";
  onset_date: string | null;
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface Procedure {
  name: string;
  procedure_date: string | null;
  body_site: string | null;
  status: "completed" | "planned" | "cancelled" | "historical" | "unknown";
  outcome: string | null;
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface VitalSign {
  name: string;
  value: string;
  unit: string | null;
  measured_at: string | null;
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface ImagingResult {
  study_type: string;
  body_site: string | null;
  study_date: string | null;
  findings: string;
  impression: string | null;
  confidence: number;
  evidence?: EvidenceRegion[];
  _trust?: TrustMetadata;
}

export interface DocumentSource {
  file: string;
  method: "text_layer" | "vision_ocr";
  page?: number;
}

export interface RawTextProcessing {
  processing_status: "COMPLETED" | "FAILED" | "PROCESSING" | "UPLOADED" | string;
  extracted_text: string;
  page_count: number;
  extraction_method: string;
  has_text: boolean;
  confidence?: number | null;
  processed_at?: string | null;
  error_message?: string | null;
}

// A single extracted page/document (one entry in timeline.visits).
export interface Visit {
  _document_id: string;
  document_type: DocumentType;
  date: string | null;
  provider_or_doctor: string | null;
  patient_name: string | null;
  medications: Medication[];
  lab_results: LabResult[];
  diagnoses: Diagnosis[];
  symptoms: Symptom[];
  procedures: Procedure[];
  vital_signs: VitalSign[];
  imaging_results: ImagingResult[];
  allergies_noted: string[];
  diagnoses_or_conditions?: string[];
  clinical_notes: string | null;
  field_evidence?: {
    date: EvidenceRegion[];
    provider_or_doctor: EvidenceRegion[];
    patient_name: EvidenceRegion[];
    allergies_noted: EvidenceRegion[];
    clinical_notes: EvidenceRegion[];
  };
  illegible_or_low_confidence_fields: string[];
  overall_confidence: number;
  _source: DocumentSource;
  document_url?: string;
  cloudinary_public_id?: string | null;
  storage_backend?: "cloudinary" | "supabase" | string;
  storage_path?: string | null;
  storage_bucket?: string | null;
  raw_text_processing?: RawTextProcessing;
  _trust?: TrustMetadata;
  _corrections?: CorrectionMarker;
}

export interface SourceReference {
  date: string | null;
  source_file: string | null;
  page?: number | null;
}

export interface MedicationTimelineEntry extends Medication {
  date: string | null;
  source_file: string | null;
  // Documents recording the SAME physical prescription share a group id
  // (document_dedup.py) so re-uploads don't count as repeat prescriptions.
  prescription_group?: string | null;
  source_page?: number | null;
}

export interface LabResultTimelineEntry extends LabResult {
  date: string | null;
  source_file: string | null;
  source_page?: number | null;
}

export interface ClinicalTimelineProvenance {
  date: string | null;
  document_date: string | null;
  source_file: string | null;
  source_page?: number | null;
  source_method?: DocumentSource["method"];
  document_id: string;
  fact_path: string;
  document_type: DocumentType;
}

export type DiagnosisTimelineEntry = Diagnosis & ClinicalTimelineProvenance;
export type SymptomTimelineEntry = Symptom & ClinicalTimelineProvenance;
export type ProcedureTimelineEntry = Procedure & ClinicalTimelineProvenance;
export type VitalSignTimelineEntry = VitalSign & ClinicalTimelineProvenance;
export type ImagingResultTimelineEntry = ImagingResult & ClinicalTimelineProvenance;

export interface TrustSummary {
  unresolved_conflicts: number;
  resolved_conflicts: number;
  quarantined_documents: number;
  quarantined_facts: number;
  corrected_fields: number;
  retrieval_policy: string;
}

export interface ConflictSource {
  document_id: string;
  field_path: string;
  value: unknown;
  source_file: string;
  page?: number | null;
  confidence?: number | null;
}

export interface RecordConflict {
  conflict_id: string;
  kind: "identity" | "document_date" | "medication" | "lab_result" | string;
  field_type: string;
  fact_key: string;
  severity: "critical" | "high" | string;
  summary: string;
  items: ConflictSource[];
  status: "unresolved" | "resolved" | "superseded";
  authoritative_document_id: string | null;
  resolution_note?: string | null;
  detected_at?: string | null;
  updated_at?: string | null;
  resolved_at?: string | null;
}

export interface Timeline {
  visits: Visit[];
  /** Complete source list for correction/audit; visits is trusted-only. */
  documents?: Visit[];
  medications_timeline: MedicationTimelineEntry[];
  lab_results_timeline: LabResultTimelineEntry[];
  diagnoses_timeline?: DiagnosisTimelineEntry[];
  symptoms_timeline?: SymptomTimelineEntry[];
  procedures_timeline?: ProcedureTimelineEntry[];
  vital_signs_timeline?: VitalSignTimelineEntry[];
  imaging_results_timeline?: ImagingResultTimelineEntry[];
  known_allergies: string[];
  // Files recognised as re-uploads of the same physical prescription.
  // Absent on snapshots built before deduplication existed.
  duplicate_document_groups?: DuplicateDocumentGroup[];
  allergy_evidence?: Array<{
    allergy: string;
    document_id: string;
    source_file: string;
    evidence: EvidenceRegion[];
  }>;
  trust_summary?: TrustSummary;
  conflicts?: RecordConflict[];
}

// ---- Cross-check (medical_extractor.py CROSS_CHECK_JSON_SCHEMA) ----------

export interface DrugInteraction {
  medications_involved: string[];
  explanation: string;
  severity: "low" | "moderate" | "high";
  confidence: number;
  sources?: SourceReference[];
}

export interface DuplicateOccurrence {
  date: string | null;
  source_file: string | null;
  page?: number | null;
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
  page?: number | null;
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
  sources?: SourceReference[];
}

export interface MedicationInstruction extends SourceReference {
  dosage: string | null;
  dosage_value: number | null;
  dosage_unit: string | null;
  frequency: string | null;
  frequency_per_day: number | null;
  is_as_needed: boolean;
}

export interface MedicationTransition {
  medication: string;
  previous: MedicationInstruction;
  current: MedicationInstruction;
  changed_fields?: string[];
  sources: SourceReference[];
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

export interface GuidelineCombination extends GradedFinding {
  opioid?: string;
  depressant?: string;
  plain?: string;
  quote?: string;
  status?: string;
  window_start?: string | null;
  window_end?: string | null;
  citation?: { source?: string; page?: number; publication_no?: string };
}

export interface EmlAgeConflict extends GradedFinding {
  medication?: string;
  restriction?: string;
  explanation?: string;
  severity?: string;
  confidence?: number;
  source_page?: number;
  population?: string;
}

export interface CrossCheckReport {
  // Every finding may additionally carry evidence-grading and timing fields
  // (GradedFinding) — added deterministically server-side.
  potential_drug_interactions: (DrugInteraction & GradedFinding)[];
  duplicate_prescriptions: (DuplicatePrescription & GradedFinding)[];
  conflicting_dosage_instructions: (ConflictingDosage & GradedFinding)[];
  allergy_conflicts: (AllergyConflict & GradedFinding)[];
  guideline_flagged_combinations?: GuidelineCombination[];
  eml_age_conflicts?: EmlAgeConflict[];
  medication_changes?: MedicationTransition[];
  medication_continuations?: MedicationTransition[];
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

/**
 * A page kept despite incomplete drug-name translation. The medications
 * named here are stored, but cannot be compared against the rest of the
 * record for duplicates or interactions.
 */
export interface LanguageDegradation {
  degraded: boolean;
  file?: string;
  problems: string[];
  unmatched_medications: string[];
  languages?: string[];
  confidence?: number;
  message: string;
  advice?: string;
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
  source_page?: number | null;
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
  risk_level?: "none" | "low" | "moderate" | "high";
  risk_reason?: string;
  professional_review_recommended?: boolean;
  confidence: number;
  explanation: string;
}

export interface InsufficientData {
  test_name: string;
  reason: string;
}

export interface SingleLabResult {
  test_name: string;
  date: string | null;
  value: string | number | null;
  numeric_value?: number | null;
  unit?: string | null;
  original_unit?: string | null;
  unit_assumed?: boolean;
  reference_range?: string | null;
  range_source?: "printed" | "general" | null | string;
  range_bounds?: {
    low?: number | null;
    high?: number | null;
    unit?: string | null;
    source?: string | null;
    basis?: Record<string, unknown> | null;
  } | null;
  status: "normal" | "high" | "low" | "unknown" | string;
  source_file: string | null;
  source_page?: number | null;
  confidence?: number | null;
  is_main_test?: boolean;
  explanation: string;
}

export interface LabTrendsReport {
  trends: LabTrend[];
  single_results?: SingleLabResult[];
  patient_context?: { sex?: string | null; age?: number | null };
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
  kind:
    | "status_changed"
    | "value_changed"
    | "newly_measured"
    | "instruction_changed"
    | "newly_documented";
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

// ---- Follow-up action center (follow_up.py) -------------------------------

export interface FollowUpTask {
  id: string;
  kind: "record_verification" | "clinical_question";
  category: string;
  priority: "high" | "medium" | "low";
  title: string;
  action: string;
  reason: string;
  evidence: Array<{
    date: string | null;
    source_file: string | null;
    document_url?: string | null;
  }>;
  timing_guardrail: string;
}

export interface FollowUpPlan {
  tasks: FollowUpTask[];
  summary: {
    total: number;
    high_priority: number;
    medium_priority: number;
    record_verification: number;
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
  /** Earliest cited date. Kept for backward compatibility — prefer `dates`. */
  date: string;
  /** Every date this document was cited for. One document cited across two
   *  visits is still ONE source, so the dates live here rather than
   *  producing duplicate entries. */
  dates?: string[];
  source_file: string;
  // Enriched in code from the timeline (never invented by the model).
  document_type?: DocumentType | string | null;
  document_url?: string;
  /** Page within a multi-page document, when the retrieved chunk had one.
   *  Attached server-side from chunk metadata — never guessed by the model. */
  page?: number | null;
  document_id?: string;
  evidence_id?: string;
  quote?: string;
  bbox?: [number, number, number, number] | null;
  verification_status?: string;
  evidence_tier?: "A" | "B" | "C";
}

export interface QAResponse {
  answer: string;
  confidence: number;
  confidence_reason?: string;
  sources: QASource[];
  // True when the answer combined facts from more than one source document.
  // Optional for older snapshots; the backend always sends it now.
  cross_document?: boolean;
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
  trust_notice?: string;
  quarantined_conflict_count?: number;
}

export interface ChatHistoryEntry {
  role: "user" | "assistant" | "system";
  content: string;
}

// ---- Trust corrections and conflict review -------------------------------

export interface CorrectionEvent {
  id: string;
  correction_batch_id: string;
  user_id: string;
  document_id: string;
  field_path: string;
  original_value: unknown;
  previous_value: unknown;
  corrected_value: unknown;
  reason: string;
  created_at: string;
}

export interface DocumentCorrectionsResponse {
  document_id: string;
  original_extraction: Visit;
  effective_extraction: Visit;
  corrections: CorrectionEvent[];
}

export interface ConflictsResponse {
  conflicts: RecordConflict[];
  resolution_events: Array<{
    id: string;
    conflict_id: string;
    old_status: string;
    new_status: string;
    authoritative_document_id?: string | null;
    note?: string | null;
    created_at: string;
  }>;
  trust_summary: TrustSummary;
}

export interface RecordRebuildResponse {
  timeline: Timeline;
  cross_check_report: CrossCheckReport;
  lab_trends: LabTrendsReport;
  conflicts?: RecordConflict[];
  trust_summary: TrustSummary;
  indexed: boolean;
  chunks_indexed: number;
  index_error?: string | null;
  correction_batch_id?: string;
  events?: CorrectionEvent[];
  conflict?: RecordConflict;
}

export interface DeleteDocumentResponse {
  deleted: true;
  document_id: string;
  file_name?: string | null;
  pages_deleted: number;
  documents_remaining: number;
  indexed: boolean;
  index_error?: string | null;
}

export interface DeleteWorkspaceResponse {
  deleted: true;
}

// ---- Patient snapshot (api.py GET /api/v1/patient-snapshot) --------------
// One request that returns everything the dashboard needs, instead of three
// separate calls to /timeline + /cross-check + /lab-trends.

export interface DosageFinding {
  kind: string;
  medication?: string;
  ingredient?: string;
  explanation?: string;
  confidence?: number;
  severity?: string;
  source?: string;
}

export interface DosageReport {
  findings: DosageFinding[];
  checked_medications?: number;
  note?: string;
}

export interface PatientProfileSummary {
  legal_name?: string | null;
  preferred_name?: string | null;
  date_of_birth?: string | null;
}

export interface PatientSnapshot {
  user_id: string;
  patient_timeline: Timeline;
  cross_check_report: CrossCheckReport;
  lab_trends: LabTrendsReport;
  dosage_report?: DosageReport;
  consult_triage?: { referral_items?: Array<{ trigger?: string; urgency?: string }> };
  patient_profile?: PatientProfileSummary | null;
  trust_summary?: TrustSummary;
  updated_at: string | null;
  // True when the server reconstructed this view from the durable documents
  // table because the cached snapshot row was missing. The record is intact;
  // only the AI safety cross-check still needs to be re-run.
  rebuilt_from_documents?: boolean;
}

// ---- AI analysis logs -----------------------------------------------------

/** Entity counts persisted for one document extraction. */
export interface AnalysisPersistedCounts {
  medications?: number;
  lab_results?: number;
  allergies?: number;
  findings?: number;
  events?: number;
}

/**
 * Result payload of a `document_extraction` entry. One entry covers one
 * uploaded document — `page_count` / `document_ids` describe the extracted
 * page rows that were merged into it.
 */
export interface DocumentExtractionResult {
  summary?: string | null;
  document_type_detected?: string | null;
  confidence_score?: number | null;
  persisted_counts?: AnalysisPersistedCounts;
  source_file?: string | null;
  document_id?: string | null;
  document_ids?: string[];
  page_count?: number;
  raw_text_processing?: Record<string, unknown> | null;
}

/** Result payload of a saved `qa` entry. */
export interface QaAnalysisResult {
  paragraphs?: string[];
  citations?: Array<Record<string, unknown>>;
  confidence?: number | null;
  guidance?: string | null;
}

export interface AnalysisLogRecord {
  id: string;
  analysis_type: "document_extraction" | "qa" | string;
  result: Record<string, unknown> & Partial<DocumentExtractionResult> & Partial<QaAnalysisResult>;
  confidence?: number | null;
  summary?: string | null;
  created_at?: string | null;
}

export interface AnalysisLogsResponse {
  analyses: AnalysisLogRecord[];
  count: number;
  total: number;
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
  trust_summary?: TrustSummary;
  conflicts?: RecordConflict[];
  indexed: boolean;
  index_error?: string;
  // Machine-readable reason indexing did not complete:
  // "memory_limit" | "no_indexable_content" | "indexing_failed".
  index_error_code?: string;
  // Files that failed while the rest of the batch succeeded (partial upload).
  failed_files?: FailedFile[];
  // Re-uploads recognised as byte-for-byte duplicates and not added again.
  duplicate_files_skipped?: DuplicateFileSkipped[];
  /** Files accepted at reduced confidence because some drug names could not be normalized. */
  language_degradations?: LanguageDegradation[];
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

export type FacilityKind = "hospital" | "clinic" | "pharmacy" | "laboratory" | "any";

export interface CareFacility {
  id: string;
  name: string;
  kind: string;
  latitude: number;
  longitude: number;
  address?: string | null;
  phone?: string | null;
  website?: string | null;
  distance_km?: number | null;
  source_url?: string | null;
  provider: string;
}

export interface CareFacilitiesResponse {
  query: { location: string; kind: string };
  origin: { latitude: number; longitude: number; label: string; provider: string } | null;
  facilities: CareFacility[];
  result_count: number;
  provider: string;
  disclaimer: string;
}

export interface HealthResponse {
  status: string;
}

// ---- Find care (Geoapify primary, OpenStreetMap fallback) ---------------

export type CareDay = "mon" | "tue" | "wed" | "thu" | "fri" | "sat" | "sun";
export type CareTimeOfDay = "any" | "morning" | "afternoon" | "evening";
export type CareAvailability = "open" | "closed" | "unknown";
export type CareMatchKind = "specialty" | "hospital" | "general" | "other";

export interface CareSpecialtyOption {
  id: string;
  label: string;
  reasons?: string[];
}

export interface CareSuggestion {
  suggested: CareSpecialtyOption;
  alternatives: CareSpecialtyOption[];
  all: CareSpecialtyOption[];
  has_records: boolean;
}

export interface CarePlace {
  id: string;
  name: string;
  place_type: string;
  match_kind: CareMatchKind;
  specialties: string[];
  address: string | null;
  phone: string | null;
  website: string | null;
  opening_hours: string | null;
  availability: CareAvailability;
  lat: number;
  lon: number;
  distance_km: number;
  score: number;
  source: string;
  source_url: string;
}

export interface CareSearchResponse {
  query: {
    city: string;
    specialty_id: string;
    specialty_label: string;
    days: CareDay[];
    time_of_day: CareTimeOfDay;
    radius_km: number;
  };
  location: { lat: number; lon: number; label: string; source: string };
  suggestion: CareSpecialtyOption;
  results: CarePlace[];
  result_count: number;
  zero_results_hint: string | null;
  source: {
    name: string;
    geocoder: string;
    directory: string;
    license: string;
    attribution: string;
    url: string;
  };
  disclaimer: string;
}

// ========================================================================== //
// Clinical-safety & longitudinal CDS types (P0/P1/P2 features)
// ========================================================================== //

export type Severity = "high" | "moderate" | "low";

/** A generic finding shared by the drug-lab / renal-hepatic / condition engines. */
export interface ClinicalFinding {
  medications_involved?: string[];
  condition?: string;
  organ?: string;
  lab?: { test: string; value: number | string | null; unit: string | null; flag?: string | null };
  lab_markers?: Array<{
    test: string;
    value: number | null;
    unit: string | null;
    flag?: string | null;
  }>;
  explanation: string;
  severity: Severity;
  confidence?: number;
  source?: string;
  rule?: string;
  finding_kind?: string;
  // alert-fatigue annotation
  feedback_verdict?: string | null;
  is_overridden?: boolean;
}

export interface VitalTrend {
  vital: string;
  display_name: string;
  data_points: Array<{ date: string | null; value: string | number }>;
  direction: string;
  latest: string | number;
  unit?: string | null;
  latest_flag: string | null;
  risk_level: string;
  explanation: string;
}
export interface VitalTrendsReport {
  trends: VitalTrend[];
  insufficient_data: Array<{ vital: string; reason: string }>;
  summary: { vital_types: number; abnormal_latest: number };
}

export interface EarlyWarningComponent {
  signal: string;
  value: number | null;
  points: number;
  max_points: number;
  detail: string;
}
export interface EarlyWarningReport {
  score: number;
  max_possible: number;
  risk_band: string;
  advice: string;
  components: EarlyWarningComponent[];
  inputs_available: number;
  inputs_total: number;
  note: string;
}

export interface AdherenceSignal {
  ingredient: string;
  signal: string;
  gap_days?: number;
  between?: string[];
  last_supply?: string;
  estimated_end?: string;
  detail: string;
}
export interface AdherenceReport {
  reference_date?: string;
  signals: AdherenceSignal[];
  summary: { medications_reviewed: number; signal_count: number };
  note: string;
}

export interface SymptomFinding {
  symptom: string;
  relevant_medications_on_record: string[];
  relevant_abnormal_labs: string[];
}
export interface SymptomAnalysis {
  analysed: boolean;
  matched_symptoms?: string[];
  findings?: SymptomFinding[];
  summary?: string;
  note?: string;
}

export interface CareGap {
  kind: string;
  title: string;
  detail: string;
  priority: string;
}
export interface PreventiveCareReport {
  age: number | null;
  sex: string | null;
  care_gaps: CareGap[];
  count: number;
  note: string;
}

export interface ManagedFinding extends ClinicalFinding {
  finding_key: string;
  _source_list?: string;
  _merged_count?: number;
  suppressed_reason?: string;
}
export interface ManagedAlertsReport {
  active_findings: ManagedFinding[];
  active_count: number;
  suppressed_findings: ManagedFinding[];
  suppressed_count: number;
  collapsed_duplicates: number;
  merge_log: Array<{ collapsed_into: string; rule?: string }>;
}

export type FeedbackVerdict = "confirmed" | "false_positive" | "needs_change" | "overridden";
export interface FindingFeedbackInput {
  finding_key?: string;
  finding_kind?: string;
  rule?: string;
  medications_involved?: string[];
  condition?: string;
  organ?: string;
  verdict: FeedbackVerdict;
  reason?: string;
  note?: string;
  reviewer?: string;
}
export interface FindingFeedbackEntry extends FindingFeedbackInput {
  user_id?: string;
  finding_key: string;
  created_at: string;
}
export interface FeedbackMetrics {
  total: number;
  decided: number;
  by_verdict: Record<string, number>;
  confirmation_rate: number | null;
  false_positive_rate: number | null;
  override_rate: number | null;
  by_finding_kind: Record<string, Record<string, number>>;
  noisiest_rules: Array<{
    rule: string;
    total: number;
    overrides: number;
    false_positives: number;
  }>;
}

export type FindingLifecycleState =
  "new" | "active" | "reviewed" | "confirmed" | "dismissed" | "resolved" | "reopened";
export interface FindingLifecycleInput {
  finding_kind?: string;
  rule?: string;
  medications_involved?: string[];
  condition?: string;
  organ?: string;
  to_state: FindingLifecycleState;
  reason?: string;
  actor?: string;
}
export interface FindingLifecycleResult {
  finding_key: string;
  state: FindingLifecycleState;
  from_state?: FindingLifecycleState;
  transitioned?: boolean;
  unchanged?: boolean;
}
export interface FindingLifecycleOverview {
  findings: Array<
    Record<string, unknown> & {
      finding_key: string;
      lifecycle_state: FindingLifecycleState;
      is_open: boolean;
    }
  >;
  open_count: number;
  closed_count: number;
  by_state: Record<string, number>;
}

export interface FhirImportResult {
  patient_name: string;
  documents: unknown[];
  imported: Record<string, number>;
  ignored_resource_types: string[];
  note: string;
  persisted?: boolean;
  persistence_error?: string | null;
}

export interface PatientMeasurementInput {
  name: string;
  value: string | number;
  unit?: string;
  measured_at?: string;
  kind?: string;
  note?: string;
}
export interface PatientMeasurement extends PatientMeasurementInput {
  source: string;
  recorded_at: string;
}

export interface ProviderMessageInput {
  body: string;
  provider?: string;
  thread_id?: string;
  finding_key?: string;
  direction?: string;
}
export interface ProviderMessage extends ProviderMessageInput {
  user_id?: string;
  thread_id: string;
  direction: string;
  created_at: string;
}
export interface ProviderThread {
  thread_id: string;
  provider: string;
  message_count: number;
  last_at: string;
}

export interface GuidelinesSource {
  key: string;
  version: string;
  reviewed: string;
  description: string;
  source_url?: string;
  age_days: number | null;
  stale: boolean;
}
// ---- Consult triage (GET /api/v1/consult-triage) --------------------------

export interface TriageAction {
  /** Rule that fired, e.g. "drug_interaction". */
  trigger: string;
  /** What the finding is about, e.g. "Warfarin + Ibuprofen". */
  subject: string;
  /** Plain-language explanation of the finding. */
  detail: string;
  /** "pharmacist" or "doctor". */
  route: string;
  urgency: string;
  urgency_meaning?: string | null;
  /** Why this was routed to a pharmacist rather than a doctor, or vice versa. */
  why_this_route?: string | null;
  confidence?: number | null;
  confidence_caveat?: string | null;
  category?: string | null;
  specialty?: { key: string; label: string } | null;
  timing?: { status?: string | null; explanation?: string | null } | null;
  is_historical?: boolean;
}

export interface TriageSpecialty {
  key: string;
  label: string;
  urgency: string;
  confidence?: number | null;
  triggered_by?: string[];
}

export interface ConsultTriageReport {
  output_version?: string;
  consult_needed: boolean;
  consult_type?: string | null;
  urgency?: string | null;
  urgency_meaning?: string | null;
  confidence?: number | null;
  recommended_specialties: TriageSpecialty[];
  pharmacist_actions: TriageAction[];
  doctor_actions: TriageAction[];
  referral_items?: TriageAction[];
  document_quality_notices?: Array<Record<string, unknown>>;
  document_quality_note?: string | null;
  summary: string;
  emergency_advice: string;
  note: string;
}

// ---- Medication reconciliation (GET /api/v1/medications/reconciliation) ---

export type ReconciledState =
  "active" | "duplicate" | "dose_conflict" | "discontinued" | "single_supply" | string;

export interface ReconciledMedication {
  ingredient: string;
  display_name: string;
  state: ReconciledState;
  is_active: boolean;
  sources: Array<{
    name?: string;
    date?: string | null;
    source_file?: string | null;
    dose?: string | null;
  }>;
  supply_count: number;
  active_supply_count: number;
  doses: string[];
  dose_conflict: boolean;
  duplicate: boolean;
  notes: string[];
}

export interface MedicationReconciliationReport {
  reference_date: string;
  reconciled_medications: ReconciledMedication[];
  summary: {
    total_ingredients: number;
    active: number;
    discontinued: number;
    duplicates: number;
    dose_conflicts: number;
  };
  note: string;
}

// ---- Deterioration trajectory (GET /api/v1/deterioration) -----------------

export interface DeteriorationPoint {
  date?: string | null;
  score: number;
  risk_band: string;
  components?: Record<string, number | null>;
  source_file?: string | null;
}

export interface DeteriorationReport {
  trajectory: DeteriorationPoint[];
  point_count: number;
  latest_score: number;
  latest_band: string;
  previous_score?: number | null;
  peak_score: number;
  trend: string;
  sustained_high: boolean;
  worsening_signals: string[];
  deteriorating: boolean;
  note: string;
}

// ---- Record export (GET /api/v1/export, /api/v1/export/validation) --------

export interface FhirValidationReport {
  valid: boolean;
  format?: string;
  bundle_type?: string;
  errors?: string[];
  warnings?: string[];
  resource_counts?: Record<string, number>;
  [key: string]: unknown;
}

// ---- Finding history (GET /api/v1/findings/history/change-log) ------------

export interface FindingChangeLogEntry {
  finding_key: string;
  kind?: string | null;
  severity?: string | null;
  rule?: string | null;
  subject?: string | null;
  first_seen: string;
  last_seen: string;
  seen_in_runs: number;
  absent_then_recurred: boolean;
}

export interface FindingChangeLog {
  snapshots: number;
  findings: FindingChangeLogEntry[];
}

// ---- Guidelines refresh (POST /api/v1/guidelines/refresh) -----------------

export interface GuidelinesRefreshResult {
  applied: Array<{ key: string; version: string }>;
  applied_count?: number;
  checked?: boolean;
  checked_at?: string | null;
  manifest_url?: string | null;
  new_sources_in_manifest?: string[] | null;
  reason?: string | null;
  note?: string | null;
  [key: string]: unknown;
}

export interface GuidelinesStatus {
  sources: GuidelinesSource[];
  total: number;
  stale_count: number;
  staleness_threshold_days: number;
  note: string;
}
