/**
 * Research Centrum — PAGE 3 of Trading Center (SCREEN 3).
 */
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AppShell } from "../../../layouts/AppShell";
import { TradingContextBar } from "../workspaces/TradingContextBar";
import { tradingCenterStatusRows } from "../workspaces/tradingStatusRows";
import { useTradingContext } from "../workspaces/useTradingContext";
import {
  AdvancedDrawer,
  CompareDrawer,
  CreateLabRunDrawer,
} from "../workspaces/strategyLab/StrategyLabDrawers";
import type { DiscoveryRow } from "../workspaces/strategyLab/useStrategyLabData";
import { useStrategyLabData } from "../workspaces/strategyLab/useStrategyLabData";
import {
  CertifyDrawer,
  FeedsDrawer,
  ImportDrawer,
  ReplayDrawer,
} from "../workspaces/marketData/MarketDataDrawers";
import { MarketDataView } from "../workspaces/marketData/MarketDataView";
import type { LibraryRow } from "../workspaces/marketData/useMarketDataWorkspace";
import { useMarketDataWorkspace } from "../workspaces/marketData/useMarketDataWorkspace";
import { DeployPaperDrawer } from "../workspaces/tradingDesk/TradingDeskDrawers";
import { useTradingDeskData } from "../workspaces/tradingDesk/useTradingDeskData";
import { ResearchCommandPage } from "../researchCommand/ResearchCommandPage";
import { ResearchLabPage } from "../researchLab/ResearchLabPage";
import { getTradingWorkspace } from "../workspaces/workspaceConfig";
import { ResearchCenterView } from "./ResearchCenterView";
import "../../../styles/trading-workspaces.css";
import "../../../styles/trading-strategy-lab.css";
import "../../../styles/trading-market-data-workspace.css";
import "../../../styles/trading-command-hub.css";
import "../../../styles/trading-desk-workspace.css";
import "../../../styles/trading-research-command.css";
import "../../../styles/trading-research-lab.css";

export function ResearchCenterPage() {
  const ctx = useTradingContext();
  const data = useStrategyLabData();
  const marketData = useMarketDataWorkspace();
  const desk = useTradingDeskData(ctx.market, ctx.timeframe);
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const ws = getTradingWorkspace("research_center");
  const section = params.get("section");
  const strategyId = params.get("strategy");
  const tab = params.get("tab");

  const showMarketData =
    section === "market-data" || section === "datasets" || section === "feeds";

  const [selectedRowId, setSelectedRowId] = useState<string | null>(strategyId);
  const [compareIds, setCompareIds] = useState<string[]>([]);
  const [showCreateRun, setShowCreateRun] = useState(false);
  const [showCompare, setShowCompare] = useState(false);
  const [showAssign, setShowAssign] = useState(false);
  const [showResearchCommand, setShowResearchCommand] = useState(section === "research-command");
  const [showResearchLab, setShowResearchLab] = useState(section === "lab");
  const [showAdvanced, setShowAdvanced] = useState(section === "backtest" || tab === "backtest");
  const [advancedLabId, setAdvancedLabId] = useState<string | null>(null);

  const [selectedMdRow, setSelectedMdRow] = useState<LibraryRow | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [showFeeds, setShowFeeds] = useState(section === "feeds");
  const [showCertify, setShowCertify] = useState(false);
  const [showReplay, setShowReplay] = useState(false);
  const [certifyRow, setCertifyRow] = useState<LibraryRow | null>(null);
  const [replayRow, setReplayRow] = useState<LibraryRow | null>(null);

  useEffect(() => {
    if (strategyId) setSelectedRowId(strategyId);
  }, [strategyId]);

  useEffect(() => {
    setShowResearchCommand(section === "research-command");
    setShowResearchLab(section === "lab");
    if (section === "backtest" || tab === "backtest") {
      setShowAdvanced(true);
    }
  }, [section, tab]);

  const selectedRow = useMemo<DiscoveryRow | null>(
    () => data.discovery.find((r) => r.id === selectedRowId || r.strategyId === selectedRowId) ?? null,
    [data.discovery, selectedRowId],
  );

  const compareRows = useMemo(
    () => data.discovery.filter((r) => compareIds.includes(r.id)),
    [data.discovery, compareIds],
  );

  const subtitle = useMemo(() => {
    if (section === "market-data") return "Dataset- & marktuniversum (voorheen aparte Market Data-pagina).";
    if (section === "strategies") return "Strategie-inventaris en builder.";
    if (section === "backtest") return "Historische simulatie / offline backtest.";
    if (section === "lab") return "Research Lab lifecycle, hypotheses, lineage.";
    if (section === "research-command") return "Research Command compositie.";
    return ws.subtitle;
  }, [section, ws.subtitle]);

  async function refreshAll() {
    await Promise.all([
      data.refresh(),
      marketData.refresh(),
      marketData.refreshProviders(),
      desk.refresh(),
      ctx.refresh(),
    ]);
  }

  function openAdvanced() {
    const matchedLab = data.matchLabForStrategy(selectedRow?.strategyId ?? null);
    const rawLabId = selectedRow?.labId ?? (matchedLab ? matchedLab.lab_id : null);
    setAdvancedLabId(rawLabId != null ? String(rawLabId) : null);
    setShowAdvanced(true);
  }

  function openMarketDataSection() {
    const next = new URLSearchParams(params);
    next.set("section", "market-data");
    setParams(next, { replace: true });
  }

  const strategyOptions = useMemo(
    () =>
      data.strategies.map((s) => ({
        id: s.strategy_id,
        label: `${s.name} (v${s.current_version})`,
      })),
    [data.strategies],
  );

  function handleAssigned(result: Record<string, unknown>) {
    const deploymentId = String(
      (result as { deployment?: { deployment_id?: string } }).deployment?.deployment_id ??
        result.deployment_id ??
        "",
    );
    const q = new URLSearchParams({ mode: "realtime", section: "broker-boundary" });
    if (deploymentId) q.set("deployment", deploymentId);
    navigate(`/trading/live-agents?${q.toString()}`);
  }

  return (
    <AppShell
      variant="v2"
      v2Title={`Trading Center / ${ws.title}`}
      v2Subtitle={subtitle}
      v2Online={!ctx.loading && !data.loading}
      v2Refreshing={ctx.loading || data.loading || marketData.loading}
      onV2Refresh={() => void refreshAll()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-research-center"
      v2ScrollableMain
    >
      <main
        className="lv-v2-page lv-rc-page"
        aria-label="Research Centrum"
        data-section={section ?? undefined}
        data-strategy={strategyId ?? undefined}
        data-tab={tab ?? undefined}
      >
        <TradingContextBar ctx={ctx} />

        {showMarketData ? (
          <>
            {marketData.error ? (
              <p className="lv-md-error" role="alert">
                {marketData.error}
                <button type="button" className="lv-md-btn" onClick={() => void marketData.refresh()}>
                  Opnieuw proberen
                </button>
              </p>
            ) : null}
            <MarketDataView
              data={marketData}
              onOpenImport={() => setShowImport(true)}
              onOpenFeeds={() => setShowFeeds(true)}
              onOpenCertify={(row) => {
                setCertifyRow(row);
                setShowCertify(true);
              }}
              onOpenReplay={(row) => {
                setReplayRow(row);
                setShowReplay(true);
              }}
              onSelectRow={setSelectedMdRow}
            />
            {selectedMdRow ? (
              <p className="lv-md-muted" style={{ marginTop: "-0.4rem" }}>
                Geselecteerd: <strong>{selectedMdRow.symbol}</strong> · {selectedMdRow.timeframe} ·{" "}
                {selectedMdRow.path}
              </p>
            ) : null}
            {showImport ? <ImportDrawer data={marketData} onClose={() => setShowImport(false)} /> : null}
            {showFeeds ? <FeedsDrawer data={marketData} onClose={() => setShowFeeds(false)} /> : null}
            {showCertify ? (
              <CertifyDrawer data={marketData} initialRow={certifyRow} onClose={() => setShowCertify(false)} />
            ) : null}
            {showReplay ? (
              <ReplayDrawer data={marketData} initialRow={replayRow} onClose={() => setShowReplay(false)} />
            ) : null}
          </>
        ) : showResearchCommand ? (
          <div className="lv-rc-command-embed" data-section="research-command">
            <header className="lv-ao-panel__head">
              <h3>Research Command</h3>
              <button
                type="button"
                className="lv-hub-btn"
                onClick={() => {
                  setShowResearchCommand(false);
                  const next = new URLSearchParams(params);
                  next.delete("section");
                  setParams(next, { replace: true });
                }}
              >
                Terug naar inventaris
              </button>
            </header>
            <ResearchCommandPage embedded />
          </div>
        ) : showResearchLab ? (
          <div className="lv-rc-lab-embed" data-section="lab">
            <header className="lv-ao-panel__head">
              <h3>Research Lab</h3>
              <button
                type="button"
                className="lv-hub-btn"
                onClick={() => {
                  setShowResearchLab(false);
                  const next = new URLSearchParams(params);
                  next.delete("section");
                  setParams(next, { replace: true });
                }}
              >
                Terug naar inventaris
              </button>
            </header>
            <ResearchLabPage embedded />
          </div>
        ) : (
          <>
            {data.error ? (
              <p className="lv-sl-error" role="alert">
                {data.error}
                <button type="button" className="lv-tc-btn" onClick={() => void data.refresh()}>
                  Opnieuw proberen
                </button>
              </p>
            ) : null}
            <ResearchCenterView
              data={data}
              marketData={marketData}
              selectedRow={selectedRow}
              onSelectRow={(row) => setSelectedRowId(row.id)}
              compareIds={compareIds}
              onToggleCompare={(id) =>
                setCompareIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
              }
              onOpenCreateRun={() => setShowCreateRun(true)}
              onOpenCompare={() => setShowCompare(true)}
              onOpenAdvanced={openAdvanced}
              onOpenMarketData={openMarketDataSection}
              onAssignToAgent={() => setShowAssign(true)}
            />
          </>
        )}

        {showAssign ? (
          <DeployPaperDrawer
            data={desk}
            initialStrategyId={selectedRow?.strategyId ?? ""}
            strategyOptions={strategyOptions}
            onClose={() => setShowAssign(false)}
            onDeployed={handleAssigned}
          />
        ) : null}

        {showCreateRun ? (
          <CreateLabRunDrawer
            data={data}
            onClose={() => setShowCreateRun(false)}
            onCreated={(labId) => {
              setAdvancedLabId(labId);
              setShowAdvanced(true);
            }}
          />
        ) : null}

        {showCompare && compareRows.length >= 2 ? (
          <CompareDrawer
            rows={compareRows}
            onClose={() => setShowCompare(false)}
            onClear={() => setCompareIds([])}
          />
        ) : null}

        {showAdvanced ? (
          <AdvancedDrawer
            data={data}
            labId={advancedLabId}
            strategyId={selectedRow?.strategyId ?? null}
            onClose={() => setShowAdvanced(false)}
          />
        ) : null}
      </main>
    </AppShell>
  );
}
