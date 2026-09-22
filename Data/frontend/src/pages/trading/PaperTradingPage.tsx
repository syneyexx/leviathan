import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import {
  AreaSpark,
  CandleChart,
  MOCK_CANDLES,
  Panel,
  RingGauge,
  Spark,
  Tone,
  TradingHero,
} from "./shared";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;
const SIDES = ["Buy", "Sell", "Short", "Cover"] as const;

const KPIS = [
  { label: "Account Balance", value: "$100,000.00", delta: "+2.85%", up: true, spark: [20, 22, 24, 26, 28, 30, 32, 34], muted: false },
  { label: "Buying Power", value: "$97,152.68", delta: "Available", up: true, spark: [40, 39, 38, 37, 36, 35, 34, 33], muted: true },
  { label: "Total P&L (Sim)", value: "+$2,847.32", delta: "+2.85%", up: true, spark: [10, 14, 12, 18, 22, 20, 26, 30], muted: false },
  { label: "Day P&L", value: "+$412.18", delta: "+0.41%", up: true, spark: [15, 16, 18, 17, 20, 22, 21, 24], muted: false },
  { label: "Trade Stats", value: "36 trades", delta: "Win 69.4% · Sharpe 1.32", up: true, spark: [30, 32, 34, 33, 36, 38, 40, 42], muted: true },
] as const;

const WATCH = [
  { symbol: "AAPL", price: "178.24", chg: "+1.09%", up: true, spark: [20, 22, 24, 23, 26, 28, 27, 30] },
  { symbol: "NVDA", price: "875.40", chg: "+2.14%", up: true, spark: [25, 28, 30, 34, 32, 38, 40, 44] },
  { symbol: "TSLA", price: "172.80", chg: "−1.84%", up: false, spark: [50, 48, 46, 44, 42, 40, 38, 36] },
  { symbol: "MSFT", price: "425.60", chg: "+0.72%", up: true, spark: [28, 29, 30, 31, 30, 32, 33, 34] },
  { symbol: "AMZN", price: "182.10", chg: "+0.95%", up: true, spark: [22, 24, 23, 26, 28, 27, 29, 31] },
  { symbol: "META", price: "512.30", chg: "−0.42%", up: false, spark: [40, 39, 41, 40, 38, 37, 38, 36] },
  { symbol: "GOOGL", price: "156.40", chg: "+0.68%", up: true, spark: [24, 25, 26, 25, 27, 28, 29, 30] },
  { symbol: "SPY", price: "524.18", chg: "+0.35%", up: true, spark: [30, 31, 32, 31, 33, 34, 35, 36] },
] as const;

const POSITIONS = [
  { sym: "AAPL", side: "LONG", shares: "100", avg: "172.40", last: "178.24", pnl: "+$584.00", pct: "+3.39%" },
  { sym: "NVDA", side: "LONG", shares: "15", avg: "840.00", last: "875.40", pnl: "+$531.00", pct: "+4.21%" },
  { sym: "TSLA", side: "SHORT", shares: "40", avg: "180.20", last: "172.80", pnl: "+$296.00", pct: "+4.11%" },
  { sym: "MSFT", side: "LONG", shares: "25", avg: "418.00", last: "425.60", pnl: "+$190.00", pct: "+1.82%" },
] as const;

const OPEN_ORDERS = [
  { type: "Limit", side: "Buy", sym: "AMZN", px: "180.50", qty: "30", status: "Working", time: "10:12:04" },
  { type: "Stop", side: "Sell", sym: "AAPL", px: "174.00", qty: "100", status: "Armed", time: "09:48:22" },
] as const;

const FILLED = [
  { type: "Market", side: "Buy", sym: "NVDA", px: "840.00", qty: "15", status: "Filled", time: "09:21:18" },
  { type: "Limit", side: "Sell", sym: "META", px: "518.40", qty: "20", status: "Filled", time: "08:56:41" },
  { type: "Market", side: "Short", sym: "TSLA", px: "180.20", qty: "40", status: "Filled", time: "08:14:09" },
] as const;

const JOURNAL = [
  { t: "10:18", sym: "AAPL", setup: "Momentum", result: "+$184", note: "Clean breakout above VWAP, held through pullback." },
  { t: "09:42", sym: "NVDA", setup: "Pullback", result: "+$210", note: "Bought dip to 20 EMA · scaled out ⅓." },
  { t: "09:05", sym: "TSLA", setup: "Breakdown", result: "+$96", note: "Short into failed reclaim of prior day high." },
  { t: "08:51", sym: "META", setup: "Mean Rev", result: "−$62", note: "Stopped — news spike invalidated setup." },
  { t: "08:22", sym: "SPY", setup: "ORB", result: "+$48", note: "Opening range break · tight risk." },
] as const;

const CHALLENGE = [
  { label: "Complete 50 trades", done: false },
  { label: "Win rate ≥ 60%", done: true },
  { label: "Max DD under $2,000", done: true },
  { label: "Journal every trade", done: true },
  { label: "No revenge trades", done: false },
] as const;

const MARKERS = [
  { index: 5, side: "B" as const },
  { index: 11, side: "S" as const },
  { index: 16, side: "B" as const },
  { index: 20, side: "S" as const },
];

const SLIP = [12, 28, 44, 62, 48, 30, 18, 10, 6];

export function PaperTradingPage() {
  const toast = useAppToast();
  const [tf, setTf] = useState<(typeof TIMEFRAMES)[number]>("15m");
  const [side, setSide] = useState<(typeof SIDES)[number]>("Buy");
  const [shares, setShares] = useState("100");
  const [tp, setTp] = useState(true);
  const [sl, setSl] = useState(true);

  const isSellish = side === "Sell" || side === "Short";

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search symbols, strategies, insights..."
      systemItems={["PAPER TRADING", "SIMULATION MODE"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="PAPER TRADING"
          kicker="PRACTICE. EXECUTE. LEARN."
          quote="“The market is a teacher. Paper trading is your rehearsal for mastery.” — LEVIATHAN"
          image={tradingHeroes.paper}
          rails={["SIMULATE · REFINE · BUILD", "DISCIPLINE · DOMINATE", "SAME MARKETS", "REAL OPPORTUNITY · ZERO RISK"]}
          objectPosition="center 28%"
        />
        <section className="lv-tp-kpi-row" aria-label="Paper account metrics">
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
          <article className="lv-tp-kpi lv-tp-broker-card">
            <div className="lv-tp-kpi-label">Broker Status</div>
            <div className="lv-tp-kpi-value">SANDBOX BROKER</div>
            <div className="lv-tp-kpi-sub">Paper Trading Environment</div>
            <span className="lv-tp-sim-badge">
              <i /> Connected · SIM
            </span>
          </article>
        </section>

        <section className="lv-tp-paper-mid">
          <Panel
            title="AAPL · Apple Inc."
            action={
              <div className="lv-tp-tf">
                {TIMEFRAMES.map((item) => (
                  <button key={item} type="button" className={tf === item ? "is-active" : ""} onClick={() => setTf(item)}>
                    {item}
                  </button>
                ))}
              </div>
            }
          >
            <div className="lv-tp-chart-head">
              <div>
                <span className="lv-tp-price">178.24</span>
                <Tone value={true}>+$1.92 (+1.09%)</Tone>
                <div className="lv-tp-chart-meta">Simulated fills marked B / S</div>
              </div>
            </div>
            <CandleChart candles={MOCK_CANDLES} height={250} markers={MARKERS} />
            <div className="lv-tp-ma">
              <span><i style={{ background: "#D6A957" }} /> SMA 20</span>
              <span><i style={{ background: "#22C9D6" }} /> SMA 50</span>
              <span><i style={{ background: "#8b5cf6" }} /> SMA 200</span>
            </div>
          </Panel>

          <Panel title="Order Ticket (Simulated)">
            <div className="lv-tp-side-tabs">
              {SIDES.map((s) => (
                <button
                  key={s}
                  type="button"
                  className={`${s.toLowerCase()}${side === s ? " is-active" : ""}`}
                  onClick={() => setSide(s)}
                >
                  {s}
                </button>
              ))}
            </div>
            <label className="lv-tp-field">
              <span>Symbol</span>
              <select defaultValue="AAPL">
                <option>AAPL</option>
                <option>NVDA</option>
                <option>TSLA</option>
                <option>MSFT</option>
              </select>
            </label>
            <div className="lv-tp-field-row">
              <label className="lv-tp-field">
                <span>Order Type</span>
                <select defaultValue="Market">
                  <option>Market</option>
                  <option>Limit</option>
                  <option>Stop</option>
                </select>
              </label>
              <label className="lv-tp-field">
                <span>Shares</span>
                <input value={shares} onChange={(e) => setShares(e.target.value)} />
              </label>
            </div>
            <label className="lv-tp-field">
              <span>Time in Force</span>
              <select defaultValue="Day">
                <option>Day</option>
                <option>GTC</option>
                <option>IOC</option>
              </select>
            </label>
            <div className="lv-tp-toggle-row">
              <label>
                <input type="checkbox" checked={tp} onChange={(e) => setTp(e.target.checked)} />
                Take Profit
              </label>
              <label>
                <input type="checkbox" checked={sl} onChange={(e) => setSl(e.target.checked)} />
                Stop Loss
              </label>
            </div>
            {tp || sl ? (
              <div className="lv-tp-field-row">
                {tp ? (
                  <label className="lv-tp-field">
                    <span>TP Price</span>
                    <input defaultValue="184.50" />
                  </label>
                ) : null}
                {sl ? (
                  <label className="lv-tp-field">
                    <span>SL Price</span>
                    <input defaultValue="174.00" />
                  </label>
                ) : null}
              </div>
            ) : null}
            <div className="lv-tp-est">
              <span>
                Est. Cost <strong>$17,824.00</strong>
              </span>
              <span>
                Sim Fee <strong>$0.00</strong>
              </span>
            </div>
            <button
              type="button"
              className={`lv-tp-submit${isSellish ? " sell" : ""}`}
              onClick={() => toast(`Simulated ${side} order · ${shares} AAPL`)}
            >
              Place Simulated {side} Order
            </button>
          </Panel>

          <Panel title="Watchlist">
            <ul className="lv-tp-watch">
              {WATCH.map((item) => (
                <li key={item.symbol}>
                  <strong>{item.symbol}</strong>
                  <span>{item.price}</span>
                  <Tone value={item.up}>{item.chg}</Tone>
                  <Spark points={item.spark} color={item.up ? "#34d399" : "#f87171"} width={52} height={18} />
                </li>
              ))}
            </ul>
          </Panel>
        </section>

        <section className="lv-tp-paper-bottom">
          <div style={{ display: "flex", flexDirection: "column", gap: "var(--lv-card-gap)", minWidth: 0 }}>
            <Panel title="Simulated Positions">
              <div className="lv-tp-table-wrap">
                <table className="lv-tp-table">
                  <thead>
                    <tr>
                      <th>Symbol</th>
                      <th>Side</th>
                      <th>Shares</th>
                      <th>Avg</th>
                      <th>Last</th>
                      <th>P&L</th>
                      <th>P&L%</th>
                      <th>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {POSITIONS.map((p) => (
                      <tr key={p.sym}>
                        <td className="sym">{p.sym}</td>
                        <td>
                          <span className={`lv-tp-side ${p.side.toLowerCase()}`}>{p.side}</span>
                        </td>
                        <td>{p.shares}</td>
                        <td>{p.avg}</td>
                        <td>{p.last}</td>
                        <td className="is-good">{p.pnl}</td>
                        <td className="is-good">{p.pct}</td>
                        <td>
                          <button type="button" className="lv-tp-mini" onClick={() => toast(`Close ${p.sym}`)}>
                            Close
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <Panel title="Execution Statistics">
              <div className="lv-tp-exec-grid">
                <div>
                  Profit Factor
                  <strong>1.73</strong>
                </div>
                <div>
                  Expectancy
                  <strong className="is-good">$124.66</strong>
                </div>
                <div>
                  Max Drawdown
                  <strong className="is-bad">−$1,284.32</strong>
                </div>
                <div>
                  Avg Hold
                  <strong>42m</strong>
                </div>
                <div>
                  Best Trade
                  <strong className="is-good">+$412.00</strong>
                </div>
                <div>
                  Worst Trade
                  <strong className="is-bad">−$186.40</strong>
                </div>
              </div>
            </Panel>
          </div>

          <Panel title="Orders">
            <div className="lv-tp-orders-stack">
              <div>
                <div className="lv-tp-panel-title" style={{ marginBottom: 6 }}>Open Orders</div>
                <table className="lv-tp-table">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Side</th>
                      <th>Sym</th>
                      <th>Price</th>
                      <th>Qty</th>
                      <th>Status</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {OPEN_ORDERS.map((o) => (
                      <tr key={o.time + o.sym}>
                        <td>{o.type}</td>
                        <td>{o.side}</td>
                        <td className="sym">{o.sym}</td>
                        <td>{o.px}</td>
                        <td>{o.qty}</td>
                        <td className="is-cyan">{o.status}</td>
                        <td>{o.time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div>
                <div className="lv-tp-panel-title" style={{ marginBottom: 6 }}>Filled Orders</div>
                <table className="lv-tp-table">
                  <thead>
                    <tr>
                      <th>Type</th>
                      <th>Side</th>
                      <th>Sym</th>
                      <th>Price</th>
                      <th>Qty</th>
                      <th>Status</th>
                      <th>Time</th>
                    </tr>
                  </thead>
                  <tbody>
                    {FILLED.map((o) => (
                      <tr key={o.time + o.sym}>
                        <td>{o.type}</td>
                        <td>{o.side}</td>
                        <td className="sym">{o.sym}</td>
                        <td>{o.px}</td>
                        <td>{o.qty}</td>
                        <td className="is-good">{o.status}</td>
                        <td>{o.time}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <div className="lv-tp-slip">
                <div className="lv-tp-panel-title">Slippage Analysis · Avg 0.8 bps</div>
                <div className="lv-tp-slip-bars" aria-hidden="true">
                  {SLIP.map((h, i) => (
                    <span key={i} style={{ height: `${h}%` }} />
                  ))}
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Trade Journal">
            <ul className="lv-tp-journal">
              {JOURNAL.map((j) => (
                <li key={j.t + j.sym}>
                  <div className="head">
                    <strong>
                      {j.t} · {j.sym} · {j.setup}
                    </strong>
                    <Tone value={!j.result.startsWith("−") && !j.result.startsWith("-")}>{j.result}</Tone>
                  </div>
                  {j.note}
                </li>
              ))}
            </ul>
          </Panel>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--lv-card-gap)", minWidth: 0 }}>
            <Panel title="Trading Challenge">
              <div className="lv-tp-challenge">
                <RingGauge value={72} label="36 / 50 trades" display="72%" />
                <ul className="lv-tp-challenge-list">
                  {CHALLENGE.map((c) => (
                    <li key={c.label} className={c.done ? "done" : ""}>
                      {c.label}
                    </li>
                  ))}
                </ul>
              </div>
            </Panel>

            <Panel title="Broker Status">
              <ul className="lv-tp-broker-tech">
                <li>
                  <span>Order Latency</span>
                  <strong>12 ms</strong>
                </li>
                <li>
                  <span>Data Feed</span>
                  <strong className="is-good">Live</strong>
                </li>
                <li>
                  <span>Fill Model</span>
                  <strong>Realistic</strong>
                </li>
                <li>
                  <span>Slippage Model</span>
                  <strong>On</strong>
                </li>
                <li>
                  <span>Session</span>
                  <strong>RTH</strong>
                </li>
              </ul>
              <AreaSpark points={[14, 12, 11, 13, 10, 12, 11, 9, 12, 10, 11, 12]} color="#22c9d6" width={180} height={36} />
            </Panel>
          </div>
        </section>

        <p className="lv-footer-quote">
          “Practice until discipline becomes instinct.” — LEVIATHAN
        </p>
      </main>
    </AppShell>
  );
}
