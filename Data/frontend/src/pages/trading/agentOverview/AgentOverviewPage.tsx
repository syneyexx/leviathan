/**
 * Agent Overzicht — PAGE shell (Wave 1 IA).
 * Full SCREEN 1 composition lands in Wave 2; this mounts the shared Trading
 * Center shell, deep-link params, and existing oversight data so the route is
 * operational under the new IA without inventing business truth.
 */
import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "../workspaces/TradingContextBar";
import { tradingCenterStatusRows } from "../workspaces/tradingStatusRows";
import { useTradingContext } from "../workspaces/useTradingContext";
import { CommandHubView } from "../workspaces/commandHub/CommandHubView";
import { getTradingWorkspace } from "../workspaces/workspaceConfig";
import "../../../styles/trading-workspaces.css";
import "../../../styles/trading-command-hub.css";

export function AgentOverviewPage() {
  const ctx = useTradingContext();
  const [params] = useSearchParams();
  const ws = getTradingWorkspace("agent_overview");
  const section = params.get("section");
  const drawer = params.get("drawer");
  const agentId = params.get("agent");
  const tab = params.get("tab");

  const subtitle = useMemo(() => {
    if (section === "portfolio") {
      return "Portfolio-beheer is onderdeel van Agent Overzicht (geen aparte Portefeuille-pagina).";
    }
    if (drawer === "control-room") {
      return "Institutionele Control Room-capaciteiten via advanced drawer (geen aparte Control Room-pagina).";
    }
    return ws.subtitle;
  }, [section, drawer, ws.subtitle]);

  return (
    <AppShell
      variant="v2"
      v2Title={`Trading Center / ${ws.title}`}
      v2Subtitle={subtitle}
      v2Online={!ctx.loading}
      v2Refreshing={ctx.loading}
      onV2Refresh={() => void ctx.refresh()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-agent-overview"
      v2ScrollableMain
    >
      <main
        className="lv-v2-page lv-ao-page"
        aria-label="Agent Overzicht"
        data-section={section ?? undefined}
        data-drawer={drawer ?? undefined}
        data-agent={agentId ?? undefined}
        data-tab={tab ?? undefined}
      >
        <TradingContextBar ctx={ctx} />
        {/* Wave 2 replaces CommandHubView with AgentOverviewView (SCREEN 1). */}
        <CommandHubView ctx={ctx} />
      </main>
    </AppShell>
  );
}
