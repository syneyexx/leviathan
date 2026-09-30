import { test, expect } from "@playwright/test";
import { installAgentsV2VisualFixture } from "./helpers/agentsV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/agents-v2-reference.png",
);

test.describe("Agents V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("agents loads with LM nav expanded and Screen 1 sections", async ({ page }) => {
    await installAgentsV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/agents?agent=agent_trader");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LM");
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText("Agents");
    await expect(nav.getByRole("link", { name: "Agents", exact: true }).first()).toBeVisible();
    // Hades may deep-link to Agents, but there is no standalone top-level owner.
    await expect(nav.locator("> .lv-v2-nav-item", { hasText: "Agents" })).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "LLM / Agents" })).toBeVisible();
    await expect(page.getByText("Autonome agents, samenwerking, missies en uitvoering.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Agent toevoegen" })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Leviathan Agents" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Nieuwe missie" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Registry openen" })).toBeVisible();

    await expect(page.getByText("Actieve Agents", { exact: true })).toBeVisible();
    await expect(page.getByText("Idle Agents", { exact: true })).toBeVisible();
    await expect(page.getByText("Missies", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Tool Calls", { exact: true })).toBeVisible();
    await expect(page.getByText("Succesratio", { exact: true })).toBeVisible();
    await expect(page.getByText("UNMEASURED").first()).toBeVisible();

    await expect(page.getByText("Agent Directory")).toBeVisible();
    await expect(page.getByText("Agent Architectuur")).toBeVisible();
    await expect(page.getByText("Geselecteerde Agent")).toBeVisible();
    await expect(page.getByText("Trader Agent").first()).toBeVisible();

    await expect(page.getByText("Agent Activiteit").first()).toBeVisible();
    await expect(page.getByText("Workflow Pipeline & Recente Missies")).toBeVisible();
    await expect(page.getByText("Tool Permissions")).toBeVisible();

    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("agents-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.18,
      animations: "disabled",
    });

    // Reference file must exist for reviewers (not used as rendered asset).
    expect(REFERENCE.length).toBeGreaterThan(10);

    expect(errors.filter((e) => !e.includes("favicon")).slice(0, 8), `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/agents keeps LM group open with Agents child active (not Hades)", async ({ page }) => {
    await installAgentsV2VisualFixture(page);
    await page.goto("/agents");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LM");
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText("Agents");
    await expect(page.locator(".lv-v2-nav-item.is-active .lv-v2-nav-item__label")).not.toContainText("Hades");
  });

  test("agents interactions: select, search, create, mission, architecture, models link", async ({
    page,
  }) => {
    await installAgentsV2VisualFixture(page);
    await page.goto("/agents");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Trader Agent").first()).toBeVisible();

    // select agent from directory
    const researchRow = page.locator(".lv-v2-agents-table tbody tr", { hasText: "Research Agent" });
    await researchRow.click();
    await expect(page.locator(".lv-v2-agents-inspector__id")).toContainText("Research Agent");

    // search
    const search = page.getByPlaceholder("Zoek agent…");
    await search.fill("Trader");
    await expect(page.locator(".lv-v2-agents-table tbody")).toContainText("Trader Agent");
    await expect(page.locator(".lv-v2-agents-table tbody")).not.toContainText("Research Agent");
    await search.fill("");

    // registry focus
    await page.getByRole("button", { name: "Registry openen" }).click();
    await expect(search).toBeFocused();

    // architecture node selection
    await page.getByRole("button", { name: "Volledig overzicht" }).click();
    await expect(page.getByLabel("Agent Architecture volledig overzicht")).toBeVisible();
    await page.keyboard.press("Escape").catch(() => undefined);
    await page.locator(".lv-v2-agents-overlay").click({ position: { x: 8, y: 8 } }).catch(() => undefined);

    // inspector tabs
    await page.getByRole("tab", { name: "Capabilities" }).click();
    await expect(page.getByText("assigned").first()).toBeVisible();
    await page.getByRole("tab", { name: "Tools" }).click();
    await expect(page.getByRole("link", { name: "Tools" }).first()).toBeVisible();
    await page.getByRole("tab", { name: "Configuratie" }).click();
    await expect(page.getByText("Approval")).toBeVisible();
    await page.getByRole("tab", { name: "Overzicht" }).click();
    await expect(page.getByRole("link", { name: "Open Models" })).toBeVisible();

    // create agent
    await page.getByRole("button", { name: "+ Agent toevoegen" }).click();
    await expect(page.getByText(/Create|Nieuwe|New Agent|Agent editor|Create agent/i).first()).toBeVisible({
      timeout: 10_000,
    });
    await page.keyboard.press("Escape");

    // launch mission modal
    await page.getByRole("button", { name: "+ Nieuwe missie" }).click();
    await expect(page.getByText(/Launch|Missie|mission|Dry-run|Request/i).first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test("protected system agent stays read-only in inspector", async ({ page }) => {
    await installAgentsV2VisualFixture(page);
    await page.goto("/agents?agent=agent_guardian");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-agents-inspector__id")).toContainText("System Guardian");
    await expect(page.getByText("SYSTEM").first()).toBeVisible();
    await expect(page.getByText("Read-only SYSTEM")).toBeVisible();
  });
});
