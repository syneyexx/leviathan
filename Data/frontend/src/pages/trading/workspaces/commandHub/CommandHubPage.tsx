import { AppShell } from "../../../../layouts/AppShell";
import type { SidebarStatusRow } from "../../../../components/layout/AppSidebarV2";
import { TradingContextBar } from "../TradingContextBar";
import { useTradingContext } from "../useTradingContext";
import { CommandHubView } from "./CommandHubView";
import "../../../../styles/trading-command-hub.css";

export function CommandHubPage() {
  const ctx = useTradingContext();

  const statusRows: SidebarStatusRow[] = [
    { id: "trading-engine", label: "Trading Engine", value: ctx.loading ? "…" : "Running", tone: "success" },
    {
      id: "agent-network",
      label: "Agent Network",
      value: ctx.loading ? "…" : "Connected",
      tone: "success",
    },
    { id: "market-data", label: "Market Data", value: ctx.loading ? "…" : "Online", tone: "success" },
    { id: "paper-trading", label: "Paper Trading", value: "Active", tone: "success" },
    {
      id: "live-trading",
      label: "Live Trading",
      value: ctx.liveTrading,
      tone: ctx.liveTrading === "BLOCKED" ? "danger" : "warning",
    },
  ];

  return (
    <AppShell
      variant="v2"
      v2Title="Trading Center / Command Hub"
      v2Subtitle="Centrale overzicht en controle voor autonoom trading onderzoek, simulatie en paper trading."
      v2Online={!ctx.loading}
      v2Refreshing={ctx.loading}
      onV2Refresh={() => void ctx.refresh()}
      v2StatusRows={statusRows}
      pageClass="lv-app--trading-command-hub"
    >
      <main className="lv-v2-page lv-v2-page--command-hub">
        <TradingContextBar ctx={ctx} />
        <CommandHubView ctx={ctx} />
      </main>
    </AppShell>
  );
}
