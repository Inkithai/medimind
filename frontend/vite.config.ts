import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// During local development, run the backend (uvicorn api:app) on :8000
// and the Vite dev server here. Vite proxies /api to the backend so the
// browser uses same-origin relative URLs and avoids CORS.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 5173,
    allowedHosts: true,
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY_TARGET || "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
