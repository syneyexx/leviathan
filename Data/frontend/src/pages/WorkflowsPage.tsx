/**
 * Leviathan V2 Workflows — canonical `/workflows`.
 * Screen 1 production Workflows control plane. No page-local CSS.
 */

import { WorkflowsBottomAnalytics } from "../components/workflows/WorkflowsBottomAnalytics";
import { WorkflowsCenter } from "../components/workflows/WorkflowsCenter";
import { WorkflowsDetail } from "../components/workflows/WorkflowsDetail";
import { WorkflowsHero } from "../components/workflows/WorkflowsHero";
import { WorkflowsLibrary } from "../components/workflows/WorkflowsLibrary";
import { WorkflowsMetrics } from "../components/workflows/WorkflowsMetrics";
import { WorkflowsModals } from "../components/workflows/WorkflowsModals";
import { ErrorState, LoadingState } from "../components/ui";
import { AppShell } from "../layouts/AppShell";
import { useWorkflowsWorkspace } from "./workflows/useWorkflowsWorkspace";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

export function WorkflowsPage() {
  const ws = useWorkflowsWorkspace();
  const frozen = visualFixtureNow();

  const recentForDetail =
    ws.overview?.recent_executions?.filter((e) => e.workflow_id === ws.selectedId) ??
    ws.executions;

  return (
    <AppShell
      variant="v2"
      v2Title="Runtime & Tools / Workflows"
      v2Subtitle="Ontwerp, beheer en monitor AI workflows en automatiseringen."
      v2Online={!ws.loadError}
      v2Refreshing={ws.loading}
      onV2Refresh={() => {
        void ws.load();
      }}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--workflows">
        {ws.stale ? (
          <p className="lv-v2-warn" role="status">
            Stale — vernieuwen mislukt; laatste goede snapshot behouden.
          </p>
        ) : null}

        <WorkflowsHero
          onNewWorkflow={() => ws.setModal("create")}
          onOpenTemplates={() => ws.setModal("templates")}
        />

        <WorkflowsMetrics
          overview={ws.overview}
          loading={ws.loading && !ws.overview}
          unmeasured={Boolean(ws.overviewError && !ws.overview)}
        />

        {ws.loadError && !ws.definitions.length ? (
          <ErrorState title="Workflows laden mislukt" detail={ws.loadError} />
        ) : null}
        {ws.loading && !ws.definitions.length && !ws.loadError ? (
          <LoadingState label="Workflows laden…" />
        ) : null}

        <section className="lv-v2-wf-workspace" aria-label="Workflows werkruimte">
          <WorkflowsLibrary
            rows={ws.filtered}
            selectedId={ws.selectedId}
            query={ws.query}
            onQuery={ws.setQuery}
            category={ws.category}
            categories={ws.categories}
            onCategory={ws.setCategory}
            filter={ws.filter}
            onFilter={ws.setFilter}
            counts={ws.counts}
            viewMode={ws.viewMode}
            onViewMode={ws.setViewMode}
            nowMs={ws.nowMs}
            onSelect={ws.requestSelect}
            onNew={() => ws.setModal("create")}
            onRun={(id) => {
              void ws.run(id);
            }}
            busy={ws.busy}
          />

          <WorkflowsCenter
            selected={ws.selected}
            draft={ws.draft}
            dirty={ws.dirty}
            busy={ws.busy}
            loading={ws.loading}
            centerTab={ws.centerTab}
            onCenterTab={ws.setCenterTab}
            palette={ws.palette}
            executions={ws.executions}
            executionsError={ws.executionsError}
            logs={ws.logs}
            logsError={ws.logsError}
            nowMs={ws.nowMs}
            onSave={() => void ws.save()}
            onRun={() => void ws.run()}
            onResumeExecution={(executionId) => void ws.resumeExecution(executionId)}
            onUpdateDraft={ws.updateDraft}
            onGraphChange={ws.setGraph}
          />

          <WorkflowsDetail
            selected={ws.selected}
            draft={ws.draft}
            detailTab={ws.detailTab}
            onDetailTab={ws.setDetailTab}
            versions={ws.versions}
            versionsError={ws.versionsError}
            recentExecutions={
              recentForDetail.length
                ? recentForDetail
                : ws.overview?.recent_executions ?? ws.executions
            }
            nowMs={ws.nowMs}
            busy={ws.busy}
            onEdit={() => ws.setCenterTab("config")}
            onDuplicate={() => void ws.duplicate()}
            onDelete={() => ws.setModal("delete")}
            onRestoreVersion={(v) => void ws.restoreVersion(v)}
            onUpdateDraft={ws.updateDraft}
          />
        </section>

        <WorkflowsBottomAnalytics overview={ws.overview} />

        <WorkflowsModals
          modal={ws.modal}
          busy={ws.busy}
          createName={ws.createName}
          createDesc={ws.createDesc}
          onCreateName={ws.setCreateName}
          onCreateDesc={ws.setCreateDesc}
          templates={ws.templates}
          createFromTemplateId={ws.createFromTemplateId}
          onCreateFromTemplateId={ws.setCreateFromTemplateId}
          selectedName={ws.selected?.name}
          onClose={() => ws.setModal(null)}
          onCreate={() => void ws.create()}
          onDelete={() => void ws.remove()}
          onDiscardUnsaved={ws.discardAndSelect}
          onOpenCreate={() => ws.setModal("create")}
        />
      </main>
    </AppShell>
  );
}
