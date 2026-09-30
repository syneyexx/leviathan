import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { MetricCard } from "../ui";

type Props = {
  ws: AgentsWorkspace;
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

export function AgentsMetrics({ ws }: Props) {
  const { kpis, loading, live } = ws;

  return (
    <section className="lv-v2-metrics lv-v2-metrics--agents" aria-label="Agent fleet KPI's">
      <MetricCard
        className="lv-v2-agents-kpi"
        variant="agents"
        label="Actieve Agents"
        loading={kpis.activeAgents.loading}
        value={kpis.activeAgents.value}
        sublabel={kpis.activeAgents.sublabel}
        chart={
          kpis.activeAgents.available ? (
            <MetricBars heights={[42, 58, 50, 72, 55, 80, 62, 74]} tone="success" />
          ) : undefined
        }
      />
      <MetricCard
        className="lv-v2-agents-kpi"
        variant="system"
        label="Idle Agents"
        loading={kpis.idleAgents.loading}
        value={kpis.idleAgents.value}
        sublabel={kpis.idleAgents.sublabel}
        chart={
          kpis.idleAgents.available ? (
            <MetricBars heights={[30, 45, 38, 55, 42, 60, 48, 58]} />
          ) : undefined
        }
      />
      <MetricCard
        className="lv-v2-agents-kpi"
        variant="jobs"
        label="Missies"
        loading={kpis.missions.loading}
        value={kpis.missions.value}
        sublabel={kpis.missions.sublabel}
        chart={
          kpis.missions.available ? (
            <MetricBars heights={[35, 50, 44, 68, 52, 75, 58, 70]} tone="agents" />
          ) : undefined
        }
      />
      <MetricCard
        className="lv-v2-agents-kpi"
        variant="research"
        label="Tool Calls"
        loading={kpis.toolCalls.loading}
        value={kpis.toolCalls.value}
        sublabel={kpis.toolCalls.sublabel}
      />
      <MetricCard
        className="lv-v2-agents-kpi"
        variant="trading"
        label="Succesratio"
        loading={kpis.successRate.loading}
        value={kpis.successRate.value}
        sublabel={`${kpis.successRate.sublabel}${live ? "" : " · stale"}`}
        valueTone={kpis.successRate.available ? "success" : "default"}
        chart={
          kpis.successRate.available ? (
            <MetricBars heights={[48, 55, 62, 58, 70, 74, 68, 78]} tone="success" />
          ) : undefined
        }
      />
      {loading ? <span className="lv-v2-sr-only">Laden…</span> : null}
    </section>
  );
}
