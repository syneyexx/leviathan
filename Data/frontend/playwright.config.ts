import { defineConfig, devices } from "@playwright/test";

/**
 * Bounded operator-path E2E (WAVE 31).
 * API calls are stubbed in-spec — no live backend required.
 * Browsers optional: `npm run test:e2e` skips honestly when Chromium is missing.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [["list"]],
  timeout: 45_000,
  use: {
    baseURL: process.env.LEVIATHAN_E2E_BASE_URL || "http://127.0.0.1:5173",
    trace: "on-first-retry",
    ...devices["Desktop Chrome"],
  },
  webServer: {
    command: "npx vite --host 127.0.0.1 --port 5173 --strictPort",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
