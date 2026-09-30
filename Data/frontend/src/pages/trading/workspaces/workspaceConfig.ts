/**
 * Trading Center four-workspace architecture.
 * Nav and routes must stay at exactly these four workspaces.
 * WAVE 5+: each workspace is a full native page (no legacy surface-tab embeds).
 */

export type TradingWorkspaceId =
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
    id: "command_hub",
    route: "/trading/command-hub",
    label: "Command Hub",
    title: "Command Hub",
    subtitle:
      "Central overview and control for autonomous trading research, simulation, and paper trading.",
    defaultSurface: "overview",
    surfaces: [{ id: "overview", label: "Overview", level: "PRIMARY" }],
  },
  {
    id: "strategy_lab",
    route: "/trading/strategy-lab",
    label: "Strategy Lab",
    title: "Strategy Lab",
    subtitle: "Strategy discovery, validation, qualification ladder, and historical simulation.",
    defaultSurface: "lab",
    surfaces: [{ id: "lab", label: "Strategy Lab", level: "PRIMARY", legacyPath: "/trading/lab" }],
  },
  {
    id: "trading_desk",
    route: "/trading/trading-desk",
    label: "Trading Desk",
    title: "Trading Desk",
    subtitle: "Paper execution, portfolios, wallets, risk, and live-trading boundary.",
    defaultSurface: "paper",
    surfaces: [{ id: "paper", label: "Trading Desk", level: "PRIMARY", legacyPath: "/trading/paper" }],
  },
  {
    id: "market_data",
    route: "/trading/market-data",
    label: "Market Data",
    title: "Market Data",
    subtitle: "Select, validate and monitor market data for research and paper execution.",
    defaultSurface: "library",
    surfaces: [
      { id: "library", label: "Market Data", level: "PRIMARY", legacyPath: "/trading/marktdata" },
    ],
  },
] as const;

export const TRADING_LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  "/trading/onderzoek": "/trading/command-hub",
  "/trading/control-room": "/trading/command-hub",
  "/trading/lab": "/trading/strategy-lab",
  "/trading/strategieen": "/trading/strategy-lab",
  "/trading/simulatie": "/trading/strategy-lab",
  "/trading/paper": "/trading/trading-desk",
  "/trading/portefeuille": "/trading/trading-desk",
  "/trading/broker": "/trading/trading-desk",
  "/trading/marktdata": "/trading/market-data",
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
