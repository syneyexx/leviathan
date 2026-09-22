import { useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { SubMenu } from "../../components/SubMenu";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import {
  AreaSpark,
  CandleChart,
  MOCK_CANDLES,
  Panel,
  Spark,
  Tone,
  TradingHero,
} from "./shared";

const INDICES = [
  { name: "S&P 500", price: "5,248.32", change: "+18.42 (+0.35%)", up: true, spark: [40, 42, 41, 44, 46, 45, 48, 50] },
  { name: "NASDAQ", price: "16,442.10", change: "+62.18 (+0.38%)", up: true, spark: [30, 32, 34, 33, 36, 38, 40, 42] },
  { name: "DOW JONES", price: "39,128.55", change: "-42.10 (−0.11%)", up: false, spark: [50, 49, 48, 47, 46, 45, 44, 43] },
  { name: "BTC", price: "94,312.65", change: "+1,326 (+1.43%)", up: true, spark: [20, 28, 26, 35, 40, 38, 48, 55] },
  { name: "ETH", price: "3,482.10", change: "+28.40 (+0.82%)", up: true, spark: [25, 27, 30, 29, 32, 34, 36, 38] },
  { name: "GOLD", price: "2,341.80", change: "+5.20 (+0.22%)", up: true, spark: [22, 23, 22, 24, 25, 24, 26, 27] },
  { name: "WTI", price: "78.42", change: "−0.64 (−0.81%)", up: false, spark: [40, 38, 39, 36, 35, 34, 33, 32] },
  { name: "EUR/USD", price: "1.0842", change: "−0.0008 (−0.07%)", up: false, spark: [35, 34, 36, 35, 34, 33, 34, 33] },
] as const;

const TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h", "1D"] as const;
const WATCH_TABS = ["All", "Crypto", "FX", "Indices", "Futures"] as const;

const ASKS = [
  { px: "94,328.40", sz: "0.482" },
  { px: "94,324.10", sz: "0.215" },
  { px: "94,320.55", sz: "0.891" },
  { px: "94,318.20", sz: "0.340" },
  { px: "94,315.80", sz: "1.124" },
  { px: "94,314.00", sz: "0.672" },
] as const;

const BIDS = [
  { px: "94,312.65", sz: "0.958" },
  { px: "94,310.20", sz: "1.240" },
  { px: "94,306.80", sz: "0.415" },
  { px: "94,302.15", sz: "0.780" },
  { px: "94,298.40", sz: "2.105" },
  { px: "94,294.00", sz: "0.556" },
] as const;

const WATCH = [
  { symbol: "BTC/USD", price: "94,312.65", chg: "+1.43%", up: true, spark: [40, 42, 45, 44, 48, 52, 50, 58] },
  { symbol: "ETH/USD", price: "3,482.10", chg: "+0.82%", up: true, spark: [30, 32, 35, 33, 36, 40, 38, 42] },
  { symbol: "SOL/USD", price: "178.42", chg: "−1.12%", up: false, spark: [50, 48, 46, 44, 42, 40, 38, 36] },
  { symbol: "AAPL", price: "178.24", chg: "+1.09%", up: true, spark: [20, 22, 24, 23, 26, 28, 27, 30] },
  { symbol: "NVDA", price: "875.40", chg: "+2.14%", up: true, spark: [25, 28, 30, 34, 32, 38, 40, 44] },
  { symbol: "EUR/USD", price: "1.0842", chg: "−0.07%", up: false, spark: [40, 39, 41, 40, 38, 37, 38, 36] },
  { symbol: "SPY", price: "524.18", chg: "+0.35%", up: true, spark: [28, 29, 30, 31, 30, 32, 33, 34] },
  { symbol: "GOLD", price: "2,341.80", chg: "+0.22%", up: true, spark: [25, 26, 25, 27, 28, 27, 29, 30] },
] as const;

const TICKS = [
  { t: "14:27:41", sym: "BTC", px: "94,312.65", sz: "0.42", ex: "BINANCE" },
  { t: "14:27:40", sym: "ETH", px: "3,482.10", sz: "2.10", ex: "COINBASE" },
  { t: "14:27:39", sym: "AAPL", px: "178.24", sz: "120", ex: "NASDAQ" },
  { t: "14:27:38", sym: "NVDA", px: "875.40", sz: "45", ex: "NASDAQ" },
  { t: "14:27:37", sym: "BTC", px: "94,310.20", sz: "0.18", ex: "BINANCE" },
  { t: "14:27:36", sym: "SOL", px: "178.42", sz: "80", ex: "BINANCE" },
  { t: "14:27:35", sym: "SPY", px: "524.18", sz: "300", ex: "ARCA" },
  { t: "14:27:34", sym: "EUR", px: "1.0842", sz: "1.2M", ex: "FXCM" },
  { t: "14:27:33", sym: "TSLA", px: "172.80", sz: "90", ex: "NASDAQ" },
  { t: "14:27:32", sym: "BTC", px: "94,308.00", sz: "0.65", ex: "OKX" },
  { t: "14:27:31", sym: "MSFT", px: "425.60", sz: "55", ex: "NASDAQ" },
  { t: "14:27:30", sym: "GOLD", px: "2,341.80", sz: "12", ex: "COMEX" },
] as const;

const SOURCES = [
  { name: "Bloomberg B-PIPE", up: "99.98%", lat: "4.2 ms" },
  { name: "Refinitiv Elektron", up: "99.95%", lat: "5.8 ms" },
  { name: "Coinbase Pro WS", up: "99.91%", lat: "12.4 ms" },
  { name: "Binance Market", up: "99.97%", lat: "8.1 ms" },
  { name: "Polygon.io", up: "99.89%", lat: "18.6 ms" },
  { name: "ICE Consolidated", up: "99.94%", lat: "6.3 ms" },
] as const;

const EXCHANGES = [
  { name: "NYSE", lat: "3.1 ms" },
  { name: "NASDAQ", lat: "2.8 ms" },
  { name: "CME", lat: "4.4 ms" },
  { name: "BINANCE", lat: "8.1 ms" },
  { name: "COINBASE", lat: "12.4 ms" },
  { name: "CBOE", lat: "3.6 ms" },
  { name: "LSE", lat: "14.2 ms" },
  { name: "EURONEXT", lat: "15.8 ms" },
] as const;

const QUEUES = [
  { name: "Market Data", pct: 72 },
  { name: "News Feed", pct: 38 },
  { name: "Fundamentals", pct: 24 },
  { name: "Alt Data", pct: 56 },
  { name: "Corporate Actions", pct: 12 },
] as const;

const ALERTS = [
  { kind: "warn", title: "Missing ticks detected", detail: "ETH/USD · 3 gaps · last 60s" },
  { kind: "info", title: "Feed failover complete", detail: "Polygon → ICE secondary" },
  { kind: "err", title: "Checksum mismatch", detail: "CME ES · batch 4821" },
  { kind: "warn", title: "Stale quote threshold", detail: "EUR/JPY · 820 ms" },
  { kind: "info", title: "Schema migration applied", detail: "Refinitiv RIC map v4.2" },
] as const;

const CALENDAR = [
  { t: "12:30", event: "US CPI YoY", ccy: "US", impact: "high", act: "3.2%", fc: "3.1%", prev: "3.2%" },
  { t: "14:00", event: "FOMC Minutes", ccy: "US", impact: "high", act: "—", fc: "—", prev: "—" },
  { t: "08:00", event: "EU GDP QoQ", ccy: "EU", impact: "med", act: "0.3%", fc: "0.2%", prev: "0.1%" },
  { t: "09:30", event: "UK Retail Sales", ccy: "UK", impact: "med", act: "−0.4%", fc: "0.1%", prev: "0.3%" },
  { t: "01:30", event: "JP CPI Core", ccy: "JP", impact: "low", act: "2.8%", fc: "2.7%", prev: "2.6%" },
  { t: "15:45", event: "US Crude Inventories", ccy: "US", impact: "med", act: "−2.1M", fc: "−1.4M", prev: "1.8M" },
] as const;

const NEWS = [
  { t: "14:22", src: "Reuters", head: "Fed officials signal patience on next cut", sent: "bull", score: "+0.62" },
  { t: "14:18", src: "Bloomberg", head: "BTC ETF inflows hit weekly high", sent: "bull", score: "+0.81" },
  { t: "14:11", src: "WSJ", head: "Chipmakers face supply chain pressure", sent: "bear", score: "−0.44" },
  { t: "14:04", src: "CNBC", head: "Oil softens on inventory build fears", sent: "bear", score: "−0.31" },
  { t: "13:58", src: "FT", head: "Eurozone PMI holds above expansion", sent: "neut", score: "+0.08" },
  { t: "13:51", src: "CoinDesk", head: "ETH staking ratio continues climb", sent: "bull", score: "+0.55" },
] as const;

const SYMBOLS = [
  { sym: "AAPL", name: "Apple Inc.", cls: "Equity", ex: "NASDAQ" },
  { sym: "BTCUSD", name: "Bitcoin / USD", cls: "Crypto", ex: "BINANCE" },
  { sym: "ES", name: "E-mini S&P 500", cls: "Future", ex: "CME" },
  { sym: "EURUSD", name: "Euro / US Dollar", cls: "FX", ex: "FXCM" },
  { sym: "GLD", name: "SPDR Gold Shares", cls: "ETF", ex: "ARCA" },
  { sym: "NVDA", name: "NVIDIA Corp.", cls: "Equity", ex: "NASDAQ" },
] as const;

export function MarktdataPage() {
  const toast = useAppToast();
  const [tf, setTf] = useState<(typeof TIMEFRAMES)[number]>("1h");
  const [watchTab, setWatchTab] = useState<(typeof WATCH_TABS)[number]>("All");
  const [query, setQuery] = useState("");

  const symbols = SYMBOLS.filter(
    (s) =>
      !query ||
      s.sym.toLowerCase().includes(query.toLowerCase()) ||
      s.name.toLowerCase().includes(query.toLowerCase()),
  );

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search symbols, markets, data sources, or instruments..."
      systemItems={["MARKETS LIVE", "DATA STREAMING", "ALL SYSTEMS NOMINAL"]}
      layout="wide"
      pageClass="lv-app--trading"
    >
      <main className="lv-main lv-tp-main">
        <TradingHero
          title="MARKTDATA"
          kicker="INGEST. STREAM. INTERPRET."
          quote="“Information is the raw material of alpha.” — LEVIATHAN"
          image={tradingHeroes.marktdata}
          rails={["MORE SIGNALS", "DEEPER CONTEXT", "GLOBAL MARKETS", "REAL-TIME EDGE"]}
          objectPosition="center 32%"
        />

        <SubMenu />

        <section className="lv-tp-ticker" aria-label="Index tickers">
          {INDICES.map((item) => (
            <article key={item.name} className="lv-tp-tick">
              <div className="lv-tp-tick-label">{item.name}</div>
              <div className="lv-tp-tick-value">{item.price}</div>
              <div className="lv-tp-tick-foot">
                <Tone value={item.up}>{item.change}</Tone>
                <Spark points={item.spark} color={item.up ? "#34d399" : "#f87171"} />
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tp-md-mid">
          <Panel
            title="BTC/USD · Bitcoin / U.S. Dollar"
            action={
              <div className="lv-tp-tf">
                {TIMEFRAMES.map((item) => (
                  <button key={item} type="button" className={tf === item ? "is-active" : ""} onClick={() => setTf(item)}>
                    {item}
                  </button>
                ))}
                <button type="button" className="lv-tp-mini" onClick={() => toast("Indicators")}>
                  Indicators
                </button>
                <a className="lv-tp-link" href="#tv" onClick={(e) => { e.preventDefault(); toast("TradingView"); }}>
                  TradingView
                </a>
              </div>
            }
          >
            <div className="lv-tp-chart-head">
              <div>
                <span className="lv-tp-price">94,312.65</span>
                <Tone value={true}>+1,326.18 (+1.43%)</Tone>
              </div>
            </div>
            <CandleChart candles={MOCK_CANDLES} height={240} />
            <div className="lv-tp-ma">
              <span><i style={{ background: "#D6A957" }} /> SMA 20</span>
              <span><i style={{ background: "#22C9D6" }} /> SMA 50</span>
              <span><i style={{ background: "#8b5cf6" }} /> SMA 200</span>
            </div>
          </Panel>

          <Panel title="Order Book">
            <div className="lv-tp-book">
              {[...ASKS].reverse().map((row) => (
                <div key={row.px} className="lv-tp-book-row ask">
                  <span className="lv-tp-book-bar" style={{ width: `${30 + Number(row.sz) * 40}%` }} />
                  <span>{row.sz}</span>
                  <span className="px">{row.px}</span>
                  <span className="sz" />
                </div>
              ))}
              <div className="lv-tp-book-mid">
                <span>94,312.65</span>
                <Tone value={true}>Spread 1.35</Tone>
              </div>
              {BIDS.map((row) => (
                <div key={row.px} className="lv-tp-book-row bid">
                  <span className="lv-tp-book-bar" style={{ width: `${30 + Number(row.sz) * 40}%` }} />
                  <span />
                  <span className="px">{row.px}</span>
                  <span className="sz">{row.sz}</span>
                </div>
              ))}
            </div>
          </Panel>

          <Panel
            title="Watchlist"
            action={
              <div className="lv-tp-tabs">
                {WATCH_TABS.map((tab) => (
                  <button key={tab} type="button" className={`lv-tp-chip${watchTab === tab ? " is-active" : ""}`} onClick={() => setWatchTab(tab)}>
                    {tab}
                  </button>
                ))}
              </div>
            }
          >
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

          <Panel title="Live Tick Stream">
            <ul className="lv-tp-ticks">
              {TICKS.map((tick) => (
                <li key={`${tick.t}-${tick.sym}-${tick.px}`}>
                  <span>{tick.t}</span>
                  <strong>{tick.sym}</strong>
                  <span>{tick.px}</span>
                  <span>{tick.sz}</span>
                  <span className="ex">{tick.ex}</span>
                </li>
              ))}
            </ul>
          </Panel>
        </section>

        <section className="lv-tp-md-infra">
          <Panel title="Data Source Health">
            <ul className="lv-tp-src-list">
              {SOURCES.map((s) => (
                <li key={s.name}>
                  <strong>{s.name}</strong>
                  <span className="is-good">{s.up}</span>
                  <span>{s.lat}</span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Exchange Connectivity">
            <div className="lv-tp-ex-grid">
              {EXCHANGES.map((ex) => (
                <div key={ex.name} className="lv-tp-ex-card">
                  <strong>{ex.name}</strong>
                  <span className="lv-tp-status-dot">Connected</span>
                  <div>{ex.lat}</div>
                </div>
              ))}
            </div>
          </Panel>

          <Panel title="Latency & Freshness">
            <div className="lv-tp-metric-pair">
              <div className="lv-tp-metric-box">
                <div className="lbl">End-to-End Latency</div>
                <div className="val">12.4 ms</div>
                <AreaSpark points={[18, 16, 14, 15, 13, 12, 14, 11, 12, 10, 13, 12]} color="#22c9d6" width={140} height={36} />
              </div>
              <div className="lv-tp-metric-box">
                <div className="lbl">Data Freshness</div>
                <div className="val">98.7%</div>
                <AreaSpark points={[90, 92, 94, 93, 96, 97, 95, 98, 97, 99, 98, 99]} color="#34d399" width={140} height={36} />
              </div>
            </div>
            <div className="lv-tp-metric-pair" style={{ marginTop: 8 }}>
              <div className="lv-tp-metric-box">
                <div className="lbl">Throughput</div>
                <div className="val">1.42 M/s</div>
              </div>
              <div className="lv-tp-metric-box">
                <div className="lbl">Packet Loss</div>
                <div className="val is-good">0.02%</div>
              </div>
            </div>
          </Panel>

          <Panel title="Ingestion Queues">
            <ul className="lv-tp-queue-list">
              {QUEUES.map((q) => (
                <li key={q.name}>
                  <div className="row">
                    <span>{q.name}</span>
                    <strong>{q.pct}%</strong>
                  </div>
                  <div className="lv-tp-bar">
                    <span style={{ width: `${q.pct}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Data Integrity Alerts">
            <ul className="lv-tp-alert-list">
              {ALERTS.map((a) => (
                <li key={a.title}>
                  <span className={`ico ${a.kind}`} />
                  <div>
                    <strong>{a.title}</strong>
                    {a.detail}
                  </div>
                </li>
              ))}
            </ul>
          </Panel>
        </section>

        <section className="lv-tp-md-bottom">
          <Panel title="Economic Calendar">
            <div className="lv-tp-table-wrap">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Event</th>
                    <th>Ccy</th>
                    <th>Impact</th>
                    <th>Actual</th>
                    <th>Forecast</th>
                    <th>Prev</th>
                  </tr>
                </thead>
                <tbody>
                  {CALENDAR.map((row) => (
                    <tr key={`${row.t}-${row.event}`}>
                      <td>{row.t}</td>
                      <td className="sym">{row.event}</td>
                      <td>{row.ccy}</td>
                      <td>
                        <span className={`lv-tp-impact ${row.impact}`}>{row.impact}</span>
                      </td>
                      <td>{row.act}</td>
                      <td>{row.fc}</td>
                      <td>{row.prev}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="News & Sentiment">
            <div className="lv-tp-table-wrap">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Source</th>
                    <th>Headline</th>
                    <th>Sentiment</th>
                  </tr>
                </thead>
                <tbody>
                  {NEWS.map((n) => (
                    <tr key={n.t + n.head}>
                      <td>{n.t}</td>
                      <td>{n.src}</td>
                      <td className="sym">{n.head}</td>
                      <td>
                        <span className={`lv-tp-sent ${n.sent}`}>
                          {n.sent === "bull" ? "Bullish" : n.sent === "bear" ? "Bearish" : "Neutral"} {n.score}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Symbol Search">
            <div className="lv-tp-search-box">
              <input
                type="search"
                placeholder="Symbol, name, ISIN..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
              <button type="button" className="lv-tp-mini" onClick={() => toast("Filter symbols")}>
                Filter
              </button>
            </div>
            <div className="lv-tp-table-wrap">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Name</th>
                    <th>Class</th>
                    <th>Exchange</th>
                  </tr>
                </thead>
                <tbody>
                  {symbols.map((s) => (
                    <tr key={s.sym} style={{ cursor: "pointer" }} onClick={() => toast(`Open ${s.sym}`)}>
                      <td className="sym">{s.sym}</td>
                      <td>{s.name}</td>
                      <td>{s.cls}</td>
                      <td>{s.ex}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
        </section>

        <p className="lv-footer-quote">
          “Better data. Clearer markets. A more intelligent tomorrow.” — LEVIATHAN
        </p>
      </main>
    </AppShell>
  );
}
