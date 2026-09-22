import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import { LineSeries, Panel, Spark, Tone, TradingHero } from "./shared";

const LIB_TABS = ["Strategy Library", "Favorites", "My Strategies", "Templates", "Community", "Sentiment", "AI Generated"] as const;
const BUILDER_TABS = ["Visual Builder", "Code View", "Backtest", "Live Deploy"] as const;
const PARAM_TABS = ["Parameters", "Optimization", "Walk-Forward", "Monte Carlo"] as const;
const BT_TABS = ["1M", "6M", "1Y", "3Y", "ALL"] as const;

const CATEGORIES = [
  { name: "Trend Following", desc: "Momentum across timeframes", tag: "TREND", count: 12 },
  { name: "Mean Reversion", desc: "Statistical pullbacks", tag: "MEAN REVERSION", count: 8 },
  { name: "Statistical Arbitrage", desc: "Pairs & residual alpha", tag: "STAT ARB", count: 6 },
  { name: "Machine Learning", desc: "AI-driven alpha", tag: "ML", count: 9 },
  { name: "Volatility Trading", desc: "IV crush & expansion", tag: "VOL", count: 5 },
  { name: "Event Driven", desc: "Catalysts & flows", tag: "EVENT", count: 4 },
] as const;

const TOP_STRATS = [
  { rank: 1, name: "Quantum Trend", type: "Trend", ret: "+42.8%", sharpe: "2.14", dd: "-9.2%", win: "71%", status: "LIVE" },
  { rank: 2, name: "Mean Reversion Pro", type: "Mean Rev", ret: "+31.4%", sharpe: "1.86", dd: "-11.1%", win: "64%", status: "LIVE" },
  { rank: 3, name: "Vol Harvest XL", type: "Vol", ret: "+28.6%", sharpe: "1.72", dd: "-14.8%", win: "58%", status: "PAPER" },
  { rank: 4, name: "Neural Momentum", type: "ML", ret: "+36.1%", sharpe: "1.95", dd: "-12.4%", win: "67%", status: "LIVE" },
  { rank: 5, name: "Event Alpha", type: "Event", ret: "+22.3%", sharpe: "1.41", dd: "-8.6%", win: "62%", status: "PAPER" },
  { rank: 6, name: "Pairs Nexus", type: "Stat Arb", ret: "+19.8%", sharpe: "1.58", dd: "-6.4%", win: "69%", status: "LIVE" },
] as const;

const EXPERIMENTS = [
  { date: "Apr 21", strategy: "Quantum Trend", changes: "EMA 12→10", result: "+1.8%", sharpe: "2.18", status: "Completed" },
  { date: "Apr 20", strategy: "Neural Momentum", changes: "RSI filter on", result: "+0.9%", sharpe: "1.99", status: "Completed" },
  { date: "Apr 19", strategy: "Vol Harvest XL", changes: "ATR stop 2.0", result: "-0.4%", sharpe: "1.68", status: "Completed" },
  { date: "Apr 18", strategy: "Mean Reversion Pro", changes: "Window 48h", result: "+2.1%", sharpe: "1.91", status: "Completed" },
  { date: "Apr 17", strategy: "Pairs Nexus", changes: "z-score 2.2", result: "+0.6%", sharpe: "1.61", status: "Completed" },
] as const;

const FACTORS = [
  { name: "Momentum", value: 68, pos: true },
  { name: "Value", value: 22, pos: true },
  { name: "Volatility", value: 41, pos: false },
  { name: "Liquidity", value: 55, pos: true },
  { name: "Carry", value: 18, pos: false },
  { name: "Quality", value: 34, pos: true },
] as const;

const DEPLOYS = [
  { name: "Quantum Trend", env: "Live · Binance", when: "Apr 12", status: "RUNNING" },
  { name: "Neural Momentum", env: "Live · Apex", when: "Apr 08", status: "RUNNING" },
  { name: "Mean Reversion Pro", env: "Paper · Internal", when: "Apr 18", status: "RUNNING" },
  { name: "Pairs Nexus", env: "Live · Orion", when: "Mar 29", status: "RUNNING" },
] as const;

const EQUITY_STRAT = [100, 104, 103, 110, 118, 116, 124, 132, 128, 140, 148, 145, 158];
const EQUITY_BH = [100, 102, 98, 105, 108, 104, 112, 115, 110, 118, 122, 119, 128];

const PARAMS = [
  { label: "Fast MA Period", value: 12, min: 5, max: 50 },
  { label: "Slow MA Period", value: 48, min: 20, max: 200 },
  { label: "RSI Length", value: 14, min: 5, max: 30 },
  { label: "RSI Overbought", value: 72, min: 55, max: 90 },
  { label: "RSI Oversold", value: 28, min: 10, max: 45 },
  { label: "Stop Loss (ATR)", value: 2.0, min: 0.5, max: 5, step: 0.1 },
  { label: "Take Profit (ATR)", value: 3.5, min: 1, max: 8, step: 0.1 },
  { label: "Position Size %", value: 2.5, min: 0.5, max: 10, step: 0.1 },
] as const;

export function StrategieenPage() {
  const toast = useAppToast();
  const [libTab, setLibTab] = useState<(typeof LIB_TABS)[number]>("Strategy Library");
  const [builderTab, setBuilderTab] = useState<(typeof BUILDER_TABS)[number]>("Visual Builder");
  const [paramTab, setParamTab] = useState<(typeof PARAM_TABS)[number]>("Parameters");
  const [btTab, setBtTab] = useState<(typeof BT_TABS)[number]>("ALL");
  const [activeCat, setActiveCat] = useState("Trend Following");
  const [params, setParams] = useState<Record<string, number>>(() =>
    Object.fromEntries(PARAMS.map((p) => [p.label, p.value])),
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Strategies Mode"
      searchPlaceholder="Search strategies, assets, indicators, models..."
      systemItems={["MARKETS LIVE", "SYSTEMS OPERATIONAL"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="TRADING STRATEGIEËN"
          kicker="DESIGN. TEST. DEPLOY."
          quote="“Systematic discipline turns ideas into an edge.” — LEVIATHAN"
          image={tradingHeroes.strategieen}
          rails={["IDEAS", "MODELS", "BACKTESTS", "OPTIMIZATION", "DEPLOYMENT", "ALPHA"]}
          objectPosition="center 30%"
        />

        <SubMenu />

        <section className="lv-st-kpi-row">
          {[
            { label: "Total Strategies", value: "48", foot: "+6 this month", spark: [20, 24, 28, 30, 34, 38, 42, 48], good: true },
            { label: "Active Strategies", value: "12", foot: "4 live · 8 paper", spark: [10, 12, 11, 13, 12, 14, 13, 12], good: true },
            { label: "Avg. Annual Return", value: "+24.3%", foot: "+6.1% vs benchmark", spark: [18, 20, 22, 21, 24, 26, 25, 28], good: true },
            { label: "Sharpe Ratio (Avg)", value: "1.42", foot: "+0.28 vs previous", spark: [1, 1.1, 1.2, 1.15, 1.3, 1.35, 1.4, 1.42], good: true },
            { label: "Max Drawdown (Avg)", value: "-11.8%", foot: "-2.1% vs previous", spark: [8, 9, 10, 11, 10, 12, 11, 12], good: false },
            { label: "Profit Factor (Avg)", value: "1.87", foot: "+0.32 vs previous", spark: [1.4, 1.5, 1.55, 1.6, 1.7, 1.75, 1.8, 1.87], good: true },
          ].map((k) => (
            <article key={k.label} className="lv-st-kpi">
              <div className="lbl">{k.label}</div>
              <div className="val">{k.value}</div>
              <div className="foot">
                <span className={k.good ? "is-good" : "is-bad"}>{k.foot}</span>
                <Spark points={k.spark} color={k.good ? "#34d399" : "#f87171"} />
              </div>
            </article>
          ))}
        </section>

        <section className="lv-st-mid">
          <Panel title="Strategy Library">
            <div className="lv-st-lib-tabs">
              {LIB_TABS.map((t) => (
                <button key={t} type="button" className={`lv-tp-chip${libTab === t ? " is-active" : ""}`} onClick={() => setLibTab(t)}>
                  {t}
                </button>
              ))}
            </div>
            <div className="lv-st-lib-tools">
              <input className="lv-tp-input" type="search" placeholder="Search strategies..." />
              <select className="lv-tp-select" defaultValue="All Types">
                <option>All Types</option>
                <option>Trend</option>
                <option>Mean Rev</option>
                <option>ML</option>
              </select>
              <select className="lv-tp-select" defaultValue="All Markets">
                <option>All Markets</option>
                <option>Crypto</option>
                <option>Equities</option>
                <option>FX</option>
              </select>
            </div>
            <div className="lv-st-cat-grid">
              {CATEGORIES.map((c) => (
                <button
                  key={c.name}
                  type="button"
                  className={`lv-st-cat${activeCat === c.name ? " is-active" : ""}`}
                  onClick={() => setActiveCat(c.name)}
                >
                  <strong>{c.name}</strong>
                  <span>{c.desc}</span>
                  <em>
                    {c.tag} · {c.count} strategies
                  </em>
                </button>
              ))}
            </div>
          </Panel>

          <Panel
            title="Strategy Builder"
            action={
              <button type="button" className="lv-tp-btn lv-tp-btn--accent" onClick={() => toast("Strategy saved")}>
                Save Strategy
              </button>
            }
          >
            <div className="lv-tp-tabs" style={{ marginBottom: 8 }}>
              {BUILDER_TABS.map((t) => (
                <button key={t} type="button" className={`lv-tp-chip${builderTab === t ? " is-active" : ""}`} onClick={() => setBuilderTab(t)}>
                  {t}
                </button>
              ))}
            </div>
            <div className="lv-st-builder-canvas">
              <div className="lv-st-toolbar">
                {["+", "◇", "▣", "⚙"].map((icon) => (
                  <button key={icon} type="button" onClick={() => toast("Node tool")} aria-label="Builder tool">
                    {icon}
                  </button>
                ))}
              </div>
              <div className="lv-st-nodes">
                <div className="lv-st-node">
                  Market Data
                  <small>BTC/USD</small>
                </div>
                <div className="lv-st-edge" />
                <div className="lv-st-node">
                  Indicators
                  <small>EMA · RSI · ATR</small>
                </div>
                <div className="lv-st-edge" />
                <div className="lv-st-node">
                  Entry Logic
                  <small>EMA Cross + RSI Filter</small>
                </div>
                <div className="lv-st-edge" />
                <div className="lv-st-fork">
                  <div className="lv-st-node is-risk">
                    Risk Management
                    <small>ATR stops · size</small>
                  </div>
                  <div className="lv-st-node is-exec">
                    Execution
                    <small>Limit · IOC</small>
                  </div>
                </div>
                <div className="lv-st-edge" />
                <div className="lv-st-node">
                  Exit Logic
                  <small>TP / SL / Time</small>
                </div>
              </div>
            </div>
          </Panel>

          <Panel title="Parameter Tuning">
            <div className="lv-tp-tabs" style={{ marginBottom: 8 }}>
              {PARAM_TABS.map((t) => (
                <button key={t} type="button" className={`lv-tp-chip${paramTab === t ? " is-active" : ""}`} onClick={() => setParamTab(t)}>
                  {t}
                </button>
              ))}
            </div>
            <div className="lv-st-params">
              {PARAMS.map((p) => (
                <div key={p.label} className="lv-st-param">
                  <label htmlFor={`param-${p.label}`}>{p.label}</label>
                  <strong>{params[p.label]}</strong>
                  <input
                    id={`param-${p.label}`}
                    className="lv-tp-slider"
                    type="range"
                    min={p.min}
                    max={p.max}
                    step={"step" in p ? p.step : 1}
                    value={params[p.label]}
                    onChange={(e) => setParams((prev) => ({ ...prev, [p.label]: Number(e.target.value) }))}
                  />
                </div>
              ))}
            </div>
            <button type="button" className="lv-tp-btn lv-tp-btn--accent lv-tp-btn--fill" style={{ marginTop: 8 }} onClick={() => toast("Optimization started")}>
              Optimize
            </button>
          </Panel>
        </section>

        <section className="lv-st-bottom">
          <Panel title="Top Strategies">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Strategy</th>
                  <th>Type</th>
                  <th>Return</th>
                  <th>Sharpe</th>
                  <th>Max DD</th>
                  <th>Win</th>
                  <th>Status</th>
                </tr>
              </thead>
              <tbody>
                {TOP_STRATS.map((s) => (
                  <tr key={s.name}>
                    <td>{s.rank}</td>
                    <td>{s.name}</td>
                    <td>{s.type}</td>
                    <td>
                      <Tone value={1}>{s.ret}</Tone>
                    </td>
                    <td>{s.sharpe}</td>
                    <td className="is-bad">{s.dd}</td>
                    <td>{s.win}</td>
                    <td>
                      <span className={`lv-tp-pill${s.status === "LIVE" ? " is-live" : " is-paper"}`}>{s.status}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <Panel
            title="Backtest Summary · BTC/USD · 2021–2024 · 1D"
            action={
              <div className="lv-tp-tabs">
                {BT_TABS.map((t) => (
                  <button key={t} type="button" className={`lv-tp-chip${btTab === t ? " is-active" : ""}`} onClick={() => setBtTab(t)}>
                    {t}
                  </button>
                ))}
              </div>
            }
          >
            <div className="lv-st-bt-metrics">
              {[
                ["Total Return", "+58.4%"],
                ["CAGR", "+18.2%"],
                ["Sharpe", "1.74"],
                ["Max DD", "-14.6%"],
              ].map(([k, v]) => (
                <div key={k}>
                  <span>{k}</span>
                  <strong className={String(v).startsWith("-") ? "is-bad" : "is-good"}>{v}</strong>
                </div>
              ))}
            </div>
            <LineSeries
              series={[
                { values: EQUITY_STRAT, color: "#22c9d6" },
                { values: EQUITY_BH, color: "#f87171" },
              ]}
              height={120}
            />
            <div className="lv-tp-muted" style={{ marginTop: 4 }}>
              Strategy (cyan) vs Buy &amp; Hold (red)
            </div>
            <div className="lv-st-risk-side">
              <span>Volatility</span>
              <strong>16.4%</strong>
              <span>Sortino</span>
              <strong>2.08</strong>
              <span>VaR 95%</span>
              <strong>-2.1%</strong>
              <span>Calmar</span>
              <strong>1.25</strong>
            </div>
          </Panel>

          <Panel title="Recent Experiments">
            <table className="lv-tp-table">
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Strategy</th>
                  <th>Changes</th>
                  <th>Result</th>
                  <th>Sharpe</th>
                </tr>
              </thead>
              <tbody>
                {EXPERIMENTS.map((e) => (
                  <tr key={e.date + e.strategy}>
                    <td>{e.date}</td>
                    <td>{e.strategy}</td>
                    <td>{e.changes}</td>
                    <td>
                      <Tone value={e.result.startsWith("+") ? 1 : -1}>{e.result}</Tone>
                    </td>
                    <td>{e.sharpe}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Panel>

          <div style={{ display: "flex", flexDirection: "column", gap: "var(--lv-card-gap)" }}>
            <Panel title="Factor Exposure">
              {FACTORS.map((f) => (
                <div key={f.name} className="lv-st-factor">
                  <span>{f.name}</span>
                  <div className="lv-st-factor-bar">
                    <span className={f.pos ? "is-pos" : "is-neg"} style={{ width: `${f.value}%` }} />
                  </div>
                  <strong className={f.pos ? "is-good" : "is-bad"}>
                    {f.pos ? "+" : "-"}
                    {f.value}%
                  </strong>
                </div>
              ))}
            </Panel>
            <Panel title="Deployment Status">
              {DEPLOYS.map((d) => (
                <div key={d.name} className="lv-st-deploy-row">
                  <div>
                    <strong style={{ color: "var(--lv-text-bright)" }}>{d.name}</strong>
                    <div className="lv-tp-muted">
                      {d.env} · {d.when}
                    </div>
                  </div>
                  <span className="lv-tp-pill is-live">{d.status}</span>
                </div>
              ))}
            </Panel>
          </div>
        </section>
      </main>
    </AppShell>
  );
}
