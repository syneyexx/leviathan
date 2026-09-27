import type { AgentEvent } from "../../../types/api";

export function PaperTradingActivityLogPanel({ events }: { events: AgentEvent[] }) {
  return (
    <article className="lv-paper-panel lv-paper-activity">
      <header className="lv-paper-panel-head">
        <h2>Agent Activity Log</h2>
        <span className="lv-paper-muted">live</span>
      </header>
      {events.length === 0 ? (
        <p className="lv-paper-state">No agent activity yet.</p>
      ) : (
        <ul className="lv-paper-log">
          {events.slice(0, 40).map((e) => {
            const t = e.createdAt ? new Date(e.createdAt) : null;
            const hh = t
              ? t.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
              : "—";
            return (
              <li key={e.eventId}>
                <time>{hh}</time>
                <strong>{e.agentId || "system"}</strong>
                <span>{e.message || e.category}</span>
              </li>
            );
          })}
        </ul>
      )}
    </article>
  );
}
