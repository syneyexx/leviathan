import type { AgentsDashboard } from "../../types/api";
import { formatDurationMs, formatPct, formatSyncAge } from "./helpers";
import { Glyph } from "./agentsUi";

type Kpi = {
  key: string;
  label: string;
  value: string;
  sub: string;
  icon: string;
  tone?: "ok" | "warn" | "muted";
  title?: string;
};

export function AgentsKpiStrip({
  dashboard,
  nowMs,
  stale,
}: {
  dashboard: AgentsDashboard | null;
  nowMs: number;
  stale: boolean;
}) {
  const d = dashboard;
  const workersAvailable = Boolean(d?.workers.available);
  const kpis: Kpi[] = [
    {
      key: "agents",
      label: "Total Agents",
      value: d ? String(d.fleet.totalAgents) : "—",
      sub: d ? `${d.fleet.architecture} arch components` : "loading",
      icon: "users",
      title: "Non-archived fleet agents (architecture descriptors excluded)",
    },
    {
      key: "workers",
      label: "Active Workers",
      value: d && workersAvailable && d.workers.active != null ? String(d.workers.active) : "—",
      sub: !d
        ? "loading"
        : workersAvailable
          ? `${d.workers.instances ?? 0} registered · ${d.workers.supervisorHealth ?? "unknown"}`
          : "registry unavailable",
      icon: "workers",
      tone: d && !workersAvailable ? "muted" : undefined,
      title: "Ready/busy/starting/draining registry instances",
    },
    {
      key: "orch",
      label: "Orchestrators",
      value: d ? String(d.fleet.orchestrators) : "—",
      sub: d ? `${d.fleet.orchestratorsFleet} fleet · ${d.fleet.orchestratorsSystem} system` : "loading",
      icon: "planner",
    },
    {
      key: "running",
      label: "Running Tasks",
      value: d ? String(d.missions.active) : "—",
      sub: d ? `${d.missions.queued} queued · ${d.missions.running} running` : "loading",
      icon: "tasks",
    },
    {
      key: "success",
      label: "Success Rate",
      value: d ? formatPct(d.performance.successRate) : "—",
      sub: d
        ? d.performance.successRate == null
          ? `no terminal missions · ${d.windowHours}h`
          : `n=${d.performance.eligibleTerminal} · ${d.windowHours}h`
        : "loading",
      icon: "check",
      tone:
        d?.performance.successRate == null
          ? "muted"
          : d.performance.successRate >= 0.9
            ? "ok"
            : "warn",
      title: "completed / (completed + failed); cancelled excluded",
    },
    {
      key: "avg",
      label: "Avg Response Time",
      value: d ? formatDurationMs(d.performance.avgDurationMs) : "—",
      sub: d
        ? d.performance.p95DurationMs != null
          ? `p95 ${formatDurationMs(d.performance.p95DurationMs)} · n=${d.performance.sampleSize}`
          : "no completed samples"
        : "loading",
      icon: "gauge",
      title: "Mission startedAt → finishedAt for completed missions in window",
    },
    {
      key: "memory",
      label: "Memory Linked",
      value: d ? String(d.fleet.memoryLinked) : "—",
      sub: d ? `of ${d.fleet.totalAgents} agents` : "loading",
      icon: "memory",
      title: "Agents with a non-none memory policy",
    },
    {
      key: "sync",
      label: "Last Sync",
      value: d ? formatSyncAge(d.lastSync, nowMs) : "—",
      sub: stale ? "stale — retrying" : d ? "polling 6s" : "loading",
      icon: "sync",
      tone: stale ? "warn" : undefined,
    },
  ];

  return (
    <section className="lv-ag-kpis" aria-label="Agent fleet KPIs">
      {kpis.map((k) => (
        <article key={k.key} className={`lv-ag-kpi${k.tone ? ` is-${k.tone}` : ""}`} title={k.title}>
          <Glyph kind={k.icon} className="lv-ag-kpi-icon" />
          <div className="lv-ag-kpi-body">
            <span className="lv-ag-kpi-label">{k.label}</span>
            <strong className="lv-ag-kpi-value">{k.value}</strong>
            <small className="lv-ag-kpi-sub">{k.sub}</small>
          </div>
        </article>
      ))}
    </section>
  );
}
