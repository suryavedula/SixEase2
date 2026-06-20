import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Vite config (TASK-003, EPIC-01).
// - @tailwindcss/vite: Tailwind v4 (CSS-first, no tailwind.config.js / postcss.config.js).
// - server.host: bind 0.0.0.0 so the dockerised dev server (compose `frontend`) is reachable.
// - the dev server runs on 5173, which the backend CORS list already allow-lists.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    port: 5173,
    // Poll-based watching keeps hot reload working through the Docker bind-mount.
    watch: { usePolling: true },
  },
});
