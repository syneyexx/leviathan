import { useMemo, useState } from "react";
import type { AgentDefinition, AgentMissionLaunchPayload } from "../../types/api";
import { canLaunchAgent, healthLabel } from "./helpers";
import { Modal } from "./agentsUi";

export function LaunchMissionModal({
  agents,
  initialAgentId,
  agentsEnabled,
  busy,
  onLaunch,
  onClose,
}: {
  agents: AgentDefinition[];
  initialAgentId: string;
  agentsEnabled: boolean | undefined;
  busy: boolean;
  onLaunch: (agentId: string, payload: AgentMissionLaunchPayload) => void;
  onClose: () => void;
}) {
  const candidates = useMemo(
    () => agents.filter((a) => !a.archived && a.entityType !== "architecture"),
    [agents],
  );
  const [agentId, setAgentId] = useState(
    candidates.some((a) => a.agentId === initialAgentId)
      ? initialAgentId
      : (candidates.find((a) => canLaunchAgent(a, agentsEnabled).ok)?.agentId ?? ""),
  );
  const [title, setTitle] = useState("");
  const [requestText, setRequestText] = useState("");
  const [priority, setPriority] = useState<"low" | "med" | "high">("med");
  const [dryRun, setDryRun] = useState(false);
  const [useJobs, setUseJobs] = useState(false);

  const agent = candidates.find((a) => a.agentId === agentId);
  const gate = canLaunchAgent(agent, agentsEnabled);
  const canSubmit = gate.ok && requestText.trim().length > 0 && !busy;

  return (
    <Modal
      title="Launch Mission"
      onClose={onClose}
      footer={
        <>
          <span className="lv-ag-field-hint">
            {gate.ok ? "POST /api/agents/{id}/missions" : gate.reason}
          </span>
          <button
            type="button"
            className="lv-ag-btn-gold"
            disabled={!canSubmit}
            onClick={() =>
              onLaunch(agentId, {
                request: requestText.trim(),
                title: title.trim() || undefined,
                priority,
                dryRun,
                useJobs,
              })
            }
          >
            {dryRun ? "Plan (dry-run)" : "Launch / Deploy"}
          </button>
        </>
      }
    >
      <div className="lv-ag-editor-grid">
        <label className="lv-ag-field">
          <span>Agent</span>
          <select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            <option value="">Select an agent…</option>
            {candidates.map((a) => (
              <option key={a.agentId} value={a.agentId}>
                {a.name} · {a.kind} · {healthLabel(a)}
              </option>
            ))}
          </select>
        </label>
        <label className="lv-ag-field">
          <span>Task title (optional)</span>
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label className="lv-ag-field lv-ag-span-2">
          <span>Task request</span>
          <textarea
            rows={4}
            value={requestText}
            onChange={(e) => setRequestText(e.target.value)}
            placeholder="Describe the mission request"
          />
        </label>
        <div className="lv-ag-field">
          <span>Priority</span>
          <div className="lv-ag-seg">
            {(["low", "med", "high"] as const).map((p) => (
              <button
                key={p}
                type="button"
                className={priority === p ? "is-active" : ""}
                onClick={() => setPriority(p)}
              >
                {p}
              </button>
            ))}
          </div>
        </div>
        <div className="lv-ag-field">
          <span>Execution</span>
          <label className="lv-ag-check is-inline">
            <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} />
            <span>Dry-run plan only</span>
          </label>
          <label className="lv-ag-check is-inline">
            <input type="checkbox" checked={useJobs} onChange={(e) => setUseJobs(e.target.checked)} />
            <span>useJobs (durable job runtime)</span>
          </label>
        </div>
      </div>
    </Modal>
  );
}
