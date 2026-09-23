/** FINALBETA Offline Datasets mock data (UI-only). */

export type OfflineDatasetStatus =
  | "ready"
  | "converting"
  | "queued"
  | "verification_failed"
  | "sync_required";

export type OfflineDatasetRow = {
  id: string;
  name: string;
  source: string;
  size: string;
  status: OfflineDatasetStatus;
  statusLabel: string;
  progress?: number;
  compression: string;
  localPath: string;
  checksum: string;
  lastSynced: string;
};

export type OfflineDatasetDetail = {
  id: string;
  name: string;
  status: OfflineDatasetStatus;
  statusLabel: string;
  source: string;
  description: string;
  originalSize: string;
  localSize: string;
  format: string;
  localPath: string;
  checksum: string;
  lastSynced: string;
  indexPresent: boolean;
  usedBy: string;
};

export type OfflineActiveJob = {
  id: string;
  dataset: string;
  task: string;
  progress: number;
  eta: string;
  state: "Bezig" | "Wachtend";
};

export const OFFLINE_PAGE_COPY = {
  title: "DATASET OFFLINE",
  subtitle:
    "DATASETS GELEERD IN BRAIN — Overzicht van datasets waarvan de kennis succesvol in LEVIATHAN Brain is geïndexeerd.",
  quote: "A DEEPER INTELLIGENCE A BRIGHTER TOMORROW.",
};

export const OFFLINE_STATS = [
  {
    id: "datasets",
    label: "Offline Datasets",
    value: "142",
    delta: "+18% vs. vorige maand",
    deltaTone: "up" as const,
    hint: "Lokale packages",
    icon: "database",
    tone: "gold" as const,
  },
  {
    id: "storage",
    label: "Local Storage Used",
    value: "892 GB",
    sub: "van 4.0 TB",
    progress: 22,
    hint: "22% bezet",
    icon: "save",
    tone: "cyan" as const,
  },
  {
    id: "conversions",
    label: "Active Conversions",
    value: "3",
    hint: "2 converteren, 1 indexeren",
    icon: "refresh",
    tone: "cyan" as const,
  },
  {
    id: "verification",
    label: "Verification Issues",
    value: "2",
    hint: "1 mislukt, 1 checksum afwijking",
    icon: "shield",
    tone: "red" as const,
  },
  {
    id: "exports",
    label: "Package Exports",
    value: "27",
    delta: "+35% deze maand",
    deltaTone: "up" as const,
    hint: "Portable .jvpack",
    icon: "download",
    tone: "gold" as const,
  },
] as const;

export const OFFLINE_ACTIONS = [
  { id: "queue", label: "Toevoegen aan offline queue", icon: "plus", toast: "Toegevoegd aan offline queue" },
  {
    id: "convert",
    label: "Converteer geselecteerde dataset",
    icon: "play",
    toast: "Conversie gestart",
  },
  { id: "pause", label: "Pauzeer conversie", icon: "pause", toast: "Conversie gepauzeerd" },
  { id: "resume", label: "Hervat job", icon: "play", toast: "Job hervat" },
  { id: "remove", label: "Verwijder offline kopie", icon: "trash", toast: "Offline kopie verwijderd" },
  { id: "verify", label: "Verifieer integriteit", icon: "shield", toast: "Integriteitscontrole gestart" },
  { id: "export", label: "Exporteer offline package", icon: "download", toast: "Package-export voorbereid" },
  { id: "folder", label: "Open lokale map", icon: "folder", toast: "Lokale map geopend" },
  { id: "storage", label: "Opslag beheren", icon: "database", toast: "Opslagbeheer" },
  { id: "settings", label: "Offline instellingen", icon: "settings", toast: "Offline instellingen" },
] as const;

export const OFFLINE_SOURCE_FILTERS = ["Alle bronnen", "Hugging Face", "Lokaal", "Dataset Brain", "Kaggle"];
export const OFFLINE_STATUS_FILTERS = ["Alle statussen", "Offline klaar", "Converting", "Queued", "Sync required"];
export const OFFLINE_SIZE_FILTERS = ["Alle groottes", "< 10 GB", "10–100 GB", "> 100 GB"];

export const OFFLINE_TABLE_ROWS: OfflineDatasetRow[] = [
  {
    id: "nl_wiki_2024",
    name: "nl_wiki_2024",
    source: "Hugging Face",
    size: "124 GB",
    status: "ready",
    statusLabel: "Offline klaar",
    compression: "zstd (42%)",
    localPath: "D:\\Leviathan\\data\\nl_wiki_2024",
    checksum: "a4f2…9c1e",
    lastSynced: "2024-09-16",
  },
  {
    id: "code_instructions_v2",
    name: "code_instructions_v2",
    source: "Hugging Face",
    size: "48 GB",
    status: "converting",
    statusLabel: "Converting",
    progress: 62,
    compression: "zstd (—)",
    localPath: "D:\\Leviathan\\data\\code_instructions_v2",
    checksum: "—",
    lastSynced: "2024-09-17",
  },
  {
    id: "medical_knowledge",
    name: "medical_knowledge",
    source: "Lokaal",
    size: "22 GB",
    status: "queued",
    statusLabel: "Queued",
    compression: "lz4 (—)",
    localPath: "D:\\Leviathan\\data\\medical_knowledge",
    checksum: "—",
    lastSynced: "—",
  },
  {
    id: "synthetic_dialogues_v1",
    name: "synthetic_dialogues_v1",
    source: "Dataset Brain",
    size: "9.4 GB",
    status: "converting",
    statusLabel: "Converting",
    progress: 38,
    compression: "zstd (51%)",
    localPath: "D:\\Leviathan\\data\\synthetic_dialogues_v1",
    checksum: "b91c…02af",
    lastSynced: "2024-09-15",
  },
  {
    id: "eu_legal_corpus",
    name: "eu_legal_corpus",
    source: "Kaggle",
    size: "31 GB",
    status: "verification_failed",
    statusLabel: "Verification failed",
    compression: "zstd (38%)",
    localPath: "D:\\Leviathan\\data\\eu_legal_corpus",
    checksum: "mismatch",
    lastSynced: "2024-09-10",
  },
  {
    id: "multilingual_news",
    name: "multilingual_news",
    source: "Hugging Face",
    size: "76 GB",
    status: "sync_required",
    statusLabel: "Sync required",
    compression: "zstd (44%)",
    localPath: "D:\\Leviathan\\data\\multilingual_news",
    checksum: "c3e8…11bd",
    lastSynced: "2024-08-28",
  },
  {
    id: "codeparrot_clean",
    name: "codeparrot-clean",
    source: "Hugging Face",
    size: "112 GB",
    status: "ready",
    statusLabel: "Offline klaar",
    compression: "zstd (47%)",
    localPath: "D:\\Leviathan\\data\\codeparrot-clean",
    checksum: "d7aa…88f0",
    lastSynced: "2024-09-14",
  },
  {
    id: "agent_tool_logs",
    name: "agent_tool_logs",
    source: "Lokaal",
    size: "4.2 GB",
    status: "ready",
    statusLabel: "Offline klaar",
    compression: "zstd (33%)",
    localPath: "D:\\Leviathan\\data\\agent_tool_logs",
    checksum: "e102…44ce",
    lastSynced: "2024-09-17",
  },
];

export const OFFLINE_DATASET_DETAILS: Record<string, OfflineDatasetDetail> = {
  nl_wiki_2024: {
    id: "nl_wiki_2024",
    name: "nl_wiki_2024",
    status: "ready",
    statusLabel: "Offline klaar",
    source: "Hugging Face",
    description: "Nederlandse Wikipedia dataset — gecomprimeerd en geïndexeerd voor lokale RAG.",
    originalSize: "186 GB",
    localSize: "124 GB",
    format: ".jvpack",
    localPath: "D:\\Leviathan\\data\\nl_wiki_2024",
    checksum: "a4f2c91e…9c1e8b44 (SHA256)",
    lastSynced: "2024-09-16 14:22",
    indexPresent: true,
    usedBy: "3 projecten · 2 agents",
  },
  code_instructions_v2: {
    id: "code_instructions_v2",
    name: "code_instructions_v2",
    status: "converting",
    statusLabel: "Converting (62%)",
    source: "Hugging Face",
    description: "Code-instruct dataset voor lokale fine-tuning pipelines.",
    originalSize: "72 GB",
    localSize: "48 GB (partial)",
    format: ".jvpack (in progress)",
    localPath: "D:\\Leviathan\\data\\code_instructions_v2",
    checksum: "—",
    lastSynced: "2024-09-17 09:05",
    indexPresent: false,
    usedBy: "1 project · 1 agent",
  },
};

export const OFFLINE_STORAGE_SEGMENTS = [
  { label: "Datasets", value: "712 GB", pct: 80, color: "#3ac7ee" },
  { label: "Indexen", value: "112 GB", pct: 12.5, color: "#eab94f" },
  { label: "Packages", value: "48 GB", pct: 5.4, color: "#20e38d" },
  { label: "Overig", value: "20 GB", pct: 2.1, color: "#6f8490" },
] as const;

export const OFFLINE_CONVERSION_SETTINGS = {
  format: "zstd",
  level: "6",
  chunk: "1 GB",
  toggles: [
    { id: "index", label: "Maak zoekindex aan", on: true },
    { id: "meta", label: "Include metadata", on: true },
    { id: "verify", label: "Verifieer na conversie", on: false },
  ],
  portablePackage: true,
};

export const OFFLINE_ACTIVE_JOBS: OfflineActiveJob[] = [
  {
    id: "job-code",
    dataset: "code_instructions_v2",
    task: "Converting",
    progress: 62,
    eta: "~2u 14m",
    state: "Bezig",
  },
  {
    id: "job-med",
    dataset: "medical_knowledge",
    task: "Packaging",
    progress: 14,
    eta: "Wacht op queue",
    state: "Wachtend",
  },
  {
    id: "job-syn",
    dataset: "synthetic_dialogues_v1",
    task: "Indexing",
    progress: 38,
    eta: "~45m",
    state: "Bezig",
  },
  {
    id: "job-wiki",
    dataset: "nl_wiki_2024",
    task: "Idle",
    progress: 100,
    eta: "—",
    state: "Wachtend",
  },
];

export const OFFLINE_INTEGRITY = {
  lastCheck: "2024-09-16 14:25",
  result: "Geslaagd",
  checks: [
    { id: "file", label: "Bestand intact", ok: true },
    { id: "index", label: "Index consistent", ok: true },
    { id: "chunk", label: "Chunk validatie", ok: true },
    { id: "meta", label: "Metadata geldig", ok: true },
  ],
};

export const OFFLINE_PACKAGE_SUMMARY = {
  format: ".jvpack",
  version: "1.0",
  size: "124 GB",
  includes: [
    { id: "ds", label: "Dataset bestanden", on: true },
    { id: "idx", label: "Zoekindex", on: true },
    { id: "meta", label: "Metadata", on: true },
    { id: "hash", label: "Hashes", on: true },
  ],
};

export const OFFLINE_TABLE_META = {
  total: 142,
  pageSize: 8,
  page: 1,
};
