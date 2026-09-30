import { test, expect } from "@playwright/test";
import { installChatV2VisualFixture } from "./helpers/chatV2Visual";
import { installDashboardV2VisualFixture } from "./helpers/dashboardV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/chat-v2-reference.png",
);

test.describe("Chat V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("chat loads with Dashboard nav expanded and Screen 1 sections", async ({ page }) => {
    await installChatV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/chat");
    await page.waitForFunction(() => document.fonts?.ready?.then(() => true) ?? true);
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-page--chat")).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Dashboard",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Chat");
    await expect(nav.getByRole("link", { name: "Taken", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Dashboard", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "Reasoning", exact: true })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Prompts", exact: true })).toHaveCount(0);
    await expect(nav.getByRole("link", { name: "Evaluations", exact: true })).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "Hades AI / Chat" })).toBeVisible();
    await expect(page.getByText("Geselecteerd Model", { exact: true })).toBeVisible();
    await expect(page.getByText("AI Agent", { exact: true })).toBeVisible();
    await expect(page.getByText("Reasoning Modus", { exact: true })).toBeVisible();
    await expect(page.getByText("Tools & Integraties", { exact: true })).toBeVisible();
    await expect(page.getByText("Qwen2.5-14B-Instruct").first()).toBeVisible();
    await expect(page.getByText("Hades (Standaard)").first()).toBeVisible();
    await expect(page.getByText("Diep Redeneren").first()).toBeVisible();
    await expect(page.getByText("Gesprekshistorie")).toBeVisible();
    await expect(page.getByText("AI infrastructuur strategie").first()).toBeVisible();
    await expect(page.getByText("Context & Geheugen")).toBeVisible();
    await expect(page.getByText("Bronnen & Verificatie")).toBeVisible();
    await expect(page.getByText("Systeem Metrics")).toBeVisible();
    await expect(page.getByText("NVIDIA Runtime Docs")).toBeVisible();
    await expect(page.getByPlaceholder("Stel een vraag aan Hades AI...")).toBeVisible();

    // Fixture conversation must hydrate before screenshot so quick prompts stay hidden
    // and date groups resolve against frozen now (Vandaag / Gisteren / Vorige 7 dagen).
    await expect(page.locator(".lv-v2-msg")).toHaveCount(2, { timeout: 15_000 });
    await expect(page.locator(".lv-v2-quick-prompts")).toHaveCount(0);
    await expect(page.locator(".lv-v2-chat-group__label")).toHaveText([
      /Vandaag/i,
      /Gisteren/i,
      /Vorige 7 dagen/i,
    ]);
    await expect(page.getByText("GPU 0 - GTX 1060").first()).toBeVisible();
    await expect(page.getByText("GPU 1 - RTX 5060 Ti").first()).toBeVisible();

    await page.waitForTimeout(600);

    await expect(page).toHaveScreenshot("chat-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/chat keeps Dashboard group open with Chat child active", async ({ page }) => {
    await installChatV2VisualFixture(page);
    await page.goto("/chat");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      "Dashboard",
    );
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Chat");
  });

  test("Dashboard submenu remains intact on /", async ({ page }) => {
    await installDashboardV2VisualFixture(page);
    await page.goto("/");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Dashboard");
    await expect(page.getByRole("link", { name: "Taken", exact: true })).toBeVisible();
  });
});

void REFERENCE;
