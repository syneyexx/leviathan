import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { CandleChart, LineSeries, MOCK_CANDLES, Panel, Tone, TradingHero } from "./shared";

const PERIODS = ["3M", "6M", "1Y", "3Y", "5Y", "ALL"] as const;
const SPEEDS = ["0.1x", "0.5x", "1x", "2x", "5x", "10x"] as const;
const TFS = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;

const ASKS = [
  { price: "24,528.40", size: "0.84", total: "2.41" },
  { price: "24,526.10", size: "1.20", total: "1.57" },
  { price: "24,524.75", size: "0.36", total: "0.37" },
] as const;

const BIDS = [
  { price: "24,521.90", size: "1.12", total: "1.12" },
  { price: "24,519.40", size: "0.68", total: "1.80" },
  { price: "24,517.05", size: "2.04", total: "3.84" },
  { price: "24,514.80", size: "0.91", total: "4.75" },
] as const;

const FILLS = [
  { t: "10:42:17", side: "BUY", px: "24,521.90", sz: "0.25" },
  { t: "10:41:58", side: "SELL", px: "24,518.20", sz: "0.40" },
  { t: "10:41:22", side: "BUY", px: "24,509.10", sz: "0.18" },
  { t: "10:40:47", side: "BUY", px: "24,501.55", sz: "0.55" },
  { t: "10:40:11", side: "SELL", px: "24,496.80", sz: "0.30" },
  { t: "10:39:36", side: "BUY", px: "24,488.40", sz: "0.22" },
  { t: "10:39:02", side: "SELL", px: "24,482.15", sz: "0.48" },
  { t: "10:38:29", side: "BUY", px: "24,475.60", sz: "0.15" },
] as const;

const EVENTS = [
  { t: "Mar 14 10:00", event: "FOMC Rate Decision", impact: "High", asset: "BTC", desc: "Fed holds rates; hawkish guidance" },
  { t: "Mar 10 08:30", event: "CPI Inflation Data", impact: "High", asset: "BTC", desc: "YoY CPI 5.0% vs 5.2% exp" },
  { t: "Feb 28 14:00", event: "Exchange Outage", impact: "Medium", asset: "BTC", desc: "Major venue API degraded 42m" },
  { t: "Feb 12 09:15", event: "ETF Flow Spike", impact: "Medium", asset: "BTC", desc: "Net inflows +$412M session" },
  { t: "Jan 24 16:00", event: "Options Expiry", impact: "High", asset: "BTC", desc: "$1.8B notional weekly expiry" },
] as const;

const WORKERS = [
  { id: "sim-01", strategy: "Quantum Trend", progress: 78, uptime: "04:12:08" },
  { id: "sim-02", strategy: "Mean Reversion Pro", progress: 64, uptime: "03:48:21" },
  { id: "sim-03", strategy: "Vol Harvest", progress: 41, uptime: "02:19:55" },
  { id: "sim-04", strategy: "Event Alpha", progress: 92, uptime: "05:02:14" },
] as const;

const EQUITY = [100, 102, 101, 105, 108, 107, 112, 116, 114, 119, 122, 121, 125];
const DRAWDOWN = [0, -2, -1, -4, -3, -6, -5, -8, -7, -10, -9, -12, -3];

export function SimulatiePage() {
  const toast = useAppToast();
  const [period, setPeriod] = useState<(typeof PERIODS)[number]>("1Y");
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>("1x");
  const [tf, setTf] = useState<(typeof TFS)[number]>("1h");
  const [playing, setPlaying] = useState(true);

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Simulation Mode"
      searchPlaceholder="Search markets, assets, strategies, or run simulations..."
      systemItems={["MARKETS LIVE", "SIMULATION MODE"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="MARKT SIMULATIE"
          kicker="REPLAY. ANALYZE. ADAPT."
          quote="“The markets always speak. Simulation lets you listen more carefully.” — LEVIATHAN"
          image={tradingHeroes.simulatie}
          objectPosition="center 32%"
        />

        <SubMenu />

        <section className="lv-sim-config" aria-label="Simulation configuration">
          <article className="lv-sim-config-card">
            <div className="lbl">Scenario</div>
            <strong>BTC Bull Run 2023</strong>
            <p>Full-cycle replay with real market data</p>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Asset / Market</div>
            <strong>BTC/USD</strong>
            <p>Bitcoin / US Dollar</p>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Historical Period</div>
            <strong>Jan 01, 2023 — Dec 31, 2023</strong>
            <div className="lv-sim-periods">
              {PERIODS.map((p) => (
                <button key={p} type="button" className={`lv-tp-chip${period === p ? " is-active" : ""}`} onClick={() => setPeriod(p)}>
                  {p}
                </button>
              ))}
            </div>
          </article>
          <article className="lv-sim-config-card">
            <div className="lbl">Simulation Configuration</div>
            <strong>Standard Execution</strong>
            <p>Realistic Slippage · Fees · Latency</p>
            <button type="button" className="lv-tp-btn lv-tp-btn--accent" style={{ marginTop: 8 }} onClick={() => toast("Configure simulation")}>
              Configure
            </button>
          </article>
        </section>

        <section className="lv-sim-playback" aria-label="Playback controls">
          <div className="lv-sim-controls">
            {["⏹", "⏮", playing ? "⏸" : "▶", "⏭", "⏭⏭"].map((icon, i) => (
              <button
                key={icon + i}
                type="button"
                className={i === 2 && playing ? "is-active" : ""}
                onClick={() => {
                  if (i === 2) setPlaying((v) => !v);
                  else toast("Playback");
                }}
                aria-label={["Stop", "Rewind", "Play/Pause", "Fast forward", "Skip end"][i]}
              >
                {icon}
              </button>
            ))}
          </div>
          <div className="lv-sim-speeds">
            {SPEEDS.map((s) => (
              <button key={s} type="button" className={`lv-tp-chip${speed === s ? " is-active" : ""}`} onClick={() => setSpeed(s)}>
                {s}
              </button>
            ))}
          </div>
          <div className="lv-sim-timeline">
            <div className="lv-sim-timeline-meta">
              <span>Mar 14, 2023 10:42:17</span>
              <span className="lv-tp-muted">Day 73 / 365 · 42%</span>
            </div>
            <div className="lv-sim-seek" role="slider" aria-valuenow={42} aria-valuemin={0} aria-valuemax={100}>
              <span />
              <i style={{ left: "18%" }} />
              <i style={{ left: "34%" }} />
              <i style={{ left: "61%" }} />
              <i style={{ left: "79%" }} />
            </div>
          </div>
          <button type="button" className="lv-tp-btn lv-tp-btn--gold" onClick={() => toast("Go to Live")}>
            Go to Live
          </button>
        </section>

        <section className="lv-sim-chart-grid">
          <Panel
            title="BTC/USD · Replay Chart"
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
                <button type="button" className="lv-tp-chip" onClick={() => toast("Events")}>
                  Events
                </button>
              </div>
            }
          >
            <div className="lv-sim-chart-head">
              <div>
                <strong>BTC/USD</strong>
                <span className="lv-tp-mono">24,521.90 </span>
                <Tone value={0.86}>+0.86%</Tone>
              </div>
              <div className="lv-tp-muted">SMA 20 · 50 · 200</div>
            </div>
            <CandleChart candles={MOCK_CANDLES} height={240} />
          </Panel>

          <Panel title="Order Book (Replay)">
            <div className="lv-sim-ob">
              <div className="lv-sim-ob-row lv-tp-muted">
                <span>Price</span>
                <span>Size</span>
                <span>Total</span>
              </div>
              {ASKS.map((r) => (
                <div key={r.price} className="lv-sim-ob-row is-ask">
                  <span>{r.price}</span>
                  <span>{r.size}</span>
                  <span>{r.total}</span>
                </div>
              ))}
              <div className="lv-sim-ob-row" style={{ color: "var(--lv-gold-bright)", fontWeight: 650, padding: "6px 0" }}>
                <span>24,521.90</span>
                <span>Spread</span>
                <span>2.85</span>
              </div>
              {BIDS.map((r) => (
                <div key={r.price} className="lv-sim-ob-row is-bid">
                  <span>{r.price}</span>
                  <span>{r.size}</span>
                  <span>{r.total}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Simulated Fills (Tape)">
            <div className="lv-sim-tape">
              {FILLS.map((f) => (
                <div key={f.t + f.side} className="lv-sim-tape-row">
                  <span className="lv-tp-muted">{f.t}</span>
                  <span className={f.side === "BUY" ? "is-good" : "is-bad"}>{f.side}</span>
                  <span>{f.px}</span>
                  <span>{f.sz}</span>
                </div>
              ))}
            </div>
          </Panel>
        </section>

        <section className="lv-sim-stats">
          <Panel title="Simulated Portfolio Value">
            <div style={{ fontSize: 28, fontWeight: 700, color: "var(--lv-text-bright)" }}>$124,832.47</div>
            <Tone value={24.83}>+24.83%</Tone>
            <div className="lv-sim-metric-grid" style={{ marginTop: 10 }}>
              <div>
                <span>Initial Capital</span>
                <strong>$100,000</strong>
              </div>
              <div>
                <span>Unrealized P&amp;L</span>
                <strong className="is-good">+$4,218</strong>
              </div>
              <div>
                <span>Realized P&amp;L</span>
                <strong className="is-good">+$20,614</strong>
              </div>
              <div>
                <span>Cash</span>
                <strong>$38,420</strong>
              </div>
            </div>
          </Panel>

          <Panel title="Strategy Performance">
            <div className="lv-sim-metric-grid">
              {[
                ["Total Return", "+24.83%", true],
                ["Sharpe Ratio", "1.42", true],
                ["Win Rate", "67.3%", true],
                ["Profit Factor", "2.31", true],
                ["Total Trades", "428", null],
                ["Avg Hold", "18h 24m", null],
                ["Best Trade", "+$2,840", true],
                ["Worst Trade", "-$1,120", false],
              ].map(([k, v, up]) => (
                <div key={String(k)}>
                  <span>{k}</span>
                  <strong className={up === true ? "is-good" : up === false ? "is-bad" : ""}>{v}</strong>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Equity Curve">
            <LineSeries series={[{ values: EQUITY, color: "#22c9d6" }]} height={120} />
            <div className="lv-tp-muted" style={{ marginTop: 4 }}>
              Strategy equity vs initial capital
            </div>
          </Panel>

          <Panel title="Drawdown Analysis">
            <LineSeries series={[{ values: DRAWDOWN, color: "#f87171" }]} height={90} />
            <div className="lv-sim-metric-grid" style={{ marginTop: 8 }}>
              <div>
                <span>Max Drawdown</span>
                <strong className="is-bad">-12.47%</strong>
              </div>
              <div>
                <span>Current DD</span>
                <strong className="is-bad">-3.21%</strong>
              </div>
              <div>
                <span>Recovery Time</span>
                <strong>18 days</strong>
              </div>
              <div>
                <span>Underwater</span>
                <strong>11%</strong>
              </div>
            </div>
          </Panel>
        </section>

        <section className="lv-sim-bottom">
          <Panel title="Scenario Events">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Time</th>
                  <th>Event</th>
                  <th>Impact</th>
                  <th>Asset</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {EVENTS.map((e) => (
                  <tr key={e.t}>
                    <td>{e.t}</td>
                    <td>{e.event}</td>
                    <td>
                      <span className={`lv-tp-pill${e.impact === "High" ? " is-bad" : " is-warn"}`}>{e.impact}</span>
                    </td>
                    <td>{e.asset}</td>
                    <td>{e.desc}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel title="Active Simulation Workers">
            {WORKERS.map((w) => (
              <div key={w.id} className="lv-sim-worker">
                <strong>{w.id}</strong>
                <div>
                  <div>{w.strategy}</div>
                  <div className="lv-tp-bar" style={{ marginTop: 4 }}>
                    <span style={{ width: `${w.progress}%` }} />
                  </div>
                </div>
                <div style={{ textAlign: "right" }}>
                  <span className="lv-tp-pill is-live">Running</span>
                  <div className="lv-tp-muted">{w.uptime}</div>
                </div>
              </div>
            ))}
          </Panel>

          <Panel title="Simulation Summary" className="lv-sim-summary">
            <dl>
              <dt>Initial Capital</dt>
              <dd>$100,000</dd>
              <dt>Position Sizing</dt>
              <dd>2% risk / trade</dd>
              <dt>Trading Fees</dt>
              <dd>0.10%</dd>
              <dt>Slippage Model</dt>
              <dd>Realistic</dd>
              <dt>Execution Latency</dt>
              <dd>50–250ms</dd>
              <dt>Data Source</dt>
              <dd>Historical L2</dd>
              <dt>Fill Model</dt>
              <dd>Queue priority</dd>
              <dt>Benchmark</dt>
              <dd>BTC buy &amp; hold</dd>
            </dl>
          </Panel>
        </section>

        <footer className="lv-sim-foot">
          <span>Same markets. A sharper you. — LEVIATHAN</span>
          <span className="lv-tp-pill is-live">Simulation Running</span>
        </footer>
      </main>
    </AppShell>
  );
}
