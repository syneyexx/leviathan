import type { DashboardOverview } from "../../hooks/useDashboardOverview";
import { MetricCard } from "../ui";

type Props = {
  overview: DashboardOverview;
};

/** Decorative KPI bars (visual density only — not historical series). */
function MetricBars({ heights }: { heights: number[] }) {
  return (
    <div className="lv-v2-metric-card__chart" aria-hidden="true">
      {heights.map((h, i) => (
        <span key={i} className="lv-v2-metric-card__bar" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

export function DashboardMetrics({ overview }: Props) {
  const { systemStatus, agents, jobs, research, trading, loading } = overview;

  return (
    <section className="lv-v2-metrics" aria-label="KPI overzicht">
      <MetricCard
        variant="system"
        label="Systeem Status"
        loading={loading}
        valueTone={systemStatus.operational ? "success" : "default"}
        value={systemStatus.label}
        chart={<MetricBars heights={systemStatus.operational ? [40, 70, 45, 85, 55, 90, 60, 75] : [20, 20, 22, 20, 20, 22, 20, 20]} />}
      />
      <MetricCard
        variant="agents"
        label="Actieve Agents"
        loading={loading}
        value={agents.available && agents.active != null ? String(agents.active) : "—"}
        sublabel={
          agents.available && agents.total != null
            ? `van ${agents.total} beschikbaar`
            : agents.available
              ? "gemeten"
              : "UNAVAILABLE"
        }
        delta={
          agents.delta != null && agents.delta !== 0
            ? `${agents.delta > 0 ? "+" : ""}${agents.delta}`
            : undefined
        }
        chart={
          agents.available && agents.active != null ? (
            <MetricBars heights={[35, 55, 45, 70, 50, 80, 60, 75]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="jobs"
        label="Actieve Jobs"
        loading={loading}
        value={jobs.available && jobs.active != null ? String(jobs.active) : "—"}
        sublabel={
          jobs.available && jobs.queued != null
            ? `van ${jobs.queued} in queue`
            : jobs.available
              ? "gemeten"
              : "UNAVAILABLE"
        }
        chart={
          jobs.available && jobs.active != null ? (
            <MetricBars heights={[30, 50, 40, 65, 45, 70, 55, 60]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="research"
        label="Onderzoek"
        loading={loading}
        value={
          research.available && research.activeCount != null ? String(research.activeCount) : "—"
        }
        sublabel={research.available ? "actieve experimenten" : "UNAVAILABLE"}
        chart={
          research.available && research.activeCount != null ? (
            <MetricBars heights={[25, 45, 35, 60, 40, 70, 50, 55]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="trading"
        label="Trading"
        loading={loading}
        value={
          trading.available && trading.activeStrategies != null
            ? String(trading.activeStrategies)
            : "—"
        }
        sublabel={
          trading.available
            ? trading.paper
              ? "actieve strategieën (paper)"
              : "actieve strategieën"
            : "UNAVAILABLE"
        }
        chart={
          trading.available && trading.activeStrategies != null ? (
            <MetricBars heights={[28, 48, 38, 58, 42, 68, 52, 62]} />
          ) : undefined
        }
      />
    </section>
  );
}
