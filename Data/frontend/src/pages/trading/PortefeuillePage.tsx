import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero, fmtMoney } from "./shared";

export function PortefeuillePage() {
  const [runs, setRuns] = useState<Array<Record<string, unknown>>>([]);
  const [paper, setPaper] = useState<Array<Record<string, unknown>>>([]);
  const [live, setLive] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [runList, sessions, liveStatus] = await Promise.all([
          api.listMarketSimRuns(20),
          api.listPaperSessions().catch(() => ({ sessions: [] })),
          api.marketSimLiveTradingStatus().catch(() => null),
        ]);
        setRuns(runList.runs as unknown as Array<Record<string, unknown>>);
        setPaper(sessions.sessions);
        setLive(liveStatus);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    })();
  }, []);

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero title="Portefeuille" image={tradingHeroes.portefeuille} />
      <div className="lv-tp-wrap">
        <p className="lv-tp-lede">
          Books are separated by mode: historical simulation, live paper, and live broker.
          Live broker remains blocked. Figures below are from the control plane — not fabricated.
        </p>
        {error && <div className="lv-tp-banner is-bad">{error}</div>}

        <div className="lv-tp-grid-3">
          <Panel title="Historical simulation">
            <ul className="lv-tp-list">
              {runs.map((r) => (
                <li key={String(r.run_id)}>
                  <strong>{String(r.symbol)}</strong> · {String(r.status)}
                  <div>equity {fmtMoney(Number(r.equity))} · cash {fmtMoney(Number(r.cash))} · pos {String(r.position_qty)}</div>
                  <div className="lv-tp-muted">run {String(r.run_id).slice(0, 8)} · hash {String(r.data_hash).slice(0, 10)}</div>
                </li>
              ))}
              {!runs.length && <li className="lv-tp-muted">No simulation runs</li>}
            </ul>
            <Link to="/trading/simulatie">Open simulation</Link>
          </Panel>

          <Panel title="Live paper">
            <ul className="lv-tp-list">
              {paper.map((s) => {
                const w = (s.wallet as Record<string, unknown>) || {};
                return (
                  <li key={String(s.session_id)}>
                    <strong>{String(s.symbol)}</strong> · {String(s.status)} · feed {String(s.feed_status)}
                    <div>cash {String(w.cash ?? "—")} · equity {String(w.equity ?? "—")}</div>
                  </li>
                );
              })}
              {!paper.length && <li className="lv-tp-muted">No paper sessions</li>}
            </ul>
            <Link to="/trading/paper">Open paper trading</Link>
          </Panel>

          <Panel title="Live broker">
            <p><strong>{String(live?.LIVE_TRADING_AVAILABLE ?? "BLOCKED")}</strong></p>
            <p className="lv-tp-muted">{String(live?.detail ?? "Live orders are blocked by default.")}</p>
            <Link to="/trading/broker">Broker status</Link>
          </Panel>
        </div>
      </div>
    </AppShell>
  );
}
