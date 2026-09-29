import { test, expect } from "@playwright/test";
import { installApiStubs } from "./helpers/apiStub";

test.describe("operator smoke", () => {
  test("app startup smoke — shell mounts", async ({ page }) => {
    await installApiStubs(page);
    await page.goto("/");
    await expect(page.locator(".lv-app")).toBeVisible({ timeout: 20_000 });
  });
});
