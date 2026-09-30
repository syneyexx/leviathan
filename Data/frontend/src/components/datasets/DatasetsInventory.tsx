import { Link } from "react-router-dom";
import type { DhEmbedding, DhRow } from "../../mocks/datasets-dashboard";
import { sourceGlyph, statusLabel } from "../../pages/datasets/datasetsMapping";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";
import { EmptyState, LoadingState } from "../ui";

type Props = {
  ws: DatasetsWorkspace;
};

function EmbeddingsCell({ emb }: { emb: DhEmbedding }) {
  if (emb.kind === "indexed") {
    return (
      <span className="lv-v2-ds-embed is-indexed">
        <i aria-hidden="true" />
        Indexed
      </span>
    );
  }
  if (emb.kind === "indexing") {
    const known = emb.pct >= 0;
    return (
      <div
        className="lv-v2-ds-embed-progress"
        aria-label={known ? `Indexing ${emb.pct}%` : "Indexing (progress unmeasured)"}
      >
        <span>{known ? `Indexing ${emb.pct}%` : "Indexing…"}</span>
        <div className={`lv-v2-ds-bar${known ? "" : " is-indeterminate"}`}>
          <i style={known ? { width: `${emb.pct}%` } : undefined} />
        </div>
      </div>
    );
  }
  const label =
    emb.kind === "not_indexed" ? "Not indexed" : emb.kind === "queued" ? "Queued" : "Pending";
  return <span className="lv-v2-ds-embed is-muted">{label}</span>;
}

function RowMenu({ row, ws }: { row: DhRow; ws: DatasetsWorkspace }) {
  if (ws.menuFor !== row.id) return null;
  return (
    <div className="lv-v2-ds-menu" ref={ws.menuRef} role="menu">
      <button type="button" role="menuitem" onClick={() => void ws.onIndex(row.id)}>
        Index embeddings
      </button>
      <Link
        role="menuitem"
        to="/offline-datasets"
        onClick={() => ws.setMenuFor(null)}
      >
        Open offline view
      </Link>
      <button
        type="button"
        role="menuitem"
        className="is-danger"
        onClick={() => void ws.onDelete(row.id)}
      >
        Delete
      </button>
    </div>
  );
}

export function DatasetsInventory({ ws }: Props) {
  const allSelected =
    ws.filteredRows.length > 0 && ws.filteredRows.every((r) => ws.selectedIds.has(r.id));

  if (ws.loading && ws.liveRows.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <LoadingState label="Loading datasets…" />
      </section>
    );
  }

  if (!ws.loading && !ws.error && ws.datasets.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <EmptyState
          title="No datasets yet"
          detail="Create, upload, or import a dataset to populate this inventory."
        />
      </section>
    );
  }

  if (!ws.loading && ws.filteredRows.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <EmptyState title="No datasets match these filters." detail="Adjust search, type, or updated filters." />
      </section>
    );
  }

  if (ws.view === "grid") {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <div className="lv-v2-ds-grid">
          {ws.filteredRows.map((row) => (
            <button
              key={row.id}
              type="button"
              className={`lv-v2-ds-card${ws.activeId === row.id ? " is-selected" : ""}`}
              onClick={() => ws.setActiveId(row.id)}
            >
              <div className="lv-v2-ds-card__top">
                <span className={`lv-v2-ds-status is-${row.status}`}>{statusLabel(row.status)}</span>
                <span className="lv-v2-ds-source">
                  <span className={`lv-v2-ds-source-ico is-${row.sourceKind}`}>{sourceGlyph(row.sourceKind)}</span>
                  {row.source}
                </span>
              </div>
              <strong>{row.name}</strong>
              <p>{row.description}</p>
              <div className="lv-v2-ds-card__meta">
                <span>{row.type}</span>
                <span>{row.size}</span>
                <span>{row.records}</span>
                <EmbeddingsCell emb={row.embeddings} />
              </div>
            </button>
          ))}
        </div>
      </section>
    );
  }

  return (
    <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
      <div className="lv-v2-ds-table-wrap">
        <table className="lv-v2-ds-table">
          <thead>
            <tr>
              <th>
                <input
                  type="checkbox"
                  className="lv-v2-ds-check"
                  checked={allSelected}
                  onChange={() => ws.toggleSelectAll()}
                  aria-label="Select all visible datasets"
                />
              </th>
              <th>Name</th>
              <th>Source</th>
              <th>Type</th>
              <th>Size</th>
              <th>Records</th>
              <th>Status</th>
              <th>Embeddings</th>
              <th>Last Updated</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {ws.filteredRows.map((row) => (
              <tr
                key={row.id}
                className={ws.activeId === row.id ? "is-selected" : undefined}
                onClick={() => ws.setActiveId(row.id)}
              >
                <td onClick={(e) => e.stopPropagation()}>
                  <input
                    type="checkbox"
                    className="lv-v2-ds-check"
                    checked={ws.selectedIds.has(row.id)}
                    onChange={() => ws.toggleSelected(row.id)}
                    aria-label={`Select ${row.name}`}
                  />
                </td>
                <td>
                  <div className="lv-v2-ds-name">
                    <strong>{row.name}</strong>
                    <span>{row.description}</span>
                  </div>
                </td>
                <td>
                  <span className="lv-v2-ds-source">
                    <span className={`lv-v2-ds-source-ico is-${row.sourceKind}`} aria-hidden="true">
                      {sourceGlyph(row.sourceKind)}
                    </span>
                    {row.source}
                  </span>
                </td>
                <td>
                  <span className={`lv-v2-ds-type is-${row.type.toLowerCase()}`}>{row.type}</span>
                </td>
                <td>{row.size}</td>
                <td>{row.records}</td>
                <td>
                  <span className={`lv-v2-ds-status is-${row.status}`}>
                    <i aria-hidden="true" />
                    {statusLabel(row.status)}
                  </span>
                </td>
                <td>
                  <EmbeddingsCell emb={row.embeddings} />
                </td>
                <td>{row.updated}</td>
                <td onClick={(e) => e.stopPropagation()} className="lv-v2-ds-actions-cell">
                  <button
                    type="button"
                    className="lv-v2-ds-more"
                    aria-label={`Actions for ${row.name}`}
                    aria-expanded={ws.menuFor === row.id}
                    onClick={() => ws.setMenuFor(ws.menuFor === row.id ? null : row.id)}
                  >
                    ⋯
                  </button>
                  <RowMenu row={row} ws={ws} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
