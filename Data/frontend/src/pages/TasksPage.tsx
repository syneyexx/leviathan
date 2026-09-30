import { useCallback } from "react";
import { TasksBottomGrid } from "../components/tasks/TasksBottomGrid";
import { TasksDetailPanel } from "../components/tasks/TasksDetailPanel";
import { TasksHero } from "../components/tasks/TasksHero";
import { TasksMetrics } from "../components/tasks/TasksMetrics";
import { TasksOverviewTable } from "../components/tasks/TasksOverviewTable";
import { ErrorState, LoadingState } from "../components/ui";
import { useTasksWorkspace } from "../hooks/useTasksWorkspace";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import { TaskCreateDialog } from "./tasks/TaskCreateDialog";

function visualFixtureNow(): Date | undefined {
  if (typeof window === "undefined") return undefined;
  const frozen = (window as Window & { __LV_V2_FROZEN_NOW__?: string }).__LV_V2_FROZEN_NOW__;
  if (!frozen) return undefined;
  const d = new Date(frozen);
  return Number.isNaN(d.getTime()) ? undefined : d;
}

/**
 * Dashboard / Taken — operational projection of TaskService + JobRuntime.
 * Visual layout follows the Taken V2 reference; truth comes from /api/tasks*.
 */
export function TasksPage() {
  const ws = useTasksWorkspace();
  const toast = useAppToast();
  const frozen = visualFixtureNow();

  const notify = useCallback(
    (message: string) => {
      toast(message);
    },
    [toast],
  );

  const wrapAction = useCallback(
    async (fn: () => Promise<{ ok: boolean; error?: string; label?: string } | void>) => {
      const result = await fn();
      if (result && "ok" in result) {
        if (result.ok) toast(`${result.label ?? "Actie"} ok`);
        else if (result.error) toast(result.error);
      }
    },
    [toast],
  );

  return (
    <AppShell
      variant="v2"
      v2Title="Dashboard / Taken"
      v2Subtitle="Beheer, monitor en controleer alle taken, jobs en achtergrondprocessen in Leviathan."
      v2Online={ws.online}
      v2Refreshing={ws.refreshing}
      onV2Refresh={ws.refresh}
      v2StatusRows={ws.sidebarStatus}
      v2Now={frozen ? () => frozen : undefined}
    >
      <main className="lv-v2-page lv-v2-page--tasks">
        <TasksHero />
        <TasksMetrics summary={ws.summary} loading={ws.loading} />

        {ws.loadError ? (
          <ErrorState title="Taken laden mislukt" detail={ws.loadError} />
        ) : null}
        {ws.stale ? (
          <div className="lv-v2-tasks-stale" role="status">
            Gegevens mogelijk verouderd — vernieuwen mislukt.
          </div>
        ) : null}

        {ws.loading && ws.tasks.length === 0 ? <LoadingState label="Taken laden…" /> : null}

        <section className="lv-v2-tasks-workspace" aria-label="Taken werkruimte">
          <TasksOverviewTable
            tasks={ws.tasks}
            selectedId={ws.selectedId}
            busy={ws.actionBusy}
            filters={{
              searchInput: ws.searchInput,
              setSearchInput: ws.setSearchInput,
              status: ws.status,
              setStatus: ws.setStatus,
              type: ws.type,
              setType: ws.setType,
              assignee: ws.assignee,
              setAssignee: ws.setAssignee,
              priority: ws.priority,
              setPriority: ws.setPriority,
              typeOptions: ws.typeOptions,
              agents: ws.agents,
            }}
            onSelect={ws.selectTask}
            onNewTask={() => ws.setCreateOpen(true)}
            onCancel={(task) => void wrapAction(() => ws.cancelTask(task))}
            onRetry={(task) => void wrapAction(() => ws.retryTask(task))}
            onDuplicate={(task) => void wrapAction(() => ws.duplicateTask(task))}
            onChangePriority={(task, p) => void wrapAction(() => ws.changePriority(task, p))}
          />
          {ws.selected ? (
            <TasksDetailPanel
              key={ws.selected.taskId}
              task={ws.selected}
              busy={ws.actionBusy}
              onCancel={(task) => void wrapAction(() => ws.cancelTask(task))}
              onDuplicate={(task) => void wrapAction(() => ws.duplicateTask(task))}
              onChangePriority={(task, p) => void wrapAction(() => ws.changePriority(task, p))}
              onError={notify}
            />
          ) : (
            <aside className="lv-v2-panel lv-v2-tasks-detail lv-v2-tasks-detail--empty" aria-label="Taak Details">
              <p className="lv-v2-muted">Selecteer een taak om details te bekijken.</p>
            </aside>
          )}
        </section>

        <TasksBottomGrid
          activity={ws.activity}
          agentActivity={ws.agentActivity}
          summary={ws.summary}
          telemetry={ws.telemetry.sample}
          telemetryError={ws.telemetry.error}
          onSelectTask={ws.selectTask}
        />
      </main>

      <TaskCreateDialog
        key={ws.createOpen ? "create-open" : "create-closed"}
        open={ws.createOpen}
        agents={ws.agents}
        defaultBoardColumn="backlog"
        onClose={() => ws.setCreateOpen(false)}
        onCreated={ws.onCreated}
        onError={notify}
        onSuccess={notify}
      />
    </AppShell>
  );
}
