import { execSync } from "child_process";
import path from "path";
import { fileURLToPath } from "url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const rootDir = path.dirname(fileURLToPath(import.meta.url));

/**
 * The commit being built, so the app can say exactly which build it is.
 * Render sets RENDER_GIT_COMMIT for every build; elsewhere git is asked, and
 * without either the build is "dev". Shown in Settings next to the version.
 */
function buildCommit(): string {
  const fromRender = (process.env.RENDER_GIT_COMMIT ?? "").trim();
  if (fromRender) return fromRender.slice(0, 7);
  try {
    return execSync("git rev-parse --short=7 HEAD", { cwd: rootDir, stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "dev";
  }
}

// Dev server proxies /api to the local backend so there are no CORS issues
// during development. In production the frontend calls VITE_API_BASE directly.
export default defineConfig({
  plugins: [react()],
  define: {
    __BUILD_COMMIT__: JSON.stringify(buildCommit()),
  },
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
