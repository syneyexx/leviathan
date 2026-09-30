import { MetricCard } from "../ui";
import type { TaskSummary } from "../../types/api";

type Props = {
  summary: TaskSummary | null;
  loading?: boolean;
};

function pctOf(part: number, total: number): string | null {
  if (!total) return null;
  return `${Math.round((part / total) * 100)}% van totaal`;
}

function series(summary: TaskSummary | null, key: keyof NonNullable<TaskSummary["sparklines"]>): number[] {
  const values = summary?.sparklines?.[key];
  return Array.isArray(values) ? values : [];
}

/** Real bucket heights from summary sparklines (not decorative). */
function MetricBars({
  heights,
  className = "",
}: {
  heights: number[];
  className?: string;
}) {
  const max = Math.max(1, ...heights);
  return (
    <div className={`lv-v2-metric-card__chart lv-v2-tasks-metric-bars ${className}`} aria-hidden="true">
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

export function TasksMetrics({ summary, loading }: Props) {
  const total = summary?.total ?? null;
  const running = summary?.running ?? null;
  const waiting = summary?.waiting ?? null;
  const completed = summary?.completedLast7Days ?? null;
  const failed = summary?.failed ?? null;

  const cards = [
    {
      id: "total",
      label: "Totaal Taken",
      value: total == null ? "—" : String(total),
      sublabel:
        running != null && waiting != null
          ? `${running} actief / ${waiting} in wachtrij`
          : summary
            ? "—"
            : undefined,
      spark: series(summary, "total"),
      variant: "jobs" as const,
      chartClass: "",
    },
    {
      id: "running",
      label: "Lopende Taken",
      value: running == null ? "—" : String(running),
      sublabel: total != null && running != null ? pctOf(running, total) ?? "—" : summary ? "—" : undefined,
      spark: series(summary, "running"),
      variant: "agents" as const,
      chartClass: "lv-v2-metric-card__chart--agents",
    },
    {
      id: "waiting",
      label: "Wachtende Taken",
      value: waiting == null ? "—" : String(waiting),
      sublabel: waiting != null ? "In wachtrij" : summary ? "—" : undefined,
      spark: series(summary, "waiting"),
      variant: "trading" as const,
      chartClass: "lv-v2-metric-card__chart--amber",
    },
    {
      id: "completed",
      label: "Voltooide Taken",
      value: completed == null ? "—" : String(completed),
      sublabel: completed != null ? "Afgelopen 7 dagen" : summary ? "—" : undefined,
      spark: series(summary, "completed"),
      variant: "system" as const,
      chartClass: "lv-v2-metric-card__chart--success",
    },
    {
      id: "failed",
      label: "Mislukte Taken",
      value: failed == null ? "—" : String(failed),
      sublabel: total != null && failed != null ? pctOf(failed, total) ?? "—" : summary ? "—" : undefined,
      spark: series(summary, "failed"),
      variant: "research" as const,
      chartClass: "lv-v2-tasks-metric-bars--danger",
    },
  ];

  return (
    <section className="lv-v2-metrics lv-v2-metrics--tasks" aria-label="Taken KPI's">
      {cards.map((card) => (
        <MetricCard
          key={card.id}
          className={`lv-v2-tasks-metric lv-v2-tasks-metric--${card.id}`}
          label={card.label}
          value={card.value}
          sublabel={card.sublabel}
          variant={card.variant}
          loading={Boolean(loading && !summary)}
          chart={
            <MetricBars
              heights={card.spark.length ? card.spark : [0, 0, 0, 0, 0, 0, 0]}
              className={card.chartClass}
            />
          }
        />
      ))}
    </section>
  );
}
