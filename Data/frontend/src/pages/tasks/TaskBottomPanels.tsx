import { useMemo, useState } from "react";
import type {
  TaskAgentActivity,
  TaskEvent,
  TaskTimelineItem,
  TaskWeekdayCompletions,
  TaskWorkloadEntry,
} from "../../types/api";
import {
  avatarTone,
  eventTone,
  formatEventLabel,
  formatRelative,
  initials,
  timelineTone,
  workloadTone,
} from "./taskUtils";

type Props = {
  timeline: TaskTimelineItem[];
  timelineView: "today" | "week" | "calendar";
  onTimelineView: (view: "today" | "week" | "calendar") => void;
  agentActivity: TaskAgentActivity[];
  activity: TaskEvent[];
  weekday: TaskWeekdayCompletions | null;
  workload: TaskWorkloadEntry[];
  onSelectTask?: (taskId: string) => void;
};

const HOURS = ["6 AM", "9 AM", "12 PM", "3 PM", "6 PM", "9 PM"];

export function TaskBottomPanels({
  timeline,
  timelineView,
  onTimelineView,
  agentActivity,
  activity,
  weekday,
  workload,
  onSelectTask,
}: Props) {
  const [feedFilter, setFeedFilter] = useState("all");

  const timelineMeta = useMemo(() => {
    const now = new Date();
    if (timelineView === "today") {
      return now.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric", year: "numeric" });
    }
    if (timelineView === "week") return "This week";
    return now.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  }, [timelineView]);

  const timelineRows = useMemo(() => {
    // Group by title as row label; place blocks by hour-of-day for today, else sequential.
    return timeline.slice(0, 12).map((item, index) => {
      const start = item.startAt ? new Date(item.startAt) : null;
      let startSlot = index % 4;
      let span = 2;
      if (start && !Number.isNaN(start.getTime()) && timelineView === "today") {
        const hour = start.getHours() + start.getMinutes() / 60;
        startSlot = Math.max(0, Math.min(5, (hour - 6) / 3));
        if (item.endAt) {
          const end = new Date(item.endAt);
          if (!Number.isNaN(end.getTime())) {
            const endHour = end.getHours() + end.getMinutes() / 60;
            span = Math.max(0.5, Math.min(6, (endHour - 6) / 3 - startSlot));
          }
        }
      }
      return {
        ...item,
        startSlot,
        span,
        tone: timelineTone(item.boardColumn, item.blocked),
      };
    });
  }, [timeline, timelineView]);

  const filteredActivity = useMemo(() => {
    if (feedFilter === "agents") {
      return activity.filter((a) => (a.actorType || "").toLowerCase().includes("agent"));
    }
    if (feedFilter === "humans") {
      return activity.filter((a) => {
        const t = (a.actorType || "").toLowerCase();
        return t.includes("operator") || t.includes("human") || t === "user";
      });
    }
    return activity;
  }, [activity, feedFilter]);

  const bars = weekday?.bars ?? [0, 0, 0, 0, 0, 0, 0];
  const weekdays = weekday?.weekdays ?? ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const maxBar = Math.max(1, ...bars);
  const completionRate = useMemo(() => {
    const total = bars.reduce((a, b) => a + b, 0);
    if (total === 0) return 0;
    // Honest rate proxy: share of weekday capacity filled vs peak day (not a fake KPI).
    return Math.round((bars.reduce((a, b) => a + b, 0) / (maxBar * 7)) * 100);
  }, [bars, maxBar]);

  const maxWorkload = Math.max(1, ...workload.map((w) => w.activeCount), 1);

  return (
    <div className="lv-tasks-bottom-grid">
      <section className="lv-tasks-panel lv-tasks-timeline">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Execution Timeline</span>
          <div className="lv-tasks-panel-actions">
            <div className="lv-tasks-mini-tabs">
              {(
                [
                  ["Today", "today"],
                  ["This Week", "week"],
                  ["Calendar", "calendar"],
                ] as const
              ).map(([label, view]) => (
                <button
                  key={view}
                  type="button"
                  className={`lv-tasks-mini-tab${timelineView === view ? " is-active" : ""}`}
                  onClick={() => onTimelineView(view)}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        </header>
        <div className="lv-tasks-panel-body">
          <div className="lv-tasks-timeline-meta">
            <span>{timelineMeta}</span>
          </div>
          {timelineRows.length === 0 ? (
            <p className="lv-tasks-empty">Geen taken</p>
          ) : (
            <>
              <div className="lv-tasks-timeline-hours">
                <span>name</span>
                {HOURS.map((h) => (
                  <span key={h}>{h}</span>
                ))}
              </div>
              {timelineRows.map((row) => (
                <button
                  key={`${row.taskId}-${row.kind}-${row.startAt}`}
                  type="button"
                  className="lv-tasks-timeline-row"
                  onClick={() => onSelectTask?.(row.taskId)}
                >
                  <div className="lv-tasks-timeline-name">
                    <span className={`lv-tasks-avatar ${avatarTone(row.title)}`}>{initials(row.title)}</span>
                    {row.title}
                  </div>
                  <div className="lv-tasks-timeline-track">
                    <div
                      className={`lv-tasks-timeline-block lv-tasks-timeline-block--${row.tone}`}
                      style={{
                        left: `${(row.startSlot / 6) * 100}%`,
                        width: `${(row.span / 6) * 100}%`,
                      }}
                    >
                      {row.kind}
                    </div>
                  </div>
                </button>
              ))}
            </>
          )}
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-agent-activity">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Agent Activity</span>
        </header>
        <div className="lv-tasks-panel-body">
          {agentActivity.length === 0 ? (
            <p className="lv-tasks-empty">Geen agent activity</p>
          ) : (
            agentActivity.map((agent) => {
              const tone =
                agent.status === "running" || agent.status === "busy"
                  ? "cyan"
                  : agent.status === "error" || agent.status === "failed"
                    ? "red"
                    : "green";
              const progressPct =
                agent.progress != null
                  ? agent.progress > 1
                    ? Math.round(agent.progress)
                    : Math.round(agent.progress * 100)
                  : null;
              return (
                <button
                  key={agent.agentId}
                  type="button"
                  className="lv-tasks-agent-row"
                  onClick={() => agent.activeTaskId && onSelectTask?.(agent.activeTaskId)}
                >
                  <div className={`lv-tasks-agent-avatar lv-tasks-avatar ${avatarTone(agent.name)} is-${tone}`}>
                    {initials(agent.name)}
                  </div>
                  <div className="lv-tasks-agent-main">
                    <div className="lv-tasks-agent-name">{agent.name}</div>
                    <div className="lv-tasks-agent-status">
                      {agent.status}
                      {progressPct != null ? ` · ${progressPct}%` : ""}
                      {agent.activeTaskCount ? ` · ${agent.activeTaskCount} tasks` : ""}
                    </div>
                    <div className="lv-tasks-agent-detail">{agent.detail || agent.phase || "—"}</div>
                  </div>
                  <div className="lv-tasks-agent-ago">{formatRelative(agent.lastRunAt)}</div>
                </button>
              );
            })
          )}
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-feed">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Console / Activity Feed</span>
          <div className="lv-tasks-panel-actions">
            <span className="lv-tasks-live">Live</span>
            <select
              className="lv-tasks-select"
              value={feedFilter}
              aria-label="Feed filter"
              onChange={(e) => setFeedFilter(e.target.value)}
            >
              <option value="all">All</option>
              <option value="agents">Agents</option>
              <option value="humans">Humans</option>
            </select>
          </div>
        </header>
        <div className="lv-tasks-panel-body">
          {filteredActivity.length === 0 ? (
            <p className="lv-tasks-empty">Geen activity</p>
          ) : (
            filteredActivity.map((item) => (
              <button
                key={item.eventId}
                type="button"
                className="lv-tasks-feed-row"
                onClick={() => onSelectTask?.(item.taskId)}
              >
                <span className="lv-tasks-feed-time">{formatRelative(item.createdAt)}</span>
                <span className={`lv-tasks-feed-dot lv-tasks-feed-dot--${eventTone(item.eventType)}`} />
                <div className="lv-tasks-feed-text">
                  <strong>{item.actorType || "system"}</strong>
                  <span> {formatEventLabel(item.eventType).toLowerCase()} </span>
                  {item.taskTitle ? <em>“{item.taskTitle}”</em> : null}
                </div>
              </button>
            ))
          )}
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-insights">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Productivity Insights</span>
        </header>
        <div className="lv-tasks-panel-body">
          <div className="lv-tasks-insights-top">
            <div className="lv-tasks-donut-wrap">
              <svg className="lv-tasks-donut" viewBox="0 0 78 78" aria-hidden="true">
                <circle cx="39" cy="39" r="30" fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="7" />
                <circle
                  cx="39"
                  cy="39"
                  r="30"
                  fill="none"
                  stroke="#00bfea"
                  strokeWidth="7"
                  strokeLinecap="round"
                  strokeDasharray={`${2 * Math.PI * 30 * (completionRate / 100)} ${2 * Math.PI * 30}`}
                  transform="rotate(-90 39 39)"
                />
              </svg>
              <div className="lv-tasks-donut-center">
                <span className="lv-tasks-donut-pct">{completionRate}%</span>
                <span className="lv-tasks-donut-label">Week Fill</span>
              </div>
            </div>
            <div className="lv-tasks-weekday-chart">
              {weekdays.map((day, index) => (
                <div key={day} className="lv-tasks-weekday-col">
                  <div
                    className="lv-tasks-weekday-bar"
                    style={{ height: `${Math.round((bars[index] / maxBar) * 100)}%` }}
                    title={`${bars[index]} completed`}
                  />
                  <span className="lv-tasks-weekday-label">{day}</span>
                </div>
              ))}
            </div>
          </div>
          <h4 className="lv-tasks-workload-title">Workload by Assignee</h4>
          {workload.length === 0 ? (
            <p className="lv-tasks-empty">Geen workload</p>
          ) : (
            workload.map((row, index) => (
              <div key={`${row.assigneeId ?? row.assigneeName}-${index}`} className="lv-tasks-workload-row">
                <span className="lv-tasks-workload-name">{row.assigneeName}</span>
                <div className="lv-tasks-workload-track">
                  <div
                    className={`lv-tasks-workload-fill lv-tasks-workload-fill--${workloadTone(index)}`}
                    style={{ width: `${(row.activeCount / maxWorkload) * 100}%` }}
                  />
                </div>
                <span className="lv-tasks-workload-count">{row.activeCount}</span>
              </div>
            ))
          )}
        </div>
      </section>
    </div>
  );
}
