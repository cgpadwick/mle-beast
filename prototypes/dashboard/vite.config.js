import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy `/api/*` to the FastAPI backend during dev so the React app can
// hit it with relative URLs. SSE works through proxies as long as we
// don't buffer — Vite forwards as-is.
export default defineConfig({
  plugins: [react()],
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
