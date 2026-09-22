import type {
  FinalBetaHoofdmenuId,
  FinalBetaHoofdmenuSection,
  FinalBetaPageId,
} from "./types";

/** Canonical navigable pages (excludes deprecated redirect aliases). */
export const FINALBETA_PAGES: FinalBetaPageId[] = [
  "login",
  "dashboard",
  "chat",
  "coding",
  "tasks",
  "models",
  "model-training",
  "agents",
  "llm-stats",
  "dataset-management",
  "offline-datasets",
  "datasets",
  "media",
  "youtube",
  "tiktok",
  "instagram",
  "facebook",
  "media-queue",
  "media-viral",
  "media-calendar",
  "media-analytics",
  "media-library",
  "media-personas",
  "trading",
  "trading-simulation",
  "trading-strategies",
  "trading-marketdata",
  "trading-portfolio",
  "trading-paper",
  "trading-broker",
  "research",
  "brain",
  "memory",
  "knowledge",
  "evidence",
  "files",
  "performance",
  "tools",
  "mcp",
  "workflows",
  "settings-general",
  "settings-interface",
  "settings-llm-behavior",
  "settings-llm-studio",
  "settings-security",
  "settings-benchmarks",
  "settings-storage",
  "settings-python",
  "settings-console",
  "settings-logs",
  "settings-backups",
  // Deprecated aliases kept for hash compatibility
  "mission-control",
  "settings",
  "system",
];

export const FINALBETA_PAGE_LABELS: Record<FinalBetaPageId, string> = {
  login: "Login",
  dashboard: "Dashboard",
  chat: "Chatten",
  coding: "Coding",
  tasks: "Taken",
  models: "Modellen",
  "model-training": "Training",
  agents: "Agents",
  "llm-stats": "Statestieken",
  "dataset-management": "Dataset Management",
  "offline-datasets": "Offline Datasets",
  datasets: "Datasets",
  media: "Overzicht",
  youtube: "Youtube",
  tiktok: "Tiktok",
  instagram: "Instagram",
  facebook: "Facebook",
  "media-queue": "Algemene publicatiewachtrij",
  "media-viral": "Viral radar",
  "media-calendar": "Calendar",
  "media-analytics": "Analytics",
  "media-library": "Bibliotheek",
  "media-personas": "Personas",
  trading: "Overzicht",
  "trading-simulation": "Simulatie",
  "trading-strategies": "Strategieën",
  "trading-marketdata": "Marktdata",
  "trading-portfolio": "Portefeuille",
  "trading-paper": "Paper trading",
  "trading-broker": "Broker trading",
  research: "Research",
  brain: "Brain",
  memory: "Geheugen",
  knowledge: "Knowledge Library",
  evidence: "Evidence Vault",
  files: "Bestanden",
  performance: "Performance",
  tools: "Plugins",
  mcp: "MCP",
  workflows: "Workflows",
  "settings-general": "Algemeen",
  "settings-interface": "Interface",
  "settings-llm-behavior": "LLM Gedrag",
  "settings-llm-studio": "LLM Studio",
  "settings-security": "Rechten & Security",
  "settings-benchmarks": "Model Benchmarks",
  "settings-storage": "Opslag",
  "settings-python": "Python & Runtime",
  "settings-console": "Console",
  "settings-logs": "Logs",
  "settings-backups": "Backups & Configuratie",
  "mission-control": "Taken",
  settings: "Algemeen",
  system: "Console",
};

/** Legacy hash → canonical page. */
export function resolveFinalBetaPageId(page: FinalBetaPageId): FinalBetaPageId {
  if (page === "mission-control") return "tasks";
  if (page === "settings") return "settings-general";
  if (page === "system") return "settings-console";
  if (page === "files") return "datasets";
  return page;
}

/**
 * HOOFDMENU (top) + SUBMENU (left).
 * Clicking a HOOFDMENU item opens its home page and swaps the SUBMENU.
 */
export const FINALBETA_HOOFDMENU: FinalBetaHoofdmenuSection[] = [
  {
    id: "hades-ai",
    label: "Hades AI",
    home: "dashboard",
    submenu: [
      { id: "dashboard", label: "Dashboard", icon: "grid", desc: "Overzicht en status" },
      { id: "chat", label: "Chatten", icon: "chat", desc: "Gesprekken en taken" },
      { id: "coding", label: "Coding", icon: "code", desc: "Patches & sandbox" },
      { id: "tasks", label: "Taken", icon: "check", desc: "Work Runtime & missies" },
    ],
  },
  {
    id: "llm",
    label: "LLM",
    home: "models",
    submenu: [
      { id: "models", label: "Modellen", icon: "database", desc: "Lokale modelcatalogus" },
      { id: "agents", label: "Agents", icon: "users", desc: "Specialisten" },
      { id: "model-training", label: "Training", icon: "bolt", desc: "Fine-tune & ATME" },
      { id: "dataset-management", label: "Dataset Management", icon: "folder", desc: "Bibliotheek & imports" },
      { id: "offline-datasets", label: "Offline Datasets", icon: "download", desc: "Lokale packages & sync" },
      { id: "llm-stats", label: "Statestieken", icon: "chart", desc: "Tokens, geheugen & training" },
    ],
  },
  {
    id: "media-control",
    label: "Media Control",
    home: "media",
    submenu: [
      { id: "media", label: "Overzicht", icon: "grid", desc: "Media dashboard" },
      { id: "youtube", label: "Youtube", icon: "play", desc: "Kanalen & uploads" },
      { id: "tiktok", label: "Tiktok", icon: "image", desc: "Short-form video" },
      { id: "instagram", label: "Instagram", icon: "image", desc: "Posts & stories" },
      { id: "facebook", label: "Facebook", icon: "users", desc: "Pagina’s & bereik" },
      { id: "media-queue", label: "Algemene publicatiewachtrij", icon: "list", desc: "Algemene wachtrij" },
      { id: "media-viral", label: "Viral radar", icon: "target", desc: "Trends & signalen" },
      { id: "media-calendar", label: "Calendar", icon: "calendar", desc: "Publicatieplanning" },
      { id: "media-analytics", label: "Analytics", icon: "chart", desc: "Bereik & conversie" },
      { id: "media-library", label: "Bibliotheek", icon: "folder", desc: "Assets & templates" },
      { id: "media-personas", label: "Personas", icon: "users", desc: "Stem & personages" },
    ],
  },
  {
    id: "trading-center",
    label: "TradingCenter",
    home: "trading",
    submenu: [
      { id: "trading", label: "Overzicht", icon: "grid", desc: "TradingCenter commandocentrum" },
      { id: "trading-marketdata", label: "Marktdata", icon: "line", desc: "Koersen & feeds" },
      { id: "trading-strategies", label: "Strategieën", icon: "list", desc: "Strategie-lab" },
      { id: "trading-simulation", label: "Simulatie", icon: "chart", desc: "Simulatieomgeving" },
      { id: "trading-portfolio", label: "Portefeuille", icon: "database", desc: "Posities & PnL" },
      { id: "trading-paper", label: "Paper trading", icon: "file", desc: "Paper accounts" },
      { id: "trading-broker", label: "Broker trading", icon: "link", desc: "Broker-koppeling" },
    ],
  },
  {
    id: "onderzoek",
    label: "Onderzoek & Kennis",
    home: "research",
    submenu: [
      { id: "research", label: "Research", icon: "search", desc: "Web & bronnen" },
      { id: "brain", label: "Brain", icon: "brain", desc: "Graph & relaties" },
      { id: "memory", label: "Geheugen", icon: "book", desc: "Langetermijngeheugen" },
      { id: "knowledge", label: "Knowledge Library", icon: "book", desc: "Kennisbank" },
      { id: "evidence", label: "Evidence Vault", icon: "shield", desc: "Bewijsstukken" },
      { id: "datasets", label: "Datasets", icon: "database", desc: "Data hub & bronnen" },
    ],
  },
  {
    id: "plugin-runtime",
    label: "Plugin & Runtime",
    home: "performance",
    submenu: [
      { id: "performance", label: "Performance", icon: "chart", desc: "Runtime metrics" },
      { id: "tools", label: "Plugins", icon: "wrench", desc: "Packages & tools" },
      { id: "mcp", label: "MCP", icon: "link", desc: "MCP servers" },
      { id: "workflows", label: "Workflows", icon: "list", desc: "Automatisering" },
      { id: "settings-console", label: "Console", icon: "terminal", desc: "Instellingen console" },
    ],
  },
  {
    id: "settings",
    label: "Instellingen",
    home: "settings-general",
    submenu: [
      { id: "settings-general", label: "Algemeen", icon: "settings", desc: "Basisvoorkeuren" },
      { id: "settings-interface", label: "Interface", icon: "image", desc: "UI-presets" },
      { id: "settings-llm-behavior", label: "LLM Gedrag", icon: "brain", desc: "Redeneerprofielen" },
      { id: "settings-llm-studio", label: "LLM Studio", icon: "database", desc: "Modelstudio" },
      { id: "settings-security", label: "Rechten & Security", icon: "shield", desc: "Policies" },
      { id: "settings-benchmarks", label: "Model Benchmarks", icon: "chart", desc: "Vergelijkingen" },
      { id: "settings-storage", label: "Opslag", icon: "folder", desc: "Databases & paden" },
      { id: "settings-python", label: "Python & Runtime", icon: "terminal", desc: "Runtime config" },
      { id: "settings-console", label: "Console", icon: "terminal", desc: "Systeemconsole" },
      { id: "settings-logs", label: "Logs", icon: "list", desc: "Logviewer" },
      { id: "settings-backups", label: "Backups & Configuratie", icon: "save", desc: "Back-up & restore" },
    ],
  },
];

export const AUTO_DESIGN_PAGES: FinalBetaPageId[] = [
  "memory",
  "files",
  "media",
  "research",
  "youtube",
  "tiktok",
  "instagram",
  "facebook",
  "model-training",
];

export function finalBetaHoofdmenu(page: FinalBetaPageId): FinalBetaHoofdmenuId {
  const resolved = resolveFinalBetaPageId(page);
  for (const section of FINALBETA_HOOFDMENU) {
    if (section.home === resolved) return section.id;
    if (section.submenu.some((item) => item.id === resolved)) return section.id;
  }
  if (resolved === "dashboard" || resolved === "login") return "hades-ai";
  return "hades-ai";
}

/** @deprecated Prefer finalBetaHoofdmenu. */
export function finalBetaTopGroup(page: FinalBetaPageId): FinalBetaHoofdmenuId {
  return finalBetaHoofdmenu(page);
}

export function finalBetaSubmenuFor(page: FinalBetaPageId) {
  const id = finalBetaHoofdmenu(page);
  return FINALBETA_HOOFDMENU.find((section) => section.id === id)?.submenu ?? [];
}

export function isFinalBetaPageId(value: string): value is FinalBetaPageId {
  return (FINALBETA_PAGES as string[]).includes(value);
}

/** Hash format: `#/fb/<page>` — isolated from Lux `#/<page>`. */
export function readFinalBetaPageFromHash(): FinalBetaPageId {
  if (typeof window === "undefined") return "login";
  const raw = window.location.hash.replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean);
  // Single hash schema for FINALBETA: only `#/fb/<page>` (F-21).
  // Bare Lux hashes (`#/chat`) are handled as explicit redirects by the app shell.
  if (parts[0] === "fb" && parts[1] && isFinalBetaPageId(parts[1])) {
    return resolveFinalBetaPageId(parts[1]);
  }
  return "login";
}

/** Map a Lux-style hash page to a FINALBETA redirect target, if any. */
export function luxHashToFinalBetaRedirect(hash: string): FinalBetaPageId | null {
  const raw = hash.replace(/^#\/?/, "");
  const parts = raw.split("/").filter(Boolean);
  if (parts[0] === "fb") return null;
  if (parts[0] && isFinalBetaPageId(parts[0])) return resolveFinalBetaPageId(parts[0]);
  return null;
}

export function finalBetaHash(page: FinalBetaPageId): string {
  return `#/fb/${resolveFinalBetaPageId(page)}`;
}
