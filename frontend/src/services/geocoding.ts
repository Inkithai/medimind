import type { Coordinates, LocationPlace } from "../types/location";

// Photon handles OSM places/landmarks and reverse geocoding. Open-Meteo adds
// fast prefix matching for cities (for example, "Nego" → "Negombo"). Both
// endpoints are configurable so production deployments can use hosted copies.
const PHOTON_URL = (import.meta.env?.VITE_GEOCODING_API_URL || "https://photon.komoot.io").replace(
  /\/$/,
  "",
);
const CITY_GEOCODING_URL = (
  import.meta.env?.VITE_CITY_GEOCODING_API_URL || "https://geocoding-api.open-meteo.com/v1"
).replace(/\/$/, "");

interface PhotonFeature {
  properties: {
    osm_type?: string;
    osm_id?: number;
    osm_value?: string;
    type?: string;
    name?: string;
    housenumber?: string;
    street?: string;
    locality?: string;
    district?: string;
    city?: string;
    county?: string;
    state?: string;
    postcode?: string;
    country?: string;
    countrycode?: string;
  };
  geometry: {
    coordinates: [number, number];
  };
}

interface PhotonResponse {
  features?: PhotonFeature[];
}

interface CityResult {
  id: number;
  name: string;
  latitude: number;
  longitude: number;
  feature_code?: string;
  country_code?: string;
  country?: string;
  admin1?: string;
  admin2?: string;
  admin3?: string;
  postcode?: string;
}

interface CityResponse {
  results?: CityResult[];
}

export interface LocationSearchOptions {
  signal?: AbortSignal;
  /** ISO 3166-1 alpha-2 codes. Omit to search worldwide. */
  countryCodes?: string[];
  /** Ranking hint for landmark results; it does not restrict results to this area. */
  proximity?: Coordinates;
  limit?: number;
}

function first(...values: Array<string | undefined>): string | undefined {
  return values.find((value) => value?.trim());
}

function uniqueParts(values: Array<string | undefined>): string[] {
  const seen = new Set<string>();
  return values.filter((value): value is string => {
    const normalized = value?.trim().toLocaleLowerCase();
    if (!value || !normalized || seen.has(normalized)) return false;
    seen.add(normalized);
    return true;
  });
}

function normalizePhoton(feature: PhotonFeature): LocationPlace | null {
  const [longitude, latitude] = feature.geometry?.coordinates || [];
  if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) return null;

  const properties = feature.properties || {};
  const name =
    first(properties.name, properties.street, properties.city, properties.district) ||
    "Selected location";
  const locality = first(
    properties.city,
    properties.district,
    properties.locality,
    properties.county,
  );
  const area =
    locality && locality.toLocaleLowerCase() !== name.toLocaleLowerCase() ? locality : undefined;
  const displayName = uniqueParts([
    properties.name,
    properties.housenumber,
    properties.street,
    properties.locality,
    properties.district,
    properties.city,
    properties.county,
    properties.state,
    properties.postcode,
    properties.country,
  ]).join(", ");

  return {
    id:
      properties.osm_type && properties.osm_id
        ? `${properties.osm_type}-${properties.osm_id}`
        : `photon-${latitude}-${longitude}`,
    name,
    displayName: displayName || name,
    area,
    region: first(properties.state, properties.county),
    country: properties.country,
    countryCode: properties.countrycode?.toUpperCase(),
    postcode: properties.postcode,
    type: properties.osm_value || properties.type,
    latitude,
    longitude,
  };
}

function normalizeCity(city: CityResult): LocationPlace | null {
  if (!Number.isFinite(city.latitude) || !Number.isFinite(city.longitude)) return null;
  return {
    id: `city-${city.id}`,
    name: city.name,
    displayName: uniqueParts([
      city.name,
      city.admin3,
      city.admin2,
      city.admin1,
      city.postcode,
      city.country,
    ]).join(", "),
    region: city.admin1,
    country: city.country,
    countryCode: city.country_code?.toUpperCase(),
    postcode: city.postcode,
    type: city.feature_code?.startsWith("PPL") ? "city" : "place",
    latitude: city.latitude,
    longitude: city.longitude,
  };
}

function languageCode(): string {
  if (typeof navigator === "undefined" || !navigator.language) return "en";
  return navigator.language.split("-")[0] || "en";
}

async function fetchPhotonSearch(
  query: string,
  options: LocationSearchOptions,
  requestLimit: number,
): Promise<LocationPlace[]> {
  const params = new URLSearchParams({
    q: query,
    limit: String(Math.min(requestLimit * 2, 20)),
    lang: languageCode(),
  });
  if (options.proximity) {
    params.set("lat", String(options.proximity.latitude));
    params.set("lon", String(options.proximity.longitude));
  }
  const response = await fetch(`${PHOTON_URL}/api/?${params.toString()}`, {
    signal: options.signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw responseError(response.status);
  const data = (await response.json()) as PhotonResponse;
  if (!Array.isArray(data.features)) return [];
  return data.features
    .map(normalizePhoton)
    .filter((place): place is LocationPlace => Boolean(place));
}

async function fetchCitySearch(
  query: string,
  options: LocationSearchOptions,
  requestLimit: number,
): Promise<LocationPlace[]> {
  const params = new URLSearchParams({
    name: query,
    count: String(Math.min(requestLimit, 10)),
    language: languageCode(),
    format: "json",
  });
  // Open-Meteo accepts one country filter. Multiple countries are filtered
  // after retrieval along with Photon results.
  if (options.countryCodes?.length === 1) {
    params.set("countryCode", options.countryCodes[0]!.toUpperCase());
  }
  const response = await fetch(`${CITY_GEOCODING_URL}/search?${params.toString()}`, {
    signal: options.signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw responseError(response.status);
  const data = (await response.json()) as CityResponse;
  if (!Array.isArray(data.results)) return [];
  return data.results.map(normalizeCity).filter((place): place is LocationPlace => Boolean(place));
}

export async function searchLocations(
  query: string,
  options: LocationSearchOptions = {},
): Promise<LocationPlace[]> {
  const requestLimit = Math.min(Math.max(options.limit ?? 5, 1), 8);
  const normalizedQuery = query.trim();
  const [cities, landmarks] = await Promise.allSettled([
    fetchCitySearch(normalizedQuery, options, requestLimit),
    fetchPhotonSearch(normalizedQuery, options, requestLimit),
  ]);

  if (options.signal?.aborted) throw new DOMException("The request was aborted.", "AbortError");
  if (cities.status === "rejected" && landmarks.status === "rejected") {
    throw cities.reason instanceof Error ? cities.reason : responseError(0);
  }

  const allowedCountries = new Set(options.countryCodes?.map((code) => code.toUpperCase()) || []);
  const combined = [
    ...(cities.status === "fulfilled" ? cities.value : []),
    ...(landmarks.status === "fulfilled" ? landmarks.value : []),
  ].filter(
    (place) =>
      !allowedCountries.size || (place.countryCode && allowedCountries.has(place.countryCode)),
  );

  const unique = new Map<string, LocationPlace>();
  for (const place of combined) {
    // City providers can return the same place with slightly different points.
    const key = `${place.name.toLocaleLowerCase()}|${place.countryCode || ""}|${place.type || ""}`;
    if (!unique.has(key)) unique.set(key, place);
  }
  return [...unique.values()].slice(0, requestLimit);
}

export async function reverseGeocode(
  coordinates: Coordinates,
  signal?: AbortSignal,
): Promise<LocationPlace> {
  const params = new URLSearchParams({
    lat: coordinates.latitude.toFixed(7),
    lon: coordinates.longitude.toFixed(7),
    lang: languageCode(),
  });
  const response = await fetch(`${PHOTON_URL}/reverse?${params.toString()}`, {
    signal,
    headers: { Accept: "application/json" },
  });
  if (!response.ok) throw responseError(response.status);
  const data = (await response.json()) as PhotonResponse;
  const place = data.features
    ?.map(normalizePhoton)
    .find((value): value is LocationPlace => Boolean(value));
  if (!place) throw new Error("We couldn't find an address for this point.");
  return place;
}

function responseError(status: number): Error {
  if (status === 429) {
    return new Error("Location search is busy right now. Please wait a moment and try again.");
  }
  return new Error("We couldn't reach location search. Check your connection and try again.");
}

export function locationSecondaryText(place: LocationPlace): string {
  const parts = uniqueParts([place.area, place.region, place.country]);
  return parts.join(", ") || place.displayName;
}
