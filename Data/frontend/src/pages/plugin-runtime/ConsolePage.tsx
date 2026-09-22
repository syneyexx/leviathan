import { useEffect, useMemo, useState, type ReactNode } from "react";
import { api } from "../../api/client";
import { useLiveEvents } from "../../hooks/useLiveEvents";
import { useSystemTelemetry } from "../../hooks/useSystemTelemetry";
import { AppShell } from "../../layouts/AppShell";
import { useAppToast } from "../../state/useAppToast";
import type { ModuleSnapshot, RuntimeEvent } from "../../types/api";
import { Bar, Panel } from "./shared";

type CmdMode = "Command" | "Help";

const LOG_TABS = ["System Logs", "Errors", "HTTP", "Modules", "MCP", "Workflows"] as const;

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

const DEFAULT_COMMANDS = [
  "help",
  "health",
  "status",
  "events 30",
  "modules list",
  "mcp list",
  "tools",
  "workflows list",
  "jobs list",
  "telemetry",
];

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

function formatEventTime(ms: number): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function nowStamp(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

function levelClass(level: string): string {
  const u = level.toUpperCase();
  if (u === "SUCCESS") return "SUCCESS";
  if (u === "WARNING" || u === "WARN") return "WARNING";
  if (u === "ERROR" || u === "CRITICAL") return u === "CRITICAL" ? "ERROR" : "ERROR";
  if (u === "DEBUG") return "DEBUG";
  return "INFO";
}

function formatBytes(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "Unavailable";
  const gb = n / (1024 * 1024 * 1024);
  if (gb >= 1) return `${gb.toFixed(1)} GB`;
  const mb = n / (1024 * 1024);
  return `${mb.toFixed(0)} MB`;
}

export function ConsolePage() {
  const toast = useAppToast();
  const { sample, error: telemetryError } = useSystemTelemetry({ enabled: true, intervalMs: 2000 });
  const {
    events,
    connection,
    error: eventsError,
    paused,
    setPaused,
    refresh,
    clearLocal,
  } = useLiveEvents({ enabled: true, bufferSize: 800 });

  const [logTab, setLogTab] = useState<(typeof LOG_TABS)[number]>("System Logs");
  const [cmdMode, setCmdMode] = useState<CmdMode>("Command");
  const [filterOpen, setFilterOpen] = useState(false);
  const [logQuery, setLogQuery] = useState("");
  const [command, setCommand] = useState("");
  const [busy, setBusy] = useState(false);
  const [history, setHistory] = useState<Array<{ id: string; time: string; command: string; ok: boolean }>>([]);
  const [commands, setCommands] = useState(DEFAULT_COMMANDS);
  const [modules, setModules] = useState<ModuleSnapshot | null>(null);
  const [modulesError, setModulesError] = useState<string | null>(null);

  useEffect(() => {
    void api.listOperatorCommands().then(
      (data) => {
        if (data.commands?.length) {
          setCommands(data.commands.map((c) => c.name));
        }
      },
      () => undefined,
    );
    void api.listModules().then(
      (data) => {
        setModules(data);
        setModulesError(null);
      },
      (err) => setModulesError(err instanceof Error ? err.message : "Modules unavailable"),
    );
  }, []);

  const filteredLogs = useMemo(() => {
    let rows = events;
    if (logTab === "Errors") {
      rows = rows.filter((e) => {
        const l = e.level.toUpperCase();
        return l === "ERROR" || l === "CRITICAL";
      });
    } else if (logTab === "HTTP") {
      rows = rows.filter((e) => e.category === "http" || e.subsystem === "http");
    } else if (logTab === "Modules") {
      rows = rows.filter((e) => e.category === "module_manager" || Boolean(e.module_id));
    } else if (logTab === "MCP") {
      rows = rows.filter((e) => e.category === "mcp" || Boolean(e.mcp_server_id));
    } else if (logTab === "Workflows") {
      rows = rows.filter((e) => e.category === "workflow" || Boolean(e.workflow_id));
    }
    const q = logQuery.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((e) => {
      const hay = `${e.message} ${e.level} ${e.category} ${e.subsystem} ${e.name} ${e.correlation_id ?? ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [events, logQuery, logTab]);

  const statusCards = useMemo(() => {
    const cpu = sample?.dashboard.cpuPct;
    const connLabel =
      connection === "open"
        ? "Live"
        : connection === "reconnecting"
          ? "Reconnecting"
          : connection === "connecting"
            ? "Connecting"
            : connection === "error"
              ? "Error"
              : "Idle";
    const moduleCount = modules?.modules?.length ?? null;
    return [
      {
        id: "system",
        label: "System",
        value: cpu == null ? "Unavailable" : `${Math.round(cpu)}% CPU`,
        tone: cpu != null && cpu < 85 ? "ok" : undefined,
      },
      {
        id: "uptime",
        label: "Event stream",
        value: connLabel,
        tone: connection === "open" ? "ok" : undefined,
      },
      {
        id: "lograte",
        label: "Buffered events",
        value: String(events.length),
      },
      {
        id: "processes",
        label: "Modules",
        value: moduleCount == null ? "—" : String(moduleCount),
      },
    ];
  }, [connection, events.length, modules, sample]);

  const resources = useMemo(() => {
    const cpu = sample?.dashboard.cpuPct;
    const ram = sample?.dashboard.ramPct;
    const gpu = sample?.dashboard.gpuPct;
    const vram = sample?.dashboard.vramPct;
    const mem = sample?.memory;
    return [
      {
        id: "cpu",
        label: "CPU",
        value: cpu == null ? "Unavailable" : `${cpu.toFixed(0)}%`,
        pct: cpu ?? 0,
        available: cpu != null,
      },
      {
        id: "ram",
        label: "RAM",
        value:
          ram == null
            ? "Unavailable"
            : `${formatBytes(mem?.usedBytes)} / ${formatBytes(mem?.totalBytes)}`,
        pct: ram ?? 0,
        available: ram != null,
      },
      {
        id: "gpu",
        label: "GPU",
        value: gpu == null ? "Unavailable" : `${gpu.toFixed(0)}%`,
        pct: gpu ?? 0,
        available: gpu != null,
      },
      {
        id: "vram",
        label: "VRAM",
        value: vram == null ? "Unavailable" : `${vram.toFixed(0)}%`,
        pct: vram ?? 0,
        available: vram != null,
      },
    ];
  }, [sample]);

  async function runCommand(raw?: string) {
    const text = (raw ?? command).trim();
    if (!text) {
      toast("Enter a command");
      return;
    }
    if (cmdMode === "Help") {
      setCommand("help");
    }
    if (busy) return;
    setBusy(true);
    setHistory((prev) => [{ id: `h-${Date.now()}`, time: nowStamp(), command: text, ok: true }, ...prev].slice(0, 20));
    try {
      const { result } = await api.runOperatorCommand(text);
      setHistory((prev) =>
        prev.map((h, i) => (i === 0 ? { ...h, ok: result.ok } : h)),
      );
      if (result.ok) {
        toast(`OK: ${text}`);
      } else {
        toast(result.error || `Failed: ${text}`);
      }
      void refresh();
      if (text.startsWith("modules")) {
        const snap = await api.listModules();
        setModules(snap);
      }
      setCommand("");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Command failed");
    } finally {
      setBusy(false);
    }
  }

  function copyLogs() {
    const text = filteredLogs
      .map((l) => `${formatEventTime(l.created_at_ms)} [${l.level}] ${l.message}`)
      .join("\n");
    void navigator.clipboard?.writeText(text).then(
      () => toast("Logs copied"),
      () => toast("Copy unavailable"),
    );
  }

  function exportLogs() {
    const payload = JSON.stringify(
      filteredLogs.map((e) => ({
        sequence: e.sequence,
        created_at_ms: e.created_at_ms,
        level: e.level,
        category: e.category,
        subsystem: e.subsystem,
        name: e.name,
        message: e.message,
        correlation_id: e.correlation_id,
        duration_ms: e.duration_ms,
        source: e.source,
      })),
      null,
      2,
    );
    const blob = new Blob([payload], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `leviathan-console-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast("Exported filtered events");
  }

  function renderEvent(line: RuntimeEvent) {
    const lvl = levelClass(line.level);
    return (
      <div key={line.event_id} className="lv-pr-console-log-line">
        <span className="time">{formatEventTime(line.created_at_ms)}</span>
        <span className={`level level-${lvl}`}>[{lvl}]</span>
        <span className="msg">
          {line.subsystem ? `${line.subsystem} · ` : ""}
          {line.message}
          {line.correlation_id ? ` · corr=${line.correlation_id}` : ""}
          {line.duration_ms != null ? ` · ${Math.round(line.duration_ms)}ms` : ""}
        </span>
      </div>
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
              Live Leviathan runtime events, operator commands, and measured resources.
              {eventsError ? ` · ${eventsError}` : ""}
              {telemetryError ? ` · ${telemetryError}` : ""}
            </p>
          </div>
          <p className="lv-pr-console-quote" aria-hidden="true">
            DISCIPLINE CREATES FREEDOM
            <span className="lv-pr-console-quote-mark" />
          </p>
        </header>

        <section className="lv-pr-console-status" aria-label="Console status">
          {statusCards.map((card) => (
            <article key={card.id} className="lv-pr-console-status-card">
              <div className={`lv-pr-console-status-icon${card.tone === "ok" ? " is-ok" : ""}`}>
                {STATUS_ICONS[card.id]}
              </div>
              <div className="lv-pr-console-status-copy">
                <div className="label">{card.label}</div>
                <div className={`value${card.tone === "ok" ? " is-ok" : ""}`}>{card.value}</div>
              </div>
            </article>
          ))}
          <div className="lv-pr-console-toolbar">
            <button
              type="button"
              className="lv-pr-console-tool"
              onClick={() => {
                clearLocal();
                toast("Local view cleared (server history kept)");
              }}
            >
              Clear
            </button>
            <button type="button" className="lv-pr-console-tool" onClick={exportLogs}>
              Export
            </button>
            <button
              type="button"
              className={`lv-pr-console-tool${filterOpen ? " is-active" : ""}`}
              onClick={() => setFilterOpen((v) => !v)}
            >
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
              {paused ? "Resume" : "Pause"}
            </button>
            <button type="button" className="lv-pr-console-tool" onClick={() => void refresh()}>
              Refresh
            </button>
          </div>
        </section>

        {filterOpen ? (
          <div className="lv-pr-console-filter">
            <input
              className="lv-pr-console-filter-input"
              value={logQuery}
              onChange={(e) => setLogQuery(e.target.value)}
              placeholder="Filter by message, level, category, correlation…"
              aria-label="Filter logs"
            />
          </div>
        ) : null}

        <div className="lv-pr-console-layout">
          <div className="lv-pr-console-main">
            <div className="lv-pr-console-tabs" role="tablist" aria-label="Log channels">
              {LOG_TABS.map((tab) => (
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
              </div>
              <div
                className={`lv-pr-console-log${paused ? " is-paused" : ""}`}
                role="log"
                aria-live={paused ? "off" : "polite"}
              >
                {filteredLogs.length === 0 ? (
                  <div className="lv-pr-console-log-empty">
                    {connection === "connecting" ? "Connecting to event stream…" : "No events match this view."}
                  </div>
                ) : (
                  filteredLogs.map(renderEvent)
                )}
              </div>
            </div>

            <section className="lv-pr-console-cmd" aria-label="Command input">
              <div className="lv-pr-console-tabs is-cmd" role="tablist" aria-label="Command mode">
                {(["Command", "Help"] as const).map((mode) => (
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
                  <span className="prompt">leviathan&gt;</span>
                  <input
                    value={command}
                    onChange={(e) => setCommand(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        void runCommand();
                      }
                    }}
                    placeholder="Operator command (help, modules list, mcp list, …)"
                    aria-label="Console command"
                    spellCheck={false}
                    disabled={busy}
                  />
                </label>
                <div className="lv-pr-console-run">
                  <button
                    type="button"
                    className="lv-pr-console-run-btn"
                    onClick={() => void runCommand()}
                    disabled={busy}
                  >
                    {busy ? "…" : "Run"}
                  </button>
                </div>
              </div>
              <div className="lv-pr-console-common-block">
                <div className="lv-pr-console-common-label">Common Commands</div>
                <div className="lv-pr-console-common">
                  {commands.map((chip) => (
                    <button
                      key={chip}
                      type="button"
                      className="lv-pr-console-chip"
                      onClick={() => {
                        setCommand(chip);
                        void runCommand(chip);
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
            <Panel className="lv-pr-console-panel" title="Runtime Components">
              <div className="lv-pr-console-process-list">
                {(modules?.modules ?? []).length === 0 ? (
                  <div className="lv-pr-console-log-empty">
                    {modulesError || (modules?.enabled === false ? "Module manager disabled" : "No modules discovered")}
                  </div>
                ) : (
                  (modules?.modules ?? []).map((m) => {
                    const id = m.manifest?.module_id ?? "unknown";
                    const status = m.status ?? "UNKNOWN";
                    return (
                      <div key={id} className="lv-pr-console-process">
                        <div>
                          <div className="name">{m.manifest?.name ?? id}</div>
                          <div className="meta">
                            {status}
                            {m.error ? ` · ${m.error}` : ""}
                          </div>
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </Panel>

            <Panel className="lv-pr-console-panel" title="Resources">
              <div className="lv-pr-console-resources">
                {resources.map((r) => (
                  <div key={r.id} className="lv-pr-console-resource">
                    <div className="lv-pr-console-resource-head">
                      <span>{r.label}</span>
                      <span>{r.value}</span>
                    </div>
                    {r.available ? <Bar pct={r.pct} tone="cyan" className="lv-pr-console-resource-bar" /> : null}
                  </div>
                ))}
              </div>
            </Panel>

            <Panel className="lv-pr-console-panel" title="Command History">
              <div className="lv-pr-console-history">
                {history.length === 0 ? (
                  <div className="lv-pr-console-log-empty">No commands yet</div>
                ) : (
                  history.map((h) => (
                    <button
                      key={h.id}
                      type="button"
                      className="lv-pr-console-history-item"
                      onClick={() => setCommand(h.command)}
                    >
                      <span className="time">{h.time}</span>
                      <span className={h.ok ? "ok" : "err"}>{h.command}</span>
                    </button>
                  ))
                )}
              </div>
            </Panel>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}
