import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "../../api/client";
import type { MarketDataSource, MarketSimStatusResponse } from "../../types/api";
import { useAppToast } from "../../state/useAppToast";
import { TradingShell, hashShort } from "./shared";

export function MarktdataPage() {
  const toast = useAppToast();
  const [status, setStatus] = useState<MarketSimStatusResponse | null>(null);
  const [sources, setSources] = useState<MarketDataSource[]>([]);
  const [path, setPath] = useState("BTCUSDT_1h.csv");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const st = await api.marketSimStatus();
      setStatus(st);
      if (st.enabled) {
        const { sources: list } = await api.listMarketData();
        setSources(list);
      }
      setError(st.enabled ? null : "LEVIATHAN_FEATURE_MARKET_SIM is OFF");
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

  return (
    <TradingShell title="Marktdata">
      <section className="lv-tr-kpi-row">
        <article className="lv-tr-kpi">
          <div className="lv-tr-kpi-label">Markets root</div>
          <div className="lv-tr-kpi-value" style={{ fontSize: "0.85rem" }}>
            {status?.health.markets_root ?? "—"}
          </div>
          <div className="lv-tr-kpi-foot">
            <span>{status?.health.exists ? "exists" : "missing"}</span>
          </div>
        </article>
        <article className="lv-tr-kpi">
          <div className="lv-tr-kpi-label">Indexed</div>
          <div className="lv-tr-kpi-value">{status?.health.sources_indexed ?? 0}</div>
        </article>
        <article className="lv-tr-kpi">
          <div className="lv-tr-kpi-label">Ready</div>
          <div className="lv-tr-kpi-value">{status?.health.sources_ready ?? 0}</div>
        </article>
        <article className="lv-tr-kpi">
          <div className="lv-tr-kpi-label">Feature</div>
          <div className="lv-tr-kpi-value">{status?.enabled ? "ON" : "OFF"}</div>
        </article>
      </section>

      {error ? (
        <article className="lv-panel lv-tr-card">
          <p>{error}</p>
        </article>
      ) : null}

      <section className="lv-tr-mid">
        <article className="lv-panel lv-tr-card">
          <div className="lv-section-label">Register / scan</div>
          <p>
            Place real OHLCV CSV files under the markets root. Columns: timestamp, open, high, low, close,
            volume. Parquet is optional (requires pyarrow).
          </p>
          <label className="lv-tr-field">
            <span>Relative path under markets root</span>
            <input value={path} onChange={(e) => setPath(e.target.value)} />
          </label>
          <div className="lv-tr-actions">
            <button type="button" disabled={busy} onClick={() => void register()}>
              Validate & register
            </button>
            <button type="button" disabled={busy} onClick={() => void scan()}>
              Scan folder
            </button>
          </div>
        </article>

        <article className="lv-panel lv-tr-card" style={{ gridColumn: "span 2" }}>
          <div className="lv-section-label">Sources</div>
          <div className="lv-tr-table-wrap">
            <table className="lv-tr-table">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th>TF</th>
                  <th>Status</th>
                  <th>Bars</th>
                  <th>Range</th>
                  <th>Hash</th>
                  <th>Path</th>
                </tr>
              </thead>
              <tbody>
                {sources.map((s) => (
                  <tr key={s.source_id}>
                    <td>{s.symbol}</td>
                    <td>{s.timeframe}</td>
                    <td>{s.status}</td>
                    <td>{s.bar_count}</td>
                    <td>
                      {s.start_ts ?? "—"} → {s.end_ts ?? "—"}
                    </td>
                    <td title={s.content_hash}>{hashShort(s.content_hash)}</td>
                    <td>{s.path}</td>
                  </tr>
                ))}
                {!sources.length ? (
                  <tr>
                    <td colSpan={7}>No sources indexed — drop CSV files and scan</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          {sources.some((s) => s.validation_error) ? (
            <ul className="lv-tr-activity">
              {sources
                .filter((s) => s.validation_error)
                .map((s) => (
                  <li key={s.source_id}>
                    <span className="lv-tr-dot info" />
                    <div>
                      <strong>{s.path}</strong>
                      <small>{s.validation_error}</small>
                    </div>
                  </li>
                ))}
            </ul>
          ) : null}
        </article>
      </section>
    </TradingShell>
  );
}
