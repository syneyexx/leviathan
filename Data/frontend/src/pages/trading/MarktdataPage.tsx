import { useCallback, useEffect, useState } from "react";
import { tradingHeroes } from "../../assets/tradingAssets";
import { ApiError, api } from "../../api/client";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type { MarketDataSource, MarketSimStatusResponse } from "../../types/api";
import { Panel, TradingHero, hashShort } from "./shared";
import { InstitutionalStrip } from "./InstitutionalStrip";

export function MarktdataPage() {
  const toast = useAppToast();
  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [path, setPath] = useState("BTCUSDT_1h.csv");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const st = await api.marketSimStatus();
      setStatus(st);
      if (st.enabled) {
        const { sources: list } = await api.listMarketData();
        setSources(list);
      } else {
        setSources([]);
      }
      setError(st.enabled ? null : "Market sim is OFF (LEVIATHAN_FEATURE_MARKET_SIM). Default is ON for local/dev.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to load market data");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function scan() {
    setBusy(true);
    try {
      const { sources: list } = await api.scanMarketData();
      setSources(list);
      toast(`Indexed ${list.length} file(s)`);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Scan failed");
    } finally {
      setBusy(false);
    }
  }

  async function register() {
    setBusy(true);
    try {
      const { source } = await api.registerMarketData({ path });
      toast(`${source.symbol} · ${source.status}`);
      await refresh();
    } catch (err) {
      toast(err instanceof ApiError ? err.message : "Register failed");
    } finally {
      setBusy(false);
    }
  }

  const filtered = sources.filter(
    (s) =>
      !query ||
      s.symbol.toLowerCase().includes(query.toLowerCase()) ||
      s.path.toLowerCase().includes(query.toLowerCase()),
  );
  const ready = sources.filter((s) => s.status === "READY").length;
  const invalid = sources.filter((s) => s.status === "INVALID").length;
  const qualityFail = sources.filter((s) => {
    const q = (s.metadata as { qualityVerdict?: string } | undefined)?.qualityVerdict;
    return q === "FAIL";
  }).length;
  const qualityWarn = sources.filter((s) => {
    const q = (s.metadata as { qualityVerdict?: string } | undefined)?.qualityVerdict;
    return q === "WARN";
  }).length;

  function qualityOf(s: MarketDataSource): string {
    const meta = s.metadata as { qualityVerdict?: string; quality?: { qualityVerdict?: string } } | undefined;
    return meta?.qualityVerdict || meta?.quality?.qualityVerdict || "UNMEASURED";
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Trading Mode"
      searchPlaceholder="Search symbols, markets, data sources, or instruments..."
      systemItems={[
        status?.enabled ? "MARKET SIM ON" : "MARKET SIM OFF",
        `${ready} READY`,
        status?.health.exists ? "ROOT EXISTS" : "ROOT MISSING",
      ]}
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
        <InstitutionalStrip />
        {error ? (
          <Panel title="Market data">
            <p>{error}</p>
          </Panel>
        ) : null}

        <section className="lv-tp-ticker" aria-label="Market data health">
          {[
            { name: "Markets root", price: status?.health.markets_root ?? "—", change: status?.health.exists ? "exists" : "missing", up: !!status?.health.exists },
            { name: "Indexed", price: String(status?.health.sources_indexed ?? sources.length), change: "filesystem + hash", up: true },
            { name: "Ready", price: String(status?.health.sources_ready ?? ready), change: "validated OHLCV", up: ready > 0 },
            { name: "Invalid", price: String(invalid), change: "failed validation", up: invalid === 0 },
            { name: "Quality FAIL", price: String(qualityFail), change: "OHLC / order / neg", up: qualityFail === 0 },
            { name: "Quality WARN", price: String(qualityWarn), change: "gaps / outliers", up: true },
            { name: "Feature", price: status?.enabled ? "ON" : "OFF", change: "LEVIATHAN_FEATURE_MARKET_SIM", up: !!status?.enabled },
            { name: "Parquet", price: "optional", change: "pyarrow if installed", up: true },
          ].map((item) => (
            <article key={item.name} className="lv-tp-tick">
              <div className="lv-tp-tick-label">{item.name}</div>
              <div className="lv-tp-tick-value" style={{ fontSize: item.name === "Markets root" ? "0.75rem" : undefined }}>
                {item.price}
              </div>
              <div className="lv-tp-tick-foot">
                <span className={item.up ? "is-good" : "is-bad"}>{item.change}</span>
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tp-md-mid">
          <Panel
            title="Register / scan OHLCV files"
            action={
              <div className="lv-tp-tf">
                <button type="button" className="lv-tp-mini" disabled={busy} onClick={() => void scan()}>
                  Scan folder
                </button>
                <button type="button" className="lv-tp-mini" disabled={busy} onClick={() => void register()}>
                  Validate & register
                </button>
              </div>
            }
          >
            <p className="lv-tp-muted">
              Place CSV files under the markets root. Required columns: timestamp, open, high, low, close, volume.
              Large files stay on disk; DB stores metadata + content hash only.
            </p>
            <div className="lv-tp-search-box" style={{ marginTop: 8 }}>
              <input
                type="text"
                placeholder="Relative path under markets root"
                value={path}
                onChange={(e) => setPath(e.target.value)}
              />
            </div>
          </Panel>

          <Panel title="Indexed sources">
            <div className="lv-tp-search-box">
              <input
                type="search"
                placeholder="Filter symbol or path..."
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="lv-tp-table-wrap">
              <table className="lv-tp-table">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>TF</th>
                    <th>Status</th>
                    <th>Quality</th>
                    <th>Bars</th>
                    <th>Range</th>
                    <th>Hash</th>
                    <th>Path</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((s) => {
                    const q = qualityOf(s);
                    return (
                    <tr key={s.source_id}>
                      <td className="sym">{s.symbol}</td>
                      <td>{s.timeframe}</td>
                      <td>
                        <span className={`lv-tp-pill${s.status === "READY" ? " is-live" : ""}`}>{s.status}</span>
                      </td>
                      <td>
                        <span
                          className={`lv-tp-pill${q === "PASS" ? " is-live" : ""}`}
                          title="PASS | WARN | FAIL | UNMEASURED — parse ≠ quality pass"
                        >
                          {q}
                        </span>
                      </td>
                      <td>{s.bar_count}</td>
                      <td>
                        {s.start_ts?.slice(0, 10) ?? "—"} → {s.end_ts?.slice(0, 10) ?? "—"}
                      </td>
                      <td title={s.content_hash}>{hashShort(s.content_hash)}</td>
                      <td>{s.path}</td>
                    </tr>
                    );
                  })}
                  {!filtered.length ? (
                    <tr>
                      <td colSpan={8}>No sources indexed — drop CSV files and scan</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel title="Validation errors">
            <ul className="lv-tp-alert-list">
              {sources
                .filter((s) => s.validation_error)
                .map((s) => (
                  <li key={s.source_id}>
                    <span className="ico err" />
                    <div>
                      <strong>{s.path}</strong>
                      {s.validation_error}
                    </div>
                  </li>
                ))}
              {!sources.some((s) => s.validation_error) ? (
                <li>
                  <span className="ico info" />
                  <div>
                    <strong>No validation errors</strong>
                    Ready sources passed OHLCV schema checks; Quality column reports PASS/WARN/FAIL/UNMEASURED
                  </div>
                </li>
              ) : null}
            </ul>
          </Panel>

          <Panel title="Providers & limits">
            <ul className="lv-tp-src-list">
              <li>
                <strong>CSV local / Binance public / Stooq</strong>
                <span>AVAILABLE</span>
                <span>OHLCV historical + public quotes for paper</span>
              </li>
              <li>
                <strong>L2 order book</strong>
                <span>NOT CLAIMED</span>
                <span>candles only — no order-book realism</span>
              </li>
              <li>
                <strong>Live broker orders</strong>
                <span>BLOCKED</span>
                <span>TradingStub / live guard</span>
              </li>
            </ul>
          </Panel>
        </section>

        <p className="lv-footer-quote">
          “Better data. Clearer markets. A more intelligent tomorrow.” — LEVIATHAN
        </p>
      </main>
    </AppShell>
  );
}
