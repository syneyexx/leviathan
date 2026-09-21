import { Loader2 } from "lucide-react";
import { Panel, StatusBadge } from "@/components/hades/ui";
import { formatMetric, healthTone, statusTone, type AgentSortKey } from "@/lib/agents-console";
import { formatDate, type HadesAgent } from "@/lib/hades-api";
import { currentTaskLabel, dash } from "./helpers";

type AgentsListProps = {
  agents: HadesAgent[];
  visibleAgents: HadesAgent[];
  selectedId: string | undefined;
  loading: boolean;
  hasError: boolean;
  toolbar: React.ReactNode;
  onSelect: (agentId: string) => void;
  onSort: (key: AgentSortKey) => void;
};

export function AgentsList({
  agents,
  visibleAgents,
  selectedId,
  loading,
  hasError,
  toolbar,
  onSelect,
  onSort,
}: AgentsListProps) {
  return (
    <Panel className="overflow-hidden">
      {toolbar}
      <div className="table-scroll rounded-lg border border-border">
        <table className="data-table agents-table">
          <thead>
            <tr>
              <th><button type="button" className="sort-btn" onClick={() => onSort("name")}>Agent</button></th>
              <th><button type="button" className="sort-btn" onClick={() => onSort("status")}>Status</button></th>
              <th>Health</th>
              <th>Type</th>
              <th>Model / provider</th>
              <th>Huidige taak</th>
              <th><button type="button" className="sort-btn" onClick={() => onSort("tokens")}>Tokens</button></th>
              <th><button type="button" className="sort-btn" onClick={() => onSort("runs")}>Runs</button></th>
              <th><button type="button" className="sort-btn" onClick={() => onSort("failures")}>Fails</button></th>
              <th>Queue</th>
              <th><button type="button" className="sort-btn" onClick={() => onSort("last_activity")}>Laatste activiteit</button></th>
            </tr>
          </thead>
          <tbody>
            {loading && !agents.length ? (
              <tr><td colSpan={11}><div className="table-empty"><Loader2 className="spin muted-icon" /> Agents laden…</div></td></tr>
            ) : null}
            {visibleAgents.map((agent) => (
              <tr
                key={agent.id}
                className={agent.id === selectedId ? "selected-row clickable-row" : "clickable-row"}
                onClick={() => onSelect(agent.id)}
              >
                <td>
                  <strong>{agent.name}</strong>
                  <small>{agent.id}</small>
                </td>
                <td><StatusBadge tone={statusTone(agent.status)}>{agent.status_label || agent.status || "—"}</StatusBadge></td>
                <td><StatusBadge tone={healthTone(agent.health)}>{agent.health_label || agent.health || "—"}</StatusBadge></td>
                <td>{dash(agent.role)}</td>
                <td>
                  <strong>{dash(agent.model)}</strong>
                  <small>{dash(agent.provider)}</small>
                </td>
                <td className={agent.status === "error" ? "text-destructive" : undefined}>
                  <span className="line-clamp-2">{currentTaskLabel(agent)}</span>
                </td>
                <td className="tabular-nums">
                  {agent.usage?.known ? formatMetric(agent.usage.total_tokens, { compact: true }) : "—"}
                  <small>
                    in {agent.usage?.known ? formatMetric(agent.usage.input_tokens, { compact: true }) : "—"}
                    {" / "}
                    out {agent.usage?.known ? formatMetric(agent.usage.output_tokens, { compact: true }) : "—"}
                  </small>
                </td>
                <td className="tabular-nums">{agent.metrics?.runs ?? 0}</td>
                <td className="tabular-nums">{agent.metrics?.failed_runs ?? 0}</td>
                <td className="tabular-nums">{agent.queue?.pending ?? 0}</td>
                <td>{formatDate(agent.last_activity_at ?? null)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && !visibleAgents.length ? <div className="table-empty">Geen agents gevonden met deze filters.</div> : null}
        {!loading && !agents.length && !hasError ? <div className="table-empty">Nog geen agents geregistreerd in HADES.</div> : null}
      </div>
    </Panel>
  );
}
