import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import {
  assertDatasetManagementFrozenClockContract,
  installDatasetManagementV2VisualFixture,
} from "./helpers/datasetManagementV2Visual";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../docs/ui_reference/dataset-management-llm-v2-reference.jpg",
);

test.describe("Dataset Management V2 visual", () => {
  test.use({
    viewport: { width: 1672, height: 941 },
    deviceScaleFactor: 1,
  });

  test("frozen clock contract", () => {
    expect(assertDatasetManagementFrozenClockContract()).toBe(true);
  });

  test("dataset management loads with LLM nav expanded and Screen 1 sections", async ({ page }) => {
    await installDatasetManagementV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/dataset-management");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-page--dataset-management")).toBeVisible();

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LLM");
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText(
      /Dataset Manager|Dataset Management/,
    );
    await expect(nav.getByRole("link", { name: /Dataset Manager|Dataset Management/ })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Dataset Management" }).first()).toBeVisible();
    await expect(page.getByText("ORGANISEER. VERRIJK. CONTROLEER. VERSNEL.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Dataset toevoegen" }).first()).toBeVisible();

    await expect(page.getByText("Totaal Datasets")).toBeVisible();
    await expect(page.getByText("Totaal Samples")).toBeVisible();
    await expect(page.getByText("Opslag Gebruikt")).toBeVisible();
    await expect(page.getByText("Actieve Imports")).toBeVisible();
    await expect(page.getByText("Validatie Issues")).toBeVisible();
    await expect(page.getByText("Catalog Status")).toBeVisible();

    await expect(page.getByRole("heading", { name: "Dataset Acties" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Dataset Services" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Dataset bibliotheek" })).toBeVisible();
    await expect(page.getByText("nl_wiki_2024").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Details" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Voorbeeld data" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Opslag" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Sla metagegevens op" })).toBeVisible();
    await expect(page.getByText(/Data is ruwe potentie/)).toBeVisible();

    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("dataset-management-v2-1672x941.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/dataset-management keeps LLM group open with Dataset Manager child active", async ({
    page,
  }) => {
    await installDatasetManagementV2VisualFixture(page);
    await page.goto("/dataset-management");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LLM");
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText(/Dataset Manager/);
  });

  test("library selection and metadata edit affordance", async ({ page }) => {
    await installDatasetManagementV2VisualFixture(page);
    await page.goto("/dataset-management");
    await expect(page.locator(".lv-v2-page--dataset-management")).toBeVisible({ timeout: 20_000 });

    const codeRow = page.locator(".lv-v2-dm-table tbody tr", { hasText: "code_instructions_v2" });
    await codeRow.click();
    await expect(codeRow).toHaveClass(/is-active/);
    await expect(page.getByText("code_instructions_v2").first()).toBeVisible();

    await page.getByRole("button", { name: "Metagegevens bewerken" }).click();
    await expect(page.getByText("Weergavenaam")).toBeVisible();
    await expect(page.getByRole("button", { name: "Opslaan" })).toBeVisible();
  });
});

void REFERENCE;
