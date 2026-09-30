import { MetricCard } from "../ui";
import type { MemoryWorkspace } from "../../hooks/useMemoryWorkspace";

function fmt(n: number | null | undefined): string {
  if (n == null) return "—";
  return n.toLocaleString("nl-NL");
}

function MiniBars({
  values,
  tone = "success",
}: {
  values?: number[];
  tone?: "success" | "agents" | "amber" | "jobs";
}) {
  if (!values || values.length === 0) {
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

export function MemoryMetrics({ ws }: { ws: MemoryWorkspace }) {
  const series = ws.analytics?.series;
  return (
    <section className="lv-v2-metrics lv-v2-metrics--memory" aria-label="Geheugen KPI's">
      <MetricCard
        label="Totaal Geheugen"
        value={fmt(ws.kpi.total)}
        sublabel={ws.kpi.active != null ? `${fmt(ws.kpi.active)} active` : undefined}
        variant="system"
        loading={ws.loading}
        chart={<MiniBars values={series?.new_items.map((d) => d.count)} tone="success" />}
      />
      <MetricCard
        label="Vector Embeddings"
        value={fmt(ws.kpi.embeddings)}
        sublabel="geïndexeerde memories"
        variant="agents"
        loading={ws.loading}
        chart={<MiniBars values={series?.embeddings.map((d) => d.count)} tone="agents" />}
      />
      <MetricCard
        label="Opslag Gebruik"
        value={ws.kpi.storage}
        sublabel={ws.kpi.storageProvenance}
        variant="jobs"
        loading={ws.loading}
        chart={<MiniBars values={series?.new_items.map((d) => d.count)} tone="jobs" />}
      />
      <MetricCard
        label="Bronnen"
        value={fmt(ws.kpi.sources)}
        sublabel="unieke Memory sources"
        variant="research"
        loading={ws.loading}
        chart={<MiniBars values={series?.searches.map((d) => d.count)} tone="amber" />}
      />
      <MetricCard
        label="Zoekopdrachten"
        value={fmt(ws.kpi.searches)}
        sublabel={`venster ${ws.kpi.searchesLabel}`}
        variant="trading"
        loading={ws.loading}
        chart={<MiniBars values={series?.searches.map((d) => d.count)} tone="jobs" />}
      />
    </section>
  );
}
