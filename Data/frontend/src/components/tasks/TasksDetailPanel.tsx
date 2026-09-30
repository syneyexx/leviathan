import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, EmptyState, ProgressBar } from "../ui";
import type {
  JobRecord,
  TaskDependency,
  TaskEvent,
  TaskRecord,
  TaskSubtask,
} from "../../types/api";
import {
  canCancelTask,
  canPauseTask,
  displayProgressPct,
  displayTaskId,
  errMsg,
  finishedAt,
  formatDateTime,
  formatDuration,
  formatEventLabel,
  formatRelative,
  operationalStatus,
  priorityLabel,
  startedAt,
  statusLabel,
  statusTone,
  taskTypeLabel,
  taskTypeTone,
} from "../../pages/tasks/taskUtils";

type Tab = "overzicht" | "logs" | "resultaten" | "configuratie" | "gerelateerd";

type Props = {
  task: TaskRecord;
  busy?: boolean;
  onCancel: (task: TaskRecord) => void;
  onDuplicate: (task: TaskRecord) => void;
  onChangePriority: (task: TaskRecord, priority: string) => void;
  onError: (message: string) => void;
};

export function TasksDetailPanel({
  task,
  busy,
  onCancel,
  onDuplicate,
  onChangePriority,
  onError,
}: Props) {
  const [tab, setTab] = useState<Tab>("overzicht");
  const [subtasks, setSubtasks] = useState<TaskSubtask[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [deps, setDeps] = useState<TaskDependency[]>([]);
  const [job, setJob] = useState<JobRecord | null>(null);
  const [tabLoading, setTabLoading] = useState(false);
  const [priorityOpen, setPriorityOpen] = useState(false);

  const load = useCallback(async () => {
    setTabLoading(true);
    try {
      const [subs, evs, depRes] = await Promise.all([
        api.listTaskSubtasks(task.taskId),
        api.listTaskEvents(task.taskId, { limit: 100 }),
        api.listTaskDependencies(task.taskId),
      ]);
      setSubtasks(subs.subtasks ?? []);
      setEvents(evs.events ?? []);
      setDeps(depRes.dependencies ?? []);
      if (task.jobId) {
        try {
          const jobRes = await api.getJob(task.jobId);
          setJob(jobRes.job ?? null);
        } catch {
          setJob(null);
        }
      } else {
        setJob(null);
      }
    } catch (err) {
      onError(errMsg(err, "Taakdetails laden mislukt"));
    } finally {
      setTabLoading(false);
    }
  }, [task.taskId, task.jobId, onError]);

  useEffect(() => {
    setTab("overzicht");
    void load();
  }, [load]);

  const status = operationalStatus(task);
  const pct = displayProgressPct(task);
  const start = startedAt(task);
  const end = finishedAt(task);
  const pauseOk = canPauseTask(task);

  const tabs: Array<{ id: Tab; label: string }> = [
    { id: "overzicht", label: "Overzicht" },
    { id: "logs", label: "Logs" },
    { id: "resultaten", label: "Resultaten" },
    { id: "configuratie", label: "Configuratie" },
    { id: "gerelateerd", label: "Gerelateerde Taken" },
  ];

  return (
    <aside className="lv-v2-panel lv-v2-tasks-detail" aria-label="Taak Details">
      <header className="lv-v2-tasks-detail__head">
        <div className="lv-v2-tasks-detail__title-row">
          <span className="lv-v2-tasks-detail__icon" aria-hidden="true">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7">
              <path d="M9 11l3 3L22 4" />
              <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
            </svg>
          </span>
          <div>
            <h3 className="lv-v2-tasks-detail__title">{task.title}</h3>
            <div className="lv-v2-tasks-detail__meta">
              <span className={`lv-v2-tasks-status lv-v2-tasks-status--${statusTone(status)}`}>
                <i aria-hidden="true" />
                {statusLabel(status)}
              </span>
              <span className="lv-v2-tasks-id">{displayTaskId(task)}</span>
            </div>
          </div>
        </div>
        {task.description ? <p className="lv-v2-tasks-detail__desc">{task.description}</p> : null}
      </header>

      <div className="lv-v2-tasks-tabs" role="tablist" aria-label="Taak tabs">
        {tabs.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            className={tab === t.id ? "is-active" : undefined}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <div className="lv-v2-tasks-detail__body" role="tabpanel">
        {tabLoading ? <p className="lv-v2-muted">Laden…</p> : null}

        {tab === "overzicht" ? (
          <div className="lv-v2-tasks-detail-overview">
            <section>
              <h4>Algemene Informatie</h4>
              <dl className="lv-v2-tasks-kv">
                <div>
                  <dt>Type</dt>
                  <dd>
                    <Badge tone={taskTypeTone(task.taskType)}>{taskTypeLabel(task.taskType)}</Badge>
                  </dd>
                </div>
                <div>
                  <dt>Agent</dt>
                  <dd>{task.assigneeName || "—"}</dd>
                </div>
                <div>
                  <dt>Prioriteit</dt>
                  <dd>{priorityLabel(task.priority)}</dd>
                </div>
                <div>
                  <dt>Status</dt>
                  <dd>{statusLabel(status)}</dd>
                </div>
                <div>
                  <dt>Gestart</dt>
                  <dd>{formatDateTime(start)}</dd>
                </div>
                <div>
                  <dt>Laatst bijgewerkt</dt>
                  <dd>{formatDateTime(task.updatedAt)}</dd>
                </div>
                <div>
                  <dt>Duur</dt>
                  <dd>{formatDuration(start, status === "running" ? null : end)}</dd>
                </div>
                <div>
                  <dt>Verwachte duur</dt>
                  <dd>Onbekend</dd>
                </div>
              </dl>
            </section>

            <section>
              <div className="lv-v2-tasks-detail-progress-head">
                <h4>Voortgang</h4>
                <strong>{pct == null ? "—" : `${pct}%`}</strong>
              </div>
              <ProgressBar value={pct} />
              {subtasks.length > 0 ? (
                <ul className="lv-v2-tasks-steps">
                  {subtasks.map((s) => (
                    <li key={s.subtaskId} className={s.completed ? "is-done" : undefined}>
                      <span className="lv-v2-tasks-step-mark" aria-hidden="true">
                        {s.completed ? "✓" : "○"}
                      </span>
                      <span>{s.title}</span>
                      <em>{s.completed ? "100%" : "0%"}</em>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="lv-v2-muted">Geen subtaken / uitvoeringsstappen beschikbaar.</p>
              )}
            </section>

            {task.description ? (
              <section>
                <h4>Beschrijving</h4>
                <p>{task.description}</p>
              </section>
            ) : null}

            <section className="lv-v2-tasks-detail-actions" aria-label="Taakacties">
              <Button
                variant="secondary"
                size="sm"
                disabled
                title={task.controls?.pauseReason || "Pauze niet ondersteund"}
              >
                Pauzeren
              </Button>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || !canCancelTask(task)}
                title={!canCancelTask(task) ? "Stoppen niet beschikbaar voor deze status" : "Stoppen"}
                onClick={() => onCancel(task)}
              >
                Stoppen
              </Button>
              <div className="lv-v2-tasks-priority-wrap">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={busy || task.controls?.canChangePriority === false}
                  onClick={() => setPriorityOpen((v) => !v)}
                >
                  Prioriteit wijzigen
                </Button>
                {priorityOpen ? (
                  <div className="lv-v2-tasks-menu" role="menu">
                    {(["high", "medium", "low"] as const).map((p) => (
                      <button
                        key={p}
                        type="button"
                        role="menuitem"
                        onClick={() => {
                          setPriorityOpen(false);
                          onChangePriority(task, p);
                        }}
                      >
                        {priorityLabel(p)}
                      </button>
                    ))}
                  </div>
                ) : null}
              </div>
              <Button
                variant="secondary"
                size="sm"
                disabled={busy || task.controls?.canDuplicate === false}
                onClick={() => onDuplicate(task)}
              >
                Dupliceer
              </Button>
            </section>
            {!pauseOk ? (
              <p className="lv-v2-muted lv-v2-tasks-pause-note">
                {task.controls?.pauseReason || "JobRuntime ondersteunt geen pauze."}
              </p>
            ) : null}
          </div>
        ) : null}

        {tab === "logs" ? (
          events.length === 0 ? (
            <EmptyState title="Geen logs" detail="Er zijn nog geen gebeurtenissen voor deze taak." />
          ) : (
            <ul className="lv-v2-tasks-log-list">
              {events.map((ev) => (
                <li key={ev.eventId}>
                  <time>{formatRelative(ev.createdAt) || formatDateTime(ev.createdAt)}</time>
                  <span>{formatEventLabel(ev.eventType)}</span>
                </li>
              ))}
            </ul>
          )
        ) : null}

        {tab === "resultaten" ? (
          !task.jobId && !task.missionId ? (
            <EmptyState title="Geen resultaten" detail="Deze taak heeft geen gekoppelde job- of missieresultaten." />
          ) : job ? (
            <div className="lv-v2-tasks-result">
              <dl className="lv-v2-tasks-kv">
                <div>
                  <dt>Job</dt>
                  <dd>{String(job.jobId || job.id || task.jobId)}</dd>
                </div>
                <div>
                  <dt>State</dt>
                  <dd>{String(job.state || job.status || "—")}</dd>
                </div>
                <div>
                  <dt>Error</dt>
                  <dd>{job.error ? String(job.error) : "—"}</dd>
                </div>
              </dl>
              {job.result_summary != null || job.result != null ? (
                <pre className="lv-v2-tasks-pre">{JSON.stringify(job.result_summary ?? job.result, null, 2)}</pre>
              ) : (
                <p className="lv-v2-muted">Nog geen resultaatpayload.</p>
              )}
              {Array.isArray(job.artifact_refs) && job.artifact_refs.length > 0 ? (
                <ul className="lv-v2-tasks-artifacts">
                  {job.artifact_refs.map((ref, i) => (
                    <li key={i}>{typeof ref === "string" ? ref : JSON.stringify(ref)}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <EmptyState title="Resultaat niet beschikbaar" detail="Jobgegevens konden niet worden geladen." />
          )
        ) : null}

        {tab === "configuratie" ? (
          <div className="lv-v2-tasks-config">
            <dl className="lv-v2-tasks-kv">
              <div>
                <dt>Execution binding</dt>
                <dd>{String(task.executionBinding)}</dd>
              </div>
              <div>
                <dt>Capability</dt>
                <dd>{task.capabilityId || "—"}</dd>
              </div>
              <div>
                <dt>Workflow</dt>
                <dd>{task.workflowId || "—"}</dd>
              </div>
              <div>
                <dt>Schedule</dt>
                <dd>{task.scheduleId || "—"}</dd>
              </div>
            </dl>
            <h4>Aangevraagde configuratie</h4>
            <pre className="lv-v2-tasks-pre">
              {JSON.stringify(task.capabilityArguments ?? {}, null, 2)}
            </pre>
            <h4>Metadata</h4>
            <pre className="lv-v2-tasks-pre">{JSON.stringify(task.metadata ?? {}, null, 2)}</pre>
          </div>
        ) : null}

        {tab === "gerelateerd" ? (
          deps.length === 0 ? (
            <EmptyState title="Geen gerelateerde taken" detail="Er zijn geen canonieke afhankelijkheden." />
          ) : (
            <ul className="lv-v2-tasks-related">
              {deps.map((d) => (
                <li key={d.dependencyId}>
                  <strong>{d.dependsOn?.title || d.dependsOnTaskId}</strong>
                  <span>{d.soft ? "soft dependency" : "hard dependency"}</span>
                </li>
              ))}
            </ul>
          )
        ) : null}
      </div>
    </aside>
  );
}
