/** FINALBETA Knowledge Library — pixel mock data (UI-only). */

export type KlibTabId =
  | "overzicht"
  | "zoeken"
  | "bronnen"
  | "netwerk"
  | "curatie"
  | "governance"
  | "instellingen";

export type KlibSearchMode = "hybride" | "semantisch" | "exact";

export type KlibDomain = {
  id: string;
  label: string;
  count: string;
  icon: string;
};

export type KlibRecentItem = {
  id: string;
  title: string;
  excerpt: string;
  ago: string;
  kind: string;
  icon: string;
  tags?: string[];
};

export type KlibIngestItem = {
  id: string;
  name: string;
  status: "verwerken" | "wachtrij" | "gereed";
  statusLabel: string;
  progress: number | null;
};

export type KlibGovernanceMetric = {
  id: string;
  label: string;
  value: string;
  tone: "cyan" | "gold" | "muted" | "warn";
};

export type KlibTopTopic = {
  rank: number;
  label: string;
  volume: string;
  trend: string;
  trendUp: boolean;
};

export type KlibCuratieStat = {
  id: string;
  label: string;
  value: string;
};

export const KLIB_HERO = {
  title: "KNOWLEDGE LIBRARY",
  subtitle: "VERZAMELEN. STRUCTUREREN. VERBINDEN. TOEPASSEN.",
  quote: "Kennis krijgt pas waarde wanneer het in verband wordt gebracht.",
};

export const KLIB_TABS: {
  id: KlibTabId;
  label: string;
  sub: string;
  icon: string;
}[] = [
  { id: "overzicht", label: "Overzicht", sub: "Kennisbibliotheek", icon: "grid" },
  { id: "zoeken", label: "Zoeken & Verkennen", sub: "Vind kennis", icon: "search" },
  { id: "bronnen", label: "Bronnen", sub: "Ingestie & connecties", icon: "database" },
  { id: "netwerk", label: "Semantisch Netwerk", sub: "Relaties & context", icon: "link" },
  { id: "curatie", label: "Curatie", sub: "Tags, labels & taxonomie", icon: "sliders" },
  { id: "governance", label: "Governance", sub: "Validatie & kwaliteit", icon: "shield" },
  { id: "instellingen", label: "Instellingen", sub: "Voorkeuren & beheer", icon: "settings" },
];

export const KLIB_KPIS = [
  {
    id: "total",
    label: "Totaal Kennisitems",
    value: "482K",
    delta: "+12%",
    hint: "kennisitems in bibliotheek",
    icon: "file",
    sparkline: null as number[] | null,
  },
  {
    id: "sources",
    label: "Geïndexeerde Bronnen",
    value: "1.2K",
    delta: "+8%",
    hint: "documenten, systemen, feeds",
    icon: "database",
    sparkline: null,
  },
  {
    id: "accuracy",
    label: "Zoeknauwkeurigheid",
    value: "98%",
    delta: "+3%",
    hint: "relevante resultaten (RAG)",
    icon: "target",
    sparkline: null,
  },
  {
    id: "velocity",
    label: "Update Velociteit",
    value: "1.3K",
    delta: "+28%",
    hint: "nieuwe items / week",
    icon: "line",
    sparkline: [3, 5, 4, 8, 7, 11, 9, 14, 12, 16, 13, 18],
  },
] as const;

export const KLIB_DOMAINS: KlibDomain[] = [
  { id: "strategie", label: "Strategie & Organisatie", count: "48.2K", icon: "target" },
  { id: "tech", label: "Technologie & Innovatie", count: "62.1K", icon: "grid" },
  { id: "markt", label: "Markt & Concurrentie", count: "38.7K", icon: "chart" },
  { id: "klant", label: "Klant & Gebruiker", count: "29.3K", icon: "users" },
  { id: "product", label: "Product & Dienstverlening", count: "41.6K", icon: "wrench" },
  { id: "data", label: "Data & Analytics", count: "55.4K", icon: "database" },
  { id: "compliance", label: "Compliance & Wetgeving", count: "18.9K", icon: "shield" },
  { id: "intern", label: "Interne Kennis", count: "112K", icon: "book" },
];

export const KLIB_RECENT: KlibRecentItem[] = [
  {
    id: "r1",
    title: "AI Governance Framework",
    excerpt: "Richtlijnen voor verantwoorde AI-adoptie en risicobeheer in de organisatie.",
    ago: "2u geleden",
    kind: "Whitepaper",
    icon: "file",
    tags: ["Governance", "AI"],
  },
  {
    id: "r2",
    title: "Marktanalyse Generatieve AI 2024",
    excerpt: "Sectorale adoptie, investeringen en concurrentiedynamiek in Europa.",
    ago: "5u geleden",
    kind: "Rapport",
    icon: "chart",
    tags: ["Generatieve AI", "Markt"],
  },
  {
    id: "r3",
    title: "EU AI Act Implementatiegids",
    excerpt: "Praktische stappen voor compliance, documentatie en menselijk toezicht.",
    ago: "8u geleden",
    kind: "Handboek",
    icon: "book",
    tags: ["EU", "Compliance"],
  },
  {
    id: "r4",
    title: "Data Mesh Architectuur",
    excerpt: "Patronen voor gedecentraliseerd data ownership en productdenken.",
    ago: "1d geleden",
    kind: "Artikel",
    icon: "grid",
  },
  {
    id: "r5",
    title: "Cybersecurity Best Practices",
    excerpt: "Zero-trust, segmentatie en incident response voor kritieke workloads.",
    ago: "1d geleden",
    kind: "Whitepaper",
    icon: "shield",
  },
];

export const KLIB_SEARCH_FILTERS = {
  domains: ["Alle domeinen", "Strategie & Organisatie", "Technologie & Innovatie", "Data & Analytics"],
  sourceTypes: ["Alle brontypes", "Documenten", "Feeds", "Interne notities", "Web"],
  periods: ["Alle periodes", "24 uur", "7 dagen", "30 dagen", "Dit jaar"],
};

export const KLIB_SEARCH_TOGGLES = [
  { id: "synonyms", label: "Synoniemen & uitbreidingen", defaultOn: true },
  { id: "conceptual", label: "Conceptuele matching", defaultOn: true },
  { id: "related", label: "Gerelateerde items tonen", defaultOn: false },
  { id: "refs", label: "Bronverwijzingen", defaultOn: true },
  { id: "cluster", label: "Resultaten clusteren", defaultOn: false },
] as const;

export const KLIB_CONTEXT = {
  title: "Generatieve AI in de Zorg",
  badge: "Nieuw",
  tags: ["Zorg", "AI", "Implementatie"],
  summary:
    "Implementatie van generatieve AI in zorginstellingen vraagt om strikte governance, patiëntprivacy en klinische validatie. Succesfactoren zijn multidisciplinaire teams, heldere use-cases en continue monitoring van bias en veiligheid.",
  actions: [
    { id: "summary", label: "Samenvatting genereren", icon: "file" },
    { id: "related", label: "Gerelateerde kennis tonen", icon: "link" },
    { id: "trends", label: "Trends en patronen analyseren", icon: "chart" },
    { id: "apply", label: "Toepassingsmogelijkheden voorstellen", icon: "bolt" },
  ],
};

export const KLIB_INGEST_QUEUE: KlibIngestItem[] = [
  {
    id: "q1",
    name: "McKinsey — State of AI 2024.pdf",
    status: "verwerken",
    statusLabel: "Verwerken",
    progress: 64,
  },
  {
    id: "q2",
    name: "Zendesk — Support Knowledge Export",
    status: "wachtrij",
    statusLabel: "In wachtrij",
    progress: null,
  },
  {
    id: "q3",
    name: "Interne Notities — Q3 Strategie",
    status: "gereed",
    statusLabel: "Gereed",
    progress: 100,
  },
];

export const KLIB_GRAPH_STATS = {
  concepts: "12.4K",
  relations: "48.7K",
  entities: "892",
  clusters: "24",
};

export const KLIB_GOVERNANCE: KlibGovernanceMetric[] = [
  { id: "eval", label: "Geëvalueerde items", value: "94%", tone: "cyan" },
  { id: "trusted", label: "Betrouwbare bronnen", value: "98%", tone: "cyan" },
  { id: "manual", label: "Handmatige validatie", value: "12%", tone: "gold" },
  { id: "stale", label: "Verouderde items", value: "3%", tone: "warn" },
  { id: "dup", label: "Dubbele items", value: "1.2%", tone: "muted" },
];

export const KLIB_TOP_TOPICS: KlibTopTopic[] = [
  { rank: 1, label: "Generatieve AI", volume: "18.4K", trend: "+24%", trendUp: true },
  { rank: 2, label: "AI Governance", volume: "12.1K", trend: "+18%", trendUp: true },
  { rank: 3, label: "Digitale Transformatie", volume: "9.8K", trend: "+11%", trendUp: true },
  { rank: 4, label: "Data & Privacy", volume: "7.2K", trend: "+6%", trendUp: true },
  { rank: 5, label: "Klinische Innovatie", volume: "5.9K", trend: "-2%", trendUp: false },
];

export const KLIB_CURATIE: KlibCuratieStat[] = [
  { id: "untagged", label: "Ongetagde items", value: "342" },
  { id: "suggest", label: "Suggesties", value: "124" },
  { id: "review", label: "Te reviewen", value: "28" },
  { id: "newtags", label: "Nieuwe tags", value: "17" },
];

export const KLIB_FOOTER = {
  left: "RESEARCH & KNOWLEDGE // KNOWLEDGE LIBRARY",
  right: "KNOWLEDGE FUELS INTELLIGENCE // INTELLIGENCE DRIVES IMPACT",
};
