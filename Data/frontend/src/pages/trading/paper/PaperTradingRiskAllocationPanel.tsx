import type { PortfolioDashboard } from "../../../types/api";
import { Donut } from "../shared";
import { fmtMoney, fmtPct, num } from "./utils/format";

const COLORS = ["#22d3ee", "#34d399", "#e8c547", "#a78bfa", "#f87171", "#60a5fa", "#94a3b8"];

export function PaperTradingRiskAllocationPanel({
  dashboard,
}: {
  dashboard: PortfolioDashboard | null;
}) {
  if (!dashboard) {
    return (
      <article className="lv-paper-panel lv-paper-risk">
        <header className="lv-paper-panel-head">
          <h2>Risk & Allocation</h2>
        </header>
        <p className="lv-paper-state">No allocation data yet.</p>
      </article>
    );
  }

  const assets = dashboard.allocation?.assets || [];
  const slices = assets.slice(0, 6).map((a, i) => ({
    value: Math.max(0.01, a.allocation_pct),
    color: COLORS[i % COLORS.length],
    label: a.symbol,
  }));
  const openCount = dashboard.positions?.length || 0;
  const settings = (dashboard.portfolio.settings || {}) as Record<string, unknown>;
  const maxRaw = settings.max_concurrent_positions;
  const maxPos =
    typeof maxRaw === "number" || typeof maxRaw === "string" ? num(maxRaw) : 10;
  const var1d = dashboard.risk.var_1d_95;
  const center = `$${fmtMoney(num(dashboard.allocation.total_equity) / 1000, 1)}K`;

  return (
    <article className="lv-paper-panel lv-paper-risk">
      <header className="lv-paper-panel-head">
        <h2>Risk & Allocation</h2>
      </header>
      <div className="lv-paper-risk-body">
        {slices.length ? (
          <div className="lv-paper-donut-wrap">
            <Donut slices={slices} size={132} center={center} />
            <ul className="lv-paper-legend-list">
              {slices.map((s) => (
                <li key={s.label}>
                  <i style={{ background: s.color }} />
                  {s.label} · {s.value.toFixed(1)}%
                </li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="lv-paper-state">No open exposure — allocation empty.</p>
        )}
        <div className="lv-paper-secondary-metrics is-col">
          <div>
            <span>Leverage</span>
            <strong>{dashboard.exposure.leverage.toFixed(1)}x</strong>
          </div>
          <div>
            <span>Active Positions</span>
            <strong>
              {openCount}/{maxPos || "—"}
            </strong>
          </div>
          <div>
            <span>Value at Risk</span>
            <strong>
              {var1d == null ? "—" : fmtPct(Math.abs(var1d) <= 1 ? var1d * 100 : var1d)}
            </strong>
          </div>
        </div>
      </div>
    </article>
  );
}
