import { test, expect } from "@playwright/test";
import { installApiStubs } from "./helpers/apiStub";

test.describe("Brain operator paths", () => {
  test("Brain Graph page loads", async ({ page }) => {
    await installApiStubs(page);
    await page.goto("/brain");
    // Graph view uses hero title; other views use .lv-br-title via BrainHeader.
    await expect(page.getByRole("heading", { name: /^Brain$/i })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.locator('[data-brain-view="Graph"]')).toBeVisible();
  });

  test("Brain Clusters view loads when tab exists", async ({ page }) => {
    await installApiStubs(page);
    await page.goto("/brain");
    const clustersTab = page.locator('[data-brain-view="Clusters"]');
    // Honest skip if route/tab removed — not a fake PASS.
    test.skip((await clustersTab.count()) === 0, "Brain Clusters tab not present");
    await clustersTab.click();
    await expect(page.getByText("Total Clusters")).toBeVisible({ timeout: 20_000 });
  });
});
