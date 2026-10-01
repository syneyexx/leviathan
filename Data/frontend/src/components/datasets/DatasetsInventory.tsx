import { Link } from "react-router-dom";
import type { DhEmbedding, DhRow } from "../../pages/datasets/constants";
import { rowStatusLabel, sourceGlyph } from "../../pages/datasets/datasetsMapping";
import type { DatasetsWorkspace } from "../../pages/datasets/useDatasetsWorkspace";
import { EmptyState, LoadingState } from "../ui";

type Props = {
  ws: DatasetsWorkspace;
};

function typeClass(type: string): string {
  const t = type.toLowerCase();
  if (t.includes("tabel") || t.includes("struct")) return "structured";
  if (t.includes("doc")) return "document";
  if (t.includes("tekst") || t.includes("text")) return "text";
  if (t.includes("code")) return "code";
  if (t.includes("json")) return "code";
  if (t.includes("beeld") || t.includes("image") || t.includes("multi")) return "multimodal";
  return "text";
}

function statusClass(row: DhRow): string {
  if (row.embeddings.kind === "indexed" && row.status === "ready") return "ready";
  if (row.embeddings.kind === "indexing" || row.embeddings.kind === "queued") return "validating";
  return row.status;
}

function EmbeddingsHint({ emb }: { emb: DhEmbedding }) {
  if (emb.kind === "indexing") {
    const known = emb.pct >= 0;
    return (
      <span className="lv-sr-only">
        {known ? `Indexing ${emb.pct}%` : "Indexing (progress unmeasured)"}
      </span>
    );
  }
  return null;
}

function RowMenu({ row, ws }: { row: DhRow; ws: DatasetsWorkspace }) {
  if (ws.menuFor !== row.id) return null;
  return (
    <div className="lv-v2-ds-menu" ref={ws.menuRef} role="menu">
      <button type="button" role="menuitem" onClick={() => ws.openInAnalyse(row.id)}>
        Openen in Analyse
      </button>
      <button type="button" role="menuitem" onClick={() => void ws.onIndex(row.id)}>
        Indexeren
      </button>
      <button type="button" role="menuitem" onClick={() => void ws.onExportDownload(row.id)}>
        Downloaden / Exporteren
      </button>
      <Link role="menuitem" to="/datasets?mode=learning" onClick={() => ws.setMenuFor(null)}>
        Learning weergave
      </Link>
      <button
        type="button"
        role="menuitem"
        className="is-danger"
        onClick={() => void ws.onDelete(row.id)}
      >
        Verwijderen
      </button>
    </div>
  );
}

export function DatasetsInventory({ ws }: Props) {
  const allSelected =
    ws.filteredRows.length > 0 && ws.filteredRows.every((r) => ws.selectedIds.has(r.id));
  const col = (id: string) => ws.visibleColumns.has(id as never);

  if (ws.loading && ws.liveRows.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <LoadingState label="Datasets laden…" />
      </section>
    );
  }

  if (!ws.loading && !ws.error && ws.datasets.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <EmptyState
          title="Nog geen datasets"
          detail="Maak, upload of importeer een dataset om de inventaris te vullen."
        />
      </section>
    );
  }

  if (!ws.loading && ws.filteredRows.length === 0) {
    return (
      <section className="lv-v2-panel lv-v2-ds-inventory" aria-label="Datasets inventory" data-testid="datasets-inventory">
        <EmptyState title="Geen datasets matchen deze filters." detail="Pas zoekopdracht, type of periode aan." />
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
                <span className={`lv-v2-ds-status is-${statusClass(row)}`}>{rowStatusLabel(row)}</span>
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
              </div>
            </button>
          ))}
        </div>
        <Pagination ws={ws} />
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
                  aria-label="Selecteer alle zichtbare datasets"
                />
              </th>
              {col("name") ? <th>Naam</th> : null}
              {col("type") ? <th>Type</th> : null}
              {col("source") ? <th>Bron</th> : null}
              {col("size") ? <th>Grootte</th> : null}
              {col("records") ? <th>Records</th> : null}
              {col("status") ? <th>Status</th> : null}
              {col("updated") ? <th>Laatst gewijzigd</th> : null}
              {col("actions") ? <th>Acties</th> : null}
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
                    aria-label={`Selecteer ${row.name}`}
                  />
                </td>
                {col("name") ? (
                  <td>
                    <div className="lv-v2-ds-name">
                      <strong>{row.name}</strong>
                      <span>{row.description}</span>
                    </div>
                  </td>
                ) : null}
                {col("type") ? (
                  <td>
                    <span className={`lv-v2-ds-type is-${typeClass(row.type)}`}>{row.type}</span>
                  </td>
                ) : null}
                {col("source") ? (
                  <td>
                    <span className="lv-v2-ds-source">
                      <span className={`lv-v2-ds-source-ico is-${row.sourceKind}`} aria-hidden="true">
                        {sourceGlyph(row.sourceKind)}
                      </span>
                      {row.source}
                    </span>
                  </td>
                ) : null}
                {col("size") ? <td>{row.size}</td> : null}
                {col("records") ? <td>{row.records}</td> : null}
                {col("status") ? (
                  <td>
                    <span className={`lv-v2-ds-status is-${statusClass(row)}`}>
                      <i aria-hidden="true" />
                      {rowStatusLabel(row)}
                      <EmbeddingsHint emb={row.embeddings} />
                    </span>
                  </td>
                ) : null}
                {col("updated") ? <td>{row.updated}</td> : null}
                {col("actions") ? (
                  <td onClick={(e) => e.stopPropagation()} className="lv-v2-ds-actions-cell">
                    <button
                      type="button"
                      className="lv-v2-ds-icon-btn"
                      aria-label={`Open ${row.name}`}
                      title="Open detail"
                      onClick={() => ws.setActiveId(row.id)}
                    >
                      ⌕
                    </button>
                    <button
                      type="button"
                      className="lv-v2-ds-icon-btn"
                      aria-label={`Index ${row.name}`}
                      title="Indexeren"
                      onClick={() => void ws.onIndex(row.id)}
                    >
                      ◎
                    </button>
                    <button
                      type="button"
                      className="lv-v2-ds-icon-btn"
                      aria-label={`Analyse ${row.name}`}
                      title="Openen in Analyse"
                      onClick={() => ws.openInAnalyse(row.id)}
                    >
                      ⌁
                    </button>
                    <button
                      type="button"
                      className="lv-v2-ds-more"
                      aria-label={`Acties voor ${row.name}`}
                      aria-expanded={ws.menuFor === row.id}
                      onClick={() => ws.setMenuFor(ws.menuFor === row.id ? null : row.id)}
                    >
                      ⋯
                    </button>
                    <RowMenu row={row} ws={ws} />
                  </td>
                ) : null}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Pagination ws={ws} />
    </section>
  );
}

function Pagination({ ws }: { ws: DatasetsWorkspace }) {
  const total = ws.catalogTotal ?? ws.filteredRows.length;
  const from = total === 0 ? 0 : ws.offset + 1;
  const to = Math.min(ws.offset + ws.filteredRows.length, total);
  return (
    <div className="lv-v2-ds-pager" aria-label="Inventaris paginering">
      <span>
        {from}–{to} van {total}
        {ws.hasMore || ws.offset > 0 ? " (pagina)" : ""}
      </span>
      <div>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={ws.offset <= 0 || ws.busy}
          onClick={() => ws.goPage(Math.max(0, ws.offset - ws.pageSize))}
        >
          Vorige
        </button>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
          disabled={!ws.hasMore || ws.busy}
          onClick={() => ws.goPage(ws.offset + ws.pageSize)}
        >
          Volgende
        </button>
      </div>
    </div>
  );
}
