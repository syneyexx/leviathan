import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { MetricCard } from "../ui";

type Props = {
  overview: ResearchWorkspace;
};

function MetricBars({ heights, tone }: { heights: number[]; tone?: string }) {
  return (
    <div className={`lv-v2-metric-card__chart${tone ? ` lv-v2-metric-card__chart--${tone}` : ""}`} aria-hidden="true">
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

export function ResearchMetrics({ overview }: Props) {
  const { metrics, loading } = overview;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--research" aria-label="Research KPI's">
      <MetricCard
        variant="research"
        label="Actieve Onderzoeken"
        loading={loading || metrics.activeResearch.loading}
        value={fmt(metrics.activeResearch.value)}
        sublabel={metrics.activeResearch.sublabel}
        chart={
          metrics.activeResearch.available ? (
            <MetricBars heights={[40, 55, 48, 70, 52, 78, 60, 72]} tone="success" />
          ) : undefined
        }
      />
      <MetricCard
        variant="agents"
        label="Onderzoeks Agents"
        loading={loading || metrics.researchAgents.loading}
        value={fmt(metrics.researchAgents.value)}
        sublabel={metrics.researchAgents.sublabel}
        chart={
          metrics.researchAgents.available ? (
            <MetricBars heights={[30, 48, 40, 65, 45, 70, 55, 68]} tone="agents" />
          ) : undefined
        }
      />
      <MetricCard
        variant="system"
        label="Kennisbronnen"
        loading={loading || metrics.knowledgeSources.loading}
        value={fmt(metrics.knowledgeSources.value)}
        sublabel={metrics.knowledgeSources.sublabel}
        chart={
          metrics.knowledgeSources.available ? (
            <MetricBars heights={[28, 45, 38, 60, 50, 72, 58, 66]} />
          ) : undefined
        }
      />
      <MetricCard
        variant="trading"
        label="Web Bronnen"
        loading={loading || metrics.webSources.loading}
        value={metrics.webSources.available ? fmt(metrics.webSources.value) : "—"}
        sublabel={metrics.webSources.sublabel}
        chart={
          metrics.webSources.available ? (
            <MetricBars heights={[35, 50, 42, 68, 48, 75, 55, 70]} tone="amber" />
          ) : undefined
        }
      />
      <MetricCard
        variant="jobs"
        label="Documenten"
        loading={loading || metrics.documents.loading}
        value={metrics.documents.available ? fmt(metrics.documents.value) : "—"}
        sublabel={metrics.documents.sublabel}
        chart={
          metrics.documents.available ? (
            <MetricBars heights={[32, 48, 40, 62, 46, 70, 52, 64]} />
          ) : undefined
        }
      />
    </section>
  );
}
