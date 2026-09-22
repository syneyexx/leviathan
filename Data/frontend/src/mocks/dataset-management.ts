/** FINALBETA Dataset Management mock data (UI-only). */

export type DatasetMgmtStatus = "Klaar" | "Verwerkt" | "Bezig" | "Wachtrij" | "Waarschuwing" | "Fout";

export type DatasetMgmtRow = {
  id: string;
  name: string;
  type: string;
  typeTone: "cyan" | "gold" | "green" | "purple" | "blue";
  source: string;
  sourceIcon: string;
  split: string;
  size: string;
  tokens: string;
  status: DatasetMgmtStatus;
  tags: string[];
  updated: string;
};

export type DatasetMgmtDetail = {
  id: string;
  name: string;
  description: string;
  source: string;
  type: string;
  splits: string;
  location: string;
  version: string;
  language: string;
  license: string;
  taskType: string;
  created: string;
  updated: string;
};

export type DatasetSampleTab = "JSON" | "Tekst" | "Tabel";

export type DatasetImportJob = {
  id: string;
  task: string;
  dataset: string;
  status: "Klaar" | "Bezig" | "Wachtrij";
  progress: number;
  started: string;
  duration: string;
};

export const DM_PAGE_COPY = {
  title: "DATASET MANAGEMENT",
  subtitle: "ORGANISEER. VERRIJK. CONTROLEER. VERSNEL.",
  quote: "Goede data vormt de fundering van betere intelligentie.",
  pillars: ["RUWE DATA", "BETERE MODELLEN", "DIEPER INZICHT", "GROTERE IMPACT"],
};

export const DM_STATS = [
  {
    id: "datasets",
    label: "Totaal Datasets",
    value: "248",
    delta: "▲ +12%",
    deltaSub: "vs. vorige maand",
    icon: "database",
    tone: "cyan" as const,
  },
  {
    id: "samples",
    label: "Totaal Samples",
    value: "186.4M",
    delta: "▲ +28%",
    deltaSub: "+40.7M",
    icon: "file",
    tone: "cyan" as const,
  },
  {
    id: "storage",
    label: "Opslag Gebruikt",
    value: "842 GB",
    sub: "van 2.0 TB",
    progress: 42,
    hint: "42% bezet",
    icon: "save",
    tone: "gold" as const,
  },
  {
    id: "imports",
    label: "Actieve Imports",
    value: "3",
    hint: "2 bezig · 1 in wachtrij",
    icon: "refresh",
    tone: "cyan" as const,
  },
  {
    id: "validation",
    label: "Validatie Issues",
    value: "12",
    hint: "4 kritiek · 8 waarschuwingen",
    icon: "shield",
    tone: "red" as const,
  },
  {
    id: "sync",
    label: "Sync Status",
    value: "Online",
    hint: "Laatste sync 5 min geleden",
    icon: "globe",
    tone: "green" as const,
  },
] as const;

export const DM_ACTIONS = [
  { id: "add", label: "Dataset toevoegen", icon: "plus", toast: "Dataset toevoegen" },
  { id: "hf", label: "Importeren (Hugging Face)", icon: "download", toast: "Hugging Face import" },
  { id: "local", label: "Lokale bestanden importeren", icon: "upload", toast: "Lokale import" },
  { id: "create", label: "Nieuwe dataset aanmaken", icon: "squareplus", toast: "Nieuwe dataset" },
  { id: "delete", label: "Geselecteerde verwijderen", icon: "trash", toast: "Verwijderen (demo)", danger: true },
  { id: "offline", label: "Converteren naar offline", icon: "save", toast: "Offline conversie" },
  { id: "dup", label: "Dupliceren", icon: "copy", toast: "Dataset gedupliceerd" },
  { id: "index", label: "Index opnieuw opbouwen", icon: "refresh", toast: "Index rebuild gestart" },
  { id: "validate", label: "Valideren", icon: "checkcircle", toast: "Validatie gestart" },
  { id: "export", label: "Exporteren", icon: "download", toast: "Export voorbereid" },
] as const;

export const DM_TYPE_FILTERS = ["Alle types", "Tekst", "Code", "Chat", "PDF", "Logs"];
export const DM_SOURCE_FILTERS = ["Alle bronnen", "Open Data", "Hugging Face", "Lokaal", "Synthetic"];
export const DM_SPLIT_FILTERS = ["Alle splits", "train", "validation", "test"];
export const DM_STATUS_FILTERS = ["Alle statussen", "Klaar", "Verwerkt", "Bezig", "Wachtrij", "Waarschuwing"];

export const DM_TAG_OPTIONS = ["nl", "wiki", "kennis", "code", "instruct", "medisch", "chat", "legal", "eu", "news"];

export const DM_TABLE_ROWS: DatasetMgmtRow[] = [
  {
    id: "nl_wiki_2024",
    name: "nl_wiki_2024",
    type: "Tekst",
    typeTone: "cyan",
    source: "Open Data",
    sourceIcon: "globe",
    split: "train",
    size: "48 GB",
    tokens: "12.1M",
    status: "Klaar",
    tags: ["nl", "wiki", "kennis"],
    updated: "2024-09-09 16:27",
  },
  {
    id: "code_instructions_v2",
    name: "code_instructions_v2",
    type: "Code",
    typeTone: "gold",
    source: "Hugging Face",
    sourceIcon: "download",
    split: "train",
    size: "18 GB",
    tokens: "8.4M",
    status: "Verwerkt",
    tags: ["code", "instruct"],
    updated: "2024-09-17 09:14",
  },
  {
    id: "medical_knowledge",
    name: "medical_knowledge",
    type: "Tekst",
    typeTone: "cyan",
    source: "Lokaal",
    sourceIcon: "folder",
    split: "validation",
    size: "12 GB",
    tokens: "3.8M",
    status: "Klaar",
    tags: ["medisch", "nl"],
    updated: "2024-09-15 11:02",
  },
  {
    id: "synthetic_dialogues",
    name: "synthetic_dialogues",
    type: "Chat",
    typeTone: "purple",
    source: "Synthetic",
    sourceIcon: "bolt",
    split: "train",
    size: "6.2 GB",
    tokens: "2.1M",
    status: "Bezig",
    tags: ["chat", "nl"],
    updated: "2024-09-17 14:05",
  },
  {
    id: "eu_legal_corpus",
    name: "eu_legal_corpus",
    type: "Tekst",
    typeTone: "cyan",
    source: "Open Data",
    sourceIcon: "globe",
    split: "train",
    size: "22 GB",
    tokens: "5.6M",
    status: "Klaar",
    tags: ["legal", "eu"],
    updated: "2024-09-10 08:44",
  },
  {
    id: "multilingual_news",
    name: "multilingual_news",
    type: "Tekst",
    typeTone: "cyan",
    source: "Hugging Face",
    sourceIcon: "download",
    split: "train",
    size: "31 GB",
    tokens: "9.2M",
    status: "Klaar",
    tags: ["news", "multi"],
    updated: "2024-09-14 19:33",
  },
  {
    id: "agent_tool_logs",
    name: "agent_tool_logs",
    type: "Logs",
    typeTone: "blue",
    source: "Lokaal",
    sourceIcon: "folder",
    split: "train",
    size: "1.8 GB",
    tokens: "420K",
    status: "Klaar",
    tags: ["agents", "logs"],
    updated: "2024-09-16 07:18",
  },
  {
    id: "research_papers_v3",
    name: "research_papers_v3",
    type: "PDF",
    typeTone: "green",
    source: "Lokaal",
    sourceIcon: "folder",
    split: "train",
    size: "14 GB",
    tokens: "1.2M",
    status: "Waarschuwing",
    tags: ["research"],
    updated: "2024-09-12 22:51",
  },
];

export const DM_DATASET_DETAILS: Record<string, DatasetMgmtDetail> = {
  nl_wiki_2024: {
    id: "nl_wiki_2024",
    name: "nl_wiki_2024",
    description:
      "Nederlandse Wikipedia dump (2024) — opgeschoonde artikelen voor kennisverrijking, RAG en instruct-tuning.",
    source: "Open Data (Wikipedia)",
    type: "Tekst (documenten)",
    splits: "train 100%",
    location: "/data/datasets/nl_wiki_2024",
    version: "2024.09.01",
    language: "Nederlands",
    license: "CC BY-SA 3.0",
    taskType: "Language modeling · RAG",
    created: "2024-08-28 10:12",
    updated: "2024-09-09 16:27:11",
  },
};

export const DM_SAMPLE_JSON = `{
  "id": "wiki_000001",
  "title": "Amsterdam",
  "text": "Amsterdam is de hoofdstad en grootste stad van Nederland...",
  "source": "nl.wikipedia.org",
  "url": "https://nl.wikipedia.org/wiki/Amsterdam",
  "length": 4821
}`;

export const DM_IMPORT_JOBS: DatasetImportJob[] = [
  {
    id: "job-1",
    task: "importeren",
    dataset: "synthetic_dialogues",
    status: "Bezig",
    progress: 64,
    started: "14:02",
    duration: "18m",
  },
  {
    id: "job-2",
    task: "valideren",
    dataset: "research_papers_v3",
    status: "Wachtrij",
    progress: 0,
    started: "—",
    duration: "—",
  },
  {
    id: "job-3",
    task: "dedupliceren",
    dataset: "nl_wiki_2024",
    status: "Klaar",
    progress: 100,
    started: "12:40",
    duration: "2u 11m",
  },
];

export const DM_STORAGE_HEALTH = {
  used: "842 GB",
  total: "2.0 TB",
  pct: 42,
  dedupeSaved: "-358 GB",
  integrity: "Geen fouten",
  lastCheck: "2024-09-17 14:20",
};

export const DM_TAG_CLOUD = [
  { tag: "kennis", count: 62 },
  { tag: "tekst", count: 46 },
  { tag: "nl", count: 48 },
  { tag: "code", count: 31 },
  { tag: "wiki", count: 28 },
  { tag: "instruct", count: 24 },
  { tag: "chat", count: 19 },
  { tag: "legal", count: 14 },
  { tag: "eu", count: 12 },
  { tag: "research", count: 11 },
] as const;

export const DM_FOOTER_ACTIONS = [
  { id: "import", label: "Importeer dataset", tone: "outline" as const },
  { id: "validate", label: "Valideer dataset", tone: "outline" as const },
  { id: "offline", label: "Converteer naar offline", tone: "outline" as const },
  { id: "save", label: "Sla metagegevens op", tone: "gold" as const },
  { id: "delete", label: "Verwijder dataset", tone: "danger" as const },
] as const;

export const DM_TABLE_META = {
  total: 248,
  page: 1,
  pageSize: 8,
  pageCount: 32,
};

export const DM_SAMPLE_TABS: DatasetSampleTab[] = ["JSON", "Tekst", "Tabel"];

export const DM_QUICK_ACTIONS = [
  { id: "edit", label: "Metagegevens bewerken", icon: "sliders" },
  { id: "tags", label: "Tags beheren", icon: "book" },
  { id: "preview", label: "Voorbeeld bekijken", icon: "file" },
  { id: "train", label: "Gebruik in training", icon: "play" },
] as const;
