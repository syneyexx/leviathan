import { test, expect, type Locator } from "@playwright/test";
import { installModelsV2VisualFixture } from "./helpers/modelsV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../../docs/ui_reference/models-v2-reference.png",
);

/**
 * React patches HTMLInputElement's `value` setter to track changes; setting
 * `el.value` directly (even before dispatching an "input" event) is a no-op
 * from React's perspective, so range sliders never fire onChange. Bypass the
 * patched setter the same way Testing Library's fireEvent does.
 */
async function setRangeValue(locator: Locator, value: string): Promise<void> {
  await locator.evaluate((el: HTMLInputElement, val: string) => {
    const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value")?.set;
    nativeSetter?.call(el, val);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }, value);
}

test.describe("Models V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("models loads with LM nav expanded and Screen 1 sections", async ({ page }) => {
    await installModelsV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/models");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open")).toBeVisible();
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Modellen");
    await expect(nav.getByRole("link", { name: "Modellen", exact: true })).toBeVisible();
    await expect(nav.getByRole("link", { name: "LM", exact: true })).toHaveCount(0);

    await expect(page.getByRole("heading", { name: "LM / Models" })).toBeVisible();
    await expect(page.getByText("Beheer, configureer en optimaliseer lokale modellen")).toBeVisible();
    await expect(page.getByRole("button", { name: "Refresh" })).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Model toevoegen" })).toBeVisible();

    await expect(page.getByText("Runtime Provider", { exact: true })).toBeVisible();
    await expect(page.getByText("Hardware Overzicht", { exact: true })).toBeVisible();
    await expect(page.getByText("VRAM Reservering", { exact: true })).toBeVisible();
    await expect(page.getByText("Load Configuratie", { exact: true })).toBeVisible();
    await expect(page.getByText("Multi-GPU Verdelen", { exact: true })).toBeVisible();
    await expect(page.getByText("Geavanceerde Opties", { exact: true })).toBeVisible();
    await expect(page.getByText("Optimalisatie", { exact: true })).toBeVisible();
    await expect(page.getByText("Geschatte Resource Gebruik", { exact: true })).toBeVisible();
    await expect(page.getByText("Verwachte Performance", { exact: true })).toBeVisible();
    await expect(page.getByText("Acties", { exact: true })).toBeVisible();

    const hardwarePanel = page.locator(".lv-v2-panel", { hasText: "Hardware Overzicht" });
    await expect(page.getByText("Qwen2.5-14B-Instruct")).toBeVisible();
    await expect(hardwarePanel.getByText("GTX 1060")).toBeVisible();
    await expect(hardwarePanel.getByText("RTX 5060 Ti")).toBeVisible();
    await expect(page.getByText("LM Studio (Lokaal)")).toBeVisible();
    await expect(page.getByText("Geteste profielen", { exact: true })).toBeVisible();
    await expect(page.locator(".lv-v2-models-table tbody tr")).toHaveCount(4);
    await expect(page.locator(".lv-v2-models-table tr.is-best")).toContainText("26.3");

    // Capability-unsupported fields stay disabled with an explanatory note
    // instead of silently hiding (LM Studio hardcodes seed/cpuThreads/prefixCache).
    await expect(page.getByText("Niet ondersteund door LM Studio").first()).toBeVisible();
    await expect(page.locator(".lv-v2-models-field-row", { hasText: "Seed (optioneel)" }).locator("input")).toBeDisabled();

    await page.waitForTimeout(400);

    await expect(page).toHaveScreenshot("models-v2-1664x936.png", {
      fullPage: false,
      maxDiffPixelRatio: 0.14,
      animations: "disabled",
    });

    expect(errors, `console/page errors: ${errors.join(" | ")}`).toEqual([]);
  });

  test("/models keeps LM group open with Modellen child active", async ({ page }) => {
    await installModelsV2VisualFixture(page);
    await page.goto("/models");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText("LM");
    await expect(page.locator(".lv-v2-nav-child.is-active")).toContainText("Modellen");
  });

  test("models interactions: select model, search, edit config, estimate, optimize, load/unload", async ({
    page,
  }) => {
    await installModelsV2VisualFixture(page);
    await page.goto("/models");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByText("Qwen2.5-14B-Instruct")).toBeVisible();

    // --- select model ---
    const llamaRow = page.getByRole("button", { name: /Llama-3\.2-3B-Instruct/ });
    await llamaRow.click();
    await expect(llamaRow).toHaveAttribute("aria-pressed", "true");
    const qwenRow = page.getByRole("button", { name: /Qwen2\.5-14B-Instruct/ });
    await expect(qwenRow).toHaveAttribute("aria-pressed", "false");

    // --- search ---
    const catalogList = page.locator(".lv-v2-models-catalog__list");
    const search = page.getByPlaceholder("Zoek modellen…");
    await search.fill("Mistral");
    await expect(catalogList.getByText("Mistral-7B-Instruct")).toBeVisible();
    await expect(catalogList.getByText("Qwen2.5-14B-Instruct")).not.toBeVisible();
    await search.fill("");

    // Re-select Qwen (loaded model) for the remaining assertions.
    await qwenRow.click();
    await expect(qwenRow).toHaveAttribute("aria-pressed", "true");

    // --- edit context length + gpu offload ---
    const loadConfigPanel = page.locator(".lv-v2-panel", { hasText: "Load Configuratie" });
    const contextInput = loadConfigPanel.locator(".lv-v2-models-field-row", { hasText: "Context lengte" }).locator("input");
    await contextInput.fill("16384");
    await expect(contextInput).toHaveValue("16384");

    const offloadRow = loadConfigPanel.locator(".lv-v2-models-field-row", { hasText: "GPU offload (algemeen)" });
    const offloadSlider = offloadRow.locator('input[type="range"]');
    await setRangeValue(offloadSlider, "60");
    await expect(offloadRow.locator(".lv-v2-models-range__value")).toHaveText("60%");

    await expect(page.getByText("Er zijn niet-toegepaste wijzigingen")).toBeVisible();

    // --- edit multi-GPU split ---
    const multiGpuPanel = page.locator(".lv-v2-panel", { hasText: "Multi-GPU Verdelen" });
    await multiGpuPanel.locator(".lv-v2-models-field-row select").selectOption({ label: "Handmatig" });
    const gpuSlider = multiGpuPanel.locator(".lv-v2-models-multi-gpu__row").first().locator('input[type="range"]');
    await expect(gpuSlider).toBeEnabled();
    await setRangeValue(gpuSlider, "50");

    // --- estimate ---
    const estimatePanel = page.locator(".lv-v2-panel", { hasText: "Geschatte Resource Gebruik" });
    await expect(estimatePanel.getByText("Nog niet geschat")).toBeVisible();
    await page.getByRole("button", { name: "Eerst schatten (zonder laden)" }).click();
    await expect(estimatePanel.getByText("10.2 GB")).toBeVisible({ timeout: 10_000 });

    // --- optimize (fixture) ---
    const optimizePanel = page.locator(".lv-v2-panel", { hasText: "Optimalisatie" });
    await optimizePanel.getByRole("button", { name: "Automatisch optimaliseren" }).click();
    await expect(page.getByRole("status")).toContainText("Optimalisatie voltooid", { timeout: 10_000 });
    await expect(page.locator(".lv-v2-models-table tbody tr")).toHaveCount(4);
    await expect(page.locator(".lv-v2-models-table tr.is-best")).toBeVisible();

    // --- load / unload (fixture) — Llama starts unloaded ---
    await llamaRow.click();
    await expect(llamaRow).toHaveAttribute("aria-pressed", "true");
    const unloadBtn = page.getByRole("button", { name: "Model ontladen" });
    await expect(unloadBtn).toBeDisabled();

    await page.getByRole("button", { name: /Model laden in/ }).click();
    await expect(page.getByRole("status")).toContainText("Model geladen", { timeout: 10_000 });
    await expect(unloadBtn).toBeEnabled({ timeout: 10_000 });

    await unloadBtn.click();
    await expect(page.getByRole("status")).toContainText("Model ontladen", { timeout: 10_000 });
    await expect(unloadBtn).toBeDisabled({ timeout: 10_000 });
  });
});

void REFERENCE;
