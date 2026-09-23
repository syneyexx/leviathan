import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { DhRow } from "../mocks/datasets-dashboard";
import {
  countDatasetsByFilter,
  filterDatasetRows,
  matchesDatasetFilter,
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
    row({ id: "1", name: "allenai/c4", sourceKind: "huggingface", source: "Hugging Face", type: "Text" }),
    row({ id: "2", name: "wikitext", sourceKind: "huggingface", source: "Hugging Face", type: "Text" }),
    row({
      id: "3",
      name: "local-corpus",
      sourceKind: "local",
      source: "Local",
      status: "offline",
      type: "Document",
    }),
    row({
      id: "4",
      name: "curated-bench",
      sourceKind: "curated",
      source: "Curated",
      type: "Structured",
    }),
    row({
      id: "5",
      name: "hf-code",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Code",
      status: "processing",
    }),
    row({
      id: "6",
      name: "hf-docs",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Document",
      status: "validating",
    }),
    row({
      id: "7",
      name: "hf-multi",
      sourceKind: "huggingface",
      source: "Hugging Face",
      type: "Multimodal",
    }),
  ];
}

describe("datasets inventory filters (live rows)", () => {
  it("All renders every API-mapped record (7)", () => {
    const rows = sampleInventory();
    const filtered = filterDatasetRows(rows, { filter: "all" });
    expect(filtered).toHaveLength(7);
    expect(filtered.map((r) => r.name)).toEqual(rows.map((r) => r.name));
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
});

describe("datasets inventory + activity co-existence regression", () => {
  const pageSrc = readFileSync(join(here, "DatasetsPage.tsx"), "utf8");
  const cssSrc = readFileSync(join(here, "../styles/datasets-dashboard.css"), "utf8");

  it("keeps GET /api/datasets inventory list/grid in the page (not replaced by activity)", () => {
    expect(pageSrc).toContain("api.listDatasets");
    expect(pageSrc).toContain('aria-label="Datasets inventory"');
    expect(pageSrc).toContain("data-testid=\"datasets-inventory\"");
    expect(pageSrc).toContain("filteredRows.map");
    expect(pageSrc).toContain("lv-dh-table");
    expect(pageSrc).toContain("lv-dh-grid");
    expect(pageSrc).toContain("row.name");
  });

  it("renders Dataset Activity as a complementary section after inventory", () => {
    expect(pageSrc).toContain("<DatasetActivityConsole");
    const inventoryAt = pageSrc.indexOf('aria-label="Datasets inventory"');
    const activityAt = pageSrc.indexOf("<DatasetActivityConsole");
    expect(inventoryAt).toBeGreaterThan(-1);
    expect(activityAt).toBeGreaterThan(-1);
    expect(inventoryAt).toBeLessThan(activityAt);
  });

  it("does not introduce a DatasetListV2 replacement", () => {
    expect(pageSrc).not.toMatch(/DatasetListV2/);
    expect(pageSrc).not.toMatch(/mockDatasets|DH_DEMO_ROWS/);
  });

  it("CSS prevents inventory panel from flex-shrinking away under activity console", () => {
    expect(cssSrc).toMatch(/\.lv-dh-main\s*>\s*\*\s*\{[^}]*flex-shrink:\s*0/s);
    expect(cssSrc).toMatch(/\.lv-dh-panel\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
    expect(cssSrc).toMatch(/\.lv-dh-panel\s*\{[^}]*min-height:\s*160px/s);
    expect(cssSrc).toMatch(/\.lv-dac\s*\{[^}]*flex:\s*0\s+0\s+auto/s);
  });

  it("inventory filtering is wired through shared helper (not inlined-away)", () => {
    expect(pageSrc).toContain("filterDatasetRows");
    expect(pageSrc).toContain("countDatasetsByFilter");
  });
});
