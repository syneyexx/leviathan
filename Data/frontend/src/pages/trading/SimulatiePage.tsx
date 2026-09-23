import { useMemo, useState, type CSSProperties, type ReactNode } from "react";
import { media } from "../../assets/media";
import { AppShell } from "../../layouts/AppShell";
import "../../styles/trading-simulation-reference.css";

const candles = [
  58840, 58420, 57920, 57480, 57020, 57580, 58040, 57640, 58210, 58660, 59020, 59680,
  59240, 58880, 59510, 60020, 60380, 59830, 60470, 60810, 60260, 59880, 59410, 60040,
  60510, 61280, 61840, 62310, 61760, 62240, 62680, 62010, 61520, 61280, 61860, 62440,
  62120, 62740, 63320, 64020, 63520, 63060, 62640, 63120, 63780, 63220, 62860, 62540,
  63140, 63620, 64080, 63740, 63320, 62940, 63480, 63840, 64120, 63720, 63440, 63260,
  63640, 64040, 64580, 64920, 64260, 63840, 63420, 63920, 64380, 64740, 65020, 64680,
  64140, 63820, 64260, 64580, 64320, 63920, 64140, 64620, 65040, 65420, 65720,
];

const kpis = [
  ["agents", "5", "Active Agents"],
  ["capital", "$100,000", "Simulated Capital"],
  ["positions", "3", "Open Positions"],
  ["win", "68.4%", "Win Rate"],
  ["data", "Binance (API)", "Market Data Source"],
  ["time", "2024-01-01", "Simulation Time"],
  ["sync", "2 minutes ago", "Last Sync"],
] as const;

const positions = [
  { symbol: "BTC/USDT", side: "LONG", qty: "0.25", entry: "62,301", pnl: "+1,842", pct: "+2.96%" },
  { symbol: "ETH/USDT", side: "LONG", qty: "2.4", entry: "2,412", pnl: "+513", pct: "+1.76%" },
  { symbol: "SOL/USDT", side: "SHORT", qty: "12", entry: "143.2", pnl: "-208", pct: "-2.18%" },
];

const imports = [
  ["BTCUSDT_1h_2020_2024", "Completed", "2.4M", "Sep 17, 14:12"],
  ["ETHUSDT_1h_2020_2024", "Completed", "1.8M", "Sep 17, 13:55"],
  ["SOLUSDT_1h_2021_2024", "Processing", "892K", "Sep 17, 14:20"],
  ["Market_Data_Multi_Asset", "Queued", "—", "Sep 17, 14:26"],
] as const;

const agents = [
  ["Strategy Agent", "Strategy Development", "Active", "Analyzing pattern", "78%", "+8.4%", "strategy"],
  ["Risk Agent", "Risk Management", "Active", "Monitoring exposure", "96%", "-0.2%", "risk"],
  ["Execution Agent", "Order Execution", "Active", "Placing order", "89%", "+2.1%", "exec"],
  ["Macro Agent", "Market Analysis", "Active", "Scanning news", "72%", "+1.3%", "macro"],
  ["Learning Agent", "Strategy Evolution", "Training", "Updating model", "65%", "+1.2%", "learn"],
] as const;

const thoughts = [
  ["14:27", "Market Analysis", "BTC is approaching a key resistance level at 64,000. Volume is increasing, indicating a potential breakout.", "analysis"],
  ["14:27", "Pattern Detected", "Bullish flag pattern detected on 1h timeframe. Confidence: 78%", "pattern"],
  ["14:26", "Hypothesis", "If BTC breaks 64,000 with volume > 1.5x, probability of reaching 66,500 is 62% based on historical data.", "hypothesis"],
  ["14:26", "Planned Action", "Consider scaling into long position if confirmed breakout. Set stop loss at 62,800.", "action"],
  ["14:25", "Risk Assessment", "Current position size is within risk limits. Drawdown risk: Low.", "risk"],
] as const;

const logs = [
  ["14:27:36", "EXECUTION", "Placed limit buy order for ETH/USDT at 2,418.5 (qty: 0.8)"],
  ["14:27:33", "RISK", "Position size validated. Portfolio risk: 2.3% (limit: 5.0%)"],
  ["14:27:28", "STRATEGY", "Strategy Agent detected bullish flag pattern on BTC (confidence: 78%)"],
  ["14:27:21", "LEARNING", "Updated model weights. Reward: +0.32. Exploration rate: 0.28"],
  ["14:27:15", "MARKET", "New 1h candle closed: O:63,421 H:63,890 L:63,112 C:63,762 (+0.54%)"],
  ["14:27:03", "MACRO", "Analyzing news: Fed rate cut expectations increasing (sentiment: bullish)"],
] as const;

function Icon({ type }: { type: string }) {
  const common = { fill: "none", stroke: "currentColor", strokeWidth: 1.7, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };
  if (type === "agents") return <svg viewBox="0 0 24 24" {...common}><circle cx="9" cy="8" r="3"/><path d="M3.5 19c.6-3.2 2.4-5 5.5-5s4.9 1.8 5.5 5"/><circle cx="17.5" cy="9" r="2.2"/><path d="M15.5 14.5c2.9-.7 4.6.8 5 3.5"/></svg>;
  if (type === "capital" || type === "data") return <svg viewBox="0 0 24 24" {...common}><ellipse cx="12" cy="5" rx="7" ry="3"/><path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6"/></svg>;
  if (type === "positions") return <svg viewBox="0 0 24 24" {...common}><path d="M4 19V9M10 19V5M16 19v-7M3 18l5-5 4 2 7-8"/><path d="M16 7h3v3"/></svg>;
  if (type === "win") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><path d="m12 12 6-6"/></svg>;
  if (type === "time") return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>;
  if (type === "sync") return <svg viewBox="0 0 24 24" {...common}><path d="M20 8a8 8 0 0 0-13.5-2L4 8"/><path d="M4 4v4h4M4 16a8 8 0 0 0 13.5 2L20 16"/><path d="M20 20v-4h-4"/></svg>;
  return <svg viewBox="0 0 24 24" {...common}><circle cx="12" cy="12" r="8"/></svg>;
}

function Panel({ title, children, className = "", action }: { title: string; children: ReactNode; className?: string; action?: ReactNode }) {
  return <section className={`ts-panel ${className}`}><header className="ts-panel-head"><span>{title}</span>{action}</header><div className="ts-panel-body">{children}</div></section>;
}

function MockChart() {
  const chart = useMemo(() => {
    const min = 56000;
    const max = 66500;
    const w = 1000;
    const h = 282;
    const step = w / candles.length;
    const bars = candles.map((close, i) => {
      const open = i === 0 ? close + 300 : candles[i - 1];
      const swing = 260 + ((i * 73) % 330);
      const high = Math.min(max, Math.max(open, close) + swing);
      const low = Math.max(min, Math.min(open, close) - swing * 0.72);
      const y = (v: number) => ((max - v) / (max - min)) * h;
      return { x: i * step + step / 2, openY: y(open), closeY: y(close), highY: y(high), lowY: y(low), up: close >= open, width: Math.max(4.2, step * .58) };
    });
    const eq = candles.map((_, i) => 58700 + i * 82 + Math.sin(i * .42) * 560 + Math.cos(i * .17) * 210);
    const yEq = (v: number) => ((max - v) / (max - min)) * h;
    const eqPath = eq.map((v, i) => `${i === 0 ? "M" : "L"}${(i * step + step / 2).toFixed(2)},${yEq(v).toFixed(2)}`).join(" ");
    return { bars, eqPath };
  }, []);

  const signals = [
    { i: 18, label: "BUY", tone: "buy" }, { i: 36, label: "BUY", tone: "buy" },
    { i: 39, label: "SELL", tone: "sell" }, { i: 58, label: "BUY", tone: "buy" },
    { i: 66, label: "SELL", tone: "sell" }, { i: 64, label: "BUY", tone: "buy" },
  ];

  return <div className="ts-chart-wrap">
    <svg className="ts-price-svg" viewBox="0 0 1000 370" preserveAspectRatio="none" aria-label="BTC USDT simulated candlestick chart">
      <defs>
        <linearGradient id="eqGlow" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#20b8ff" stopOpacity=".95"/><stop offset="1" stopColor="#20b8ff" stopOpacity=".12"/></linearGradient>
      </defs>
      {Array.from({ length: 7 }).map((_, i) => <line key={`h${i}`} x1="0" y1={i * 47} x2="1000" y2={i * 47} className="ts-grid-line" />)}
      {Array.from({ length: 10 }).map((_, i) => <line key={`v${i}`} x1={i * 111} y1="0" x2={i * 111} y2="282" className="ts-grid-line" />)}
      <path d={chart.eqPath} className="ts-equity-line" />
      {chart.bars.map((b, i) => <g key={i} className={b.up ? "ts-candle up" : "ts-candle down"}>
        <line x1={b.x} y1={b.highY} x2={b.x} y2={b.lowY}/>
        <rect x={b.x - b.width / 2} y={Math.min(b.openY, b.closeY)} width={b.width} height={Math.max(2.5, Math.abs(b.closeY - b.openY))}/>
      </g>)}
      {signals.map((s) => {
        const b = chart.bars[s.i];
        const y = s.tone === "buy" ? Math.min(270, b.lowY + 28) : Math.max(18, b.highY - 28);
        return <g key={`${s.i}${s.label}`} className={`ts-signal ${s.tone}`} transform={`translate(${b.x} ${y})`}>
          <path d={s.tone === "buy" ? "M0 -9 L7 3 L-7 3 Z" : "M0 9 L7 -3 L-7 -3 Z"}/>
          <text x="0" y={s.tone === "buy" ? 17 : -10}>{s.label}</text>
        </g>;
      })}
      {Array.from({ length: 84 }).map((_, i) => {
        const v = 5 + ((i * 19) % 33);
        return <rect key={`vol${i}`} x={i * 11.9 + 1} y={315 - v} width="7.5" height={v} className={candles[i % candles.length] >= candles[Math.max(0, (i - 1) % candles.length)] ? "ts-volume up" : "ts-volume down"}/>;
      })}
      <line x1="0" y1="329" x2="1000" y2="329" className="ts-rsi-divider"/>
      <path d="M0 351 C55 342 90 362 128 348 S205 338 242 350 S320 362 356 346 S425 334 474 349 S553 359 598 346 S666 339 704 351 S774 361 820 344 S900 355 1000 339" className="ts-rsi-line"/>
    </svg>
    <div className="ts-price-axis"><span>66,000</span><span>64,000</span><span className="current">63,762.8</span><span>62,000</span><span>60,000</span><span>58,000</span><span>56,000</span></div>
    <div className="ts-time-axis"><span>Sep 10</span><span>12:00</span><span>Sep 11</span><span>12:00</span><span>Sep 12</span><span>12:00</span><span>Sep 13</span><span>Sep 14</span><span>Sep 15</span><span>Sep 16</span><span>Sep 17</span><span>12:00</span></div>
  </div>;
}

function MiniEquity() {
  return <svg className="ts-mini-equity" viewBox="0 0 240 80" preserveAspectRatio="none"><defs><linearGradient id="miniFill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#00e5b0" stopOpacity=".35"/><stop offset="1" stopColor="#00e5b0" stopOpacity="0"/></linearGradient></defs><path d="M0 68 L13 61 L26 64 L40 53 L53 55 L66 47 L80 51 L93 41 L106 43 L120 34 L133 37 L146 31 L160 35 L173 23 L186 26 L200 17 L213 21 L226 12 L240 5 L240 80 L0 80 Z" fill="url(#miniFill)"/><path d="M0 68 L13 61 L26 64 L40 53 L53 55 L66 47 L80 51 L93 41 L106 43 L120 34 L133 37 L146 31 L160 35 L173 23 L186 26 L200 17 L213 21 L226 12 L240 5" fill="none" stroke="#00e5b0" strokeWidth="2"/></svg>;
}

export function SimulatiePage() {
  const [running, setRunning] = useState(false);
  const [speed, setSpeed] = useState("1x");
  const [scenario, setScenario] = useState("Standard");
  const [learningTab, setLearningTab] = useState("Performance");
  const [consoleTab, setConsoleTab] = useState("All (127)");

  return <AppShell
    activeMode="explore"
    modeLabel="Simulation Mode"
    searchPlaceholder="Search markets, assets, strategies..."
    systemItems={["MARKET SIM ON", running ? "RUNNING" : "READY", "5 AGENTS"]}
    layout="wide"
    pageClass="lv-app--trading lv-app--trading-sim-ref"
  >
    <main className="lv-main ts-main">
      <section className="ts-hero">
        <img src={media.architectureBg} alt="" />
        <div className="ts-hero-overlay" />
        <div className="ts-hero-copy">
          <h1>TRADINGCENTER SIMULATION</h1>
          <div className="ts-hero-kicker">AI-POWERED TRADING SIMULATION &amp; STRATEGY EVOLUTION</div>
          <p>“Simulate. Learn. Adapt. Outperform.”</p>
        </div>
        <div className="ts-hero-kpis">
          {kpis.map(([icon, value, label]) => <div className="ts-kpi" key={label}><span className="ts-kpi-icon"><Icon type={icon}/></span><div><strong>{value}</strong><span>{label}</span></div></div>)}
        </div>
      </section>

      <section className="ts-controls">
        <button className={`ts-run-btn ${running ? "is-running" : ""}`} onClick={() => setRunning((v) => !v)}><span>▶</span>{running ? "Simulation Running" : "Start Simulation"}</button>
        <button onClick={() => setRunning(false)}>Ⅱ <span>Pause</span></button>
        <button>▶ <span>Step</span></button>
        <button>↶ <span>Reset</span></button>
        <div className="ts-control-divider" />
        <label>Speed:</label>
        <div className="ts-speed-row">{["0.25x", "0.5x", "1x", "2x", "5x"].map((v) => <button key={v} className={speed === v ? "is-active" : ""} onClick={() => setSpeed(v)}>{v}</button>)}</div>
        <div className="ts-control-divider" />
        <label>Market:</label><select defaultValue="BTC/USDT"><option>BTC/USDT</option><option>ETH/USDT</option></select>
        <label>Timeframe:</label><select defaultValue="1h"><option>1h</option><option>15m</option><option>4h</option></select>
        <label>Scenario:</label><select value={scenario} onChange={(e) => setScenario(e.target.value)}><option>Standard</option><option>Bull Market</option><option>Bear Market</option><option>High Volatility</option></select>
        <button className="ts-icon-btn">⚙</button><button className="ts-save-btn">▣ <span>Save Run</span></button>
      </section>

      <section className="ts-top-grid">
        <Panel title="PRICE CHART & SIMULATION" className="ts-chart-panel">
          <div className="ts-chart-toolbar"><strong>BTC/USDT</strong><span>1h</span><span className="ohlc">O <b>63,421.2</b></span><span className="ohlc">H <b>63,890.1</b></span><span className="ohlc">L <b>63,112.4</b></span><span className="ohlc">C <b>63,762.8</b></span><span className="gain">+341.6 (+0.54%)</span><span className="ts-chart-spacer"/><span className="dot ai"/>AI Actions <span className="diamond"/>Buy Signal <span className="tri"/>Sell Signal <button className="ts-toggle">Equity <i/></button><button>Indicators⌄</button><button>↗</button><button>⚙</button></div>
          <MockChart />
          <div className="ts-chart-footer"><div className="ts-range">{["1D", "5D", "1M", "3M", "6M", "1Y", "All"].map((x) => <button key={x}>{x}</button>)}</div><div className="ts-scrub"><i style={{ width: "42%" }}/></div><span>14:27:36 (UTC+2)</span><span>%</span><span>log</span><span className="auto">auto</span></div>
        </Panel>

        <Panel title="PORTFOLIO & RISK" className="ts-portfolio">
          <div className="ts-portfolio-top"><div><span>Total Equity</span><strong>$112,846</strong><b>+12.85%</b></div><div><span>Unrealized PnL</span><strong>$2,347</strong><b>+2.12%</b></div></div>
          <div className="ts-stat-strip"><div><span>Cash</span><b>$87,421</b></div><div><span>Positions</span><b>$25,425</b></div><div><span>Total Return</span><b className="good">+12.85%</b></div></div>
          <div className="ts-stat-strip"><div><span>Max Drawdown</span><b className="bad">-4.21%</b></div><div><span>Sharpe Ratio</span><b>1.42</b></div><div><span>Sortino Ratio</span><b>1.87</b></div></div>
          <div className="ts-mini-tabs"><button className="active">Equity Curve</button><button>Drawdown</button><button>Daily PnL</button></div><MiniEquity />
        </Panel>

        <div className="ts-right-stack">
          <Panel title="POSITIONS (3)" action={<button className="ts-viewall">View All</button>} className="ts-positions">
            <table><thead><tr><th>SYMBOL</th><th>SIDE</th><th>QTY</th><th>ENTRY</th><th>PnL</th><th>PnL%</th></tr></thead><tbody>{positions.map((p) => <tr key={p.symbol}><td>{p.symbol}</td><td><span className={`side ${p.side.toLowerCase()}`}>{p.side}</span></td><td>{p.qty}</td><td>{p.entry}</td><td className={p.pnl.startsWith("+") ? "good" : "bad"}>{p.pnl}</td><td className={p.pct.startsWith("+") ? "good" : "bad"}>{p.pct}</td></tr>)}</tbody></table>
          </Panel>
          <Panel title="MARKET SNAPSHOT — BTC/USDT" className="ts-market">
            <div className="ts-market-price"><strong>63,762.8</strong><b>+341.6 (+0.54%)</b></div>
            <div className="ts-market-meta"><div><span>24h High</span><b>64,231.1</b><span>24h Low</span><b>61,983.4</b></div><div><span>24h Volume (BTC)</span><b>28,421.3</b><span>24h Volume (USDT)</span><b>1.81B</b></div></div>
            <div className="ts-book"><div><h4>Bids <span>Size</span></h4>{[["63,762.7","1.214"],["63,762.6","0.842"],["63,762.5","2.113"],["63,762.4","4.621"],["63,762.3","3.998"]].map(([p,s],i)=><div key={p} className="bid" style={{"--w":`${25+i*14}%`} as CSSProperties}><span>{p}</span><b>{s}</b></div>)}</div><div><h4>Asks <span>Size</span></h4>{[["63,762.8","1.521"],["63,762.9","2.341"],["63,763.0","1.887"],["63,763.1","3.114"],["63,763.2","4.002"]].map(([p,s],i)=><div key={p} className="ask" style={{"--w":`${30+i*12}%`} as CSSProperties}><span>{p}</span><b>{s}</b></div>)}</div></div>
          </Panel>
        </div>
      </section>

      <section className="ts-mid-grid">
        <Panel title="DATA INGESTION" className="ts-ingestion">
          <div className="ts-upload-row"><label className="ts-upload">⇧ Upload Market Data<input type="file" hidden /></label><div className="ts-drop">▧ <span>Drag &amp; drop market data files here<small>CSV, Parquet, or JSON</small></span></div></div>
          <h4>Recent Imports</h4><div className="ts-list-head"><span>DATASET</span><span>STATUS</span><span>ROWS</span><span>DATE</span></div>{imports.map((r) => <div className="ts-import-row" key={r[0]}><span>{r[0]}</span><span className={r[1]==="Completed"?"good":r[1]==="Processing"?"warn":"muted"}>{r[1]==="Completed"?"● ":r[1]==="Processing"?"◉ ":"○ "}{r[1]}</span><span>{r[2]}</span><span>{r[3]}</span>{r[1]==="Processing"?<i className="ts-progress"/>:null}</div>)}
        </Panel>

        <Panel title="AGENT ROSTER (5)" action={<button className="ts-viewall">Manage Agents</button>} className="ts-agents">
          <div className="ts-agent-head"><span>AGENT</span><span>ROLE</span><span>STATUS</span><span>ACTION</span><span>CONF</span><span>PnL</span></div>{agents.map((a) => <div className="ts-agent-row" key={a[0]}><span className={`agent-icon ${a[6]}`}>◉</span><span><b>{a[0]}</b></span><span>{a[1]}</span><span className={a[2]==="Active"?"good":"warn"}>● {a[2]}</span><span>{a[3]}</span><span>{a[4]}</span><span className={String(a[5]).startsWith("+")?"good":"bad"}>{a[5]}</span></div>)}
        </Panel>

        <Panel title="AGENT THINKING — Strategy Agent" action={<select defaultValue="Strategy Agent"><option>Strategy Agent</option><option>Risk Agent</option></select>} className="ts-thinking">
          <div className="ts-thoughts">{thoughts.map((t) => <div className="ts-thought" key={`${t[0]}${t[1]}`}><time>{t[0]}</time><span className={`thought-icon ${t[3]}`}>◉</span><div><b>{t[1]}</b><p>{t[2]}</p></div></div>)}</div>
        </Panel>

        <Panel title="STRATEGY LEARNING" className="ts-learning">
          <div className="ts-learning-tabs">{["Performance","Evolution","Patterns","Rewards"].map((x)=><button key={x} className={learningTab===x?"active":""} onClick={()=>setLearningTab(x)}>{x}</button>)}</div>
          <div className="ts-current-strategy"><span>Current Strategy</span><b>Multi-Asset Momentum v2.3</b><em>◆ Training</em></div>
          <div className="ts-learning-metrics">{[["Cumulative Return","+12.85%","good"],["Win Rate","68.4%",""],["Total Trades","47",""],["Avg Win","+2.34%","good"],["Avg Loss","-1.21%","bad"],["Profit Factor","2.14","good"]].map(([l,v,c])=><div key={l}><span>{l}</span><b className={c}>{v}</b></div>)}</div>
          <div className="ts-explore"><span>Exploration</span><b>28%</b><i><u style={{width:"28%"}}/></i><span>Exploitation</span><b>72%</b><i className="gold"><u style={{width:"72%"}}/></i></div>
          <h4>Recent Discoveries</h4><ul className="ts-discoveries"><li><time>14:12</time>Detected bullish momentum pattern (BTC, 1h)</li><li><time>13:47</time>Correlation opportunity: ETH/SOL divergence</li><li><time>12:33</time>Improved entry timing using volume profile</li><li><time>11:22</time>Risk adjustment reduced drawdown by 18%</li></ul>
        </Panel>
      </section>

      <section className="ts-bottom-grid">
        <Panel title="SIMULATION EVENTS CONSOLE" className="ts-console">
          <div className="ts-console-tabs">{["All (127)","Orders (24)","Risk (12)","Strategy (38)","Learning (21)","System (32)"].map((x)=><button key={x} className={consoleTab===x?"active":""} onClick={()=>setConsoleTab(x)}>{x}</button>)}</div>
          <div className="ts-log">{logs.map((l)=><div key={`${l[0]}${l[1]}`}><time>{l[0]}</time><b className={`log-${l[1].toLowerCase()}`}>[{l[1]}]</b><span>{l[2]}</span></div>)}</div>
        </Panel>

        <Panel title="SCENARIO PRESETS" className="ts-scenarios">
          <div className="ts-scenario-grid">{[["Standard","Realistic market conditions","Most common"],["Bull Market","Upward trending market","Optimistic scenario"],["Bear Market","Downward trending market","Stress test"],["High Volatility","Increased market volatility","Risk testing"]].map((s)=><button key={s[0]} className={scenario===s[0]?"active":""} onClick={()=>setScenario(s[0])}><span className="scenario-orb">◉</span><b>{s[0]}</b><small>{s[1]}</small><em>{s[2]}</em></button>)}</div><button className="ts-custom">+ Create Custom Scenario</button>
        </Panel>

        <Panel title="BENCHMARK COMPARISON" action={<button className="ts-viewall">Configure</button>} className="ts-benchmark">
          <div className="ts-bench-head"><span>ASSET</span><span>LEVIATHAN</span><span>BUY &amp; HOLD</span><span>outperformance</span></div>{[["BTC/USDT","+12.85%","+6.21%","+6.64%","72%"],["ETH/USDT","+8.41%","+4.12%","+4.29%","58%"],["SOL/USDT","+5.23%","+2.11%","+3.12%","43%"],["TOTAL","+9.62%","+4.15%","+5.47%","86%"]].map((r)=><div className="ts-bench-row" key={r[0]}><span>{r[0]}</span><b className="good">{r[1]}</b><span>{r[2]}</span><b className="good">{r[3]}</b><i><u style={{width:r[4]}}/></i></div>)}
        </Panel>
      </section>
    </main>
  </AppShell>;
}
