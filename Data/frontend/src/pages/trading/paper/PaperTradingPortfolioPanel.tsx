import type { PortfolioDashboard } from "../../../types/api";
import { AreaSpark } from "../shared";
import { fmtMoney, fmtPct, fmtSigned, num, toneClass } from "./utils/format";

export function PaperTradingPortfolioPanel({
  dashboard,
  loading,
}: {
  dashboard: PortfolioDashboard | null;
  loading: boolean;
}) {
  if (loading && !dashboard) {
    return (
      <article className="lv-paper-panel lv-paper-portfolio">
        <header className="lv-paper-panel-head">
          <h2>Paper Portfolio</h2>
        </header>
        <p className="lv-paper-state">Loading portfolio…</p>
      </article>
    );
  }
  if (!dashboard) {
    return (
      <article className="lv-paper-panel lv-paper-portfolio">
        <header className="lv-paper-panel-head">
          <h2>Paper Portfolio</h2>
        </header>
        <p className="lv-paper-state">Awaiting paper portfolio session.</p>
      </article>
    );
  }

  const { kpis, risk, performance_summary: perf } = dashboard;
  const equityPts = (perf.series || [])
    .map((p) => num(p.equity))
    .filter((n) => Number.isFinite(n));
  const daily = num(kpis.daily_pnl);
  const total = num(kpis.unrealized_pnl) + num(kpis.realized_pnl);

  return (
    <article className="lv-paper-panel lv-paper-portfolio">
      <header className="lv-paper-panel-head">
        <h2>Paper Portfolio</h2>
        <span className="lv-paper-muted">USDT</span>
      </header>
      <div className="lv-paper-equity-row">
        <div>
          <div className="lv-paper-label">Total Equity (USDT)</div>
          <div className="lv-paper-equity">${fmtMoney(kpis.total_equity)}</div>
          <div className={`lv-paper-delta ${toneClass(kpis.daily_pnl_pct)}`}>
            {fmtPct(kpis.daily_pnl_pct)}
          </div>
        </div>
        {equityPts.length >= 2 ? (
          <AreaSpark points={equityPts.slice(-40)} width={140} height={48} color="#22c9d6" />
        ) : (
          <div className="lv-paper-mini-empty">No equity curve yet</div>
        )}
      </div>
      <div className="lv-paper-metric-grid">
        <div>
          <span>Total PnL</span>
          <strong className={toneClass(total)}>{fmtSigned(total)}</strong>
        </div>
        <div>
          <span>Daily PnL</span>
          <strong className={toneClass(daily)}>
            {fmtSigned(daily)} ({fmtPct(kpis.daily_pnl_pct)})
          </strong>
        </div>
        <div>
          <span>Unrealized PnL</span>
          <strong className={toneClass(num(kpis.unrealized_pnl))}>
            {fmtSigned(kpis.unrealized_pnl)}
          </strong>
        </div>
        <div>
          <span>Realized PnL</span>
          <strong className={toneClass(num(kpis.realized_pnl))}>
            {fmtSigned(kpis.realized_pnl)}
          </strong>
        </div>
      </div>
      <div className="lv-paper-secondary-metrics">
        <div>
          <span>Win Rate</span>
          <strong>{kpis.win_rate == null ? "—" : `${(kpis.win_rate * 100).toFixed(1)}%`}</strong>
        </div>
        <div>
          <span>Sharpe</span>
          <strong>{risk.sharpe == null ? "—" : risk.sharpe.toFixed(2)}</strong>
        </div>
        <div>
          <span>Max Drawdown</span>
          <strong className="is-bad">
            {risk.max_drawdown == null ? "—" : fmtPct(-Math.abs(risk.max_drawdown))}
          </strong>
        </div>
      </div>
    </article>
  );
}
