import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assertToolsFrozenClockContract, installToolsV2VisualFixture } from "./helpers/toolsV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(__dirname, "../../docs/ui_reference/tools-v2-reference.jpg");

/**
 * Tools V2 visual regression — application viewport matching reference density.
 * Fixture-only data via window.__LV_V2_VISUAL_FIXTURE__ = 'tools'.
 */
test.describe("Tools V2 visual", () => {
  test.use({ viewport: { width: 1672, height: 941 }, deviceScaleFactor: 1 });

  test("frozen clock contract", () => {
    assertToolsFrozenClockContract();
  });

  test("Screen 1 matches reference within tolerance", async ({ page }) => {
    await installToolsV2VisualFixture(page);

    await page.goto("/tools");
    await expect(page.locator(".lv-v2-page--tools")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText("Runtime & Tools / Tools").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Tools", exact: true }).first()).toBeVisible();
    await expect(page.getByText("Totaal Tools")).toBeVisible();
    await expect(page.getByText("Tools Categorieën")).toBeVisible();
    await expect(page.getByText("Plugin Tools")).toBeVisible();
    await expect(page.getByText("MCP Tools")).toBeVisible();
    await expect(page.getByText("Custom Tools")).toBeVisible();
    await expect(page.getByText("Succesratio")).toBeVisible();
    await expect(page.getByText("Tools Bibliotheek")).toBeVisible();
    await expect(page.getByLabel("Tool Details")).toBeVisible();
    await expect(page.getByRole("tab", { name: "Overzicht" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Parameters" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Schema" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Voorbeeld" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Logs" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Afhankelijkheden" })).toBeVisible();
    await expect(page.getByText("MCP Servers")).toBeVisible();
    await expect(page.getByText("Plugins", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Recente Tool Aanroepen")).toBeVisible();
    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("tools-v2-screen1.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.12,
      animations: "disabled",
    });
  });
});

void REFERENCE;
