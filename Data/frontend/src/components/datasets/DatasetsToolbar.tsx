import {
  DS_COLUMNS,
  DS_FILTER_PILLS,
  DS_TYPE_OPTIONS,
  DS_UPDATED_OPTIONS,
} from "../../pages/datasets/constants";
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
          + Nieuwe dataset
        </button>

        <div className="lv-v2-ds-dropdown" ref={ws.importMenuRef}>
          <button
            type="button"
            className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
            disabled={ws.busy}
            aria-expanded={ws.importMenuOpen}
            onClick={() => ws.setImportMenuOpen((v) => !v)}
          >
            Importeren ▾
          </button>
          {ws.importMenuOpen ? (
            <div className="lv-v2-ds-menu lv-v2-ds-menu--toolbar" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  ws.setImportMenuOpen(false);
                  ws.setModal("import");
                }}
              >
                Bestand uploaden
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  ws.setImportMenuOpen(false);
                  ws.setModal("import");
                }}
              >
                Lokaal pad
              </button>
            </div>
          ) : null}
        </div>

        <div className="lv-v2-ds-dropdown" ref={ws.externalMenuRef}>
          <button
            type="button"
            className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
            disabled={ws.busy}
            aria-expanded={ws.externalMenuOpen}
            onClick={() => ws.setExternalMenuOpen((v) => !v)}
          >
            Externe bron koppelen ▾
          </button>
          {ws.externalMenuOpen ? (
            <div className="lv-v2-ds-menu lv-v2-ds-menu--toolbar" role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  ws.setExternalMenuOpen(false);
                  ws.setModal("hf");
                }}
              >
                Hugging Face
              </button>
              <button type="button" role="menuitem" disabled title="Geen connector geconfigureerd">
                Overige bronnen (niet geconfigureerd)
              </button>
            </div>
          ) : null}
        </div>

        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy || !ws.canProcess}
          title={
            ws.canProcess
              ? "Materialiseer geselecteerde datasets"
              : "Selecteer datasets om te verwerken"
          }
          onClick={() => void ws.onBulkProcess()}
        >
          Verwerken
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => void ws.onBulkIndex()}
        >
          Indexeren
        </button>
      </div>

      <label className="lv-v2-ds-search">
        <span className="lv-sr-only">Zoek datasets</span>
        <input
          value={ws.queryInput}
          onChange={(e) => ws.setQueryInput(e.target.value)}
          placeholder="Zoek datasets..."
          aria-label="Zoek datasets"
        />
      </label>

      <div className="lv-v2-ds-pills" role="tablist" aria-label="Dataset filters">
        {DS_FILTER_PILLS.map((pill) => (
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
        <div className="lv-v2-ds-dropdown">
          <button
            type="button"
            className={`lv-v2-button lv-v2-button--ghost lv-v2-button--sm${ws.filtersOpen ? " is-active" : ""}`}
            aria-expanded={ws.filtersOpen}
            onClick={() => ws.setFiltersOpen((v) => !v)}
          >
            Filters
          </button>
          {ws.filtersOpen ? (
            <div className="lv-v2-ds-menu lv-v2-ds-menu--toolbar lv-v2-ds-filters-panel" role="group">
              <label>
                Type
                <select
                  className="lv-v2-select"
                  value={ws.typeFilter}
                  onChange={(e) => ws.setTypeFilter(e.target.value as typeof ws.typeFilter)}
                >
                  {DS_TYPE_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Bijgewerkt
                <select
                  className="lv-v2-select"
                  value={ws.updatedFilter}
                  onChange={(e) => ws.setUpdatedFilter(e.target.value as typeof ws.updatedFilter)}
                >
                  {DS_UPDATED_OPTIONS.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          ) : null}
        </div>

        <div className="lv-v2-ds-dropdown" ref={ws.columnsMenuRef}>
          <button
            type="button"
            className={`lv-v2-button lv-v2-button--ghost lv-v2-button--sm${ws.columnsOpen ? " is-active" : ""}`}
            aria-expanded={ws.columnsOpen}
            onClick={() => ws.setColumnsOpen((v) => !v)}
          >
            Kolommen
          </button>
          {ws.columnsOpen ? (
            <div className="lv-v2-ds-menu lv-v2-ds-menu--toolbar" role="menu">
              {DS_COLUMNS.map((col) => (
                <label key={col.id} className="lv-v2-ds-col-toggle">
                  <input
                    type="checkbox"
                    checked={ws.visibleColumns.has(col.id)}
                    disabled={col.id === "name"}
                    onChange={() => ws.toggleColumn(col.id)}
                  />
                  {col.label}
                </label>
              ))}
            </div>
          ) : null}
        </div>

        <div className="lv-v2-ds-view-toggle" role="group" aria-label="Weergave">
          <button
            type="button"
            className={ws.view === "list" ? "is-active" : undefined}
            aria-pressed={ws.view === "list"}
            aria-label="Lijstweergave"
            onClick={() => ws.setView("list")}
          >
            ☰
          </button>
          <button
            type="button"
            className={ws.view === "grid" ? "is-active" : undefined}
            aria-pressed={ws.view === "grid"}
            aria-label="Rasterweergave"
            onClick={() => ws.setView("grid")}
          >
            ▦
          </button>
        </div>
      </div>
    </div>
  );
}
