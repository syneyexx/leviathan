import { test, expect } from "@playwright/test";
import { installBrainV2VisualFixture } from "./helpers/brainV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/brain-v2-reference.png",
);

test.describe("Brain V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("brain loads with Research nav expanded and Screen 1 sections", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Brain");
    await expect(page.getByRole("link", { name: "Research", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Geheugen", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Knowledge Library", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Evidence Vault", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Datasets", exact: true })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Leviathan Brain" })).toBeVisible();
    await expect(page.getByText("Actieve Nodes")).toBeVisible();
    await expect(page.getByText("Kennis Links")).toBeVisible();
    await expect(page.getByText("Geheugen Clusters").first()).toBeVisible();
    await expect(page.getByText("Redenering Jobs")).toBeVisible();
    await expect(page.getByText("Bewijs Items")).toBeVisible();
    await expect(page.getByText("Kennis Netwerk")).toBeVisible();
    await expect(page.getByText("Geselecteerde Node")).toBeVisible();
    await expect(page.getByText("Recente Kennis Activiteit")).toBeVisible();
    await expect(page.getByText("Entity Types")).toBeVisible();
    await expect(page.getByText("Redenering Queue")).toBeVisible();
    await expect(page.getByText("Systeem Gezondheid")).toBeVisible();
    await expect(page.getByText("System Status")).toBeVisible();

    // Fixture KPIs settle
    await expect(page.getByText("12.842").or(page.getByText("12,842"))).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByText("Bitcoin").first()).toBeVisible();

    await page.waitForTimeout(600);

    await expect(page).toHaveScreenshot("brain-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.12,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/brain keeps Research group open with Brain child active", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Research",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Brain");
  });

  test("Dashboard submenu remains intact on /", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Dashboard");
    await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Taken", exact: true })).toBeVisible();
  });
});

void REFERENCE;
