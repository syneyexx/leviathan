/**
 * Agent Overzicht — PAGE 1 of Trading Center (SCREEN 1).
 */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "../workspaces/TradingContextBar";
import { tradingCenterStatusRows } from "../workspaces/tradingStatusRows";
import { useTradingContext } from "../workspaces/useTradingContext";
import { useTradingDeskData } from "../workspaces/tradingDesk/useTradingDeskData";
import { getTradingWorkspace } from "../workspaces/workspaceConfig";
import {
  AdvancedDrawer,
  ControlRoomDrawer,
  CreatePortfolioDrawer,
  OrchestraDrawer,
} from "./AgentOverviewDrawers";
import { AgentOverviewView } from "./AgentOverviewView";
import type { AoDetailTab } from "./useAgentOverviewData";
import { useAgentOverviewData } from "./useAgentOverviewData";
import "../../../styles/trading-workspaces.css";
import "../../../styles/trading-command-hub.css";
import "../../../styles/trading-desk-workspace.css";

export function AgentOverviewPage() {
  const ctx = useTradingContext();
  const data = useAgentOverviewData();
  const desk = useTradingDeskData(ctx.market, ctx.timeframe);
  const [params, setParams] = useSearchParams();
  const ws = getTradingWorkspace("agent_overview");

  const section = params.get("section");
  const drawer = params.get("drawer");
  const agentId = params.get("agent");
  const tab = params.get("tab") as AoDetailTab | null;

  const [showCreatePortfolio, setShowCreatePortfolio] = useState(section === "portfolio");
  const [showAdvanced, setShowAdvanced] = useState(section === "portfolio");
  const [showControlRoom, setShowControlRoom] = useState(drawer === "control-room");
  const [showOrchestra, setShowOrchestra] = useState(false);

  useEffect(() => {
    if (agentId) data.setSelectedId(agentId);
  }, [agentId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (tab && ["overzicht", "wallet", "sessies", "architectuur"].includes(tab)) {
      data.setDetailTab(tab);
    }
  }, [tab]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (drawer === "control-room") setShowControlRoom(true);
    if (section === "portfolio") {
      setShowAdvanced(true);
    }
  }, [drawer, section]);

  const subtitle = useMemo(() => {
    if (section === "portfolio") {
      return "Portfolio-beheer is onderdeel van Agent Overzicht (geen aparte Portefeuille-pagina).";
    }
    if (drawer === "control-room") {
      return "Institutionele Control Room-capaciteiten via advanced drawer.";
    }
    return ws.subtitle;
  }, [section, drawer, ws.subtitle]);

  async function refreshAll() {
    await Promise.all([data.refresh(), desk.refresh(), ctx.refresh()]);
  }

  function closeControlRoom() {
    setShowControlRoom(false);
    if (params.get("drawer") === "control-room") {
      const next = new URLSearchParams(params);
      next.delete("drawer");
      setParams(next, { replace: true });
    }
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
      pageClass="lv-app--trading-agent-overview"
      v2ScrollableMain
    >
      <main
        className="lv-v2-page lv-ao-page"
        aria-label="Agent Overzicht"
        data-section={section ?? undefined}
        data-drawer={drawer ?? undefined}
        data-agent={data.selected?.id ?? undefined}
        data-tab={data.detailTab}
      >
        <TradingContextBar ctx={ctx} />
        <AgentOverviewView
          data={data}
          onOpenPortfolio={() => {
            setShowCreatePortfolio(false);
            setShowAdvanced(true);
          }}
          onOpenControlRoom={() => setShowControlRoom(true)}
          onOpenOrchestra={() => setShowOrchestra(true)}
        />

        {showCreatePortfolio ? (
          <CreatePortfolioDrawer data={desk} onClose={() => setShowCreatePortfolio(false)} />
        ) : null}
        {showAdvanced ? <AdvancedDrawer data={desk} onClose={() => setShowAdvanced(false)} /> : null}
        <ControlRoomDrawer open={showControlRoom} onClose={closeControlRoom} />
        <OrchestraDrawer open={showOrchestra} onClose={() => setShowOrchestra(false)}>
          <p className="lv-ao-muted">
            Orchestra mandate / autonomy / missions blijven via TradingOrchestraService. Live money blijft BLOCKED.
          </p>
          <ul className="lv-ao-list">
            {data.orchestras.map((o) => (
              <li key={o.orchestraId}>
                <strong>{o.name}</strong> · autonomy={String(o.autonomyLevel)} · health={String(o.health)} ·
                members={o.memberAgentIds?.length ?? o.members?.length ?? UNMEASURED_NUM(o)}
              </li>
            ))}
            {!data.orchestras.length ? <li className="lv-ao-empty">Geen orchestras.</li> : null}
          </ul>
          <p className="lv-ao-muted">
            Volledige orchestra acties (mandate update, autonomy, missions) via Advanced portfolio/desk drawer.
          </p>
          <button
            type="button"
            className="lv-hub-btn"
            onClick={() => {
              setShowOrchestra(false);
              setShowAdvanced(true);
            }}
          >
            Open advanced orchestra controls
          </button>
        </OrchestraDrawer>
      </main>
    </AppShell>
  );
}

function UNMEASURED_NUM(o: { memberAgentIds?: string[]; members?: unknown[] }): string | number {
  const n = o.memberAgentIds?.length ?? o.members?.length;
  return n == null ? "UNMEASURED" : n;
}
