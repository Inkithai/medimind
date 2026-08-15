export type FacilityKind =
  | "hospital"
  | "clinic"
  | "doctor"
  | "pharmacy"
  | "laboratory"
  | "other";

export type MatchLevel = "exact" | "related" | "other";

export type EntityType = "practitioner" | "facility" | "organization";

export interface CareSpecialty {
  key: string;
  label: string;
}

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
  source: string;
  entityType: EntityType;
  specialties: string[];
  matchLevel?: MatchLevel;
  matchReason?: string;
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
  source: string;
  entity_type: EntityType;
  specialties: string[];
  match_level: MatchLevel | null;
  match_reason: string | null;
}
