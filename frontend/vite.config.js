import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev, the Vite server proxies API calls to the FastAPI backend. The backend
// port is taken from CA_BACKEND_PORT (set by run.sh) and defaults to 8000.
// In production, FastAPI serves the built files from dist/, so relative paths work.
const backendPort = process.env.CA_BACKEND_PORT || "8000";
export default defineConfig({
  plugins: [react()],
  base: "./",
  server: {
    port: 5173,
    proxy: {
      "/api": `http://localhost:${backendPort}`,
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
