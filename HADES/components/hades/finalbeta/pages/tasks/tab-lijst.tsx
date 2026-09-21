"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../../icons";
import {
  LIST_STATUS_FILTERS,
  listStatusLabel,
  listStatusOf,
  type FinalBetaKanbanTask,
  type TaskListStatus,
  type TaskPriority,
} from "../../mocks/tasks";

type Props = {
  tasks: FinalBetaKanbanTask[];
  selectedId: string;
  onSelect: (id: string) => void;
};

function priorityClass(priority: TaskPriority) {
  if (priority === "Hoog") return "high";
  if (priority === "Medium") return "medium";
  return "low";
}

function taskIcon(task: FinalBetaKanbanTask): "database" | "code" | "flask" | "chart" | "file" {
  const tone = task.projectTone;
  if (tone === "data") return "database";
  if (tone === "development") return "code";
  if (tone === "research") return "flask";
  if (tone === "trading") return "chart";
  return "file";
}

export function TasksTabLijst({ tasks, selectedId, onSelect }: Props) {
  const [statusFilter, setStatusFilter] = useState<"all" | TaskListStatus>("all");

  const counts = useMemo(() => {
    const base: Record<"all" | TaskListStatus, number> = {
      all: tasks.length,
      open: 0,
      running: 0,
      review: 0,
      done: 0,
      blocked: 0,
    };
    for (const task of tasks) base[listStatusOf(task)] += 1;
    return base;
  }, [tasks]);

  const rows = useMemo(() => {
    if (statusFilter === "all") return tasks;
    return tasks.filter((task) => listStatusOf(task) === statusFilter);
  }, [tasks, statusFilter]);

  return (
    <div className="tasks-lijst-tab">
      <div className="tasks-status-filters" role="tablist" aria-label="Statusfilter">
        {LIST_STATUS_FILTERS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={statusFilter === item.id}
            className={`tasks-status-chip${statusFilter === item.id ? " active" : ""}`}
            onClick={() => setStatusFilter(item.id)}
          >
            {item.label}
            <span className="tasks-status-chip-count">{counts[item.id]}</span>
          </button>
        ))}
      </div>

      <div className="tasks-table-wrap card">
        <table className="tasks-table">
          <thead>
            <tr>
              <th className="col-check" aria-label="Selecteer" />
              <th>Taaknaam</th>
              <th>Project</th>
              <th>Eigenaar</th>
              <th>Prioriteit</th>
              <th>Status</th>
              <th>Deadline</th>
              <th>Voortgang</th>
              <th>Labels</th>
              <th className="col-actions" aria-label="Acties" />
            </tr>
          </thead>
          <tbody>
            {rows.map((task) => {
              const status = listStatusOf(task);
              const active = task.id === selectedId;
              return (
                <tr
                  key={task.id}
                  className={active ? "active" : undefined}
                  onClick={() => onSelect(task.id)}
                >
                  <td className="col-check" onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" aria-label={`Selecteer ${task.title}`} />
                  </td>
                  <td>
                    <button type="button" className="tasks-table-name" onClick={() => onSelect(task.id)}>
                      <span className={`tasks-row-ico tone-${task.projectTone ?? "development"}`}>
                        <FbIcon name={taskIcon(task)} size={12} />
                      </span>
                      <span>{task.title}</span>
                    </button>
                  </td>
                  <td>
                    <span className={`tasks-project-pill tone-${task.projectTone ?? "development"}`}>
                      {task.project ?? "—"}
                    </span>
                  </td>
                  <td>
                    <span className="tasks-owner-cell">
                      <FbIcon name="user" size={11} />
                      {task.owner}
                    </span>
                  </td>
                  <td>
                    <span className={`tasks-prio-pill ${priorityClass(task.priority)}`}>{task.priority}</span>
                  </td>
                  <td>
                    <span className={`tasks-status-pill ${status}`}>{listStatusLabel(status)}</span>
                  </td>
                  <td className="tasks-deadline-cell">{task.deadline}</td>
                  <td>
                    <div className="tasks-table-progress">
                      <div className="tasks-progress-bar">
                        <i style={{ width: `${task.progress ?? (status === "done" ? 100 : 0)}%` }} />
                      </div>
                      <span>{task.progress ?? (status === "done" ? 100 : 0)}%</span>
                    </div>
                  </td>
                  <td>
                    <div className="tasks-table-labels">
                      {task.tags.slice(0, 2).map((tag) => (
                        <span key={tag} className="tag">
                          {tag}
                        </span>
                      ))}
                    </div>
                  </td>
                  <td className="col-actions" onClick={(e) => e.stopPropagation()}>
                    <button type="button" className="tasks-row-more" aria-label="Acties" data-toast="Acties">
                      <FbIcon name="more" size={14} />
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
