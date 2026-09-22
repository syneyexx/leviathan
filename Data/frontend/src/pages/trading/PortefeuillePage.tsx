import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import {
  Donut,
  LineSeries,
  Panel,
  RingGauge,
  Spark,
  TradingHero,
} from "./shared";

const KPIS = [
  {
    label: "Total Equity",
    value: "$248,703.42",
    delta: "+2.48% · +$6,312.18",
    up: true,
    spark: [20, 24, 22, 28, 30, 34, 38, 42],
    muted: false,
  },
  {
    label: "Daily P&L",
    value: "+$6,312.18",
    delta: "+2.61%",
    up: true,
    spark: [10, 14, 18, 16, 22, 28, 30, 36],
    muted: false,
  },
  {
    label: "Total Exposure",
    value: "81.4%",
    delta: "Target 70–85%",
    up: true,
    spark: [60, 62, 65, 68, 72, 75, 78, 81],
    muted: true,
  },
  {
    label: "Cash Balance",
    value: "$46,927.38",
    delta: "18.6% of equity",
    up: true,
    spark: [40, 38, 36, 34, 32, 30, 28, 26],
    muted: true,
  },
  {
    label: "Portfolio Beta",
    value: "0.92",
    delta: "vs S&P 500",
    up: true,
    spark: [90, 91, 89, 92, 93, 91, 92, 92],
    muted: true,
  },
  {
    label: "YTD Return",
    value: "+14.27%",
    delta: "vs S&P +7.31%",
    up: true,
    spark: [5, 6, 7, 8, 9, 11, 12, 14],
    muted: false,
  },
] as const;

const RANGES = ["1D", "1W", "1M", "3M", "6M", "YTD", "1Y", "ALL"] as const;

const PORTFOLIO_SERIES = {
  portfolio: [100, 102, 101, 104, 107, 106, 110, 112, 111, 115, 118, 117, 121, 124, 122, 126, 128, 130, 129, 134],
  spy: [100, 101, 100, 102, 103, 102, 104, 105, 104, 106, 107, 106, 108, 109, 108, 110, 111, 112, 111, 113],
  nasdaq: [100, 101, 102, 101, 104, 105, 104, 107, 108, 107, 110, 112, 111, 114, 113, 116, 118, 117, 119, 121],
} as const;

const ALLOCATION = [
  { name: "Equities", value: 62.4, color: "#34d399" },
  { name: "ETFs", value: 16.8, color: "#22c9d6" },
  { name: "Crypto", value: 8.7, color: "#D6A957" },
  { name: "Bonds", value: 5.2, color: "#8b5cf6" },
  { name: "Cash", value: 18.6, color: "#64748b" },
  { name: "Other", value: 1.3, color: "#f472b6" },
] as const;

const SECTORS = [
  { name: "Technology", pct: 28.4 },
  { name: "Financials", pct: 14.2 },
  { name: "Healthcare", pct: 11.6 },
  { name: "Consumer", pct: 9.8 },
  { name: "Energy", pct: 7.4 },
  { name: "Industrials", pct: 6.2 },
  { name: "Communication", pct: 5.1 },
  { name: "Other", pct: 4.7 },
] as const;

const POSITIONS = [
  { sym: "AAPL", name: "Apple Inc.", qty: "120", avg: "162.40", px: "178.24", mv: "$21,388.80", pnl: "+$1,900.80", pct: "+9.76%", w: "8.6%" },
  { sym: "MSFT", name: "Microsoft", qty: "45", avg: "402.10", px: "425.60", mv: "$19,152.00", pnl: "+$1,057.50", pct: "+5.85%", w: "7.7%" },
  { sym: "NVDA", name: "NVIDIA", qty: "28", avg: "720.00", px: "875.40", mv: "$24,511.20", pnl: "+$4,351.20", pct: "+21.58%", w: "9.9%" },
  { sym: "TSLA", name: "Tesla", qty: "60", avg: "192.50", px: "172.80", mv: "$10,368.00", pnl: "−$1,182.00", pct: "−10.23%", w: "4.2%" },
  { sym: "AMZN", name: "Amazon", qty: "55", avg: "168.20", px: "182.10", mv: "$10,015.50", pnl: "+$764.50", pct: "+8.26%", w: "4.0%" },
  { sym: "GOOGL", name: "Alphabet", qty: "70", avg: "142.80", px: "156.40", mv: "$10,948.00", pnl: "+$952.00", pct: "+9.52%", w: "4.4%" },
  { sym: "SPY", name: "S&P 500 ETF", qty: "80", avg: "498.20", px: "524.18", mv: "$41,934.40", pnl: "+$2,078.40", pct: "+5.21%", w: "16.9%" },
  { sym: "BTC", name: "Bitcoin", qty: "0.18", avg: "82,400", px: "94,312", mv: "$16,976.16", pnl: "+$2,144.16", pct: "+14.46%", w: "6.8%" },
] as const;

const HEAT = [
  { name: "NVDA", pct: "+21.6%", tone: "up-lg" as const },
  { name: "AAPL", pct: "+9.8%", tone: "up" as const },
  { name: "MSFT", pct: "+5.9%", tone: "up" as const },
  { name: "GOOGL", pct: "+9.5%", tone: "up" as const },
  { name: "AMZN", pct: "+8.3%", tone: "up" as const },
  { name: "SPY", pct: "+5.2%", tone: "up" as const },
  { name: "TSLA", pct: "−10.2%", tone: "down-lg" as const },
  { name: "META", pct: "−2.4%", tone: "down" as const },
] as const;

const RISK = [
  { label: "VaR (95% 1D)", value: "$4,812" },
  { label: "Expected Shortfall", value: "$6,940" },
  { label: "Max Drawdown", value: "−6.8%" },
  { label: "Volatility (ann.)", value: "12.4%" },
  { label: "Sharpe Ratio", value: "1.32" },
  { label: "Alpha (YTD)", value: "6.96%" },
] as const;

const CORR_LABELS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY"] as const;
const CORR: number[][] = [
  [1.0, 0.72, 0.58, 0.41, 0.65, 0.78],
  [0.72, 1.0, 0.61, 0.38, 0.69, 0.81],
  [0.58, 0.61, 1.0, 0.52, 0.55, 0.64],
  [0.41, 0.38, 0.52, 1.0, 0.44, 0.36],
  [0.65, 0.69, 0.55, 0.44, 1.0, 0.74],
  [0.78, 0.81, 0.64, 0.36, 0.74, 1.0],
];

const REBAL = [
  { title: "Reduce NVDA", detail: "28.4% → 22.0% target", action: "Sell", tag: "over" as const, tagLabel: "Overweight" },
  { title: "Increase Bonds", detail: "5.2% → 10.0% target", action: "Buy", tag: "under" as const, tagLabel: "Underweight" },
  { title: "Trim TSLA", detail: "Cut risk · −40 shares", action: "Sell", tag: "over" as const, tagLabel: "High Vol" },
] as const;

const OPEN = [
  { sym: "NVDA", side: "LONG", qty: "28", pnl: "+$4,351" },
  { sym: "AAPL", side: "LONG", qty: "120", pnl: "+$1,901" },
  { sym: "TSLA", side: "LONG", qty: "60", pnl: "−$1,182" },
] as const;

const CLOSED = [
  { sym: "AMD", side: "LONG", qty: "40", pnl: "+$842" },
  { sym: "META", side: "SHORT", qty: "15", pnl: "+$318" },
  { sym: "COIN", side: "LONG", qty: "22", pnl: "−$214" },
] as const;

function corrTone(v: number) {
  if (v >= 0.7) return "hi";
  if (v >= 0.45) return "mid";
  return "lo";
}

export function PortefeuillePage() {
  const toast = useAppToast();
  const [range, setRange] = useState<(typeof RANGES)[number]>("YTD");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search positions, allocations, risk metrics..."
      systemItems={["MARKETS LIVE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="PORTEFEUILLE"
          kicker="ALLOCATE. MONITOR. PROTECT."
          quote="“Capital is a weapon. Discipline is the edge. A well-constructed portfolio turns uncertainty into opportunity.” — LEVIATHAN"
          image={tradingHeroes.portefeuille}
          rails={["LONGER HORIZONS", "STRONGER OUTCOMES", "CAPITAL DISCIPLINE", "INTELLIGENCE · FREEDOM"]}
          objectPosition="center 30%"
        />
        <section className="lv-tp-kpi-row" aria-label="Portfolio KPIs">
          {KPIS.map((k) => (
            <article key={k.label} className="lv-tp-kpi">
              <div className="lv-tp-kpi-label">{k.label}</div>
              <div className="lv-tp-kpi-value">{k.value}</div>
              <div className="lv-tp-kpi-foot">
                <span className={k.muted ? "lv-tp-kpi-sub" : k.up ? "is-good" : "is-bad"}>{k.delta}</span>
                <Spark points={k.spark} color={k.muted ? "#64748b" : "#34d399"} />
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tp-pf-mid">
          <Panel
            title="Portfolio Value"
            action={
              <div className="lv-tp-tf">
                {RANGES.map((r) => (
                  <button key={r} type="button" className={range === r ? "is-active" : ""} onClick={() => setRange(r)}>
                    {r}
                  </button>
                ))}
              </div>
            }
          >
            <LineSeries
              width={560}
              height={180}
              series={[
                { values: PORTFOLIO_SERIES.portfolio, color: "#34d399" },
                { values: PORTFOLIO_SERIES.spy, color: "#D6A957" },
                { values: PORTFOLIO_SERIES.nasdaq, color: "#22c9d6" },
              ]}
            />
            <div className="lv-tp-ma">
              <span><i style={{ background: "#34d399" }} /> Portfolio</span>
              <span><i style={{ background: "#D6A957" }} /> S&P 500</span>
              <span><i style={{ background: "#22c9d6" }} /> NASDAQ</span>
            </div>
            <div className="lv-tp-stats-side">
              <div>
                <span>Alpha</span>
                <strong className="is-good">6.96%</strong>
              </div>
              <div>
                <span>Volatility</span>
                <strong>12.4%</strong>
              </div>
              <div>
                <span>Sharpe</span>
                <strong>1.32</strong>
              </div>
              <div>
                <span>Max DD</span>
                <strong className="is-bad">−6.8%</strong>
              </div>
            </div>
          </Panel>

          <Panel title="Asset Allocation">
            <div className="lv-tp-donut-wrap">
              <Donut
                slices={ALLOCATION.map((a) => ({ value: a.value, color: a.color }))}
                center="$248.7k"
              />
              <ul className="lv-tp-legend">
                {ALLOCATION.map((a) => (
                  <li key={a.name}>
                    <span>
                      <i style={{ background: a.color }} />
                      {a.name}
                    </span>
                    <strong>{a.value}%</strong>
                  </li>
                ))}
              </ul>
            </div>
          </Panel>

          <Panel title="Sector Allocation">
            <ul className="lv-tp-sector-bars">
              {SECTORS.map((s) => (
                <li key={s.name}>
                  <div className="row">
                    <span>{s.name}</span>
                    <strong>{s.pct}%</strong>
                  </div>
                  <div className="lv-tp-bar">
                    <span style={{ width: `${(s.pct / 30) * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </section>

        <section className="lv-tp-pf-lists">
          <Panel title="Positions">
            <div className="lv-tp-table-wrap">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Qty</th>
                    <th>Avg</th>
                    <th>Price</th>
                    <th>Mkt Value</th>
                    <th>P&L</th>
                    <th>P&L%</th>
                    <th>Weight</th>
                  </tr>
                </thead>
                <tbody>
                  {POSITIONS.map((p) => (
                    <tr key={p.sym}>
                      <td className="sym">{p.sym}</td>
                      <td>{p.name}</td>
                      <td>{p.qty}</td>
                      <td>{p.avg}</td>
                      <td>{p.px}</td>
                      <td>{p.mv}</td>
                      <td className={p.pnl.startsWith("−") || p.pnl.startsWith("-") ? "is-bad" : "is-good"}>{p.pnl}</td>
                      <td className={p.pct.startsWith("−") || p.pct.startsWith("-") ? "is-bad" : "is-good"}>{p.pct}</td>
                      <td>{p.w}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Gain / Loss Heatmap">
            <div className="lv-tp-heat">
              {HEAT.map((h) => (
                <div key={h.name} className={`lv-tp-heat-cell ${h.tone}`}>
                  <strong>{h.name}</strong>
                  <span className={h.pct.startsWith("−") || h.pct.startsWith("-") ? "is-bad" : "is-good"}>{h.pct}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Risk Metrics & Correlation">
            <ul className="lv-tp-risk-list">
              {RISK.map((r) => (
                <li key={r.label}>
                  <span>{r.label}</span>
                  <strong>{r.value}</strong>
                </li>
              ))}
            </ul>
            <table className="lv-tp-corr" aria-label="Correlation matrix">
              <thead>
                <tr>
                  <th />
                  {CORR_LABELS.map((l) => (
                    <th key={l}>{l}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {CORR.map((row, i) => (
                  <tr key={CORR_LABELS[i]}>
                    <th>{CORR_LABELS[i]}</th>
                    {row.map((v, j) => (
                      <td key={`${i}-${j}`} className={corrTone(v)}>
                        {v.toFixed(2)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>
        </section>

        <section className="lv-tp-pf-bottom">
          <Panel
            title="Rebalancing Suggestions"
            action={
              <button type="button" className="lv-tp-mini" onClick={() => toast("Apply rebalance")}>
                Apply All
              </button>
            }
          >
            <ul className="lv-tp-rebal">
              {REBAL.map((r) => (
                <li key={r.title}>
                  <div>
                    <strong>{r.title}</strong>
                    <span>{r.detail}</span>
                  </div>
                  <button type="button" className="lv-tp-mini" onClick={() => toast(`${r.action} · ${r.title}`)}>
                    {r.action}
                  </button>
                  <span className={`lv-tp-tag ${r.tag}`}>{r.tagLabel}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Open Positions & Closed Trades">
            <div className="lv-tp-split-tables">
              <div>
                <div className="lv-tp-panel-title" style={{ marginBottom: 6 }}>Open</div>
                <table className="lv-tp-table">
                  <thead>
                    <tr>
                      <th>Sym</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>P&L</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {OPEN.map((o) => (
                      <tr key={o.sym}>
                        <td className="sym">{o.sym}</td>
                        <td><span className={`lv-tp-side ${o.side.toLowerCase()}`}>{o.side}</span></td>
                        <td>{o.qty}</td>
                        <td className={o.pnl.startsWith("−") || o.pnl.startsWith("-") ? "is-bad" : "is-good"}>{o.pnl}</td>
                        <td>
                          <button type="button" className="lv-tp-mini" onClick={() => toast(`Close ${o.sym}`)}>
                            Close
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <div className="lv-tp-panel-title" style={{ marginBottom: 6 }}>Closed</div>
                <table className="lv-tp-table">
                  <thead>
                    <tr>
                      <th>Sym</th>
                      <th>Side</th>
                      <th>Qty</th>
                      <th>P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {CLOSED.map((c) => (
                      <tr key={c.sym}>
                        <td className="sym">{c.sym}</td>
                        <td><span className={`lv-tp-side ${c.side.toLowerCase()}`}>{c.side}</span></td>
                        <td>{c.qty}</td>
                        <td className={c.pnl.startsWith("−") || c.pnl.startsWith("-") ? "is-bad" : "is-good"}>{c.pnl}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </Panel>

          <Panel title="Account Health">
            <div className="lv-tp-health-rings">
              <RingGauge value={94} label="Margin Level" />
              <RingGauge value={100} label="Liquidity" />
              <RingGauge value={0} label="Margin Calls" display="0" color="#22c9d6" />
              <RingGauge value={88} label="Risk Score" display="A" color="#D6A957" />
            </div>
          </Panel>
        </section>

        <p className="lv-footer-quote">
          “Better portfolios. A freer tomorrow.” — LEVIATHAN
        </p>
      </main>
    </AppShell>
  );
}
