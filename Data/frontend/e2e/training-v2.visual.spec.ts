import { test, expect } from "@playwright/test";
import { installTrainingV2VisualFixture } from "./helpers/trainingV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/training-v2-reference.png",
);

test.describe("Training V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("training loads with LLM nav expanded and Screen 1 sections", async ({ page }) => {
    await installTrainingV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/training");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LLM");
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText(
      "Training",
    );
    await expect(nav.getByRole("link", { name: "Training", exact: true })).toBeVisible();
    // Training lives under LLM — no standalone top-level Training owner.
    await expect(nav.locator("> .lv-v2-nav-item", { hasText: "Training" })).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "LLM / Model Training" })).toBeVisible();
    await expect(
      page.getByText("Train, fine-tune en optimaliseer lokale taalmodellen en agents."),
    ).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Nieuwe training" })).toBeVisible();

    await expect(page.getByText("Training Engine", { exact: true })).toBeVisible();
    await expect(page.getByText("Leviathan Trainer").first()).toBeVisible();
    await expect(page.getByText("Hardware Overzicht", { exact: true })).toBeVisible();
    await expect(page.getByText("Trainings Statistieken", { exact: true })).toBeVisible();
    await expect(page.getByText("Dataset Bronnen", { exact: true })).toBeVisible();
    await expect(page.getByText("Models voor Training", { exact: true })).toBeVisible();
    await expect(page.getByText("Trainings Parameters", { exact: true })).toBeVisible();
    await expect(page.getByText("Training Runs", { exact: true })).toBeVisible();
    await expect(page.getByText("Live Trainingsgrafieken", { exact: true })).toBeVisible();
    await expect(page.getByText("Huidige Run Details", { exact: true })).toBeVisible();
    await expect(page.getByText("Checkpoints", { exact: true })).toBeVisible();

    // Engine is Leviathan Trainer — not LM Studio as trainer.
    const enginePanel = page.locator(".lv-v2-panel", { hasText: "Training Engine" });
    await expect(enginePanel.getByText("Leviathan Trainer")).toBeVisible();
    await expect(enginePanel.getByText("LM Studio")).toHaveCount(0);

    // Hardware fixture GPUs
    const hardwarePanel = page.locator(".lv-v2-panel", { hasText: "Hardware Overzicht" });
    await expect(hardwarePanel.getByText("GTX 1060")).toBeVisible();
    await expect(hardwarePanel.getByText("RTX 3060 Ti")).toBeVisible();

    // Trainable models only — GGUF filtered out
    await expect(page.getByText("Qwen2.5-14B")).toBeVisible();
    await expect(page.getByText("Llama-3.2-3B")).toBeVisible();
    await expect(page.getByText("Qwen2.5-14B-Instruct Q4_K_M")).toHaveCount(0);

    // Method selector has no fixture option
    const methodSelect = page.locator(".lv-v2-panel", { hasText: "Trainings Parameters" }).locator("select").first();
    await expect(methodSelect.locator('option[value="fixture"]')).toHaveCount(0);
    await expect(methodSelect.locator('option[value="sft"]')).toHaveCount(1);

    // Honest actions — Stop present for running job, no Pause
    await expect(page.getByRole("button", { name: "Stop" }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: /Pause|Pauze/i })).toHaveCount(0);

    // Real metrics language — no fake accuracy chrome in graphs
    await expect(page.getByRole("button", { name: "Loss" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Perplexity" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Accuracy" })).toHaveCount(0);

    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("training-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/training keeps LLM group open with Training child active", async ({ page }) => {
    await installTrainingV2VisualFixture(page);
    await page.goto("/training");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LLM");
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Training");
  });

  test("training interactions: select model/dataset, edit config, open preflight", async ({ page }) => {
    await installTrainingV2VisualFixture(page);
    await page.goto("/training");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    const llama = page.getByRole("button", { name: /Llama-3\.2-3B/ });
    await llama.click();
    await expect(llama).toHaveAttribute("aria-pressed", "true");

    const sharegpt = page.getByRole("button", { name: /ShareGPT NL/ });
    await sharegpt.click();
    await expect(sharegpt).toHaveAttribute("aria-pressed", "true");

    const config = page.locator(".lv-v2-panel", { hasText: "Trainings Parameters" });
    await config.locator("select").first().selectOption("lora");
    await expect(config.getByText("LoRA rank")).toBeVisible();

    await page.getByRole("button", { name: "+ Nieuwe training" }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    await expect(page.getByText("Preflight")).toBeVisible();
    await expect(page.getByRole("button", { name: "Start training" })).toBeVisible();
  });
});

void REFERENCE;
