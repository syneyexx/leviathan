/**
 * Live Agents — PAGE 2 of Trading Center (SCREEN 2).
 * REALTIME FEED / OFFLINE REPLAY + PAPER EXECUTION only.
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "../workspaces/TradingContextBar";
import { tradingCenterStatusRows } from "../workspaces/tradingStatusRows";
import { useTradingContext } from "../workspaces/useTradingContext";
import { AdvancedDrawer, DeployPaperDrawer } from "../workspaces/tradingDesk/TradingDeskDrawers";
import { useTradingDeskData } from "../workspaces/tradingDesk/useTradingDeskData";
import { getTradingWorkspace } from "../workspaces/workspaceConfig";
import { LiveAgentsView } from "./LiveAgentsView";
import type { DataMode } from "./useLiveAgentsData";
import { useLiveAgentsData } from "./useLiveAgentsData";
import "../../../styles/trading-workspaces.css";
import "../../../styles/trading-command-hub.css";
import "../../../styles/trading-desk-workspace.css";

export function LiveAgentsPage() {
  const ctx = useTradingContext();
  const data = useLiveAgentsData(ctx.market);
  const desk = useTradingDeskData(ctx.market, ctx.timeframe);
  const [params] = useSearchParams();
  const ws = getTradingWorkspace("live_agents");

  const section = params.get("section");
  const mode = params.get("mode") as DataMode | null;
  const agentId = params.get("agent");

  const [showDeploy, setShowDeploy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(section === "broker-boundary");

  useEffect(() => {
    if (mode === "realtime" || mode === "offline") data.setDataMode(mode);
  }, [mode]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (agentId) data.setSelectedId(agentId);
  }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (section === "broker-boundary") setShowAdvanced(true);
  }, [section]);

  const subtitle = useMemo(() => {
    if (section === "broker-boundary") {
      return "Broker boundary: LIVE MONEY blijft BLOCKED. Alleen PAPER EXECUTION.";
    }
    if (data.dataMode === "realtime") {
      return "REALTIME FEED + PAPER EXECUTION — live money blijft BLOCKED.";
    }
    return "OFFLINE REPLAY + PAPER EXECUTION.";
  }, [section, data.dataMode]);

  async function refreshAll() {
    await Promise.all([data.refresh(), desk.refresh(), ctx.refresh()]);
  }

  return (
    <AppShell
      variant="v2"
      v2Title={`Trading Center / ${ws.title}`}
      v2Subtitle={subtitle}
      v2Online={!ctx.loading && !data.loading}
      v2Refreshing={ctx.loading || data.loading}
      onV2Refresh={() => void refreshAll()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-live-agents"
      v2ScrollableMain
    >
      <main
        className="lv-v2-page lv-la-page"
        aria-label="Live Agents"
        data-section={section ?? undefined}
        data-mode={data.dataMode}
        data-agent={data.selected?.id ?? undefined}
        data-execution="PAPER"
      >
        <TradingContextBar ctx={ctx} />
        <LiveAgentsView
          data={data}
          onOpenDeploy={() => setShowDeploy(true)}
          onOpenAdvanced={() => setShowAdvanced(true)}
        />
        {showDeploy ? <DeployPaperDrawer data={desk} onClose={() => setShowDeploy(false)} /> : null}
        {showAdvanced ? <AdvancedDrawer data={desk} onClose={() => setShowAdvanced(false)} /> : null}
      </main>
    </AppShell>
  );
}
