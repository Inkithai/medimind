/** Care-recommendation types returned by GET /api/v1/care/recommendations. */

export interface CareEvidence {
  date?: string | null;
  source_file?: string | null;
  description: string;
}

export interface ScoreFactor {
  /** Patient-readable name of the factor (e.g. "Medication/allergy conflict"). */
  label: string;
  /** How many points this factor contributed to the final score. */
  points: number;
  /** Optional short evidence note shown next to the factor in the disclosure. */
  note?: string;
}

export type CareRelevance = "high" | "moderate" | "possible";

export interface CareRecommendation {
  /** Patient-facing specialty display name. */
  specialty: string;
  /** Stable identifier (matches the keys in SPECIALTY_DISPLAY). */
  specialty_key: string;
  relevance: CareRelevance;
  /** 0–100 score representing how strongly the records support this care type. */
  relevance_score: number;
  title: string;
  /** One-sentence patient-friendly explanation. */
  reason: string;
  evidence: CareEvidence[];
  source_records: number;
  /** Transparent breakdown of how the score was assembled. */
  score_factors: ScoreFactor[];
  /** True when a safety signal (allergy conflict / drug interaction / etc.) drives the rec. */
  has_safety_signal: boolean;
  /** Optional one-liner shown next to the safety badge. */
  safety_message?: string | null;
}

export interface CareRecommendationsResponse {
  recommendations: CareRecommendation[];
  note?: string;
}

/** Full specialty taxonomy for the search form. */
export interface SpecialtyGroup {
  label: string;
  specialties: Array<{ key: string; name: string }>;
}

/** Searchable specialty option (flattened for the combobox). */
export interface SpecialtyOption {
  key: string;
  name: string;
  group: "recommended" | "browse";
  /** If this is a recommendation, show the reason from the patient's records. */
  recommendationNote?: string;
  /** Relevance bucket for the badge label. */
  relevance?: CareRelevance;
  /** Numeric 0–100 score, when available. */
  relevanceScore?: number;
}

/**
 * Short, search-form-friendly label for each specialty. The backend
 * returns a more verbose label (e.g. "Endocrinologist"); the UI uses
 * this for the specialty selector dropdown and for the "Find nearby"
 * results label.
 */
export const SPECIALTY_DISPLAY: Record<string, string> = {
  general_physician: "General Physician / Primary Care",
  clinical_pharmacist: "Clinical Pharmacist",
  allergist: "Allergy / Immunology",
  endocrinologist: "Endocrinology / Diabetes",
  nephrologist: "Nephrology",
  cardiologist: "Cardiology",
  dermatologist: "Dermatology",
  gastroenterologist: "Gastroenterology",
  hematologist: "Hematology",
  neurologist: "Neurology",
  oncologist: "Oncology",
  ophthalmologist: "Ophthalmology",
  orthopedic: "Orthopedic Specialist",
  psychiatrist: "Psychiatry",
  pulmonologist: "Pulmonology",
  rheumatologist: "Rheumatology",
};
