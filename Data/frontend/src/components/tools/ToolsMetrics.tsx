import { MetricCard } from "../ui";
import type { ToolsOverview } from "../../types/api";

type Props = {
  overview: ToolsOverview | null;
  loading?: boolean;
};

function MiniBars({
  values,
  tone = "success",
}: {
  values?: number[];
  tone?: "success" | "agents" | "amber" | "jobs" | "danger";
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

function MiniLine({ values }: { values?: number[] }) {
  if (!values || values.length < 2) {
    return <div className="lv-v2-metric-card__chart lv-v2-metric-card__chart--empty" aria-hidden="true" />;
  }
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(max - min, 1);
  const pts = values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * 100;
      const y = 100 - ((v - min) / span) * 100;
      return `${x},${y}`;
    })
    .join(" ");
  return (
    <svg className="lv-v2-tools-sparkline" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      <polyline fill="none" stroke="currentColor" strokeWidth="3" points={pts} />
    </svg>
  );
}

export function ToolsMetrics({ overview, loading }: Props) {
  const unmeasured = !overview || overview.success_ratio_unmeasured;
  const success =
    overview?.success_ratio_pct != null ? `${overview.success_ratio_pct}%` : unmeasured ? "—" : "—";
  const delta =
    overview?.success_ratio_delta_pp != null
      ? `${overview.success_ratio_delta_pp > 0 ? "+" : ""}${overview.success_ratio_delta_pp}% vs. vorige week`
      : undefined;

  const pluginCount = overview?.plugins?.length;
  const mcpServerCount = overview?.mcp_servers?.length;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--tools" aria-label="Tools KPI's">
      <MetricCard
        className="lv-v2-tools-metric"
        label="Totaal Tools"
        value={overview ? String(overview.total_capabilities) : "—"}
        sublabel={
          overview
            ? `${overview.active_capabilities} actief / ${overview.inactive_capabilities} inactief`
            : undefined
        }
        variant="system"
        loading={Boolean(loading && !overview)}
        chart={<MiniBars values={overview?.spark?.total_tools} tone="success" />}
      />
      <MetricCard
        className="lv-v2-tools-metric"
        label="Tools Categorieën"
        value={overview ? String(overview.category_count) : "—"}
        sublabel={
          overview?.categories?.length
            ? overview.categories
                .slice(0, 4)
                .map((c) => c.label)
                .join(", ") + (overview.categories.length > 4 ? "..." : "")
            : undefined
        }
        variant="agents"
        loading={Boolean(loading && !overview)}
        chart={<MiniBars values={overview?.spark?.categories} tone="agents" />}
      />
      <MetricCard
        className="lv-v2-tools-metric"
        label="Plugin Tools"
        value={overview ? String(overview.plugin_tool_count) : "—"}
        sublabel={pluginCount != null ? `${pluginCount} plugins` : undefined}
        variant="jobs"
        loading={Boolean(loading && !overview)}
        chart={<MiniBars values={overview?.spark?.plugin} tone="jobs" />}
      />
      <MetricCard
        className="lv-v2-tools-metric"
        label="MCP Tools"
        value={overview ? String(overview.mcp_tool_count) : "—"}
        sublabel={mcpServerCount != null ? `${mcpServerCount} servers` : undefined}
        variant="research"
        loading={Boolean(loading && !overview)}
        chart={<MiniBars values={overview?.spark?.mcp} tone="agents" />}
      />
      <MetricCard
        className="lv-v2-tools-metric"
        label="Custom Tools"
        value={overview ? String(overview.custom_tool_count) : "—"}
        sublabel="Eigen tools"
        variant="trading"
        loading={Boolean(loading && !overview)}
        chart={<MiniBars values={overview?.spark?.custom} tone="amber" />}
      />
      <MetricCard
        className="lv-v2-tools-metric"
        label="Succesratio"
        value={success}
        sublabel={delta}
        valueTone="success"
        variant="system"
        loading={Boolean(loading && !overview)}
        chart={
          <div className="lv-v2-tools-metric__line" aria-hidden="true">
            <MiniLine values={overview?.spark?.success} />
          </div>
        }
      />
    </section>
  );
}
