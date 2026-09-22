export type SubMenuItem = {
  id: string;
  label: string;
  /** Dedicated route — every submenu item has a real page. */
  to: string;
};

export type MainMenuItem = {
  id: string;
  label: string;
  /** Default landing route when the hoofdmenu item is clicked. */
  to: string;
  /** Path prefixes that keep this hoofdmenu item active. */
  match: readonly string[];
  submenu: readonly SubMenuItem[];
};

/**
 * HOOFDMENU (left sidebar) + SUBMENU (footer dock under the middle box).
 * Every submenu item has its own route.
 */
export const MAIN_MENU: readonly MainMenuItem[] = [
  {
    id: "hades",
    label: "Hades AI",
    to: "/",
    match: ["/", "/chat", "/coding", "/tasks", "/status"],
    submenu: [
      { id: "chatten", label: "Chatten", to: "/chat" },
      { id: "coding", label: "Coding", to: "/coding" },
      { id: "taken", label: "Taken", to: "/tasks" },
    ],
  },
  {
    id: "llm",
    label: "LLM",
    to: "/models",
    match: ["/models", "/training", "/agents", "/analytics"],
    submenu: [
      { id: "modellen", label: "Modellen", to: "/models" },
      { id: "training", label: "Model Training", to: "/training" },
      { id: "agents", label: "Agents", to: "/agents" },
      { id: "stats", label: "Stats", to: "/analytics" },
    ],
  },
  {
    id: "media",
    label: "Media Control",
    to: "/media",
    match: ["/media"],
    submenu: [
      { id: "overzicht", label: "Overzicht", to: "/media" },
      { id: "youtube", label: "Youtube", to: "/media/youtube" },
      { id: "tiktok", label: "Tiktok", to: "/media/tiktok" },
      { id: "instagram", label: "Instagram", to: "/media/instagram" },
      { id: "facebook", label: "Facebook", to: "/media/facebook" },
      { id: "queue", label: "Publicatiewachtrij", to: "/media/queue" },
      { id: "viral", label: "Viral radar", to: "/media/viral" },
      { id: "calendar", label: "Calender", to: "/media/calendar" },
      { id: "media-analytics", label: "Analytics", to: "/media/analytics" },
      { id: "library", label: "Bibliotheek", to: "/media/library" },
      { id: "personas", label: "Personas", to: "/media/personas" },
    ],
  },
  {
    id: "trading",
    label: "TradingCenter",
    to: "/trading",
    match: ["/trading"],
    submenu: [
      { id: "simulatie", label: "Simulatie", to: "/trading" },
      { id: "strategieen", label: "Strategieen", to: "/trading/strategieen" },
      { id: "marktdata", label: "Marktdata", to: "/trading/marktdata" },
      { id: "portefeuille", label: "Portefeuille", to: "/trading/portefeuille" },
      { id: "paper", label: "PAPER trading", to: "/trading/paper" },
      { id: "broker", label: "BROKER trading", to: "/trading/broker" },
    ],
  },
  {
    id: "research",
    label: "Onderzoek & Kennis",
    to: "/research",
    match: ["/research", "/brain", "/memory", "/knowledge", "/evidence", "/datasets"],
    submenu: [
      { id: "research", label: "Research", to: "/research" },
      { id: "brain", label: "Brain", to: "/brain" },
      { id: "geheugen", label: "Geheugen", to: "/memory" },
      { id: "knowledge", label: "Knowledge Library", to: "/knowledge" },
      { id: "evidence", label: "Evidence Vault", to: "/evidence" },
      { id: "bestanden", label: "Bestanden", to: "/datasets" },
    ],
  },
  {
    id: "runtime",
    label: "Plugin & Runtime",
    to: "/tools",
    match: ["/tools", "/performance", "/mcp", "/workflows", "/console"],
    submenu: [
      { id: "performance", label: "Performance", to: "/performance" },
      { id: "modules", label: "Modules", to: "/tools" },
      { id: "mcp", label: "MCP", to: "/mcp" },
      { id: "workflows", label: "Workflows", to: "/workflows" },
      { id: "console", label: "Console", to: "/console" },
    ],
  },
  {
    id: "settings",
    label: "Instellingen",
    to: "/settings",
    match: ["/settings"],
    submenu: [
      { id: "algemeen", label: "Algemeen", to: "/settings" },
      { id: "llm-gedrag", label: "LLM Gedrag", to: "/settings/llm-gedrag" },
      { id: "llm-studio", label: "LLM Studio", to: "/settings/llm-studio" },
      { id: "rechten", label: "Rechten & Security", to: "/settings/rechten" },
      { id: "benchmarks", label: "Model Benchmarks", to: "/settings/benchmarks" },
      { id: "mediacenter", label: "Mediacenter", to: "/settings/mediacenter" },
      { id: "opslag", label: "Opslag", to: "/settings/opslag" },
      { id: "python", label: "Python & Runtime", to: "/settings/python" },
      { id: "settings-console", label: "Console", to: "/settings/console" },
      { id: "logs", label: "Logs", to: "/settings/logs" },
    ],
  },
] as const;

export function normalizePath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function findMainMenuByPath(pathname: string): MainMenuItem {
  const path = normalizePath(pathname);

  // Prefer the longest matching prefix so /media/youtube stays under Media, not a shorter miss.
  let best: MainMenuItem | null = null;
  let bestLen = -1;

  for (const item of MAIN_MENU) {
    for (const prefix of item.match) {
      const normalized = normalizePath(prefix);
      if (normalized === "/") {
        if (path === "/" && bestLen < 1) {
          best = item;
          bestLen = 1;
        }
        continue;
      }
      if (path === normalized || path.startsWith(`${normalized}/`)) {
        if (normalized.length > bestLen) {
          best = item;
          bestLen = normalized.length;
        }
      }
    }
  }

  return best ?? MAIN_MENU[0];
}

export function isMainMenuActive(item: MainMenuItem, pathname: string): boolean {
  return findMainMenuByPath(pathname).id === item.id;
}

export function findSubMenuItem(section: MainMenuItem, pathname: string): SubMenuItem | null {
  const path = normalizePath(pathname);

  const exact = section.submenu.find((item) => normalizePath(item.to) === path);
  if (exact) return exact;

  // Longest dedicated route that owns this path (for nested pages).
  let best: SubMenuItem | null = null;
  let bestLen = -1;
  for (const item of section.submenu) {
    const to = normalizePath(item.to);
    if (to === "/") continue;
    if (path === to || path.startsWith(`${to}/`)) {
      if (to.length > bestLen) {
        best = item;
        bestLen = to.length;
      }
    }
  }
  if (best) return best;

  // Section landing (e.g. Hades AI → dashboard) may have no matching submenu route.
  if (normalizePath(section.to) === path) return null;

  return section.submenu[0] ?? null;
}

export function allSubMenuRoutes(): readonly SubMenuItem[] {
  return MAIN_MENU.flatMap((section) => [...section.submenu]);
}
