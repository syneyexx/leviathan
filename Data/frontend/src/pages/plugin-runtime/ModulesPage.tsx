/**
 * Leviathan V2 Modules — canonical `/modules`.
 * Screen 1 production ModuleManager control plane. No page-local CSS.
 */

import { ModulesDetail } from "../../components/modules/ModulesDetail";
import { ModulesHero } from "../../components/modules/ModulesHero";
import { ModulesInstallPanel } from "../../components/modules/ModulesInstallPanel";
import { ModulesLibrary } from "../../components/modules/ModulesLibrary";
import { ModulesLocalNav } from "../../components/modules/ModulesLocalNav";
import { ModulesMetrics } from "../../components/modules/ModulesMetrics";
import { ModulesProjectionViews } from "../../components/modules/ModulesProjectionViews";
import { ErrorState, LoadingState } from "../../components/ui";
import { AppShell } from "../../layouts/AppShell";
import { useModulesWorkspace } from "./modules/useModulesWorkspace";
import { isInstalled, moduleId } from "./modules/viewModels";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function ModulesPage() {
  const ws = useModulesWorkspace();
  const frozen = visualFixtureNow();

  const openInstallForSelected = () => {
    if (!ws.selected) {
      ws.setNewModuleOpen(true);
      return;
    }
    void ws.onLifecycle("install");
  };

  return (
    <AppShell
      variant="v2"
      v2Title="Runtime & Tools / Modules"
      v2Subtitle="Beheer, installeer en monitor alle runtime modules en externe capabilities."
      v2Online={!ws.loadError}
      v2Refreshing={ws.loading}
      onV2Refresh={() => {
        void ws.load();
      }}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--modules">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — vernieuwen mislukt; laatste goede snapshot behouden.
          </p>
        ) : null}

        <ModulesHero
          onInstallNew={() => {
            ws.setFilter("not_installed");
            ws.setNewModuleOpen(true);
            const first = ws.modules.find((m) => !isInstalled(m));
            if (first) ws.selectModule(moduleId(first));
            void ws.onLifecycle("install");
          }}
          onOpenManager={() => {
            ws.setWorkspaceView("modules");
            ws.setDetailTab("configuration");
          }}
        />

        <ModulesMetrics
          kpis={ws.kpis}
          installedCount={ws.installedCount}
          loading={ws.loading && !ws.snapshot}
          sparklines={ws.visualSparklines}
        />

        {ws.loadError ? <ErrorState title="Modules laden mislukt" detail={ws.loadError} /> : null}
        {ws.loading && !ws.snapshot ? <LoadingState label="Modules laden…" /> : null}

        {!ws.managerEnabled && ws.snapshot ? (
          <p className="lv-v2-warn" role="status">
            Feature flag OFF — module system disabled. Geen gefabriceerde modules.
          </p>
        ) : null}

        <section className="lv-v2-modules-workspace" aria-label="Modules werkruimte">
          <ModulesLocalNav activeView={ws.workspaceView} onSelectView={ws.setWorkspaceView} />

          {ws.workspaceView === "modules" ? (
            <>
              <ModulesLibrary
                rows={ws.rows}
                selectedId={ws.selectedId}
                query={ws.query}
                onQuery={ws.setQuery}
                filter={ws.filter}
                onFilter={ws.setFilter}
                counts={ws.counts}
                discovering={ws.discovering}
                managerEnabled={ws.managerEnabled}
                loading={ws.loading}
                loadError={ws.loadError}
                onSelect={ws.selectModule}
                onDiscover={() => void ws.onDiscover()}
                onRefresh={() => void ws.load()}
              />
              <ModulesDetail
                selected={ws.selected}
                detailTab={ws.detailTab}
                setDetailTab={ws.setDetailTab}
                actions={ws.actions}
                lifecycleBusy={ws.lifecycleBusy}
                pendingLifecycle={ws.pendingLifecycle}
                healthPayload={ws.healthPayload}
                logLines={ws.logLines}
                jobsPayload={ws.jobsPayload}
                versionsPayload={ws.versionsPayload}
                capabilitiesPayload={ws.capabilitiesPayload}
                panelJson={ws.panelJson}
                lastResult={ws.lastResult}
                lastAction={ws.lastAction}
                activityEvents={ws.activityEvents}
                ops={ws.ops}
                operation={ws.operation}
                setOperation={ws.setOperation}
                argsJson={ws.argsJson}
                setArgsJson={ws.setArgsJson}
                executing={ws.executing}
                versionRef={ws.versionRef}
                setVersionRef={ws.setVersionRef}
                versionId={ws.versionId}
                setVersionId={ws.setVersionId}
                onLifecycle={(a) => void ws.onLifecycle(a)}
                onExecute={() => void ws.onExecute()}
                onCancelJob={() => void ws.cancelPendingJob()}
                onOpenInstall={openInstallForSelected}
              />
            </>
          ) : (
            <div className="lv-v2-modules-projection-wrap">
              <ModulesProjectionViews
                view={ws.workspaceView}
                modules={ws.modules}
                snapshot={ws.snapshot}
                selectedId={ws.selectedId}
                onSelectModule={(id) => {
                  ws.selectModule(id);
                  ws.setWorkspaceView("modules");
                }}
              />
            </div>
          )}
        </section>

        <ModulesInstallPanel
          open={ws.installPanelOpen || ws.newModuleOpen}
          onClose={() => {
            ws.setInstallPanelOpen(false);
            ws.setNewModuleOpen(false);
          }}
          plan={ws.installPlan}
          operation={ws.installOperation}
          primaryCta={ws.primaryInstallCta}
          busy={ws.lifecycleBusy}
          onApproveAndInstall={() => void ws.approveAndInstallEverything()}
          onRetry={() => void ws.retryInstall()}
        />
      </main>
    </AppShell>
  );
}
