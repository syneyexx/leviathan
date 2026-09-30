/**
 * TEST / DEMO placeholders for Datasets UI.
 *
 * Production pages/hooks MUST NOT import fixture numbers or DH_DEMO_* as
 * runtime fallbacks. Prefer pages/datasets/constants.ts for types & labels.
 * Visual regression: mocks/datasetsV2VisualFixture.ts
 */

export type {
  DhColumnId,
  DhEmbedding,
  DhFilterId,
  DhRow,
  DhSourceKind,
  DhStatus,
} from "../pages/datasets/constants";

export {
  DH_FILTER_PILLS,
  DH_PAGE_COPY,
  DH_TYPE_OPTIONS,
  DH_UPDATED_OPTIONS,
  DS_COLUMNS,
  DS_FILTER_PILLS,
  DS_PAGE_COPY,
  DS_TYPE_OPTIONS,
  DS_UPDATED_OPTIONS,
} from "../pages/datasets/constants";

import type { DhFilterId, DhRow } from "../pages/datasets/constants";

/** Fixed pill counts for empty-state visual match (screenshot) — TEST ONLY. */
export const DH_DEMO_FILTER_COUNTS: Record<DhFilterId, number> = {
  all: 24,
  local: 8,
  external: 16,
  indexed: 18,
  not_indexed: 6,
};

/** DEMO-only decorative rows — must never be rendered as live inventory without DemoBanner. */
export const DH_DEMO_ROWS: DhRow[] = [
  {
    id: "demo-pile",
    name: "The Pile (Subset)",
    description: "Diverse text corpus for language modeling",
    source: "Hugging Face",
    sourceKind: "huggingface",
    type: "Text",
    size: "12.4 GB",
    records: "22.4M",
    status: "ready",
    embeddings: { kind: "indexed" },
    updated: "2 days ago",
    tags: ["nlp", "lm"],
  },
  {
    id: "demo-arxiv",
    name: "arXiv AI Papers 2024",
    description: "Machine learning research papers from arXiv",
    source: "arXiv",
    sourceKind: "arxiv",
    type: "Document",
    size: "3.1 GB",
    records: "1.2M",
    status: "ready",
    embeddings: { kind: "indexed" },
    updated: "12 hours ago",
    tags: ["research", "pdf"],
  },
  {
    id: "demo-pubmed",
    name: "PubMed 2024",
    description: "Biomedical abstracts and citations",
    source: "NCBI",
    sourceKind: "ncbi",
    type: "Text",
    size: "8.7 GB",
    records: "4.8M",
    status: "ready",
    embeddings: { kind: "indexing", pct: 78 },
    updated: "3 hours ago",
    tags: ["bio", "medical"],
  },
  {
    id: "demo-climate",
    name: "Climate Change Research",
    description: "Climate science reports and structured observations",
    source: "Curated",
    sourceKind: "curated",
    type: "Structured",
    size: "2.4 GB",
    records: "860K",
    status: "processing",
    embeddings: { kind: "queued" },
    updated: "45 min ago",
    tags: ["climate"],
  },
  {
    id: "demo-local-logs",
    name: "Lab Instrumentation Logs",
    description: "Local sensor and lab device telemetry",
    source: "Local",
    sourceKind: "local",
    type: "Structured",
    size: "640 MB",
    records: "12.1M",
    status: "offline",
    embeddings: { kind: "not_indexed" },
    updated: "5 days ago",
    tags: ["local", "logs"],
  },
  {
    id: "demo-code",
    name: "Open Source Code Corpus",
    description: "Curated multi-language source repositories",
    source: "Curated",
    sourceKind: "curated",
    type: "Code",
    size: "18.2 GB",
    records: "6.4M",
    status: "ready",
    embeddings: { kind: "indexed" },
    updated: "1 day ago",
    tags: ["code"],
  },
  {
    id: "demo-hf-instruct",
    name: "Instruction Tuning Mix",
    description: "Aligned instruction / response pairs",
    source: "Hugging Face",
    sourceKind: "huggingface",
    type: "Text",
    size: "4.6 GB",
    records: "3.2M",
    status: "validating",
    embeddings: { kind: "pending" },
    updated: "20 min ago",
    tags: ["instruct"],
  },
  {
    id: "demo-local-notes",
    name: "Field Research Notes",
    description: "Offline-ready markdown field notes archive",
    source: "Local",
    sourceKind: "local",
    type: "Document",
    size: "128 MB",
    records: "42K",
    status: "offline",
    embeddings: { kind: "not_indexed" },
    updated: "1 week ago",
    tags: ["offline", "notes"],
  },
];

export const DH_DEMO_OVERVIEW = [
  { id: "total", label: "Total Datasets", value: "24", icon: "database" },
  { id: "local", label: "Local Datasets", value: "8", icon: "folder" },
  { id: "offline", label: "Offline Ready", value: "5", icon: "offline" },
  { id: "sync", label: "Active Sync Jobs", value: "2", icon: "sync" },
] as const;

export const DH_DEMO_STORAGE = {
  usedGb: 97.2,
  totalGb: 200,
  segments: [
    { id: "local", label: "Local Datasets", gb: 68.4, color: "#2ec4b6" },
    { id: "cache", label: "Cache & Indexes", gb: 18.1, color: "#4f8cff" },
    { id: "processing", label: "Processing", gb: 7.3, color: "#9b5cff" },
    { id: "other", label: "Other", gb: 3.4, color: "#6b7280" },
  ],
} as const;

export const DH_DEMO_PIPELINE = [
  {
    id: "pipe-pubmed",
    title: "Indexing embeddings",
    detail: "PubMed 2024",
    pct: 78,
    eta: "12 min left",
    tone: "cyan" as const,
    icon: "brain",
  },
  {
    id: "pipe-climate",
    title: "Processing dataset",
    detail: "Climate Change Research",
    pct: 42,
    eta: "28 min left",
    tone: "purple" as const,
    icon: "pulse",
  },
  {
    id: "pipe-validate",
    title: "Schema validation",
    detail: "Instruction Tuning Mix",
    pct: 61,
    eta: "8 min left",
    tone: "blue" as const,
    icon: "check",
  },
];

export const DH_DEMO_HEALTH = [
  {
    id: "integrity",
    label: "Ready Coverage",
    pct: null as number | null,
    hint: "fixture preview",
    tone: "orange" as const,
  },
  {
    id: "schema",
    label: "Schema Validation",
    pct: null as number | null,
    hint: "fixture — no schema probe",
    tone: "orange" as const,
  },
  {
    id: "embedding",
    label: "Embedding Coverage",
    pct: null as number | null,
    hint: "fixture preview",
    tone: "orange" as const,
  },
  {
    id: "offline",
    label: "Offline Availability",
    pct: null as number | null,
    hint: "fixture preview",
    tone: "orange" as const,
  },
];
