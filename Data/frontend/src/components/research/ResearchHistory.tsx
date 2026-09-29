import type { ResearchWorkspace } from "../../hooks/useResearchWorkspace";
import {
  depthLabelNl,
  relativeAgoNl,
  statusBadgeTone,
  statusLabelNl,
  type ResearchFilterTab,
} from "../../pages/research/researchHelpers";
import { Badge, Panel } from "../ui";

type Props = {
  ws: ResearchWorkspace;
};

const FILTERS: Array<{ id: ResearchFilterTab; label: string }> = [
  { id: "all", label: "Alle" },
  { id: "active", label: "Actief" },
  { id: "completed", label: "Afgerond" },
  { id: "drafts", label: "Concepten" },
];

export function ResearchHistory({ ws }: Props) {
  const {
    recentProjects,
    projectFilter,
    setProjectFilter,
    projectSearch,
    setProjectSearch,
    filterCounts,
    project,
    selectProject,
    showAllRecent,
    setShowAllRecent,
    loading,
  } = ws;

  return (
    <Panel
      className="lv-v2-research-history"
      title="Recente Onderzoeken"
      action={
        <button
          type="button"
          className="lv-v2-brain-link"
          onClick={() => setShowAllRecent(!showAllRecent)}
        >
          {showAllRecent ? "Toon minder" : "Alles bekijken"}
        </button>
      }
    >
      <div className="lv-v2-research-history__tools">
        <label className="lv-v2-research-search">
          <span className="lv-v2-sr-only">Zoek onderzoeken</span>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
            <circle cx="11" cy="11" r="7" />
            <path d="m20 20-3.5-3.5" />
          </svg>
          <input
            type="search"
            value={projectSearch}
            onChange={(e) => setProjectSearch(e.target.value)}
            placeholder="Zoek onderzoeken…"
          />
        </label>
        <div className="lv-v2-segmented" role="tablist" aria-label="Project filters">
          {FILTERS.map((f) => (
            <button
              key={f.id}
              type="button"
              role="tab"
              aria-selected={projectFilter === f.id}
              className={projectFilter === f.id ? "is-active" : undefined}
              onClick={() => setProjectFilter(f.id)}
            >
              {f.label}
              <span className="lv-v2-segmented__count">{filterCounts[f.id]}</span>
            </button>
          ))}
        </div>
      </div>

      {loading && recentProjects.length === 0 ? (
        <p className="lv-v2-muted">Laden…</p>
      ) : recentProjects.length === 0 ? (
        <p className="lv-v2-muted">Geen onderzoeken in deze filter.</p>
      ) : (
        <ul className="lv-v2-research-list">
          {recentProjects.map((p) => {
            const selected = project?.project_id === p.project_id;
            return (
              <li key={p.project_id}>
                <button
                  type="button"
                  className={`lv-v2-research-row${selected ? " is-selected" : ""}`}
                  aria-pressed={selected}
                  onClick={() => void selectProject(p.project_id)}
                >
                  <span className="lv-v2-research-row__ico" aria-hidden="true">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
                      <circle cx="12" cy="12" r="8" />
                      <path d="M12 8v4l3 2" />
                    </svg>
                  </span>
                  <span className="lv-v2-research-row__main">
                    <strong>{p.title || p.topic}</strong>
                    <em>{depthLabelNl(p.depth)}</em>
                  </span>
                  <Badge tone={statusBadgeTone(p.status)}>{statusLabelNl(p.status)}</Badge>
                  <time className="lv-v2-research-row__time">{relativeAgoNl(p.updated_at || p.created_at)}</time>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}
