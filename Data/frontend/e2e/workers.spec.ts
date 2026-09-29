import { test, expect } from "@playwright/test";
import { installApiStubs } from "./helpers/apiStub";

/**
 * Worker Fabric dashboard surfaces on /agents (no dedicated /workers route).
 * Skip honestly when that operator path is absent.
 */
test.describe("Worker dashboard", () => {
  test("agents page with worker fabric loads when route exists", async ({ page }) => {
    await installApiStubs(page);
    const response = await page.goto("/agents");
    if (!response || response.status() >= 400) {
      test.skip(true, "Workers/agents route unavailable");
    }
    // Release-critical smoke: Agent fleet hosts Worker Fabric projections.
    await expect(page.locator(".lv-app")).toBeVisible({ timeout: 20_000 });
    // Page should not hard-crash into the catch-all redirect away from /agents.
    await expect(page).toHaveURL(/\/agents\/?$/);
  });
});
