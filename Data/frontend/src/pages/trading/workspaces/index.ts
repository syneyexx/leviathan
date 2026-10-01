export { AgentOverviewPage } from "../agentOverview/AgentOverviewPage";
export { LiveAgentsPage } from "../liveAgents/LiveAgentsPage";
export { ResearchCenterPage } from "../researchCenter/ResearchCenterPage";
export {
  TRADING_WORKSPACES,
  TRADING_LEGACY_REDIRECTS,
  getTradingWorkspace,
  resolveWorkspaceSurface,
  resolveTradingRedirect,
} from "./workspaceConfig";

/** @deprecated Four-workspace page entrypoints — kept for import compatibility until Wave 7 deletion. */
export { CommandHubPage } from "./CommandHubPage";
export { StrategyLabWorkspacePage } from "./StrategyLabWorkspacePage";
export { TradingDeskPage } from "./TradingDeskPage";
export { MarketDataWorkspacePage } from "./MarketDataWorkspacePage";
