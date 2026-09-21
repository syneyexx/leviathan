"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../../icons";
import {
  TIMELINE_MONTHS,
  TIMELINE_TOTAL_DAYS,
  type FinalBetaKanbanTask,
  type TimelineGroup,
  type TimelineItem,
} from "../../mocks/tasks";

type Props = {
  tasks: FinalBetaKanbanTask[];
};

const COLUMN_META: Array<{ id: string; title: string; color: string }> = [
  { id: "open", title: "Open", color: "#1aa4ff" },
  { id: "running", title: "Running", color: "#f0b429" },
  { id: "review", title: "Review", color: "#9b5cff" },
  { id: "done", title: "Done", color: "#20e38d" },
];

const EPOCH = Date.UTC(2026, 8, 1); // 1 Sep 2026

function dayOffset(isoLike: string | undefined): number | null {
  if (!isoLike || isoLike === "—") return null;
  const t = Date.parse(isoLike);
  if (Number.isNaN(t)) {
    // try nl short dates already formatted — fall back null
    return null;
  }
  const days = Math.floor((t - EPOCH) / 86_400_000) + 1;
  return Math.max(1, Math.min(TIMELINE_TOTAL_DAYS, days));
}

function shortLabel(day: number): string {
  const d = new Date(EPOCH + (day - 1) * 86_400_000);
  return d.toLocaleDateString("nl-NL", { day: "numeric", month: "short" });
}

function todayDay(): number {
  const days = Math.floor((Date.now() - EPOCH) / 86_400_000) + 1;
  return Math.max(1, Math.min(TIMELINE_TOTAL_DAYS, days));
}

function toTimelineItem(task: FinalBetaKanbanTask, index: number): TimelineItem {
  const start = dayOffset(task.created) ?? Math.min(TIMELINE_TOTAL_DAYS - 7, 1 + index * 3);
  const endRaw = dayOffset(task.deadline);
  const end = endRaw != null && endRaw >= start ? endRaw : Math.min(TIMELINE_TOTAL_DAYS, start + 7);
  const color =
    task.column === "done"
      ? "#20e38d"
      : task.column === "running"
        ? "#f0b429"
        : task.column === "review"
          ? "#9b5cff"
          : "#1aa4ff";
  const kind = task.column === "review" && /fail|block/i.test(task.tags.join(" ")) ? "blocker" : "task";
  return {
    id: task.id,
    title: task.title,
    kind,
    startLabel: shortLabel(start),
    endLabel: shortLabel(end),
    startDay: start,
    endDay: end,
    progress: typeof task.progress === "number" ? task.progress : task.column === "done" ? 100 : task.column === "running" ? 50 : 0,
    color,
  };
}

function tasksToGroups(tasks: FinalBetaKanbanTask[]): TimelineGroup[] {
  return COLUMN_META.map((col) => ({
    id: col.id,
    title: col.title,
    items: tasks.filter((t) => t.column === col.id).map((t, i) => toTimelineItem(t, i)),
  })).filter((g) => g.items.length > 0);
}

function pct(day: number) {
  const clamped = Math.max(0, Math.min(TIMELINE_TOTAL_DAYS, day));
  return (clamped / TIMELINE_TOTAL_DAYS) * 100;
}

function barStyle(item: TimelineItem) {
  const start = Math.max(0, item.startDay);
  const end = Math.max(start + 0.5, item.endDay);
  const left = pct(start);
  const width = Math.max(0.8, pct(end) - pct(start));
  return { left: `${left}%`, width: `${width}%`, background: `${item.color}33`, borderColor: item.color };
}

export function TasksTabTijdlijn({ tasks }: Props) {
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});
  const [zoom, setZoom] = useState(1);
  const groups = useMemo(() => tasksToGroups(tasks), [tasks]);
  const today = todayDay();

  const toggle = (id: string) => setCollapsed((prev) => ({ ...prev, [id]: !prev[id] }));

  return (
    <div className="tasks-tijdlijn-tab" data-live="tasks-tijdlijn">
      <header className="tasks-gantt-toolbar">
        <div className="tasks-gantt-title">
          <strong>Tijdlijn</strong>
          <span className="muted">Live taken · Sep – Dec 2026</span>
        </div>
        <div className="tasks-gantt-zoom">
          <button
            type="button"
            className="tasks-gantt-icon-btn"
            aria-label="Zoom uit"
            onClick={() => setZoom((z) => Math.max(0.75, Number((z - 0.1).toFixed(2))))}
          >
            <FbIcon name="search" size={13} />
            <span className="tasks-gantt-zoom-sign">−</span>
          </button>
          <button
            type="button"
            className="tasks-gantt-icon-btn"
            aria-label="Zoom in"
            onClick={() => setZoom((z) => Math.min(1.5, Number((z + 0.1).toFixed(2))))}
          >
            <FbIcon name="search" size={13} />
            <span className="tasks-gantt-zoom-sign">+</span>
          </button>
        </div>
      </header>

      {!groups.length ? (
        <div className="card" style={{ padding: 16 }}>
          <p className="muted">Geen taken voor de tijdlijn. Maak of start een taak in Kanban.</p>
        </div>
      ) : (
        <div className="tasks-gantt card" style={{ ["--gantt-zoom" as string]: String(zoom) }}>
          <div className="tasks-gantt-left">
            <div className="tasks-gantt-left-head">
              <span>Taak / Mijlpaal</span>
              <span>Start</span>
              <span>Einde</span>
            </div>
            {groups.map((group) => {
              const isCollapsed = Boolean(collapsed[group.id]);
              return (
                <div key={group.id} className="tasks-gantt-group">
                  <button type="button" className="tasks-gantt-group-head" onClick={() => toggle(group.id)}>
                    <FbIcon name="chevron" size={11} style={{ transform: isCollapsed ? undefined : "rotate(90deg)" }} />
                    <strong>{group.title}</strong>
                    <em>{group.items.length}</em>
                  </button>
                  {!isCollapsed
                    ? group.items.map((item) => (
                        <div key={item.id} className={`tasks-gantt-row meta kind-${item.kind}`}>
                          <span className="tasks-gantt-name">
                            {item.kind === "milestone" || item.kind === "blocker" ? (
                              <i className={`tasks-gantt-diamond ${item.kind}`} />
                            ) : (
                              <i className="tasks-gantt-bar-dot" style={{ background: item.color }} />
                            )}
                            {item.title}
                          </span>
                          <span>{item.startLabel}</span>
                          <span>{item.endLabel}</span>
                        </div>
                      ))
                    : null}
                </div>
              );
            })}
          </div>

          <div className="tasks-gantt-right">
            <div className="tasks-gantt-months">
              {TIMELINE_MONTHS.map((month) => (
                <div
                  key={month.label}
                  className="tasks-gantt-month"
                  style={{ width: `${(month.days / TIMELINE_TOTAL_DAYS) * 100}%` }}
                >
                  {month.label} 2026
                </div>
              ))}
            </div>
            <div className="tasks-gantt-days">
              {Array.from({ length: 16 }, (_, i) => (
                <span key={i} style={{ left: `${(i / 15) * 100}%` }} />
              ))}
            </div>

            <div className="tasks-gantt-today" style={{ left: `${pct(today)}%` }}>
              <span>Vandaag</span>
            </div>

            <div className="tasks-gantt-chart-body">
              {groups.map((group) => {
                if (collapsed[group.id]) return null;
                return (
                  <div key={group.id} className="tasks-gantt-chart-group">
                    <div className="tasks-gantt-chart-spacer" />
                    {group.items.map((item) => {
                      if (item.kind === "milestone" || item.kind === "blocker") {
                        return (
                          <div key={item.id} className="tasks-gantt-chart-row">
                            <span
                              className={`tasks-gantt-milestone ${item.kind}`}
                              style={{ left: `${pct(item.startDay)}%`, borderColor: item.color, background: item.color }}
                              title={item.title}
                            />
                          </div>
                        );
                      }
                      const style = barStyle(item);
                      return (
                        <div key={item.id} className="tasks-gantt-chart-row">
                          <div className="tasks-gantt-bar" style={style} title={`${item.title} · ${item.progress}%`}>
                            <i style={{ width: `${item.progress}%`, background: item.color }} />
                            <span>{item.progress}%</span>
                          </div>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      <footer className="tasks-gantt-legend">
        <span>
          <i className="lg-task" /> Task
        </span>
        <span>
          <i className="lg-ms" /> Milestone
        </span>
        <span>
          <i className="lg-blocker" /> Blocker
        </span>
        <span>
          <i className="lg-today" /> Current Date
        </span>
      </footer>
    </div>
  );
}
