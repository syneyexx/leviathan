"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { useHadesTasks } from "@/components/hades/features/tasks/hooks/useHadesTasks";
import type { HadesTask } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import {
  TASK_COLUMNS,
  TASK_TABS,
  type FinalBetaKanbanTask,
  type TaskColumn,
  type TaskPriority,
} from "../mocks/tasks";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";
import { TasksTabKalender, TasksTabLijst, TasksTabMijnTaken, TasksTabTijdlijn } from "./tasks";

type Props = { onNavigate: FinalBetaNavigate };
type TaskTab = (typeof TASK_TABS)[number];

function mapPriority(priority: HadesTask["priority"]): TaskPriority {
  if (priority === "high") return "Hoog";
  if (priority === "low") return "Laag";
  return "Medium";
}

function mapColumn(status: string): TaskColumn {
  const s = String(status || "").toLowerCase();
  if (s === "running") return "running";
  if (s === "paused") return "review";
  if (s === "completed") return "done";
  if (s === "failed") return "review";
  if (s === "cancelled") return "done";
  return "open";
}

function formatTaskDate(value?: string | null): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("nl-NL", {
      day: "2-digit",
      month: "short",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return value;
  }
}

function toKanbanTask(task: HadesTask): FinalBetaKanbanTask {
  const column = mapColumn(task.status);
  const progress = typeof task.progress === "number" ? Math.round(task.progress) : undefined;
  return {
    id: task.id,
    code: task.id.slice(0, 12).toUpperCase(),
    title: task.title || "Taak",
    description: task.prompt || task.result || task.error || "—",
    column,
    priority: mapPriority(task.priority),
    date: formatTaskDate(task.finished_at || task.updated_at || task.created_at),
    tags: [task.agent || "agent", String(task.status || "pending")].filter(Boolean),
    progress: column === "running" || column === "review" ? progress : progress && progress > 0 ? progress : undefined,
    owner: task.agent || "HADES",
    type: task.model_id || "Work Runtime",
    created: formatTaskDate(task.created_at),
    deadline: formatTaskDate(task.finished_at || task.updated_at),
    project: task.agent || undefined,
    mine: true,
  };
}

const DAYS = ["Zondag", "Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag"];
const MONTHS = [
  "januari",
  "februari",
  "maart",
  "april",
  "mei",
  "juni",
  "juli",
  "augustus",
  "september",
  "oktober",
  "november",
  "december",
];

const COLUMN_STATUS: Record<TaskColumn, string> = {
  open: "Open",
  running: "In uitvoering",
  review: "Wacht op review",
  done: "Gereed",
};

const TAB_WELCOME: Record<TaskTab, { subtitle: string; quote: string }> = {
  Kanban: {
    subtitle: "Plan, voer uit en bewaak alle taken binnen het HADES ecosysteem. Van idee tot impact.",
    quote: "Execution turns intelligence into reality.",
  },
  Lijst: {
    subtitle: "Alle taken in één overzichtelijke tabel. Filter, sorteer en bewaak voortgang.",
    quote: "Execution turns intelligence into reality.",
  },
  "Mijn taken": {
    subtitle: "Focus op wat voor jou belangrijk is. Jouw taken, jouw impact.",
    quote: "Small steps compound into extraordinary results.",
  },
  Kalender: {
    subtitle: "Deadlines en mijlpalen op de kalender. Zie wat wanneer speelt.",
    quote: "Time is the canvas where execution paints results.",
  },
  Tijdlijn: {
    subtitle: "Sprintplanning en afhankelijkheden op één tijdlijn.",
    quote: "Sequence creates momentum. Momentum creates outcomes.",
  },
  Analytics: {
    subtitle: "Plan, voer uit en bewaak alle taken binnen het HADES ecosysteem. Van idee tot impact.",
    quote: "Execution turns intelligence into reality.",
  },
};

function pad(n: number) {
  return String(n).padStart(2, "0");
}

function priorityClass(priority: TaskPriority) {
  if (priority === "Hoog") return "high";
  if (priority === "Medium") return "medium";
  return "low";
}

function TaskCard({
  task,
  active,
  onSelect,
}: {
  task: FinalBetaKanbanTask;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <button type="button" className={`tasks-card${active ? " active" : ""}`} onClick={onSelect}>
      <span className="tasks-card-menu" aria-hidden="true">
        <FbIcon name="more" size={14} />
      </span>
      <strong className="tasks-card-title">{task.title}</strong>
      <p className="tasks-card-desc">{task.description}</p>
      <div className="tasks-card-tags">
        {task.tags.map((tag) => (
          <span key={tag} className="tag">
            {tag}
          </span>
        ))}
      </div>
      <div className="tasks-card-meta">
        <span className={`tasks-prio ${priorityClass(task.priority)}`}>
          <i />
          {task.priority}
        </span>
        <span className="tasks-date">
          <FbIcon name="calendar" size={11} />
          {task.date}
        </span>
      </div>
      {typeof task.progress === "number" ? (
        <div className="tasks-card-progress">
          <div className="tasks-progress-bar">
            <i style={{ width: `${task.progress}%` }} />
          </div>
          <span>{task.progress}%</span>
        </div>
      ) : null}
    </button>
  );
}

export function TasksPage({ onNavigate }: Props) {
  const [now, setNow] = useState(() => new Date());
  const [tab, setTab] = useState<TaskTab>("Kanban");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  const { tasks: apiTasks, loading, error, refresh, create } = useHadesTasks();
  const kanbanTasks = useMemo(() => apiTasks.map(toKanbanTask), [apiTasks]);

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => {
    if (!selectedId && kanbanTasks[0]) setSelectedId(kanbanTasks[0].id);
    if (selectedId && kanbanTasks.length && !kanbanTasks.some((t) => t.id === selectedId)) {
      setSelectedId(kanbanTasks[0]?.id ?? null);
    }
  }, [kanbanTasks, selectedId]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return kanbanTasks;
    return kanbanTasks.filter(
      (task) =>
        task.title.toLowerCase().includes(q) ||
        task.description.toLowerCase().includes(q) ||
        task.tags.some((tag) => tag.toLowerCase().includes(q)) ||
        task.owner.toLowerCase().includes(q) ||
        (task.project ?? "").toLowerCase().includes(q),
    );
  }, [query, kanbanTasks]);

  const counts = useMemo(() => {
    const base = { open: 0, running: 0, review: 0, done: 0 } as Record<TaskColumn, number>;
    for (const task of kanbanTasks) base[task.column] += 1;
    return base;
  }, [kanbanTasks]);

  const selected = kanbanTasks.find((task) => task.id === selectedId) ?? kanbanTasks[0] ?? null;
  const welcome = TAB_WELCOME[tab];
  const showToolbar = tab === "Kanban" || tab === "Lijst" || tab === "Kalender";
  const searchPlaceholder =
    tab === "Lijst"
      ? "Zoek taken, beschrijvingen, labels of project..."
      : "Zoek taken, agents, mappen...";

  async function onNewTask() {
    const title = window.prompt("Titel van de nieuwe taak");
    if (!title?.trim()) return;
    const prompt = window.prompt("Prompt / opdracht", title.trim()) || title.trim();
    try {
      const task = await create({
        title: title.trim(),
        prompt: prompt.trim(),
        agent: "general",
        priority: "normal",
        auto_start: false,
      });
      setSelectedId(task.id);
      toast.success(`Taak aangemaakt: ${task.title}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    }
  }

  let panel: ReactNode = null;
  if (tab === "Kanban") {
    panel = (
      <div className="tasks-board">
        {TASK_COLUMNS.map((column) => {
          const cards = filtered.filter((task) => task.column === column.id);
          return (
            <section key={column.id} className={`tasks-column tone-${column.tone}`}>
              <header className="tasks-col-head">
                <span className={`tasks-col-ico ${column.tone}`}>
                  <FbIcon name={column.icon} size={14} />
                </span>
                <div className="tasks-col-copy">
                  <div className="tasks-col-title">{column.title}</div>
                  <div className="tasks-col-sub">{column.sub}</div>
                </div>
                <span className="tasks-col-count">{counts[column.id]}</span>
              </header>
              <div className="tasks-col-body">
                {loading && !kanbanTasks.length ? (
                  <p className="muted" style={{ padding: 8 }}>
                    Taken laden…
                  </p>
                ) : null}
                {!loading && !cards.length ? (
                  <p className="muted" style={{ padding: 8 }}>
                    Geen taken
                  </p>
                ) : null}
                {cards.map((task) => (
                  <TaskCard
                    key={task.id}
                    task={task}
                    active={selected != null && task.id === selected.id}
                    onSelect={() => setSelectedId(task.id)}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    );
  } else if (tab === "Lijst") {
    panel = (
      <TasksTabLijst
        tasks={filtered}
        selectedId={selected?.id ?? ""}
        onSelect={setSelectedId}
      />
    );
  } else if (tab === "Mijn taken") {
    panel = (
      <TasksTabMijnTaken
        tasks={kanbanTasks}
        selectedId={selected?.id ?? ""}
        onSelect={setSelectedId}
      />
    );
  } else if (tab === "Kalender") {
    panel = (
      <TasksTabKalender
        tasks={filtered}
        selectedId={selected?.id ?? ""}
        onSelect={setSelectedId}
      />
    );
  } else if (tab === "Tijdlijn") {
    panel = <TasksTabTijdlijn tasks={kanbanTasks} />;
  } else {
    panel = (
      <div className="tasks-alt card">
        <strong>Analytics</strong>
        <p className="muted">Analytics volgt in een volgende iteratie</p>
      </div>
    );
  }

  const body = (
    <div className="tasks-page" data-live="tasks">
      <div className="tasks-welcome">
        <div className="tasks-welcome-copy">
          <h1>Taken</h1>
          <p>{welcome.subtitle}</p>
        </div>
        <div className="tasks-welcome-mid">“{welcome.quote}”</div>
        <div className="tasks-welcome-right">
          <div className="tasks-clock">
            <div className="tasks-clock-copy">
              <div className="date">
                {DAYS[now.getDay()]} {now.getDate()} {MONTHS[now.getMonth()]} {now.getFullYear()}
              </div>
              <div className="time">
                {pad(now.getHours())}:{pad(now.getMinutes())}
              </div>
            </div>
            <FbIcon name="bolt" size={22} className="tasks-sun" />
          </div>
          <button type="button" className="btn btn-gold tasks-new" onClick={() => void onNewTask()}>
            <FbIcon name="plus" size={13} />
            Nieuwe taak
          </button>
        </div>
      </div>

      {error ? (
        <div className="card" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>Taken laden mislukt.</strong> {error.message}
        </div>
      ) : null}

      <nav className="tasks-tabs" aria-label="Taken weergaven">
        {TASK_TABS.map((item) => (
          <button
            key={item}
            type="button"
            className={`tasks-tab${tab === item ? " active" : ""}`}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </nav>

      {showToolbar ? (
        <div className={`tasks-toolbar${tab === "Lijst" ? " tasks-toolbar-lijst" : ""}`}>
          <label className="tasks-search">
            <FbIcon name="search" size={14} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={searchPlaceholder}
              aria-label="Zoek taken"
            />
          </label>
          <button type="button" className="tasks-filter" data-toast="Filter projecten">
            Alle projecten
            <FbIcon name="chevron" size={12} />
          </button>
          {tab === "Lijst" ? (
            <button type="button" className="tasks-filter" data-toast="Filter statussen">
              Alle statussen
              <FbIcon name="chevron" size={12} />
            </button>
          ) : null}
          <button type="button" className="tasks-filter" data-toast="Filter prioriteiten">
            Alle prioriteiten
            <FbIcon name="chevron" size={12} />
          </button>
          {tab === "Kalender" ? (
            <button type="button" className="tasks-filter" data-toast="Filter labels">
              Alle labels
              <FbIcon name="chevron" size={12} />
            </button>
          ) : null}
          <button type="button" className="tasks-filter" data-toast="Filter eigenaren">
            Alle eigenaren
            <FbIcon name="chevron" size={12} />
          </button>
          {tab === "Lijst" ? (
            <button type="button" className="tasks-filter" data-toast="Meer filters">
              Meer filters
              <FbIcon name="sliders" size={12} />
            </button>
          ) : tab === "Kanban" ? (
            <button type="button" className="tasks-filter" data-toast="Filter labels">
              Alle labels
              <FbIcon name="chevron" size={12} />
            </button>
          ) : null}
        </div>
      ) : null}

      {panel}

      <div className="tasks-bottom">
        <div className="tasks-quick">
          <span className="tasks-quick-label">Snelle acties</span>
          <button type="button" className="btn btn-sm btn-gold" onClick={() => void onNewTask()}>
            <FbIcon name="plus" size={12} />
            Nieuwe taak
          </button>
          <button
            type="button"
            className="btn btn-sm btn-outline"
            onClick={() => void refresh().then(() => toast.success("Taken vernieuwd"))}
          >
            Vernieuwen
          </button>
        </div>
        <div className="tasks-stats">
          <span className="tasks-stats-label">Taakstatistieken</span>
          <span>
            <b>{kanbanTasks.length}</b> Totaal
          </span>
          <span>
            <b className="c-blue">{counts.open}</b> Open
          </span>
          <span>
            <b className="c-cyan">{counts.running}</b> In uitvoering
          </span>
          <span>
            <b className="c-amber">{counts.review}</b> Review
          </span>
          <span>
            <b className="c-green">{counts.done}</b> Gereed
          </span>
        </div>
      </div>
    </div>
  );

  const inspector = !selected ? (
    <p className="muted">Geen taak geselecteerd.</p>
  ) : (
    <>
      <div className="tasks-insp-head">
        <div>
          <h3 className="insp-title">Taak details</h3>
          <div className="tasks-insp-code">#{selected.code}</div>
        </div>
        <button type="button" className="tasks-insp-close" aria-label="Sluiten" onClick={() => setSelectedId(null)}>
          ×
        </button>
      </div>

      <section className="insp-section">
        <div className="insp-card tasks-detail-card">
          <h2 className="tasks-detail-title">{selected.title}</h2>
          <div className="detail-row">
            <span className="k">Status</span>
            <span className={`v tasks-status-pill ${selected.column}`}>{COLUMN_STATUS[selected.column]}</span>
          </div>
          <div className="detail-row">
            <span className="k">Prioriteit</span>
            <span className={`v tasks-prio ${priorityClass(selected.priority)}`}>
              <i />
              {selected.priority}
            </span>
          </div>
          <div className="detail-row">
            <span className="k">Eigenaar</span>
            <span className="v tasks-owner">
              <FbIcon name="user" size={12} />
              {selected.owner}
            </span>
          </div>
          <div className="detail-row">
            <span className="k">Type</span>
            <span className="v">{selected.type}</span>
          </div>
          <div className="detail-row">
            <span className="k">Aangemaakt</span>
            <span className="v">{selected.created}</span>
          </div>
          <div className="detail-row">
            <span className="k">Deadline</span>
            <span className="v">{selected.deadline}</span>
          </div>

          {typeof selected.progress === "number" ? (
            <div className="tasks-detail-progress">
              <div className="tasks-detail-progress-top">
                <span>Voortgang</span>
                <span>{selected.progress}%</span>
              </div>
              <div className="tasks-progress-bar lg">
                <i style={{ width: `${selected.progress}%` }} />
              </div>
            </div>
          ) : null}

          <div className="tasks-detail-labels">
            <span className="k">Labels</span>
            <div className="tasks-card-tags">
              {selected.tags.map((tag) => (
                <span key={tag} className="tag">
                  {tag}
                </span>
              ))}
              <button type="button" className="tasks-label-add" data-toast="Label toevoegen" aria-label="Label toevoegen">
                +
              </button>
            </div>
          </div>
        </div>
      </section>

      <section className="insp-section">
        <h3 className="insp-title">Beschrijving</h3>
        <div className="insp-card">
          <p className="tasks-detail-desc">{selected.description}</p>
        </div>
      </section>

      {selected.mission ? (
        <section className="insp-section">
          <h3 className="insp-title">Gerelateerde missie</h3>
          <button type="button" className="insp-card tasks-mission" data-toast={selected.mission.title}>
            <span className="tasks-mission-ico">
              <FbIcon name="target" size={14} />
            </span>
            <span>
              <strong>{selected.mission.title}</strong>
              <small>{selected.mission.sub}</small>
            </span>
          </button>
        </section>
      ) : null}

      {selected.log?.length ? (
        <section className="insp-section">
          <h3 className="insp-title">Uitvoeringslog</h3>
          <div className="insp-card tasks-log">
            {selected.log.map((entry) => (
              <div key={entry.title} className={`tasks-log-step ${entry.state}`}>
                <span className="tasks-log-dot" />
                <div>
                  <strong>{entry.title}</strong>
                  <div className="muted">{entry.sub}</div>
                </div>
                <span className="tasks-log-ago">{entry.ago}</span>
              </div>
            ))}
          </div>
        </section>
      ) : null}

      {selected.nextSteps?.length ? (
        <section className="insp-section">
          <h3 className="insp-title">Volgende stappen</h3>
          <div className="insp-card tasks-next">
            {selected.nextSteps.map((step) => (
              <label key={step.label} className="tasks-check">
                <input type="checkbox" defaultChecked={step.done} />
                <span>{step.label}</span>
              </label>
            ))}
          </div>
        </section>
      ) : null}
    </>
  );

  const footer = (
    <footer className="dash-footer tasks-footer">
      <span>HADES FINALBETA | Local AI Platform · tasks live</span>
      <span className="motto">
        Build a smarter tomorrow. <b>━━</b>
      </span>
    </footer>
  );

  return (
    <FinalBetaShell
      page="tasks"
      body={body}
      inspector={inspector}
      onNavigate={onNavigate}
      appClassName="tasks-app"
      mainClassName="tasks-main"
      footer={footer}
    />
  );
}
