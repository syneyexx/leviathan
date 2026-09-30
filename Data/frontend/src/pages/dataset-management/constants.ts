/**
 * Leviathan V2 Dataset Management — production constants.
 *
 * These are real labels/filters/copy only. No fixture numbers (counts,
 * sizes, sample data) live here — see mocks/datasetManagementV2VisualFixture.ts
 * for TEST-ONLY Screen 1 visual regression data.
 */

export type DatasetSampleTab = "JSON" | "Tekst" | "Tabel";

export const DM_PAGE_COPY = {
  title: "Dataset Management",
  subtitle: "Beheer en verrijk datasets voor modelontwikkeling, RAG, evaluatie en training.",
  intro:
    "Importeer vanuit lokale bronnen of publieke repositories, valideer, verrijk semantisch en versnel training workflows.",
  quote: "Data vormt de ruwe potentie. Kennis ontstaat door structuur.",
  quoteAttribution: "— LEVIATHAN",
  pillars: ["ORGANISEER", "VERRIJK", "CONTROLEER", "VERSNEL"],
};

export const DM_TYPE_FILTERS = ["Alle types", "Tekst", "Code", "Chat", "PDF", "Logs"];
export const DM_SOURCE_FILTERS = ["Alle bronnen", "Open Data", "Hugging Face", "Lokaal", "Synthetic", "Afgeleid"];
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

export const DM_SAMPLE_TABS: DatasetSampleTab[] = ["JSON", "Tekst", "Tabel"];

export type SidebarAction = {
  id: string;
  label: string;
  icon: string;
  danger?: boolean;
};

export const DM_SIDEBAR_ACTIONS: SidebarAction[] = [
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

export const DM_FOOTER_ACTIONS = [
  { id: "import", label: "Importeer dataset", tone: "outline" as const },
  { id: "rescan", label: "Opnieuw scannen", tone: "outline" as const },
  { id: "validate", label: "Valideer dataset", tone: "outline" as const },
  { id: "learn", label: "Kennis leren", tone: "outline" as const },
  { id: "save", label: "Sla metagegevens op", tone: "gold" as const },
  { id: "delete", label: "Verwijder dataset", tone: "danger" as const },
] as const;

export const DM_ADVANCED_ACTIONS = [
  { id: "dedupe", label: "Dedupliceren", icon: "copy" },
  { id: "transform", label: "Transformeren", icon: "sliders" },
  { id: "split", label: "Split genereren", icon: "database" },
  { id: "tokenize", label: "Tokenizen", icon: "file" },
  { id: "pii", label: "PII scan", icon: "shield" },
  { id: "contamination", label: "Contaminatie check", icon: "checkcircle" },
  { id: "materialize", label: "Materialiseren", icon: "save" },
] as const;

export const DM_UPLOAD_ACCEPT =
  ".jsonl,.ndjson,.json,.csv,.tsv,.txt,.md,.markdown,.parquet";

export const DM_UPLOAD_SUFFIXES = new Set([
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

export const DM_PAGE_SIZE = 100;
export const DM_SEARCH_DEBOUNCE_MS = 350;
