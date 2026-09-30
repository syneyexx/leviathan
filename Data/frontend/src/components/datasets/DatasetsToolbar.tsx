import {
  DH_FILTER_PILLS,
  DH_TYPE_OPTIONS,
  DH_UPDATED_OPTIONS,
} from "../../mocks/datasets-dashboard";
import { filterIcon } from "../../pages/datasets/datasetsMapping";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";

type Props = {
  ws: DatasetsWorkspace;
};

export function DatasetsToolbar({ ws }: Props) {
  return (
    <div className="lv-v2-ds-toolbar">
      <div className="lv-v2-ds-toolbar__actions">
        <button
          type="button"
          className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => ws.setModal("create")}
        >
          + Create Dataset
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => ws.setModal("import")}
        >
          Import Dataset
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => ws.setModal("hf")}
        >
          Connect Hugging Face
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => void ws.onProcessQueue()}
        >
          Process queue
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy || !ws.activeId}
          onClick={() => ws.activeId && void ws.onIndex(ws.activeId)}
        >
          Index embeddings
        </button>
      </div>

      <label className="lv-v2-ds-search">
        <span className="lv-sr-only">Search datasets</span>
        <input
          value={ws.query}
          onChange={(e) => ws.setQuery(e.target.value)}
          placeholder="Search datasets…"
          aria-label="Search datasets"
        />
      </label>

      <div className="lv-v2-ds-pills" role="tablist" aria-label="Dataset filters">
        {DH_FILTER_PILLS.map((pill) => (
          <button
            key={pill.id}
            type="button"
            role="tab"
            aria-selected={ws.filter === pill.id}
            className={`lv-v2-ds-pill${ws.filter === pill.id ? " is-active" : ""}`}
            onClick={() => ws.setFilter(pill.id)}
          >
            <span aria-hidden="true">{filterIcon(pill.icon)}</span>
            {pill.label}
            <span className="lv-v2-ds-pill__count">({ws.filterCounts[pill.id]})</span>
          </button>
        ))}
      </div>

      <div className="lv-v2-ds-toolbar__meta">
        <select
          className="lv-v2-select"
          value={ws.typeFilter}
          onChange={(e) => ws.setTypeFilter(e.target.value as typeof ws.typeFilter)}
          aria-label="Filter by type"
        >
          {DH_TYPE_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
        <select
          className="lv-v2-select"
          value={ws.updatedFilter}
          onChange={(e) => ws.setUpdatedFilter(e.target.value as typeof ws.updatedFilter)}
          aria-label="Filter by updated"
        >
          {DH_UPDATED_OPTIONS.map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
        <button
          type="button"
          className={`lv-v2-button lv-v2-button--ghost lv-v2-button--sm${ws.filtersOpen ? " is-active" : ""}`}
          aria-expanded={ws.filtersOpen}
          onClick={() => ws.setFiltersOpen((v) => !v)}
        >
          Filters
        </button>
        <div className="lv-v2-ds-view-toggle" role="group" aria-label="View mode">
          <button
            type="button"
            className={ws.view === "list" ? "is-active" : undefined}
            aria-pressed={ws.view === "list"}
            aria-label="List view"
            onClick={() => ws.setView("list")}
          >
            ☰
          </button>
          <button
            type="button"
            className={ws.view === "grid" ? "is-active" : undefined}
            aria-pressed={ws.view === "grid"}
            aria-label="Grid view"
            onClick={() => ws.setView("grid")}
          >
            ▦
          </button>
        </div>
      </div>
    </div>
  );
}
