import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Proxy API calls to Flask so the browser sees one origin (no CORS setup needed).
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": `http://localhost:${process.env.API_PORT || 5001}` },
  },
});
