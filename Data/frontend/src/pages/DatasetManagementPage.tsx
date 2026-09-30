/**
 * Leviathan V2 Dataset Management — canonical `/dataset-management`.
 * LLM → Dataset Management operator control plane. No page-local CSS.
 * Screen 1 visual reference: docs/ui_reference/dataset-management-llm-v2-reference.png
 */

import { DatasetActivityConsole } from "./datasets/DatasetActivityConsole";
import { DatasetMgmtActions } from "../components/dataset-management/DatasetMgmtActions";
import { DatasetMgmtDetails } from "../components/dataset-management/DatasetMgmtDetails";
import { DatasetMgmtHero } from "../components/dataset-management/DatasetMgmtHero";
import { DatasetMgmtLibrary } from "../components/dataset-management/DatasetMgmtLibrary";
import { DatasetMgmtMetrics } from "../components/dataset-management/DatasetMgmtMetrics";
import { DatasetMgmtPreview } from "../components/dataset-management/DatasetMgmtPreview";
import { DatasetMgmtSemanticSummary } from "../components/dataset-management/DatasetMgmtSemanticSummary";
import { DatasetMgmtServices } from "../components/dataset-management/DatasetMgmtServices";
import { DatasetMgmtStorage } from "../components/dataset-management/DatasetMgmtStorage";
import { AppShell } from "../layouts/AppShell";
import { DM_PAGE_SIZE, DM_UPLOAD_ACCEPT } from "./dataset-management/constants";
import { displayNameForDataset } from "./dataset-management/viewModels";
import { useDatasetManagementWorkspace } from "./dataset-management/useDatasetManagementWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function DatasetManagementPage() {
  const ws = useDatasetManagementWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="LLM / Dataset Management"
      v2Subtitle="Datasetbeheer, import, validatie, semantische verrijking en training workflows."
      v2Online={!ws.error}
      v2Refreshing={ws.loading || ws.overviewLoading}
      onV2Refresh={() => {
        void ws.loadPage({ quiet: true });
        void ws.loadOverview({ quiet: true });
        void ws.refreshJobs();
      }}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={
        <button
          type="button"
          className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
          disabled={ws.busy}
          onClick={() => void ws.onSidebarAction("upload")}
        >
          + Dataset toevoegen
        </button>
      }
    >
      <main className="lv-v2-page lv-v2-page--dataset-mgmt">
        <input
          ref={ws.uploadRef}
          type="file"
          accept={DM_UPLOAD_ACCEPT}
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0] ?? null;
            e.target.value = "";
            void ws.onUploadFile(file);
          }}
        />

        {ws.error && ws.datasets.length > 0 ? (
          <p className="lv-v2-warn" role="status">
            Stale — vernieuwen mislukt; laatste goede snapshot behouden. {ws.error}
          </p>
        ) : null}

        <DatasetMgmtHero onAddDataset={() => void ws.onSidebarAction("upload")} />

        <DatasetMgmtMetrics
          overview={ws.overview}
          loading={ws.overviewLoading && !ws.overview}
          error={ws.overviewError}
        />

        <section className="lv-v2-dm-workspace" aria-label="Dataset Management werkruimte">
          <div className="lv-v2-dm-left">
            <DatasetMgmtActions
              selectedCount={ws.selectedId ? 1 : 0}
              busy={ws.busy}
              exportReady={Boolean(ws.exportArtifact)}
              exportCount={ws.exportVersionCount}
              actionDisabledReason={ws.actionDisabledReason}
              onAction={(id) => void ws.onSidebarAction(id)}
              onDownloadExport={() => void ws.onDownloadExport()}
            />
            <DatasetMgmtServices
              services={ws.overview?.services ?? []}
              loading={ws.overviewLoading && !ws.overview}
            />
          </div>

          <div className="lv-v2-dm-center">
            <DatasetMgmtLibrary
              loading={ws.loading}
              error={ws.error}
              rows={ws.filtered}
              total={ws.total}
              offset={ws.offset}
              pageSize={ws.pageSize || DM_PAGE_SIZE}
              hasMore={ws.hasMore}
              onPageChange={ws.goToPage}
              selectedId={ws.selectedId}
              onSelect={ws.setSelectedId}
              selectedVersion={ws.selectedVersion}
              queryInput={ws.queryInput}
              onQueryChange={ws.setQueryInput}
              typeFilter={ws.typeFilter}
              onTypeFilter={ws.setTypeFilter}
              sourceFilter={ws.sourceFilter}
              onSourceFilter={ws.setSourceFilter}
              categoryFilter={ws.categoryFilter}
              onCategoryFilter={ws.setCategoryFilter}
              splitFilter={ws.splitFilter}
              onSplitFilter={ws.setSplitFilter}
              statusFilter={ws.statusFilter}
              onStatusFilter={ws.setStatusFilter}
              onRetry={() => void ws.loadPage({ offset: 0 })}
            />
            <div className="lv-v2-dm-activity">
              <DatasetActivityConsole
                jobs={ws.jobs}
                entries={ws.activityEntries}
                preferredJobId={ws.preferredJobId}
                onPreferredJobIdChange={ws.setPreferredJobId}
                apiError={ws.jobsError}
                live={ws.live}
                busy={ws.busy}
                onCancelJob={(id) => void ws.onCancelDatasetJob(id)}
                onClearView={ws.clearActivityView}
              />
            </div>
          </div>

          <div className="lv-v2-dm-right">
            <DatasetMgmtDetails ws={ws} />
            <DatasetMgmtSemanticSummary ws={ws} />
            <DatasetMgmtPreview ws={ws} />
            <DatasetMgmtStorage
              overview={ws.overview}
              loading={ws.overviewLoading && !ws.overview}
            />
            <DatasetMgmtTagsPanel
              overview={ws.overview}
              loading={ws.overviewLoading && !ws.overview}
              onTagClick={ws.applyTagFilter}
            />
          </div>
        </section>

        {ws.modal ? (
          <div
            className="lv-v2-dm-modal-backdrop"
            role="presentation"
            onClick={() => !ws.busy && ws.setModal(null)}
          >
            <div
              className="lv-v2-dm-modal"
              role="dialog"
              aria-modal="true"
              aria-labelledby="dm-modal-title"
              onClick={(e) => e.stopPropagation()}
            >
              {ws.modal === "create" ? (
                <>
                  <h2 id="dm-modal-title">Nieuwe dataset</h2>
                  <p>Maak een lege catalogus-shell in DatasetService. Geen nep-rijen.</p>
                  <div className="lv-v2-dm-form">
                    <label className="lv-v2-dm-field">
                      Naam
                      <input
                        className="lv-v2-input"
                        value={ws.createName}
                        onChange={(e) => ws.setCreateName(e.target.value)}
                        placeholder="mijn-corpus"
                      />
                    </label>
                    <label className="lv-v2-dm-field">
                      Beschrijving
                      <textarea
                        className="lv-v2-input"
                        value={ws.createDesc}
                        onChange={(e) => ws.setCreateDesc(e.target.value)}
                      />
                    </label>
                    <label className="lv-v2-dm-field">
                      Licentie (optioneel)
                      <input
                        className="lv-v2-input"
                        value={ws.createLicense}
                        onChange={(e) => ws.setCreateLicense(e.target.value)}
                        placeholder="MIT"
                      />
                    </label>
                    <div className="lv-v2-dm-modal-actions">
                      <button type="button" className="lv-v2-button lv-v2-button--secondary" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                        Annuleren
                      </button>
                      <button
                        type="button"
                        className="lv-v2-button lv-v2-button--primary"
                        disabled={ws.busy || !ws.createName.trim()}
                        onClick={() => void ws.onCreateSubmit()}
                      >
                        Aanmaken
                      </button>
                    </div>
                  </div>
                </>
              ) : null}

              {ws.modal === "local" ? (
                <>
                  <h2 id="dm-modal-title">Lokale bestanden importeren</h2>
                  <p>Alleen paden binnen allowlisted roots. Geen willekeurige systeempaden.</p>
                  <div className="lv-v2-dm-form">
                    <label className="lv-v2-dm-field">
                      Pad
                      <input
                        className="lv-v2-input"
                        value={ws.localPath}
                        onChange={(e) => ws.setLocalPath(e.target.value)}
                        placeholder="/data/corpus.jsonl"
                      />
                    </label>
                    <label className="lv-v2-dm-field">
                      Optionele naam
                      <input className="lv-v2-input" value={ws.localName} onChange={(e) => ws.setLocalName(e.target.value)} />
                    </label>
                    <label className="lv-v2-dm-field">
                      Optionele beschrijving
                      <textarea className="lv-v2-input" value={ws.localDesc} onChange={(e) => ws.setLocalDesc(e.target.value)} />
                    </label>
                    <div className="lv-v2-dm-modal-actions">
                      <button type="button" className="lv-v2-button lv-v2-button--secondary" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                        Annuleren
                      </button>
                      <button
                        type="button"
                        className="lv-v2-button lv-v2-button--primary"
                        disabled={ws.busy || !ws.localPath.trim()}
                        onClick={() => void ws.onLocalSubmit()}
                      >
                        Importeren
                      </button>
                    </div>
                  </div>
                </>
              ) : null}

              {ws.modal === "hf" ? (
                <>
                  <h2 id="dm-modal-title">Importeren (Hugging Face)</h2>
                  <p>
                    Token wordt niet in dataset-metadata, jobconfig, URL of localStorage bewaard.
                    Bulk transfer draait op de dataset worker.
                  </p>
                  <div className="lv-v2-dm-form">
                    <label className="lv-v2-dm-field">
                      Repository ID
                      <input className="lv-v2-input" value={ws.hfRepo} onChange={(e) => ws.setHfRepo(e.target.value)} placeholder="owner/dataset" />
                    </label>
                    <label className="lv-v2-dm-field">
                      Revision
                      <input className="lv-v2-input" value={ws.hfRevision} onChange={(e) => ws.setHfRevision(e.target.value)} placeholder="main" />
                    </label>
                    <label className="lv-v2-dm-field">
                      Bestandsnaam (optioneel — leeg = volledige repo)
                      <input className="lv-v2-input" value={ws.hfFilename} onChange={(e) => ws.setHfFilename(e.target.value)} />
                    </label>
                    <label className="lv-v2-dm-field">
                      Weergavenaam (optioneel)
                      <input className="lv-v2-input" value={ws.hfName} onChange={(e) => ws.setHfName(e.target.value)} />
                    </label>
                    <label className="lv-v2-dm-field">
                      Beschrijving (optioneel)
                      <textarea className="lv-v2-input" value={ws.hfDesc} onChange={(e) => ws.setHfDesc(e.target.value)} />
                    </label>
                    <label className="lv-v2-dm-field">
                      Access token (optioneel)
                      <input
                        className="lv-v2-input"
                        type="password"
                        value={ws.hfToken}
                        onChange={(e) => ws.setHfToken(e.target.value)}
                        autoComplete="off"
                      />
                    </label>
                    <div className="lv-v2-dm-modal-actions">
                      <button type="button" className="lv-v2-button lv-v2-button--secondary" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                        Annuleren
                      </button>
                      <button
                        type="button"
                        className="lv-v2-button lv-v2-button--primary"
                        disabled={ws.busy || !ws.hfRepo.trim()}
                        onClick={() => void ws.onHfSubmit()}
                      >
                        {ws.hfFilename.trim() ? "Bestand importeren" : "Volledige repository importeren"}
                      </button>
                    </div>
                  </div>
                </>
              ) : null}

              {ws.modal === "delete" ? (
                <>
                  <h2 id="dm-modal-title">Dataset verwijderen</h2>
                  <p>
                    Bevestig verwijdering van{" "}
                    <strong>
                      {ws.selected ? displayNameForDataset(ws.selected) : ws.selectedId}
                    </strong>
                    .
                  </p>
                  <ul className="lv-v2-dm-delete-list">
                    <li>Catalogus-metadata en versies in DatasetStore worden verwijderd.</li>
                    <li>Owned corpus-artefacten onder dataset-roots worden opgeruimd waar van toepassing.</li>
                    <li>Gedeelde externe/lokale bronbestanden buiten owned roots blijven staan.</li>
                    <li>Brain/Knowledge-indexen worden niet stilzwijgend als “geleerd” gelaten — delete faalt bij training-referenties.</li>
                    <li>Actieve jobs kunnen delete blokkeren via DatasetService.</li>
                  </ul>
                  <div className="lv-v2-dm-modal-actions">
                    <button type="button" className="lv-v2-button lv-v2-button--secondary" disabled={ws.busy} onClick={() => ws.setModal(null)}>
                      Annuleren
                    </button>
                    <button
                      type="button"
                      className="lv-v2-button lv-v2-button--danger"
                      disabled={ws.busy}
                      onClick={() => void ws.onDeleteConfirm()}
                    >
                      Verwijderen
                    </button>
                  </div>
                </>
              ) : null}
            </div>
          </div>
        ) : null}
      </main>
    </AppShell>
  );
}

/** Thin wrapper so Tags can filter the library on click. */
function DatasetMgmtTagsPanel({
  overview,
  loading,
  onTagClick,
}: {
  overview: ReturnType<typeof useDatasetManagementWorkspace>["overview"];
  loading: boolean;
  onTagClick: (tag: string) => void;
}) {
  const tags = overview?.tagCounts ?? [];
  return (
    <section className="lv-v2-panel lv-v2-dm-panel lv-v2-dm-tags" aria-label="Populaire tags">
      <h3 className="lv-v2-panel__title">Populaire tags</h3>
      {loading ? (
        <p className="lv-v2-dm-muted">Tags laden…</p>
      ) : tags.length === 0 ? (
        <p className="lv-v2-dm-muted">Geen tags in metadata</p>
      ) : (
        <div className="lv-v2-dm-tag-cloud">
          {tags.map((t) => (
            <button
              key={t.tag}
              type="button"
              className="lv-v2-dm-tag"
              onClick={() => onTagClick(t.tag)}
              title={`Filter op tag ${t.tag}`}
            >
              {t.tag} ({t.count})
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
