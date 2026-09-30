import { test, expect } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { installDatasetManagementV2VisualFixture } from "./helpers/datasetManagementV2Visual";
import { DATASET_MGMT_V2_VISUAL_FROZEN_ISO } from "../src/mocks/datasetManagementV2VisualFixture";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../docs/ui_reference/dataset-management-llm-v2-reference.png",
);

/**
 * Dataset Management V2 visual regression — exact Screen 1 viewport 1672×941.
 * Fixture-only data via installDatasetManagementV2VisualFixture (route mocks +
 * frozen clock). Conceptual compare target: dataset-management-llm-v2-reference.png
 */
test.describe("Dataset Management V2 visual", () => {
  test.use({
    viewport: { width: 1672, height: 941 },
    deviceScaleFactor: 1,
  });

  test("frozen clock matches Screen 1 reference", () => {
    expect(DATASET_MGMT_V2_VISUAL_FROZEN_ISO).toBe("2025-05-25T14:38:12.000Z");
  });

  test("dataset-management loads with LLM nav expanded and Screen 1 sections", async ({
    page,
  }) => {
    await installDatasetManagementV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/dataset-management");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-page--dataset-mgmt")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      /LLM|LM/i,
    );
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText(
      /Dataset Manager|Dataset Management/i,
    );
    await expect(nav.getByRole("link", { name: /Dataset Manager/i })).toBeVisible();

    await expect(page.locator(".lv-v2-hero--dm")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Dataset Management", exact: true })).toBeVisible();

    await expect(page.locator(".lv-v2-dm-metrics")).toBeVisible();
    await expect(page.getByText("Totaal Datasets", { exact: true })).toBeVisible();
    await expect(page.getByText("248", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("48.7M", { exact: true })).toBeVisible();
    await expect(page.getByText("Actieve Imports", { exact: true })).toBeVisible();
    await expect(page.getByText("Validatie Issues", { exact: true })).toBeVisible();
    await expect(page.getByText("17", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("Gezond").first()).toBeVisible();

    await expect(page.getByRole("heading", { name: "Dataset bibliotheek" })).toBeVisible();
    await expect(page.getByText("nl_wiki_2024").first()).toBeVisible();
    await expect(page.getByText("code_instructions_v2").first()).toBeVisible();

    await expect(page.locator(".lv-v2-dm-details")).toBeVisible();
    await expect(page.locator(".lv-v2-dm-services")).toBeVisible();
    await expect(page.getByText("Embedding Pipeline")).toBeVisible();
    await expect(page.getByText("Indexing Service")).toBeVisible();

    await expect(
      page.locator(".lv-v2-dm-activity, .lv-dac").first(),
    ).toBeVisible();

    await expect(page.locator(".lv-v2-dm-storage")).toBeVisible();
    await expect(page.getByText("Datasets").first()).toBeVisible();
    await expect(page.locator(".lv-v2-dm-tags")).toBeVisible();
    await expect(page.getByText(/nl \(48\)/)).toBeVisible();

    const fs = await import("node:fs");
    const outDir = path.resolve(__dirname, "../test-results");
    fs.mkdirSync(outDir, { recursive: true });
    const screenshotPath = path.join(outDir, "dataset-management-v2-screen1.png");
    await page.screenshot({ path: screenshotPath, fullPage: false });
    // Conceptual visual compare target (human / future pixel-diff):
    // Data/docs/ui_reference/dataset-management-llm-v2-reference.png
    expect(fs.existsSync(REFERENCE)).toBeTruthy();
    expect(fs.existsSync(screenshotPath)).toBeTruthy();

    const critical = errors.filter((e) => !/favicon|ResizeObserver|Non-Error/i.test(e));
    expect(critical).toEqual([]);
  });
});
