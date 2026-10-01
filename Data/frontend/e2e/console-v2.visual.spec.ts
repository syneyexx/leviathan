import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertConsoleFrozenClockContract,
  installConsoleV2VisualFixture,
} from "./helpers/consoleV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/console-v2-reference.png");

/**
 * Console V2 visual regression — application viewport matching Screen 1 density.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'console'.
 */
test.describe("Console V2 visual", () => {
  test.use({ viewport: { width: 1664, height: 936 }, deviceScaleFactor: 1 });

  test("frozen clock contract", () => {
    assertConsoleFrozenClockContract();
  });

  test("Screen 1 structure + screenshot", async ({ page }) => {
    await installConsoleV2VisualFixture(page);

    await page.goto("/console");
    await expect(page.locator(".lv-v2-page--console")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Runtime & Tools / Console").first()).toBeVisible();
    await expect(page.getByText("Totale Logs (24u)", { exact: true })).toBeVisible();
    await expect(page.getByText("Actieve Services", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Waarschuwingen", { exact: true })).toBeVisible();
    await expect(page.getByText("Fouten", { exact: true })).toBeVisible();
    await expect(page.getByText("Gem. Log Rate", { exact: true })).toBeVisible();
    await expect(page.getByText("Log Filters", { exact: true })).toBeVisible();
    await expect(page.getByText("Log Statistieken (Laatste 24 uur)", { exact: true })).toBeVisible();
    await expect(page.getByText("Meest Actieve Componenten", { exact: true })).toBeVisible();
    await expect(page.getByText("Recente Fouten", { exact: true })).toBeVisible();
    await expect(page.getByText("LIVE", { exact: true }).first()).toBeVisible();
    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("console-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });
  });
});

void REFERENCE;
