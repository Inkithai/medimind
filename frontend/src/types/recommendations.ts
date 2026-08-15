/** Care-recommendation types returned by GET /api/v1/care/recommendations. */

export interface CareEvidence {
  date?: string | null;
  source_file?: string | null;
  description: string;
}

export interface CareRecommendation {
  specialty: string;
  specialty_key: string;
  relevance: "high" | "moderate" | "possible" | "needs_clinical_review";
  title: string;
  explanation: string;
  evidence: CareEvidence[];
  source_records: number;
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
  /** Relevance badge label for recommended specialties. */
  relevance?: string;
}
