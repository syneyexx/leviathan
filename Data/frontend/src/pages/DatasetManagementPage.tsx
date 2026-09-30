/**
 * Leviathan V2 LLM / Dataset Management — canonical `/dataset-management`.
 * Screen 1 library + detail + activity workspace.
 * No page-local CSS — layout lives in `styles/leviathan-v2.css` under
 * `.lv-v2-page--dataset-management`.
 */

import { DatasetManagementActions } from "../components/dataset-management/DatasetManagementActions";
import { DatasetManagementDetail } from "../components/dataset-management/DatasetManagementDetail";
import { DatasetManagementDialogs } from "../components/dataset-management/DatasetManagementDialogs";
import { DatasetManagementFooter } from "../components/dataset-management/DatasetManagementFooter";
import { DatasetManagementHero } from "../components/dataset-management/DatasetManagementHero";
import { DatasetManagementLibrary } from "../components/dataset-management/DatasetManagementLibrary";
import { DatasetManagementMetrics } from "../components/dataset-management/DatasetManagementMetrics";
import { DatasetManagementServices } from "../components/dataset-management/DatasetManagementServices";
import { DatasetManagementStorage } from "../components/dataset-management/DatasetManagementStorage";
import { Button, ErrorState } from "../components/ui";
import { useDatasetManagementWorkspace } from "../hooks/useDatasetManagementWorkspace";
import { AppShell } from "../layouts/AppShell";
import { DatasetActivityConsole } from "./datasets/DatasetActivityConsole";
import { DM_PAGE_COPY, UPLOAD_ACCEPT } from "./datasets/datasetManagementConstants";

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

  const actions = (
    <>
      <Button variant="secondary" size="sm" loading={ws.refreshing} onClick={() => void ws.refresh()}>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M20 12a8 8 0 1 1-2.2-5.5" />
          <path d="M20 4v5h-5" />
        </svg>
        Refresh
      </Button>
      <Button variant="primary" size="sm" onClick={() => void ws.onSidebarAction("upload")}>
        + Dataset toevoegen
      </Button>
    </>
  );

  return (
    <AppShell
      variant="v2"
      v2Title={DM_PAGE_COPY.shellTitle}
      v2Subtitle={DM_PAGE_COPY.shellSubtitle}
      v2Online={ws.online}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
      v2Actions={actions}
      v2HideRefresh
    >
      <input
        ref={ws.uploadRef}
        type="file"
        hidden
        accept={UPLOAD_ACCEPT}
        onChange={(e) => {
          const file = e.target.files?.[0] ?? null;
          e.target.value = "";
          void ws.onUploadFile(file);
        }}
      />

      <main className="lv-v2-page lv-v2-page--dataset-management">
        <DatasetManagementHero onAddDataset={() => void ws.onSidebarAction("upload")} />
        <DatasetManagementMetrics kpis={ws.kpis} loading={ws.loading} />

        {ws.error ? (
          <ErrorState title="Datasets laden mislukt" detail={ws.error} />
        ) : null}

        <section className="lv-v2-dm-workspace" aria-label="Dataset werkruimte">
          <aside className="lv-v2-dm-left">
            <DatasetManagementActions ws={ws} />
            <DatasetManagementServices ws={ws} />
          </aside>

          <div className="lv-v2-dm-center">
            <DatasetManagementLibrary ws={ws} />
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

          <aside className="lv-v2-dm-right">
            <DatasetManagementDetail ws={ws} />
            <DatasetManagementStorage ws={ws} />
          </aside>
        </section>

        <DatasetManagementFooter ws={ws} />
      </main>

      <DatasetManagementDialogs ws={ws} />
    </AppShell>
  );
}
