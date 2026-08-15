/** The canonical Find Care categories. `other` keeps unclassified healthcare
 * listings visible under "All" instead of silently dropping them. */
export const FACILITY_KINDS = [
  "hospital",
  "clinic",
  "pharmacy",
  "laboratory",
  "doctor",
  "other",
] as const;

export type FacilityKind = (typeof FACILITY_KINDS)[number];

/** Provider-neutral facility shape used by the Find Care page.
 *
 * Optional fields are `undefined` only when the directory did not publish
 * them. The UI must render a "not available" fallback instead of inventing a
 * value. */
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
  /** Directory-provided specialty/primary-type label, e.g. "Dentist". */
  specialty?: string;
  /** True/false only when the search requested a specialty. */
  specialtyMatch?: boolean;
  source: string;
}

/** Wire format returned by GET /api/v1/care/facilities. */
export interface CareFacilityResponse {
  id: string;
  name: string;
  kind: string;
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
  specialty?: string | null;
  specialty_match?: boolean | null;
  source: string;
}
