import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import { Panel } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

export function ResearchStats({ ws }: Props) {
  const max = Math.max(
    1,
    ...ws.stats7d.map((d) => d.completed + d.active + d.failed),
  );

  return (
    <Panel title="Onderzoeks Statistieken">
      <p className="lv-v2-muted lv-v2-research-stats__range">Laatste 7 dagen</p>
      <div className="lv-v2-research-chart" role="img" aria-label="Onderzoeksstatistieken laatste 7 dagen">
        {ws.stats7d.map((d) => {
          const total = d.completed + d.active + d.failed;
          const h = Math.round((total / max) * 100);
          const cH = total ? Math.round((d.completed / total) * h) : 0;
          const aH = total ? Math.round((d.active / total) * h) : 0;
          const fH = Math.max(0, h - cH - aH);
          return (
            <div key={d.day} className="lv-v2-research-chart__col">
              <div className="lv-v2-research-chart__stack" style={{ height: `${Math.max(h, 4)}%` }}>
                {fH > 0 ? <span className="is-failed" style={{ flex: fH }} /> : null}
                {aH > 0 ? <span className="is-active" style={{ flex: aH }} /> : null}
                {cH > 0 ? <span className="is-completed" style={{ flex: cH }} /> : null}
              </div>
              <em>{d.day}</em>
            </div>
          );
        })}
      </div>
      <ul className="lv-v2-research-chart__legend">
        <li><i className="is-completed" /> Afgerond</li>
        <li><i className="is-active" /> Actief</li>
        <li><i className="is-failed" /> Mislukt</li>
      </ul>
    </Panel>
  );
}
