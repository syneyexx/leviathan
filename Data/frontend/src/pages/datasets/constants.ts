/**
 * Leviathan V2 Datasets (Onderzoek & Kennis) — production presentation contracts.
 *
 * Labels, filter ids, column ids, and page copy only.
 * No fixture numbers, sample rows, or screenshot KPI values live here.
 * Visual regression fixtures: src/mocks/datasetsV2VisualFixture.ts
 * Legacy demo placeholders (tests only): src/mocks/datasets-dashboard.ts
 */

export type DhSourceKind = "huggingface" | "local" | "curated" | "arxiv" | "ncbi" | "other";

export type DhStatus =
  | "ready"
  | "offline"
  | "validating"
  | "processing"
  | "failed"
  | "cancelled"
  | "unknown";

export type DhEmbedding =
  | { kind: "indexed" }
  | { kind: "not_indexed" }
  | { kind: "pending" }
  | { kind: "queued" }
  | { kind: "indexing"; pct: number };

/** Primary inventory filter pills — matches reference composition. */
export type DhFilterId = "all" | "local" | "external" | "indexed" | "not_indexed";

export type DhColumnId =
  | "name"
  | "type"
  | "source"
  | "size"
  | "records"
  | "status"
  | "updated"
  | "actions";

export type DhRow = {
  id: string;
  name: string;
  description: string;
  source: string;
  sourceKind: DhSourceKind;
  type: string;
  size: string;
  records: string;
  status: DhStatus;
  embeddings: DhEmbedding;
  updated: string;
  tags?: string[];
  /** Present when mapped from live API */
  live?: boolean;
  byteSize?: number | null;
  rowCount?: number | null;
  updatedAt?: string | null;
};

export const DS_PAGE_COPY = {
  title: "Datasets",
  breadcrumb: "Kennis & Onderzoek / Datasets",
  subtitle: "Beheer, importeer en analyseer alle datasets voor je onderzoek en AI agents.",
  searchPlaceholder: "Zoek datasets...",
} as const;

export const DS_TYPE_OPTIONS = [
  "Alle types",
  "Tekst",
  "Tabel",
  "Documenten",
  "Multimodal",
  "Code",
  "JSON",
  "Afbeeldingen",
] as const;

export const DS_UPDATED_OPTIONS = [
  "Laatst gewijzigd",
  "Laatste 24 uur",
  "Laatste 7 dagen",
  "Laatste 30 dagen",
  "Oudste eerst",
] as const;

export const DS_ACTIVITY_PERIODS = [
  "Laatste 24 uur",
  "Laatste 7 dagen",
  "Laatste 30 dagen",
  "Alles",
] as const;

export const DS_FILTER_PILLS: Array<{
  id: DhFilterId;
  label: string;
  icon: string;
}> = [
  { id: "all", label: "Alle Datasets", icon: "grid" },
  { id: "local", label: "Lokale", icon: "folder" },
  { id: "external", label: "Externe", icon: "external" },
  { id: "indexed", label: "Geïndexeerd", icon: "indexed" },
  { id: "not_indexed", label: "Niet geïndexeerd", icon: "pending" },
];

export const DS_COLUMNS: Array<{ id: DhColumnId; label: string; defaultVisible: boolean }> = [
  { id: "name", label: "Naam", defaultVisible: true },
  { id: "type", label: "Type", defaultVisible: true },
  { id: "source", label: "Bron", defaultVisible: true },
  { id: "size", label: "Grootte", defaultVisible: true },
  { id: "records", label: "Records", defaultVisible: true },
  { id: "status", label: "Status", defaultVisible: true },
  { id: "updated", label: "Laatst gewijzigd", defaultVisible: true },
  { id: "actions", label: "Acties", defaultVisible: true },
];

export const DS_PAGE_SIZE = 50;
export const DS_SEARCH_DEBOUNCE_MS = 350;
export const DS_BULK_MAX = 25;

/** English legacy aliases kept for older filter strings in tests / callers. */
export const DH_TYPE_OPTIONS = [
  "All Types",
  "Text",
  "Structured",
  "Document",
  "Multimodal",
  "Code",
] as const;

export const DH_UPDATED_OPTIONS = [
  "Last Updated",
  "Last 24 hours",
  "Last 7 days",
  "Last 30 days",
  "Oldest first",
] as const;

/** @deprecated Prefer DS_FILTER_PILLS — retained for transitional imports. */
export const DH_FILTER_PILLS = DS_FILTER_PILLS;

/** @deprecated Prefer DS_PAGE_COPY */
export const DH_PAGE_COPY = {
  title: DS_PAGE_COPY.title,
  subtitle: DS_PAGE_COPY.subtitle,
  description: DS_PAGE_COPY.subtitle,
  quote: "DATA EXTENDS HUMAN CURIOSITY. — LEVIATHAN",
} as const;
