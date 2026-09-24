import { useMemo, useState, type SVGProps } from "react";
import { AppShell } from "../layouts/AppShell";
import {
  ACTIVITY_FEED,
  AGENT_ACTIVITY,
  COLUMN_META,
  DEFAULT_SELECTED_TASK_ID,
  TASKS_CARDS,
  TASKS_KPIS,
  TIMELINE_ROWS,
  WEEKDAY_BARS,
  WEEKDAYS,
  WORKLOAD,
  type TaskCard,
  type TaskColumn,
  type TaskPriority,
} from "../mocks/tasksReferenceMock";
import "../styles/tasks-reference.css";

type IconProps = SVGProps<SVGSVGElement>;

function Svg(props: IconProps) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    />
  );
}

function IconLayers(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3 3 8l9 5 9-5-9-5Z" />
      <path d="m3 12 9 5 9-5" />
      <path d="m3 16 9 5 9-5" />
    </Svg>
  );
}

function IconProgress(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" strokeDasharray="6 4" />
      <path d="M12 8v4l2.5 1.5" />
    </Svg>
  );
}

function IconWarning(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 4 3.5 19h17L12 4Z" />
      <path d="M12 10v4" />
      <path d="M12 17h.01" />
    </Svg>
  );
}

function IconCheck(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="m8.5 12 2.5 2.5 4.5-5" />
    </Svg>
  );
}

function IconClock(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2" />
    </Svg>
  );
}

function IconRobot(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="5" y="8" width="14" height="11" rx="3" />
      <path d="M12 5v3" />
      <circle cx="9.5" cy="13" r="1" fill="currentColor" stroke="none" />
      <circle cx="14.5" cy="13" r="1" fill="currentColor" stroke="none" />
      <path d="M9 16.5h6" />
    </Svg>
  );
}

function IconSearch(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4 4" />
    </Svg>
  );
}

function IconBolt(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M13 3 6 13h5l-1 8 8-11h-5l0-7Z" />
    </Svg>
  );
}

function IconSparkle(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3v4M12 17v4M3 12h4M17 12h4" />
      <path d="m6.5 6.5 2.5 2.5M15 15l2.5 2.5M17.5 6.5 15 9M9 15l-2.5 2.5" />
      <circle cx="12" cy="12" r="2.2" />
    </Svg>
  );
}

function IconPlus(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 6v12M6 12h12" />
    </Svg>
  );
}

function IconMore(props: IconProps) {
  return (
    <Svg {...props}>
      <circle cx="6" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="12" cy="12" r="1.3" fill="currentColor" stroke="none" />
      <circle cx="18" cy="12" r="1.3" fill="currentColor" stroke="none" />
    </Svg>
  );
}

function IconClipboard(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="7" y="5" width="10" height="15" rx="2" />
      <path d="M9 5V4h6v1" />
      <path d="M10 10h4M10 14h4" />
    </Svg>
  );
}

function IconShield(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M12 3 5 6v5c0 4.2 2.8 7.4 7 9 4.2-1.6 7-4.8 7-9V6l-7-3Z" />
      <path d="m9.5 12 1.8 1.8 3.4-3.6" />
    </Svg>
  );
}

function IconLink(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9.5 14.5 14.5 9.5" />
      <path d="M11 17.5 9 19.5a3.2 3.2 0 0 1-4.5-4.5L6.5 13" />
      <path d="M13 6.5 15 4.5a3.2 3.2 0 0 1 4.5 4.5L17.5 11" />
    </Svg>
  );
}

function IconClose(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M7 7l10 10M17 7 7 17" />
    </Svg>
  );
}

function IconCalendar(props: IconProps) {
  return (
    <Svg {...props}>
      <rect x="4" y="5" width="16" height="15" rx="2" />
      <path d="M4 10h16M9 3v4M15 3v4" />
    </Svg>
  );
}

function IconPlay(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M9 7.5v9l8-4.5-8-4.5Z" />
    </Svg>
  );
}

function IconPause(props: IconProps) {
  return (
    <Svg {...props}>
      <path d="M8 7h3v10H8zM13 7h3v10h-3z" />
    </Svg>
  );
}

function KpiIcon({ type }: { type: (typeof TASKS_KPIS)[number]["icon"] }) {
  switch (type) {
    case "layers":
      return <IconLayers />;
    case "progress":
      return <IconProgress />;
    case "warning":
      return <IconWarning />;
    case "check":
      return <IconCheck />;
    case "clock":
      return <IconClock />;
    case "robot":
      return <IconRobot />;
    default:
      return <IconLayers />;
  }
}

function ColumnIcon({ type }: { type: (typeof COLUMN_META)[TaskColumn]["icon"] }) {
  switch (type) {
    case "clipboard":
      return <IconClipboard />;
    case "layers":
      return <IconLayers />;
    case "shield":
      return <IconShield />;
    case "check":
      return <IconCheck />;
    default:
      return <IconClipboard />;
  }
}

function priorityClass(priority: TaskPriority): string {
  if (priority === "High") return "lv-tasks-badge--high";
  if (priority === "Medium") return "lv-tasks-badge--medium";
  return "lv-tasks-badge--low";
}

function avatarTone(name: string): string {
  if (name.includes("Research")) return "lv-tasks-avatar--green";
  if (name.includes("Coding")) return "lv-tasks-avatar--cyan";
  if (name.includes("Trading")) return "lv-tasks-avatar--gold";
  if (name.includes("Finance")) return "lv-tasks-avatar--orange";
  if (name.includes("Emma")) return "lv-tasks-avatar--purple";
  if (name.includes("Sarah")) return "lv-tasks-avatar--red";
  if (name.includes("Planning")) return "lv-tasks-avatar--purple";
  return "";
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

function ProgressRing({ value }: { value: number }) {
  const r = 7.2;
  const c = 2 * Math.PI * r;
  const offset = c - (Math.max(0, Math.min(100, value)) / 100) * c;
  return (
    <svg className="lv-tasks-ring" viewBox="0 0 20 20" aria-hidden="true">
      <circle className="lv-tasks-ring-track" cx="10" cy="10" r={r} />
      <circle
        className={`lv-tasks-ring-value${value >= 100 ? " is-done" : ""}`}
        cx="10"
        cy="10"
        r={r}
        strokeDasharray={c}
        strokeDashoffset={offset}
      />
    </svg>
  );
}

function TaskCardView({
  task,
  selected,
  onSelect,
}: {
  task: TaskCard;
  selected: boolean;
  onSelect: (id: string) => void;
}) {
  return (
    <button
      type="button"
      className={`lv-tasks-card${selected ? " is-selected" : ""}`}
      onClick={() => onSelect(task.id)}
    >
      <div className="lv-tasks-card-top">
        <h3 className="lv-tasks-card-title">{task.title}</h3>
        <span className="lv-tasks-card-menu" aria-hidden="true">
          <IconMore />
        </span>
      </div>
      <div className="lv-tasks-card-badges">
        <span className={`lv-tasks-badge ${priorityClass(task.priority)}`}>{task.priority}</span>
        <span className="lv-tasks-badge lv-tasks-badge--tag">{task.tag}</span>
      </div>
      <p className="lv-tasks-card-desc">{task.description}</p>
      <div className="lv-tasks-card-foot">
        <div className="lv-tasks-card-assignee">
          <span className={`lv-tasks-avatar ${avatarTone(task.assignee)}`}>{initials(task.assignee)}</span>
          <span>{task.assignee}</span>
        </div>
        <div className="lv-tasks-card-meta">
          <span className="lv-tasks-card-date">{task.date}</span>
          <ProgressRing value={task.progress ?? 0} />
        </div>
      </div>
    </button>
  );
}

function DetailsPanel({ task }: { task: TaskCard }) {
  const [tab, setTab] = useState("Details");
  const tabs = ["Details", "Subtasks", "Notes", "Dependencies", "Activity"] as const;
  const detailDescription =
    task.id === "ip-1"
      ? "Update the financial model with latest revenue projections, cost structure, and scenario analysis for Q2."
      : task.description;

  return (
    <aside className="lv-tasks-details">
      <div className="lv-tasks-details-head">
        <h2 className="lv-tasks-details-title">{task.title}</h2>
        <div className="lv-tasks-details-actions">
          <button type="button" className="lv-tasks-icon-btn" aria-label="Copy link">
            <IconLink />
          </button>
          <button type="button" className="lv-tasks-icon-btn" aria-label="More">
            <IconMore />
          </button>
          <button type="button" className="lv-tasks-icon-btn" aria-label="Close">
            <IconClose />
          </button>
        </div>
      </div>

      <div className="lv-tasks-details-badges">
        <span className="lv-tasks-badge lv-tasks-badge--status">{task.statusLabel ?? "In Progress"}</span>
        <span className={`lv-tasks-badge ${priorityClass(task.priority)}`}>{task.priority}</span>
        <span className="lv-tasks-due">
          <IconCalendar />
          {task.dueFull ?? task.date}
          {task.dueHint ? <span className="lv-tasks-due-hint">{task.dueHint}</span> : null}
        </span>
      </div>

      <p className="lv-tasks-details-desc">{detailDescription}</p>

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
                <span className={`lv-tasks-avatar ${avatarTone(task.assignee)}`}>{initials(task.assignee)}</span>
                <div>
                  <strong>{task.assignee}</strong>
                  <small>{task.assigneeRole ?? "Agent"}</small>
                </div>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Project</span>
              <div className="lv-tasks-field-value">
                <a className="lv-tasks-field-link" href="#project">
                  {task.project ?? "—"}
                </a>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Tags</span>
              <div className="lv-tasks-field-value" style={{ flexWrap: "wrap" }}>
                {(task.tags ?? [task.tag]).map((tag) => (
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
                    <div className="lv-tasks-progress-fill" style={{ width: `${task.progress ?? 0}%` }} />
                  </div>
                  <span className="lv-tasks-progress-pct">{task.progress ?? 0}%</span>
                </div>
              </div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Created</span>
              <div className="lv-tasks-field-value">{task.created ?? "—"}</div>
            </div>
            <div className="lv-tasks-field">
              <span className="lv-tasks-field-label">Last Updated</span>
              <div className="lv-tasks-field-value">{task.updated ?? "—"}</div>
            </div>
          </>
        ) : (
          <p className="lv-tasks-details-desc" style={{ padding: 0 }}>
            {tab} content for “{task.title}” will appear here.
          </p>
        )}
      </div>

      <div className="lv-tasks-details-foot">
        <button type="button" className="lv-tasks-btn lv-tasks-btn--outline">
          Assign Agent
        </button>
        <button type="button" className="lv-tasks-btn lv-tasks-btn--neutral">
          <IconPlay />
          Start
        </button>
        <button type="button" className="lv-tasks-btn lv-tasks-btn--neutral">
          <IconPause />
          Pause
        </button>
        <button type="button" className="lv-tasks-btn lv-tasks-btn--gold">
          <IconCheck />
          Complete
        </button>
      </div>
    </aside>
  );
}

function BottomPanels() {
  const [timelineTab, setTimelineTab] = useState("Today");
  const hours = ["6 AM", "9 AM", "12 PM", "3 PM", "6 PM", "9 PM"];

  return (
    <div className="lv-tasks-bottom-grid">
      <section className="lv-tasks-panel lv-tasks-timeline">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Execution Timeline</span>
          <div className="lv-tasks-panel-actions">
            <div className="lv-tasks-mini-tabs">
              {(["Today", "This Week", "Calendar"] as const).map((item) => (
                <button
                  key={item}
                  type="button"
                  className={`lv-tasks-mini-tab${timelineTab === item ? " is-active" : ""}`}
                  onClick={() => setTimelineTab(item)}
                >
                  {item}
                </button>
              ))}
            </div>
            <button type="button" className="lv-tasks-linkish">
              View All
            </button>
          </div>
        </header>
        <div className="lv-tasks-panel-body">
          <div className="lv-tasks-timeline-meta">
            <span>Today, Apr 23, 2025</span>
          </div>
          <div className="lv-tasks-timeline-hours">
            <span>name</span>
            {hours.map((h) => (
              <span key={h}>{h}</span>
            ))}
          </div>
          {TIMELINE_ROWS.map((row) => (
            <div key={row.id} className="lv-tasks-timeline-row">
              <div className="lv-tasks-timeline-name">
                <span className={`lv-tasks-avatar ${avatarTone(row.name)}`}>{initials(row.name)}</span>
                {row.name}
              </div>
              <div className="lv-tasks-timeline-track">
                <div
                  className={`lv-tasks-timeline-block lv-tasks-timeline-block--${row.tone}`}
                  style={{
                    left: `${(row.start / 6) * 100}%`,
                    width: `${(row.span / 6) * 100}%`,
                  }}
                >
                  {row.block}
                </div>
              </div>
            </div>
          ))}
          <button type="button" className="lv-tasks-timeline-add">
            + Add to Calendar
          </button>
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-agent-activity">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Agent Activity</span>
          <button type="button" className="lv-tasks-linkish">
            View All
          </button>
        </header>
        <div className="lv-tasks-panel-body">
          {AGENT_ACTIVITY.map((agent) => (
            <div key={agent.id} className="lv-tasks-agent-row">
              <div className={`lv-tasks-agent-avatar lv-tasks-avatar ${avatarTone(agent.name)} is-${agent.tone}`}>
                {initials(agent.name)}
              </div>
              <div className="lv-tasks-agent-main">
                <div className="lv-tasks-agent-name">{agent.name}</div>
                <div className="lv-tasks-agent-status">
                  {agent.status} · <em>{agent.confidence}% confidence</em>
                </div>
                <div className="lv-tasks-agent-detail">{agent.detail}</div>
              </div>
              <div className="lv-tasks-agent-ago">{agent.ago}</div>
            </div>
          ))}
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-feed">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Console / Activity Feed</span>
          <div className="lv-tasks-panel-actions">
            <span className="lv-tasks-live">Live</span>
            <select className="lv-tasks-select" defaultValue="all" aria-label="Feed filter">
              <option value="all">All</option>
              <option value="agents">Agents</option>
              <option value="humans">Humans</option>
            </select>
          </div>
        </header>
        <div className="lv-tasks-panel-body">
          {ACTIVITY_FEED.map((item) => (
            <div key={item.id} className="lv-tasks-feed-row">
              <span className="lv-tasks-feed-time">{item.time}</span>
              <span className={`lv-tasks-feed-dot lv-tasks-feed-dot--${item.tone}`} />
              <div className="lv-tasks-feed-text">
                {item.parts.map((part, index) => {
                  if (part.emphasis) return <strong key={index}>{part.text}</strong>;
                  if (part.quote) return <em key={index}>“{part.text}”</em>;
                  return <span key={index}>{part.text}</span>;
                })}
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="lv-tasks-panel lv-tasks-insights">
        <header className="lv-tasks-panel-head">
          <span className="lv-tasks-panel-title">Productivity Insights</span>
          <select className="lv-tasks-select" defaultValue="week" aria-label="Insights range">
            <option value="week">This Week</option>
            <option value="month">This Month</option>
          </select>
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
                  strokeDasharray={`${2 * Math.PI * 30 * 0.78} ${2 * Math.PI * 30}`}
                  transform="rotate(-90 39 39)"
                />
              </svg>
              <div className="lv-tasks-donut-center">
                <span className="lv-tasks-donut-pct">78%</span>
                <span className="lv-tasks-donut-label">Completion Rate</span>
                <span className="lv-tasks-donut-delta">↑ +12%</span>
              </div>
            </div>
            <div className="lv-tasks-weekday-chart">
              {WEEKDAYS.map((day, index) => (
                <div key={day} className="lv-tasks-weekday-col">
                  <div className="lv-tasks-weekday-bar" style={{ height: `${WEEKDAY_BARS[index]}%` }} />
                  <span className="lv-tasks-weekday-label">{day}</span>
                </div>
              ))}
            </div>
          </div>
          <h4 className="lv-tasks-workload-title">Workload by Assignee</h4>
          {WORKLOAD.map((row) => (
            <div key={row.name} className="lv-tasks-workload-row">
              <span className="lv-tasks-workload-name">{row.name}</span>
              <div className="lv-tasks-workload-track">
                <div
                  className={`lv-tasks-workload-fill lv-tasks-workload-fill--${row.tone}`}
                  style={{ width: `${(row.count / 8) * 100}%` }}
                />
              </div>
              <span className="lv-tasks-workload-count">{row.count}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}

/**
 * Taken — Mission Control workspace for tasks, agents, and execution.
 * Visual reconstruction against the TAKEN reference; mock data only for this pass.
 */
export function TasksPage() {
  const [selectedId, setSelectedId] = useState(DEFAULT_SELECTED_TASK_ID);

  const selected = useMemo(
    () => TASKS_CARDS.find((task) => task.id === selectedId) ?? TASKS_CARDS[3],
    [selectedId],
  );

  const columns = useMemo(() => {
    const order: TaskColumn[] = ["backlog", "inProgress", "review", "done"];
    return order.map((key) => ({
      key,
      meta: COLUMN_META[key],
      cards: TASKS_CARDS.filter((card) => card.column === key),
    }));
  }, []);

  return (
    <AppShell activeMode="explore" searchPlaceholder="Zoek taken, jobs, approvals...">
      <main className="lv-main lv-tasks-page">
        <header className="lv-tasks-hero">
          <div className="lv-tasks-hero-left">
            <div className="lv-tasks-hero-title-row">
              <h1 className="lv-tasks-hero-title">TAKEN</h1>
              <p className="lv-tasks-hero-subtitle">Mission Control for Tasks, Agents, and Execution</p>
            </div>
            <p className="lv-tasks-hero-quote">“Ideas mean nothing. Execution is everything.” — LEVIATHAN</p>
          </div>
          <div className="lv-tasks-hero-right">
            Discipline turns
            <br />
            intention into freedom.
            <br />— Leviathan
          </div>
        </header>

        <section className="lv-tasks-kpis" aria-label="Task KPIs">
          {TASKS_KPIS.map((kpi) => (
            <article key={kpi.id} className="lv-tasks-kpi">
              <div className={`lv-tasks-kpi-icon lv-tasks-kpi-icon--${kpi.tone}`}>
                <KpiIcon type={kpi.icon} />
              </div>
              <div className="lv-tasks-kpi-body">
                <span className="lv-tasks-kpi-label">{kpi.label}</span>
                <div className="lv-tasks-kpi-value-row">
                  <span className="lv-tasks-kpi-value">{kpi.value}</span>
                  {kpi.delta ? <span className="lv-tasks-kpi-delta">{kpi.delta}</span> : null}
                </div>
              </div>
            </article>
          ))}
        </section>

        <section className="lv-tasks-toolbar" aria-label="Task filters">
          <div className="lv-tasks-toolbar-left">
            <label className="lv-tasks-search">
              <IconSearch />
              <input type="search" placeholder="Search tasks..." aria-label="Search tasks" />
            </label>
            <select className="lv-tasks-select" defaultValue="all-priorities" aria-label="Priority filter">
              <option value="all-priorities">All Priorities</option>
              <option value="high">High</option>
              <option value="medium">Medium</option>
              <option value="low">Low</option>
            </select>
            <select className="lv-tasks-select" defaultValue="all-statuses" aria-label="Status filter">
              <option value="all-statuses">All Statuses</option>
              <option value="backlog">Backlog</option>
              <option value="in-progress">In Progress</option>
              <option value="review">Review</option>
              <option value="done">Done</option>
            </select>
            <select className="lv-tasks-select" defaultValue="all-assignees" aria-label="Assignee filter">
              <option value="all-assignees">All Assignees</option>
              <option value="alex">Alex Chen</option>
              <option value="emma">Emma Park</option>
              <option value="agents">Agents</option>
            </select>
            <select className="lv-tasks-select lv-tasks-select--date" defaultValue="week" aria-label="Date range">
              <option value="week">Today - This Week</option>
              <option value="today">Today</option>
              <option value="month">This Month</option>
            </select>
          </div>
          <div className="lv-tasks-toolbar-right">
            <button type="button" className="lv-tasks-btn lv-tasks-btn--gold">
              <IconPlus />
              New Task
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline">
              <IconBolt />
              Quick Capture
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--outline">
              <IconSparkle />
              Auto-Plan
            </button>
            <button type="button" className="lv-tasks-btn lv-tasks-btn--ghost" aria-label="More actions">
              <IconMore />
            </button>
          </div>
        </section>

        <section className="lv-tasks-workspace" aria-label="Task workspace">
          <div className="lv-tasks-board">
            {columns.map((column) => (
              <div key={column.key} className="lv-tasks-column">
                <div className="lv-tasks-column-head">
                  <div className={`lv-tasks-column-title lv-tasks-column-title--${column.meta.tone}`}>
                    <ColumnIcon type={column.meta.icon} />
                    <span>
                      {column.meta.title}{" "}
                      <span className="lv-tasks-column-count">({column.meta.count})</span>
                    </span>
                  </div>
                  <button type="button" className="lv-tasks-column-add" aria-label={`Add to ${column.meta.title}`}>
                    <IconPlus />
                  </button>
                </div>
                <div className="lv-tasks-column-body">
                  {column.cards.map((card) => (
                    <TaskCardView
                      key={card.id}
                      task={card}
                      selected={selectedId === card.id}
                      onSelect={setSelectedId}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
          {selected ? <DetailsPanel task={selected} /> : null}
        </section>

        <BottomPanels />
      </main>
    </AppShell>
  );
}
