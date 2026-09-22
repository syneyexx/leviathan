import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { CandleChart, LineSeries, MOCK_CANDLES, Panel, Spark, Tone, TradingHero } from "./shared";

const TFS = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;
const ORDER_TYPES = ["Market", "Limit", "Stop", "Stop Limit"] as const;

const BROKERS = [
  {
    name: "Apex Securities",
    markets: "Equity · Options · Futures",
    latency: "12 ms",
    value: "$248,703.42",
    power: "$186,420.19",
  },
  {
    name: "Orion Markets",
    markets: "Global Equities · FX · CFDs",
    latency: "18 ms",
    value: "$92,480.37",
    power: "$68,211.05",
  },
  {
    name: "Vertex Prime",
    markets: "Crypto · Derivatives",
    latency: "24 ms",
    value: "$54,216.90",
    power: "$40,912.33",
  },
] as const;

const OPEN_ORDERS = [
  { t: "14:21:08", sym: "AAPL", side: "BUY", type: "Limit", px: "181.50", qty: "100", status: "Open" },
  { t: "14:18:42", sym: "NVDA", side: "SELL", type: "Stop", px: "875.00", qty: "25", status: "Open" },
  { t: "14:12:17", sym: "TSLA", side: "BUY", type: "Limit", px: "168.20", qty: "50", status: "Open" },
  { t: "13:58:03", sym: "MSFT", side: "SELL", type: "Limit", px: "422.80", qty: "40", status: "Open" },
] as const;

const EXECS = [
  { t: "14:26:11", sym: "AAPL", side: "BUY", qty: "50", px: "182.28", venue: "ARCA", fee: "$0.62" },
  { t: "14:24:55", sym: "META", side: "SELL", qty: "20", px: "512.40", venue: "NSDQ", fee: "$0.48" },
  { t: "14:19:33", sym: "AMD", side: "BUY", qty: "75", px: "164.12", venue: "BATS", fee: "$0.71" },
  { t: "14:11:08", sym: "NVDA", side: "BUY", qty: "10", px: "882.15", venue: "ARCA", fee: "$0.55" },
  { t: "14:02:44", sym: "SPY", side: "SELL", qty: "30", px: "518.62", venue: "ARCA", fee: "$0.39" },
] as const;

const POSITIONS = [
  { sym: "AAPL", qty: "150", avg: "178.40", last: "182.34", pnl: "+$591.00", pct: "+2.21%" },
  { sym: "NVDA", qty: "40", avg: "860.20", last: "882.15", pnl: "+$878.00", pct: "+2.55%" },
  { sym: "TSLA", qty: "-60", avg: "175.10", last: "171.42", pnl: "+$220.80", pct: "+2.10%" },
  { sym: "MSFT", qty: "80", avg: "410.55", last: "418.90", pnl: "+$668.00", pct: "+2.03%" },
  { sym: "META", qty: "-25", avg: "520.00", last: "512.40", pnl: "+$190.00", pct: "+1.46%" },
  { sym: "AMD", qty: "120", avg: "158.30", last: "164.12", pnl: "+$698.40", pct: "+3.68%" },
  { sym: "SPY", qty: "45", avg: "512.10", last: "518.62", pnl: "+$293.40", pct: "+1.27%" },
  { sym: "QQQ", qty: "-30", avg: "448.20", last: "445.05", pnl: "+$94.50", pct: "+0.70%" },
] as const;

const ALERTS = [
  { t: "14:26", text: "Order size approaching limit · AAPL", tone: "warn" },
  { t: "14:18", text: "New day trade count: 3/10", tone: "info" },
  { t: "14:05", text: "Broker connection restored · Orion", tone: "ok" },
  { t: "13:52", text: "Margin usage crossed 40%", tone: "warn" },
  { t: "13:41", text: "Stop triggered · TSLA short cover partial", tone: "info" },
  { t: "13:20", text: "Risk engine: all limits within range", tone: "ok" },
] as const;

const LATENCY_SERIES = [12, 14, 11, 18, 22, 16, 13, 28, 15, 12, 19, 14, 11, 17, 13];

export function BrokerTradingPage() {
  const toast = useAppToast();
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<(typeof ORDER_TYPES)[number]>("Limit");
  const [tf, setTf] = useState<(typeof TFS)[number]>("15m");
  const [qty, setQty] = useState("100");
  const [tp, setTp] = useState(true);
  const [sl, setSl] = useState(true);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Broker Mode"
      searchPlaceholder="Search symbols, strategies, accounts, or commands..."
      systemItems={["MARKETS OPEN", "BROKERS CONNECTED: 3/3"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="BROKER TRADING"
          kicker="CONNECT. EXECUTE. CONTROL."
          quote="“Execution is where conviction becomes reality.” — LEVIATHAN"
          image={tradingHeroes.broker}
          rails={["MULTI BROKER / MULTI MARKET / ONE MIND", "EXECUTE / ANALYZE / ADAPT / REPEAT", "DISCIPLINE / SYSTEMS / BETTER / OUTCOMES"]}
          objectPosition="center 28%"
        />
        <section className="lv-br-top">
          <Panel
            title="Connected Brokers · 3/3 Online"
            action={
              <button type="button" className="lv-tp-btn lv-tp-btn--gold" onClick={() => toast("Add Broker")}>
                + Add Broker
              </button>
            }
          >
            <div className="lv-br-brokers">
              {BROKERS.map((b) => (
                <article key={b.name} className="lv-br-broker">
                  <strong>{b.name}</strong>
                  <div className="meta">{b.markets}</div>
                  <div style={{ marginTop: 6 }}>
                    <span className="lv-tp-pill is-live">Connected · {b.latency}</span>
                  </div>
                  <div className="stats">
                    <div>
                      <span className="lv-tp-muted">Account Value</span>
                      <strong>{b.value}</strong>
                    </div>
                    <div>
                      <span className="lv-tp-muted">Buying Power</span>
                      <strong>{b.power}</strong>
                    </div>
                  </div>
                </article>
              ))}
            </div>
          </Panel>

          <div className="lv-br-kpis">
            <article className="lv-br-kpi">
              <div className="lbl">Total Account Value</div>
              <div className="val">$395,400.69</div>
              <div className="sub is-good">+2.68% · +$10,308.41</div>
            </article>
            <article className="lv-br-kpi">
              <div className="lbl">Total P&amp;L (Today)</div>
              <div className="val is-good">+$7,312.26</div>
              <div className="sub" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span className="is-good">+1.88%</span>
                <Spark points={[12, 14, 18, 16, 22, 28, 30, 36]} />
              </div>
            </article>
            <article className="lv-br-kpi">
              <div className="lbl">Open Positions</div>
              <div className="val">12</div>
              <div className="sub lv-tp-muted">6 Long · 6 Short</div>
            </article>
            <article className="lv-br-kpi">
              <div className="lbl">Margin Usage</div>
              <div className="val">42.6%</div>
              <div className="lv-tp-bar" style={{ marginTop: 6 }}>
                <span style={{ width: "42.6%" }} />
              </div>
              <div className="sub lv-tp-muted">$168,432 / $395,401</div>
            </article>
            <article className="lv-br-kpi" style={{ gridColumn: "1 / -1" }}>
              <div className="lbl">Risk Limits</div>
              <div className="val" style={{ fontSize: 14 }}>
                <span className="lv-tp-pill is-live">OK — All limits within range</span>
              </div>
            </article>
          </div>
        </section>

        <section className="lv-br-mid">
          <Panel
            title="AAPL · Apple Inc. · NASDAQ"
            action={
              <div className="lv-tp-tabs">
                {TFS.map((t) => (
                  <button key={t} type="button" className={`lv-tp-chip${tf === t ? " is-active" : ""}`} onClick={() => setTf(t)}>
                    {t}
                  </button>
                ))}
                <button type="button" className="lv-tp-chip" onClick={() => toast("Indicators")}>
                  Indicators
                </button>
                <button type="button" className="lv-tp-chip" onClick={() => toast("Draw")}>
                  Draw
                </button>
              </div>
            }
          >
            <div style={{ display: "flex", gap: 10, alignItems: "baseline", marginBottom: 6 }}>
              <strong style={{ color: "var(--lv-text-bright)", fontSize: 18 }}>182.34</strong>
              <Tone value={1}>+2.18 · +1.21%</Tone>
            </div>
            <CandleChart
              candles={MOCK_CANDLES}
              height={240}
              markers={[
                { index: 4, side: "B" },
                { index: 9, side: "S" },
                { index: 14, side: "B" },
                { index: 19, side: "S" },
              ]}
            />
          </Panel>

          <Panel title="Order Ticket">
            <div className="lv-br-ticket-sides">
              <button type="button" className={`buy${side === "BUY" ? " is-active" : ""}`} onClick={() => setSide("BUY")}>
                BUY
              </button>
              <button type="button" className={`sell${side === "SELL" ? " is-active" : ""}`} onClick={() => setSide("SELL")}>
                SELL
              </button>
            </div>
            <div className="lv-tp-tabs" style={{ margin: "8px 0" }}>
              {ORDER_TYPES.map((t) => (
                <button key={t} type="button" className={`lv-tp-chip${orderType === t ? " is-active" : ""}`} onClick={() => setOrderType(t)}>
                  {t}
                </button>
              ))}
            </div>
            <div className="lv-br-ticket-fields">
              <div className="lv-tp-field">
                <label htmlFor="br-sym">Symbol</label>
                <input id="br-sym" className="lv-tp-input" defaultValue="AAPL" />
              </div>
              <div className="lv-tp-field">
                <label htmlFor="br-qty">Quantity</label>
                <input id="br-qty" className="lv-tp-input" value={qty} onChange={(e) => setQty(e.target.value)} />
              </div>
              <div className="lv-tp-field">
                <label htmlFor="br-route">Order Route</label>
                <select id="br-route" className="lv-tp-select" defaultValue="Auto">
                  <option>Auto</option>
                  <option>ARCA</option>
                  <option>NSDQ</option>
                  <option>BATS</option>
                </select>
              </div>
              <div className="lv-tp-field">
                <label htmlFor="br-tif">Time in Force</label>
                <select id="br-tif" className="lv-tp-select" defaultValue="Day">
                  <option>Day</option>
                  <option>GTC</option>
                  <option>IOC</option>
                </select>
              </div>
            </div>
            <div className="lv-br-checks" style={{ marginTop: 8 }}>
              <label>
                <input type="checkbox" checked={tp} onChange={(e) => setTp(e.target.checked)} />
                Take Profit · 185.00 · +1.46%
              </label>
              <label>
                <input type="checkbox" checked={sl} onChange={(e) => setSl(e.target.checked)} />
                Stop Loss · 179.50 · -1.56%
              </label>
            </div>
            <div className="lv-br-est" style={{ marginTop: 10 }}>
              <span>Est. Cost $18,234.00</span>
              <span>Est. Fees $1.25</span>
            </div>
            <button
              type="button"
              className={`lv-tp-btn lv-tp-btn--fill ${side === "BUY" ? "lv-tp-btn--buy" : "lv-tp-btn--sell"}`}
              style={{ marginTop: 10 }}
              onClick={() => toast(`${side} order placed`)}
            >
              Place {side === "BUY" ? "Buy" : "Sell"} Order
            </button>
          </Panel>

          <div className="lv-br-stack">
            <Panel
              title="Open Orders (4)"
              action={
                <button type="button" className="lv-tp-btn" onClick={() => toast("Cancel all")}>
                  Cancel All
                </button>
              }
            >
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Sym</th>
                    <th>Side</th>
                    <th>Type</th>
                    <th>Price</th>
                    <th>Qty</th>
                  </tr>
                </thead>
                <tbody>
                  {OPEN_ORDERS.map((o) => (
                    <tr key={o.t + o.sym}>
                      <td>{o.t}</td>
                      <td>{o.sym}</td>
                      <td className={o.side === "BUY" ? "is-good" : "is-bad"}>{o.side}</td>
                      <td>{o.type}</td>
                      <td>{o.px}</td>
                      <td>{o.qty}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <Panel title="Executions (Live)">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Sym</th>
                    <th>Side</th>
                    <th>Qty</th>
                    <th>Price</th>
                    <th>Venue</th>
                    <th>Fees</th>
                  </tr>
                </thead>
                <tbody>
                  {EXECS.map((e) => (
                    <tr key={e.t + e.sym}>
                      <td>{e.t}</td>
                      <td>{e.sym}</td>
                      <td className={e.side === "BUY" ? "is-good" : "is-bad"}>{e.side}</td>
                      <td>{e.qty}</td>
                      <td>{e.px}</td>
                      <td>{e.venue}</td>
                      <td>{e.fee}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
          </div>
        </section>

        <section className="lv-br-bottom">
          <Panel title="Live Positions (12)">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>Qty</th>
                  <th>Avg</th>
                  <th>Last</th>
                  <th>P&amp;L</th>
                  <th>P&amp;L %</th>
                </tr>
              </thead>
              <tbody>
                {POSITIONS.map((p) => (
                  <tr key={p.sym}>
                    <td>{p.sym}</td>
                    <td className={p.qty.startsWith("-") ? "is-bad" : ""}>{p.qty}</td>
                    <td>{p.avg}</td>
                    <td>{p.last}</td>
                    <td className="is-good">{p.pnl}</td>
                    <td className="is-good">{p.pct}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Margin &amp; Risk">
            <div className="lv-tp-muted">Margin Usage</div>
            <div className="lv-tp-bar" style={{ margin: "4px 0 10px" }}>
              <span style={{ width: "42.6%" }} />
            </div>
            <div className="lv-tp-muted">Day Trade Limit</div>
            <div className="lv-tp-bar is-warn" style={{ margin: "4px 0 10px" }}>
              <span style={{ width: "18%" }} />
            </div>
            <div className="lv-tp-muted" style={{ marginBottom: 6 }}>
              $36,421 / $200,000
            </div>
            {[
              "Position Size",
              "Daily Loss",
              "Concentration",
              "Leverage Cap",
              "Order Rate",
            ].map((item) => (
              <div key={item} className="lv-br-limit-row">
                <span>{item}</span>
                <span className="ok">OK</span>
              </div>
            ))}
            <div className="lv-br-limit-row" style={{ marginTop: 8 }}>
              <span>Portfolio Beta</span>
              <strong>0.82</strong>
            </div>
            <div className="lv-br-limit-row">
              <span>VaR (1D)</span>
              <strong>2.4%</strong>
            </div>
          </Panel>

          <Panel title="Broker Health">
            {BROKERS.map((b) => (
              <div key={b.name} className="lv-br-health-row">
                <span>{b.name.split(" ")[0]}</span>
                <strong>{b.latency}</strong>
                <span className="lv-tp-muted">99.99%</span>
              </div>
            ))}
            <div className="lv-tp-muted" style={{ margin: "8px 0 4px" }}>
              Execution Latency (ms)
            </div>
            <LineSeries series={[{ values: LATENCY_SERIES, color: "#22c9d6" }]} height={80} />
          </Panel>

          <Panel title="Compliance &amp; Alerts">
            {ALERTS.map((a) => (
              <div key={a.t + a.text} className="lv-br-alert">
                <time>{a.t}</time>
                <div>
                  <span className={`lv-tp-pill${a.tone === "ok" ? " is-live" : a.tone === "warn" ? " is-warn" : " is-info"}`}>
                    {a.tone}
                  </span>
                  <div style={{ marginTop: 4 }}>{a.text}</div>
                </div>
              </div>
            ))}
          </Panel>
        </section>
      </main>
    </AppShell>
  );
}
