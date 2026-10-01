import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { installDatasetsV2VisualFixture } from "./helpers/datasetsV2Visual";
import { DATASETS_V2_VISUAL_FROZEN_ISO } from "../src/mocks/datasetsV2VisualFixture";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

/**
 * Legacy `/dataset-management` redirect → canonical `/datasets?mode=manage`.
 * Fixture-only data via installDatasetsV2VisualFixture (route mocks + frozen clock).
 */
test.describe("Dataset Management → Datasets redirect", () => {
  test.use({
    viewport: { width: 1672, height: 941 },
    deviceScaleFactor: 1,
  });

  test("frozen clock fixture remains stable", () => {
    expect(DATASETS_V2_VISUAL_FROZEN_ISO).toBe("2025-05-25T14:37:26.000Z");
  });

  test("dataset-management redirects to canonical datasets manage mode", async ({ page }) => {
    await installDatasetsV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/dataset-management");
    await expect(page).toHaveURL(/\/datasets\?.*mode=manage/, { timeout: 20_000 });
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-page--datasets")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      /Onderzoek|Kennis/i,
    );
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText(
      /Datasets/i,
    );
    await expect(nav.getByRole("link", { name: /Datasets/i })).toBeVisible();

    const critical = errors.filter((e) => !/favicon|ResizeObserver|Non-Error/i.test(e));
    expect(critical).toEqual([]);
  });
});
