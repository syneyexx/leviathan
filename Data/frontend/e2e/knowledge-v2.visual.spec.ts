import { expect, test } from "@playwright/test";
import { installKnowledgeLibraryV2VisualFixture } from "./helpers/knowledgeLibraryV2Visual";

test.describe("Knowledge Library V2 visual", () => {
  test("screen 1 matches reference composition", async ({ page }) => {
    await page.setViewportSize({ width: 1664, height: 936 });
    await installKnowledgeLibraryV2VisualFixture(page);
    await page.goto("/knowledge");

    await expect(page.getByRole("heading", { name: "Knowledge Library" })).toBeVisible();
    await expect(page.getByText("Totale Bronnen")).toBeVisible();
    await expect(page.getByText("Totale Grootte")).toBeVisible();
    await expect(page.getByText("Bron Types").first()).toBeVisible();
    await expect(page.getByText("Embedding Status")).toBeVisible();
    await expect(page.getByText("Laatste Ingestie")).toBeVisible();

    await expect(page.getByRole("button", { name: "Bibliotheek" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Ingestie" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Bronnen" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Vector Search" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Kennis Grafiek" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Analyses" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Datasets" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Notities" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Instellingen" })).toBeVisible();

    await expect(page.getByText("Tags").first()).toBeVisible();
    await expect(page.getByRole("heading", { name: "Geselecteerde Bron" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Preview" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Metadata" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Inhoud" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Embeddings" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Relaties" })).toBeVisible();
    await expect(page.getByText("Ingestie Voortgang")).toBeVisible();
    await expect(page.getByText("Recente Ingesties")).toBeVisible();
    await expect(page.getByText(/Gerelateerde Bronnen/)).toBeVisible();

    await expect(page).toHaveScreenshot("knowledge-library-v2-screen1.png", {
      animations: "disabled",
      caret: "hide",
    });
  });
});
