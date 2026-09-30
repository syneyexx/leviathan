import { useMemo } from "react";
import type { AgentsWorkspace } from "../../hooks/useAgentsWorkspace";
import { EmptyState, Panel, Badge } from "../ui";

type Props = { ws: AgentsWorkspace };

/**
 * Inter-agent / orchestration activity feed.
 * Uses real AgentEvent rows — never invents agent↔agent chat.
 */
export function AgentsActivityFeed({ ws }: Props) {
  const { events, agentNameById, live } = ws;

  const rows = useMemo(() => {
    return [...events]
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
      .slice(0, 14)
      .map((e) => {
        const cat = String(e.category || e.level || "event").toLowerCase();
        const tone =
          cat.includes("error") || e.level === "error"
            ? ("danger" as const)
            : cat.includes("delegat")
              ? ("info" as const)
              : cat.includes("analys") || cat.includes("evaluat")
                ? ("warning" as const)
                : cat.includes("data") || cat.includes("memory")
                  ? ("data" as const)
                  : ("system" as const);
        const label =
          cat.includes("delegat")
            ? "Delegatie"
            : cat.includes("signal")
              ? "Signal"
              : cat.includes("system")
                ? "Systeem"
                : cat.includes("analys")
                  ? "Analyse"
                  : cat.includes("evaluat")
                    ? "Evaluatie"
                    : cat.includes("data") || cat.includes("memory")
                      ? "Data"
                      : "Event";
        return {
          id: e.eventId,
          time: (e.createdAt || "").slice(11, 19) || "—",
          from: e.agentId ? agentNameById[e.agentId] || e.agentId.slice(0, 10) : "system",
          mission: e.missionId ? e.missionId.slice(0, 8) : null,
          message: e.message,
          tone,
          label,
        };
      });
  }, [events, agentNameById]);

  return (
    <Panel
      className="lv-v2-agents-feed"
      title="Agent Activiteit"
      meta={live ? "Live · events" : "Stale"}
    >
      {rows.length === 0 ? (
        <EmptyState title="Geen events" detail="AgentEvent / Signal Fabric feed is leeg." />
      ) : (
        <ul className="lv-v2-agents-feed__list">
          {rows.map((r) => (
            <li key={r.id}>
              <time>{r.time}</time>
              <div className="lv-v2-agents-feed__body">
                <strong>{r.from}</strong>
                {r.mission ? <span className="lv-v2-agents-feed__mission">→ {r.mission}</span> : null}
                <p title={r.message}>{r.message}</p>
              </div>
              <Badge tone={r.tone}>{r.label}</Badge>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
