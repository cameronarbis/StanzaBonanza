import { defineConfig } from "vite";

// In dev, Vite proxies /api to the FastAPI server so the browser sees
// one origin and production CORS stays empty (docs/DESIGN.md §5.7).
export default defineConfig({
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
