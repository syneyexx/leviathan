import { useMemo } from "react";
import { formatElapsed } from "../../lib/jobStatus";
import type { AgentDefinition, AgentMission } from "../../types/api";
import {
  agentIconKind,
  agentMissionStats,
  agentOrigin,
  formatPct,
  healthLabel,
  isArchitectureEntry,
  statusTone,
} from "./helpers";
import { AgentIcon, PanelHead } from "./agentsUi";

export function ActiveAgentsPanel({
  agents,
  missions,
  selectedId,
  totalCount,
  query,
  showAll,
  onQuery,
  onToggleAll,
  onSelect,
}: {
  agents: AgentDefinition[];
  missions: AgentMission[];
  selectedId: string;
  totalCount: number;
  query: string;
  showAll: boolean;
  onQuery: (q: string) => void;
  onToggleAll: () => void;
  onSelect: (id: string) => void;
}) {
  const statsById = useMemo(() => {
    const out: Record<string, ReturnType<typeof agentMissionStats>> = {};
    for (const a of agents) out[a.agentId] = agentMissionStats(missions, a.agentId);
    return out;
  }, [agents, missions]);

  return (
    <section className="lv-ag-panel lv-ag-active">
      <PanelHead
        title="Active Agents"
        right={
          <>
            <input
              type="search"
              className="lv-ag-mini-search"
              placeholder="Search…"
              value={query}
              onChange={(e) => onQuery(e.target.value)}
              aria-label="Search agents"
            />
            <span className="lv-ag-count">
              {agents.length === totalCount ? `${totalCount} agents` : `${agents.length}/${totalCount}`}
            </span>
            <button type="button" className="lv-ag-link" onClick={onToggleAll}>
              {showAll ? "Fleet only" : "View All"} →
            </button>
          </>
        }
      />
      <div className="lv-ag-table-wrap">
        <table className="lv-ag-table is-dense">
          <thead>
            <tr>
              <th>Agent</th>
              <th>Role</th>
              <th>Model</th>
              <th>Status</th>
              <th className="is-num" title="Active / total missions">Tasks</th>
              <th className="is-num" title="Completed / (completed + failed)">Succ.</th>
              <th>Memory</th>
              <th className="is-num">Last run</th>
            </tr>
          </thead>
          <tbody>
            {agents.length === 0 ? (
              <tr>
                <td colSpan={8} className="lv-ag-empty">
                  {totalCount === 0 ? "No agents yet. Create one to begin." : "No agents match filters."}
                </td>
              </tr>
            ) : (
              agents.map((agent) => {
                const label = healthLabel(agent);
                const arch = isArchitectureEntry(agent);
                const st = statsById[agent.agentId];
                return (
                  <tr
                    key={agent.agentId}
                    className={selectedId === agent.agentId ? "is-selected" : ""}
                    onClick={() => onSelect(agent.agentId)}
                  >
                    <td>
                      <span className="lv-ag-cell-agent">
                        <span className="lv-ag-cell-icon" aria-hidden="true">
                          <svg viewBox="0 0 24 24">
                            <AgentIcon kind={agentIconKind(agent)} />
                          </svg>
                        </span>
                        <span className="lv-ag-cell-name" title={agent.name}>
                          {agent.name}
                        </span>
                        {agentOrigin(agent) === "system" ? <span className="lv-ag-sys">SYS</span> : null}
                      </span>
                    </td>
                    <td className="is-muted" title={agent.role || String(agent.kind)}>
                      {agent.role || String(agent.kind)}
                    </td>
                    <td className="is-model" title={agent.modelRef || "inherit / unset"}>
                      {arch ? "—" : agent.modelRef || "inherit"}
                    </td>
                    <td>
                      <span className={`lv-ag-chip is-${statusTone(label)}${label === "Busy" ? " is-busy" : ""}`}>
                        {label}
                      </span>
                    </td>
                    <td className="is-num">{arch ? "—" : `${st?.active ?? 0}/${st?.total ?? 0}`}</td>
                    <td className="is-num">{arch ? "—" : formatPct(st?.successRate ?? null, 0)}</td>
                    <td className="is-muted">{arch ? "—" : agent.memoryPolicy}</td>
                    <td className="is-num is-muted">{agent.lastRunAt ? formatElapsed(agent.lastRunAt) : "—"}</td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
}
