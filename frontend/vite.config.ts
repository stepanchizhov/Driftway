import path from "path";
import { fileURLToPath } from "url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

// Dev server proxies /api to the local backend so there are no CORS issues
// during development. In production the frontend calls VITE_API_BASE directly.
export default defineConfig({
  plugins: [react()],
  server: {
    fs: {
      strict: false,
      allow: [rootDir, path.resolve(rootDir, "..")],
    },
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
});
