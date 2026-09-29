import { Link } from "react-router-dom";
import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { Badge, Panel } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchAgentsPanel({ ws }: Props) {
  const rows = ws.agentRows;
  const scopeLabel =
    ws.workers.length > 0 ? "project workers" : ws.poolWorkers.length > 0 ? "Worker Fabric" : null;

  return (
    <Panel
      title="Onderzoeks Agenten"
      action={
        <Link className="lv-v2-brain-link" to="/agents">
          Alles bekijken
        </Link>
      }
    >
      {scopeLabel ? <p className="lv-v2-muted lv-v2-research-agents__scope">{scopeLabel}</p> : null}
      {ws.loading && rows.length === 0 ? (
        <p className="lv-v2-muted">Laden…</p>
      ) : rows.length === 0 ? (
        <p className="lv-v2-muted">Geen research workers beschikbaar in deze projectie.</p>
      ) : (
        <ul className="lv-v2-research-agents">
          {rows.slice(0, 6).map((row) => (
            <li key={row.id} className="lv-v2-research-agents__row">
              <span className="lv-v2-research-agents__ico" aria-hidden="true">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                  <rect x="6" y="8" width="12" height="10" rx="2" />
                  <path d="M12 4v4M9 12h.01M15 12h.01" />
                </svg>
              </span>
              <div className="lv-v2-research-agents__main">
                <strong>{row.name}</strong>
                <span>{row.expertise}</span>
              </div>
              <Badge tone={row.statusTone}>
                {row.statusTone === "success" ? "Beschikbaar" : row.status}
              </Badge>
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
