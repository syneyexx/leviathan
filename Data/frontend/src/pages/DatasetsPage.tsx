/**
 * Leviathan V2 Datasets — canonical `/datasets` (Onderzoek & Kennis → Datasets).
 * Visual layout follows the Datasets V2 reference; truth comes from DatasetService.
 * No page-local CSS — styles live in leviathan-v2.css under .lv-v2-page--datasets.
 */

import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { DatasetsBottomWidgets } from "../components/datasets/DatasetsBottomWidgets";
import { DatasetsDetailPanel } from "../components/datasets/DatasetsDetailPanel";
import { DatasetsInventory } from "../components/datasets/DatasetsInventory";
import { DatasetsMetrics } from "../components/datasets/DatasetsMetrics";
import { DatasetsModals } from "../components/datasets/DatasetsModals";
import { DatasetsToolbar } from "../components/datasets/DatasetsToolbar";
import { ErrorState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
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
  const [params] = useSearchParams();

  useEffect(() => {
    const deep = params.get("dataset");
    if (deep) ws.setActiveId(deep);
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps -- deep-link once per param

  return (
    <AppShell
      variant="v2"
      v2Title="Kennis & Onderzoek / Datasets"
      v2Subtitle="Beheer, importeer en analyseer alle datasets voor je onderzoek en AI agents."
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
            STALE — laatste succesvolle update {ws.lastUpdated ? new Date(ws.lastUpdated).toLocaleString() : "—"}.
            Behouden inventaris na refresh-fout.
          </p>
        ) : null}

        {ws.error && ws.datasets.length === 0 ? (
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

        <section className="lv-v2-ds-workspace" aria-label="Datasets workspace">
          <DatasetsInventory ws={ws} />
          <DatasetsDetailPanel ws={ws} />
        </section>

        <DatasetsBottomWidgets ws={ws} />
        <DatasetsModals ws={ws} />
      </main>
    </AppShell>
  );
}
