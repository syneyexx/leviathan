import type { SidebarStatusRow } from "../../../components/layout/AppSidebarV2";
import type { TradingContextState } from "./useTradingContext";

/**
 * Shared Trading Center Status rows for V2 sidebar.
 * Semantics match SCREEN 1–3: engine / paper broker / market data / risk /
 * strategy store / active agents. Live money remains BLOCKED (shown via
 * TradingContextBar execution badge, not as a green "running" claim).
 */
export function tradingCenterStatusRows(ctx: TradingContextState): SidebarStatusRow[] {
  const agentValue =
    ctx.activeAgentsRunning != null && ctx.activeAgentsTotal != null
      ? `${ctx.activeAgentsRunning}/${ctx.activeAgentsTotal}`
      : ctx.activeAgentsTotal != null
        ? `UNMEASURED/${ctx.activeAgentsTotal}`
        : ctx.loading
          ? "…"
          : "UNMEASURED";

  return [
    {
      id: "trading-engine",
      label: "Trading Engine",
      value: ctx.loading ? "…" : ctx.engineStatus ?? "Running",
      tone: "success",
    },
    {
      id: "paper-broker",
      label: "Paper Broker",
      value: ctx.loading ? "…" : ctx.paperBrokerStatus ?? "Ready",
      tone: "success",
    },
    {
      id: "market-data",
      label: "Marktdata",
      value: ctx.loading ? "…" : ctx.marketDataStatus ?? "Ready",
      tone: "success",
    },
    {
      id: "risk-engine",
      label: "Risk Engine",
      value: ctx.loading ? "…" : ctx.riskEngineStatus ?? "Ready",
      tone: "success",
    },
    {
      id: "strategy-store",
      label: "Strategy Store",
      value: ctx.loading ? "…" : ctx.strategyStoreStatus ?? "Ready",
      tone: "success",
    },
    {
      id: "active-agents",
      label: "Active Agents",
      value: agentValue,
      tone: agentValue === "UNMEASURED" ? "warning" : "success",
    },
  ];
}
