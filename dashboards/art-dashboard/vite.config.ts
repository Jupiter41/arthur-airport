/// <reference types="vitest" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const gatewayHttpTarget =
  process.env.VITE_GATEWAY_PROXY_TARGET || "http://localhost:3000";
const gatewayWsTarget = gatewayHttpTarget.replace(/^http/, "ws");

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: gatewayHttpTarget,
        changeOrigin: true,
      },
      "/auth": {
        target: gatewayHttpTarget,
        changeOrigin: true,
      },
      "/ws": {
        target: gatewayWsTarget,
        ws: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          mapbox: ["mapbox-gl"],
          leaflet: ["leaflet"],
          recharts: ["recharts"],
        },
      },
    },
  },
});
