import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the local FastAPI backend (uvicorn on :8080).
// Prod: FastAPI serves the built dist/ itself, so no proxy needed.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8080" },
  },
  build: { outDir: "dist" },
});
