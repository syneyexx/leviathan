import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertAnalyticsFrozenClockContract,
  installAnalyticsV2VisualFixture,
} from "./helpers/analyticsV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/analytics-v2-reference.png");

/**
 * Analytics / Statistieken V2 visual regression — viewport 1664×936.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'analytics'.
 */
test.describe("Analytics V2 visual", () => {
  test.use({ viewport: { width: 1664, height: 936 }, deviceScaleFactor: 1 });

  test("frozen clock contract", () => {
    assertAnalyticsFrozenClockContract();
  });

  test("Screen 1 matches reference within tolerance", async ({ page }) => {
    await installAnalyticsV2VisualFixture(page);

    await page.goto("/analytics");
    await expect(page.locator(".lv-v2-page--analytics")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("LLM / Statistieken")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Statistieken", exact: true }).first()).toBeVisible();

    await expect(page.getByText("Totaal Kennis Items")).toBeVisible();
    await expect(page.getByText("Totaal Datasets")).toBeVisible();
    await expect(page.getByText("Totaal Documenten")).toBeVisible();
    await expect(page.getByText("Onderzoek Opdrachten")).toBeVisible();
    await expect(page.getByText("Gem. Verwerkingstijd")).toBeVisible();
    await expect(page.getByText("Systeem Gebruik")).toBeVisible();

    await expect(page.getByText("Kennis Groei")).toBeVisible();
    await expect(page.getByText("Dataset Groei")).toBeVisible();
    await expect(page.getByText("Onderzoek Activiteit")).toBeVisible();

    await expect(page.getByText("Item Types Verdeling")).toBeVisible();
    await expect(page.getByText("Dataset Types")).toBeVisible();
    await expect(page.getByText("Bronnen Verdeling")).toBeVisible();

    await expect(page.getByText("Top Agents")).toBeVisible();
    await expect(page.getByText("Top Bronnen")).toBeVisible();
    await expect(page.getByText("Populairste Tags")).toBeVisible();

    await expect(page.getByText("System Resource Gebruik")).toBeVisible();
    await expect(page.getByText("Verwerkingstijden")).toBeVisible();
    await expect(page.getByText("Activiteit Log")).toBeVisible();

    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("analytics-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.12,
      animations: "disabled",
    });
  });
});

void REFERENCE;
