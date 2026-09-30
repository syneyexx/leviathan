/**
 * Trading Desk (WAVE 5/6) — PRIMARY pixel layout.
 * Hero + CTAs → KPI strip → chart/toolbar → wallets table → positions/orders →
 * risk & allocation panel → activity/decisions stream.
 */
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import type { PortfolioPosition, PortfolioRecommendation } from "../../../../types/api";
import { UNMEASURED } from "../commandHub/hubFormat";
import type { OrderRow, TradingDeskData, WalletRow } from "./useTradingDeskData";

function fmtUsd(n: number | null | undefined, digits = 0): string {
  if (n == null || Number.isNaN(n)) return UNMEASURED;
  const sign = n < 0 ? "-" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits })}`;
}

function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return UNMEASURED;
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

function fmtMetric(n: number | null | undefined, digits = 2): string {
  if (n == null || Number.isNaN(n)) return UNMEASURED;
  return n.toFixed(digits);
}

function toneClass(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return "is-muted";
  return n >= 0 ? "is-good" : "is-bad";
}

function num(v: string | number | null | undefined): number {
  if (v == null || v === "") return 0;
  const n = typeof v === "number" ? v : Number(v);
  return Number.isFinite(n) ? n : 0;
}

function PriceChart({ bars, symbol, timeframe }: { bars: TradingDeskData["bars"]; symbol: string; timeframe: string }) {
  const width = 720;
  const height = 220;
  const closes = bars.map((b) => b.close);
  if (closes.length < 2) {
    return (
      <div className="lv-td-chart__empty">
        <p>No bars indexed for {symbol} · {timeframe} — open Market Data to index a source.</p>
      </div>
    );
  }
  const max = Math.max(...closes);
  const min = Math.min(...closes);
  const span = max - min || 1;
  const pad = 12;
  const coords = closes.map((v, i) => {
    const x = pad + (i / (closes.length - 1)) * (width - pad * 2);
    const y = height - pad - ((v - min) / span) * (height - pad * 2);
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const area = `${line} L${width - pad},${height - pad} L${pad},${height - pad} Z`;
  const last = closes[closes.length - 1];
  const first = closes[0];
  const changePct = first ? ((last - first) / first) * 100 : null;
  const tone = changePct == null ? "muted" : changePct >= 0 ? "green" : "red";
  return (
    <div className="lv-td-chart">
      <div className="lv-td-chart__head">
        <span className="lv-td-chart__symbol">{symbol}</span>
        <span className="lv-td-chart__price">{fmtUsd(last, last < 10 ? 4 : 2)}</span>
        <span className={`lv-hub-tone-${tone}`}>{fmtPct(changePct)}</span>
        <span className="lv-td-chart__tf">{timeframe}</span>
      </div>
      <svg className="lv-td-chart__svg" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
        <path d={area} fill="url(#tdChartFill)" opacity="0.85" />
        <path d={line} fill="none" stroke={tone === "red" ? "#f87171" : "#22d3ee"} strokeWidth="2" strokeLinejoin="round" />
        <defs>
          <linearGradient id="tdChartFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={tone === "red" ? "#f87171" : "#22d3ee"} stopOpacity="0.28" />
            <stop offset="100%" stopColor={tone === "red" ? "#f87171" : "#22d3ee"} stopOpacity="0" />
          </linearGradient>
        </defs>
      </svg>
    </div>
  );
}

function WalletsTable({
  data,
  onSelect,
}: {
  data: TradingDeskData;
  onSelect: (id: string) => void;
}) {
  if (!data.wallets.length) {
    return (
      <p className="lv-td-empty">
        No paper wallets yet — click <strong>Open portfolio create</strong> in the hero to create one.
      </p>
    );
  }
  return (
    <div className="lv-td-table-scroll">
      <table className="lv-td-table">
        <thead>
          <tr>
            <th>Wallet / Portfolio</th>
            <th>Status</th>
            <th>Mode</th>
            <th>Equity</th>
            <th>Cash</th>
            <th>Unrealized</th>
            <th>Realized</th>
            <th>Kill switch</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {data.wallets.map((w: WalletRow) => (
            <tr
              key={w.id}
              className={data.selectedPortfolioId === w.id ? "is-selected" : ""}
              onClick={() => onSelect(w.id)}
            >
              <td>{w.name}</td>
              <td>
                <span className={`lv-td-pill lv-td-pill--${w.status.toLowerCase()}`}>{w.status}</span>
              </td>
              <td>{w.mode}</td>
              <td>{fmtUsd(w.equity)}</td>
              <td>{fmtUsd(w.cash)}</td>
              <td className={toneClass(w.unrealizedPnl)}>{fmtUsd(w.unrealizedPnl)}</td>
              <td className={toneClass(w.realizedPnl)}>{fmtUsd(w.realizedPnl)}</td>
              <td>{w.killSwitch ? <span className="lv-td-pill lv-td-pill--armed">ARMED</span> : "—"}</td>
              <td onClick={(e) => e.stopPropagation()} className="lv-td-row-actions">
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--ghost"
                  disabled={!!data.busy}
                  onClick={() => void data.lifecycle("start", w.id)}
                >
                  Start
                </button>
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--ghost"
                  disabled={!!data.busy}
                  onClick={() => void data.lifecycle("pause", w.id)}
                >
                  Pause
                </button>
                <button
                  type="button"
                  className="lv-td-btn lv-td-btn--ghost"
                  disabled={!!data.busy}
                  onClick={() => void data.lifecycle("resume", w.id)}
                >
                  Resume
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function PositionsTable({ data }: { data: TradingDeskData }) {
  const positions: PortfolioPosition[] = data.positions;
  if (!positions.length) {
    return <p className="lv-td-empty">No open positions for this wallet.</p>;
  }
  return (
    <>
      <div className="lv-td-panel__toolbar">
        <button
          type="button"
          className="lv-td-btn lv-td-btn--danger"
          disabled={!data.selectedPositions.length || !!data.busy}
          onClick={() => void data.closeSelectedPositions()}
        >
          Close Selected ({data.selectedPositions.length})
        </button>
      </div>
      <div className="lv-td-table-scroll" style={{ maxHeight: 260 }}>
        <table className="lv-td-table">
          <thead>
            <tr>
              <th />
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Mark</th>
              <th>PnL</th>
              <th>Alloc</th>
              <th>Risk</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.position_id}>
                <td>
                  <input
                    type="checkbox"
                    checked={data.selectedPositions.includes(p.position_id)}
                    onChange={(e) =>
                      data.setSelectedPositions((prev) =>
                        e.target.checked ? [...prev, p.position_id] : prev.filter((id) => id !== p.position_id),
                      )
                    }
                  />
                </td>
                <td>{p.symbol}</td>
                <td>
                  <span className={`lv-td-chip ${p.side === "LONG" ? "is-long" : "is-short"}`}>{p.side}</span>
                </td>
                <td>{p.qty}</td>
                <td>{fmtUsd(num(p.avg_entry_price))}</td>
                <td>{fmtUsd(num(p.mark_price))}</td>
                <td className={toneClass(num(p.unrealized_pnl))}>{fmtUsd(num(p.unrealized_pnl))}</td>
                <td>{p.allocation_pct.toFixed(1)}%</td>
                <td>
                  <span className={`lv-td-chip is-risk-${String(p.risk).toLowerCase()}`}>{p.risk}</span>
                </td>
                <td>
                  <button
                    type="button"
                    className="lv-td-btn lv-td-btn--danger"
                    disabled={!!data.busy}
                    onClick={() => void data.closePosition(p.position_id)}
                  >
                    Close
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function OrdersTable({ orders }: { orders: OrderRow[] }) {
  if (!orders.length) {
    return <p className="lv-td-empty">No orders placed yet for this wallet.</p>;
  }
  return (
    <div className="lv-td-table-scroll" style={{ maxHeight: 260 }}>
      <table className="lv-td-table">
        <thead>
          <tr>
            <th>Time</th>
            <th>Symbol</th>
            <th>Side</th>
            <th>Qty</th>
            <th>Status</th>
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td>{o.createdAt.slice(11, 19) || o.createdAt}</td>
              <td>{o.symbol}</td>
              <td>
                <span className={`lv-td-chip ${o.side === "BUY" || o.side === "COVER" ? "is-long" : "is-short"}`}>
                  {o.side}
                </span>
              </td>
              <td>{o.qty}</td>
              <td>
                <span className="lv-td-pill">{o.status}</span>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function RiskGuardPanel({ data, onOpenAdvanced }: { data: TradingDeskData; onOpenAdvanced: () => void }) {
  const dash = data.dashboard;
  if (!dash) {
    return (
      <div>
        <p className="lv-td-empty">Select a wallet to load risk &amp; allocation.</p>
      </div>
    );
  }
  return (
    <div className="lv-td-riskguard">
      <ul className="lv-td-metric-list">
        <li><span>Sharpe</span><strong>{fmtMetric(dash.risk.sharpe)}</strong></li>
        <li><span>Sortino</span><strong>{fmtMetric(dash.risk.sortino)}</strong></li>
        <li><span>Max drawdown</span><strong>{fmtPct(dash.risk.max_drawdown)}</strong></li>
        <li><span>VaR 1D 95%</span><strong>{fmtPct(dash.risk.var_1d_95)}</strong></li>
        <li><span>Volatility</span><strong>{fmtPct(dash.risk.volatility)}</strong></li>
        <li><span>Leverage</span><strong>{fmtMetric(dash.exposure.leverage)}x</strong></li>
        <li><span>Gross exposure</span><strong>{fmtPct(dash.exposure.gross_exposure_pct)}</strong></li>
        <li><span>Stress level</span><strong>{dash.risk.stress_level}</strong></li>
      </ul>
      <div className="lv-td-recommendations">
        <header>
          <h4>Rebalancing recommendations</h4>
          <button
            type="button"
            className="lv-td-btn"
            disabled={!dash.recommendations?.length || !!data.busy}
            onClick={() => void data.rebalanceExecute()}
          >
            Execute All
          </button>
        </header>
        {(dash.recommendations || []).length ? (
          <ul className="lv-td-rec-list">
            {dash.recommendations.map((r: PortfolioRecommendation) => (
              <li key={r.recommendation_id}>
                <div>
                  <strong>{r.type.replace(/_/g, " ")}</strong>
                  <span className={`lv-td-impact is-${r.impact.toLowerCase()}`}>{r.impact}</span>
                </div>
                <p>{r.reason}</p>
                <button
                  type="button"
                  className="lv-td-btn"
                  disabled={!!data.busy || !r.estimated_orders?.length}
                  onClick={() => void data.runRecommendation(r)}
                >
                  Run
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="lv-td-empty">No rebalancing recommendations — book within targets.</p>
        )}
      </div>
      <div className="lv-td-riskguard__foot">
        <button type="button" className="lv-td-btn" disabled={!!data.busy} onClick={() => void data.saveAllocations()}>
          Save Allocation
        </button>
        <button type="button" className="lv-td-btn" onClick={() => void data.exportPortfolio("csv")}>
          Export CSV
        </button>
        <button type="button" className="lv-td-btn lv-td-btn--ghost" onClick={onOpenAdvanced}>
          Advanced ▸
        </button>
      </div>
    </div>
  );
}

function ActivityStream({ data }: { data: TradingDeskData }) {
  if (!data.activity.length) {
    return <p className="lv-td-empty">No agent decisions recorded yet for the current mandate.</p>;
  }
  return (
    <ul className="lv-td-activity">
      {data.activity.map((a) => (
        <li key={a.id}>
          <span className="lv-td-activity__time">{a.time.slice(11, 19) || a.time}</span>
          <span className="lv-td-activity__agent">{a.agent}</span>
          <span className="lv-td-activity__stage">{a.stage}</span>
          <span className="lv-td-activity__summary">{a.summary}</span>
        </li>
      ))}
    </ul>
  );
}

export function TradingDeskView({
  data,
  onOpenCreatePortfolio,
  onOpenDeploy,
  onOpenAdvanced,
}: {
  data: TradingDeskData;
  onOpenCreatePortfolio: () => void;
  onOpenDeploy: () => void;
  onOpenAdvanced: () => void;
}) {
  const [tab, setTab] = useState<"positions" | "orders">("positions");

  const wallet = data.selectedWallet;
  const killArmed = wallet?.killSwitch ?? false;

  const kpis = data.kpis;

  const kpiCards = useMemo(
    () => [
      { id: "equity", label: "Equity", value: fmtUsd(kpis.equity), tone: "muted" },
      { id: "cash", label: "Cash", value: fmtUsd(kpis.cash), tone: "muted" },
      { id: "positions", label: "Open Positions", value: String(kpis.openPositions), tone: "muted" },
      {
        id: "daypnl",
        label: "Day PnL",
        value: `${fmtUsd(kpis.dayPnl)} (${fmtPct(kpis.dayPnlPct)})`,
        tone: toneClass(kpis.dayPnl),
      },
      { id: "risk", label: "Risk Status", value: kpis.riskStatus, tone: "muted" },
      { id: "live", label: "Live Trading", value: kpis.liveTrading, tone: kpis.liveTrading === "BLOCKED" ? "is-bad" : "is-warn" },
    ],
    [kpis],
  );

  return (
    <div className="lv-td-view" aria-busy={data.loading}>
      <section className="lv-td-hero" aria-label="Trading Desk">
        <div className="lv-td-hero__copy">
          <p className="lv-td-hero__kicker">Autonomous Trading Desk</p>
          <h2>Paper execution, wallets &amp; risk in one operator surface</h2>
          <p className="lv-td-hero__sub">
            Absorbs Paper Trading, Portefeuille, Broker boundary and Wallets into a single desk. Live money
            remains <strong>{data.liveTrading}</strong> — every action here is paper / simulated capital.
          </p>
          <div className="lv-td-hero__cta">
            <button type="button" className="lv-td-btn lv-td-btn--primary" onClick={onOpenDeploy}>
              Deploy paper
            </button>
            <button
              type="button"
              className="lv-td-btn lv-td-btn--danger"
              disabled={!data.selectedPortfolioId || !!data.busy}
              onClick={() => void data.flatten()}
            >
              Flatten
            </button>
            <button
              type="button"
              className={`lv-td-btn ${killArmed ? "lv-td-btn--danger" : "lv-td-btn--ghost"}`}
              disabled={!data.selectedPortfolioId || !!data.busy}
              onClick={() => void data.killSwitch(!killArmed)}
            >
              {killArmed ? "Disarm kill switch" : "Kill switch"}
            </button>
            <button type="button" className="lv-td-btn" onClick={onOpenCreatePortfolio}>
              Open portfolio create
            </button>
            <Link className="lv-td-btn lv-td-btn--ghost" to="/trading/command-hub">
              Command Hub
            </Link>
          </div>
        </div>
        <div className="lv-td-hero__wallet">
          <span className="lv-td-hero__wallet-label">Active wallet</span>
          <select
            className="lv-td-select"
            value={data.selectedPortfolioId}
            onChange={(e) => data.setSelectedPortfolioId(e.target.value)}
          >
            {!data.wallets.length ? <option value="">No wallet</option> : null}
            {data.wallets.map((w) => (
              <option key={w.id} value={w.id}>
                {w.name} · {w.status}
              </option>
            ))}
          </select>
        </div>
      </section>

      {data.error ? (
        <p className="lv-td-error" role="alert">
          {data.error}
          <button type="button" className="lv-td-btn" onClick={() => void data.refresh()}>
            Retry
          </button>
        </p>
      ) : null}

      {data.notice ? (
        <p className="lv-td-notice" role="status">
          {data.notice}
        </p>
      ) : null}

      <section className="lv-td-kpis" aria-busy={data.dashboardLoading}>
        {kpiCards.map((k) => (
          <article key={k.id} className="lv-td-kpi">
            <p className="lv-td-kpi__label">{k.label}</p>
            <p className={`lv-td-kpi__value ${k.tone}`}>{data.loading ? "…" : k.value}</p>
          </article>
        ))}
      </section>

      <section className="lv-td-main-grid">
        <article className="lv-td-panel lv-td-panel--chart">
          <header>
            <h3>Market chart</h3>
            <span className="lv-td-panel__badge">{data.barsLoading ? "Loading…" : `${data.bars.length} bars`}</span>
          </header>
          <PriceChart bars={data.bars} symbol={data.market} timeframe={data.timeframe} />
        </article>

        <article className="lv-td-panel lv-td-panel--riskguard">
          <header>
            <h3>RiskGuard &amp; Allocation</h3>
          </header>
          <RiskGuardPanel data={data} onOpenAdvanced={onOpenAdvanced} />
        </article>
      </section>

      <section className="lv-td-panel" aria-label="Wallets (Paper)">
        <header>
          <h3>Wallets (Paper) · {data.wallets.length}</h3>
          <span className="lv-td-panel__badge">Total equity {fmtUsd(data.totalEquity)}</span>
        </header>
        <WalletsTable data={data} onSelect={(id) => data.setSelectedPortfolioId(id)} />
      </section>

      <section className="lv-td-panel" aria-label="Positions & Orders">
        <header>
          <div className="lv-td-tabs">
            <button type="button" className={tab === "positions" ? "is-active" : ""} onClick={() => setTab("positions")}>
              Positions ({data.positions.length})
            </button>
            <button type="button" className={tab === "orders" ? "is-active" : ""} onClick={() => setTab("orders")}>
              Orders ({data.orders.length})
            </button>
          </div>
        </header>
        {tab === "positions" ? <PositionsTable data={data} /> : <OrdersTable orders={data.orders} />}
      </section>

      <section className="lv-td-panel" aria-label="Activity / Decisions">
        <header>
          <h3>Activity / Decisions</h3>
          <span className="lv-td-panel__badge">Latest {data.activity.length}</span>
        </header>
        <ActivityStream data={data} />
      </section>
    </div>
  );
}
