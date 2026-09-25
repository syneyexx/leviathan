import type { AgentsDashboard } from "../../types/api";
import { formatPct } from "./helpers";
import { Glyph, LiveBadge, PanelHead } from "./agentsUi";

type Step = { key: string; label: string; icon: string; value: string; caption: string; title: string };

export function OrchestrationFlowPanel({
  dashboard,
  live,
}: {
  dashboard: AgentsDashboard | null;
  live: boolean;
}) {
  const f = dashboard?.flow;
  const steps: Step[] = [
    {
      key: "incoming",
      label: "Incoming Task",
      icon: "tasks",
      value: f ? String(f.incoming) : "—",
      caption: "queued",
      title: "Missions in QUEUED state",
    },
    {
      key: "routing",
      label: "Routing & Analysis",
      icon: "flow",
      value: f ? String(f.routing) : "—",
      caption: "starting",
      title: "Missions in STARTING state",
    },
    {
      key: "orch",
      label: "Orchestrator Assignment",
      icon: "planner",
      value: f ? String(f.orchestrators) : "—",
      caption: "orchestrators",
      title: "Fleet + system orchestrators available",
    },
    {
      key: "exec",
      label: "Agent Execution",
      icon: "coding",
      value: f ? String(f.executing) : "—",
      caption: "running",
      title: "Missions RUNNING or CANCELLING",
    },
    {
      key: "verify",
      label: "Verification & Evaluation",
      icon: "check",
      value: f?.verifying != null ? String(f.verifying) : dashboard ? formatPct(dashboard.performance.successRate) : "—",
      caption: f?.verifying != null ? "verifying" : "pass rate",
      title:
        f?.verifying != null
          ? "Running missions whose metadata marks verification"
          : "No verification stage traced — showing window success rate",
    },
    {
      key: "memory",
      label: "Memory Writeback",
      icon: "memory",
      value: f?.memoryWriteback != null ? String(f.memoryWriteback) : "—",
      caption: f?.memoryWriteback != null ? "memories" : "untraced",
      title: "MEMORY_CANDIDATE signals in window (null when Signal Fabric cannot attribute)",
    },
    {
      key: "done",
      label: "Completion",
      icon: "check",
      value: f ? String(f.completed) : "—",
      caption: dashboard ? `in ${dashboard.windowHours}h` : "",
      title: "Completed missions in the dashboard window",
    },
  ];

  return (
    <section className="lv-ag-panel lv-ag-flow">
      <PanelHead title="Orchestration Flow" right={<LiveBadge live={live} label={live ? "Live Flow" : "Stale"} />} />
      <ol className="lv-ag-flow-steps">
        {steps.map((s, i) => (
          <li key={s.key} className={`lv-ag-flow-step${s.value === "—" ? " is-null" : ""}`} title={s.title}>
            <Glyph kind={s.icon} className="lv-ag-flow-icon" />
            <span className="lv-ag-flow-label">{s.label}</span>
            <strong>{s.value}</strong>
            <small>{s.caption}</small>
            {i < steps.length - 1 ? <i className="lv-ag-flow-arrow" aria-hidden="true" /> : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
