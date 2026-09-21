export type MemoryKind = "preference" | "project" | "persistent" | "fact" | "session";

export type FinalBetaMemory = {
  id: string;
  title: string;
  summary: string;
  ago: string;
  kind: MemoryKind;
  kindLabel: string;
  tone: "purple" | "green" | "cyan" | "gold" | "blue";
  icon: string;
  status: string;
  created: string;
  lastUsed: string;
  relevance: number;
  relevanceLabel: string;
  project: string;
  tags: string[];
  source: string;
  links: number;
  content: string[];
  related: Array<{ title: string; ago: string; icon: string; tone: string }>;
};

export const MEMORY_STATS = [
  {
    id: "total",
    label: "Totaal herinneringen",
    value: "4.327",
    hint: "+12% in alle categorieën",
    icon: "database",
    tone: "cyan",
  },
  {
    id: "persistent",
    label: "Persistente herinneringen",
    value: "618",
    hint: "+8% Lange termijn context",
    icon: "bolt",
    tone: "gold",
  },
  {
    id: "project",
    label: "Projectherinneringen",
    value: "2.641",
    hint: "+15% in 24 projecten",
    icon: "folder",
    tone: "green",
  },
  {
    id: "prefs",
    label: "Persoonlijke voorkeuren",
    value: "328",
    hint: "+6% Instellingen, stijl en doelen",
    icon: "user",
    tone: "purple",
  },
  {
    id: "health",
    label: "Geheugen gezondheid",
    value: "98%",
    hint: "Sterk en consistent",
    icon: "shield",
    tone: "green",
  },
] as const;

export const MEMORY_CATEGORIES = [
  { label: "Persistente herinneringen", count: 618, color: "#f0b429" },
  { label: "Projectherinneringen", count: 2641, color: "#20e38d" },
  { label: "Persoonlijke voorkeuren", count: 328, color: "#9b5cff" },
  { label: "Feiten & context", count: 512, color: "#1aa4ff" },
  { label: "Sessiegeheugen", count: 228, color: "#20c8e8" },
] as const;

export const MEMORY_TAGS = [
  { tag: "#hades", count: 428 },
  { tag: "#ai", count: 312 },
  { tag: "#eu", count: 274 },
  { tag: "#trading", count: 198 },
  { tag: "#research", count: 176 },
  { tag: "#voorkeur", count: 154 },
  { tag: "#analyse", count: 141 },
  { tag: "#project", count: 128 },
  { tag: "#context", count: 97 },
  { tag: "#agents", count: 84 },
] as const;

export const MEMORY_HEALTH_CHECKS = [
  { label: "Consistente context", value: "Uitstekend", tone: "green" },
  { label: "Geen conflicterende herinneringen", value: "OK", tone: "green" },
  { label: "Recente activiteit", value: "Actief", tone: "cyan" },
  { label: "Relevante koppelingen", value: "Optimaal", tone: "green" },
] as const;

export const MEMORY_CHATS = [
  { title: "EU AI Act — strategische impact", date: "17 sep 2026", count: 12 },
  { title: "HADES Chat-primary IA", date: "16 sep 2026", count: 9 },
  { title: "Trading Lab risk caps", date: "15 sep 2026", count: 7 },
  { title: "Knowledge graph clusters", date: "14 sep 2026", count: 11 },
] as const;

export const MEMORY_PROJECTS = [
  { title: "EU AI regulering", count: 426, tone: "gold" },
  { title: "HADES ontwikkeling", count: 291, tone: "cyan" },
  { title: "Trading strategie", count: 184, tone: "green" },
  { title: "Media Control pipeline", count: 126, tone: "purple" },
] as const;

export const MEMORY_ACTIONS = [
  { label: "Nieuwe herinnering", icon: "plus" },
  { label: "Tags beheren", icon: "sliders" },
  { label: "Herinneringen exporteren", icon: "download" },
  { label: "Context samenvatten", icon: "book" },
  { label: "Duplicaten controleren", icon: "copy" },
  { label: "Geheugen optimaliseren", icon: "bolt" },
] as const;

export const mockMemories: FinalBetaMemory[] = [
  {
    id: "m1",
    title: "Voorkeur: Analyse stijl",
    summary: "Heldere samenvatting bovenaan, daarna diepgang en concrete aanbevelingen.",
    ago: "12m",
    kind: "preference",
    kindLabel: "Voorkeur",
    tone: "purple",
    icon: "user",
    status: "Actief",
    created: "17 sep 2026, 11:12",
    lastUsed: "17 sep 2026, 13:05",
    relevance: 94,
    relevanceLabel: "Zeer hoog",
    project: "Algemeen",
    tags: ["#voorkeur", "#analyse", "#stijl"],
    source: "Gesprek met HADES",
    links: 14,
    content: [
      "Heldere samenvatting bovenaan",
      "Concrete aanbevelingen met prioriteit",
      "Bronnen kort en verifieerbaar",
      "Geen opgeblazen jargon",
      "Altijd lokale/offline fallback benoemen",
    ],
    related: [
      { title: "Voorkeur: Antwoordlengte", ago: "2u", icon: "user", tone: "purple" },
      { title: "Project: EU AI Act framing", ago: "1d", icon: "folder", tone: "green" },
      { title: "Fact: Chat-primary IA", ago: "2d", icon: "book", tone: "cyan" },
      { title: "Voorkeur: Nederlandse UI", ago: "3d", icon: "user", tone: "purple" },
      { title: "Persistente: Werkstijl Strijder", ago: "5d", icon: "shield", tone: "gold" },
    ],
  },
  {
    id: "m2",
    title: "Project: EU AI regulering",
    summary: "Kernrisico’s, compliance-paden en impact op lokale AI-workspaces.",
    ago: "2u",
    kind: "project",
    kindLabel: "Project",
    tone: "green",
    icon: "folder",
    status: "Actief",
    created: "12 sep 2026, 09:40",
    lastUsed: "17 sep 2026, 11:50",
    relevance: 88,
    relevanceLabel: "Hoog",
    project: "EU AI regulering",
    tags: ["#eu", "#ai", "#policy"],
    source: "Research + Evidence Vault",
    links: 26,
    content: [
      "Focus op high-risk AI systemen",
      "Documenteer data provenance",
      "Koppel evidence aan claims",
    ],
    related: [
      { title: "Evidence: AI Act samenvatting", ago: "1d", icon: "shield", tone: "gold" },
      { title: "Chat: strategische impact", ago: "1d", icon: "chat", tone: "cyan" },
    ],
  },
  {
    id: "m3",
    title: "Persistent: Offline-first beleid",
    summary: "Netwerkfeatures falen stil naar lokale werking; geen cloud-afhankelijkheid.",
    ago: "5u",
    kind: "persistent",
    kindLabel: "Persistent",
    tone: "gold",
    icon: "shield",
    status: "Actief",
    created: "2 sep 2026, 14:18",
    lastUsed: "17 sep 2026, 08:22",
    relevance: 91,
    relevanceLabel: "Zeer hoog",
    project: "HADES ontwikkeling",
    tags: ["#hades", "#offline", "#policy"],
    source: "AGENTS.md / productrichting",
    links: 19,
    content: [
      "Internet is optioneel",
      "Lokale LM Studio blijft primaire runtime",
      "Failures moeten actionable en lokaal zijn",
    ],
    related: [{ title: "Fact: LM Studio gateway", ago: "4d", icon: "database", tone: "cyan" }],
  },
  {
    id: "m4",
    title: "Fact: Hardware RTX 4090 24GB",
    summary: "Lokale VRAM-capaciteit voor training en inference budgeting.",
    ago: "1d",
    kind: "fact",
    kindLabel: "Feit",
    tone: "cyan",
    icon: "database",
    status: "Actief",
    created: "28 aug 2026, 10:05",
    lastUsed: "16 sep 2026, 19:40",
    relevance: 72,
    relevanceLabel: "Hoog",
    project: "HADES ontwikkeling",
    tags: ["#hardware", "#vram"],
    source: "System metrics",
    links: 6,
    content: ["GPU: RTX 4090", "VRAM: 24GB", "Gebruik voor ATME dual memory"],
    related: [],
  },
  {
    id: "m5",
    title: "Voorkeur: Nederlandse interface",
    summary: "UI-copy en labels primair in het Nederlands houden.",
    ago: "1d",
    kind: "preference",
    kindLabel: "Voorkeur",
    tone: "purple",
    icon: "user",
    status: "Actief",
    created: "5 sep 2026, 16:12",
    lastUsed: "17 sep 2026, 12:01",
    relevance: 85,
    relevanceLabel: "Hoog",
    project: "Algemeen",
    tags: ["#voorkeur", "#ui", "#nl"],
    source: "Gesprek met HADES",
    links: 8,
    content: ["Labels in het Nederlands", "Behoud Engelse producttermen waar nodig"],
    related: [],
  },
  {
    id: "m6",
    title: "Project: Trading Lab risk caps",
    summary: "Paper-only limieten en geen live broker executie in Lab.",
    ago: "2d",
    kind: "project",
    kindLabel: "Project",
    tone: "green",
    icon: "folder",
    status: "Actief",
    created: "8 sep 2026, 11:33",
    lastUsed: "15 sep 2026, 17:10",
    relevance: 79,
    relevanceLabel: "Hoog",
    project: "Trading strategie",
    tags: ["#trading", "#risk"],
    source: "Trading Lab docs",
    links: 11,
    content: ["Simulation/paper only", "Risk caps verplicht in backtests"],
    related: [],
  },
  {
    id: "m7",
    title: "Sessie: Context compiler tuning",
    summary: "Tokenbudget en retrieval ranking tijdelijk aangescherpt.",
    ago: "3d",
    kind: "session",
    kindLabel: "Sessie",
    tone: "blue",
    icon: "clock",
    status: "Actief",
    created: "14 sep 2026, 13:20",
    lastUsed: "14 sep 2026, 18:02",
    relevance: 61,
    relevanceLabel: "Medium",
    project: "HADES ontwikkeling",
    tags: ["#context", "#runtime"],
    source: "Work Runtime",
    links: 4,
    content: ["Lagere default temperature in coding", "Prioriteer lokale knowledge hits"],
    related: [],
  },
  {
    id: "m8",
    title: "Persistent: Chat-primary richting",
    summary: "Eind-tot-eind workflows via Chat; Advanced consoles blijven beschikbaar.",
    ago: "4d",
    kind: "persistent",
    kindLabel: "Persistent",
    tone: "gold",
    icon: "shield",
    status: "Actief",
    created: "1 sep 2026, 09:00",
    lastUsed: "16 sep 2026, 21:14",
    relevance: 96,
    relevanceLabel: "Zeer hoog",
    project: "HADES ontwikkeling",
    tags: ["#hades", "#chat", "#ia"],
    source: "Productrichting D018",
    links: 22,
    content: ["Chat is primary surface", "Geen autonome Gen2 backlog"],
    related: [],
  },
];
