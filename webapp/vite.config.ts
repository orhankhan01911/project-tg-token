/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  // The Python API runs on 127.0.0.1:8001; proxy /api so the Mini App can
  // call its backend without CORS preflights during local dev. In production,
  // the Mini App is served over HTTPS via tunnel/Vercel and the API URL is
  // configured via VITE_API_URL.
  // Pinned to 5183 — earlier ports (5173–5180) are taken by sibling
  // frontends on this host. Don't fight them.
  server: {
    host: "127.0.0.1",
    port: 5183,
    strictPort: true,
    // Vite 5 rejects unknown hosts by default. We accept any *.trycloudflare.com
    // tunnel + the local origins. For prod, the Mini App is served from
    // a fixed hostname (Vercel etc.) and this list won't matter.
    allowedHosts: [".trycloudflare.com", "127.0.0.1", "localhost"],
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8002",
        changeOrigin: true,
      },
    },
  },
  test: {
    globals: true,
    environment: "happy-dom",
    setupFiles: ["./src/test-setup.ts"],
  },
});
