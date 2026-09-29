import { test, expect } from "@playwright/test";
import { installBrainV2VisualFixture } from "./helpers/brainV2Visual";
import path from "node:path";

const OUT = "/opt/cursor/artifacts/screenshots";

test.describe("Brain V2 interaction demo", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("filter, zoom, and advanced graph", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-dna-node").first()).toBeVisible({ timeout: 15_000 });
    await page.screenshot({
      path: path.join(OUT, "brain-v2-demo-loaded.png"),
      animations: "disabled",
    });

    await page.locator(".lv-v2-dna__tab", { hasText: "Concepten" }).click();
    await page.waitForTimeout(300);
    await page.screenshot({
      path: path.join(OUT, "brain-v2-demo-filter.png"),
      animations: "disabled",
    });

    await page.locator(".lv-v2-dna__tab", { hasText: "Alles" }).click();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.getByRole("button", { name: "Zoom in" }).click();
    await page.waitForTimeout(200);
    await page.screenshot({
      path: path.join(OUT, "brain-v2-demo-zoom.png"),
      animations: "disabled",
    });

    await page.getByRole("button", { name: /Toon geavanceerd/i }).click();
    await expect(page.getByRole("tab", { name: "Tree" })).toBeVisible();
    await page.screenshot({
      path: path.join(OUT, "brain-v2-demo-advanced.png"),
      animations: "disabled",
    });
  });
});
