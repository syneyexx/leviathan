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
  /** Optional clock for deterministic tests; defaults to Date.now(). */
  nowMs?: number;
};

const MS_HOUR = 60 * 60 * 1000;
const MS_DAY = 24 * MS_HOUR;

function updatedAtMs(row: DhRow): number | null {
  if (!row.updatedAt) return null;
  const t = Date.parse(row.updatedAt);
  return Number.isFinite(t) ? t : null;
}

/**
 * Filter/sort live DhRow[] for the inventory list/grid.
 * Names and metadata must already come from API-mapped rows — never invent them here.
 *
 * Updated options (NO PLACEBO):
 * - Last Updated: newest first (default sort by updatedAt desc when available)
 * - Last 24 hours / 7 days / 30 days: filter by updatedAt window
 * - Oldest first: ascending updatedAt
 */
export function filterDatasetRows(rows: DhRow[], opts: DatasetInventoryFilterOpts): DhRow[] {
  const q = (opts.query ?? "").trim().toLowerCase();
  const typeFilter = opts.typeFilter ?? "All Types";
  const updatedFilter = opts.updatedFilter ?? "Last Updated";
  const now = opts.nowMs ?? Date.now();

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

  const windowMs =
    updatedFilter === "Last 24 hours"
      ? MS_HOUR * 24
      : updatedFilter === "Last 7 days"
        ? MS_DAY * 7
        : updatedFilter === "Last 30 days"
          ? MS_DAY * 30
          : null;

  if (windowMs != null) {
    const cutoff = now - windowMs;
    next = next.filter((r) => {
      const t = updatedAtMs(r);
      // Rows without a parseable updatedAt cannot satisfy a time window.
      return t != null && t >= cutoff;
    });
  }

  const ascending = updatedFilter === "Oldest first";
  next = [...next].sort((a, b) => {
    const ta = updatedAtMs(a);
    const tb = updatedAtMs(b);
    if (ta == null && tb == null) return 0;
    if (ta == null) return 1;
    if (tb == null) return -1;
    return ascending ? ta - tb : tb - ta;
  });

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

/** Drop selection ids that no longer exist in the current filtered projection. */
export function reconcileSelection(selectedIds: Set<string>, visibleIds: Iterable<string>): Set<string> {
  const visible = new Set(visibleIds);
  let changed = false;
  const next = new Set<string>();
  for (const id of selectedIds) {
    if (visible.has(id)) next.add(id);
    else changed = true;
  }
  return changed ? next : selectedIds;
}
