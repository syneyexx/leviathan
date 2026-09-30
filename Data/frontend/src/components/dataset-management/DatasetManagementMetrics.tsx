import { MetricCard } from "../ui";
import type { DatasetKpiCard } from "../../hooks/useDatasetManagementWorkspace";

type Props = {
  kpis: DatasetKpiCard[];
  loading?: boolean;
};

function MiniBars({ values, tone = "cyan" }: { values?: number[]; tone?: string }) {
  if (!values?.length) {
    return <div className="lv-v2-metric-card__chart lv-v2-metric-card__chart--empty" aria-hidden="true" />;
  }
  const max = Math.max(...values, 1);
  return (
    <div className={`lv-v2-metric-card__chart lv-v2-metric-card__chart--${tone}`} aria-hidden="true">
      {values.slice(-8).map((v, i) => (
        <span
          key={i}
          className="lv-v2-metric-card__bar"
          style={{ height: `${Math.max(12, Math.round((v / max) * 100))}%` }}
        />
      ))}
    </div>
  );
}

export function DatasetManagementMetrics({ kpis, loading }: Props) {
  return (
    <section className="lv-v2-metrics lv-v2-metrics--dataset-mgmt" aria-label="Dataset KPI's">
      {kpis.map((kpi) => (
        <MetricCard
          key={kpi.id}
          className={`lv-v2-dm-metric lv-v2-dm-metric--${kpi.tone}`}
          label={kpi.label}
          value={kpi.value}
          sublabel={kpi.hint}
          delta={kpi.delta}
          variant={
            kpi.tone === "red"
              ? "research"
              : kpi.tone === "gold"
                ? "trading"
                : kpi.tone === "green"
                  ? "system"
                  : "jobs"
          }
          valueTone={kpi.tone === "green" ? "success" : "default"}
          loading={Boolean(loading && kpi.value === "…")}
          chart={
            kpi.progress != null ? (
              <div className="lv-v2-dm-metric__progress" aria-hidden="true">
                <i style={{ width: `${Math.max(0, Math.min(100, kpi.progress))}%` }} />
              </div>
            ) : (
              <MiniBars
                values={kpi.sparkline}
                tone={kpi.tone === "red" ? "danger" : kpi.tone === "green" ? "success" : "jobs"}
              />
            )
          }
        />
      ))}
    </section>
  );
}
