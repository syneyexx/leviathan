import { Badge, Button, EmptyState } from "../ui";
import type { WorkflowDefinition } from "../../types/api";
import type { LibraryFilter, ViewMode } from "../../pages/workflows/useWorkflowsWorkspace";
import {
  definitionIsActive,
  formatRelativeNl,
  statusLabelNl,
} from "../../pages/workflows/useWorkflowsWorkspace";

type Props = {
  rows: WorkflowDefinition[];
  selectedId: string | null;
  query: string;
  onQuery: (q: string) => void;
  category: string;
  categories: string[];
  onCategory: (c: string) => void;
  filter: LibraryFilter;
  onFilter: (f: LibraryFilter) => void;
  counts: { all: number; active: number; inactive: number; templates: number };
  viewMode: ViewMode;
  onViewMode: (m: ViewMode) => void;
  nowMs: number;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRun: (id: string) => void;
  busy?: boolean;
};

export function WorkflowsLibrary({
  rows,
  selectedId,
  query,
  onQuery,
  category,
  categories,
  onCategory,
  filter,
  onFilter,
  counts,
  viewMode,
  onViewMode,
  nowMs,
  onSelect,
  onNew,
  onRun,
  busy,
}: Props) {
  return (
    <article className="lv-v2-panel lv-v2-wf-library" aria-label="Workflow bibliotheek">
      <div className="lv-v2-panel__head lv-v2-wf-library__head">
        <h3 className="lv-v2-panel__title">Workflows</h3>
        <div className="lv-v2-panel__action">
          <Button variant="primary" size="sm" onClick={onNew} disabled={busy}>
            + Nieuwe workflow
          </Button>
        </div>
      </div>

      <div className="lv-v2-wf-library__tools">
        <label className="lv-v2-wf-search">
          <span className="sr-only">Zoek workflows</span>
          <input
            type="search"
            placeholder="Zoek workflows..."
            value={query}
            onChange={(e) => onQuery(e.target.value)}
          />
        </label>
        <select
          className="lv-v2-wf-select"
          value={category}
          onChange={(e) => onCategory(e.target.value)}
          aria-label="Categorie"
        >
          <option value="all">Alle categorieën</option>
          {categories.map((c) => (
            <option key={c} value={c}>
              {c}
            </option>
          ))}
        </select>
        <div className="lv-v2-wf-view-toggle" role="group" aria-label="Weergave">
          <button
            type="button"
            className={viewMode === "list" ? "is-active" : ""}
            onClick={() => onViewMode("list")}
            aria-pressed={viewMode === "list"}
            title="Lijst"
          >
            ≡
          </button>
          <button
            type="button"
            className={viewMode === "grid" ? "is-active" : ""}
            onClick={() => onViewMode("grid")}
            aria-pressed={viewMode === "grid"}
            title="Grid"
          >
            ▦
          </button>
        </div>
      </div>

      <div className="lv-v2-wf-chips" role="tablist" aria-label="Status filter">
        {(
          [
            ["all", "Alle", counts.all],
            ["active", "Actief", counts.active],
            ["inactive", "Inactief", counts.inactive],
            ["templates", "Templates", counts.templates],
          ] as const
        ).map(([id, label, count]) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={filter === id}
            className={`lv-v2-wf-chip${filter === id ? " is-active" : ""}`}
            onClick={() => onFilter(id)}
          >
            {label} <span>({count})</span>
          </button>
        ))}
      </div>

      <div className={`lv-v2-wf-rows${viewMode === "grid" ? " is-grid" : ""}`}>
        {rows.length === 0 ? (
          <EmptyState title="Geen workflows" detail="Pas filters aan of maak een nieuwe workflow." />
        ) : (
          rows.map((row) => {
            const active = definitionIsActive(row.status);
            const selected = row.workflow_id === selectedId;
            return (
              <button
                key={row.workflow_id}
                type="button"
                className={`lv-v2-wf-row${selected ? " is-selected" : ""}`}
                onClick={() => onSelect(row.workflow_id)}
              >
                <span className="lv-v2-wf-row__check" aria-hidden="true">
                  <input type="checkbox" tabIndex={-1} readOnly checked={selected} />
                </span>
                <span className={`lv-v2-wf-row__icon is-${String(row.status).toLowerCase()}`} aria-hidden="true">
                  ⧉
                </span>
                <span className="lv-v2-wf-row__body">
                  <span className="lv-v2-wf-row__top">
                    <span className="lv-v2-wf-row__name">{row.name}</span>
                    <Badge tone={active ? "success" : row.status === "TEMPLATE" ? "info" : "danger"}>
                      {statusLabelNl(row.status)}
                    </Badge>
                  </span>
                  <span className="lv-v2-wf-row__desc">{row.description || row.category || "—"}</span>
                </span>
                <span className="lv-v2-wf-row__meta">
                  <time dateTime={row.updated_at}>{formatRelativeNl(row.updated_at, nowMs)}</time>
                  <span
                    className="lv-v2-wf-row__play"
                    role="presentation"
                    onClick={(e) => {
                      e.stopPropagation();
                      onRun(row.workflow_id);
                    }}
                    title="Uitvoeren"
                  >
                    ▶
                  </span>
                </span>
              </button>
            );
          })
        )}
      </div>
    </article>
  );
}
