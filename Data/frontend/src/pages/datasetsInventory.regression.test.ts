import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { DhRow } from "../mocks/datasets-dashboard";
import {
  countDatasetsByFilter,
  filterDatasetRows,
  matchesDatasetFilter,
  reconcileSelection,
} from "./datasets/datasetsInventory";

const here = dirname(fileURLToPath(import.meta.url));

function row(partial: Partial<DhRow> & Pick<DhRow, "id" | "name">): DhRow {
  return {
    description: "",
    source: "Local",
    sourceKind: "local",
    type: "Text",
    size: "1 MB",
    records: "10",
    status: "ready",
    embeddings: { kind: "not_indexed" },
    updated: "1 day ago",
    live: true,
    ...partial,
  };
}

/** Seven HF-shaped rows mirroring the reported live inventory size. */
function sampleInventory(): DhRow[] {
  return [
    row({ id: "1", name: "allenai/c4", sourceKind: "huggingface", source: "Hugging Face", type: "Text", updatedAt: "2026-09-30T12:00:00Z" }),
    row({ id: "2", name: "wikitext", sourceKind: "huggingface", source: "Hugging Face", type: "Text", updatedAt: "2026-09-29T12:00:00Z" }),
    row({
      id: "3",
      name: "local-corpus",
      sourceKind: "local",
      source: "Local",
      status: "offline",
      type: "Document",
      updatedAt: "2026-09-01T12:00:00Z",
    }),
    row({
      id: "4",
      name: "curated-bench",
      sourceKind: "curated",
      source: "Curated",
      type: "Structured",
      updatedAt: "2026-09-28T12:00:00Z",
    }),
    row({
      id: "5",
      name: "hf-code",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Code",
      status: "processing",
      updatedAt: "2026-09-30T10:00:00Z",
    }),
    row({
      id: "6",
      name: "hf-docs",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Document",
      status: "validating",
      updatedAt: "2026-09-20T12:00:00Z",
    }),
    row({
      id: "7",
      name: "hf-multi",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Multimodal",
      updatedAt: "2026-08-01T12:00:00Z",
    }),
  ];
}

describe("datasets inventory filters (live rows)", () => {
  it("All renders every API-mapped record (7)", () => {
    const rows = sampleInventory();
    const filtered = filterDatasetRows(rows, { filter: "all" });
    expect(filtered).toHaveLength(7);
  });

  it("Hugging Face filter keeps only HF sourceKind rows", () => {
    const filtered = filterDatasetRows(sampleInventory(), { filter: "huggingface" });
    expect(filtered).toHaveLength(5);
    expect(filtered.every((r) => r.sourceKind === "huggingface")).toBe(true);
  });

  it("Local / Curated / Offline / Processing filters work", () => {
    const rows = sampleInventory();
    expect(filterDatasetRows(rows, { filter: "local" }).map((r) => r.id)).toEqual(["3"]);
    expect(filterDatasetRows(rows, { filter: "curated" }).map((r) => r.id)).toEqual(["4"]);
    expect(filterDatasetRows(rows, { filter: "offline" }).map((r) => r.id)).toEqual(["3"]);
    expect(filterDatasetRows(rows, { filter: "processing" }).map((r) => r.id).sort()).toEqual([
      "5",
      "6",
    ]);
  });

  it("search filters visible datasets by name without inventing names", () => {
    const filtered = filterDatasetRows(sampleInventory(), { filter: "all", query: "wiki" });
    expect(filtered.map((r) => r.name)).toEqual(["wikitext"]);
  });

  it("pill counts match live row kinds/statuses", () => {
    const counts = countDatasetsByFilter(sampleInventory());
    expect(counts.all).toBe(7);
    expect(counts.huggingface).toBe(5);
    expect(counts.local).toBe(1);
    expect(counts.curated).toBe(1);
    expect(counts.offline).toBe(1);
    expect(counts.processing).toBe(2);
  });

  it("matchesDatasetFilter treats all as pass-through", () => {
    expect(matchesDatasetFilter(sampleInventory()[0], "all")).toBe(true);
  });

  it("Last 24 hours / 7 days / 30 days filter on updatedAt (no placebo)", () => {
    const nowMs = Date.parse("2026-09-30T14:00:00Z");
    const rows = sampleInventory();
    expect(
      filterDatasetRows(rows, { filter: "all", updatedFilter: "Last 24 hours", nowMs }).map((r) => r.id).sort(),
    ).toEqual(["1", "5"]);
    expect(
      filterDatasetRows(rows, { filter: "all", updatedFilter: "Last 7 days", nowMs }).map((r) => r.id).sort(),
    ).toEqual(["1", "2", "4", "5"]);
    expect(
      filterDatasetRows(rows, { filter: "all", updatedFilter: "Last 30 days", nowMs }).map((r) => r.id).sort(),
    ).toEqual(["1", "2", "3", "4", "5", "6"]);
  });

  it("Oldest first sorts ascending by updatedAt", () => {
    const filtered = filterDatasetRows(sampleInventory(), { filter: "all", updatedFilter: "Oldest first" });
    expect(filtered[0]?.id).toBe("7");
    expect(filtered[filtered.length - 1]?.id).toBe("1");
  });

  it("reconcileSelection drops ids missing from visible projection", () => {
    const selected = new Set(["1", "gone", "3"]);
    const next = reconcileSelection(selected, ["1", "2", "3"]);
    expect([...next].sort()).toEqual(["1", "3"]);
  });
});

describe("datasets inventory + activity co-existence regression", () => {
  const pageSrc = readFileSync(join(here, "DatasetsPage.tsx"), "utf8");
  const cssSrc = readFileSync(join(here, "../styles/leviathan-v2.css"), "utf8");

  it("keeps GET /api/datasets inventory list/grid in the page (not replaced by activity)", () => {
    const inventorySrc = readFileSync(join(here, "../components/datasets/DatasetsInventory.tsx"), "utf8");
    expect(pageSrc).toContain("useDatasetsWorkspace");
    expect(pageSrc).toContain("DatasetsInventory");
    expect(inventorySrc).toContain('data-testid="datasets-inventory"');
    expect(pageSrc).toContain("variant=\"v2\"");
  });

  it("renders Dataset Activity as a complementary section after inventory", () => {
    expect(pageSrc).toContain("<DatasetActivityConsole");
    const inventoryAt = pageSrc.indexOf("<DatasetsInventory");
    const activityAt = pageSrc.indexOf("<DatasetActivityConsole");
    expect(inventoryAt).toBeGreaterThan(-1);
    expect(activityAt).toBeGreaterThan(-1);
    expect(inventoryAt).toBeLessThan(activityAt);
  });

  it("does not introduce a DatasetListV2 replacement", () => {
    expect(pageSrc).not.toMatch(/DatasetListV2/);
    expect(pageSrc).not.toMatch(/mockDatasets|DH_DEMO_ROWS/);
  });

  it("V2 CSS keeps inventory / workspace / activity under datasets page namespace", () => {
    expect(cssSrc).toMatch(/\.lv-v2-page--datasets/);
    expect(cssSrc).toMatch(/\.lv-v2-ds-workspace/);
    expect(cssSrc).toMatch(/\.lv-v2-ds-inventory/);
    expect(cssSrc).toMatch(/\.lv-v2-page--datasets\s+\.lv-dac/);
  });

  it("inventory filtering is wired through shared helper (not inlined-away)", () => {
    const wsSrc = readFileSync(join(here, "datasets/useDatasetsWorkspace.ts"), "utf8");
    const widgetsSrc = readFileSync(
      join(here, "../components/datasets/DatasetsBottomWidgets.tsx"),
      "utf8",
    );
    expect(wsSrc).toContain("filterDatasetRows");
    expect(wsSrc).toContain("countDatasetsByFilter");
    expect(wsSrc).toContain("api.listDatasets");
    expect(wsSrc).toContain("/settings?section=opslag");
    expect(widgetsSrc).toContain("Manage Storage");
  });
});
