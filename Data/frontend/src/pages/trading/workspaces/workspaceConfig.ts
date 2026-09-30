/**
 * Trading Center four-workspace architecture (WAVE 1).
 * Nav and routes must stay at exactly these four workspaces.
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
  /** progressive disclosure level */
  level: "PRIMARY" | "SECONDARY" | "ADVANCED";
  /** legacy route this surface preserves (if any) */
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
    surfaces: [
      { id: "overview", label: "Overview", level: "PRIMARY" },
      {
        id: "research-command",
        label: "Research Command",
        level: "SECONDARY",
        legacyPath: "/trading/onderzoek",
      },
      {
        id: "control-room",
        label: "Control Room",
        level: "ADVANCED",
        legacyPath: "/trading/control-room",
      },
    ],
  },
  {
    id: "strategy_lab",
    route: "/trading/strategy-lab",
    label: "Strategy Lab",
    title: "Strategy Lab",
    subtitle: "Strategy discovery, validation, qualification ladder, and historical simulation.",
    defaultSurface: "lab",
    surfaces: [
      { id: "lab", label: "Research Lab", level: "PRIMARY", legacyPath: "/trading/lab" },
      {
        id: "strategies",
        label: "Strategieën",
        level: "PRIMARY",
        legacyPath: "/trading/strategieen",
      },
      {
        id: "simulation",
        label: "Simulatie",
        level: "SECONDARY",
        legacyPath: "/trading/simulatie",
      },
    ],
  },
  {
    id: "trading_desk",
    route: "/trading/trading-desk",
    label: "Trading Desk",
    title: "Trading Desk",
    subtitle: "Paper execution, portfolios, wallets, risk, and live-trading boundary.",
    defaultSurface: "paper",
    surfaces: [
      { id: "paper", label: "Paper", level: "PRIMARY", legacyPath: "/trading/paper" },
      {
        id: "portfolio",
        label: "Portefeuille",
        level: "PRIMARY",
        legacyPath: "/trading/portefeuille",
      },
      {
        id: "broker",
        label: "Broker boundary",
        level: "ADVANCED",
        legacyPath: "/trading/broker",
      },
    ],
  },
  {
    id: "market_data",
    route: "/trading/market-data",
    label: "Market Data",
    title: "Market Data",
    subtitle: "Select, validate and monitor market data for research and paper execution.",
    defaultSurface: "library",
    surfaces: [
      {
        id: "library",
        label: "Dataset library",
        level: "PRIMARY",
        legacyPath: "/trading/marktdata",
      },
    ],
  },
] as const;

export const TRADING_LEGACY_REDIRECTS: Readonly<Record<string, string>> = {
  "/trading/onderzoek": "/trading/command-hub?surface=research-command",
  "/trading/control-room": "/trading/command-hub?surface=control-room",
  "/trading/lab": "/trading/strategy-lab?surface=lab",
  "/trading/strategieen": "/trading/strategy-lab?surface=strategies",
  "/trading/simulatie": "/trading/strategy-lab?surface=simulation",
  "/trading/paper": "/trading/trading-desk?surface=paper",
  "/trading/portefeuille": "/trading/trading-desk?surface=portfolio",
  "/trading/broker": "/trading/trading-desk?surface=broker",
  "/trading/marktdata": "/trading/market-data?surface=library",
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
