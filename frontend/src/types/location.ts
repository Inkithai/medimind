export interface Coordinates {
  latitude: number;
  longitude: number;
}

/** A normalized place returned by a geocoder or the browser's GPS. */
export interface LocationPlace extends Coordinates {
  id: string;
  name: string;
  displayName: string;
  area?: string;
  region?: string;
  country?: string;
  countryCode?: string;
  postcode?: string;
  /** Nominatim category, for example `city`, `beach`, or `bus_station`. */
  type?: string;
}

/** How the coordinates were obtained, so the UI never implies the user
 *  deliberately chose a location they never picked. */
export type LocationSource = "search" | "geolocation" | "pin" | "saved";

/** The durable value emitted only after the user confirms the pin. */
export interface ConfirmedLocation extends LocationPlace {
  addressDetails?: string;
  confirmedAt: string;
  source?: LocationSource;
}
