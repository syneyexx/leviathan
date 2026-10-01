import { MetricCard } from "../ui";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

function MetricBars({ heights }: { heights: number[] }) {
  const max = Math.max(1, ...heights);
  return (
    <div className="lv-v2-metric-card__chart lv-v2-ds-metric-bars" aria-hidden="true">
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

/** Deterministic spark from a scalar — decorative only, not historical truth. */
function sparkFromValue(n: number | null | undefined): number[] {
  const base = Math.max(0, n ?? 0);
  return [0.35, 0.45, 0.5, 0.55, 0.65, 0.75, 1].map((f) => Math.max(1, Math.round(base * f)));
}

function metricValue(n: number | null | undefined, unavailable: boolean): string {
  if (unavailable || n == null) return "—";
  return String(n);
}

export function DatasetsMetrics({ ws }: Props) {
  const m = ws.metrics;
  const loading = ws.loading && ws.liveRows.length === 0;
  const unavailable = Boolean(m.unavailable) || Boolean(ws.overviewError && m.total == null);

  const cards = [
    {
      id: "total",
      label: "Totaal Datasets",
      value: metricValue(m.total, unavailable),
      sublabel: unavailable
        ? m.unavailableReason || ws.overviewError || "Catalog unavailable"
        : m.catalogTotal == null
          ? "—"
          : `${m.inventoryPageSize} op pagina · ${m.catalogTotal} in catalogus`,
      spark: sparkFromValue(m.total),
      variant: "system" as const,
    },
    {
      id: "local",
      label: "Lokale Datasets",
      value: metricValue(m.local, unavailable),
      sublabel: unavailable ? "UNAVAILABLE" : m.localPct != null ? `${m.localPct}% van totaal` : "—",
      spark: sparkFromValue(m.local),
      variant: "agents" as const,
    },
    {
      id: "external",
      label: "Externe Bronnen",
      value: metricValue(m.external, unavailable),
      sublabel: unavailable
        ? "UNAVAILABLE"
        : m.externalPct != null
          ? `${m.externalPct}% van totaal`
          : "—",
      spark: sparkFromValue(m.external),
      variant: "jobs" as const,
    },
    {
      id: "size",
      label: "Totaal Grootte",
      value: unavailable ? "—" : m.sizeLabel,
      sublabel: unavailable
        ? "UNAVAILABLE"
        : m.sizeUnmeasured
          ? "Partieel — sommige datasets unmeasured"
          : m.capacityLabel
            ? `van ${m.capacityLabel}`
            : "Attributabele inventory bytes",
      spark: sparkFromValue(m.total || 1),
      variant: "research" as const,
    },
    {
      id: "indexed",
      label: "Geïndexeerd",
      value: metricValue(m.indexed, unavailable),
      sublabel: unavailable
        ? "UNAVAILABLE"
        : m.indexedPct != null
          ? `${m.indexedPct}% van totaal`
          : "—",
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
