// Live local-care recommendation contracts. Provider fields are optional because
// they are shown only when the selected external directory returns them.

export type AvailabilityPreference = "any" | "today" | "this_week" | "evenings" | "weekends";

export interface SpecialtyRoute {
  id: string;
  label: string;
  provider_query: string;
}

export interface SpecialtyRecommendation extends SpecialtyRoute {
  reason: string;
  matched_terms: string[];
  // Additive route fields. Existing clients can continue using id/label/query.
  primary?: SpecialtyRoute;
  alternative?: SpecialtyRoute | null;
}

export type CareEvidenceKind =
  | "medication"
  | "allergy"
  | "lab_result"
  | "lab_trend"
  | "visit"
  | "document"
  | "cross_check";

export interface CarePathwayEvidence {
  kind: CareEvidenceKind;
  label: string;
  source_file?: string;
  date?: string;
  document_url?: string;
  page?: number;
  confidence?: number;
  details?: string;
}

export interface ClinicalFlag {
  id: string;
  issue_type: string;
  trigger: "high_risk" | "low_confidence";
  risk_level: "high" | "review";
  title: string;
  // Existing concise flag evidence remains a string for compatibility.
  evidence: string;
  source: string;
  confidence: number | null;
  specialty: SpecialtyRecommendation;
  // Deterministic source-linked record evidence, added for the care pathway.
  pathway_evidence?: CarePathwayEvidence[];
  care_route_explanation?: string;
}

export interface CareRecommendationContext {
  eligible: boolean;
  flags: ClinicalFlag[];
  disclaimer: string;
  message: string;
}

export interface ConsultationDocument {
  source_file: string;
  reason: string;
  date?: string;
  document_url?: string;
  page?: number;
}

export interface ConsultationMedication {
  name: string;
  dose?: string;
  frequency?: string;
  source_file?: string;
  date?: string;
  confidence?: number;
  document_url?: string;
  page?: number;
}

export interface ConsultationAllergy {
  allergen: string;
  source_file?: string;
  date?: string;
  document_url?: string;
  page?: number;
}

export interface ConsultationLabPoint {
  test: string;
  value: string;
  unit?: string;
  date?: string;
  source_file?: string;
  confidence?: number;
  document_url?: string;
  page?: number;
}

export interface LowConfidenceItem {
  type: string;
  label: string;
  reason: string;
  confidence?: number;
  source_file?: string;
  date?: string;
  document_url?: string;
  page?: number;
}

export interface ConsultationPack {
  documents_to_bring: ConsultationDocument[];
  // Deliberately named records_to_discuss because active medication status is not inferred.
  medication_records_to_discuss: ConsultationMedication[];
  allergies: ConsultationAllergy[];
  relevant_lab_points: ConsultationLabPoint[];
  low_confidence_items: LowConfidenceItem[];
  clinician_questions: string[];
  disclaimer: string;
}

export interface ProviderRankingComponent {
  signal: "specialty_relevance" | "distance" | "rating" | "availability";
  /** Percentage weight this signal carries in the match score. */
  weight: number;
  /** 0–1 signal score. */
  score: number;
  /** Contribution to the 0–100 match score. */
  contribution: number;
  explanation: string;
}

export interface ProviderRanking {
  score: number;
  specialty_relevance: string;
  distance: string;
  rating: string;
  availability: string;
  availability_preference: string;
  /** Optional numeric breakdown of the same signals (referral trail). */
  components?: ProviderRankingComponent[];
}

export interface LiveProvider {
  source_provider_id: string | null;
  name: string;
  provider_type: string | null;
  source_specialties: string[];
  address: string | null;
  latitude: number | null;
  longitude: number | null;
  distance_km: number | null;
  rating: number | null;
  rating_count: number | null;
  phone: string | null;
  opening_hours: string[];
  open_now: boolean | null;
  map_url: string | null;
  website_url: string | null;
  source: string;
  ranking: ProviderRanking;
}

export interface CareProviderSearchResponse {
  clinical_flag: ClinicalFlag;
  specialty: SpecialtyRecommendation;
  // Additive evidence fields from the same authenticated clinical snapshot.
  evidence?: CarePathwayEvidence[];
  care_route_explanation?: string;
  consultation_pack?: ConsultationPack;
  location: {
    query: string;
    resolved_area: string | null;
    latitude: number | null;
    longitude: number | null;
  };
  availability: AvailabilityPreference;
  provenance: {
    live: true;
    source_id: string;
    label: string;
    retrieved_at: string;
  };
  ranking_method: string;
  providers: LiveProvider[];
  no_results_message: string | null;
  disclaimer: string;
  /** Referral trail (Phase 3): why this finding produced this search,
   *  plus the persisted record of the search itself. */
  referral_id?: string;
  referral_reason?: string;
  referral?: ReferralTrail;
}

/** Persisted referral-trail record (GET /api/v1/care-referrals + search
 *  responses). A historical record OF a search, not a live directory. */
export interface ReferralTrail {
  search_id: string;
  created_at: string;
  intent: {
    clinical_flag: {
      id: string;
      issue_type: string | null;
      trigger: string | null;
      risk_level: string | null;
      title: string | null;
      evidence: string | null;
      source: string | null;
      confidence: number | null;
    };
    specialty: {
      id: string | null;
      label: string | null;
      provider_query: string | null;
      reason: string | null;
    };
    referral_reason: string;
    care_route_explanation?: string | null;
    evidence: CarePathwayEvidence[];
    location: {
      query: string | null;
      resolved_area: string | null;
      latitude: number | null;
      longitude: number | null;
    };
    availability: string;
    availability_label: string;
  };
  results: LiveProvider[];
  ranking_method: string;
  provenance: {
    source_id: string | null;
    label: string | null;
    retrieved_at: string | null;
  };
  disclaimer: string;
}
