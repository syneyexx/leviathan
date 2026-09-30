import { test, expect } from "@playwright/test";
import { installDashboardV2VisualFixture } from "./helpers/dashboardV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/dashboard-v2-reference.png",
);

test.describe("Dashboard V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("dashboard loads with expanded Dashboard nav and Screen 1 sections", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Dashboard");
    await expect(page.getByRole("link", { name: "Taken", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Chat", exact: true })).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Hoofdmenu" }).getByRole("button", { name: /^Dashboard$/i }),
    ).toBeVisible();
    await expect(
      page.getByRole("navigation", { name: "Hoofdmenu" }).getByRole("button", { name: /Hades AI/i }),
    ).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "Welkom bij Leviathan" })).toBeVisible();
    await expect(page.getByText("Systeem Status")).toBeVisible();
    await expect(page.getByText("Systeem Gezondheid")).toBeVisible();
    await expect(page.getByText("Actieve Workers")).toBeVisible();
    await expect(page.getByText("Taak Queue")).toBeVisible();
    await expect(page.getByText("Recente Activiteiten")).toBeVisible();
    await expect(page.getByText("Onderzoek Overzicht")).toBeVisible();
    await expect(page.getByText("Trading Overzicht")).toBeVisible();
    await expect(page.getByText("Data Ingestie")).toBeVisible();
    await expect(page.getByText("GPU & Hardware")).toBeVisible();
    await expect(page.getByText("Verwachte Performance")).toBeVisible();
    await expect(page.getByText("System Status")).toBeVisible();

    // Wait for fixture metrics to settle.
    await expect(page.getByText("Operationeel")).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(500);

    await expect(page).toHaveScreenshot("dashboard-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.08,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/chat keeps Dashboard group open with Chat active", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Dashboard",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Chat");
  });

  test("/tasks keeps Dashboard group open with Taken active", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    await page.goto("/tasks");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Taken");
  });
});

// Reference path documented for human/CI comparison workflows.
void REFERENCE;
