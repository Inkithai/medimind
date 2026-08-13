export type FacilityKind =
  | "hospital"
  | "clinic"
  | "pharmacy"
  | "laboratory"
  | "doctor"
  | "healthcare";

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
}
