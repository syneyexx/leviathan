import { Link } from "react-router-dom";
import type { ReactNode } from "react";
import { formatBytes, mapType, semanticOperatorLabel, statusLabel } from "../../pages/datasets/datasetsMapping";
import { seriesFromPreview } from "../../pages/datasets/previewSeries";
import { redactSecretUri, recoveryLabel, qualityLabel, previewSampleText, previewSampleTable } from "../../pages/datasets/viewModels";
import type { DatasetsWorkspace, DetailTab } from "../../pages/datasets/useDatasetsWorkspace";
import { DatasetActivityConsole } from "../../pages/datasets/DatasetActivityConsole";
import {
  learningStatusLabel,
  resolveLearningState,
} from "../../pages/datasets/datasetLearningState";
import { EmptyState, LoadingState } from "../ui";
import { exportPhaseLabel } from "../../pages/datasets/exportState";

type Props = {
  ws: DatasetsWorkspace;
};

const PRIMARY_TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "overview", label: "Overzicht" },
  { id: "quality", label: "Kwaliteit" },
  { id: "preview", label: "Voorbeeld" },
  { id: "versions", label: "Versies" },
  { id: "processing", label: "Verwerking" },
];

const MORE_TABS: Array<{ id: DetailTab; label: string }> = [
  { id: "semantics", label: "Semantiek" },
  { id: "learning", label: "Learning" },
  { id: "provenance", label: "Herkomst" },
  { id: "activity", label: "Activiteit" },
  { id: "advanced", label: "Geavanceerd" },
];

function MiniSeriesChart({ values, label, xLabel }: { values: number[]; label: string; xLabel: string }) {
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
  return (
    <div className="lv-v2-ds-series" aria-label={`Series preview: ${label} over ${xLabel}`}>
      <div className="lv-v2-ds-series__head">
        <strong>
          {label} <span className="lv-v2-muted">× {xLabel}</span>
        </strong>
        <span>{last.toLocaleString()}</span>
      </div>
      <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
        <polyline fill="none" stroke="#38bdf8" strokeWidth="2" points={pts} />
      </svg>
    </div>
  );
}

function ActionDisabled({ reason, children }: { reason: string | null; children: ReactNode }) {
  if (!reason) return <>{children}</>;
  return (
    <span title={reason} className="lv-v2-ds-action-disabled">
      {children}
    </span>
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

  const series = seriesFromPreview(ws.detailPreview);
  const columnsKnown =
    ws.detailPreview[0] != null ? Object.keys(ws.detailPreview[0]).length : null;
  const tags = ws.tagChips.length ? ws.tagChips : row.tags ?? record.semanticTags ?? [];
  const learning = resolveLearningState({
    learningState: record.learningState ?? null,
    brain: record.brain ?? null,
    brainStatus: record.brainStatus,
    learned: record.learned,
    canonicalState: record.canonicalState,
  });
  const learningLabel = learningStatusLabel(learning);
  const brainStatus = learning?.brainStatus ?? record.brainStatus ?? "—";
  const canonicalLabel =
    learning?.canonicalState ?? record.canonicalState ?? "UNKNOWN";
  const semanticLabel = semanticOperatorLabel(record);

  const needsVersion = !ws.selectedVersionId ? "Selecteer eerst een datasetversie" : null;

  const previewBody = (() => {
    if (ws.previewError) return <p className="lv-v2-warn">{ws.previewError}</p>;
    if (ws.detailPreview.length === 0) {
      return <EmptyState title="Geen voorbeeldrijen" detail="Bounded preview vereist een gematerialiseerde versie." />;
    }
    if (ws.sampleTab === "Tekst") {
      return <pre className="lv-v2-ds-preview">{previewSampleText(ws.detailPreview)}</pre>;
    }
    if (ws.sampleTab === "Tabel") {
      return <pre className="lv-v2-ds-preview">{previewSampleTable(ws.detailPreview)}</pre>;
    }
    return <pre className="lv-v2-ds-preview">{JSON.stringify(ws.detailPreview.slice(0, 12), null, 2)}</pre>;
  })();

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

      {ws.selectionOutsidePage ? (
        <p className="lv-v2-warn" role="status">
          Geselecteerde dataset staat buiten de huidige inventarisfilters/pagina — detail blijft synchroon.
        </p>
      ) : null}

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
          {MORE_TABS.map((tab) => (
            <button key={tab.id} type="button" onClick={() => ws.setDetailTab(tab.id)}>
              {tab.label}
            </button>
          ))}
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
            {series ? (
              <MiniSeriesChart values={series.values} label={series.label} xLabel={series.xLabel} />
            ) : null}
            <dl className="lv-v2-ds-kv">
              <div>
                <dt>SOURCE</dt>
                <dd>{row.source}</dd>
              </div>
              <div>
                <dt>DATASET</dt>
                <dd>
                  {mapType(record)} · {statusLabel(row.status)}
                </dd>
              </div>
              <div>
                <dt>VERSION</dt>
                <dd>
                  {ws.selectedVersion
                    ? `${ws.selectedVersion.versionLabel} (${ws.selectedVersion.kind})`
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>VALIDATION</dt>
                <dd>{qualityLabel(record.quality)}</dd>
              </div>
              <div>
                <dt>INDEX</dt>
                <dd>
                  {row.embeddings.kind === "indexing"
                    ? row.embeddings.pct >= 0
                      ? `Indexeren ${row.embeddings.pct}%`
                      : "Indexeren (UNMEASURED)"
                    : row.embeddings.kind.replace(/_/g, " ")}
                </dd>
              </div>
              <div>
                <dt>LEARNING</dt>
                <dd>
                  {learningLabel}
                  {learning?.stale ? " · STALE" : ""}
                  {learning?.error ? ` · ERROR` : ""}
                </dd>
              </div>
              <div>
                <dt>SEMANTICS</dt>
                <dd>{semanticLabel}</dd>
              </div>
              <div>
                <dt>Grootte / Records</dt>
                <dd>
                  {formatBytes(record.byteSize)} ·{" "}
                  {record.rowCount == null ? "—" : record.rowCount.toLocaleString()}
                  {columnsKnown == null ? "" : ` · ${columnsKnown} kolommen`}
                </dd>
              </div>
            </dl>
            <div className="lv-v2-ds-tags-block">
              <div className="lv-v2-ds-tags-head">
                <span>Tags</span>
              </div>
              <div className="lv-v2-ds-tags">
                {tags.length ? (
                  tags.map((t, i) => (
                    <button
                      key={`${t.toLowerCase()}-${i}`}
                      type="button"
                      className="lv-v2-ds-tag-chip"
                      onClick={() => ws.onRemoveTagChip(t)}
                      title="Verwijderen"
                    >
                      {t} ×
                    </button>
                  ))
                ) : (
                  <span className="lv-v2-muted">Geen tags</span>
                )}
              </div>
              <div className="lv-v2-ds-tag-edit">
                <input
                  value={ws.tagInput}
                  onChange={(e) => ws.setTagInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      ws.onAddTagChip();
                    }
                  }}
                  placeholder="tag toevoegen"
                  aria-label="Tag toevoegen"
                />
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || !ws.tagInput.trim()}
                  onClick={() => ws.onAddTagChip()}
                >
                  +
                </button>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy}
                  onClick={() => void ws.onSaveTags()}
                >
                  Opslaan
                </button>
              </div>
            </div>
          </>
        ) : null}

        {ws.detailTab === "quality" || ws.detailTab === "analyse" ? (
          <div className="lv-v2-ds-analyse">
            <dl className="lv-v2-ds-kv">
              <div>
                <dt>Quality</dt>
                <dd>
                  {record.quality?.measured
                    ? `${record.quality.score ?? "—"} (${record.quality.label})`
                    : "UNMEASURED"}
                </dd>
              </div>
              <div>
                <dt>Recovery</dt>
                <dd>{recoveryLabel(ws.recovery?.recoveryState ?? ws.recovery?.state)}</dd>
              </div>
            </dl>
            <div className="lv-v2-ds-action-row">
              <ActionDisabled reason={needsVersion}>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || Boolean(needsVersion)}
                  onClick={() => void ws.onValidate()}
                >
                  Valideren
                </button>
              </ActionDisabled>
              <ActionDisabled reason={needsVersion}>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || Boolean(needsVersion)}
                  onClick={() => void ws.onScanPii()}
                >
                  PII-scan
                </button>
              </ActionDisabled>
              <ActionDisabled reason={needsVersion}>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || Boolean(needsVersion)}
                  onClick={() => void ws.onDedupe()}
                >
                  Dedupliceren
                </button>
              </ActionDisabled>
              <ActionDisabled reason={needsVersion}>
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy || Boolean(needsVersion)}
                  onClick={() => void ws.onContaminationScan()}
                >
                  Contaminatie
                </button>
              </ActionDisabled>
            </div>
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              onClick={() => ws.openInAnalyse(row.id)}
            >
              Openen in Analyse
            </button>
          </div>
        ) : null}

        {ws.detailTab === "preview" ? (
          <>
            <div className="lv-v2-ds-sample-tabs" role="tablist">
              {(["JSON", "Tekst", "Tabel"] as const).map((t) => (
                <button
                  key={t}
                  type="button"
                  role="tab"
                  className={ws.sampleTab === t ? "is-active" : undefined}
                  onClick={() => ws.setSampleTab(t)}
                >
                  {t}
                </button>
              ))}
            </div>
            {previewBody}
          </>
        ) : null}

        {ws.detailTab === "versions" ? (
          ws.detailVersions.length === 0 ? (
            <EmptyState title="Geen versies" detail="Deze dataset heeft nog geen duurzame versies." />
          ) : (
            <ul className="lv-v2-ds-version-list">
              {ws.detailVersions.map((v) => (
                <li key={v.versionId}>
                  <button
                    type="button"
                    className={ws.selectedVersionId === v.versionId ? "is-active" : undefined}
                    onClick={() => ws.setSelectedVersionId(v.versionId)}
                  >
                    <strong>{v.versionLabel}</strong>
                    <span>{v.kind}</span>
                    <span>{v.status}</span>
                    <span>{formatBytes(v.byteSize)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )
        ) : null}

        {ws.detailTab === "processing" ? (
          <div className="lv-v2-ds-action-grid">
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onMaterialize()}>
              Materialiseren
            </button>
            <ActionDisabled reason={needsVersion}>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy || Boolean(needsVersion)} onClick={() => void ws.onValidate()}>
                Valideren
              </button>
            </ActionDisabled>
            <ActionDisabled reason={needsVersion}>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy || Boolean(needsVersion)} onClick={() => void ws.onDedupe()}>
                Dedupliceren
              </button>
            </ActionDisabled>
            <ActionDisabled reason={needsVersion}>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy || Boolean(needsVersion)} onClick={() => void ws.onTransform()}>
                Transformeren
              </button>
            </ActionDisabled>
            <ActionDisabled reason={needsVersion}>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy || Boolean(needsVersion)} onClick={() => void ws.onSplit()}>
                Splitsen
              </button>
            </ActionDisabled>
            <ActionDisabled reason={needsVersion}>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy || Boolean(needsVersion)} onClick={() => void ws.onTokenize()}>
                Tokenize stats
              </button>
            </ActionDisabled>
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onExportDownload(row.id)}>
              Exporteren
            </button>
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onIndex(row.id)}>
              Indexeren
            </button>
            <p className="lv-v2-muted">Export: {exportPhaseLabel(ws.exportState.phase)}</p>
            {ws.exportState.phase === "READY" ? (
              <button type="button" className="lv-v2-button lv-v2-button--primary lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onDownloadExport()}>
                Downloaden
              </button>
            ) : null}
          </div>
        ) : null}

        {ws.detailTab === "semantics" || ws.detailTab === "metadata" ? (
          <div className="lv-v2-ds-form">
            <p className="lv-v2-muted">
              Operator overrides vs model profile — opslaan schrijft canonical semantic metadata.
            </p>
            <label>
              Weergavenaam
              <input
                value={ws.editDisplayName}
                onChange={(e) => ws.setEditDisplayName(e.target.value)}
                disabled={!ws.semanticEditing && false}
              />
            </label>
            <label>
              Categorie
              <input value={ws.editCategory} onChange={(e) => ws.setEditCategory(e.target.value)} />
            </label>
            <pre className="lv-v2-ds-preview">
              {JSON.stringify(
                {
                  operator: { displayName: ws.editDisplayName, category: ws.editCategory, tags: ws.tagChips },
                  model: record.semanticProfile,
                },
                null,
                2,
              )}
            </pre>
            <div className="lv-v2-ds-action-row">
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onSemanticAnalyze(row.id, false)}>
                Analyse enqueue
              </button>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onSemanticAnalyze(row.id, true)}>
                Analyse sync
              </button>
              <button type="button" className="lv-v2-button lv-v2-button--primary lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onSaveSemantic()}>
                Metadata opslaan
              </button>
            </div>
          </div>
        ) : null}

        {ws.detailTab === "learning" ? (
          <div className="lv-v2-ds-analyse">
            <dl className="lv-v2-ds-kv">
              <div>
                <dt>Operator label</dt>
                <dd>{learningLabel}</dd>
              </div>
              <div>
                <dt>Brain status</dt>
                <dd>{String(brainStatus)}</dd>
              </div>
              <div>
                <dt>Canonical</dt>
                <dd>{String(canonicalLabel)}</dd>
              </div>
              <div>
                <dt>Usable index</dt>
                <dd>{learning?.usableIndexId || "—"}</dd>
              </div>
              <div>
                <dt>Semantic embeddings</dt>
                <dd>
                  {learning?.semanticEmbeddings == null
                    ? "—"
                    : learning.semanticEmbeddings
                      ? "active"
                      : "unavailable"}
                  {learning?.embeddingMode ? ` · ${learning.embeddingMode}` : ""}
                </dd>
              </div>
              <div>
                <dt>Source missing</dt>
                <dd>{record.sourceMissing || learning?.sourceMissing ? "Ja" : "Nee"}</dd>
              </div>
              {learning?.error ? (
                <div>
                  <dt>Error</dt>
                  <dd className="lv-v2-warn">{learning.error}</dd>
                </div>
              ) : null}
              {learning?.stale ? (
                <div>
                  <dt>Stale</dt>
                  <dd>Ja — stale job genegeerd t.o.v. READY index</dd>
                </div>
              ) : null}
            </dl>
            <div className="lv-v2-ds-action-row">
              <button type="button" className="lv-v2-button lv-v2-button--primary lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onLearn()}>
                Kennis leren
              </button>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onLearn({ rebuild: true })}>
                Rebuild
              </button>
              <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onPreflight()}>
                Preflight
              </button>
            </div>
            <Link className="lv-v2-ds-widget__link" to="/datasets?mode=learning">
              Learning fleet →
            </Link>
          </div>
        ) : null}

        {ws.detailTab === "provenance" ? (
          <dl className="lv-v2-ds-kv">
            <div>
              <dt>Source URI</dt>
              <dd className="lv-v2-ds-mono">{redactSecretUri(record.originalUri || record.rawPath)}</dd>
            </div>
            <div>
              <dt>Content hash</dt>
              <dd className="lv-v2-ds-mono">{record.contentHash || "—"}</dd>
            </div>
            <div>
              <dt>License</dt>
              <dd>{record.license || "—"}</dd>
            </div>
            <div>
              <dt>Recovery</dt>
              <dd>{recoveryLabel(ws.recovery?.recoveryState ?? ws.recovery?.state)}</dd>
            </div>
            <div>
              <dt>Lineage</dt>
              <dd className="lv-v2-ds-mono">
                {JSON.stringify(ws.recovery ?? { datasetId: record.datasetId }, null, 2).slice(0, 800)}
              </dd>
            </div>
          </dl>
        ) : null}

        {ws.detailTab === "activity" ? (
          <DatasetActivityConsole
            jobs={ws.detailJobs}
            entries={ws.detailActivityEntries}
            preferredJobId={ws.preferredJobId}
            onPreferredJobIdChange={ws.setPreferredJobId}
            apiError={ws.detailJobsError}
            live={ws.detailJobs.some((j) => ["running", "queued", "pending"].includes(j.status.toLowerCase()))}
            busy={ws.busy}
            onCancelJob={ws.onCancelDatasetJob}
            onClearView={ws.clearActivityView}
          />
        ) : null}

        {ws.detailTab === "advanced" ? (
          <div className="lv-v2-ds-action-grid">
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onDuplicate()}>
              Dupliceren
            </button>
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onRefreshLibrary()}>
              Library rescan
            </button>
            <button type="button" className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm" disabled={ws.busy} onClick={() => void ws.onPreflight()}>
              Recovery / preflight
            </button>
            <p className="lv-v2-muted">
              Recovery: {recoveryLabel(ws.recovery?.recoveryState ?? ws.recovery?.state)} —{" "}
              {ws.recovery?.detail || "geen extra diagnostiek"}
            </p>
            <p className="lv-v2-muted">Mixtures / packing: alleen via bestaande API-routes wanneer beschikbaar.</p>
          </div>
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
            onClick={() => ws.setModal("delete")}
          >
            Verwijderen
          </button>
        </div>
        <Link className="lv-v2-ds-widget__link" to="/datasets?mode=learning">
          Learning weergave →
        </Link>
      </footer>
    </aside>
  );
}
