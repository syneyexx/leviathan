import type { BrainOverview } from "../../hooks/useBrainOverview";
import { MetricCard } from "../ui";

type Props = {
  overview: BrainOverview;
};

function MetricBars({ heights }: { heights: number[] }) {
  return (
    <div className="lv-v2-metric-card__chart" aria-hidden="true">
      {heights.map((h, i) => (
        <span key={i} className="lv-v2-metric-card__bar" style={{ height: `${h}%` }} />
      ))}
    </div>
  );
}

function fmt(n: number | null): string {
  if (n == null) return "—";
  return n.toLocaleString("nl-NL");
}

export function BrainMetrics({ overview }: Props) {
  const { metrics, loading } = overview;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--brain" aria-label="Brain KPI's">
      <MetricCard
        variant="agents"
        label="Actieve Nodes"
        loading={loading || metrics.activeNodes.loading}
        value={fmt(metrics.activeNodes.value)}
        sublabel={metrics.activeNodes.sublabel}
        chart={
          metrics.activeNodes.available ? (
            <MetricBars heights={[40, 55, 45, 70, 50, 80, 60, 72]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="system"
        label="Kennis Links"
        loading={loading || metrics.knowledgeLinks.loading}
        value={fmt(metrics.knowledgeLinks.value)}
        sublabel={metrics.knowledgeLinks.sublabel}
        chart={
          metrics.knowledgeLinks.available ? (
            <MetricBars heights={[30, 50, 42, 68, 48, 75, 55, 70]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="research"
        label="Geheugen Clusters"
        loading={loading || metrics.memoryClusters.loading}
        value={fmt(metrics.memoryClusters.value)}
        sublabel={metrics.memoryClusters.sublabel}
        chart={
          metrics.memoryClusters.available ? (
            <MetricBars heights={[28, 48, 38, 60, 44, 70, 52, 64]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="jobs"
        label="Redenering Jobs"
        loading={loading || metrics.reasoningJobs.loading}
        value={fmt(metrics.reasoningJobs.value)}
        sublabel={metrics.reasoningJobs.sublabel}
        chart={
          metrics.reasoningJobs.available ? (
            <MetricBars heights={[35, 45, 55, 40, 65, 50, 70, 58]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="trading"
        label="Bewijs Items"
        loading={loading || metrics.evidenceItems.loading}
        value={fmt(metrics.evidenceItems.value)}
        sublabel={metrics.evidenceItems.sublabel}
        chart={
          metrics.evidenceItems.available ? (
            <MetricBars heights={[32, 52, 40, 62, 48, 72, 54, 66]} />
          ) : undefined
        }
      />
    </section>
  );
}
