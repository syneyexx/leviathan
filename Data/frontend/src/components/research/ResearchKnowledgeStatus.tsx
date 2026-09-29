import { Link } from "react-router-dom";
import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { Panel, ProgressBar } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchKnowledgeStatus({ ws }: Props) {
  return (
    <Panel
      title="Kennisbron Status"
      action={
        <Link className="lv-v2-brain-link" to="/knowledge">
          Alles bekijken
        </Link>
      }
    >
      <ul className="lv-v2-stat-list">
        {ws.knowledgeStatus.map((row) => (
          <li key={row.id} className="lv-v2-stat-list__row">
            <i
              className={`lv-v2-stat-list__dot lv-v2-stat-list__dot--${row.tone}`}
              aria-hidden="true"
            />
            <span className="lv-v2-stat-list__label">{row.label}</span>
            <strong className="lv-v2-stat-list__value">{row.value}</strong>
            {row.pct != null ? (
              <>
                <span className="lv-v2-stat-list__pct">{row.pct}%</span>
                <ProgressBar value={row.pct} />
              </>
            ) : null}
          </li>
        ))}
      </ul>
    </Panel>
  );
}
