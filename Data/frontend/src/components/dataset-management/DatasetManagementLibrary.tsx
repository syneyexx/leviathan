import {
  DM_CATEGORY_FILTERS,
  DM_PAGE_COPY,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
} from "../../pages/datasets/datasetManagementConstants";
import {
  categoryForDataset,
  displayNameForDataset,
  formatBytes,
  mapSourceLabel,
  mapTypeLabel,
  qualityBars,
  splitLabelFromVersion,
  tagsForDataset,
  tokenHintForRow,
  typeToneForLabel,
} from "../../pages/datasets/datasetManagementFormat";
import { mapDatasetStatus, toneForDatasetStatus } from "../../pages/pixel/datasetStatus";
import type { DatasetManagementWorkspace } from "../../hooks/useDatasetManagementWorkspace";
import { DmIcon } from "./DatasetManagementIcons";

type Props = {
  ws: DatasetManagementWorkspace;
};

export function DatasetManagementLibrary({ ws }: Props) {
  const selectedVersion = ws.selectedVersion;

  return (
    <section className="lv-v2-panel lv-v2-dm-library" aria-label="Dataset bibliotheek">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Dataset bibliotheek</h3>
        <span className="lv-v2-panel__meta">
          {ws.libraryLoading || ws.loading
            ? "Laden…"
            : `${ws.datasets.length} zichtbaar · ${ws.libraryTotal} totaal`}
        </span>
      </div>
      <div className="lv-v2-panel__body">
        <div className="lv-v2-dm-filters">
          <label className="lv-v2-dm-search">
            <DmIcon name="search" />
            <input
              value={ws.query}
              onChange={(e) => ws.setQuery(e.target.value)}
              placeholder={DM_PAGE_COPY.searchPlaceholder}
              aria-label="Zoek datasets"
            />
          </label>
          <select
            className="lv-v2-select"
            value={ws.typeFilter}
            onChange={(e) => ws.setTypeFilter(e.target.value)}
            aria-label="Type filter"
          >
            {DM_TYPE_FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            className="lv-v2-select"
            value={ws.sourceFilter}
            onChange={(e) => ws.setSourceFilter(e.target.value)}
            aria-label="Bron filter"
          >
            {DM_SOURCE_FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            className="lv-v2-select"
            value={ws.categoryFilter}
            onChange={(e) => ws.setCategoryFilter(e.target.value)}
            aria-label="Categorie filter"
          >
            {DM_CATEGORY_FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            className="lv-v2-select"
            value={ws.splitFilter}
            onChange={(e) => ws.setSplitFilter(e.target.value)}
            aria-label="Split filter"
          >
            {DM_SPLIT_FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <select
            className="lv-v2-select"
            value={ws.statusFilter}
            onChange={(e) => ws.setStatusFilter(e.target.value)}
            aria-label="Status filter"
          >
            {DM_STATUS_FILTERS.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        </div>

        <div className="lv-v2-dm-table-wrap">
          {ws.loading && ws.datasets.length === 0 ? (
            <p className="lv-v2-dm-empty">Datasets laden…</p>
          ) : ws.datasets.length === 0 ? (
            <p className="lv-v2-dm-empty">
              {ws.libraryTotal === 0
                ? "Geen datasets. Upload of importeer om te beginnen."
                : "Geen datasets passen bij de filters."}
            </p>
          ) : (
            <table className="lv-v2-dm-table">
              <thead>
                <tr>
                  <th>Naam</th>
                  <th>Categorie</th>
                  <th>Type</th>
                  <th>Bron</th>
                  <th>Split</th>
                  <th>Grootte</th>
                  <th>Samples / Tokens</th>
                  <th>Status</th>
                  <th>Tags</th>
                  <th>Kwaliteit</th>
                </tr>
              </thead>
              <tbody>
                {ws.datasets.map((row) => {
                  const typeLabel = mapTypeLabel(row);
                  const category = categoryForDataset(row) || "Ongecategoriseerd";
                  const statusNl = mapDatasetStatus(
                    row.status,
                    row.brainStatus ?? row.brain?.brainStatus,
                    row.canonicalState ??
                      row.learningState?.canonicalState ??
                      row.brain?.canonicalState,
                  );
                  const isSelected = row.datasetId === ws.selectedId;
                  const split =
                    isSelected && selectedVersion
                      ? splitLabelFromVersion(selectedVersion)
                      : "—";
                  const tags = tagsForDataset(row);
                  const q = qualityBars(row);
                  const countHint = tokenHintForRow(row, selectedVersion, isSelected);
                  return (
                    <tr
                      key={row.datasetId}
                      className={isSelected ? "is-active" : undefined}
                      tabIndex={0}
                      aria-selected={isSelected}
                      onClick={() => ws.setSelectedId(row.datasetId)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          ws.setSelectedId(row.datasetId);
                        }
                      }}
                    >
                      <td>
                        <strong>{displayNameForDataset(row)}</strong>
                      </td>
                      <td>
                        <span className="lv-v2-dm-pill">{category}</span>
                      </td>
                      <td>
                        <span className={`lv-v2-dm-pill is-${typeToneForLabel(typeLabel)}`}>
                          {typeLabel}
                        </span>
                      </td>
                      <td>{mapSourceLabel(row.sourceType)}</td>
                      <td>{split}</td>
                      <td>{formatBytes(row.byteSize)}</td>
                      <td title={countHint.kind === "tokens" ? "Tokens" : countHint.kind === "samples" ? "Samples" : "Niet gemeten"}>
                        {countHint.value}
                        {countHint.kind === "tokens" ? (
                          <span className="lv-v2-dm-unit"> tok</span>
                        ) : countHint.kind === "samples" ? (
                          <span className="lv-v2-dm-unit"> smp</span>
                        ) : null}
                      </td>
                      <td>
                        <span className={`lv-v2-dm-pill is-${toneForDatasetStatus(statusNl)}`}>
                          {statusNl}
                        </span>
                      </td>
                      <td>
                        <div className="lv-v2-dm-pills">
                          {tags.length === 0 ? (
                            <span className="lv-v2-dm-pill">—</span>
                          ) : (
                            <>
                              {tags.slice(0, 3).map((t) => (
                                <button
                                  key={t}
                                  type="button"
                                  className="lv-v2-dm-pill"
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    ws.setTagFilter(t);
                                  }}
                                >
                                  {t}
                                </button>
                              ))}
                              {tags.length > 3 ? (
                                <span className="lv-v2-dm-pill">+{tags.length - 3}</span>
                              ) : null}
                            </>
                          )}
                        </div>
                      </td>
                      <td>
                        <span
                          className={`lv-v2-dm-quality${q.measured ? "" : " is-unmeasured"}`}
                          title={q.label}
                          aria-label={`Kwaliteit ${q.label}`}
                        >
                          {q.measured
                            ? Array.from({ length: 5 }).map((_, i) => (
                                <i
                                  key={i}
                                  className={q.bars != null && i < q.bars ? "is-on" : undefined}
                                />
                              ))
                            : "—"}
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
        {ws.libraryHasMore ? (
          <button
            type="button"
            className="lv-v2-dm-load-more"
            disabled={ws.libraryLoading}
            onClick={() => ws.loadMore()}
          >
            Meer laden
          </button>
        ) : null}
      </div>
    </section>
  );
}
