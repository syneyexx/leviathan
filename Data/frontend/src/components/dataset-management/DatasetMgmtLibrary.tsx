import { PxIcon } from "../../pages/pixel/pixel-shared";
import { mapDatasetStatus, toneForDatasetStatus } from "../../pages/pixel/datasetStatus";
import {
  DM_CATEGORY_FILTERS,
  DM_SOURCE_FILTERS,
  DM_SPLIT_FILTERS,
  DM_STATUS_FILTERS,
  DM_TYPE_FILTERS,
} from "../../pages/dataset-management/constants";
import {
  categoryForDataset,
  displayNameForDataset,
  formatBytes,
  formatCompactCount,
  mapSourceLabel,
  mapTypeLabel,
  qualityLabel,
  qualityTone,
  splitLabelFromVersion,
  tagsForDataset,
  typeToneForLabel,
} from "../../pages/dataset-management/viewModels";
import type { DatasetRecord, DatasetVersion } from "../../types/api";

type Props = {
  loading: boolean;
  error: string | null;
  rows: DatasetRecord[];
  total: number;
  offset: number;
  pageSize: number;
  hasMore: boolean;
  onPageChange: (offset: number) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  selectedVersion: DatasetVersion | null | undefined;
  queryInput: string;
  onQueryChange: (v: string) => void;
  typeFilter: string;
  onTypeFilter: (v: string) => void;
  sourceFilter: string;
  onSourceFilter: (v: string) => void;
  categoryFilter: string;
  onCategoryFilter: (v: string) => void;
  splitFilter: string;
  onSplitFilter: (v: string) => void;
  statusFilter: string;
  onStatusFilter: (v: string) => void;
  onRetry: () => void;
};

export function DatasetMgmtLibrary({
  loading,
  error,
  rows,
  total,
  offset,
  pageSize,
  hasMore,
  onPageChange,
  selectedId,
  onSelect,
  selectedVersion,
  queryInput,
  onQueryChange,
  typeFilter,
  onTypeFilter,
  sourceFilter,
  onSourceFilter,
  categoryFilter,
  onCategoryFilter,
  splitFilter,
  onSplitFilter,
  statusFilter,
  onStatusFilter,
  onRetry,
}: Props) {
  const from = total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + rows.length, total);

  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-library" aria-label="Dataset bibliotheek">
      <div className="lv-v2-panel__head">
        <h3 className="lv-v2-panel__title">Dataset bibliotheek</h3>
        <span className="lv-v2-dm-muted">
          {loading ? "Laden…" : `${rows.length} zichtbaar op pagina · ${total} totaal`}
        </span>
      </div>

      <div className="lv-v2-dm-filters">
        <label className="lv-v2-dm-search">
          <PxIcon name="search" />
          <input
            className="lv-v2-input"
            value={queryInput}
            onChange={(e) => onQueryChange(e.target.value)}
            placeholder="Zoek datasets, tags, bronnen..."
            aria-label="Zoek datasets"
          />
        </label>
        <select className="lv-v2-select" value={typeFilter} onChange={(e) => onTypeFilter(e.target.value)}>
          {DM_TYPE_FILTERS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select className="lv-v2-select" value={sourceFilter} onChange={(e) => onSourceFilter(e.target.value)}>
          {DM_SOURCE_FILTERS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select className="lv-v2-select" value={categoryFilter} onChange={(e) => onCategoryFilter(e.target.value)}>
          {DM_CATEGORY_FILTERS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select className="lv-v2-select" value={splitFilter} onChange={(e) => onSplitFilter(e.target.value)}>
          {DM_SPLIT_FILTERS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
        <select className="lv-v2-select" value={statusFilter} onChange={(e) => onStatusFilter(e.target.value)}>
          {DM_STATUS_FILTERS.map((f) => (
            <option key={f} value={f}>{f}</option>
          ))}
        </select>
      </div>

      {error ? (
        <div className="lv-v2-error" role="alert">
          <strong>Datasets niet beschikbaar</strong>
          <p>{error}</p>
          <button type="button" className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm" onClick={onRetry}>
            Opnieuw proberen
          </button>
        </div>
      ) : null}

      <div className="lv-v2-dm-table-wrap">
        {loading ? (
          <p className="lv-v2-dm-muted lv-v2-dm-table-msg">Datasets laden…</p>
        ) : rows.length === 0 ? (
          <p className="lv-v2-dm-muted lv-v2-dm-table-msg">
            {total === 0 ? "Geen datasets. Upload of importeer om te beginnen." : "Geen datasets passen bij de filters."}
          </p>
        ) : (
          <table className="lv-v2-table lv-v2-dm-table">
            <thead>
              <tr>
                <th>Naam</th>
                <th>Categorie</th>
                <th>Type</th>
                <th>Bron</th>
                <th>Split</th>
                <th>Grootte</th>
                <th>Tokens</th>
                <th>Status</th>
                <th>Kwaliteit</th>
                <th>Tags</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const typeLabel = mapTypeLabel(row);
                const category = categoryForDataset(row) || "—";
                const statusNl = mapDatasetStatus(
                  row.status,
                  row.brainStatus ?? row.brain?.brainStatus,
                  row.canonicalState ?? row.learningState?.canonicalState ?? row.brain?.canonicalState,
                );
                const split =
                  row.datasetId === selectedId && selectedVersion
                    ? splitLabelFromVersion(selectedVersion)
                    : "—";
                const tokenHint =
                  row.datasetId === selectedId && selectedVersion?.tokenStats
                    ? formatCompactCount(
                        Number(
                          (selectedVersion.tokenStats as Record<string, unknown>).total_tokens ??
                            (selectedVersion.tokenStats as Record<string, unknown>).token_count,
                        ) || null,
                      )
                    : formatCompactCount(row.rowCount);
                const tags = tagsForDataset(row);
                return (
                  <tr
                    key={row.datasetId}
                    className={row.datasetId === selectedId ? "is-active" : ""}
                    onClick={() => onSelect(row.datasetId)}
                  >
                    <td><strong>{displayNameForDataset(row)}</strong></td>
                    <td><span className="lv-v2-dm-pill">{category}</span></td>
                    <td>
                      <span className={`lv-v2-dm-pill is-${typeToneForLabel(typeLabel)}`}>{typeLabel}</span>
                    </td>
                    <td>{mapSourceLabel(row.sourceType)}</td>
                    <td>{split}</td>
                    <td>{formatBytes(row.byteSize)}</td>
                    <td>{tokenHint}</td>
                    <td>
                      <span className={`lv-v2-dm-pill is-${toneForDatasetStatus(statusNl)}`}>{statusNl}</span>
                    </td>
                    <td>
                      <span className={`lv-v2-dm-pill is-${qualityTone(row.quality)}`}>{qualityLabel(row.quality)}</span>
                    </td>
                    <td>
                      <div className="lv-v2-dm-pills">
                        {tags.length === 0 ? (
                          <span className="lv-v2-dm-pill">—</span>
                        ) : (
                          tags.map((t) => (
                            <span key={t} className="lv-v2-dm-pill">{t}</span>
                          ))
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>

      <div className="lv-v2-dm-pager">
        <span className="lv-v2-dm-muted">
          {total === 0 ? "Geen resultaten" : `${from}–${to} van ${total}`}
        </span>
        <div className="lv-v2-dm-pager-buttons">
          <button
            type="button"
            className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
            disabled={loading || offset <= 0}
            onClick={() => onPageChange(Math.max(0, offset - pageSize))}
          >
            Vorige
          </button>
          <button
            type="button"
            className="lv-v2-button lv-v2-button--secondary lv-v2-button--sm"
            disabled={loading || !hasMore}
            onClick={() => onPageChange(offset + pageSize)}
          >
            Volgende
          </button>
        </div>
      </div>
    </section>
  );
}
