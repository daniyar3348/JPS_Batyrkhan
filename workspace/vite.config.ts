import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// In development the API runs on :8000; the dev server proxies to it so the session cookie is same-origin.
const apiTarget = process.env.JPS_API_URL ?? "http://localhost:8000";
const proxied = ["/api", "/public", "/health", "/ready"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(proxied.map((path) => [path, { target: apiTarget, changeOrigin: false }])),
  },
  build: {
    outDir: "dist",
    sourcemap: true,
    rolldownOptions: {
      output: {
        // React and the router change rarely, so they get their own long-cached chunk. Other libraries stay
        // with the pages that use them, so the first load does not include code only admin pages need.
        codeSplitting: {
          groups: [{ name: "react", test: /node_modules[\\/](react|react-dom|scheduler|react-router)[\\/]/ }],
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
  },
});
