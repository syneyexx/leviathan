import { useMemo, useState } from "react";
import { media } from "../assets/media";
import { SubMenu } from "../components/SubMenu";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;
const ORDER_TYPES = ["Market", "Limit", "Stop", "OCO"] as const;
const LEVERAGE = ["1x", "2x", "5x", "10x"] as const;

const WATCHLIST = [
  { symbol: "BTC", price: "94,312.65", change: "+1.32%", up: true, spark: [40, 42, 38, 45, 48, 52, 50, 58] },
  { symbol: "ETH", price: "3,482.10", change: "+0.84%", up: true, spark: [30, 32, 35, 33, 36, 40, 38, 42] },
  { symbol: "SOL", price: "178.42", change: "-1.12%", up: false, spark: [50, 48, 46, 44, 42, 40, 38, 36] },
  { symbol: "NASDAQ", price: "21,804", change: "+0.41%", up: true, spark: [20, 22, 24, 23, 26, 28, 27, 30] },
  { symbol: "GOLD", price: "2,341.80", change: "+0.22%", up: true, spark: [25, 26, 25, 27, 28, 27, 29, 30] },
  { symbol: "EUR/USD", price: "1.0842", change: "-0.08%", up: false, spark: [40, 39, 41, 40, 38, 37, 38, 36] },
] as const;

const HEATMAP = [
  { name: "BTC", pct: "+1.3%", tone: "up" },
  { name: "ETH", pct: "+0.8%", tone: "up" },
  { name: "SOL", pct: "-1.1%", tone: "down" },
  { name: "TECH", pct: "+0.6%", tone: "up" },
  { name: "DEFI", pct: "-0.4%", tone: "down" },
  { name: "AI", pct: "+2.1%", tone: "up" },
  { name: "MEME", pct: "+4.8%", tone: "up" },
  { name: "RWA", pct: "+0.3%", tone: "up" },
] as const;

const POSITIONS = [
  { symbol: "BTC/USD", side: "LONG", size: "0.25", entry: "92,140", mark: "94,312", pnl: "+$543.12", pct: "+2.36%", liq: "76,412", stop: "90,200" },
  { symbol: "ETH/USD", side: "LONG", size: "2.40", entry: "3,390", mark: "3,482", pnl: "+$220.80", pct: "+2.71%", liq: "2,710", stop: "3,280" },
  { symbol: "SOL/USD", side: "SHORT", size: "40", entry: "182.10", mark: "178.42", pnl: "+$147.20", pct: "+2.02%", liq: "214.50", stop: "186.00" },
] as const;

const AGENTS = [
  { name: "Leviathan Core", type: "Trend", status: "Running", pnl: "+12.4%", win: "71%" },
  { name: "Night Owl Scalper", type: "Scalp", status: "Running", pnl: "+4.8%", win: "64%" },
  { name: "Macro Hedge", type: "Hedge", status: "Paused", pnl: "+1.2%", win: "58%" },
  { name: "AI Momentum", type: "ML", status: "Running", pnl: "+9.6%", win: "69%" },
] as const;

const ACTIVITY = [
  { time: "2m ago", text: "Bought 0.25 BTC/USD @ 94,280", tone: "ok" },
  { time: "11m ago", text: "Modified Stop Loss · ETH/USD → 3,280", tone: "info" },
  { time: "28m ago", text: "Leviathan Core opened SOL short", tone: "ok" },
  { time: "1h ago", text: "Risk engine rebalanced exposure", tone: "info" },
  { time: "2h ago", text: "System Health Check passed", tone: "ok" },
] as const;

function Spark({ points, color = "#34d399" }: { points: readonly number[]; color?: string }) {
  const max = Math.max(...points);
  const min = Math.min(...points);
  const path = points
    .map((v, i) => {
      const x = (i / (points.length - 1)) * 60;
      const y = 18 - ((v - min) / (max - min || 1)) * 14;
      return `${i === 0 ? "M" : "L"}${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="lv-tr-spark" viewBox="0 0 60 20" aria-hidden="true">
      <path d={path} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

function CandleChart() {
  const candles = useMemo(
    () => [
      [40, 70, 35, 55],
      [55, 80, 50, 72],
      [72, 78, 60, 64],
      [64, 90, 58, 86],
      [86, 95, 70, 74],
      [74, 88, 68, 82],
      [82, 110, 80, 104],
      [104, 120, 95, 112],
      [112, 118, 100, 108],
      [108, 130, 105, 126],
      [126, 140, 118, 134],
      [134, 145, 120, 128],
      [128, 150, 126, 146],
      [146, 160, 140, 155],
      [155, 170, 148, 166],
      [166, 175, 155, 162],
      [162, 180, 158, 176],
      [176, 190, 170, 185],
    ],
    [],
  );
  return (
    <svg className="lv-tr-chart-svg" viewBox="0 0 640 280" role="img" aria-label="BTC USD candlestick chart">
      {[0, 1, 2, 3, 4, 5].map((i) => (
        <line key={i} x1="40" x2="620" y1={20 + i * 40} y2={20 + i * 40} stroke="rgba(214,169,87,0.08)" />
      ))}
      <path d="M40,160 L100,150 L160,145 L220,130 L280,125 L340,110 L400,100 L460,95 L520,85 L580,78 L620,70" fill="none" stroke="#D6A957" strokeWidth="1.2" opacity="0.7" />
      <path d="M40,180 L100,170 L160,165 L220,155 L280,148 L340,140 L400,128 L460,120 L520,112 L580,105 L620,98" fill="none" stroke="#22C9D6" strokeWidth="1.2" opacity="0.55" />
      {candles.map((c, i) => {
        const x = 50 + i * 32;
        const [o, h, l, cl] = c;
        const up = cl >= o;
        const yOpen = 220 - o;
        const yClose = 220 - cl;
        const yHigh = 220 - h;
        const yLow = 220 - l;
        const top = Math.min(yOpen, yClose);
        const height = Math.max(2, Math.abs(yClose - yOpen));
        return (
          <g key={i}>
            <line x1={x + 5} x2={x + 5} y1={yHigh} y2={yLow} stroke={up ? "#34d399" : "#f87171"} strokeWidth="1" />
            <rect x={x} y={top} width="10" height={height} fill={up ? "#34d399" : "#f87171"} rx="1" />
            <rect x={x} y={230} width="10" height={(h - l) * 0.18} fill={up ? "rgba(52,211,153,0.35)" : "rgba(248,113,113,0.35)"} />
          </g>
        );
      })}
      <text x="28" y="28" className="lv-tr-axis">96k</text>
      <text x="28" y="108" className="lv-tr-axis">94k</text>
      <text x="28" y="188" className="lv-tr-axis">92k</text>
    </svg>
  );
}

function HealthRing({ value, label }: { value: number; label: string }) {
  const r = 22;
  const c = 2 * Math.PI * r;
  const len = (value / 100) * c;
  return (
    <div className="lv-tr-health-item">
      <svg viewBox="0 0 56 56" aria-hidden="true">
        <circle cx="28" cy="28" r={r} fill="none" stroke="rgba(52,211,153,0.15)" strokeWidth="4" />
        <circle
          cx="28"
          cy="28"
          r={r}
          fill="none"
          stroke="#34d399"
          strokeWidth="4"
          strokeDasharray={`${len} ${c - len}`}
          strokeLinecap="round"
          transform="rotate(-90 28 28)"
        />
        <text x="28" y="31" textAnchor="middle" className="lv-tr-health-val">
          {value}%
        </text>
      </svg>
      <span>{label}</span>
    </div>
  );
}

export function TradingCenterPage() {
  const toast = useAppToast();
  const [side, setSide] = useState<"BUY" | "SELL" | "CLOSE">("BUY");
  const [orderType, setOrderType] = useState<(typeof ORDER_TYPES)[number]>("Market");
  const [tf, setTf] = useState<(typeof TIMEFRAMES)[number]>("1h");
  const [leverage, setLeverage] = useState<(typeof LEVERAGE)[number]>("5x");
  const [size, setSize] = useState("1000");

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search markets, assets, strategies, or ask Leviathan..."
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tr-main">
        <section className="lv-tr-hero" aria-label="Trading Center">
          <img src={media.tradingHero} alt="" width={1400} height={220} />
        </section>

        <SubMenu />

        <section className="lv-tr-kpi-row">
          {[
            { label: "Portfolio Equity", value: "$248,703.42", delta: "+2.48%", spark: [20, 24, 22, 28, 30, 34, 38, 42] },
            { label: "Daily P&L", value: "+$6,312.18", delta: "+2.61%", spark: [10, 14, 18, 16, 22, 28, 30, 36] },
            { label: "Win Rate", value: "68.4%", delta: "+4.2%", spark: [30, 32, 34, 33, 36, 38, 40, 42] },
            { label: "Open Positions", value: "3", delta: "0.0%", spark: [20, 20, 21, 20, 20, 21, 20, 20], muted: true },
            { label: "Available Cash", value: "$92,480.37", delta: "—", spark: [25, 26, 25, 26, 25, 25, 26, 25], muted: true },
          ].map((item) => (
            <article key={item.label} className="lv-tr-kpi">
              <div className="lv-tr-kpi-label">{item.label}</div>
              <div className="lv-tr-kpi-value">{item.value}</div>
              <div className="lv-tr-kpi-foot">
                <span className={item.muted ? "" : "is-good"}>{item.delta}</span>
                <Spark points={item.spark} color={item.muted ? "#64748b" : "#34d399"} />
              </div>
            </article>
          ))}
          <article className="lv-tr-kpi">
            <div className="lv-tr-kpi-label">Risk Exposure</div>
            <div className="lv-tr-kpi-value">18.6%</div>
            <div className="lv-tr-riskbar">
              <span style={{ width: "74.4%" }} />
              <i style={{ left: "80%" }} title="Target 25%" />
            </div>
            <small>Target 25%</small>
          </article>
        </section>

        <section className="lv-tr-mid">
          <article className="lv-panel lv-tr-card lv-tr-card--chart">
            <div className="lv-tr-chart-head">
              <div>
                <strong>BTC/USD</strong>
                <span className="lv-tr-price">94,312.65</span>
                <span className="is-good">+1.32%</span>
              </div>
              <div className="lv-tr-tf">
                {TIMEFRAMES.map((item) => (
                  <button key={item} type="button" className={tf === item ? "is-active" : ""} onClick={() => setTf(item)}>
                    {item}
                  </button>
                ))}
                <button type="button" onClick={() => toast("Indicators")}>
                  Indicators
                </button>
              </div>
            </div>
            <CandleChart />
            <div className="lv-tr-ma">
              <span>
                <i style={{ background: "#D6A957" }} /> SMA 20
              </span>
              <span>
                <i style={{ background: "#22C9D6" }} /> SMA 50
              </span>
              <span>
                <i style={{ background: "#8b5cf6" }} /> SMA 200
              </span>
            </div>
          </article>

          <article className="lv-panel lv-tr-card lv-tr-order">
            <div className="lv-tr-side-tabs">
              {(["BUY", "SELL", "CLOSE"] as const).map((item) => (
                <button key={item} type="button" className={`${item.toLowerCase()}${side === item ? " is-active" : ""}`} onClick={() => setSide(item)}>
                  {item}
                </button>
              ))}
            </div>
            <div className="lv-tr-otypes">
              {ORDER_TYPES.map((item) => (
                <button key={item} type="button" className={orderType === item ? "is-active" : ""} onClick={() => setOrderType(item)}>
                  {item}
                </button>
              ))}
            </div>
            <label className="lv-tr-field">
              <span>Symbol</span>
              <select defaultValue="BTC/USD">
                <option>BTC/USD</option>
                <option>ETH/USD</option>
                <option>SOL/USD</option>
              </select>
            </label>
            <label className="lv-tr-field">
              <span>Size (USD)</span>
              <input value={size} onChange={(e) => setSize(e.target.value)} />
            </label>
            <div className="lv-tr-presets">
              {["25%", "50%", "75%", "100%"].map((p) => (
                <button key={p} type="button" onClick={() => setSize(String(Math.round(92480 * (parseInt(p, 10) / 100))))}>
                  {p}
                </button>
              ))}
            </div>
            <div className="lv-tr-lev">
              <span>Leverage</span>
              <div>
                {LEVERAGE.map((item) => (
                  <button key={item} type="button" className={leverage === item ? "is-active" : ""} onClick={() => setLeverage(item)}>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div className="lv-tr-sltp">
              <label className="lv-tr-field">
                <span>Stop Loss</span>
                <input defaultValue="92000" />
              </label>
              <label className="lv-tr-field">
                <span>Take Profit</span>
                <input defaultValue="98000" />
              </label>
            </div>
            <div className="lv-tr-est">
              <span>
                Est. Liq <strong>76,412.32</strong>
              </span>
              <span>
                Est. Fee <strong>$2.50</strong>
              </span>
            </div>
            <button type="button" className={`lv-tr-submit ${side.toLowerCase()}`} onClick={() => toast(`${side} order queued (mock)`)}>
              Place {side === "CLOSE" ? "Close" : side === "BUY" ? "Buy" : "Sell"} Order
            </button>
          </article>

          <div className="lv-tr-rightcol">
            <article className="lv-panel lv-tr-card">
              <div className="lv-section-label">Watchlist</div>
              <ul className="lv-tr-watch">
                {WATCHLIST.map((item) => (
                  <li key={item.symbol}>
                    <strong>{item.symbol}</strong>
                    <span>{item.price}</span>
                    <em className={item.up ? "is-good" : "is-bad"}>{item.change}</em>
                    <Spark points={item.spark} color={item.up ? "#34d399" : "#f87171"} />
                  </li>
                ))}
              </ul>
            </article>
            <article className="lv-panel lv-tr-card">
              <div className="lv-section-label">Market Heatmap</div>
              <div className="lv-tr-heat">
                {HEATMAP.map((item) => (
                  <div key={item.name} className={`lv-tr-heat-cell ${item.tone}`}>
                    <strong>{item.name}</strong>
                    <span>{item.pct}</span>
                  </div>
                ))}
              </div>
            </article>
          </div>
        </section>

        <section className="lv-tr-tables">
          <article className="lv-panel lv-tr-card">
            <div className="lv-section-label">Active Positions</div>
            <div className="lv-tr-table-wrap">
              <table className="lv-tr-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Side</th>
                    <th>Size</th>
                    <th>Entry</th>
                    <th>Mark</th>
                    <th>P&L</th>
                    <th>Liq / Stop</th>
                  </tr>
                </thead>
                <tbody>
                  {POSITIONS.map((p) => (
                    <tr key={p.symbol}>
                      <td>{p.symbol}</td>
                      <td>
                        <span className={`lv-tr-side ${p.side.toLowerCase()}`}>{p.side}</span>
                      </td>
                      <td>{p.size}</td>
                      <td>{p.entry}</td>
                      <td>{p.mark}</td>
                      <td className="is-good">
                        {p.pnl}
                        <small> {p.pct}</small>
                      </td>
                      <td>
                        {p.liq} / {p.stop}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </article>

          <article className="lv-panel lv-tr-card">
            <div className="lv-tr-card-head">
              <div className="lv-section-label">Trading Agents</div>
              <button type="button" className="lv-tr-mini" onClick={() => toast("Deploy strategy")}>
                + Deploy
              </button>
            </div>
            <ul className="lv-tr-agents">
              {AGENTS.map((a) => (
                <li key={a.name}>
                  <div>
                    <strong>{a.name}</strong>
                    <small>
                      {a.type} · <em className={a.status === "Running" ? "is-good" : ""}>{a.status}</em>
                    </small>
                  </div>
                  <span className="is-good">{a.pnl}</span>
                  <span>{a.win}</span>
                </li>
              ))}
            </ul>
          </article>

          <article className="lv-panel lv-tr-card">
            <div className="lv-section-label">Recent Activity</div>
            <ul className="lv-tr-activity">
              {ACTIVITY.map((item) => (
                <li key={item.time + item.text}>
                  <span className={`lv-tr-dot ${item.tone}`} />
                  <div>
                    <strong>{item.text}</strong>
                    <small>{item.time}</small>
                  </div>
                </li>
              ))}
            </ul>
          </article>
        </section>

        <section className="lv-tr-bottom">
          <article className="lv-panel lv-tr-card">
            <div className="lv-tr-card-head">
              <div className="lv-section-label">Risk Management</div>
              <button type="button" className="lv-tr-mini" onClick={() => toast("Configure risk")}>
                Configure
              </button>
            </div>
            {[
              { label: "Total Exposure", pct: 42 },
              { label: "Max Drawdown", pct: 18 },
              { label: "Value at Risk", pct: 12 },
              { label: "Daily Loss Limit", pct: 28 },
            ].map((item) => (
              <div key={item.label} className="lv-tr-riskrow">
                <div>
                  <span>{item.label}</span>
                  <strong>{item.pct}%</strong>
                </div>
                <div className="lv-tr-bar">
                  <span style={{ width: `${item.pct}%` }} />
                </div>
              </div>
            ))}
          </article>

          <article className="lv-panel lv-tr-card">
            <div className="lv-section-label">System Health</div>
            <div className="lv-tr-health">
              <HealthRing value={100} label="Data Feeds" />
              <HealthRing value={100} label="Execution" />
              <HealthRing value={99} label="AI Agents" />
              <HealthRing value={100} label="Risk Engine" />
            </div>
          </article>

          <article className="lv-panel lv-tr-card">
            <div className="lv-section-label">Quick Actions</div>
            <div className="lv-tr-actions">
              {["Run Simulation", "Paper Trade", "Deploy Strategy", "Open Backtest", "View Analytics"].map((label) => (
                <button key={label} type="button" onClick={() => toast(label)}>
                  {label}
                </button>
              ))}
            </div>
          </article>
        </section>

        <p className="lv-footer-quote">“The best trades are not found in the noise, but in the alignment of data, discipline and time.” — LEVIATHAN</p>
      </main>
    </AppShell>
  );
}
