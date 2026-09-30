import { MetricCard, Sparkline } from "../ui";
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
      stroke: "#3b82f6",
    },
    {
      id: "running",
      label: "Lopende Taken",
      value: running == null ? "—" : String(running),
      sublabel: total != null && running != null ? pctOf(running, total) ?? "—" : summary ? "—" : undefined,
      spark: series(summary, "running"),
      variant: "agents" as const,
      stroke: "#22d3ee",
    },
    {
      id: "waiting",
      label: "Wachtende Taken",
      value: waiting == null ? "—" : String(waiting),
      sublabel: waiting != null ? "In wachtrij" : summary ? "—" : undefined,
      spark: series(summary, "waiting"),
      variant: "trading" as const,
      stroke: "#f59e0b",
    },
    {
      id: "completed",
      label: "Voltooide Taken",
      value: completed == null ? "—" : String(completed),
      sublabel: completed != null ? "Afgelopen 7 dagen" : summary ? "—" : undefined,
      spark: series(summary, "completed"),
      variant: "system" as const,
      stroke: "#34d399",
    },
    {
      id: "failed",
      label: "Mislukte Taken",
      value: failed == null ? "—" : String(failed),
      sublabel: total != null && failed != null ? pctOf(failed, total) ?? "—" : summary ? "—" : undefined,
      spark: series(summary, "failed"),
      variant: "research" as const,
      stroke: "#ef4444",
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
            <Sparkline
              values={card.spark}
              width={72}
              height={28}
              className="lv-v2-tasks-spark"
              stroke={card.stroke}
            />
          }
        />
      ))}
    </section>
  );
}
