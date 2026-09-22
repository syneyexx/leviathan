import { useMemo, useState, type ReactNode } from "react";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import {
  CONSOLE_COMMAND_HISTORY,
  CONSOLE_COMMON_COMMANDS,
  CONSOLE_LOG_LINES,
  CONSOLE_LOG_TABS,
  CONSOLE_PROCESSES,
  CONSOLE_QUICK_ACTIONS,
  CONSOLE_RESOURCES,
  CONSOLE_STATUS_CARDS,
  type ConsoleLogLevel,
  type ConsoleProcessStatus,
} from "./mocks";
import { Bar, Panel } from "./shared";

type CmdMode = "Command" | "Python";

type ProcessState = {
  status: ConsoleProcessStatus;
  action: "Stop" | "Start";
};

const STATUS_ICONS: Record<string, ReactNode> = {
  system: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l2.5 2.5" />
      <path d="M8 12h.01M16 12h.01" />
    </svg>
  ),
  uptime: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="13" r="7" />
      <path d="M12 10v3.5l2 1.5" />
      <path d="M9 5h6" />
    </svg>
  ),
  lograte: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 3l7 3v5c0 4.5-3 7.8-7 9-4-1.2-7-4.5-7-9V6l7-3z" />
      <path d="M9.5 12a2.5 2.5 0 104.9.6" />
      <path d="M14.5 10.2l1.2-1.2M8.8 13.8L7.6 15" />
    </svg>
  ),
  processes: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="7.5" />
      <circle cx="12" cy="12" r="2" />
      <path d="M12 4.5v2M12 17.5v2M4.5 12h2M17.5 12h2" />
    </svg>
  ),
};

const QUICK_ICONS: Record<string, ReactNode> = {
  restart: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M19.5 12a7.5 7.5 0 11-2.2-5.3" />
      <path d="M19.5 5v4.5H15" />
    </svg>
  ),
  reload: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <circle cx="12" cy="12" r="3" />
      <path d="M12 4.5v2.2M12 17.3v2.2M4.5 12h2.2M17.3 12h2.2M6.2 6.2l1.5 1.5M16.3 16.3l1.5 1.5M17.8 6.2l-1.5 1.5M7.7 16.3l-1.5 1.5" />
    </svg>
  ),
  cache: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M9 8V6.8A1.8 1.8 0 0110.8 5h2.4A1.8 1.8 0 0115 6.8V8" />
      <path d="M7 8h10l-.8 11.2A1.8 1.8 0 0114.4 21H9.6a1.8 1.8 0 01-1.8-1.8L7 8z" />
    </svg>
  ),
  logs: (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7.5A2.5 2.5 0 016.5 5H14l4 4v9.5A2.5 2.5 0 0115.5 21h-9A2.5 2.5 0 014 18.5v-11z" />
      <path d="M14 5v4h4" />
    </svg>
  ),
};

function IconBtn({
  label,
  children,
  onClick,
}: {
  label: string;
  children: ReactNode;
  onClick?: () => void;
}) {
  return (
    <button type="button" className="lv-pr-console-icon-btn" aria-label={label} onClick={onClick}>
      {children}
    </button>
  );
}

function formatResourceValue(value: string, pct: number): string {
  if (value.includes("%") && !value.includes("/")) return value;
  return `${value} (${pct}%)`;
}

function nowStamp(): string {
  const d = new Date();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${hh}:${mm}`;
}

function nowLogTime(): string {
  const d = new Date();
  const y = d.getFullYear();
  const mo = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${y}-${mo}-${day} ${hh}:${mm}:${ss}`;
}

export function ConsolePage() {
  const toast = useAppToast();
  const [logTab, setLogTab] = useState<(typeof CONSOLE_LOG_TABS)[number]>("System Logs");
  const [cmdMode, setCmdMode] = useState<CmdMode>("Command");
  const [paused, setPaused] = useState(false);
  const [filterOpen, setFilterOpen] = useState(false);
  const [logQuery, setLogQuery] = useState("");
  const [command, setCommand] = useState("");
  const [logs, setLogs] = useState(CONSOLE_LOG_LINES);
  const [history, setHistory] = useState<Array<{ id: string; time: string; command: string }>>(() => [
    ...CONSOLE_COMMAND_HISTORY,
  ]);
  const [processes, setProcesses] = useState<Record<string, ProcessState>>(() =>
    Object.fromEntries(
      CONSOLE_PROCESSES.map((p) => [p.id, { status: p.status, action: p.action }]),
    ),
  );

  const filteredLogs = useMemo(() => {
    const q = logQuery.trim().toLowerCase();
    let rows = logs;
    if (logTab === "Errors") {
      rows = rows.filter((l) => l.level === "ERROR");
    } else if (logTab !== "System Logs") {
      const key = logTab.toLowerCase();
      rows = rows.filter(
        (l) => l.message.toLowerCase().includes(key) || l.level.toLowerCase() === key,
      );
    }
    if (!q) return rows;
    return rows.filter(
      (l) =>
        l.message.toLowerCase().includes(q) ||
        l.level.toLowerCase().includes(q) ||
        l.time.includes(q),
    );
  }, [logs, logQuery, logTab]);

  function appendLog(level: ConsoleLogLevel, message: string) {
    setLogs((prev) => [
      ...prev,
      { id: `l-${Date.now()}`, time: nowLogTime(), level, message },
    ]);
  }

  function runCommand(raw?: string) {
    const text = (raw ?? command).trim();
    if (!text) {
      toast("Enter a command");
      return;
    }
    if (paused) {
      toast("Console paused — resume to run commands");
      return;
    }
    setHistory((prev) => [{ id: `h-${Date.now()}`, time: nowStamp(), command: text }, ...prev].slice(0, 12));
    appendLog("INFO", cmdMode === "Python" ? `>>> ${text}` : `$ ${text}`);
    appendLog("SUCCESS", `Command completed: ${text}`);
    toast(`Ran: ${text}`);
    setCommand("");
  }

  function toggleProcess(id: string) {
    setProcesses((prev) => {
      const cur = prev[id];
      if (!cur) return prev;
      const nextRunning = cur.status !== "Running";
      const next: ProcessState = nextRunning
        ? { status: "Running", action: "Stop" }
        : { status: "Idle", action: "Start" };
      const name = CONSOLE_PROCESSES.find((p) => p.id === id)?.name ?? id;
      toast(`${name} ${next.status === "Running" ? "started" : "stopped"}`);
      appendLog(
        next.status === "Running" ? "SUCCESS" : "INFO",
        `${name} ${next.status === "Running" ? "started" : "stopped"}`,
      );
      return { ...prev, [id]: next };
    });
  }

  function copyLogs() {
    const text = filteredLogs.map((l) => `${l.time} [${l.level}] ${l.message}`).join("\n");
    void navigator.clipboard?.writeText(text).then(
      () => toast("Logs copied"),
      () => toast("Copy unavailable"),
    );
  }

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Console Mode"
      searchPlaceholder="Search logs..."
      systemItems={["LLM", "Neural", "Memory", "Runtime"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main lv-pr-console">
        <header className="lv-pr-console-head">
          <div className="lv-pr-console-head-left">
            <div className="lv-pr-console-crumb">
              <span className="lv-pr-console-crumb-icon" aria-hidden="true">
                <svg viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="3" />
                  <path d="M12 3.5v2.2M12 18.3v2.2M3.5 12h2.2M18.3 12h2.2M6.1 6.1l1.6 1.6M16.3 16.3l1.6 1.6M17.9 6.1l-1.6 1.6M7.7 16.3l-1.6 1.6" />
                </svg>
              </span>
              <h1 className="lv-pr-console-title">
                <span className="lv-pr-console-title-muted">Plugin &amp; Runtime</span>
                <span className="lv-pr-console-title-sep" aria-hidden="true">
                  ›
                </span>
                <span>Console</span>
              </h1>
            </div>
            <p className="lv-pr-console-sub">
              Real-time system logs, process control and runtime interaction.
            </p>
          </div>
          <p className="lv-pr-console-quote" aria-hidden="true">
            DISCIPLINE CREATES FREEDOM
            <span className="lv-pr-console-quote-mark" />
          </p>
        </header>

        <section className="lv-pr-console-status" aria-label="Console status">
          {CONSOLE_STATUS_CARDS.map((card) => (
            <article key={card.id} className="lv-pr-console-status-card">
              <div className={`lv-pr-console-status-icon${"tone" in card && card.tone === "ok" ? " is-ok" : ""}`}>
                {STATUS_ICONS[card.id]}
              </div>
              <div className="lv-pr-console-status-copy">
                <div className="label">{card.label}</div>
                <div className={`value${"tone" in card && card.tone === "ok" ? " is-ok" : ""}`}>
                  {card.value}
                </div>
              </div>
            </article>
          ))}
          <div className="lv-pr-console-toolbar">
            <button
              type="button"
              className="lv-pr-console-tool"
              onClick={() => {
                setLogs([]);
                toast("Logs cleared");
              }}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M9 8V6.8A1.8 1.8 0 0110.8 5h2.4A1.8 1.8 0 0115 6.8V8" />
                <path d="M7 8h10l-.8 11.2A1.8 1.8 0 0114.4 21H9.6a1.8 1.8 0 01-1.8-1.8L7 8z" />
                <path d="M5 8h14" />
              </svg>
              Clear
            </button>
            <button type="button" className="lv-pr-console-tool" onClick={() => toast("Export started")}>
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M12 4v10" />
                <path d="M8.5 7.5L12 4l3.5 3.5" />
                <path d="M5 14v4.5A1.5 1.5 0 006.5 20h11a1.5 1.5 0 001.5-1.5V14" />
              </svg>
              Export
            </button>
            <button
              type="button"
              className={`lv-pr-console-tool${filterOpen ? " is-active" : ""}`}
              onClick={() => setFilterOpen((v) => !v)}
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <path d="M4 6h16l-6 7.5V19l-4 1.5v-7L4 6z" />
              </svg>
              Filter
            </button>
            <button
              type="button"
              className={`lv-pr-console-tool is-gold${paused ? " is-paused" : ""}`}
              onClick={() => {
                setPaused((v) => !v);
                toast(paused ? "Console resumed" : "Console paused");
              }}
            >
              {paused ? (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M8 6.5v11l10-5.5L8 6.5z" fill="currentColor" stroke="none" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" aria-hidden="true">
                  <path d="M8 6h2.5v12H8zM13.5 6H16v12h-2.5z" fill="currentColor" stroke="none" />
                </svg>
              )}
              {paused ? "Resume" : "Pause"}
            </button>
          </div>
        </section>

        {filterOpen ? (
          <div className="lv-pr-console-filter">
            <input
              className="lv-pr-console-filter-input"
              value={logQuery}
              onChange={(e) => setLogQuery(e.target.value)}
              placeholder="Filter logs by text, level, or time…"
              aria-label="Filter logs"
            />
          </div>
        ) : null}

        <div className="lv-pr-console-layout">
          <div className="lv-pr-console-main">
            <div className="lv-pr-console-tabs" role="tablist" aria-label="Log channels">
              {CONSOLE_LOG_TABS.map((tab) => (
                <button
                  key={tab}
                  type="button"
                  role="tab"
                  aria-selected={logTab === tab}
                  className={`lv-pr-console-tab${logTab === tab ? " is-active" : ""}`}
                  onClick={() => setLogTab(tab)}
                >
                  {tab}
                </button>
              ))}
            </div>

            <div className="lv-pr-console-log-wrap">
              <div className="lv-pr-console-log-tools">
                <IconBtn label="Copy logs" onClick={copyLogs}>
                  <svg viewBox="0 0 24 24">
                    <rect x="8" y="8" width="11" height="11" rx="1.5" />
                    <path d="M6 15H5.5A1.5 1.5 0 014 13.5v-8A1.5 1.5 0 015.5 4h8A1.5 1.5 0 0115 5.5V6" />
                  </svg>
                </IconBtn>
                <IconBtn
                  label="Search logs"
                  onClick={() => {
                    setFilterOpen(true);
                    toast("Search logs");
                  }}
                >
                  <svg viewBox="0 0 24 24">
                    <circle cx="11" cy="11" r="6" />
                    <path d="M16 16l4 4" />
                  </svg>
                </IconBtn>
              </div>
              <div
                className={`lv-pr-console-log${paused ? " is-paused" : ""}`}
                role="log"
                aria-live={paused ? "off" : "polite"}
              >
                {filteredLogs.length === 0 ? (
                  <div className="lv-pr-console-log-empty">No log lines match this view.</div>
                ) : (
                  filteredLogs.map((line) => (
                    <div key={line.id} className="lv-pr-console-log-line">
                      <span className="time">{line.time}</span>
                      <span className={`level level-${line.level}`}>[{line.level}]</span>
                      <span className="msg">{line.message}</span>
                    </div>
                  ))
                )}
              </div>
            </div>

            <section className="lv-pr-console-cmd" aria-label="Command input">
              <div className="lv-pr-console-tabs is-cmd" role="tablist" aria-label="Command mode">
                {(["Command", "Python"] as const).map((mode) => (
                  <button
                    key={mode}
                    type="button"
                    role="tab"
                    aria-selected={cmdMode === mode}
                    className={`lv-pr-console-tab${cmdMode === mode ? " is-active" : ""}`}
                    onClick={() => setCmdMode(mode)}
                  >
                    {mode}
                  </button>
                ))}
              </div>
              <div className="lv-pr-console-cmd-row">
                <label className="lv-pr-console-cmd-input">
                  <span className="prompt">hades&gt;</span>
                  <input
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        runCommand();
                      }
                    }}
                    placeholder="Type a command or Python code..."
                    aria-label="Console command"
                    spellCheck={false}
                  />
                </label>
                <div className="lv-pr-console-run">
                  <button type="button" className="lv-pr-console-run-btn" onClick={() => runCommand()}>
                    Run
                  </button>
                  <button
                    type="button"
                    className="lv-pr-console-run-caret"
                    aria-label="Run options"
                    onClick={() => toast("Run options")}
                  >
                    <svg viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M7 10l5 5 5-5" />
                    </svg>
                  </button>
                </div>
              </div>
              <div className="lv-pr-console-common-block">
                <div className="lv-pr-console-common-label">Common Commands</div>
                <div className="lv-pr-console-common">
                  {CONSOLE_COMMON_COMMANDS.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      className="lv-pr-console-chip"
                      onClick={() => {
                        setCommand(chip);
                        runCommand(chip);
                      }}
                    >
                      {chip}
                    </button>
                  ))}
                </div>
              </div>
            </section>
          </div>

          <aside className="lv-pr-console-side">
            <Panel
              className="lv-pr-console-panel"
              title="Process Control"
              action={
                <IconBtn label="Process menu" onClick={() => toast("Process menu")}>
                  <svg viewBox="0 0 24 24">
                    <circle cx="6" cy="12" r="1.4" fill="currentColor" stroke="none" />
                    <circle cx="12" cy="12" r="1.4" fill="currentColor" stroke="none" />
                    <circle cx="18" cy="12" r="1.4" fill="currentColor" stroke="none" />
                  </svg>
                </IconBtn>
              }
            >
              <div className="lv-pr-console-process-list">
                {CONSOLE_PROCESSES.map((proc) => {
                  const state = processes[proc.id] ?? { status: proc.status, action: proc.action };
                  const running = state.status === "Running";
                  return (
                    <div key={proc.id} className="lv-pr-console-process">
                      <span className="name">{proc.name}</span>
                      <span className={`status${running ? " is-running" : " is-idle"}`}>
                        <span className="dot" aria-hidden="true" />
                        {state.status}
                      </span>
                      <button
                        type="button"
                        className={`lv-pr-console-proc-btn${running ? " is-stop" : " is-start"}`}
                        onClick={() => toggleProcess(proc.id)}
                      >
                        {running ? (
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <circle cx="12" cy="12" r="8" />
                            <rect x="9" y="9" width="6" height="6" rx="0.5" fill="currentColor" stroke="none" />
                          </svg>
                        ) : (
                          <svg viewBox="0 0 24 24" aria-hidden="true">
                            <circle cx="12" cy="12" r="8" />
                            <path d="M10 8.5v7l6-3.5-6-3.5z" fill="currentColor" stroke="none" />
                          </svg>
                        )}
                        {state.action}
                      </button>
                    </div>
                  );
                })}
              </div>
            </Panel>

            <Panel className="lv-pr-console-panel" title="Quick Actions">
              <div className="lv-pr-console-actions">
                {CONSOLE_QUICK_ACTIONS.map((action) => (
                  <button
                    key={action.id}
                    type="button"
                    className="lv-pr-console-action"
                    onClick={() => toast(action.label)}
                  >
                    <span className="ico" aria-hidden="true">
                      {QUICK_ICONS[action.id]}
                    </span>
                    {action.label}
                  </button>
                ))}
              </div>
            </Panel>

            <Panel className="lv-pr-console-panel" title="Resource Monitor">
              <div className="lv-pr-console-resources">
                {CONSOLE_RESOURCES.map((res) => (
                  <div key={res.id} className="lv-pr-console-resource">
                    <div className="lv-pr-console-resource-meta">
                      <span>{res.label}</span>
                      <span>{formatResourceValue(res.value, res.pct)}</span>
                    </div>
                    <Bar pct={res.pct} tone={res.tone} />
                  </div>
                ))}
              </div>
            </Panel>

            <Panel className="lv-pr-console-panel" title="Command History">
              <ul className="lv-pr-console-history">
                {history.map((item) => (
                  <li key={item.id}>
                    <button
                      type="button"
                      className="cmd"
                      onClick={() => {
                        setCommand(item.command);
                        setCmdMode("Command");
                      }}
                    >
                      {item.command}
                    </button>
                    <span className="time">{item.time}</span>
                  </li>
                ))}
              </ul>
            </Panel>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
