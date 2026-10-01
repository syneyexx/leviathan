/**
 * Leviathan V2 Datasets — canonical `/datasets` (Onderzoek & Kennis → Datasets).
 * Visual layout follows the Datasets V2 reference; truth comes from DatasetService.
 * Modes: default inventory, ?mode=manage, ?mode=learning (fleet).
 */

import { AppShell } from "../layouts/AppShell";
import { DatasetsBottomWidgets } from "../components/datasets/DatasetsBottomWidgets";
import { DatasetsDetailPanel } from "../components/datasets/DatasetsDetailPanel";
import { DatasetsInventory } from "../components/datasets/DatasetsInventory";
import { DatasetsMetrics } from "../components/datasets/DatasetsMetrics";
import { DatasetsModals } from "../components/datasets/DatasetsModals";
import { DatasetsToolbar } from "../components/datasets/DatasetsToolbar";
import { ErrorState, EmptyState, LoadingState } from "../components/ui";
import { useDatasetsWorkspace } from "./datasets/useDatasetsWorkspace";
import { learningStatusLabel, resolveLearningState } from "./datasets/datasetLearningState";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

function LearningFleetPanel({ ws }: { ws: ReturnType<typeof useDatasetsWorkspace> }) {
  if (ws.fleetLoading && ws.fleet.length === 0) {
    return <LoadingState label="Learning fleet laden…" />;
  }
  if (ws.fleetError) {
    return <ErrorState title="Learning fleet unavailable" detail={ws.fleetError} />;
  }
  if (ws.fleet.length === 0) {
    return (
      <EmptyState
        title="Geen geleerde datasets"
        detail="Leer een dataset naar Brain om de fleet te vullen. Geen N+1 getDataset-calls."
      />
    );
  }
  return (
    <section className="lv-v2-panel lv-v2-ds-fleet" aria-label="Learning fleet">
      <header className="lv-v2-ds-widget__head">
        <h3>Learning / Brain fleet</h3>
        <span className="lv-v2-ds-widget__badge">
          {ws.fleetTotal ?? ws.fleet.length} · listLearningFleet
        </span>
      </header>
      <ul className="lv-v2-ds-fleet-list">
        {ws.fleet.map((row) => {
          const learning = resolveLearningState({
            learningState:
              row.learningState && "canonicalState" in (row.learningState as object)
                ? (row.learningState as import("../types/api").DatasetLearningState)
                : null,
            brain: row.learningState ?? null,
          });
          const chunks = row.indexStats?.chunkCount ?? null;
          const docs = row.indexStats?.readyCount ?? null;
          const job = row.activeJob;
          return (
            <li key={row.datasetId}>
              <button
                type="button"
                className={ws.activeId === row.datasetId ? "is-active" : undefined}
                onClick={() => ws.setActiveId(row.datasetId)}
              >
                <strong>{row.name || row.datasetId}</strong>
                <span>{learningStatusLabel(learning)}</span>
                <span>
                  chunks {chunks == null ? "—" : chunks} · indexes {docs == null ? "—" : docs}
                </span>
                {job ? (
                  <span>
                    job {job.jobType} · {job.status}
                  </span>
                ) : null}
              </button>
              <div className="lv-v2-ds-action-row">
                <button
                  type="button"
                  className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                  disabled={ws.busy}
                  onClick={() => {
                    ws.setActiveId(row.datasetId);
                    void ws.onLearn({ rebuild: true });
                  }}
                >
                  Rebuild
                </button>
                {job?.jobId ? (
                  <button
                    type="button"
                    className="lv-v2-button lv-v2-button--ghost lv-v2-button--sm"
                    disabled={ws.busy}
                    onClick={() => void ws.onCancelDatasetJob(job.jobId)}
                  >
                    Annuleer
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function DatasetsPage() {
  const ws = useDatasetsWorkspace();
  const frozen = visualFixtureNow();
  const isLearning = ws.workspaceMode === "learning";

  return (
    <AppShell
      variant="v2"
      v2Title="Kennis & Onderzoek / Datasets"
      v2Subtitle={
        isLearning
          ? "Learning / Brain fleet — geleerde datasets en actieve INDEX jobs."
          : "Beheer, importeer en analyseer alle datasets voor je onderzoek en AI agents."
      }
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={() => {
        void ws.refresh({ quiet: true });
      }}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--datasets">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            STALE — laatste succesvolle update{" "}
            {ws.lastUpdated ? new Date(ws.lastUpdated).toLocaleString() : "—"}. Behouden inventaris
            na refresh-fout.
          </p>
        ) : null}

        {ws.error && ws.datasets.length === 0 && !isLearning ? (
          <div className="lv-v2-ds-error-block">
            <ErrorState title="Datasets unavailable" detail={ws.error} />
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              onClick={() => void ws.loadDatasets({ offset: 0 })}
            >
              Opnieuw proberen
            </button>
          </div>
        ) : null}

        <DatasetsMetrics ws={ws} />
        <DatasetsToolbar ws={ws} />

        {isLearning ? (
          <section className="lv-v2-ds-workspace" aria-label="Learning workspace">
            <LearningFleetPanel ws={ws} />
            <DatasetsDetailPanel ws={ws} />
          </section>
        ) : (
          <section className="lv-v2-ds-workspace" aria-label="Datasets workspace">
            <DatasetsInventory ws={ws} />
            <DatasetsDetailPanel ws={ws} />
          </section>
        )}

        <DatasetsBottomWidgets ws={ws} />
        <DatasetsModals ws={ws} />
      </main>
    </AppShell>
  );
}
