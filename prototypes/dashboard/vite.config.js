import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// `npm run build` writes the bundled SPA into src/mle_beast/web/static/ so
// the FastAPI app can serve it directly when the user runs `mle-beast`
// without a separate Vite dev server. The path is relative to this config
// file (../../src/...) so the build works from any cwd.
//
// During dev (`npm run dev`), Vite serves on :5173 and proxies /api/* to
// the FastAPI backend on :8000, which is the editor-friendly workflow
// (hot reload, no need to rebuild on every save).
const staticOutDir = fileURLToPath(
  new URL("../../src/mle_beast/web/static", import.meta.url),
);

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: staticOutDir,
    emptyOutDir: true,
  },
  server: {
    port: 5173,
    host: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
