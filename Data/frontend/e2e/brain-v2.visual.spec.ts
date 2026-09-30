import { test, expect } from "@playwright/test";
import { installBrainV2VisualFixture } from "./helpers/brainV2Visual";
import { installDashboardV2VisualFixture } from "./helpers/dashboardV2Visual";
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
    reducedMotion: "reduce",
  });

  // Keep screenshot typography independent of external font availability.
  test.beforeEach(async ({ page }) => {
    await page.route("https://fonts.googleapis.com/**", route => route.fulfill({contentType: "text/css", body: ""}));
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
    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Brain");
    await expect(nav.getByRole("link", { name: "Research", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Geheugen", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Knowledge Library", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Evidence Vault", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Datasets", exact: true })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Leviathan Brain" })).toBeVisible();
    await expect(page.getByText("Actieve Nodes", { exact: true })).toBeVisible();
    await expect(page.getByText("Kennis Links", { exact: true })).toBeVisible();
    await expect(page.getByText("Geheugen Clusters", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Redenering Jobs", { exact: true })).toBeVisible();
    await expect(page.getByText("Bewijs Items", { exact: true })).toBeVisible();
    await expect(page.getByText("Kennis Netwerk", { exact: true })).toBeVisible();
    await expect(page.getByText("Geselecteerde Node", { exact: true })).toBeVisible();
    await expect(page.getByText("Recente Kennis Activiteit", { exact: true })).toBeVisible();
    await expect(page.getByText("Entity Types", { exact: true })).toBeVisible();
    await expect(page.getByText("Redenering Queue", { exact: true })).toBeVisible();
    await expect(page.getByText("Systeem Gezondheid", { exact: true })).toBeVisible();
    await expect(page.getByText("System Status", { exact: true })).toBeVisible();

    // Fixture KPIs settle (nl-NL grouping)
    await expect(page.getByText("58", {exact:true}).first()).toBeVisible({
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

  test("/brain keeps Onderzoek & Kennis group open with Brain child active", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Onderzoek & Kennis",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Brain");
  });

  test("Dashboard submenu remains intact on /", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    await page.goto("/");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Dashboard");
    await expect(page.getByRole("link", { name: "Taken", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Hoofdmenu" }).getByRole("button", { name: /Hades AI/i }),
    ).toHaveCount(0);
  });
});

void REFERENCE;
