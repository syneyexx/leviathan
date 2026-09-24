import { useCallback, useEffect, useState } from "react";
import { api } from "../../api/client";
import type {
  AgentDefinition,
  TaskDependency,
  TaskEvent,
  TaskNote,
  TaskRecord,
  TaskSubtask,
} from "../../types/api";
import { IconCalendar, IconCheck, IconClose, IconLink, IconPlay, IconStop } from "./TaskIcons";
import {
  avatarTone,
  boardColumnLabel,
  canCancelTask,
  canCompleteTask,
  canStartTask,
  displayProgressPct,
  dueHint,
  errMsg,
  formatDateTime,
  formatEventLabel,
  formatRelative,
  initials,
  priorityClass,
  priorityLabel,
} from "./taskUtils";

type Tab = "Details" | "Subtasks" | "Notes" | "Dependencies" | "Activity";

type Props = {
  task: TaskRecord;
  agents: AgentDefinition[];
  allTasks: TaskRecord[];
  busy?: boolean;
  onClose: () => void;
  onRefresh: () => void;
  onError: (message: string) => void;
  onSuccess: (message: string) => void;
  onAssign: (task: TaskRecord, agentId: string | null) => void;
  onStart: (task: TaskRecord) => void;
  onCancel: (task: TaskRecord) => void;
  onComplete: (task: TaskRecord) => void;
};

export function TaskDetails({
  task,
  agents,
  allTasks,
  busy,
  onClose,
  onRefresh,
  onError,
  onSuccess,
  onAssign,
  onStart,
  onCancel,
  onComplete,
}: Props) {
  const [tab, setTab] = useState<Tab>("Details");
  const [subtasks, setSubtasks] = useState<TaskSubtask[]>([]);
  const [notes, setNotes] = useState<TaskNote[]>([]);
  const [deps, setDeps] = useState<TaskDependency[]>([]);
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [tabBusy, setTabBusy] = useState(false);
  const [newSubtask, setNewSubtask] = useState("");
  const [newNote, setNewNote] = useState("");
  const [depTarget, setDepTarget] = useState("");
  const [assignOpen, setAssignOpen] = useState(false);

  const loadTabData = useCallback(async () => {
    setTabBusy(true);
    try {
      const [subs, noteRes, depRes, evRes] = await Promise.all([
        api.listTaskSubtasks(task.taskId),
        api.listTaskNotes(task.taskId),
        api.listTaskDependencies(task.taskId),
        api.listTaskEvents(task.taskId, { limit: 100 }),
      ]);
      setSubtasks(subs.subtasks ?? []);
      setNotes(noteRes.notes ?? []);
      setDeps(depRes.dependencies ?? []);
      setEvents(evRes.events ?? []);
    } catch (err) {
      onError(errMsg(err, "Failed to load task details"));
    } finally {
      setTabBusy(false);
    }
  }, [task.taskId, onError]);

  useEffect(() => {
    setTab("Details");
    void loadTabData();
  }, [loadTabData]);

  const pct = displayProgressPct(task);
  const assignee = task.assigneeName || "Unassigned";
  const tabs: Tab[] = ["Details", "Subtasks", "Notes", "Dependencies", "Activity"];
  const hint = dueHint(task.dueAt);

  async function copyLink() {
    const url = new URL(window.location.href);
    url.searchParams.set("task", task.taskId);
    try {
      await navigator.clipboard.writeText(url.toString());
      onSuccess("Link copied");
    } catch {
      onError("Could not copy link");
    }
  }

  async function addSubtask() {
    const title = newSubtask.trim();
    if (!title) return;
    setTabBusy(true);
    try {
      await api.createSubtask(task.taskId, title);
      setNewSubtask("");
      await loadTabData();
      onRefresh();
      onSuccess("Subtask added");
    } catch (err) {
      onError(errMsg(err, "Failed to add subtask"));
    } finally {
      setTabBusy(false);
    }
  }

  async function toggleSubtask(sub: TaskSubtask) {
    setTabBusy(true);
    try {
      await api.updateSubtask(task.taskId, sub.subtaskId, { completed: !sub.completed });
      await loadTabData();
      onRefresh();
    } catch (err) {
      onError(errMsg(err, "Failed to update subtask"));
    } finally {
      setTabBusy(false);
    }
  }

  async function removeSubtask(sub: TaskSubtask) {
    setTabBusy(true);
    try {
      await api.deleteSubtask(task.taskId, sub.subtaskId);
      await loadTabData();
      onRefresh();
    } catch (err) {
      onError(errMsg(err, "Failed to delete subtask"));
    } finally {
      setTabBusy(false);
    }
  }

  async function addNote() {
    const body = newNote.trim();
    if (!body) return;
    setTabBusy(true);
    try {
      await api.createTaskNote(task.taskId, { body });
      setNewNote("");
      await loadTabData();
      onSuccess("Note added");
    } catch (err) {
      onError(errMsg(err, "Failed to add note"));
    } finally {
      setTabBusy(false);
    }
  }

  async function removeNote(note: TaskNote) {
    setTabBusy(true);
    try {
      await api.deleteTaskNote(task.taskId, note.noteId);
      await loadTabData();
    } catch (err) {
      onError(errMsg(err, "Failed to delete note"));
    } finally {
      setTabBusy(false);
    }
  }

  async function addDep() {
    if (!depTarget) return;
    setTabBusy(true);
    try {
      await api.addTaskDependency(task.taskId, { dependsOnTaskId: depTarget, soft: false });
      setDepTarget("");
      await loadTabData();
      onRefresh();
      onSuccess("Dependency added");
    } catch (err) {
      onError(errMsg(err, "Failed to add dependency"));
    } finally {
      setTabBusy(false);
    }
  }

  async function removeDep(dep: TaskDependency) {
    setTabBusy(true);
    try {
      await api.removeTaskDependency(task.taskId, dep.dependencyId);
      await loadTabData();
      onRefresh();
    } catch (err) {
      onError(errMsg(err, "Failed to remove dependency"));
    } finally {
      setTabBusy(false);
    }
  }

  const disabled = busy || tabBusy;

  return (
    <aside className="lv-tasks-details">
      <div className="lv-tasks-details-head">
        <h2 className="lv-tasks-details-title">{task.title}</h2>
        <div className="lv-tasks-details-actions">
          <button type="button" className="lv-tasks-icon-btn" aria-label="Copy link" onClick={() => void copyLink()}>
            <IconLink />
          </button>
          <button type="button" className="lv-tasks-icon-btn" aria-label="Close" onClick={onClose}>
            <IconClose />
          </button>
        </div>
      </div>

      <div className="lv-tasks-details-badges">
        <span className="lv-tasks-badge lv-tasks-badge--status">{boardColumnLabel(task.boardColumn)}</span>
        <span className={`lv-tasks-badge ${priorityClass(task.priority)}`}>{priorityLabel(task.priority)}</span>
        {task.blocked ? <span className="lv-tasks-badge lv-tasks-badge--blocked">Blocked</span> : null}
        <span className="lv-tasks-due">
          <IconCalendar />
          {formatDateTime(task.dueAt)}
          {hint ? <span className="lv-tasks-due-hint">{hint}</span> : null}
        </span>
      </div>

      <p className="lv-tasks-details-desc">{task.description || "No description"}</p>
      {task.blocked && task.blockedReason ? (
        <p className="lv-tasks-blocked-reason">{task.blockedReason}</p>
      ) : null}

      <div className="lv-tasks-tabs" role="tablist">
        {tabs.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={tab === item}
            className={`lv-tasks-tab${tab === item ? " is-active" : ""}`}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="lv-tasks-fields">
        {tab === "Details" ? (
          <>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Assignee</span>
              <div className="lv-tasks-field-value">
                <span className={`lv-tasks-avatar ${avatarTone(assignee)}`}>{initials(assignee)}</span>
                <div>
                  <strong>{assignee}</strong>
                  <small>{task.assigneeType === "agent" ? "Agent" : task.assigneeType || "—"}</small>
                </div>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Project</span>
              <div className="lv-tasks-field-value">
                <span className="lv-tasks-field-text">{task.project || "—"}</span>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Tags</span>
              <div className="lv-tasks-field-value" style={{ flexWrap: "wrap" }}>
                {(task.tags?.length ? task.tags : ["—"]).map((tag) => (
                  <span key={tag} className="lv-tasks-badge lv-tasks-badge--tag">
                    {tag}
                  </span>
                ))}
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Progress</span>
              <div className="lv-tasks-field-value">
                <div className="lv-tasks-progress-row">
                  <div className="lv-tasks-progress-bar">
                    <div className="lv-tasks-progress-fill" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="lv-tasks-progress-pct">{pct}%</span>
                </div>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Execution</span>
              <div className="lv-tasks-field-value">
                {task.executionBinding}
                {task.executionState ? ` · ${task.executionState}` : ""}
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Created</span>
              <div className="lv-tasks-field-value">{formatDateTime(task.createdAt)}</div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Last Updated</span>
              <div className="lv-tasks-field-value">{formatDateTime(task.updatedAt)}</div>
            </div>
          </>
        ) : null}

        {tab === "Subtasks" ? (
          <div className="lv-tasks-tab-panel">
            <div className="lv-tasks-inline-form">
              <input
                value={newSubtask}
                disabled={disabled}
                placeholder="New subtask…"
                onChange={(e) => setNewSubtask(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") void addSubtask();
                }}
              />
              <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={disabled} onClick={() => void addSubtask()}>
                Add
              </button>
            </div>
            {subtasks.length === 0 ? (
              <p className="lv-tasks-empty">Geen subtasks</p>
            ) : (
              <ul className="lv-tasks-checklist">
                {subtasks.map((s) => (
                  <li key={s.subtaskId}>
                    <label>
                      <input
                        type="checkbox"
                        checked={s.completed}
                        disabled={disabled}
                        onChange={() => void toggleSubtask(s)}
                      />
                      <span className={s.completed ? "is-done" : ""}>{s.title}</span>
                    </label>
                    <button type="button" className="lv-tasks-linkish" disabled={disabled} onClick={() => void removeSubtask(s)}>
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {tab === "Notes" ? (
          <div className="lv-tasks-tab-panel">
            <div className="lv-tasks-inline-form lv-tasks-inline-form--stack">
              <textarea
                value={newNote}
                disabled={disabled}
                rows={3}
                placeholder="Add a note…"
                onChange={(e) => setNewNote(e.target.value)}
              />
              <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={disabled} onClick={() => void addNote()}>
                Add note
              </button>
            </div>
            {notes.length === 0 ? (
              <p className="lv-tasks-empty">Geen notes</p>
            ) : (
              <ul className="lv-tasks-notes">
                {notes.map((n) => (
                  <li key={n.noteId}>
                    <div className="lv-tasks-note-meta">
                      <strong>{n.authorName || n.authorType || "operator"}</strong>
                      <span>{formatRelative(n.createdAt)}</span>
                    </div>
                    <p>{n.body}</p>
                    <button type="button" className="lv-tasks-linkish" disabled={disabled} onClick={() => void removeNote(n)}>
                      Delete
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {tab === "Dependencies" ? (
          <div className="lv-tasks-tab-panel">
            <div className="lv-tasks-inline-form">
              <select value={depTarget} disabled={disabled} onChange={(e) => setDepTarget(e.target.value)}>
                <option value="">Depends on…</option>
                {allTasks
                  .filter((t) => t.taskId !== task.taskId)
                  .map((t) => (
                    <option key={t.taskId} value={t.taskId}>
                      {t.title}
                    </option>
                  ))}
              </select>
              <button type="button" className="lv-tasks-btn lv-tasks-btn--outline" disabled={disabled || !depTarget} onClick={() => void addDep()}>
                Add
              </button>
            </div>
            {deps.length === 0 ? (
              <p className="lv-tasks-empty">Geen dependencies</p>
            ) : (
              <ul className="lv-tasks-deps">
                {deps.map((d) => (
                  <li key={d.dependencyId}>
                    <span>
                      {d.dependsOn?.title || d.dependsOnTaskId}
                      {d.dependsOn?.completed ? " · done" : ""}
                      {d.soft ? " · soft" : ""}
                    </span>
                    <button type="button" className="lv-tasks-linkish" disabled={disabled} onClick={() => void removeDep(d)}>
                      Remove
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}

        {tab === "Activity" ? (
          <div className="lv-tasks-tab-panel">
            {events.length === 0 ? (
              <p className="lv-tasks-empty">Geen activity</p>
            ) : (
              <ul className="lv-tasks-activity-list">
                {events.map((ev) => (
                  <li key={ev.eventId}>
                    <span className="lv-tasks-feed-time">{formatRelative(ev.createdAt)}</span>
                    <div>
                      <strong>{formatEventLabel(ev.eventType)}</strong>
                      {ev.actorType ? <span> · {ev.actorType}</span> : null}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ) : null}
      </div>

      <div className="lv-tasks-details-foot">
        <div className="lv-tasks-assign-wrap">
          <button
            type="button"
            className="lv-tasks-btn lv-tasks-btn--outline"
            disabled={disabled}
            onClick={() => setAssignOpen((v) => !v)}
          >
            Assign Agent
          </button>
          {assignOpen ? (
            <div className="lv-tasks-assign-menu">
              <button
                type="button"
                onClick={() => {
                  setAssignOpen(false);
                  onAssign(task, null);
                }}
              >
                Unassigned
              </button>
              {agents.map((a) => (
                <button
                  key={a.agentId}
                  type="button"
                  onClick={() => {
                    setAssignOpen(false);
                    onAssign(task, a.agentId);
                  }}
                >
                  {a.name}
                </button>
              ))}
            </div>
          ) : null}
        </div>
        {canStartTask(task) ? (
          <button type="button" className="lv-tasks-btn lv-tasks-btn--neutral" disabled={disabled} onClick={() => onStart(task)}>
            <IconPlay />
            Start
          </button>
        ) : null}
        {canCancelTask(task) ? (
          <button type="button" className="lv-tasks-btn lv-tasks-btn--neutral" disabled={disabled} onClick={() => onCancel(task)}>
            <IconStop />
            Cancel
          </button>
        ) : null}
        {canCompleteTask(task) ? (
          <button type="button" className="lv-tasks-btn lv-tasks-btn--gold" disabled={disabled} onClick={() => onComplete(task)}>
            <IconCheck />
            Complete
          </button>
        ) : null}
      </div>
    </aside>
  );
}
