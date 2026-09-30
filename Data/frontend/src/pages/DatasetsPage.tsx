/**
 * Leviathan V2 Datasets — canonical `/datasets` (Onderzoek & Kennis → Datasets).
 * Visual layout follows the Datasets V2 reference; truth comes from DatasetService.
 * No page-local CSS — styles live in leviathan-v2.css under .lv-v2-page--datasets.
 */

import { DatasetsBottomWidgets } from "../components/datasets/DatasetsBottomWidgets";
import { DatasetsDetailPanel } from "../components/datasets/DatasetsDetailPanel";
import { DatasetsHero } from "../components/datasets/DatasetsHero";
import { DatasetsInventory } from "../components/datasets/DatasetsInventory";
import { DatasetsMetrics } from "../components/datasets/DatasetsMetrics";
import { DatasetsModals } from "../components/datasets/DatasetsModals";
import { DatasetsToolbar } from "../components/datasets/DatasetsToolbar";
import { ErrorState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { DatasetActivityConsole } from "./datasets/DatasetActivityConsole";
import { useDatasetsWorkspace } from "./datasets/useDatasetsWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function DatasetsPage() {
  const ws = useDatasetsWorkspace();
  const frozen = visualFixtureNow();

  return (
    <AppShell
      variant="v2"
      v2Title="Onderzoek & Kennis / Datasets"
      v2Subtitle="Beheer, importeer, indexeer en analyseer datasets voor onderzoek, agents en training."
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
            STALE — last successful update {ws.lastUpdated ? new Date(ws.lastUpdated).toLocaleString() : "—"}.
            Showing retained inventory after refresh failure.
          </p>
        ) : null}

        {ws.error && ws.datasets.length === 0 ? (
          <div className="lv-v2-ds-error-block">
            <ErrorState title="Datasets unavailable" detail={ws.error} />
            <button
              type="button"
              className="lv-v2-button lv-v2-button--primary lv-v2-button--sm"
              onClick={() => void ws.loadDatasets()}
            >
              Retry
            </button>
          </div>
        ) : null}

        <DatasetsHero />
        <DatasetsMetrics ws={ws} />
        <DatasetsToolbar ws={ws} />

        <section className="lv-v2-ds-workspace" aria-label="Datasets workspace">
          <DatasetsInventory ws={ws} />
          <DatasetsDetailPanel ws={ws} />
        </section>

        <DatasetsBottomWidgets ws={ws} />

        <div className="lv-v2-ds-activity">
          <DatasetActivityConsole
            jobs={ws.jobs}
            entries={ws.activityEntries}
            preferredJobId={ws.preferredJobId}
            onPreferredJobIdChange={ws.setPreferredJobId}
            apiError={ws.jobsError}
            live={ws.live}
            busy={ws.busy}
            onCancelJob={ws.onCancelDatasetJob}
            onClearView={ws.clearActivityView}
          />
        </div>

        <DatasetsModals ws={ws} />
      </main>
    </AppShell>
  );
}
