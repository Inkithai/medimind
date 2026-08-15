import { FACILITY_KINDS, type CareFacility, type FacilityKind } from "../types/facility";

/**
 * Single source of truth for facility categorisation.
 *
 * The category chips, their counts, and the rendered cards all call the same
 * helpers here, so the UI can never claim "7 found" while showing none: the
 * counts are literally derived from the array that gets rendered.
 */

export type FacilityFilter = "all" | FacilityKind;

/** Coerce any provider value onto a canonical kind, never dropping a result. */
export function normalizeFacilityKind(value: string | null | undefined): FacilityKind {
  const candidate = (value || "").trim().toLowerCase();
  if ((FACILITY_KINDS as readonly string[]).includes(candidate)) {
    return candidate as FacilityKind;
  }
  if (candidate === "lab" || candidate === "medical_lab") return "laboratory";
  if (candidate === "medical_clinic" || candidate === "medical_center") return "clinic";
  if (candidate === "general_hospital") return "hospital";
  if (candidate === "drugstore") return "pharmacy";
  if (candidate === "dentist" || candidate === "physiotherapist" || candidate === "doctors") {
    return "doctor";
  }
  // "healthcare" and anything unmapped stay visible under All / Other.
  return "other";
}

/** The one filter predicate used by both the counts and the rendered list. */
export function matchesFilter(facility: CareFacility, filter: FacilityFilter): boolean {
  return filter === "all" || facility.kind === filter;
}

export function filterFacilities(
  facilities: CareFacility[],
  filter: FacilityFilter
): CareFacility[] {
  return facilities.filter((facility) => matchesFilter(facility, filter));
}

/** Counts computed from the same dataset and predicate that renders cards. */
export function countByFilter(
  facilities: CareFacility[],
  filters: readonly FacilityFilter[]
): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const filter of filters) {
    counts[filter] = facilities.filter((facility) => matchesFilter(facility, filter)).length;
  }
  return counts;
}

/**
 * Always a Google Maps deep link — never OpenStreetMap.
 *
 * Google's canonical `googleMapsUri` is preferred; otherwise we build a Maps
 * search from the facility's real name + address, with the coordinates as the
 * last resort so the pin still lands on the right building.
 */
export function googleMapsUrl(facility: CareFacility): string {
  const isGoogleHost = /^https?:\/\/([a-z0-9-]+\.)*(google\.[a-z.]+|goo\.gl)(\/|$)/i;
  if (facility.mapsUrl && isGoogleHost.test(facility.mapsUrl)) {
    return facility.mapsUrl;
  }
  const query = [facility.name, facility.address].filter(Boolean).join(", ");
  const hasCoordinates = Number.isFinite(facility.latitude) && Number.isFinite(facility.longitude);
  if (!query && hasCoordinates) {
    return `https://www.google.com/maps/search/?api=1&query=${facility.latitude},${facility.longitude}`;
  }
  const params = new URLSearchParams({ api: "1", query });
  if (hasCoordinates) {
    // Keeps the map centred on the listing when several share a name.
    params.set("query", `${query} ${facility.latitude},${facility.longitude}`);
  }
  return `https://www.google.com/maps/search/?${params.toString()}`;
}

/** Google Maps turn-by-turn directions to the facility. */
export function googleDirectionsUrl(facility: CareFacility): string {
  const destination =
    Number.isFinite(facility.latitude) && Number.isFinite(facility.longitude)
      ? `${facility.latitude},${facility.longitude}`
      : [facility.name, facility.address].filter(Boolean).join(", ");
  return `https://www.google.com/maps/dir/?api=1&destination=${encodeURIComponent(destination)}`;
}

/** `tel:` target, or null when the directory published no number. */
export function telHref(phone: string | undefined): string | null {
  if (!phone) return null;
  const cleaned = phone.replace(/[^\d+]/g, "");
  return cleaned.length >= 3 ? `tel:${cleaned}` : null;
}
