import { AppShell } from "../../../layouts/AppShell";
import { PaperTradingActivityLogPanel } from "./PaperTradingActivityLogPanel";
import { PaperTradingAgentFleetPanel } from "./PaperTradingAgentFleetPanel";
import { PaperTradingAnalyticsPanel } from "./PaperTradingAnalyticsPanel";
import { PaperTradingChartShell } from "./PaperTradingChartShell";
import { PaperTradingHero } from "./PaperTradingHero";
import { PaperTradingOrchestratorPanel } from "./PaperTradingOrchestratorPanel";
import { PaperTradingOrdersPanel, PaperTradingPositionsPanel } from "./PaperTradingPositionsPanel";
import { PaperTradingPortfolioPanel } from "./PaperTradingPortfolioPanel";
import { PaperTradingRiskAllocationPanel } from "./PaperTradingRiskAllocationPanel";
import { PaperTradingToolbar } from "./PaperTradingToolbar";
import { usePaperTradingOperator } from "./hooks/usePaperTradingOperator";
import "../../../styles/trading-paper.css";

export function PaperTradingPage() {
  const {
    state,
    setState,
    setSymbol,
    setTimeframe,
    addSymbol,
    patchDraft,
    saveOrchestrator,
    runAction,
    closePosition,
    toggleAgent,
    setIndicators,
    saveLayout,
    refreshCore,
  } = usePaperTradingOperator();

  const dash = state.dashboard;
  const positions = dash?.positions || [];

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <main className="lv-main lv-tp-main lv-paper-page">
        <PaperTradingHero />

        {state.error ? (
          <div className="lv-paper-banner is-bad" role="alert">
            {state.error}
            <button type="button" onClick={() => void refreshCore()}>
              Retry
            </button>
          </div>
        ) : null}

        <PaperTradingToolbar
          watchlist={state.watchlist}
          symbol={state.symbol}
          timeframe={state.timeframe}
          indicatorsOpen={state.showIndicatorsMenu}
          drawingTool={state.drawingTool}
          layoutSavedAt={state.layoutSavedAt}
          onSelectSymbol={setSymbol}
          onAddSymbol={addSymbol}
          onTimeframe={setTimeframe}
          onToggleIndicators={() =>
            setState((s) => ({ ...s, showIndicatorsMenu: !s.showIndicatorsMenu }))
          }
          onToggleDraw={() =>
            setState((s) => ({
              ...s,
              drawingTool: s.drawingTool == null ? "crosshair" : null,
            }))
          }
          onSaveLayout={saveLayout}
          onSelectTool={(tool) => setState((s) => ({ ...s, drawingTool: tool }))}
          indicators={state.indicators}
          onIndicatorChange={(key, value) => setIndicators({ [key]: value })}
        />

        <div className="lv-paper-grid">
          <section className="lv-paper-mid">
            <PaperTradingChartShell
              symbol={state.symbol}
              bars={state.bars}
              barsError={state.barsError}
              barsLoading={state.barsLoading}
              indicators={state.indicators}
              drawingTool={state.drawingTool}
              onSelectTool={(tool) => setState((s) => ({ ...s, drawingTool: tool }))}
            />
            <div className="lv-paper-right">
              <PaperTradingOrchestratorPanel
                draft={state.draft}
                portfolioStatus={dash?.portfolio.status || null}
                busyAction={state.busyAction}
                onPatch={patchDraft}
                onSave={() => void saveOrchestrator()}
                onDeploy={() => void runAction("deploy")}
                onPause={() => void runAction("pause")}
                onFlatten={() => void runAction("flatten")}
              />
              <PaperTradingPortfolioPanel dashboard={dash} loading={state.loading} />
            </div>
          </section>

          <section className="lv-paper-lower">
            <PaperTradingAgentFleetPanel
              agents={state.agents}
              deployments={state.deployments}
              strategies={dash?.strategy_allocation || []}
              busyAction={state.busyAction}
              onToggle={(id, en) => void toggleAgent(id, en)}
            />
            <div className="lv-paper-pos-stack">
              <PaperTradingPositionsPanel
                positions={positions}
                busyAction={state.busyAction}
                onClose={(id) => void closePosition(id)}
              />
              <PaperTradingOrdersPanel orders={state.orders} />
            </div>
            <PaperTradingActivityLogPanel events={state.events} />
          </section>

          <section className="lv-paper-bottom">
            <PaperTradingAnalyticsPanel dashboard={dash} />
            <PaperTradingRiskAllocationPanel dashboard={dash} />
            <div className="lv-paper-cap-note" aria-live="polite">
              {state.caps ? (
                <p>
                  Capabilities from backend · live trading{" "}
                  <strong>{String(state.caps.live_trading_default)}</strong>
                  {state.refreshing ? " · refreshing…" : ""}
                  {state.bars?.truth?.ohlcv_is_not_orderbook ? " · OHLCV ≠ order book" : ""}
                </p>
              ) : (
                <p>Loading market capabilities…</p>
              )}
            </div>
          </section>
        </div>
      </main>
    </AppShell>
  );
}
