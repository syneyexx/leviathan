/**
 * Pure inventory filtering for the Datasets page list/grid.
 * Kept separate from Dataset Activity so layout/console work cannot silently
 * replace or bypass the GET /api/datasets → list pipeline.
 */
import type { DhFilterId, DhRow } from "./constants";

export function isLocalSourceKind(kind: DhRow["sourceKind"]): boolean {
  return kind === "local";
}

export function isExternalSourceKind(kind: DhRow["sourceKind"]): boolean {
  return kind !== "local";
}

export function isIndexedEmbedding(emb: DhRow["embeddings"]): boolean {
  return emb.kind === "indexed";
}

export function matchesDatasetFilter(row: DhRow, filter: DhFilterId): boolean {
  if (filter === "all") return true;
  if (filter === "local") return isLocalSourceKind(row.sourceKind);
  if (filter === "external") return isExternalSourceKind(row.sourceKind);
  if (filter === "indexed") return isIndexedEmbedding(row.embeddings);
  if (filter === "not_indexed") return !isIndexedEmbedding(row.embeddings);
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

function normalizeTypeLabel(type: string): string {
  const t = type.toLowerCase();
  if (t === "structured" || t === "tabel") return "structured";
  if (t === "document" || t === "documenten") return "document";
  if (t === "text" || t === "tekst") return "text";
  if (t === "code") return "code";
  if (t === "multimodal" || t === "afbeeldingen") return "multimodal";
  if (t === "json") return "json";
  return t;
}

function typeFilterMatches(rowType: string, typeFilter: string): boolean {
  if (typeFilter === "All Types" || typeFilter === "Alle types") return true;
  return normalizeTypeLabel(rowType) === normalizeTypeLabel(typeFilter);
}

function isTimeWindowFilter(updatedFilter: string): number | null {
  if (updatedFilter === "Last 24 hours" || updatedFilter === "Laatste 24 uur") return MS_HOUR * 24;
  if (updatedFilter === "Last 7 days" || updatedFilter === "Laatste 7 dagen") return MS_DAY * 7;
  if (updatedFilter === "Last 30 days" || updatedFilter === "Laatste 30 dagen") return MS_DAY * 30;
  return null;
}

function isOldestFirst(updatedFilter: string): boolean {
  return updatedFilter === "Oldest first" || updatedFilter === "Oudste eerst";
}

/**
 * Filter/sort live DhRow[] for the inventory list/grid.
 * Names and metadata must already come from API-mapped rows — never invent them here.
 */
export function filterDatasetRows(rows: DhRow[], opts: DatasetInventoryFilterOpts): DhRow[] {
  const q = (opts.query ?? "").trim().toLowerCase();
  const typeFilter = opts.typeFilter ?? "Alle types";
  const updatedFilter = opts.updatedFilter ?? "Laatst gewijzigd";
  const now = opts.nowMs ?? Date.now();

  let next = rows.filter((row) => matchesDatasetFilter(row, opts.filter));
  if (typeFilter !== "All Types" && typeFilter !== "Alle types") {
    next = next.filter((r) => typeFilterMatches(r.type, typeFilter));
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

  const windowMs = isTimeWindowFilter(updatedFilter);
  if (windowMs != null) {
    const cutoff = now - windowMs;
    next = next.filter((r) => {
      const t = updatedAtMs(r);
      return t != null && t >= cutoff;
    });
  }

  const ascending = isOldestFirst(updatedFilter);
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
    external: 0,
    indexed: 0,
    not_indexed: 0,
  };
  for (const row of rows) {
    if (isLocalSourceKind(row.sourceKind)) counts.local += 1;
    else counts.external += 1;
    if (isIndexedEmbedding(row.embeddings)) counts.indexed += 1;
    else counts.not_indexed += 1;
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
