/**
 * Market Data (WAVE 5/6) — native pixel-exact page.
 * Absorbs Marktdata library, feeds, certification, replay. NO legacy embeds.
 */
import { useState } from "react";
import { AppShell } from "../../../../layouts/AppShell";
import { TradingContextBar } from "../TradingContextBar";
import { tradingCenterStatusRows } from "../tradingStatusRows";
import { useTradingContext } from "../useTradingContext";
import { CertifyDrawer, FeedsDrawer, ImportDrawer, ReplayDrawer } from "./MarketDataDrawers";
import { MarketDataView } from "./MarketDataView";
import type { LibraryRow } from "./useMarketDataWorkspace";
import { useMarketDataWorkspace } from "./useMarketDataWorkspace";
import "../../../../styles/trading-workspaces.css";
import "../../../../styles/trading-market-data-workspace.css";

export function MarketDataPage() {
  const ctx = useTradingContext();
  const data = useMarketDataWorkspace();

  const [selectedRow, setSelectedRow] = useState<LibraryRow | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [showFeeds, setShowFeeds] = useState(false);
  const [showCertify, setShowCertify] = useState(false);
  const [showReplay, setShowReplay] = useState(false);
  const [certifyRow, setCertifyRow] = useState<LibraryRow | null>(null);
  const [replayRow, setReplayRow] = useState<LibraryRow | null>(null);

  async function refreshAll() {
    await Promise.all([data.refresh(), data.refreshProviders(), ctx.refresh()]);
  }

  return (
    <AppShell
      variant="v2"
      v2Title="Trading Center / Market Data"
      v2Subtitle="Select, validate and monitor market data for trading research, backtesting and live trading."
      v2Online={!ctx.loading && !data.loading}
      v2Refreshing={ctx.loading || data.loading}
      onV2Refresh={() => void refreshAll()}
      v2StatusRows={tradingCenterStatusRows(ctx)}
      pageClass="lv-app--trading-market-data"
      v2ScrollableMain
    >
      <main className="lv-v2-page lv-md-page" aria-label="Market Data">
        <TradingContextBar ctx={ctx} />

        {data.error ? (
          <p className="lv-md-error" role="alert">
            {data.error}
            <button type="button" className="lv-md-btn" onClick={() => void data.refresh()}>
              Opnieuw proberen
            </button>
          </p>
        ) : null}

        <MarketDataView
          data={data}
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
          onSelectRow={setSelectedRow}
        />

        {selectedRow ? (
          <p className="lv-md-muted" style={{ marginTop: "-0.4rem" }}>
            Geselecteerd: <strong>{selectedRow.symbol}</strong> · {selectedRow.timeframe} · {selectedRow.path}
          </p>
        ) : null}

        {showImport ? <ImportDrawer data={data} onClose={() => setShowImport(false)} /> : null}
        {showFeeds ? <FeedsDrawer data={data} onClose={() => setShowFeeds(false)} /> : null}
        {showCertify ? (
          <CertifyDrawer data={data} initialRow={certifyRow} onClose={() => setShowCertify(false)} />
        ) : null}
        {showReplay ? (
          <ReplayDrawer data={data} initialRow={replayRow} onClose={() => setShowReplay(false)} />
        ) : null}
      </main>
    </AppShell>
  );
}
