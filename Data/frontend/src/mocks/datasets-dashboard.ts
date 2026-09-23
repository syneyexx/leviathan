/** Datasets dashboard — screenshot-matching demo placeholders (UI when API list is empty). */

export type DhSourceKind = "huggingface" | "local" | "curated" | "arxiv" | "ncbi" | "other";
export type DhStatus = "ready" | "offline" | "validating" | "processing";
export type DhEmbedding =
  | { kind: "indexed" }
  | { kind: "not_indexed" }
  | { kind: "pending" }
  | { kind: "queued" }
  | { kind: "indexing"; pct: number };

export type DhFilterId = "all" | "local" | "huggingface" | "curated" | "offline" | "processing";

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

export const DH_PAGE_COPY = {
  title: "DATASETS",
  subtitle: "Your gateway to a broader world of knowledge.",
  description:
    "Discover, manage, and connect datasets from across the web, local sources, and trusted repositories. Power deeper research with high-quality data.",
  quote: "DATA EXTENDS HUMAN CURIOSITY. — LEVIATHAN",
} as const;

export const DH_TYPE_OPTIONS = ["All Types", "Text", "Structured", "Document", "Multimodal", "Code"] as const;
export const DH_UPDATED_OPTIONS = [
  "Last Updated",
  "Last 24 hours",
  "Last 7 days",
  "Last 30 days",
  "Oldest first",
] as const;

export const DH_FILTER_PILLS: Array<{
  id: DhFilterId;
  label: string;
  icon: string;
}> = [
  { id: "all", label: "All", icon: "grid" },
  { id: "local", label: "Local", icon: "folder" },
  { id: "huggingface", label: "Hugging Face", icon: "hf" },
  { id: "curated", label: "Curated", icon: "shield" },
  { id: "offline", label: "Offline", icon: "offline" },
  { id: "processing", label: "Processing", icon: "pulse" },
];

/** Fixed pill counts for empty-state visual match (screenshot). */
export const DH_DEMO_FILTER_COUNTS: Record<DhFilterId, number> = {
  all: 24,
  local: 8,
  huggingface: 6,
  curated: 4,
  offline: 5,
  processing: 2,
};

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
    label: "Data Integrity",
    pct: 98,
    hint: null as string | null,
    tone: "green" as const,
  },
  {
    id: "schema",
    label: "Schema Validation",
    pct: 96,
    hint: "2 warnings",
    tone: "teal" as const,
  },
  {
    id: "embedding",
    label: "Embedding Coverage",
    pct: 78,
    hint: "6 datasets pending",
    tone: "blue" as const,
  },
  {
    id: "offline",
    label: "Offline Availability",
    pct: 71,
    hint: "17 datasets available offline",
    tone: "orange" as const,
  },
];
