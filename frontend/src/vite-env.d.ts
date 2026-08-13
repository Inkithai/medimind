/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev-only: proxy target for the Vite dev server (default: http://127.0.0.1:8000) */
  readonly VITE_API_PROXY_TARGET?: string;
  /** Production: the backend base URL (e.g. https://medimind.snapdeploy.dev) */
  readonly VITE_API_URL?: string;
  /** Optional Photon geocoding endpoint and Open-Meteo city-prefix endpoint. */
  readonly VITE_GEOCODING_API_URL?: string;
  readonly VITE_CITY_GEOCODING_API_URL?: string;
  /** Optional Leaflet tile URL template and matching HTML attribution. */
  readonly VITE_MAP_TILE_URL?: string;
  readonly VITE_MAP_ATTRIBUTION?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
