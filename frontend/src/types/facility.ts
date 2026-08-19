export type FacilityKind =
  "hospital" | "clinic" | "pharmacy" | "laboratory" | "doctor" | "healthcare";

/** Provider-neutral facility shape used by the Find Care page. */
export interface CareFacility {
  id: string;
  name: string;
  kind: FacilityKind;
  latitude: number;
  longitude: number;
  distanceKm: number | null;
  address?: string;
  rating?: number;
  userRatingCount?: number;
  phone?: string;
  website?: string;
  mapsUrl?: string;
  openingHours?: string[];
  openNow?: boolean;
  specialty?: string;
  specialtyMatch?: number;
  availabilityMatch?: boolean;
  rankingScore?: number;
  rankingReason?: string;
  source: string;
}

/** Wire format returned by GET /api/v1/care/facilities. */
export interface CareFacilityResponse {
  id: string;
  name: string;
  kind: FacilityKind;
  latitude: number;
  longitude: number;
  distance_km: number | null;
  address: string | null;
  rating: number | null;
  user_rating_count: number | null;
  phone: string | null;
  website: string | null;
  maps_url: string | null;
  opening_hours: string[] | null;
  open_now: boolean | null;
  specialty: string | null;
  specialty_match: number | null;
  availability_match: boolean | null;
  ranking_score: number | null;
  ranking_reason: string | null;
  source: string;
}

export type CareAvailability = "any" | "today" | "this_week" | "evening" | "weekend";

export interface CareRecommendation {
  triggered: boolean;
  issue_type: string;
  specialty: string;
  specialty_query: string;
  facility_kind: "hospital" | "clinic" | "pharmacy" | "laboratory" | "doctor";
  urgency: "routine" | "prompt";
  reason: string;
  evidence: Array<{ date: string | null; source_file: string | null; page?: number | null }>;
  disclaimer: string;
}
