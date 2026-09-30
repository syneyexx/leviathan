import { Link } from "react-router-dom";
import { formatBytes, mapType, statusLabel } from "../../pages/datasets/datasetsMapping";
import type { DatasetsWorkspace, DetailTab } from "../../pages/datasets/useDatasetsWorkspace";
import { EmptyState, LoadingState } from "../ui";

type Props = {
  ws: DatasetsWorkspace;
};

const TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "preview", label: "Preview" },
  { id: "versions", label: "Versions" },
  { id: "metadata", label: "Metadata" },
  { id: "activity", label: "Activity" },
];

export function DatasetsDetailPanel({ ws }: Props) {
  const row = ws.activeRow;
  const record = ws.activeRecord;

  if (!row || !record) {
    return (
      <aside className="lv-v2-panel lv-v2-ds-detail" aria-label="Dataset detail">
        <EmptyState title="Select a dataset" detail="Choose a row to inspect overview, preview, and versions." />
      </aside>
    );
  }

  const relatedJobs = ws.jobs.filter((j) => j.datasetId === record.datasetId).slice(0, 8);
  const tags = row.tags ?? record.semanticTags ?? [];

  return (
    <aside className="lv-v2-panel lv-v2-ds-detail" aria-label="Dataset detail">
      <header className="lv-v2-ds-detail__head">
        <div>
          <h3 className="lv-v2-ds-detail__title">{row.name}</h3>
          <p className="lv-v2-ds-detail__sub">{record.description || record.originalFilename || "—"}</p>
        </div>
        <button
          type="button"
          className="lv-v2-ds-detail__close"
          aria-label="Clear selection"
          onClick={() => ws.setActiveId(null)}
        >
          ×
        </button>
      </header>

      <div className="lv-v2-ds-detail__tabs" role="tablist" aria-label="Dataset detail tabs">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={ws.detailTab === tab.id}
            className={ws.detailTab === tab.id ? "is-active" : undefined}
            onClick={() => ws.setDetailTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="lv-v2-ds-detail__body">
        {ws.detailLoading ? <LoadingState label="Loading detail…" /> : null}
        {ws.detailError ? <p className="lv-v2-warn">{ws.detailError}</p> : null}

        {ws.detailTab === "overview" && !ws.detailLoading ? (
          <dl className="lv-v2-ds-kv">
            <div>
              <dt>Type</dt>
              <dd>{mapType(record)}</dd>
            </div>
            <div>
              <dt>Source</dt>
              <dd>{row.source}</dd>
            </div>
            <div>
              <dt>Size</dt>
              <dd>{formatBytes(record.byteSize)}</dd>
            </div>
            <div>
              <dt>Records</dt>
              <dd>{record.rowCount == null ? "—" : record.rowCount.toLocaleString()}</dd>
            </div>
            <div>
              <dt>Format</dt>
              <dd>{record.detectedFormat || "—"}</dd>
            </div>
            <div>
              <dt>Updated</dt>
              <dd>{row.updated}</dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <span className={`lv-v2-ds-status is-${row.status}`}>
                  <i aria-hidden="true" />
                  {statusLabel(row.status)}
                </span>
              </dd>
            </div>
            <div>
              <dt>Embeddings</dt>
              <dd>
                {row.embeddings.kind === "indexing"
                  ? row.embeddings.pct >= 0
                    ? `Indexing ${row.embeddings.pct}%`
                    : "Indexing (unmeasured)"
                  : row.embeddings.kind.replace(/_/g, " ")}
              </dd>
            </div>
            <div>
              <dt>Path</dt>
              <dd className="lv-v2-ds-mono">{record.rawPath || record.originalUri || "—"}</dd>
            </div>
            {tags.length ? (
              <div className="lv-v2-ds-kv--tags">
                <dt>Tags</dt>
                <dd>
                  <div className="lv-v2-ds-tags">
                    {tags.map((t) => (
                      <span key={t}>{t}</span>
                    ))}
                  </div>
                </dd>
              </div>
            ) : null}
          </dl>
        ) : null}

        {ws.detailTab === "preview" ? (
          ws.previewError ? (
            <p className="lv-v2-warn">{ws.previewError}</p>
          ) : ws.detailPreview.length === 0 ? (
            <EmptyState title="No preview rows" detail="Bounded preview requires a materialised version." />
          ) : (
            <pre className="lv-v2-ds-preview">
              {JSON.stringify(ws.detailPreview.slice(0, 12), null, 2)}
            </pre>
          )
        ) : null}

        {ws.detailTab === "versions" ? (
          ws.detailVersions.length === 0 ? (
            <EmptyState title="No versions" detail="This dataset has no durable versions yet." />
          ) : (
            <ul className="lv-v2-ds-version-list">
              {ws.detailVersions.map((v) => (
                <li key={v.versionId}>
                  <strong>{v.versionLabel}</strong>
                  <span>{v.kind}</span>
                  <span>{v.status}</span>
                  <span>{formatBytes(v.byteSize)}</span>
                </li>
              ))}
            </ul>
          )
        ) : null}

        {ws.detailTab === "metadata" ? (
          <pre className="lv-v2-ds-preview">
            {JSON.stringify(
              {
                datasetId: record.datasetId,
                name: record.name,
                sourceType: record.sourceType,
                status: record.status,
                license: record.license,
                contentHash: record.contentHash,
                semanticProfile: record.semanticProfile,
                metadata: record.metadata,
              },
              null,
              2,
            )}
          </pre>
        ) : null}

        {ws.detailTab === "activity" ? (
          relatedJobs.length === 0 ? (
            <EmptyState title="No jobs for this dataset" detail="Import, index, or process to create jobs." />
          ) : (
            <ul className="lv-v2-ds-job-list">
              {relatedJobs.map((j) => (
                <li key={j.jobId}>
                  <strong>{j.jobType.replace(/_/g, " ")}</strong>
                  <span>{j.status}</span>
                  <span>{j.phase || "—"}</span>
                  <span>
                    {j.progress == null ? "progress unmeasured" : `${Math.round(j.progress * 100)}%`}
                  </span>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>

      <footer className="lv-v2-ds-detail__foot">
        <button
          type="button"
          className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => void ws.onIndex(row.id)}
        >
          Index embeddings
        </button>
        <Link className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" to="/offline-datasets">
          Offline view
        </Link>
        <button
          type="button"
          className="lv-v2-button lv-v2-button--danger lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => void ws.onDelete(row.id)}
        >
          Delete
        </button>
      </footer>
    </aside>
  );
}
