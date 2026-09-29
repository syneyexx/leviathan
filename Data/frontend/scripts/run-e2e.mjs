#!/usr/bin/env node
/**
 * WAVE 31 — run Playwright with honest SKIP when browsers are unavailable.
 * Set LEVIATHAN_E2E_REQUIRED=1 to fail hard (release evidence runs).
 * Missing browsers / missing package = SKIP (exit 0), never fake PASS.
 */
import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";

const required = process.env.LEVIATHAN_E2E_REQUIRED === "1";
const require = createRequire(import.meta.url);

function skip(message) {
  console.log(`SKIP: ${message}`);
  console.log(
    required
      ? "LEVIATHAN_E2E_REQUIRED=1 — treating this as failure."
      : "Not a PASS. Install browsers: npx playwright install chromium",
  );
  process.exit(required ? 1 : 0);
}

try {
  require.resolve("@playwright/test/package.json");
} catch {
  skip("@playwright/test is not installed");
}

const browserProbe = spawnSync(
  process.execPath,
  [
    "--input-type=module",
    "-e",
    `
    import { chromium } from '@playwright/test';
    const b = await chromium.launch({ headless: true });
    await b.close();
    `,
  ],
  { encoding: "utf8", cwd: process.cwd() },
);

if (browserProbe.status !== 0) {
  const detail = `${browserProbe.stderr || ""}\n${browserProbe.stdout || ""}`;
  if (
    /Executable doesn't exist|browserType\.launch|Please run.*playwright install|Host system is missing dependencies/i.test(
      detail,
    ) ||
    browserProbe.status === 1 ||
    browserProbe.status === 2
  ) {
    skip(`Playwright Chromium unavailable (${detail.trim().split("\\n")[0] || "launch failed"})`);
  }
  skip(`Playwright Chromium probe failed: ${detail.trim().slice(0, 240)}`);
}

const result = spawnSync("npx", ["playwright", "test", "-c", "playwright.config.ts"], {
  stdio: "inherit",
  shell: process.platform === "win32",
  env: process.env,
  cwd: process.cwd(),
});

process.exit(result.status ?? 1);
