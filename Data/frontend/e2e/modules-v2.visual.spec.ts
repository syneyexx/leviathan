import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/modules-v2-reference.png");

/**
 * Modules V2 visual regression — exact reference viewport 1672×941.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'modules'.
 */
test.describe("Modules V2 visual", () => {
  test.use({ viewport: { width: 1672, height: 941 } });

  test("Screen 1 matches reference within tolerance", async ({ page }) => {
    await page.addInitScript(() => {
      (window as Window & { __LV_V2_VISUAL_FIXTURE__?: string; __LV_V2_FROZEN_NOW__?: string }).__LV_V2_VISUAL_FIXTURE__ =
        "modules";
      (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__ = "2025-05-25T14:37:26.000Z";
    });

    await page.goto("/modules?module=fincept-terminal");
    await expect(page.locator(".lv-v2-page--modules")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Modules", exact: true }).first()).toBeVisible();
    await expect(page.getByText("Feature Flag")).toBeVisible();
    await expect(page.getByText("Fincept Terminal Analytics").first()).toBeVisible();

    await expect(page).toHaveScreenshot("modules-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.08,
      // Reference lives under docs; Playwright stores baselines under e2e.
    });
  });
});
