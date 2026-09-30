import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertWorkflowsFrozenClockContract,
  installWorkflowsV2VisualFixture,
} from "./helpers/workflowsV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/workflows-v2-reference.png");

/**
 * Workflows V2 visual regression — exact reference viewport 1664×936.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'workflows'.
 */
test.describe("Workflows V2 visual", () => {
  test.use({ viewport: { width: 1664, height: 936 }, deviceScaleFactor: 1 });

  test("frozen clock contract", () => {
    assertWorkflowsFrozenClockContract();
  });

  test("Screen 1 matches reference within tolerance", async ({ page }) => {
    await installWorkflowsV2VisualFixture(page);

    await page.goto("/workflows");
    await expect(page.locator(".lv-v2-page--workflows")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("heading", { name: "Workflows", exact: true }).first()).toBeVisible();
    await expect(page.getByText("Totale Workflows")).toBeVisible();
    await expect(page.getByText("Research Pipeline").first()).toBeVisible();
    await expect(page.getByText("Succes Rate")).toBeVisible();
    await expect(page.getByText("Resource Gebruik")).toBeVisible();
    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("workflows-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.08,
      animations: "disabled",
    });
  });
});

void REFERENCE;
