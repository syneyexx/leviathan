export type EvidenceClaimStatus = "verified" | "review" | "conflict";

export type FinalBetaEvidenceClaim = {
  id: string;
  title: string;
  topic: string;
  reliability: number;
  updated: string;
  status: EvidenceClaimStatus;
  statusLabel: string;
  firstSeen: string;
  lastUpdate: string;
  tags: string[];
  summary: string;
  lastValidation: string;
  relatedCount: number;
};

export type EvidenceChainStep = {
  id: string;
  step: number;
  title: string;
  kind: string;
  source: string;
  reliability: number;
  badge: "Primair" | "Secundair";
  badgeTone: "green" | "blue";
};

export const EVIDENCE_STATS = [
  {
    id: "claims",
    label: "Geverifieerde claims",
    value: "4.892",
    trend: "+18%",
    trendTone: "up" as const,
    hint: "Waarvan 87% hoge betrouwbaarheid",
    icon: "checkcircle",
    tone: "cyan",
  },
  {
    id: "sources",
    label: "Bronnen in vault",
    value: "2.107",
    trend: "+16%",
    trendTone: "up" as const,
    hint: "Unieke documenten en datasets",
    icon: "link",
    tone: "cyan",
  },
  {
    id: "reliability",
    label: "Gemiddelde betrouwbaarheid",
    value: "92%",
    trend: "+4%",
    trendTone: "up" as const,
    hint: "Van alle actieve claims",
    icon: "shield",
    tone: "green",
  },
  {
    id: "chains",
    label: "Bewijsketens",
    value: "1.236",
    trend: "+23%",
    trendTone: "up" as const,
    hint: "Meervoudig onderbouwd",
    icon: "target",
    tone: "cyan",
  },
  {
    id: "conflicts",
    label: "Conflicten",
    value: "112",
    trend: "-27%",
    trendTone: "down" as const,
    hint: "Tegenstrijdige claims",
    icon: "flask",
    tone: "gold",
  },
  {
    id: "sync",
    label: "Sync status",
    value: "Online",
    valueTone: "green" as const,
    hint: "Laatste sync: 2m geleden",
    icon: "refresh",
    tone: "green",
  },
] as const;

export const EVIDENCE_TOPICS = [
  "AI-regulering",
  "Geopolitiek",
  "Energietransitie",
  "Defensie",
  "Cybersecurity",
  "Monetaire politiek",
  "Technologische adoptie",
] as const;

export const EVIDENCE_VIEWS = [
  { id: "list", label: "Lijst", icon: "list" },
  { id: "timeline", label: "Tijdlijn", icon: "clock" },
  { id: "graph", label: "Graph", icon: "target" },
] as const;

export const EVIDENCE_VALIDATION_SLICES = [
  { label: "Geverifieerd", count: 4256, pct: "87%", color: "#20e38d" },
  { label: "Waarschijnlijk", count: 392, pct: "8%", color: "#7dd87a" },
  { label: "Onzeker", count: 147, pct: "3%", color: "#f0b429" },
  { label: "Tegenstrijdig", count: 97, pct: "2%", color: "#e85b5b" },
] as const;

export const EVIDENCE_SOURCE_BARS = [
  { label: "Wetenschappelijke artikelen", pct: 32, count: "1.567", icon: "file", width: 90 },
  { label: "Nieuws en media", pct: 18, count: "899", icon: "calendar", width: 50 },
  { label: "Overheidsdocumenten", pct: 16, count: "781", icon: "shield", width: 42 },
  { label: "Rapporten & whitepapers", pct: 22, count: "1.076", icon: "book", width: 62 },
  { label: "Websites", pct: 8, count: "391", icon: "globe", width: 22 },
  { label: "Interne documenten", pct: 4, count: "178", icon: "folder", width: 12 },
] as const;

export const EVIDENCE_ACTIVITY = [
  {
    id: "a1",
    label: "Claim geverifieerd",
    detail: "AI Act treedt gefaseerd in werking vanaf 2024",
    ago: "2m geleden",
    icon: "checkcircle",
    tone: "green",
  },
  {
    id: "a2",
    label: "Nieuwe bron toegevoegd",
    detail: "Commission press release",
    ago: "12m geleden",
    icon: "upload",
    tone: "cyan",
  },
  {
    id: "a3",
    label: "Conflict gedetecteerd",
    detail: "China chip productie cijfers",
    ago: "34m geleden",
    icon: "flask",
    tone: "gold",
  },
  {
    id: "a4",
    label: "Claim bijgewerkt",
    detail: "EU energie transitie 2025",
    ago: "1h geleden",
    icon: "sliders",
    tone: "blue",
  },
  {
    id: "a5",
    label: "Bron gelinkt",
    detail: "Expert analyse toegevoegd",
    ago: "2h geleden",
    icon: "link",
    tone: "cyan",
  },
] as const;

export const EVIDENCE_AUDIT_ACTIONS = [
  { label: "Claim herbeoordelen", icon: "search" },
  { label: "Conflicten analyseren", icon: "flask" },
  { label: "Validatielog bekijken", icon: "list" },
  { label: "Exporteren", icon: "download" },
  { label: "Toevoegen aan rapport", icon: "file" },
  { label: "Deel link", icon: "link" },
] as const;

export const EVIDENCE_CHAIN: EvidenceChainStep[] = [
  {
    id: "c1",
    step: 1,
    title: "EU AI Act (2024/1689)",
    kind: "Primair document",
    source: "EU Official Journal • 13 mrt 2024",
    reliability: 98,
    badge: "Primair",
    badgeTone: "green",
  },
  {
    id: "c2",
    step: 2,
    title: "Analyse implementatietijdlijn AI Act",
    kind: "Analytische bron",
    source: "European Commission • 7 apr 2024",
    reliability: 92,
    badge: "Secundair",
    badgeTone: "blue",
  },
  {
    id: "c3",
    step: 3,
    title: "Expert analyse: fasering en implicaties",
    kind: "Expert rapport",
    source: "Bruegel • 21 apr 2024",
    reliability: 89,
    badge: "Secundair",
    badgeTone: "blue",
  },
  {
    id: "c4",
    step: 4,
    title: "Wetenschappelijk artikel",
    kind: "Peer-reviewed",
    source: "Nature AI & Society • 12 mei 2024",
    reliability: 87,
    badge: "Secundair",
    badgeTone: "blue",
  },
];

export const EVIDENCE_SOURCES = [
  {
    id: "s1",
    title: "EU AI Act (2024/1689)",
    meta: "EUR-Lex • 13 mrt 2024",
    badge: "Primair" as const,
    badgeTone: "green" as const,
  },
  {
    id: "s2",
    title: "Commission implementation guide",
    meta: "European Commission • 7 apr 2024",
    badge: "Secundair" as const,
    badgeTone: "blue" as const,
  },
  {
    id: "s3",
    title: "Economic impact assessment",
    meta: "Bruegel • 21 apr 2024",
    badge: "Secundair" as const,
    badgeTone: "blue" as const,
  },
  {
    id: "s4",
    title: "Legal analysis AI Act",
    meta: "Nature AI & Society • 12 mei 2024",
    badge: "Secundair" as const,
    badgeTone: "blue" as const,
  },
] as const;

export const mockEvidenceClaims: FinalBetaEvidenceClaim[] = [
  {
    id: "ev1",
    title: "AI Act treedt gefaseerd in werking vanaf 2024",
    topic: "EU Regulering",
    reliability: 98,
    updated: "17 sep",
    status: "verified",
    statusLabel: "Geverifieerd",
    firstSeen: "12 mrt 2024, 09:14",
    lastUpdate: "17 sep 2026, 11:43",
    tags: ["EU", "AI", "Wetgeving", "Regulering"],
    summary:
      "De EU AI Act (2024/1689) treedt gefaseerd in werking met verschillende implementatiedata per artikel en risicocategorie.",
    lastValidation: "17 sep 2026, 11:43 door HADES AI",
    relatedCount: 12,
  },
  {
    id: "ev2",
    title: "Europa investeert €200B in AI-infrastructuur",
    topic: "Technologie",
    reliability: 95,
    updated: "16 sep",
    status: "verified",
    statusLabel: "Geverifieerd",
    firstSeen: "2 jun 2024, 10:02",
    lastUpdate: "16 sep 2026, 18:20",
    tags: ["EU", "AI", "Infrastructuur"],
    summary: "Europese investeringsplannen bundelen kapitaal voor AI-datacenters, chips en onderzoek.",
    lastValidation: "16 sep 2026, 18:20 door HADES AI",
    relatedCount: 8,
  },
  {
    id: "ev3",
    title: "China versnelt productie van geavanceerde AI-chips",
    topic: "Geopolitiek",
    reliability: 78,
    updated: "16 sep",
    status: "review",
    statusLabel: "In review",
    firstSeen: "18 jul 2024, 14:33",
    lastUpdate: "16 sep 2026, 09:11",
    tags: ["China", "Chips", "Geopolitiek"],
    summary: "Meerdere bronnen melden versnelde capaciteitsuitbreiding; cijfers conflicteren nog.",
    lastValidation: "16 sep 2026, 09:11 door HADES AI",
    relatedCount: 15,
  },
  {
    id: "ev4",
    title: "Hernieuwbare energie overtreft kolen in EU (2025)",
    topic: "Energie",
    reliability: 92,
    updated: "15 sep",
    status: "verified",
    statusLabel: "Geverifieerd",
    firstSeen: "4 jan 2025, 08:40",
    lastUpdate: "15 sep 2026, 16:05",
    tags: ["Energie", "EU", "Transitie"],
    summary: "Eurostat-cijfers tonen hernieuwbare opwek boven kolen over het kalenderjaar 2025.",
    lastValidation: "15 sep 2026, 16:05 door HADES AI",
    relatedCount: 6,
  },
  {
    id: "ev5",
    title: "VS overweegt exportrestricties op AI-modellen",
    topic: "Geopolitiek",
    reliability: 61,
    updated: "15 sep",
    status: "conflict",
    statusLabel: "Conflict",
    firstSeen: "22 aug 2025, 11:18",
    lastUpdate: "15 sep 2026, 12:44",
    tags: ["VS", "Export", "AI"],
    summary: "Tegenstrijdige signalen uit beleidsdocumenten en media over reikwijdte van restricties.",
    lastValidation: "15 sep 2026, 12:44 door HADES AI",
    relatedCount: 11,
  },
  {
    id: "ev6",
    title: "Quantum computing bereikt commerciële pilotfase",
    topic: "Technologie",
    reliability: 88,
    updated: "14 sep",
    status: "verified",
    statusLabel: "Geverifieerd",
    firstSeen: "9 mrt 2025, 13:22",
    lastUpdate: "14 sep 2026, 19:30",
    tags: ["Quantum", "Technologie"],
    summary: "Eerste commerciële pilots draaien in finance en materials; schaalbaarheid blijft beperkt.",
    lastValidation: "14 sep 2026, 19:30 door HADES AI",
    relatedCount: 5,
  },
  {
    id: "ev7",
    title: "Inflatie in EU daalt naar 2,4%",
    topic: "Economie",
    reliability: 76,
    updated: "13 sep",
    status: "review",
    statusLabel: "In review",
    firstSeen: "1 sep 2026, 07:55",
    lastUpdate: "13 sep 2026, 08:12",
    tags: ["Inflatie", "EU", "Economie"],
    summary: "Voorlopige Eurostat-raming; definitieve publicatie volgt later deze maand.",
    lastValidation: "13 sep 2026, 08:12 door HADES AI",
    relatedCount: 4,
  },
  {
    id: "ev8",
    title: "EU stelt AI Governance Board in",
    topic: "EU Regulering",
    reliability: 93,
    updated: "14 sep",
    status: "verified",
    statusLabel: "Geverifieerd",
    firstSeen: "30 mei 2025, 10:00",
    lastUpdate: "14 sep 2026, 15:18",
    tags: ["EU", "Governance", "AI"],
    summary: "Nieuwe board coördineert toezicht en implementatie van de AI Act over lidstaten.",
    lastValidation: "14 sep 2026, 15:18 door HADES AI",
    relatedCount: 9,
  },
];
