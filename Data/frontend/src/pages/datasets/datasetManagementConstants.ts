/**
 * Production Dataset Management copy / filters / actions.
 * No screenshot KPI numbers or fixture table rows — those live in visual mocks only.
 */

export type DatasetMgmtStatus =
  | "Klaar"
  | "Verwerkt"
  | "Bezig"
  | "Wachtrij"
  | "Waarschuwing"
  | "Fout"
  | "Onbekend";

export type DatasetSampleTab = "JSON" | "Tekst" | "Tabel";

export type DatasetSidebarAction = {
  id: string;
  label: string;
  icon: string;
  danger?: boolean;
};

export const DM_PAGE_COPY = {
  title: "Dataset Management",
  subtitle: "ORGANISEER. VERRIJK. CONTROLEER. VERSNEL.",
  quote: "Goede data vormt de fundering van betere intelligentie.",
  pillars: ["RUWE DATA", "BETERE MODELLEN", "DIEPER INZICHT", "GROTERE IMPACT"],
  shellTitle: "LLM / Dataset Management",
  shellSubtitle: "Organiseer, verrijk en beheer datasets voor training en Brain.",
  searchPlaceholder: "Zoek in datasets, tags, bronnen...",
} as const;

export const DM_SIDEBAR_ACTIONS: DatasetSidebarAction[] = [
  { id: "upload", label: "Dataset toevoegen", icon: "plus" },
  { id: "hf", label: "Importeren (Hugging Face)", icon: "download" },
  { id: "local", label: "Lokale bestanden importeren", icon: "upload" },
  { id: "create", label: "Nieuwe dataset aanmaken", icon: "squareplus" },
  { id: "rescan", label: "Opnieuw scannen", icon: "refresh" },
  { id: "delete", label: "Geselecteerde verwijderen", icon: "trash", danger: true },
  { id: "learn", label: "Kennis leren", icon: "database" },
  { id: "dup", label: "Dupliceren", icon: "copy" },
  { id: "index", label: "Index opnieuw opbouwen", icon: "refresh" },
  { id: "validate", label: "Valideren", icon: "checkcircle" },
  { id: "export", label: "Exporteren", icon: "download" },
];

export const DM_TYPE_FILTERS = ["Alle types", "Tekst", "Code", "Chat", "PDF", "Logs", "Vision"];
export const DM_SOURCE_FILTERS = ["Alle bronnen", "Open Data", "Hugging Face", "Lokaal", "Synthetic"];
export const DM_SPLIT_FILTERS = ["Alle splits", "train", "validation", "test"];
export const DM_CATEGORY_FILTERS = [
  "Alle categorieën",
  "GENERAL",
  "FINANCE_TRADING",
  "CRYPTO_BLOCKCHAIN",
  "ANIMALS_BIOLOGY",
  "TECHNOLOGY_SOFTWARE",
  "SCIENCE_ENGINEERING",
  "HEALTH_MEDICINE",
  "RESEARCH_PUBLICATIONS",
  "EDUCATION_LANGUAGE",
];
export const DM_STATUS_FILTERS = [
  "Alle statussen",
  "Klaar",
  "Verwerkt",
  "Bezig",
  "Wachtrij",
  "Waarschuwing",
  "Fout",
  "Onbekend",
];

export const DM_FOOTER_ACTIONS = [
  { id: "import", label: "Importeer dataset", tone: "outline" as const },
  { id: "rescan", label: "Opnieuw scannen", tone: "outline" as const },
  { id: "validate", label: "Valideer dataset", tone: "outline" as const },
  { id: "learn", label: "Kennis leren", tone: "outline" as const },
  { id: "save", label: "Sla metagegevens op", tone: "gold" as const },
  { id: "delete", label: "Verwijder dataset", tone: "danger" as const },
] as const;

export const DM_SAMPLE_TABS: DatasetSampleTab[] = ["JSON", "Tekst", "Tabel"];

export const DM_QUICK_ACTIONS = [
  { id: "edit", label: "Metagegevens bewerken", icon: "sliders" },
  { id: "analyze", label: "Opnieuw analyseren", icon: "refresh" },
  { id: "preview", label: "Voorbeeld bekijken", icon: "file" },
  { id: "train", label: "Gebruik in training", icon: "play" },
  { id: "brain", label: "Geleerd in Brain", icon: "database" },
] as const;

export const DM_LIBRARY_PAGE_SIZE = 50;

export const UPLOAD_ACCEPT =
  ".jsonl,.ndjson,.json,.csv,.tsv,.txt,.md,.markdown,.parquet";

export const UPLOAD_SUFFIXES = new Set([
  ".jsonl",
  ".ndjson",
  ".json",
  ".csv",
  ".tsv",
  ".txt",
  ".md",
  ".markdown",
  ".parquet",
]);

/** Map NL UI status filter → backend status query value (or null = all). */
export function statusFilterToQuery(filter: string): string | undefined {
  if (!filter || filter === "Alle statussen") return undefined;
  const map: Record<string, string> = {
    Klaar: "ready",
    Verwerkt: "processed",
    Bezig: "running",
    Wachtrij: "queued",
    Waarschuwing: "warning",
    Fout: "failed",
    Onbekend: "unknown",
  };
  return map[filter] ?? filter;
}

export function sourceFilterToQuery(filter: string): string | undefined {
  if (!filter || filter === "Alle bronnen") return undefined;
  const map: Record<string, string> = {
    "Hugging Face": "huggingface",
    Lokaal: "local",
    Synthetic: "synthetic",
    "Open Data": "open",
  };
  return map[filter] ?? filter;
}

export function typeFilterToQuery(filter: string): string | undefined {
  if (!filter || filter === "Alle types") return undefined;
  return filter;
}
