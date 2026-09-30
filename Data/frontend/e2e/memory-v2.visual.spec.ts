import { test, expect } from "@playwright/test";
import { installMemoryV2VisualFixture } from "./helpers/memoryV2Visual";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REFERENCE = path.resolve(
  __dirname,
  "../../docs/ui_reference/memory-v2-reference.png",
);

test.describe("Memory V2 visual", () => {
  test.use({
    viewport: { width: 1664, height: 936 },
    deviceScaleFactor: 1,
  });

  test("geheugen loads with Onderzoek & Kennis expanded and Screen 1 sections", async ({
    page,
  }) => {
    await installMemoryV2VisualFixture(page);
    const errors: string[] = [];
    page.on("pageerror", (err) => errors.push(err.message));
    page.on("console", (msg) => {
      if (msg.type() === "error") errors.push(msg.text());
    });

    await page.goto("/memory");
    await expect(page.locator(".lv-v2")).toBeVisible({ timeout: 20_000 });

    const nav = page.getByRole("navigation", { name: "Hoofdmenu" });
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-item__label")).toContainText(
      /Onderzoek|Kennis|Research/i,
    );
    await expect(page.locator(".lv-v2-nav-group.is-open .lv-v2-nav-child.is-active")).toContainText(
      "Geheugen",
    );
    await expect(nav.getByRole("link", { name: "Geheugen", exact: true })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Geheugen", exact: true })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Onderzoek & Kennis / Geheugen" })).toBeVisible();
    await expect(page.getByText("Totaal Geheugen", { exact: true })).toBeVisible();
    await expect(page.getByText("1.284.632").or(page.getByText("1,284,632"))).toBeVisible();
    await expect(page.getByText("Vector Embeddings", { exact: true })).toBeVisible();
    await expect(page.getByText("Opslag Gebruik", { exact: true })).toBeVisible();
    await expect(page.locator(".lv-v2-metric-card__label", { hasText: "Bronnen" })).toBeVisible();
    await expect(page.locator(".lv-v2-metric-card__label", { hasText: "Zoekopdrachten" })).toBeVisible();

    await expect(page.getByRole("heading", { name: "Geheugen Zoeken" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Geheugen Items" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Geheugen Analytics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Semantic Index" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Geheugen Types" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Geheugen Beheer" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Automatische Verwerking" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recente Activiteit" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Top Bronnen" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Meest Gezochte Topics" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Recent Toegevoegde" })).toBeVisible();

    // Honest provider — not hardcoded ChromaDB unless configured.
    const semPanel = page.locator(".lv-v2-panel", { hasText: "Semantic Index" });
    await expect(semPanel.getByText("ChromaDB")).toHaveCount(0);
    await expect(semPanel.getByText("sqlite_control_memory_embeddings")).toBeVisible();
    await expect(semPanel.getByText("sentence_transformers")).toBeVisible();

    await expect(page.getByRole("button", { name: "Zoeken" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Index optimaliseren" })).toBeVisible();

    // Interaction: search
    await page.getByPlaceholder(/Stel je vraag|zoek in het geheugen/i).fill("Bitcoin");
    await page.getByRole("button", { name: "Zoeken" }).click();
    await expect(page.getByText(/Bitcoin halving/i).first()).toBeVisible();

    // Create note modal
    await page.getByRole("button", { name: "+ Nieuwe notitie" }).first().click();
    await expect(page.getByRole("heading", { name: "Nieuwe notitie" })).toBeVisible();
    await page.getByRole("button", { name: "Annuleren" }).click();

    // Screenshot for visual regression loop
    await page.screenshot({
      path: path.resolve(__dirname, "../../docs/ui_reference/_memory-v2-actual.png"),
      fullPage: false,
    });

    // Soft check reference exists for humans; do not fail if binary drift.
    const fs = await import("node:fs");
    expect(fs.existsSync(REFERENCE)).toBeTruthy();

    const critical = errors.filter(
      (e) => !/favicon|ResizeObserver|Non-Error/i.test(e),
    );
    expect(critical).toEqual([]);
  });
});
