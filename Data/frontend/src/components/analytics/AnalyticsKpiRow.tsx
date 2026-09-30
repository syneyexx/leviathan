import type { AnalyticsKpiMetric } from "../../types/api";
import type { AnalyticsWorkspace } from "../../pages/analytics/useAnalyticsWorkspace";

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  if (n >= 1_000) return n.toLocaleString("nl-NL");
  return String(Math.round(n * 100) / 100);
}

function formatValue(
  metric: AnalyticsKpiMetric | undefined,
  format: "count" | "seconds" | "percent",
): string {
  if (!metric || !metric.measured || metric.value == null || metric.status === "UNMEASURED") {
    return "UNMEASURED";
  }
  if (metric.status === "ERROR") return "—";
  if (format === "seconds") return `${metric.value}s`;
  if (format === "percent") return `${metric.value}%`;
  return formatCount(metric.value);
}

function deltaText(metric: AnalyticsKpiMetric | undefined): string {
  if (!metric || metric.deltaPercent == null) return "—";
  const sign = metric.deltaPercent > 0 ? "+" : "";
  return `${sign}${metric.deltaPercent}%`;
}

function deltaClass(metric: AnalyticsKpiMetric | undefined): string {
  if (!metric || metric.deltaPercent == null || !metric.deltaDirection) return "";
  if (metric.deltaDirection === "flat") return "is-flat";
  if (metric.deltaDirection === "improved") return "is-good";
  return "is-bad";
}

function MiniSpark({ values, accent }: { values: number[]; accent: string }) {
  if (!values.length) return null;
  const max = Math.max(...values, 1);
  return (
    <div className={`lv-an-spark lv-an-spark--${accent}`} aria-hidden="true">
      {values.slice(-12).map((v, i) => (
        <span key={i} style={{ height: `${Math.max(12, (v / max) * 100)}%` }} />
      ))}
    </div>
  );
}

export function AnalyticsKpiRow({ ws }: { ws: AnalyticsWorkspace }) {
  return (
    <section className="lv-an-kpi-row lv-an-kpi-row--v2" aria-label="KPI overzicht">
      {ws.kpiCards.map((card) => {
        const metric = card.metric;
        const value = ws.loading && !ws.dashboard ? "…" : formatValue(metric, card.format);
        return (
          <article
            key={card.id}
            id={`lv-an-panel-${card.id}`}
            className={`lv-an-kpi lv-an-kpi--v2 lv-an-kpi--${card.accent}`}
          >
            <div className="lv-an-kpi-label">{card.label}</div>
            <div className="lv-an-kpi-body">
              <div>
                <div className="lv-an-kpi-value">{value}</div>
                <div className={`lv-an-kpi-delta ${deltaClass(metric)}`}>{deltaText(metric)}</div>
              </div>
              {metric?.spark?.length ? <MiniSpark values={metric.spark} accent={card.accent} /> : null}
            </div>
          </article>
        );
      })}
    </section>
  );
}
