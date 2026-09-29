import { test, expect } from "@playwright/test";
import { installResearchV2VisualFixture } from "./helpers/researchV2Visual";
import { installDashboardV2VisualFixture } from "./helpers/dashboardV2Visual";
import { installBrainV2VisualFixture } from "./helpers/brainV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/research-v2-reference.png",
);

test.describe("Research V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("research loads with Research nav expanded and Screen 1 sections", async ({ page }) => {
    await installResearchV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/research");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Research");
    await expect(nav.getByRole("link", { name: "Research", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Brain", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Geheugen", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Knowledge Library", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Evidence Vault", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Datasets", exact: true })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Leviathan Research" })).toBeVisible();
    await expect(page.getByText("Actieve Onderzoeken", { exact: true })).toBeVisible();
    await expect(page.getByText("Onderzoeks Agents", { exact: true })).toBeVisible();
    await expect(page.getByText("Kennisbronnen", { exact: true })).toBeVisible();
    await expect(page.getByText("Web Bronnen", { exact: true })).toBeVisible();
    await expect(page.getByText("Documenten", { exact: true })).toBeVisible();
    await expect(page.getByText("Recente Onderzoeken", { exact: true })).toBeVisible();
    await expect(page.getByText("Nieuw Onderzoek", { exact: true })).toBeVisible();
    await expect(page.getByText("Onderzoeks Templates", { exact: true })).toBeVisible();
    await expect(page.getByText("Onderzoeks Agenten", { exact: true })).toBeVisible();
    await expect(page.getByText("Kennisbron Status", { exact: true })).toBeVisible();
    await expect(page.getByText("Onderzoeks Statistieken", { exact: true })).toBeVisible();
    await expect(page.getByText("System Status", { exact: true })).toBeVisible();

    await expect(page.getByText("Private LLM infrastructuur analyse").first()).toBeVisible({
      timeout: 15_000,
    });

    await page.waitForTimeout(600);

    await expect(page).toHaveScreenshot("research-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("research interactions: search, filter, template, type, advanced, refresh", async ({
    page,
  }) => {
    await installResearchV2VisualFixture(page);
    await page.goto("/research");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    // Start from overview: clear selected run if fixture auto-selected active project
    const back = page.getByRole("button", { name: "Terug naar overzicht" });
    if (await back.isVisible().catch(() => false)) {
      await back.click();
    }

    await expect(page.getByText("Nieuw Onderzoek", { exact: true })).toBeVisible();

    await page.getByPlaceholder("Zoek onderzoeken…").fill("Vector");
    await expect(page.getByText("Vector database vergelijking")).toBeVisible();

    await page.getByRole("tab", { name: /Afgerond/ }).click();
    await expect(page.getByText("Markt analyse AI hardware 2025")).toBeVisible();

    await page.getByRole("tab", { name: /Alle/ }).click();
    await page.getByPlaceholder("Zoek onderzoeken…").fill("");

    await page.getByRole("button", { name: "Deep Research", exact: true }).click();
    await expect(page.getByRole("button", { name: "Deep Research", exact: true })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await page.getByRole("button", { name: "Gebruik" }).first().click();

    await page.getByRole("button", { name: /Geavanceerde opties/ }).click();
    await expect(page.getByRole("tab", { name: "Files", exact: true })).toBeVisible();

    await page.getByRole("button", { name: "Refresh" }).click();
    await expect(page.locator(".lv-v2")).toBeVisible();

    await page.getByText("Private LLM infrastructuur analyse").first().click();
    await expect(page.getByText("Timeline", { exact: true })).toBeVisible({ timeout: 10_000 });
  });

  test("/research keeps Research group open with Research child active", async ({ page }) => {
    await installResearchV2VisualFixture(page);
    await page.goto("/research");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Research",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Research");
  });

  test("Brain submenu remains intact on /brain", async ({ page }) => {
    await installBrainV2VisualFixture(page);
    await page.goto("/brain");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Brain");
  });

  test("Dashboard remains intact on /", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    await page.goto("/");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Dashboard");
  });
});

void REFERENCE;
