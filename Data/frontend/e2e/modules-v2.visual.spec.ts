import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertModulesFrozenClockContract, installModulesV2VisualFixture } from "./helpers/modulesV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/modules-v2-reference.png");

/**
 * Modules V2 visual regression — exact reference viewport 1672×941.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'modules'.
 */
test.describe("Modules V2 visual", () => {
  test.use({ viewport: { width: 1672, height: 941 }, deviceScaleFactor: 1 });

  test("frozen clock contract", () => {
    assertModulesFrozenClockContract();
  });

  test("Screen 1 matches reference within tolerance", async ({ page }) => {
    await installModulesV2VisualFixture(page);

    await page.goto("/modules?module=fincept-terminal");
    await expect(page.locator(".lv-v2-page--modules")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Modules", exact: true }).first()).toBeVisible();
    await expect(page.getByText("Feature Flag")).toBeVisible();
    await expect(page.getByText("Fincept Terminal Analytics").first()).toBeVisible();
    await expect(page.getByText("Runtime Informatie")).toBeVisible();
    await expect(page.getByText("Recente Activiteiten")).toBeVisible();
    await expect(page.getByText("Dependencies & Installatie")).toBeVisible();
    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("modules-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.08,
      animations: "disabled",
    });
  });
});

void REFERENCE;
