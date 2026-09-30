/**
 * Datasets V2 visual regression — local Playwright (NOT GitHub CI).
 * Reference viewport: 1664×936. Fixture-only numbers.
 */
import { expect, test } from "@playwright/test";
import { installDatasetsV2VisualFixture } from "./helpers/datasetsV2Visual";

test.describe("Datasets V2 visual", () => {
  test("screen1 reference composition @ 1664x936", async ({ page }) => {
    await page.setViewportSize({ width: 1664, height: 936 });
    await installDatasetsV2VisualFixture(page);
    await page.goto("/datasets", { waitUntil: "networkidle" });
    await expect(page.getByTestId("datasets-inventory")).toBeVisible({ timeout: 20000 });
    await expect(page.getByText("Totaal Datasets")).toBeVisible();
    await expect(page.getByText("Dataset Verwerking")).toBeVisible();
    await expect(page.getByText("Bron Integraties")).toBeVisible();
    await expect(page.getByText("Dataset Opslag")).toBeVisible();
    await expect(page.getByText("Dataset Activiteit")).toBeVisible();
    await expect(page.locator(".lv-v2-hero--datasets")).toHaveCount(0);
    await expect(page).toHaveScreenshot("datasets-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.02,
    });
  });
});
