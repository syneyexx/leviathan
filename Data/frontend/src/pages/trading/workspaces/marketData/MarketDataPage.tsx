/**
 * Market Data (WAVE 5/6) — native pixel-exact page.
 *
 * Absorbs Marktdata (offline dataset library, scan/register), Providers
 * ("live feeds"), dataset certification, and historical replay into ONE page
 * via progressive disclosure: PRIMARY dashboard (hero/KPIs/library/feed
 * health/coverage/regime/quality/activity/provenance/replay) always visible;
 * ADVANCED capabilities (import, feeds management, certification evaluation,
 * replay controls) live in drawers. NO MarktdataPage embedding.
 */
import { useState } from "react";
import { Link } from "react-router-dom";
import { TradingContextBar } from "../TradingContextBar";
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
    <main className="lv-main lv-tp-main lv-tc-workspace lv-md-page" aria-label="Market Data">
      <header className="lv-tc-workspace__header">
        <div>
          <p className="lv-tc-workspace__crumb">
            <Link to="/trading/command-hub">Trading Center</Link>
            <span aria-hidden="true"> / </span>
            <span>Market Data</span>
          </p>
          <h1 className="lv-tc-workspace__title">Market Data</h1>
          <p className="lv-tc-workspace__subtitle">
            Marktdata selecteren, valideren en monitoren voor trading research, backtesting en live trading.
          </p>
        </div>
        <div className="lv-tc-workspace__header-actions">
          <button type="button" className="lv-tc-btn" onClick={() => void refreshAll()} disabled={data.loading || ctx.loading}>
            Refresh
          </button>
          <span className="lv-tc-badge lv-tc-badge--exec" title={`LIVE_TRADING_AVAILABLE=${ctx.liveTrading}`}>
            {ctx.executionLabel}
          </span>
        </div>
      </header>

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
      {showCertify ? <CertifyDrawer data={data} initialRow={certifyRow} onClose={() => setShowCertify(false)} /> : null}
      {showReplay ? <ReplayDrawer data={data} initialRow={replayRow} onClose={() => setShowReplay(false)} /> : null}
    </main>
  );
}
