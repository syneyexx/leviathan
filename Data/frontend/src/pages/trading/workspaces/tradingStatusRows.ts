import type { SidebarStatusRow } from "../../../components/layout/AppSidebarV2";
import type { TradingContextState } from "./useTradingContext";

/** Shared Trading Center Status rows for V2 sidebar (screenshot widget). */
export function tradingCenterStatusRows(ctx: TradingContextState): SidebarStatusRow[] {
  return [
    {
      id: "trading-engine",
      label: "Trading Engine",
      value: ctx.loading ? "…" : "Running",
      tone: "success",
    },
    {
      id: "agent-network",
      label: "Agent Network",
      value: ctx.loading ? "…" : "Connected",
      tone: "success",
    },
    {
      id: "market-data",
      label: "Market Data",
      value: ctx.loading ? "…" : "Online",
      tone: "success",
    },
    {
      id: "paper-trading",
      label: "Paper Trading",
      value: "Running",
      tone: "success",
    },
    {
      id: "risk-monitor",
      label: "Risk Monitor",
      value: "Active",
      tone: "success",
    },
    {
      id: "live-trading",
      label: "Live Trading",
      value: ctx.liveTrading,
      tone: ctx.liveTrading === "BLOCKED" ? "danger" : "warning",
    },
  ];
}
