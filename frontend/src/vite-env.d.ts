/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Dev-only: proxy target for the Vite dev server (default: http://127.0.0.1:8000) */
  readonly VITE_API_PROXY_TARGET?: string;
  /** Production: the backend base URL (e.g. https://medimind.snapdeploy.dev) */
  readonly VITE_API_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
