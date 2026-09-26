import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

const __dirname = dirname(fileURLToPath(import.meta.url));
const layoutEditorRequested = process.env.LEVIATHAN_EDITOR === "1";
const editorPluginPath = resolve(__dirname, "../../editor/vite-plugin.mjs");

async function optionalEditorPlugins(): Promise<any[]> {
  if (!layoutEditorRequested) {
    return [];
  }
  if (!existsSync(editorPluginPath)) {
    throw new Error(
      "LEVIATHAN_EDITOR=1 but editor/vite-plugin.mjs is unavailable. " +
        "Check out the editor tree, or unset LEVIATHAN_EDITOR for the default LEVIATHAN build.",
    );
  }
  const mod = await import(pathToFileURL(editorPluginPath).href);
  if (typeof mod.leviathanLayoutEditor !== "function") {
    throw new Error(
      "LEVIATHAN_EDITOR=1 but editor/vite-plugin.mjs does not export leviathanLayoutEditor().",
    );
  }
  return [mod.leviathanLayoutEditor()];
}

export default defineConfig(async () => ({
  plugins: [react(), ...(await optionalEditorPlugins())],
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
}));
