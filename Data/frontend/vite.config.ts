import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { leviathanLayoutEditor } from "../../editor/vite-plugin.mjs";

const layoutEditor = process.env.LEVIATHAN_EDITOR === "1";

export default defineConfig({
  plugins: [react(), ...(layoutEditor ? [leviathanLayoutEditor()] : [])],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    sourcemap: true,
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
