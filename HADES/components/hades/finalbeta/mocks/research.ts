export type ResearchSourceFilter =
  | "all"
  | "web"
  | "pdf"
  | "internal"
  | "news"
  | "academic"
  | "gov";

export type ResearchReliability = "zeer" | "goed" | "matig";

export type ResearchResult = {
  id: string;
  title: string;
  handle: string;
  domain: string;
  dateShort: string;
  dateFull: string;
  snippet: string;
  category: string;
  reliability: ResearchReliability;
  reliabilityLabel: string;
  favicon: "eu" | "ec" | "nos" | "nature";
  keyPoints: string[];
  quote: string;
  quoteAttr: string;
  extractions: number;
  citations: number;
};

export type ResearchInsight = {
  id: string;
  title: string;
  body: string;
  icon: string;
  relevance: "high" | "mid";
  relevanceLabel: string;
};

export type ResearchEvidenceItem = {
  id: string;
  title: string;
  domain: string;
  favicon: "eu" | "ec" | "nos";
};

export type ResearchRecent = {
  id: string;
  title: string;
  when: string;
  results: string;
};

export const RESEARCH_DEFAULT_QUERY =
  "Wat zijn de belangrijkste ontwikkelingen in Europese AI-regelgeving in 2024?";

export const RESEARCH_SOURCE_CHIPS: Array<{
  id: ResearchSourceFilter;
  label: string;
  icon: string;
}> = [
  { id: "all", label: "Alle bronnen", icon: "bolt" },
  { id: "web", label: "Web", icon: "globe" },
  { id: "pdf", label: "PDF documenten", icon: "file" },
  { id: "internal", label: "Interne kennis", icon: "grid" },
  { id: "news", label: "Nieuws", icon: "book" },
  { id: "academic", label: "Academisch", icon: "user" },
  { id: "gov", label: "Overheid", icon: "target" },
];

export const RESEARCH_RESULT_TABS = [
  { id: "results", label: "Resultaten", count: 42 },
  { id: "summary", label: "Samenvatting", count: null },
  { id: "insights", label: "Gevonden inzichten", count: 8 },
  { id: "citations", label: "Citaties", count: 12 },
  { id: "related", label: "Gerelateerde onderwerpen", count: null },
] as const;

export const RESEARCH_DETAIL_TABS = [
  { id: "summary", label: "Samenvatting", count: null },
  { id: "full", label: "Volledige tekst", count: null },
  { id: "extractions", label: "Extracties", count: 5 },
  { id: "citations", label: "Citaties", count: 3 },
  { id: "related", label: "Gerelateerde bronnen", count: null },
] as const;

export const RESEARCH_STATUS_CHECKS = [
  { id: "query", label: "Zoekopdracht", value: "✓ Voltooid", tone: "green", icon: "checkcircle" },
  { id: "sources", label: "Bronnen doorzocht", value: "42", tone: "plain", icon: "list" },
  { id: "relevant", label: "Relevante resultaten", value: "42", tone: "plain", icon: "file" },
  { id: "time", label: "Tijd", value: "12.4s", tone: "plain", icon: "clock" },
  { id: "ai", label: "AI analyse", value: "Voltooid", tone: "green", icon: "checkcircle" },
] as const;

export const RESEARCH_SOURCE_SLICES = [
  { label: "Websites", count: 18, pct: "43%", color: "#1aa4ff" },
  { label: "Nieuws", count: 9, pct: "21%", color: "#f0b429" },
  { label: "Academisch", count: 6, pct: "14%", color: "#9b5cff" },
  { label: "Overheid", count: 7, pct: "17%", color: "#20e38d" },
  { label: "Documenten", count: 2, pct: "5%", color: "#c66965" },
] as const;

export const RESEARCH_INSIGHTS: ResearchInsight[] = [
  {
    id: "i1",
    title: "Gefaseerde invoering",
    body: "De implementatie gebeurt in fases: verbodsbepalingen (feb 2025), hoog-risico systemen (aug 2026).",
    icon: "shield",
    relevance: "high",
    relevanceLabel: "Hoge relevantie",
  },
  {
    id: "i2",
    title: "Extra-territoriale werking",
    body: "De AI Act is ook van toepassing op niet-EU bedrijven die AI-systemen in de EU aanbieden.",
    icon: "globe",
    relevance: "high",
    relevanceLabel: "Hoge relevantie",
  },
  {
    id: "i3",
    title: "Nationale toezichthouders",
    body: "Elk lidstaat wijst een nationale toezichthouder aan. In Nederland is dit de Autoriteit Persoonsgegevens.",
    icon: "users",
    relevance: "mid",
    relevanceLabel: "Gemiddeld",
  },
];

export const RESEARCH_EVIDENCE: ResearchEvidenceItem[] = [
  {
    id: "ev1",
    title: "EU AI Act officieel van kracht…",
    domain: "europa.eu",
    favicon: "eu",
  },
  {
    id: "ev2",
    title: "Implementatierichtlijnen AI Act",
    domain: "ec.europa.eu",
    favicon: "ec",
  },
  {
    id: "ev3",
    title: "Analyse impact op Nederlandse…",
    domain: "nos.nl",
    favicon: "nos",
  },
];

export const RESEARCH_RECENT: ResearchRecent[] = [
  {
    id: "r1",
    title: "AI-regelgeving Europa 2024",
    when: "17 feb 2025, 16:14",
    results: "42 resultaten",
  },
  {
    id: "r2",
    title: "Impact AI op onderwijs",
    when: "15 feb 2025, 11:23",
    results: "28 resultaten",
  },
  {
    id: "r3",
    title: "Duurzame AI datacenters",
    when: "12 feb 2025, 09:47",
    results: "36 resultaten",
  },
  {
    id: "r4",
    title: "AI in de zorg: kansen en risico's",
    when: "10 feb 2025, 14:02",
    results: "19 resultaten",
  },
];

export const mockResearchResults: ResearchResult[] = [
  {
    id: "res1",
    title: "EU AI Act officieel van kracht in 2024",
    handle: "@europa.eu",
    domain: "europa.eu",
    dateShort: "12 feb 2024",
    dateFull: "12 februari 2024",
    snippet:
      "De AI Act is formeel aangenomen en stelt een geharmoniseerd kader vast voor het gebruik van AI...",
    category: "Overheid",
    reliability: "zeer",
    reliabilityLabel: "Zeer betrouwbaar",
    favicon: "eu",
    keyPoints: [
      "De EU AI Act is op 1 februari 2024 formeel van kracht geworden.",
      "De wet stelt een risicogebaseerde aanpak vast voor AI-systemen.",
      "Hoog-risico AI-systemen krijgen strenge eisen op het gebied van transparantie, documentatie en menselijk toezicht.",
      "Er geldt een gefaseerde implementatie met deadlines tussen 2024 en 2026.",
      "De wet is van toepassing op alle organisaties die AI-systemen ontwikkelen of gebruiken binnen de EU.",
    ],
    quote:
      "The AI Act establishes a common regulatory framework for artificial intelligence, based on a risk-based approach and aiming to ensure that AI systems are safe, transparent, traceable, non-discriminatory and environmentally friendly.",
    quoteAttr: "— Europese Commissie, 2024",
    extractions: 5,
    citations: 3,
  },
  {
    id: "res2",
    title: "Europese Commissie publiceert implementatierichtlijnen AI Act",
    handle: "ec.europa.eu",
    domain: "ec.europa.eu",
    dateShort: "3 apr 2024",
    dateFull: "3 april 2024",
    snippet:
      "Nieuwe richtsnoeren voor risicoclassificatie en nalevingsvereisten voor AI-systemen.",
    category: "Overheid",
    reliability: "zeer",
    reliabilityLabel: "Zeer betrouwbaar",
    favicon: "ec",
    keyPoints: [
      "De Commissie publiceerde praktische implementatierichtlijnen voor de AI Act.",
      "Richtlijnen helpen bij risicoclassificatie van AI-systemen.",
      "Nalevingseisen worden stapsgewijs aangescherpt tot 2026.",
    ],
    quote:
      "Clear guidance will help providers and deployers comply with the AI Act in a consistent way across the Single Market.",
    quoteAttr: "— Europese Commissie, 2024",
    extractions: 4,
    citations: 2,
  },
  {
    id: "res3",
    title: "Gevolgen van de AI Act voor bedrijven in 2024",
    handle: "@nos.nl",
    domain: "nos.nl",
    dateShort: "18 mrt 2024",
    dateFull: "18 maart 2024",
    snippet:
      "Nederlandse bedrijven moeten zich voorbereiden op nieuwe verplichtingen uit de AI-wetgeving.",
    category: "Nieuws",
    reliability: "goed",
    reliabilityLabel: "Betrouwbaar",
    favicon: "nos",
    keyPoints: [
      "Nederlandse bedrijven krijgen nieuwe transparantieverplichtingen.",
      "Hoog-risico toepassingen vragen vroegtijdige compliance-planning.",
      "Toezicht in Nederland ligt bij de Autoriteit Persoonsgegevens.",
    ],
    quote:
      "Bedrijven die AI inzetten, moeten sneller dan gedacht laten zien hoe hun systemen werken en welke risico's ze mitigeren.",
    quoteAttr: "— NOS, 2024",
    extractions: 3,
    citations: 2,
  },
  {
    id: "res4",
    title: "The EU AI Act: A new era for trustworthy AI",
    handle: "nature.com",
    domain: "nature.com",
    dateShort: "7 feb 2024",
    dateFull: "7 februari 2024",
    snippet:
      "Analysis of the regulatory framework and its implications for innovation in Europe.",
    category: "Academisch",
    reliability: "zeer",
    reliabilityLabel: "Zeer betrouwbaar",
    favicon: "nature",
    keyPoints: [
      "The AI Act sets a global benchmark for risk-based AI regulation.",
      "Innovation incentives coexist with strict high-risk controls.",
      "Trustworthy AI becomes a competitive advantage for EU providers.",
    ],
    quote:
      "Europe's AI Act marks a decisive shift toward enforceable standards for trustworthy artificial intelligence.",
    quoteAttr: "— Nature, 2024",
    extractions: 6,
    citations: 4,
  },
];
