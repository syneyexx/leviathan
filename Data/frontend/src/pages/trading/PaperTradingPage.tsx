import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tradingHeroes } from "../../assets/tradingAssets";
import { api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { Panel, TradingHero } from "./shared";

export function PaperTradingPage() {
  const [sessions, setSessions] = useState<Array<Record<string, unknown>>>([]);
  const [session, setSession] = useState<Record<string, unknown> | null>(null);
  const [shadowSession, setShadowSession] = useState<Record<string, unknown> | null>(null);
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [providerId, setProviderId] = useState("binance_public");
  const [side, setSide] = useState("BUY");
  const [qty, setQty] = useState("0.01");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [caps, setCaps] = useState<Record<string, unknown> | null>(null);
  const [bridgeReport, setBridgeReport] = useState<Record<string, unknown> | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [list, capabilities] = await Promise.all([
        api.listPaperSessions(),
        api.marketSimCapabilities(),
      ]);
      setSessions(list.sessions);
      setCaps(capabilities);
      if (session?.session_id) {
        const fresh = await api.getPaperSession(String(session.session_id));
        setSession(fresh.session);
      }
      if (shadowSession?.session_id) {
        const freshShadow = await api.getShadowLive(String(shadowSession.session_id));
        setShadowSession(freshShadow.session);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, [session?.session_id, shadowSession?.session_id]);

  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 4000);
    return () => window.clearInterval(id);
  }, [refresh]);

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const { session: created } = await api.createPaperSession({
        symbol,
        providerId,
        brokerId: "local_paper",
        initialCash: 100000,
      });
      setSession(created);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const startShadow = async () => {
    setBusy(true);
    setError(null);
    try {
      const { session: created } = await api.startShadowLive({ symbol, providerId });
      setShadowSession(created);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const place = async () => {
    if (!session?.session_id) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.placePaperOrder(String(session.session_id), {
        side,
        qty: Number(qty),
      });
      setSession((res.session as Record<string, unknown>) || session);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const shadowDecide = async () => {
    if (!shadowSession?.session_id) return;
    setBusy(true);
    setError(null);
    try {
      const res = await api.shadowLiveDecide(String(shadowSession.session_id), {
        side,
        qty: Number(qty),
      });
      setShadowSession((res.session as Record<string, unknown>) || shadowSession);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const exportBridge = async () => {
    if (!shadowSession?.session_id) return;
    setBusy(true);
    setError(null);
    try {
      const report = await api.exportTradingTrainingBridge({
        sessionId: String(shadowSession.session_id),
      });
      setBridgeReport(report);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const kill = async (armed: boolean) => {
    if (!session?.session_id) return;
    const { session: s } = await api.paperKillSwitch(String(session.session_id), armed);
    setSession(s);
  };

  const wallet = (session?.wallet as Record<string, unknown>) || {};
  const meta = (session?.metadata as Record<string, unknown>) || {};
  const quote = (meta.last_quote as Record<string, unknown>) || null;
  const orders = (session?.orders as Array<Record<string, unknown>>) || [];
  const shadowDecisions =
    (shadowSession?.decisions as Array<Record<string, unknown>>) || [];
  const paperMode = String(
    session?.execution_mode || session?.mode || meta.execution_mode || "LOCAL PAPER",
  );

  return (
    <AppShell layout="wide" pageClass="lv-app--trading">
      <TradingHero title="Paper Trading" image={tradingHeroes.paper} />
      <div className="lv-tp-wrap">
        <p className="lv-tp-lede">
          Modes are labeled explicitly — never as ambiguous &quot;LIVE&quot;:
          <strong> SHADOW</strong> (decide, no broker),
          <strong> LOCAL PAPER</strong> (local ledger + quotes),
          <strong> BROKER PAPER</strong> (configured paper venue only).
          Real-money remains BLOCKED.
        </p>
        <div className="lv-tp-kpi-grid" aria-label="Execution modes">
          <div className="lv-tp-kpi"><span>SHADOW</span><b>no broker order</b></div>
          <div className="lv-tp-kpi"><span>LOCAL PAPER</span><b>local ledger</b></div>
          <div className="lv-tp-kpi"><span>BROKER PAPER</span><b>paper venue only</b></div>
        </div>
        <p className="lv-tp-lede">
          Live paper mode uses a local ledger against public quotes. Not historical backtest.
          Not real money. Live broker orders remain blocked.
        </p>
        {error && <div className="lv-tp-banner is-bad">{error}</div>}

        <div className="lv-tp-kpi-grid">
          <div className="lv-tp-kpi"><span>Mode</span><strong>{paperMode}</strong></div>
          <div className="lv-tp-kpi"><span>Feed</span><strong>{String(session?.feed_status ?? "—")}</strong></div>
          <div className="lv-tp-kpi"><span>Cash</span><strong>{String(wallet.cash ?? "—")}</strong></div>
          <div className="lv-tp-kpi"><span>Equity</span><strong>{String(wallet.equity ?? "—")}</strong></div>
          <div className="lv-tp-kpi"><span>Position</span><strong>{String(wallet.position_qty ?? "—")}</strong></div>
          <div className="lv-tp-kpi"><span>Kill switch</span><strong>{session?.kill_switch ? "ARMED" : "off"}</strong></div>
        </div>

        <div className="lv-tp-grid-2">
          <Panel title="Session">
            <div className="lv-tp-form">
              <label>Symbol<input value={symbol} onChange={(e) => setSymbol(e.target.value)} /></label>
              <label>
                Provider
                <select value={providerId} onChange={(e) => setProviderId(e.target.value)}>
                  <option value="binance_public">binance_public</option>
                  <option value="csv_local">csv_local</option>
                  <option value="stooq_public">stooq_public</option>
                </select>
              </label>
              <button type="button" disabled={busy} onClick={() => void start()}>Start paper session</button>
              <button type="button" disabled={!session || busy} onClick={() => void kill(true)}>Arm kill switch</button>
              <button type="button" disabled={!session || busy} onClick={() => void kill(false)}>Disarm</button>
            </div>
            <ul className="lv-tp-list">
              {sessions.map((s) => (
                <li key={String(s.session_id)}>
                  <button type="button" onClick={() => setSession(s)}>
                    {String(s.symbol)} · {String(s.execution_mode || s.mode || "LOCAL PAPER")} ·{" "}
                    {String(s.status)} · {String(s.session_id).slice(0, 8)}
                  </button>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Order ticket (paper)">
            {quote ? (
              <p>Last quote: {String(quote.price)} ({String(quote.provider)})</p>
            ) : (
              <p className="lv-tp-muted">No quote yet — orders refuse without a price (no blind fill).</p>
            )}
            <div className="lv-tp-form">
              <label>
                Side
                <select value={side} onChange={(e) => setSide(e.target.value)}>
                  <option>BUY</option>
                  <option>SELL</option>
                </select>
              </label>
              <label>Qty<input value={qty} onChange={(e) => setQty(e.target.value)} /></label>
              <button type="button" disabled={!session || busy} onClick={() => void place()}>Submit paper order</button>
            </div>
            <ul className="lv-tp-list">
              {orders.slice().reverse().map((o) => (
                <li key={String(o.order_id)}>
                  {String(o.side)} {String(o.qty)} @ {String(o.fill_price ?? "—")} · {String(o.status)}
                  {o.reject_reason ? ` · ${String(o.reject_reason)}` : ""}
                </li>
              ))}
            </ul>
          </Panel>
        </div>

        <Panel title="Shadow Live (decide, no broker)">
          <p className="lv-tp-muted">
            Observe current market and record intended orders without submitting to any broker.
            Outcomes attach later for measurement and training export.
          </p>
          <div className="lv-tp-form">
            <button type="button" disabled={busy} onClick={() => void startShadow()}>
              Start shadow live
            </button>
            <button type="button" disabled={!shadowSession || busy} onClick={() => void shadowDecide()}>
              Record shadow decision
            </button>
            <button type="button" disabled={!shadowSession || busy} onClick={() => void exportBridge()}>
              Export training bridge
            </button>
          </div>
          {shadowSession && (
            <p>
              Shadow session {String(shadowSession.session_id).slice(0, 8)} · mode{" "}
              <strong>{String(shadowSession.mode || "SHADOW")}</strong> · decisions{" "}
              {shadowDecisions.length}
            </p>
          )}
          <ul className="lv-tp-list">
            {shadowDecisions.slice().reverse().map((d) => (
              <li key={String(d.decision_id)}>
                {String(d.side)} {String(d.qty)} @ expected {String(d.expected_execution_price ?? "—")}
                {d.realized_outcome ? " · outcome attached" : " · pending outcome"}
              </li>
            ))}
          </ul>
          {bridgeReport && (
            <pre className="lv-tp-pre">{JSON.stringify(bridgeReport, null, 2)}</pre>
          )}
        </Panel>

        <Panel title="Market capabilities (adapter-derived)">
          <pre className="lv-tp-pre">{JSON.stringify(caps?.markets ?? caps, null, 2)}</pre>
        </Panel>

        <p className="lv-tp-footer">
          <Link to="/trading/simulatie">Historical simulation</Link>
          {" · "}
          <Link to="/trading/broker">Live trading (blocked)</Link>
          {" · "}
          <Link to="/agents">Agents</Link>
        </p>
      </div>
    </AppShell>
  );
}
