/** Scored care-recommendation types returned by GET /api/v1/care/recommendations. */

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

export interface ScoredCareRecommendation {
  /** Patient-facing specialty display name. */
  specialty: string;
  /** Stable identifier (matches the keys in SPECIALTY_KEY_TO_FINDER). */
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

export interface ScoredCareRecommendationsResponse {
  recommendations: ScoredCareRecommendation[];
  note?: string;
}

/**
 * Maps the recommendation engine's specialty keys onto the care-finder
 * taxonomy ids used by the specialty selector and the facilities search
 * (`care_finder.SPECIALTIES` on the backend). Keys without a dedicated
 * directory category fall back to general practice, which can review
 * the full record and refer onward.
 */
export const SPECIALTY_KEY_TO_FINDER: Record<string, string> = {
  general_physician: "general_practice",
  clinical_pharmacist: "general_practice",
  allergist: "allergy_immunology",
  endocrinologist: "endocrinology",
  nephrologist: "nephrology",
  cardiologist: "cardiology",
  dermatologist: "dermatology",
  gastroenterologist: "gastroenterology",
  hematologist: "general_practice",
  neurologist: "neurology",
  oncologist: "oncology",
  ophthalmologist: "ophthalmology",
  orthopedic: "orthopedics",
  psychiatrist: "psychiatry",
  pulmonologist: "pulmonology",
  rheumatologist: "rheumatology",
};

export function finderSpecialtyFor(specialtyKey: string): string {
  return SPECIALTY_KEY_TO_FINDER[specialtyKey] || "general_practice";
}
