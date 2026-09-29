import type { DashboardOverview } from "../../hooks/useDashboardOverview";
import { MetricCard } from "../ui";

type Props = {
  overview: DashboardOverview;
};

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
      />
      <MetricCard
        variant="research"
        label="Onderzoek"
        loading={loading}
        value={
          research.available && research.activeCount != null ? String(research.activeCount) : "—"
        }
        sublabel={research.available ? "actieve experimenten" : "UNAVAILABLE"}
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
      />
    </section>
  );
}
