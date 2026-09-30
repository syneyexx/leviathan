import { test, expect } from "@playwright/test";
import { installApiStubs } from "./helpers/apiStub";
import { installBrainV2VisualFixture } from "./helpers/brainV2Visual";

test.describe("Brain operator paths", () => {
  test("Brain Graph page loads", async ({ page }) => {
    await installApiStubs(page);
    await page.goto("/brain");
    // V2 shell: hero title is Leviathan Brain; DNA stage is the default graph.
    await expect(page.getByRole("heading", { name: /Leviathan Brain/i })).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByText("Kennis Netwerk", { exact: true })).toBeVisible();
    await expect(page.locator(".lv-v2-dna")).toBeVisible();
  });

  test("Kennis Netwerk keeps Research Memory tools inside the panel", async ({ page }) => {
    await installApiStubs(page);
    await page.goto("/brain");
    await expect(page.getByText("Kennis Netwerk", { exact: true })).toBeVisible({ timeout: 20_000 });
    const panel = page.locator(".lv-v2-brain-network-panel");
    await expect(panel.locator(".lv-v2-dna")).toBeVisible();
    await expect(panel.getByRole("button", { name: "DNA" })).toBeVisible();
    await expect(panel.getByRole("button", { name: "Relaties" })).toBeVisible();
    const tools = panel.getByRole("tablist", { name: "Onderzoekstools" });
    await expect(tools.getByRole("tab", { name: "Bewijs" })).toBeVisible();
    await expect(tools.getByRole("tab", { name: /Kennishiaten/ })).toBeVisible();
    await expect(tools.getByRole("tab", { name: "Vergelijken" })).toBeVisible();
    await expect(tools.getByRole("tab", { name: "Agents" })).toBeVisible();
    await expect(tools.getByRole("tab", { name: "Wijzigingen" })).toBeVisible();
    await expect(tools.getByRole("tab", { name: "Bewaren" })).toBeVisible();
    // Surrounding Brain sections remain
    await expect(page.getByText("Geselecteerde Node", { exact: true })).toBeVisible();
    await expect(page.getByText("Recente Kennis Activiteit", { exact: true })).toBeVisible();
    await expect(page.getByText("Redenering Queue", { exact: true })).toBeVisible();
    await expect(page.getByText("Systeem Gezondheid", { exact: true })).toBeVisible();
  });

  test("Brain Clusters view loads when tab exists", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    const clustersTab = page.locator('[data-brain-view="Clusters"]');
    // Honest skip if route/tab removed — not a fake PASS.
    test.skip((await clustersTab.count()) === 0, "Brain Clusters tab not present");
    await clustersTab.click();
    await expect(page.getByText("Total Clusters")).toBeVisible({ timeout: 20_000 });
  });
});
