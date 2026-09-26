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
      { id: "coding", label: "Coding Agent", to: "/coding" },
      { id: "taken", label: "Taken", to: "/tasks" },
    ],
  },
  {
    id: "llm",
    label: "LLM",
    to: "/models",
    match: ["/models", "/training", "/agents", "/analytics", "/dataset-management", "/offline-datasets"],
    submenu: [
      { id: "modellen", label: "Modellen", to: "/models" },
      { id: "agents", label: "Agents", to: "/agents" },
      { id: "training", label: "Training", to: "/training" },
      { id: "dataset-management", label: "Dataset Management", to: "/dataset-management" },
      { id: "offline-datasets", label: "Offline Datasets", to: "/offline-datasets" },
      { id: "stats", label: "Statestieken", to: "/analytics" },
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
      { id: "queue", label: "Algemene publicatiewachtrij", to: "/media/queue" },
      { id: "viral", label: "Viral Radar", to: "/media/viral" },
      { id: "calendar", label: "Calendar", to: "/media/calendar" },
      { id: "media-analytics", label: "Analytics", to: "/media/analytics" },
      { id: "library", label: "Bibliotheek", to: "/media/library" },
      { id: "personas", label: "Personas", to: "/media/personas" },
    ],
  },
  {
    id: "trading",
    label: "TradingCenter",
    to: "/trading/simulatie",
    match: ["/trading"],
    submenu: [
      { id: "simulatie", label: "Simulatie", to: "/trading/simulatie" },
      { id: "strategieen", label: "Strategieen", to: "/trading/strategieen" },
      { id: "marktdata", label: "Marktdata", to: "/trading/marktdata" },
      { id: "portefeuille", label: "Portefeuille", to: "/trading/portefeuille" },
      { id: "paper", label: "PAPER trading", to: "/trading/paper" },
      { id: "broker", label: "BROKER trading", to: "/trading/broker" },
      { id: "onderzoek", label: "Onderzoek", to: "/trading/onderzoek" },
      { id: "lab", label: "Research Lab", to: "/trading/lab" },
      { id: "control-room", label: "Control Room", to: "/trading/control-room" },
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
      { id: "datasets", label: "Datasets", to: "/datasets" },
    ],
  },
  {
    id: "runtime",
    label: "Plugin & Runtime",
    to: "/tools",
    match: ["/tools", "/modules", "/performance", "/mcp", "/workflows", "/console"],
    submenu: [
      { id: "performance", label: "Performance", to: "/performance" },
      { id: "tools", label: "Tools", to: "/tools" },
      { id: "modules", label: "Modules", to: "/modules" },
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
      { id: "algemeen", label: "Algemeen", to: "/settings?section=algemeen" },
      { id: "llm-gedrag", label: "LLM Gedrag", to: "/settings?section=llm_gedrag" },
      { id: "llm-studio", label: "LLM Studio", to: "/settings?section=llm_studio" },
      { id: "rechten", label: "Rechten & Security", to: "/settings?section=rechten" },
      { id: "benchmarks", label: "Model Benchmarks", to: "/settings?section=benchmarks" },
      { id: "mediacenter", label: "Mediacenter", to: "/settings?section=mediacenter" },
      { id: "opslag", label: "Opslag", to: "/settings?section=opslag" },
      { id: "python", label: "Python & Runtime", to: "/settings?section=python" },
      { id: "settings-console", label: "Console", to: "/settings?section=console" },
      { id: "logs", label: "Logs", to: "/settings?section=logs" },
      { id: "knowledge-rag", label: "Knowledge & RAG", to: "/settings?section=knowledge_rag" },
      { id: "cognition-neuro", label: "Cognition & Neuro", to: "/settings?section=cognition_neuro" },
      { id: "agents-coding", label: "Agents & Coding", to: "/settings?section=agents_coding" },
      { id: "tools-mcp", label: "Tools & MCP", to: "/settings?section=tools_mcp" },
      { id: "markt-sim", label: "Markt Simulatie", to: "/settings?section=markt_sim" },
      { id: "data-research", label: "Data & Research", to: "/settings?section=data_research" },
    ],
  },
] as const;

export function normalizePath(pathname: string): string {
  if (!pathname || pathname === "/") return "/";
  const withoutQuery = pathname.split("?")[0] ?? pathname;
  return withoutQuery.replace(/\/+$/, "") || "/";
}

function splitRoute(to: string): { path: string; query: string } {
  const [pathPart, queryPart = ""] = to.split("?");
  return { path: normalizePath(pathPart || "/"), query: queryPart };
}

export function findMainMenuByPath(pathname: string): MainMenuItem {
  const path = normalizePath(pathname);

  // Prefer the longest matching prefix so /media/youtube stays under Media.
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

export function findSubMenuItem(
  section: MainMenuItem,
  pathname: string,
  search = "",
): SubMenuItem | null {
  const path = normalizePath(pathname);
  const searchParams = new URLSearchParams(search.startsWith("?") ? search.slice(1) : search);

  const exact = section.submenu.find((item) => {
    const { path: itemPath, query } = splitRoute(item.to);
    if (itemPath !== path) return false;
    if (!query) return true;
    const wanted = new URLSearchParams(query);
    for (const [key, value] of wanted.entries()) {
      if (searchParams.get(key) !== value) return false;
    }
    return true;
  });
  if (exact) return exact;

  let best: SubMenuItem | null = null;
  let bestLen = -1;
  for (const item of section.submenu) {
    const { path: to } = splitRoute(item.to);
    if (to === "/") continue;
    if (path === to || path.startsWith(`${to}/`)) {
      if (to.length > bestLen) {
        best = item;
        bestLen = to.length;
      }
    }
  }
  if (best) return best;

  if (normalizePath(section.to) === path) return null;

  return section.submenu[0] ?? null;
}

export function allSubMenuRoutes(): readonly SubMenuItem[] {
  return MAIN_MENU.flatMap((section) => [...section.submenu]);
}
