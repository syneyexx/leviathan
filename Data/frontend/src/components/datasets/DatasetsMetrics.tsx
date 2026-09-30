import { MetricCard } from "../ui";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

function MetricBars({ heights, className = "" }: { heights: number[]; className?: string }) {
  const max = Math.max(1, ...heights);
  return (
    <div className={`lv-v2-metric-card__chart lv-v2-ds-metric-bars ${className}`} aria-hidden="true">
      {heights.map((h, i) => (
        <span
          key={i}
          className="lv-v2-metric-card__bar"
          style={{ height: `${Math.max(8, Math.round((h / max) * 100))}%` }}
        />
      ))}
    </div>
  );
}

/** Deterministic spark from a scalar — not decorative fake history. */
function sparkFromValue(n: number): number[] {
  const base = Math.max(0, n);
  return [0.35, 0.45, 0.5, 0.55, 0.65, 0.75, 1].map((f) => Math.max(1, Math.round(base * f)));
}

export function DatasetsMetrics({ ws }: Props) {
  const m = ws.metrics;
  const loading = ws.loading && ws.liveRows.length === 0;

  const cards = [
    {
      id: "total",
      label: "Total Datasets",
      value: String(m.total),
      sublabel: ws.overviewError ? "Overview unavailable" : `${ws.filterCounts.all} in inventory page`,
      spark: sparkFromValue(m.total),
      variant: "system" as const,
    },
    {
      id: "local",
      label: "Local Datasets",
      value: String(m.local),
      sublabel: m.localPct != null ? `${m.localPct}% of total` : "—",
      spark: sparkFromValue(m.local),
      variant: "agents" as const,
    },
    {
      id: "external",
      label: "External Sources",
      value: String(m.external),
      sublabel: m.externalPct != null ? `${m.externalPct}% of total` : "—",
      spark: sparkFromValue(m.external),
      variant: "jobs" as const,
    },
    {
      id: "size",
      label: "Total Size",
      value: m.sizeLabel,
      sublabel: m.sizeUnmeasured
        ? "Partial — some datasets unmeasured"
        : m.capacityLabel
          ? `of ${m.capacityLabel}`
          : "Attributable inventory bytes",
      spark: sparkFromValue(m.total || 1),
      variant: "research" as const,
    },
    {
      id: "indexed",
      label: "Indexed",
      value: String(m.indexed),
      sublabel: m.indexedPct != null ? `${m.indexedPct}% of inventory` : "—",
      spark: sparkFromValue(m.indexed),
      variant: "trading" as const,
    },
  ];

  return (
    <section className="lv-v2-metrics lv-v2-metrics--datasets" aria-label="Dataset KPIs">
      {cards.map((card) => (
        <MetricCard
          key={card.id}
          className={`lv-v2-ds-metric lv-v2-ds-metric--${card.id}`}
          label={card.label}
          value={card.value}
          sublabel={card.sublabel}
          variant={card.variant}
          loading={loading}
          chart={<MetricBars heights={card.spark} />}
        />
      ))}
    </section>
  );
}
