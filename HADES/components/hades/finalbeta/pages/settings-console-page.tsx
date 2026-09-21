"use client";

import { useMemo, useState } from "react";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import {
  PR_CONSOLE_ENV,
  PR_CONSOLE_FILTERS,
  PR_CONSOLE_HEALTH,
  PR_CONSOLE_HISTORY,
  PR_CONSOLE_LOGS,
  PR_CONSOLE_PROCESSES,
  PR_CONSOLE_QUICK,
  PR_CONSOLE_QUOTE,
  PR_CONSOLE_RESOURCES,
  PR_CONSOLE_STATUS,
  PR_CONSOLE_TABS,
  type ConsoleLogLevel,
  type ConsoleTabId,
} from "../mocks/pr-console";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

const CMD_PROMPT = ">_";

function levelDot(level: ConsoleLogLevel): string {
  if (level === "SUCCESS") return "green";
  if (level === "WARN") return "gold";
  if (level === "ERROR") return "red";
  if (level === "DEBUG") return "cyan";
  return "blue";
}

/** Console under Plugin & Runtime (`settings-console`). */
export function SettingsConsolePage({ onNavigate }: Props) {
  const [tab, setTab] = useState<ConsoleTabId>("live");
  const [paused, setPaused] = useState(false);
  const [query, setQuery] = useState("");
  const [command, setCommand] = useState("");
  const [filters, setFilters] = useState(() =>
    Object.fromEntries(PR_CONSOLE_FILTERS.map((f) => [f.id, f.checked])) as Record<ConsoleLogLevel, boolean>,
  );

  const logs = useMemo(() => {
    const q = query.trim().toLowerCase();
    return PR_CONSOLE_LOGS.filter((line) => {
      if (!filters[line.level]) return false;
      if (!q) return true;
      return (
        line.message.toLowerCase().includes(q) ||
        line.service.toLowerCase().includes(q) ||
        line.level.toLowerCase().includes(q)
      );
    });
  }, [filters, query]);

  const body = (
    <div className="mc-page prc-page" data-page="console">
      <MediaWelcome
        title="Console"
        subtitle="Live systeemlogs, commando's en servicebeheer voor je HADES omgeving."
        quote={PR_CONSOLE_QUOTE}
        right={
          <div className="prc-welcome-actions">
            <button type="button" className="btn btn-outline" data-toast="Log exporteren">
              <FbIcon name="download" size={13} />
              Log exporteren
            </button>
            <button type="button" className="btn btn-outline" data-toast="Weergave">
              Weergave
              <FbIcon name="chevron" size={12} />
            </button>
            <button type="button" className="btn prc-btn-clear" data-toast="Console wissen">
              <FbIcon name="trash" size={13} />
              Console wissen
            </button>
          </div>
        }
      />

      <div className="prc-tabs" role="tablist">
        {PR_CONSOLE_TABS.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            className={`prc-tab${tab === item.id ? " active" : ""}`}
            aria-selected={tab === item.id}
            onClick={() => setTab(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>

      <section className="mc-panel prc-log-panel">
        <div className="prc-log-toolbar">
          <button
            type="button"
            className="prc-pause"
            data-toast={paused ? "Hervat" : "Gepauzeerd"}
            onClick={() => setPaused((v) => !v)}
          >
            <FbIcon name={paused ? "play" : "pause"} size={12} />
            {paused ? "Hervatten" : "Pauzeren"}
          </button>
          <span className="prc-live">
            <span className={`mc-dot ${paused ? "gold" : "green"}`} />
            {paused ? "Output gepauzeerd" : "Live output (volgt real-time)"}
          </span>
          <button type="button" className="prc-select" data-toast="Alle services">
            Alle services
            <FbIcon name="chevron" size={11} />
          </button>
          <button type="button" className="prc-select" data-toast="Alle niveaus">
            Alle niveaus
            <FbIcon name="chevron" size={11} />
          </button>
          <label className="prc-search">
            <FbIcon name="search" size={12} />
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Zoeken in logs..."
              aria-label="Zoeken in logs"
            />
          </label>
        </div>

        <div className="prc-log-body" role="log" aria-live={paused ? "off" : "polite"}>
          {logs.map((line) => (
            <div key={line.id} className={`prc-log-line ${line.level}`}>
              <span className="prc-log-time">{line.time}</span>
              <span className={`prc-log-level ${line.level}`}>
                <span className={`mc-dot ${levelDot(line.level)}`} />
                {line.level}
              </span>
              <span className="prc-log-svc">{line.service}</span>
              <span className="prc-log-msg">
                {line.message}
                {line.link ? (
                  <a href={line.link} onClick={(e) => e.preventDefault()}>
                    {line.link}
                  </a>
                ) : null}
              </span>
            </div>
          ))}
        </div>
      </section>

      <div className="prc-cmd-row">
        <label className="prc-cmd-input">
          <span className="prc-cmd-prompt" aria-hidden="true">
            {CMD_PROMPT}
          </span>
          <input
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="Voer een commando in... (bijv. system.status, service.restart llm, logs --follow)"
            aria-label="Console commando"
          />
        </label>
        <button type="button" className="prc-run" data-toast={command.trim() || "Uitvoeren"}>
          <FbIcon name="play" size={13} />
          Uitvoeren
        </button>
      </div>

      <div className="prc-quick">
        <span className="prc-quick-label">Snelle commando&apos;s</span>
        {PR_CONSOLE_QUICK.map((item) => (
          <button
            key={item.id}
            type="button"
            className="prc-pill"
            data-toast={item.label}
            onClick={() => setCommand(item.label)}
          >
            {item.icon ? <FbIcon name={item.icon} size={10} /> : null}
            {item.label}
          </button>
        ))}
      </div>

      <div className="prc-bottom">
        <section className="mc-panel prc-card">
          <div className="prc-card-head">
            <div className="prc-card-title">
              <span className="ico">
                <FbIcon name="terminal" size={13} />
              </span>
              Commando geschiedenis
            </div>
            <button type="button" className="prc-link" data-toast="Geschiedenis wissen">
              Wissen
            </button>
          </div>
          <div className="prc-hist-list">
            {PR_CONSOLE_HISTORY.map((row) => (
              <div key={row.id} className="prc-hist-row">
                <span className="prc-hist-time">{row.time}</span>
                <span className="prc-hist-prompt" aria-hidden="true">
                  {CMD_PROMPT}
                </span>
                <span className="prc-hist-cmd">{row.command}</span>
                <button
                  type="button"
                  className="prc-hist-copy"
                  data-toast={row.command}
                  onClick={() => setCommand(row.command)}
                  aria-label="Herstel commando"
                >
                  <FbIcon name="copy" size={11} />
                </button>
              </div>
            ))}
          </div>
        </section>

        <section className="mc-panel prc-card">
          <div className="prc-card-head">
            <div className="prc-card-title">
              <span className="ico">
                <FbIcon name="shield" size={13} />
              </span>
              Actieve processen
            </div>
            <button type="button" className="prc-details-btn" data-toast="Details openen">
              Details
              <FbIcon name="chevron" size={11} />
            </button>
          </div>
          <table className="prc-proc-table">
            <thead>
              <tr>
                <th>PID</th>
                <th>Naam</th>
                <th>CPU</th>
                <th>Geheugen</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {PR_CONSOLE_PROCESSES.map((proc) => (
                <tr key={proc.pid}>
                  <td>{proc.pid}</td>
                  <td>{proc.name}</td>
                  <td>{proc.cpu}</td>
                  <td>{proc.memory}</td>
                  <td>
                    <span className="prc-status">
                      <FbIcon name="checkcircle" size={12} />
                      {proc.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="mc-panel prc-card">
          <div className="prc-card-head">
            <div className="prc-card-title">
              <span className="ico">
                <FbIcon name="settings" size={13} />
              </span>
              Systeembronnen
            </div>
          </div>
          <div className="prc-res-list">
            {PR_CONSOLE_RESOURCES.map((res) => (
              <div key={res.id} className="prc-res-row">
                <span className="prc-res-label">
                  <span className="ico">
                    <FbIcon name={res.id === "net" ? "globe" : res.id === "disk" ? "database" : "chart"} size={11} />
                  </span>
                  {res.label}
                </span>
                <span className="prc-res-value">{res.value}</span>
                <div className={`prc-res-bar${res.tone === "blue" ? " blue" : ""}`}>
                  <span style={{ width: `${res.pct}%` }} />
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">“{PR_CONSOLE_QUOTE}”</p>

      <section className="mc-insp-section">
        <div className="mc-insp-card prc-status-card">
          <div className="prc-status-head">
            <h3>HADES STATUS</h3>
            <span className="prc-live-pill">
              <span className="mc-dot green" />
              LIVE
            </span>
          </div>
          <div className="prc-status-body">
            {PR_CONSOLE_STATUS.map((row) => (
              <div key={row.k} className="prc-status-row">
                <span className="prc-status-k">
                  <span className={`mc-dot ${row.tone === "green" ? "green" : "gold"}`} />
                  {row.k}
                </span>
                <span className={`prc-status-v${row.v === "Online" ? " green" : ""}`}>{row.v}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Console filters</h3>
        <div className="mc-insp-card prc-filter-list">
          {PR_CONSOLE_FILTERS.map((f) => (
            <label
              key={f.id}
              className="prc-filter-row"
              onClick={(e) => {
                e.preventDefault();
                setFilters((prev) => ({ ...prev, [f.id]: !prev[f.id] }));
              }}
            >
              <span className="prc-filter-left">
                <span className={`prc-check${filters[f.id] ? ` on ${f.tone}` : ""}`} aria-hidden="true">
                  {filters[f.id] ? "✓" : ""}
                </span>
                {f.label}
              </span>
              <span className="prc-filter-count">{f.count}</span>
            </label>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Service gezondheid</h3>
        <div className="mc-insp-card prc-health-list">
          {PR_CONSOLE_HEALTH.map((svc) => (
            <div key={svc.id} className="prc-health-row">
              <span className="prc-health-name">
                <span className="ico">
                  <FbIcon name={svc.icon} size={12} />
                </span>
                {svc.name}
              </span>
              <span className="prc-health-ok">
                <FbIcon name="checkcircle" size={12} />
                OK
              </span>
            </div>
          ))}
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">Omgeving</h3>
        <div className="mc-insp-card">
          {PR_CONSOLE_ENV.map((row) => (
            <div className="mc-detail-row" key={row.k}>
              <span className="k">{row.k}</span>
              <span className="v">{row.v}</span>
            </div>
          ))}
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="settings-console"
      appClassName="mc-app pr-app pr-console-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
