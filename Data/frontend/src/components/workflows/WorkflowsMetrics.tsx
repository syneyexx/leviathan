import { MetricCard, Sparkline } from "../ui";
import type { WorkflowOverview } from "../../types/api";

type Props = {
  overview: WorkflowOverview | null;
  loading?: boolean;
  unmeasured?: boolean;
};

function formatKpiValue(kpi: WorkflowOverview["kpis"][number]): string {
  if (kpi.unmeasured || kpi.value == null) return "—";
  if (kpi.unit === "%") return `${kpi.value}%`;
  if (kpi.unit === "min") return `${kpi.value} min`;
  if (typeof kpi.value === "number" && kpi.value >= 1000) {
    return kpi.value.toLocaleString("nl-NL");
  }
  return String(kpi.value);
}

function deltaClass(direction: string | undefined): string {
  if (direction === "up") return "is-up";
  if (direction === "down") return "is-down";
  return "";
}

export function WorkflowsMetrics({ overview, loading, unmeasured }: Props) {
  const kpis = overview?.kpis ?? [];
  const byId = (id: string) => kpis.find((k) => k.id === id);

  const cards = [
    byId("total_workflows"),
    byId("active_workflows"),
    byId("success_rate"),
    byId("avg_duration"),
    byId("total_executions"),
  ];

  const fallbackLabels = [
    "Totale Workflows",
    "Actieve Workflows",
    "Succes Rate",
    "Gem. Uitvoeringstijd",
    "Totaal Executies",
  ];

  const tones: Array<"jobs" | "agents" | "system" | "research" | "trading"> = [
    "jobs",
    "agents",
    "system",
    "research",
    "trading",
  ];

  const stroke = ["#38bdf8", "#34d399", "#60a5fa", "#a78bfa", "#fbbf24"];

  return (
    <section className="lv-v2-metrics lv-v2-metrics--workflows" aria-label="Workflow KPI's">
      {cards.map((kpi, i) => {
        const label = kpi?.label ?? fallbackLabels[i];
        const showUnmeasured = unmeasured || !overview || kpi?.unmeasured || kpi?.value == null;
        const value = showUnmeasured && !loading ? (overview ? "—" : "—") : kpi ? formatKpiValue(kpi) : "—";
        const changeDisplay =
          kpi?.id === "active_workflows"
            ? kpi.secondary || overview?.counts
              ? `${overview?.counts.running_executions ?? 0} draaien`
              : undefined
            : kpi?.change?.display && kpi.change.display !== "—"
              ? kpi.change.display
              : kpi?.secondary ?? undefined;
        const direction = kpi?.change?.direction;

        return (
          <MetricCard
            key={label}
            className="lv-v2-workflows-metric"
            label={label}
            value={value}
            sublabel={
              kpi?.id === "active_workflows"
                ? undefined
                : kpi?.id === "total_workflows" && kpi.secondary
                  ? undefined
                  : undefined
            }
            delta={
              changeDisplay ? (
                <span className={`lv-v2-workflows-metric__delta ${deltaClass(direction)}`}>
                  {changeDisplay}
                </span>
              ) : undefined
            }
            variant={tones[i]}
            loading={Boolean(loading && !overview)}
            chart={
              <Sparkline
                values={kpi?.sparkline ?? []}
                width={64}
                height={28}
                stroke={stroke[i]}
                className="lv-v2-workflows-spark"
              />
            }
          />
        );
      })}
    </section>
  );
}
