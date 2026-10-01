/**
 * Trading Desk (WAVE 5/6) — native pixel-exact page.
 * Absorbs Paper + Portefeuille + Broker + Wallets + Orchestra. NO legacy embeds.
 */
import { useState } from "react";
import { AppShell } from "../../../../layouts/AppShell";
import { TradingContextBar } from "../TradingContextBar";
import { tradingCenterStatusRows } from "../tradingStatusRows";
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
    <AppShell
      variant="v2"
      v2Title="Trading Center / Trading Desk"
      v2Subtitle="Paper execution, portfolios, wallets, risk, and the live-trading boundary."
      v2Online={!ctx.loading && !data.loading}
      v2Refreshing={ctx.loading || data.loading}
      onV2Refresh={() => void refreshAll()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-desk"
      v2ScrollableMain
    >
      <main className="lv-v2-page lv-td-page" aria-label="Trading Desk">
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
    </AppShell>
  );
}
