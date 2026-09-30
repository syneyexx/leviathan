import { Link } from "react-router-dom";
import { formatBytes, mapType, rowStatusLabel, statusLabel } from "../../pages/datasets/datasetsMapping";
import type { DatasetsWorkspace, DetailTab } from "../../pages/datasets/useDatasetsWorkspace";
import { EmptyState, LoadingState } from "../ui";

type Props = {
  ws: DatasetsWorkspace;
};

const PRIMARY_TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "overview", label: "Overzicht" },
  { id: "analyse", label: "Analyse" },
  { id: "preview", label: "Voorbeeld" },
  { id: "metadata", label: "Metadata" },
];

/** Detect numeric time-series columns from bounded preview — never invent BTC charts. */
function seriesFromPreview(rows: Array<Record<string, unknown>>): {
  values: number[];
  label: string;
} | null {
  if (!rows.length) return null;
  const keys = Object.keys(rows[0] ?? {});
  const numericKey = keys.find((k) =>
    rows.slice(0, 12).every((r) => {
      const v = r[k];
      return typeof v === "number" || (typeof v === "string" && v.trim() !== "" && !Number.isNaN(Number(v)));
    }),
  );
  if (!numericKey) return null;
  const values = rows
    .slice(0, 24)
    .map((r) => Number(r[numericKey]))
    .filter((n) => Number.isFinite(n));
  if (values.length < 3) return null;
  return { values, label: numericKey };
}

function MiniSeriesChart({ values, label }: { values: number[]; label: string }) {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(1e-9, max - min);
  const w = 220;
  const h = 56;
  const pts = values
    .map((v, i) => {
      const x = (i / Math.max(1, values.length - 1)) * w;
      const y = h - ((v - min) / span) * (h - 6) - 3;
      return `${x},${y}`;
    })
    .join(" ");
  const last = values[values.length - 1];
  const first = values[0];
  const delta = first !== 0 ? ((last - first) / Math.abs(first)) * 100 : null;
  return (
    <div className="lv-v2-ds-series" aria-label={`Series preview: ${label}`}>
      <div className="lv-v2-ds-series__head">
        <strong>{label}</strong>
        <span>
          {last.toLocaleString()}
          {delta != null ? (
            <em className={delta >= 0 ? "is-up" : "is-down"}>
              {" "}
              {delta >= 0 ? "+" : ""}
              {delta.toFixed(1)}%
            </em>
          ) : null}
        </span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
        <polyline fill="none" stroke="#38bdf8" strokeWidth="2" points={pts} />
      </svg>
    </div>
  );
}

export function DatasetsDetailPanel({ ws }: Props) {
  const row = ws.activeRow;
  const record = ws.activeRecord;

  if (!row || !record) {
    return (
      <aside className="lv-v2-panel lv-v2-ds-detail" aria-label="Dataset detail">
        <EmptyState title="Selecteer een dataset" detail="Kies een rij voor overzicht, analyse en voorbeeld." />
      </aside>
    );
  }

  const relatedJobs = ws.jobs.filter((j) => j.datasetId === record.datasetId).slice(0, 8);
  const tags = row.tags ?? record.semanticTags ?? [];
  const series = seriesFromPreview(ws.detailPreview);
  const columnsKnown =
    ws.detailPreview[0] != null ? Object.keys(ws.detailPreview[0]).length : null;

  return (
    <aside className="lv-v2-panel lv-v2-ds-detail" aria-label="Dataset detail">
      <header className="lv-v2-ds-detail__head">
        <div className="lv-v2-ds-detail__title-wrap">
          <span className="lv-v2-ds-detail__ico" aria-hidden="true">
            ▤
          </span>
          <div>
            <h3 className="lv-v2-ds-detail__title">{row.name}</h3>
            <p className="lv-v2-ds-detail__sub">{record.description || record.originalFilename || "—"}</p>
          </div>
        </div>
        <button
          type="button"
          className="lv-v2-ds-detail__close"
          aria-label="Selectie wissen"
          onClick={() => ws.setActiveId(null)}
        >
          ×
        </button>
      </header>

      <div className="lv-v2-ds-detail__tabs" role="tablist" aria-label="Dataset detail tabs">
        {PRIMARY_TABS.map((tab) => (
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
        <details className="lv-v2-ds-detail__more">
          <summary>Meer</summary>
          <button type="button" onClick={() => ws.setDetailTab("versions")}>
            Versies
          </button>
          <button type="button" onClick={() => ws.setDetailTab("activity")}>
            Activiteit
          </button>
          <button type="button" onClick={() => ws.setModal("health")}>
            Health
          </button>
        </details>
      </div>

      <div className="lv-v2-ds-detail__body">
        {ws.detailLoading ? <LoadingState label="Detail laden…" /> : null}
        {ws.detailError ? <p className="lv-v2-warn">{ws.detailError}</p> : null}

        {ws.detailTab === "overview" && !ws.detailLoading ? (
          <>
            {series ? <MiniSeriesChart values={series.values} label={series.label} /> : null}
            <dl className="lv-v2-ds-kv">
              <div>
                <dt>Type</dt>
                <dd>{mapType(record)}</dd>
              </div>
              <div>
                <dt>Bron</dt>
                <dd>{row.source}</dd>
              </div>
              <div>
                <dt>Grootte</dt>
                <dd>{formatBytes(record.byteSize)}</dd>
              </div>
              <div>
                <dt>Records</dt>
                <dd>{record.rowCount == null ? "—" : record.rowCount.toLocaleString()}</dd>
              </div>
              <div>
                <dt>Kolommen</dt>
                <dd>{columnsKnown == null ? "UNMEASURED" : columnsKnown}</dd>
              </div>
              <div>
                <dt>Bijgewerkt</dt>
                <dd>{row.updated}</dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>
                  <span className={`lv-v2-ds-status is-${row.status}`}>
                    <i aria-hidden="true" />
                    {rowStatusLabel(row)}
                  </span>
                </dd>
              </div>
              <div>
                <dt>Index</dt>
                <dd>
                  {row.embeddings.kind === "indexing"
                    ? row.embeddings.pct >= 0
                      ? `Indexeren ${row.embeddings.pct}%`
                      : "Indexeren (UNMEASURED)"
                    : row.embeddings.kind.replace(/_/g, " ")}
                </dd>
              </div>
              <div>
                <dt>Pad</dt>
                <dd className="lv-v2-ds-mono">{record.rawPath || record.originalUri || "—"}</dd>
              </div>
            </dl>
            <div className="lv-v2-ds-tags-block">
              <div className="lv-v2-ds-tags-head">
                <span>Tags</span>
              </div>
              <div className="lv-v2-ds-tags">
                {tags.length ? tags.map((t) => <span key={t}>{t}</span>) : <span className="lv-v2-muted">Geen tags</span>}
              </div>
              <div className="lv-v2-ds-tag-edit">
                <input
                  value={ws.tagDraft}
                  onChange={(e) => ws.setTagDraft(e.target.value)}
                  placeholder="tag1, tag2"
                  aria-label="Tags bewerken"
                />
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || !ws.tagDraft.trim()}
                  onClick={() => void ws.onSaveTags()}
                >
                  Opslaan
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.detailTab === "analyse" ? (
          <div className="lv-v2-ds-analyse">
            <p>
              Analyse opent de bestaande Research-surface met deze dataset-identiteit. Er is geen tweede
              analysis engine.
            </p>
            <dl className="lv-v2-ds-kv">
              <div>
                <dt>Semantic profile</dt>
                <dd>{record.semanticProfile?.summary || record.semanticProfile?.primaryCategory || "—"}</dd>
              </div>
              <div>
                <dt>Quality</dt>
                <dd>
                  {record.quality?.measured
                    ? `${record.quality.score ?? "—"} (${record.quality.label})`
                    : "UNMEASURED"}
                </dd>
              </div>
              <div>
                <dt>Status</dt>
                <dd>{statusLabel(row.status)}</dd>
              </div>
            </dl>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              onClick={() => ws.openInAnalyse(row.id)}
            >
              Openen in Analyse
            </button>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
              disabled={ws.busy}
              onClick={() => void ws.onSemanticAnalyze(row.id)}
            >
              Semantic analyse enqueue
            </button>
          </div>
        ) : null}

        {ws.detailTab === "preview" ? (
          ws.previewError ? (
            <p className="lv-v2-warn">{ws.previewError}</p>
          ) : ws.detailPreview.length === 0 ? (
            <EmptyState title="Geen voorbeeldrijen" detail="Bounded preview vereist een gematerialiseerde versie." />
          ) : (
            <pre className="lv-v2-ds-preview">{JSON.stringify(ws.detailPreview.slice(0, 12), null, 2)}</pre>
          )
        ) : null}

        {ws.detailTab === "versions" ? (
          ws.detailVersions.length === 0 ? (
            <EmptyState title="Geen versies" detail="Deze dataset heeft nog geen duurzame versies." />
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
            <EmptyState title="Geen jobs voor deze dataset" detail="Importeer, indexeer of verwerk om jobs te maken." />
          ) : (
            <ul className="lv-v2-ds-job-list">
              {relatedJobs.map((j) => (
                <li key={j.jobId}>
                  <strong>{j.jobType.replace(/_/g, " ")}</strong>
                  <span>{j.status}</span>
                  <span>{j.phase || "—"}</span>
                  <span>
                    {j.progress == null ? "progress UNMEASURED" : `${Math.round(j.progress * 100)}%`}
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
          className="lv-v2-button lv-v2-button--primary"
          onClick={() => ws.openInAnalyse(row.id)}
        >
          Openen in Analyse
        </button>
        <div className="lv-v2-ds-detail__foot-row">
          <div className="lv-v2-ds-dropdown" ref={ws.downloadMenuRef}>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
              disabled={ws.busy}
              aria-expanded={ws.downloadMenuOpen}
              onClick={() => ws.setDownloadMenuOpen((v) => !v)}
            >
              Downloaden ▾
            </button>
            {ws.downloadMenuOpen ? (
              <div className="lv-v2-ds-menu lv-v2-ds-menu--toolbar" role="menu">
                <button type="button" role="menuitem" onClick={() => void ws.onExportDownload(row.id)}>
                  Export / download
                </button>
              </div>
            ) : null}
          </div>
          <button
            type="button"
            className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
            onClick={() => void ws.onShareLink(row.id)}
          >
            Delen
          </button>
          <button
            type="button"
            className="lv-v2-button lv-v2-button--danger lv-v2-button--sm"
            disabled={ws.busy}
            onClick={() => void ws.onDelete(row.id)}
          >
            Verwijderen
          </button>
        </div>
        <Link className="lv-v2-ds-widget__link" to="/offline-datasets">
          Offline weergave →
        </Link>
      </footer>
    </aside>
  );
}
