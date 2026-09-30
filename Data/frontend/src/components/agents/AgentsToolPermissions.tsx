import { useMemo } from "react";
import { Link } from "react-router-dom";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { assignedCapabilityCards } from "../../pages/agents/helpers";
import { Badge, EmptyState, Panel } from "../ui";

type Props = { ws: AgentsWorkspace };

/**
 * Tool permissions for the selected agent — capability assignment + registry
 * availability only. Never invents fractional Git 12/12 style counts.
 */
export function AgentsToolPermissions({ ws }: Props) {
  const { selectedAgent, capabilities } = ws;
  const caps = useMemo(
    () => assignedCapabilityCards(selectedAgent, capabilities),
    [selectedAgent, capabilities],
  );

  return (
    <Panel
      className="lv-v2-agents-perms"
      title="Tool Permissions"
      meta={selectedAgent ? selectedAgent.name : "—"}
      action={
        <div className="lv-v2-agents-inline-links">
          <Link to="/tools">Tools</Link>
          <Link to="/mcp">MCP</Link>
        </div>
      }
    >
      {!selectedAgent ? (
        <EmptyState title="Selecteer een agent" detail="Permissions volgen selectedAgent.capabilities." />
      ) : caps.length === 0 ? (
        <EmptyState
          title="Geen tools toegewezen"
          detail="Boolean capability assignment — geen neppe capaciteitsbreuken."
        />
      ) : (
        <ul className="lv-v2-agents-perm-list">
          {caps.map((c) => (
            <li key={c.id}>
              <div>
                <strong>{c.title}</strong>
                <small>{c.id}</small>
              </div>
              <Badge tone={c.available === false ? "warning" : "success"}>
                {c.available === false ? "unavailable" : "assigned"}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
