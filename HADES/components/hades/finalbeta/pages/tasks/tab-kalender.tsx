"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../../icons";
import {
  mockMonthStats,
  mockSprintMilestones,
  mockUpcomingDeadlines,
  type FinalBetaKanbanTask,
  type TaskProjectTone,
} from "../../mocks/tasks";

type Props = {
  tasks: FinalBetaKanbanTask[];
  selectedId: string;
  onSelect: (id: string) => void;
};

const WEEKDAYS = ["Ma", "Di", "Wo", "Do", "Vr", "Za", "Zo"];
const MONTH_OPTIONS = ["September 2026", "Oktober 2026", "November 2026", "December 2026"] as const;

/** September 2026 starts on Tuesday → Monday-grid offset = 1 */
const SEP_2026_OFFSET = 1;
const SEP_2026_DAYS = 30;
const TODAY = 17;

function toneClass(tone: TaskProjectTone | undefined) {
  return `tone-${tone ?? "development"}`;
}

export function TasksTabKalender({ tasks, selectedId, onSelect }: Props) {
  const [monthLabel, setMonthLabel] = useState<(typeof MONTH_OPTIONS)[number]>("September 2026");

  const byDay = useMemo(() => {
    const map = new Map<number, FinalBetaKanbanTask[]>();
    for (const task of tasks) {
      const day = task.calDay;
      if (!day || day < 1 || day > SEP_2026_DAYS) continue;
      const list = map.get(day) ?? [];
      list.push(task);
      map.set(day, list);
    }
    return map;
  }, [tasks]);

  const cells = useMemo(() => {
    const total = SEP_2026_OFFSET + SEP_2026_DAYS;
    const weeks = Math.ceil(total / 7) * 7;
    return Array.from({ length: weeks }, (_, i) => {
      const day = i - SEP_2026_OFFSET + 1;
      if (day < 1 || day > SEP_2026_DAYS) return null;
      return day;
    });
  }, []);

  return (
    <div className="tasks-kalender-tab">
      <aside className="tasks-cal-sidebar">
        <section className="tasks-cal-widget card">
          <header className="tasks-cal-widget-head">
            <strong>Komende deadlines</strong>
          </header>
          <ul className="tasks-cal-deadlines">
            {mockUpcomingDeadlines.map((item) => (
              <li key={item.id}>
                <button type="button" className="tasks-cal-deadline" onClick={() => onSelect(item.id)}>
                  <span className={`tasks-cal-dot ${toneClass(item.tone)}`} />
                  <span className="tasks-cal-deadline-copy">
                    <strong>{item.title}</strong>
                    <small>{item.when}</small>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <section className="tasks-cal-widget card">
          <header className="tasks-cal-widget-head">
            <strong>Sprint mijlpalen</strong>
          </header>
          <div className="tasks-cal-sprints">
            {mockSprintMilestones.map((item) => (
              <div key={item.id} className="tasks-cal-sprint">
                <div className="tasks-cal-sprint-top">
                  <span>{item.title}</span>
                  <em>{item.progress}%</em>
                </div>
                <div className={`tasks-progress-bar tone-${item.tone}`}>
                  <i style={{ width: `${item.progress}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="tasks-cal-widget card">
          <header className="tasks-cal-widget-head">
            <strong>Statistieken deze maand</strong>
          </header>
          <div className="tasks-cal-stats">
            <div className="tasks-cal-stat">
              <span className="tasks-cal-ring">
                <b>{mockMonthStats.planned}</b>
              </span>
              <small>Gepland</small>
            </div>
            <div className="tasks-cal-stat">
              <span className="tasks-cal-ring green">
                <b>{mockMonthStats.completed}</b>
              </span>
              <small>Gereed</small>
            </div>
            <div className="tasks-cal-stat">
              <span className="tasks-cal-ring red">
                <b>{mockMonthStats.blocked}</b>
              </span>
              <small>Geblokkeerd</small>
            </div>
            <div className="tasks-cal-stat">
              <span className="tasks-cal-ring cyan">
                <b>{mockMonthStats.hoursLogged}</b>
              </span>
              <small>Uren</small>
            </div>
          </div>
        </section>
      </aside>

      <section className="tasks-cal-main card">
        <header className="tasks-cal-toolbar">
          <div className="tasks-cal-nav">
            <button type="button" className="tasks-cal-today-btn" data-toast="Vandaag">
              Vandaag
            </button>
            <button type="button" className="tasks-cal-nav-btn" aria-label="Vorige maand" data-toast="Vorige maand">
              <FbIcon name="chevron" size={14} style={{ transform: "rotate(180deg)" }} />
            </button>
            <button type="button" className="tasks-cal-nav-btn" aria-label="Volgende maand" data-toast="Volgende maand">
              <FbIcon name="chevron" size={14} />
            </button>
            <label className="tasks-cal-month-select">
              <span className="sr-only">Maand</span>
              <select
                value={monthLabel}
                onChange={(e) => setMonthLabel(e.target.value as (typeof MONTH_OPTIONS)[number])}
                aria-label="Maand selector"
              >
                {MONTH_OPTIONS.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </select>
              <FbIcon name="chevron" size={12} />
            </label>
          </div>
          <div className="tasks-cal-legend">
            <span className="tone-data">Data</span>
            <span className="tone-development">Development</span>
            <span className="tone-research">Research</span>
            <span className="tone-trading">Trading</span>
          </div>
        </header>

        <div className="tasks-cal-grid" role="grid" aria-label={monthLabel}>
          {WEEKDAYS.map((d) => (
            <div key={d} className="tasks-cal-weekday">
              {d}
            </div>
          ))}
          {cells.map((day, idx) => {
            if (day === null) {
              return <div key={`empty-${idx}`} className="tasks-cal-cell empty" />;
            }
            const dayTasks = byDay.get(day) ?? [];
            const isToday = day === TODAY;
            return (
              <div key={day} className={`tasks-cal-cell${isToday ? " today" : ""}`} role="gridcell">
                <div className="tasks-cal-daynum">{day}</div>
                <div className="tasks-cal-pills">
                  {dayTasks.slice(0, 3).map((task) => (
                    <button
                      key={task.id}
                      type="button"
                      className={`tasks-cal-pill ${toneClass(task.projectTone)}${task.id === selectedId ? " active" : ""}`}
                      onClick={() => onSelect(task.id)}
                      title={task.title}
                    >
                      {task.title}
                    </button>
                  ))}
                  {dayTasks.length > 3 ? <span className="tasks-cal-more">+{dayTasks.length - 3}</span> : null}
                </div>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
