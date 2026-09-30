/**
 * Trading Desk (WAVE 5/6) — native pixel-exact page.
 *
 * Absorbs Paper Trading + Portefeuille + Broker boundary + Wallets + Orchestra
 * fleet into ONE page via progressive disclosure: PRIMARY dashboard (hero /
 * CTAs / KPI strip / chart / wallets / positions+orders / RiskGuard /
 * activity) always visible; ADVANCED capabilities (agent fleet, orchestra
 * config/autonomy, paper deployments, rebalance, broker boundary inspector,
 * execution calibration) live in a drawer. NO PaperTradingPage /
 * PortefeuillePage / BrokerTradingPage embedding. Live trading stays BLOCKED
 * everywhere.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { TradingContextBar } from "../TradingContextBar";
import { useTradingContext } from "../useTradingContext";
import { AdvancedDrawer, CreatePortfolioDrawer, DeployPaperDrawer } from "./TradingDeskDrawers";
import { TradingDeskView } from "./TradingDeskView";
import { useTradingDeskData } from "./useTradingDeskData";
import "../../../../styles/trading-workspaces.css";
import "../../../../styles/trading-desk-workspace.css";

export function TradingDeskPage() {
  const ctx = useTradingContext();
  const data = useTradingDeskData(ctx.market, ctx.timeframe);

  const [showCreatePortfolio, setShowCreatePortfolio] = useState(false);
  const [showDeploy, setShowDeploy] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);

  async function refreshAll() {
    await Promise.all([data.refresh(), ctx.refresh()]);
  }

  return (
    <main className="lv-main lv-tp-main lv-tc-workspace lv-td-page" aria-label="Trading Desk">
      <header className="lv-tc-workspace__header">
        <div>
          <p className="lv-tc-workspace__crumb">
            <Link to="/trading/command-hub">Trading Center</Link>
            <span aria-hidden="true"> / </span>
            <span>Trading Desk</span>
          </p>
          <h1 className="lv-tc-workspace__title">Trading Desk</h1>
          <p className="lv-tc-workspace__subtitle">
            Paper execution, portfolios, wallets, risk, and the live-trading boundary — one operator surface.
          </p>
        </div>
        <div className="lv-tc-workspace__header-actions">
          <button
            type="button"
            className="lv-tc-btn"
            onClick={() => void refreshAll()}
            disabled={data.loading || ctx.loading}
          >
            Refresh
          </button>
          <span className="lv-tc-badge lv-tc-badge--exec" title={`LIVE_TRADING_AVAILABLE=${data.liveTrading}`}>
            {ctx.executionLabel}
          </span>
        </div>
      </header>

      <TradingContextBar ctx={ctx} />

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
  );
}
