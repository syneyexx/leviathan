/**
 * Trading Center three-page architecture (4→3 final consolidation).
 * Nav and routes must stay at exactly these three primary pages.
 * Legacy four-workspace and older nine routes redirect with query context.
 */

export type TradingWorkspaceId = "agent_overview" | "live_agents" | "research_center";

/** @deprecated Four-workspace ids — retained only for redirect typing during migration. */
export type LegacyTradingWorkspaceId =
  | "command_hub"
  | "strategy_lab"
  | "trading_desk"
  | "market_data";

export type TradingContextMode = "offline" | "live" | "hybrid";

export type TradingWorkspaceSurface = {
  id: string;
  label: string;
  level: "PRIMARY" | "SECONDARY" | "ADVANCED";
  legacyPath?: string;
};

export type TradingWorkspaceDefinition = {
  id: TradingWorkspaceId;
  route: string;
  label: string;
  title: string;
  subtitle: string;
  defaultSurface: string;
  surfaces: readonly TradingWorkspaceSurface[];
};

export const TRADING_WORKSPACES: readonly TradingWorkspaceDefinition[] = [
  {
    id: "agent_overview",
    route: "/trading/agents",
    label: "Agent Overzicht",
    title: "Agent Overzicht",
    subtitle:
      "Beheer trading agents, allocaties, wallets, PnL, en orchestratie vanuit één overzicht.",
    defaultSurface: "overview",
    surfaces: [{ id: "overview", label: "Agent Overzicht", level: "PRIMARY" }],
  },
  {
    id: "live_agents",
    route: "/trading/live-agents",
    label: "Live Agents",
    title: "Live Agents",
    subtitle:
      "Volg elke trading agent live en schakel tussen realtime marktdata en offline paper-trading scenario's.",
    defaultSurface: "live",
    surfaces: [{ id: "live", label: "Live Agents", level: "PRIMARY" }],
  },
  {
    id: "research_center",
    route: "/trading/research",
    label: "Research Centrum",
    title: "Research Centrum",
    subtitle:
      "Ontdek, train, backtest en valideer strategieën — van autonome discovery tot paper sandbox.",
    defaultSurface: "research",
    surfaces: [{ id: "research", label: "Research Centrum", level: "PRIMARY" }],
  },
] as const;

/**
 * Compatibility redirects for four-workspace + older Trading Center deep links.
 * Query strings are presentation state only — never business authority.
 */
export const TRADING_LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  // Former four workspaces
  "/trading/command-hub": "/trading/agents",
  "/trading/trading-desk": "/trading/live-agents",
  "/trading/strategy-lab": "/trading/research",
  "/trading/market-data": "/trading/research?section=market-data",
  // Older nine routes
  "/trading/simulatie": "/trading/research?section=backtest",
  "/trading/strategieen": "/trading/research?section=strategies",
  "/trading/lab": "/trading/research?section=lab",
  "/trading/marktdata": "/trading/research?section=market-data",
  "/trading/portefeuille": "/trading/agents?section=portfolio",
  "/trading/paper": "/trading/live-agents",
  "/trading/broker": "/trading/live-agents?section=broker-boundary",
  "/trading/onderzoek": "/trading/research?section=research-command",
  "/trading/control-room": "/trading/agents?drawer=control-room",
};

export function getTradingWorkspace(id: TradingWorkspaceId): TradingWorkspaceDefinition {
  const found = TRADING_WORKSPACES.find((w) => w.id === id);
  if (!found) throw new Error(`Unknown trading workspace: ${id}`);
  return found;
}

export function resolveWorkspaceSurface(
  workspace: TradingWorkspaceDefinition,
  surfaceParam: string | null,
): TradingWorkspaceSurface {
  const hit = workspace.surfaces.find((s) => s.id === surfaceParam);
  if (hit) return hit;
  return (
    workspace.surfaces.find((s) => s.id === workspace.defaultSurface) ?? workspace.surfaces[0]
  );
}

/** Map a path (without query) to a redirect target including optional query. */
export function resolveTradingRedirect(pathname: string): string | null {
  return TRADING_LEGACY_REDIRECTS[pathname] ?? null;
}
