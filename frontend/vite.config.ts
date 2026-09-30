/// <reference types="vitest/config" />
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/setupTests.ts"],
    restoreMocks: true,
    coverage: { include: ["src/**/*.{ts,tsx}"], exclude: ["src/main.tsx", "src/**/*.test.*"] },
  },
});
