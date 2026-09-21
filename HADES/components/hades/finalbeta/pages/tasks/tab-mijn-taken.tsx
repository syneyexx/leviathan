"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../../icons";
import {
  MY_TASK_CHIPS,
  listStatusLabel,
  listStatusOf,
  mockMySummary,
  type FinalBetaKanbanTask,
  type MyTaskChip,
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

function sepDay(deadline: string): number | null {
  const m = deadline.match(/^(\d{1,2})\s+sep/i);
  return m ? Number(m[1]) : null;
}

function isToday(deadline: string) {
  return sepDay(deadline) === 17;
}

function isOverdue(deadline: string) {
  const day = sepDay(deadline);
  return day !== null && day < 17;
}

function isUpcoming(deadline: string) {
  const day = sepDay(deadline);
  return day !== null && day > 17 && day <= 30;
}

function isThisWeek(deadline: string) {
  const day = sepDay(deadline);
  // Week of Mon 14 – Sun 20 Sep 2026 (contains today 17)
  return day !== null && day >= 14 && day <= 20;
}

export function TasksTabMijnTaken({ tasks, selectedId, onSelect }: Props) {
  const [chip, setChip] = useState<MyTaskChip>("Vandaag");
  const mine = useMemo(() => tasks.filter((t) => t.mine === true), [tasks]);

  const filtered = useMemo(() => {
    if (chip === "Vandaag") return mine.filter((t) => isToday(t.deadline) || (t.column === "running" && !t.blocked));
    if (chip === "Aankomend") return mine.filter((t) => isUpcoming(t.deadline) && t.column !== "done");
    if (chip === "Deze week") return mine.filter((t) => isThisWeek(t.deadline));
    if (chip === "Verlopen") return mine.filter((t) => isOverdue(t.deadline) && t.column !== "done");
    return mine.filter((t) => t.blocked);
  }, [mine, chip]);

  return (
    <div className="tasks-mine-tab">
      <div className="tasks-mine-summary">
        <article className="tasks-mine-card">
          <span className="tasks-mine-card-ico tone-gold">
            <FbIcon name="calendar" size={14} />
          </span>
          <div>
            <strong>{mockMySummary.today}</strong>
            <span>Taken vandaag</span>
          </div>
        </article>
        <article className="tasks-mine-card">
          <span className="tasks-mine-card-ico tone-red">
            <FbIcon name="clock" size={14} />
          </span>
          <div>
            <strong>{mockMySummary.overdue}</strong>
            <span>Verlopen</span>
          </div>
        </article>
        <article className="tasks-mine-card">
          <span className="tasks-mine-card-ico tone-amber">
            <FbIcon name="shield" size={14} />
          </span>
          <div>
            <strong>{mockMySummary.blocked}</strong>
            <span>Geblokkeerd</span>
          </div>
        </article>
        <article className="tasks-mine-card">
          <span className="tasks-mine-card-ico tone-green">
            <FbIcon name="checkcircle" size={14} />
          </span>
          <div>
            <strong>{mockMySummary.completionPct}%</strong>
            <span>Voltooiingsgraad</span>
          </div>
        </article>
      </div>

      <div className="tasks-mine-chips" role="tablist" aria-label="Persoonlijke filters">
        {MY_TASK_CHIPS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            aria-selected={chip === item}
            className={`tasks-mine-chip${chip === item ? " active" : ""}`}
            onClick={() => setChip(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="tasks-table-wrap card">
        <table className="tasks-table tasks-mine-table">
          <thead>
            <tr>
              <th className="col-check" aria-label="Selecteer" />
              <th>Taak</th>
              <th>Status</th>
              <th>Prioriteit</th>
              <th>Deadline</th>
              <th>Geschatte tijd</th>
              <th>Afhankelijkheden</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((task) => {
              const status = listStatusOf(task);
              const active = task.id === selectedId;
              const depTitles = (task.dependencies ?? [])
                .map((id) => tasks.find((t) => t.id === id)?.title)
                .filter(Boolean);
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
                        <FbIcon name="check" size={12} />
                      </span>
                      <span>{task.title}</span>
                    </button>
                  </td>
                  <td>
                    <span className={`tasks-status-pill ${status}`}>{listStatusLabel(status)}</span>
                  </td>
                  <td>
                    <span className={`tasks-prio-pill ${priorityClass(task.priority)}`}>{task.priority}</span>
                  </td>
                  <td className="tasks-deadline-cell">{task.deadline}</td>
                  <td>{task.estimatedTime ?? "—"}</td>
                  <td className="tasks-deps-cell">
                    {depTitles.length ? depTitles.join(", ") : <span className="muted">Geen</span>}
                  </td>
                </tr>
              );
            })}
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={7} className="tasks-table-empty">
                  Geen taken in dit filter.
                </td>
              </tr>
            ) : null}
          </tbody>
        </table>
      </div>
    </div>
  );
}
