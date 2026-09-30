/** Knowledge Library V2 constants — presentation only, not domain truth. */

export const KL_PAGE_SIZE = 50;
export const KL_SEARCH_DEBOUNCE_MS = 280;
export const KL_INGEST_POLL_MS = 2500;
export const KL_LIBRARY_POLL_MS = 30_000;

export type KlViewId =
  | "bibliotheek"
  | "ingestie"
  | "bronnen"
  | "vector"
  | "grafiek"
  | "analyses"
  | "datasets"
  | "notities"
  | "instellingen";

export type KlDetailTab = "preview" | "metadata" | "inhoud" | "embeddings" | "relaties";
export type KlViewMode = "list" | "grid";

export const KL_NAV: Array<{ id: KlViewId; label: string; kind: "view" | "route"; to?: string }> = [
  { id: "bibliotheek", label: "Bibliotheek", kind: "view" },
  { id: "ingestie", label: "Ingestie", kind: "view" },
  { id: "bronnen", label: "Bronnen", kind: "view" },
  { id: "vector", label: "Vector Search", kind: "view" },
  { id: "grafiek", label: "Kennis Grafiek", kind: "route", to: "/brain" },
  { id: "analyses", label: "Analyses", kind: "view" },
  { id: "datasets", label: "Datasets", kind: "route", to: "/datasets" },
  { id: "notities", label: "Notities", kind: "route", to: "/memory" },
  { id: "instellingen", label: "Instellingen", kind: "route", to: "/settings?section=knowledge_rag" },
];

export const KL_STATUS_LABELS: Record<string, string> = {
  DISCOVERED: "Ontdekt",
  PARSING: "Parsing",
  INDEXING: "Indexeren",
  READY: "Geïndexeerd",
  FAILED: "Mislukt",
  QUARANTINED: "Quarantaine",
  DELETED: "Verwijderd",
};

export const KL_SORT_OPTIONS = [
  { id: "updated_desc", label: "Laatst gewijzigd" },
  { id: "created_desc", label: "Laatst toegevoegd" },
  { id: "title_asc", label: "Titel A–Z" },
  { id: "size_desc", label: "Grootte" },
  { id: "relevance", label: "Relevantie" },
] as const;
