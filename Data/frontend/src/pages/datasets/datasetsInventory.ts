/**
 * Pure inventory filtering for the Datasets page list/grid.
 * Kept separate from Dataset Activity so layout/console work cannot silently
 * replace or bypass the GET /api/datasets → list pipeline.
 */
import type { DhFilterId, DhRow } from "../../mocks/datasets-dashboard";

export function matchesDatasetFilter(row: DhRow, filter: DhFilterId): boolean {
  if (filter === "all") return true;
  if (filter === "local") return row.sourceKind === "local";
  if (filter === "huggingface") return row.sourceKind === "huggingface";
  if (filter === "curated") return row.sourceKind === "curated";
  if (filter === "offline") return row.status === "offline";
  if (filter === "processing") return row.status === "processing" || row.status === "validating";
  return true;
}

export type DatasetInventoryFilterOpts = {
  filter: DhFilterId;
  query?: string;
  typeFilter?: string;
  updatedFilter?: string;
};

/**
 * Filter/sort live DhRow[] for the inventory list/grid.
 * Names and metadata must already come from API-mapped rows — never invent them here.
 */
export function filterDatasetRows(rows: DhRow[], opts: DatasetInventoryFilterOpts): DhRow[] {
  const q = (opts.query ?? "").trim().toLowerCase();
  const typeFilter = opts.typeFilter ?? "All Types";
  const updatedFilter = opts.updatedFilter ?? "Last Updated";

  let next = rows.filter((row) => matchesDatasetFilter(row, opts.filter));
  if (typeFilter !== "All Types") {
    next = next.filter((r) => r.type === typeFilter);
  }
  if (q) {
    next = next.filter(
      (r) =>
        r.name.toLowerCase().includes(q) ||
        r.description.toLowerCase().includes(q) ||
        r.source.toLowerCase().includes(q) ||
        (r.tags ?? []).some((t) => t.toLowerCase().includes(q)),
    );
  }
  if (updatedFilter === "Oldest first") {
    next = [...next].reverse();
  }
  return next;
}

export function countDatasetsByFilter(rows: DhRow[]): Record<DhFilterId, number> {
  const counts: Record<DhFilterId, number> = {
    all: rows.length,
    local: 0,
    huggingface: 0,
    curated: 0,
    offline: 0,
    processing: 0,
  };
  for (const row of rows) {
    if (row.sourceKind === "local") counts.local += 1;
    if (row.sourceKind === "huggingface") counts.huggingface += 1;
    if (row.sourceKind === "curated") counts.curated += 1;
    if (row.status === "offline") counts.offline += 1;
    if (row.status === "processing" || row.status === "validating") counts.processing += 1;
  }
  return counts;
}
