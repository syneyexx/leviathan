import { useEffect, useRef, useState } from "react";
import type { TaskBoardColumn, TaskRecord } from "../../types/api";
import { IconMore, ProgressRing } from "./TaskIcons";
import {
  avatarTone,
  boardColumnLabel,
  canCancelTask,
  canCompleteTask,
  canRetryTask,
  canStartTask,
  COLUMN_ORDER,
  displayProgressPct,
  formatDue,
  initials,
  priorityClass,
  priorityLabel,
} from "./taskUtils";

export type TaskCardAction =
  | "open"
  | "move"
  | "start"
  | "cancel"
  | "retry"
  | "duplicate"
  | "archive"
  | "complete";

type Props = {
  task: TaskRecord;
  selected: boolean;
  busy?: boolean;
  onSelect: (taskId: string) => void;
  onAction: (action: TaskCardAction, task: TaskRecord, boardColumn?: TaskBoardColumn) => void;
};

export function TaskCard({ task, selected, busy, onSelect, onAction }: Props) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const pct = displayProgressPct(task);
  const assignee = task.assigneeName || (task.assigneeType === "none" ? "Unassigned" : task.assigneeId || "—");
  const tag = task.tags?.[0] || task.project || task.executionBinding || "Task";

  useEffect(() => {
    if (!menuOpen) return;
    const onDoc = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div className={`lv-tasks-card-wrap${selected ? " is-selected" : ""}`}>
      <button
        type="button"
        className={`lv-tasks-card${selected ? " is-selected" : ""}`}
        onClick={() => onSelect(task.taskId)}
        disabled={busy}
      >
        <div className="lv-tasks-card-top">
          <h3 className="lv-tasks-card-title">{task.title}</h3>
          <span
            className="lv-tasks-card-menu"
            role="presentation"
            onClick={(e) => {
              e.stopPropagation();
              setMenuOpen((v) => !v);
            }}
          >
            <IconMore />
          </span>
        </div>
        <div className="lv-tasks-card-badges">
          <span className={`lv-tasks-badge ${priorityClass(task.priority)}`}>{priorityLabel(task.priority)}</span>
          <span className="lv-tasks-badge lv-tasks-badge--tag">{tag}</span>
          {task.blocked ? <span className="lv-tasks-badge lv-tasks-badge--blocked">Blocked</span> : null}
        </div>
        <p className="lv-tasks-card-desc">{task.description || "No description"}</p>
        <div className="lv-tasks-card-foot">
          <div className="lv-tasks-card-assignee">
            <span className={`lv-tasks-avatar ${avatarTone(assignee)}`}>{initials(assignee)}</span>
            <span>{assignee}</span>
          </div>
          <div className="lv-tasks-card-meta">
            <span className="lv-tasks-card-date">{formatDue(task.dueAt)}</span>
            <ProgressRing value={pct} />
          </div>
        </div>
      </button>
      {menuOpen ? (
        <div className="lv-tasks-card-dropdown" ref={menuRef} role="menu">
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              onAction("open", task);
            }}
          >
            Open
          </button>
          {COLUMN_ORDER.filter((c) => c !== task.boardColumn).map((col) => (
            <button
              key={col}
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAction("move", task, col);
              }}
            >
              Move to {boardColumnLabel(col)}
            </button>
          ))}
          {canStartTask(task) ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAction("start", task);
              }}
            >
              Start
            </button>
          ) : null}
          {canCancelTask(task) ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAction("cancel", task);
              }}
            >
              Cancel
            </button>
          ) : null}
          {canRetryTask(task) ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAction("retry", task);
              }}
            >
              Retry
            </button>
          ) : null}
          {canCompleteTask(task) ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => {
                setMenuOpen(false);
                onAction("complete", task);
              }}
            >
              Complete
            </button>
          ) : null}
          <button
            type="button"
            role="menuitem"
            onClick={() => {
              setMenuOpen(false);
              onAction("duplicate", task);
            }}
          >
            Duplicate
          </button>
          <button
            type="button"
            role="menuitem"
            className="is-danger"
            onClick={() => {
              setMenuOpen(false);
              onAction("archive", task);
            }}
          >
            Archive
          </button>
        </div>
      ) : null}
    </div>
  );
}
