/**
 * Live Agents — PAGE shell (Wave 1 IA).
 * Full SCREEN 2 composition lands in Wave 3. Mounts Trading Desk paper
 * execution surface under the new route so operators retain paper controls
 * while the Live Agent Grid / Datamodus layout is completed.
 */
import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "../workspaces/TradingContextBar";
import { tradingCenterStatusRows } from "../workspaces/tradingStatusRows";
import { useTradingContext } from "../workspaces/useTradingContext";
import {
  AdvancedDrawer,
  CreatePortfolioDrawer,
  DeployPaperDrawer,
} from "../workspaces/tradingDesk/TradingDeskDrawers";
import { TradingDeskView } from "../workspaces/tradingDesk/TradingDeskView";
import { useTradingDeskData } from "../workspaces/tradingDesk/useTradingDeskData";
import { getTradingWorkspace } from "../workspaces/workspaceConfig";
import "../../../styles/trading-workspaces.css";
import "../../../styles/trading-desk-workspace.css";

export function LiveAgentsPage() {
  const ctx = useTradingContext();
  const data = useTradingDeskData(ctx.market, ctx.timeframe);
  const [params] = useSearchParams();
  const ws = getTradingWorkspace("live_agents");
  const section = params.get("section");
  const mode = params.get("mode");
  const agentId = params.get("agent");

  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [showDeploy, setShowDeploy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(section === "broker-boundary");

  const subtitle = useMemo(() => {
    if (section === "broker-boundary") {
      return "Broker boundary: LIVE MONEY blijft BLOCKED. Alleen PAPER EXECUTION.";
    }
    if (mode === "realtime") {
      return "REALTIME FEED + PAPER EXECUTION — live money blijft BLOCKED.";
    }
    if (mode === "replay") {
      return "OFFLINE REPLAY + PAPER EXECUTION.";
    }
    return ws.subtitle;
  }, [section, mode, ws.subtitle]);

  async function refreshAll() {
    await Promise.all([data.refresh(), ctx.refresh()]);
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
        data-mode={mode ?? undefined}
        data-agent={agentId ?? undefined}
        data-execution="PAPER"
      >
        <TradingContextBar ctx={ctx} />
        <p className="lv-tc-badge lv-tc-badge--exec" style={{ marginBottom: 12 }}>
          LIVE DATA ≠ LIVE MONEY · Execution = PAPER ONLY
        </p>
        {/* Wave 3 replaces TradingDeskView with LiveAgentsView (SCREEN 2). */}
        <TradingDeskView
          data={data}
          onOpenCreatePortfolio={() => setShowCreatePortfolio(true)}
          onOpenDeploy={() => setShowDeploy(true)}
          onOpenAdvanced={() => setShowAdvanced(true)}
        />
        {showCreatePortfolio ? (
          <CreatePortfolioDrawer data={data} onClose={() => setShowCreatePortfolio(false)} />
        ) : null}
        {showDeploy ? <DeployPaperDrawer data={data} onClose={() => setShowDeploy(false)} /> : null}
        {showAdvanced ? <AdvancedDrawer data={data} onClose={() => setShowAdvanced(false)} /> : null}
      </main>
    </AppShell>
  );
}
