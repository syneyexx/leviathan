import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { defineConfig, loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

function gitSha(): string {
  try {
    return execSync("git rev-parse --short=12 HEAD", { stdio: ["ignore", "pipe", "ignore"] }).toString().trim();
  } catch {
    return "unknown";
  }
}

function rejectFixtureLeak(mode: string): Plugin {
  return {
    name: "reject-fixture-leak",
    generateBundle(_options, bundle) {
      if (mode === "fixture") return;
      const blob = Object.values(bundle)
        .map((item) => ("code" in item ? item.code : ""))
        .join("\n");
      if (blob.includes("visualFixture") || blob.includes("FixtureRoot")) {
        throw new Error("Production bundle contains the visual fixture.");
      }
    },
  };
}

const version = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8")).version as string;

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  if (mode !== "fixture" && env.VITE_LEVIATHAN_VISUAL_FIXTURE === "1") {
    throw new Error("Refusing build: VITE_LEVIATHAN_VISUAL_FIXTURE is set outside fixture mode.");
  }
  return {
    plugins: [react(), rejectFixtureLeak(mode)],
    define: {
      __LEVIATHAN_BUILD__: JSON.stringify({
        version,
        sha: gitSha(),
        time: new Date().toISOString(),
      }),
    },
    clearScreen: false,
    server: {
      port: 1420,
      strictPort: true,
      host: "127.0.0.1",
    },
    preview: {
      port: 4178,
      strictPort: true,
      host: "127.0.0.1",
    },
    build: {
      target: "es2022",
      sourcemap: false,
      outDir: mode === "fixture" ? "dist-fixture" : "dist",
      emptyOutDir: true,
    },
    test: {
      environment: "jsdom",
      css: false,
    },
  };
});
