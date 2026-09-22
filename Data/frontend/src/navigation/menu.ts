export type SubMenuItem = {
  id: string;
  label: string;
  /** Dedicated route when the item has its own page. */
  to?: string;
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
 * HOOFDMENU (left) + SUBMENU (under the middle content box).
 * Existing pages are wired via `to`; items without a page stay section-local tabs.
 */
export const MAIN_MENU: readonly MainMenuItem[] = [
  {
    id: "hades",
    label: "Hades AI",
    to: "/",
    match: ["/", "/chat", "/coding", "/tasks", "/status"],
    submenu: [
      { id: "chatten", label: "Chatten", to: "/chat" },
      { id: "coding", label: "Coding Agent", to: "/coding" },
      { id: "taken", label: "Taken", to: "/tasks" },
    ],
  },
  {
    id: "llm",
    label: "LLM",
    to: "/models",
    match: ["/models", "/training", "/analytics"],
    submenu: [
      { id: "modellen", label: "Modellen", to: "/models" },
      { id: "training", label: "Model Training", to: "/training" },
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
      { id: "youtube", label: "YouTube", to: "/media/youtube" },
      { id: "tiktok", label: "TikTok", to: "/media/tiktok" },
      { id: "instagram", label: "Instagram", to: "/media/instagram" },
      { id: "facebook", label: "Facebook", to: "/media/facebook" },
      { id: "queue", label: "Algemene publicatiewachtrij" },
      { id: "viral", label: "Viral radar" },
      { id: "calendar", label: "Calender" },
      { id: "media-analytics", label: "Analytics" },
      { id: "library", label: "Bibliotheek" },
      { id: "personas", label: "Personas" },
    ],
  },
  {
    id: "agents",
    label: "Agents",
    to: "/agents",
    match: ["/agents"],
    submenu: [
      { id: "fleet", label: "Fleet", to: "/agents" },
      { id: "workflows", label: "Workflows" },
      { id: "memory", label: "Memory" },
    ],
  },
  {
    id: "trading",
    label: "TradingCenter",
    to: "/trading",
    match: ["/trading"],
    submenu: [
      { id: "simulatie", label: "Simulatie", to: "/trading" },
      { id: "strategieen", label: "Strategieen" },
      { id: "marktdata", label: "Marktdata" },
      { id: "portefeuille", label: "Portefeuille" },
      { id: "paper", label: "PAPER trading" },
      { id: "broker", label: "BROKER trading" },
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
      { id: "llm-gedrag", label: "LLM Gedrag" },
      { id: "llm-studio", label: "LLM Studio" },
      { id: "rechten", label: "Rechten & Security" },
      { id: "benchmarks", label: "Model Benchmarks" },
      { id: "mediacenter", label: "Mediacenter" },
      { id: "opslag", label: "Opslag" },
      { id: "python", label: "Python & Runtime" },
      { id: "settings-console", label: "Console" },
      { id: "logs", label: "Logs" },
    ],
  },
] as const;

export function normalizePath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

export function findMainMenuByPath(pathname: string): MainMenuItem {
  const path = normalizePath(pathname);

  for (const item of MAIN_MENU) {
    for (const prefix of item.match) {
      const normalized = normalizePath(prefix);
      if (normalized === "/") {
        if (path === "/") return item;
        continue;
      }
      if (path === normalized || path.startsWith(`${normalized}/`)) {
        return item;
      }
    }
  }

  return MAIN_MENU[0];
}

export function isMainMenuActive(item: MainMenuItem, pathname: string): boolean {
  return findMainMenuByPath(pathname).id === item.id;
}

export function findSubMenuItem(
  section: MainMenuItem,
  pathname: string,
  tab: string | null,
): SubMenuItem | null {
  const path = normalizePath(pathname);

  if (tab) {
    const byTab = section.submenu.find((item) => item.id === tab);
    if (byTab) return byTab;
  }

  const byRoute = section.submenu.find((item) => item.to && normalizePath(item.to) === path);
  if (byRoute) return byRoute;

  // Prefer the submenu item whose dedicated route owns this path.
  for (const item of section.submenu) {
    if (!item.to) continue;
    const to = normalizePath(item.to);
    if (to !== "/" && (path === to || path.startsWith(`${to}/`))) return item;
  }

  // Section landing (e.g. Hades AI → dashboard) may have no matching submenu route.
  if (normalizePath(section.to) === path) return null;

  return section.submenu[0] ?? null;
}

export function submenuHref(section: MainMenuItem, item: SubMenuItem): string {
  if (item.to) return item.to;
  const base = section.to === "/" ? "/" : section.to;
  return `${base}?tab=${encodeURIComponent(item.id)}`;
}
