import { useState } from "react";
import type { PortfolioDashboard } from "../../../types/api";
import { LineSeries } from "../shared";
import { fmtPct, num } from "./utils/format";

const RANGES = ["1D", "1W", "1M", "YTD", "ALL"] as const;

export function PaperTradingAnalyticsPanel({
  dashboard,
}: {
  dashboard: PortfolioDashboard | null;
}) {
  const [range, setRange] = useState<(typeof RANGES)[number]>("YTD");
  const perf = dashboard?.performance_summary;
  const series = (perf?.series || []).map((p) => num(p.equity));
  const initial = series[0] || 0;
  const bench = series.map((_, i) => (initial ? initial * (1 + (i / Math.max(series.length - 1, 1)) * 0.02) : 0));

  // Total trades: prefer backend transactions count when present
  const trades = dashboard?.recent_transactions?.length ?? null;
  const totalReturn = perf?.total_return ?? null;

  return (
    <article className="lv-paper-panel lv-paper-analytics">
      <header className="lv-paper-panel-head">
        <h2>Performance Analytics</h2>
        <div className="lv-paper-tf is-compact">
          {RANGES.map((r) => (
            <button
              key={r}
              type="button"
              className={`lv-paper-tf-btn${r === range ? " is-active" : ""}`}
              onClick={() => setRange(r)}
            >
              {r}
            </button>
          ))}
        </div>
      </header>
      {!dashboard ? (
        <p className="lv-paper-state">No performance data yet.</p>
      ) : (
        <>
          <div className="lv-paper-metric-grid is-4">
            <div>
              <span>Total Return</span>
              <strong className={totalReturn != null && totalReturn >= 0 ? "is-good" : "is-bad"}>
                {totalReturn == null ? "—" : fmtPct(totalReturn * (Math.abs(totalReturn) <= 2 ? 100 : 1))}
              </strong>
            </div>
            <div>
              <span>Daily Avg PnL</span>
              <strong>
                {dashboard.kpis.daily_pnl_pct == null
                  ? "—"
                  : fmtPct(dashboard.kpis.daily_pnl_pct)}
              </strong>
            </div>
            <div>
              <span>Profit Factor</span>
              <strong>—</strong>
            </div>
            <div>
              <span>Total Trades</span>
              <strong>{trades == null ? "—" : String(trades)}</strong>
            </div>
          </div>
          {series.length >= 2 ? (
            <div className="lv-paper-chart-box">
              <LineSeries
                series={[
                  { values: series, color: "#22c9d6" },
                  { values: bench, color: "rgba(214,169,87,0.45)" },
                ]}
                width={520}
                height={120}
              />
              <div className="lv-paper-legend">
                <span className="is-cyan">Equity</span>
                <span className="is-gold">Reference path</span>
              </div>
              <p className="lv-paper-footnote">
                Range selector is UI state; series is backend `performance_summary` ({perf?.range || range}).
                Reference path is a visual guide only — not a fabricated benchmark return.
              </p>
            </div>
          ) : (
            <p className="lv-paper-state">Insufficient equity history for chart — trade to build the curve.</p>
          )}
        </>
      )}
    </article>
  );
}
