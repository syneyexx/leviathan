import { useMemo } from "react";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { Badge, Button, EmptyState, Panel, ProgressBar } from "../ui";

type Props = { ws: AgentsWorkspace };

const ACTIVE = new Set(["queued", "starting", "running", "cancelling", "waiting", "planning"]);

export function AgentsMissionsPanel({ ws }: Props) {
  const {
    missions,
    agentById,
    dashboard,
    busy,
    anyLaunchable,
    setLaunchOpen,
    selectMission,
    onCancelMission,
    selectedMissionId,
  } = ws;

  const pipeline = useMemo(() => {
    // Prefer dashboard flow counters when available — never invent phase %.
    const flow = dashboard?.flow;
    if (flow) {
      return [
        { id: "incoming", label: "Incoming", count: flow.incoming },
        { id: "routing", label: "Routing", count: flow.routing },
        { id: "orchestrators", label: "Orchestrators", count: flow.orchestrators },
        { id: "executing", label: "Executing", count: flow.executing },
        { id: "verifying", label: "Verifying", count: flow.verifying },
        { id: "completed", label: "Completed", count: flow.completed },
      ].filter((s) => s.count != null);
    }
    const byStatus: Record<string, number> = {};
    for (const m of missions) {
      byStatus[m.status] = (byStatus[m.status] || 0) + 1;
    }
    return Object.entries(byStatus)
      .slice(0, 6)
      .map(([status, count]) => ({ id: status, label: status, count }));
  }, [dashboard, missions]);

  const recent = useMemo(() => {
    return [...missions]
      .sort((a, b) => Date.parse(b.updatedAt || b.createdAt) - Date.parse(a.updatedAt || a.createdAt))
      .slice(0, 8);
  }, [missions]);

  return (
    <Panel
      className="lv-v2-agents-missions"
      title="Workflow Pipeline & Recente Missies"
      action={
        <Button
          variant="ghost"
          size="sm"
          disabled={!anyLaunchable || busy}
          onClick={() => setLaunchOpen(true)}
        >
          + New
        </Button>
      }
    >
      <div className="lv-v2-agents-missions__grid">
        <div>
          <h4 className="lv-v2-agents-section-title">Workflow Pipeline</h4>
          {pipeline.length === 0 ? (
            <EmptyState title="Geen pipeline data" detail="Missie/flow status nog niet beschikbaar." />
          ) : (
            <ol className="lv-v2-agents-pipeline">
              {pipeline.map((step, i) => (
                <li key={step.id}>
                  <span className="lv-v2-agents-pipeline__idx">{i + 1}</span>
                  <div className="lv-v2-agents-pipeline__body">
                    <strong>{step.label}</strong>
                    <span>{step.count} missies</span>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
        <div>
          <h4 className="lv-v2-agents-section-title">Recente Missies</h4>
          {recent.length === 0 ? (
            <EmptyState title="Geen missies" detail="Nog geen AgentMission records." />
          ) : (
            <ul className="lv-v2-agents-mission-list">
              {recent.map((m) => {
                const agent = agentById[m.agentId];
                const active = ACTIVE.has(m.status);
                const pct =
                  m.progress != null && Number.isFinite(m.progress) ? m.progress * 100 : null;
                return (
                  <li
                    key={m.missionId}
                    className={selectedMissionId === m.missionId ? "is-selected" : ""}
                  >
                    <button type="button" onClick={() => selectMission(m.missionId)}>
                      <strong title={m.title}>{m.title || m.missionId.slice(0, 10)}</strong>
                      <small>{agent?.name || m.agentId.slice(0, 10)}</small>
                      <ProgressBar value={pct} />
                      <span className="lv-v2-agents-mission-list__meta">
                        <Badge tone={active ? "info" : m.status === "completed" ? "success" : m.status === "failed" ? "danger" : "muted"}>
                          {m.status === "completed" ? "Voltooid" : m.status === "running" ? "Actief" : m.status}
                        </Badge>
                        <em>{pct != null ? `${Math.round(pct)}%` : "UNMEASURED"}</em>
                      </span>
                    </button>
                    {active ? (
                      <Button
                        variant="ghost"
                        size="sm"
                        disabled={busy}
                        onClick={() => void onCancelMission(m.missionId)}
                      >
                        Cancel
                      </Button>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Panel>
  );
}
