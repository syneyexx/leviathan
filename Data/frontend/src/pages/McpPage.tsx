import { useMemo, useState, type ReactNode } from "react";
import { pluginRuntimeHeroes } from "../assets/pluginRuntimeAssets";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import {
  MCP_ALERTS,
  MCP_AUTH_POLICIES,
  MCP_AUTH_SUMMARY,
  MCP_BRIDGE,
  MCP_KPIS,
  MCP_QUICK_ACTIONS,
  MCP_RECENT_CALLS,
  MCP_SERVERS,
  MCP_TOOL_CATALOG,
  MCP_TRANSPORTS,
  type PrTone,
} from "./plugin-runtime/mocks";
import { Bar, Panel, Pill, PrHero, Spark, Toggle } from "./plugin-runtime/shared";

const SERVER_ICONS: Record<string, ReactNode> = {
  filesystem: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M2 4h5l1.2 1.2H14v7.3H2z" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  git: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="8" cy="4" r="1.6" fill="currentColor" />
      <circle cx="4.5" cy="12" r="1.6" fill="currentColor" />
      <circle cx="11.5" cy="12" r="1.6" fill="currentColor" />
      <path d="M8 5.6v6.8M8 10.2l-2.8 1.2M8 10.2l2.8 1.2" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  fetch: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M3 8h10M10 5l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  github: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path
        d="M8 1.5A6.5 6.5 0 0 0 1.5 8c0 2.9 1.9 5.3 4.5 6.2.3.06.4-.14.4-.3v-1.1c-1.8.4-2.2-.8-2.2-.8-.3-.7-.7-.9-.7-.9-.6-.4.04-.4.04-.4.6.04 1 .7 1 .7.6 1 1.5.7 1.9.5.06-.4.2-.7.4-.9-1.5-.2-3-0.7-3-3.2 0-.7.3-1.3.7-1.8-.07-.2-.3-.9.06-1.8 0 0 .6-.2 1.9.7a6.4 6.4 0 0 1 3.4 0c1.3-.9 1.9-.7 1.9-.7.4.9.1 1.6.06 1.8.4.5.7 1.1.7 1.8 0 2.5-1.6 3-3.1 3.2.2.2.4.6.4 1.2v1.7c0 .16.1.36.4.3A6.5 6.5 0 0 0 14.5 8 6.5 6.5 0 0 0 8 1.5z"
        fill="currentColor"
      />
    </svg>
  ),
  browser: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M2.8 8h10.4M8 2.8c1.6 1.8 1.6 8.6 0 10.4M8 2.8C6.4 4.6 6.4 11.4 8 13.2" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  postgres: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <ellipse cx="8" cy="4.2" rx="5" ry="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M3 4.2v5.2c0 1.1 2.2 2 5 2s5-.9 5-2V4.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  memory: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <rect x="3" y="3" width="10" height="10" rx="1.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M5.5 6h5M5.5 8.5h5M5.5 11h3" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  docs: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M4 2.5h5.5L12 5v8.5H4z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M9.5 2.5V5H12" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  "local-python": (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M5 3.5h4.5c1.5 0 2.5 1 2.5 2.4v1.2H8.2c-1.4 0-2.4.9-2.4 2.2v1.2c0 1.3 1 2.2 2.4 2.2H12" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <circle cx="6.2" cy="5.2" r="0.7" fill="currentColor" />
      <circle cx="9.8" cy="10.8" r="0.7" fill="currentColor" />
    </svg>
  ),
};

const KPI_ICONS: Record<string, ReactNode> = {
  servers: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <rect x="2.5" y="2.5" width="11" height="3.2" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <rect x="2.5" y="6.4" width="11" height="3.2" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <rect x="2.5" y="10.3" width="11" height="3.2" rx="0.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  connected: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M6.2 9.8 4.4 8a2.4 2.4 0 1 1 3.4-3.4l.9.9M9.8 6.2 11.6 8a2.4 2.4 0 1 1-3.4 3.4l-.9-.9" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  tools: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 2.5 13 5.5v5L8 13.5 3 10.5v-5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  sessions: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="6" cy="5.5" r="2" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <circle cx="11" cy="6.2" r="1.6" fill="none" stroke="currentColor" strokeWidth="1.1" />
      <path d="M2.5 13c.4-2.2 1.9-3.3 3.5-3.3S9.1 10.8 9.5 13M9.8 9.8c1.2.1 2.3.8 2.7 2.4" fill="none" stroke="currentColor" strokeWidth="1.1" />
    </svg>
  ),
  throughput: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M2 8h2l1.5-3 2 6 2-4 1.5 2H14" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinejoin="round" />
    </svg>
  ),
  approval: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 2.2 12.5 4v3.4c0 2.8-1.9 4.8-4.5 5.6-2.6-.8-4.5-2.8-4.5-5.6V4z" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  error: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 2.5 14 13.5H2z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 6.5v3.2M8 11.2h.01" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  latency: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 8 11 5.5M8 4.2v1.4" fill="none" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    </svg>
  ),
};

const AUTH_ICONS: Record<string, ReactNode> = {
  discovered: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M8 2.2 13 5v6L8 13.8 3 11V5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  authorized: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M8 2.2 12.5 4v3.4c0 2.8-1.9 4.8-4.5 5.6-2.6-.8-4.5-2.8-4.5-5.6V4z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="m5.8 8 1.5 1.5 3-3" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  queued: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <path d="M8 2.5 14 13.5H2z" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M8 6.5v3.2M8 11.2h.01" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" />
    </svg>
  ),
  blocked: (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      <circle cx="8" cy="8" r="5.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="m4.6 4.6 6.8 6.8" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
};

const QUICK_ICONS: Record<string, ReactNode> = {
  add: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M8 3v10M3 8h10" fill="none" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" />
    </svg>
  ),
  rediscover: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M3.5 8a4.5 4.5 0 0 1 7.6-3.2L13 3v4H9l1.4-1.4A3.2 3.2 0 1 0 11.3 10" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  restart: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <path d="M3.5 8a4.5 4.5 0 0 1 7.6-3.2L13 3v4H9" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M12.5 8a4.5 4.5 0 0 1-7.6 3.2L3 13V9h4" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  ),
  config: (
    <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
      <circle cx="8" cy="8" r="2.2" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path
        d="M8 2.2v1.4M8 12.4v1.4M2.2 8h1.4M12.4 8h1.4M3.8 3.8l1 1M11.2 11.2l1 1M12.2 3.8l-1 1M4.8 11.2l-1 1"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.1"
        strokeLinecap="round"
      />
    </svg>
  ),
};

function StatusDot({ tone }: { tone: PrTone }) {
  return <span className={`lv-pr-mcp-dot is-${tone}`} aria-hidden="true" />;
}

function IconBtn({
  label,
  onClick,
  children,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button type="button" className="lv-pr-mcp-icon-btn" aria-label={label} title={label} onClick={onClick}>
      {children}
    </button>
  );
}

export function McpPage() {
  const toast = useAppToast();
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [transportFilter, setTransportFilter] = useState("all");
  const [enabledMap, setEnabledMap] = useState<Record<string, boolean>>(() =>
    Object.fromEntries(MCP_SERVERS.map((s) => [s.id, s.enabled])),
  );
  const [policies, setPolicies] = useState<Record<string, string>>(() =>
    Object.fromEntries(MCP_AUTH_POLICIES.map((p) => [p.id, p.value])),
  );

  const filteredServers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return MCP_SERVERS.filter((s) => {
      if (statusFilter !== "all" && s.status !== statusFilter) return false;
      if (transportFilter !== "all" && s.transport !== transportFilter) return false;
      if (!q) return true;
      return `${s.name} ${s.transport} ${s.isolation} ${s.lastError}`.toLowerCase().includes(q);
    });
  }, [query, statusFilter, transportFilter]);

  const toggleServer = (id: string, name: string) => {
    setEnabledMap((prev) => {
      const next = !prev[id];
      toast(next ? `${name} ingeschakeld` : `${name} uitgeschakeld`);
      return { ...prev, [id]: next };
    });
  };

  return (
    <AppShell
      activeMode="explore"
      modeLabel="Research Mode"
      searchPlaceholder="Zoek servers, tools, transports..."
      systemItems={["SYSTEMS ONLINE", "LLM", "NEURAL", "MEMORY", "TOOLS"]}
      layout="wide"
      pageClass="lv-app--plugin-runtime"
    >
      <main className="lv-main lv-pr-main">
        <PrHero title="MCP" image={pluginRuntimeHeroes.mcp} imageOnly />

        <section className="lv-pr-kpi-row" aria-label="MCP metrics">
          {MCP_KPIS.map((kpi) => (
            <article
              key={kpi.id}
              className={`lv-pr-kpi${"warn" in kpi && kpi.warn ? " is-warn" : ""}`}
            >
              <div className="lv-pr-kpi-label">{kpi.label}</div>
              <div className="lv-pr-mcp-kpi-body">
                <span className={`lv-pr-mcp-kpi-icon${"warn" in kpi && kpi.warn ? " is-warn" : ""}`}>
                  {KPI_ICONS[kpi.id]}
                </span>
                <div className="lv-pr-mcp-kpi-main">
                  <div className="lv-pr-kpi-value">
                    {kpi.value}
                    {"sub" in kpi && kpi.sub ? <small> {kpi.sub}</small> : null}
                  </div>
                  <div className="lv-pr-kpi-foot">
                    {"delta" in kpi && kpi.delta ? (
                      <span className={`lv-pr-kpi-delta${kpi.deltaGood ? " is-good" : " is-bad"}`}>
                        {kpi.delta}
                      </span>
                    ) : "pct" in kpi && kpi.pct != null ? (
                      <span className="lv-pr-kpi-delta is-good">{kpi.pct}%</span>
                    ) : (
                      <span />
                    )}
                    {"spark" in kpi && kpi.spark ? (
                      <Spark points={kpi.spark} color="#00E5FF" width={56} height={18} />
                    ) : "pct" in kpi && kpi.pct != null ? (
                      <Bar pct={kpi.pct} tone={"barTone" in kpi ? kpi.barTone : "cyan"} className="lv-pr-mcp-kpi-bar" />
                    ) : null}
                  </div>
                </div>
              </div>
            </article>
          ))}
        </section>

        <section className="lv-pr-mcp-grid">
          <div className="lv-pr-mcp-col-main">
            <Panel
              className="lv-pr-mcp-servers"
              title="MCP Servers"
              action={
                <div className="lv-pr-mcp-toolbar">
                  <input
                    className="lv-pr-mcp-input"
                    placeholder="Zoek servers, tools, transport..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    aria-label="Zoek servers"
                  />
                  <select
                    className="lv-pr-mcp-select"
                    value={statusFilter}
                    onChange={(e) => setStatusFilter(e.target.value)}
                    aria-label="Filter status"
                  >
                    <option value="all">Alle statussen</option>
                    <option value="Verbonden">Verbonden</option>
                    <option value="Fout">Fout</option>
                  </select>
                  <select
                    className="lv-pr-mcp-select"
                    value={transportFilter}
                    onChange={(e) => setTransportFilter(e.target.value)}
                    aria-label="Filter transport"
                  >
                    <option value="all">Alle transports</option>
                    <option value="stdio">stdio</option>
                    <option value="http">http</option>
                  </select>
                  <button
                    type="button"
                    className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                    onClick={() => toast("Server toevoegen")}
                  >
                    + Server toevoegen
                  </button>
                </div>
              }
            >
              <div className="lv-pr-table-wrap">
                <table className="lv-pr-table lv-pr-mcp-server-table">
                  <thead>
                    <tr>
                      <th>Naam</th>
                      <th>Transport</th>
                      <th>Status</th>
                      <th>Ingeschakeld</th>
                      <th>Tools</th>
                      <th>Laatste Health</th>
                      <th>Isolatie</th>
                      <th>Laatste Fout</th>
                      <th>Acties</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredServers.map((server) => {
                      const on = enabledMap[server.id] ?? server.enabled;
                      return (
                        <tr key={server.id}>
                          <td>
                            <span className="lv-pr-mcp-name">
                              <span className="lv-pr-mcp-name-icon">{SERVER_ICONS[server.id] ?? SERVER_ICONS.docs}</span>
                              <span className="is-name">{server.name}</span>
                            </span>
                          </td>
                          <td>{server.transport}</td>
                          <td>
                            <span className={`lv-pr-mcp-status is-${server.statusTone}`}>
                              <StatusDot tone={server.statusTone} />
                              {server.status}
                            </span>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="lv-pr-mcp-toggle-btn"
                              onClick={() => toggleServer(server.id, server.name)}
                              aria-label={`${server.name} ${on ? "uitschakelen" : "inschakelen"}`}
                            >
                              <Toggle on={on} label={server.name} />
                            </button>
                          </td>
                          <td>{server.tools}</td>
                          <td className="lv-pr-mcp-health">{server.lastHealth}</td>
                          <td className="lv-pr-mcp-iso">{server.isolation}</td>
                          <td className={server.lastError !== "—" ? "is-err" : ""}>{server.lastError}</td>
                          <td>
                            <div className="lv-pr-mcp-row-actions">
                              <IconBtn label="Open" onClick={() => toast(`${server.name} openen`)}>
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <path d="M6 3.5H3.5v9h9V10M8.5 3.5H12.5V7.5M12.5 3.5 7 9" fill="none" stroke="currentColor" strokeWidth="1.2" />
                                </svg>
                              </IconBtn>
                              <IconBtn label="Instellingen" onClick={() => toast(`${server.name} instellingen`)}>
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" strokeWidth="1.2" />
                                  <path d="M8 2.4v1.3M8 12.3v1.3M2.4 8h1.3M12.3 8h1.3" fill="none" stroke="currentColor" strokeWidth="1.1" />
                                </svg>
                              </IconBtn>
                              <IconBtn label="Vernieuwen" onClick={() => toast(`${server.name} health check`)}>
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <path d="M3.5 8a4.5 4.5 0 0 1 7.5-3.3L13 3v4H9" fill="none" stroke="currentColor" strokeWidth="1.2" />
                                </svg>
                              </IconBtn>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </Panel>

            <div className="lv-pr-mcp-lower-left">
              <Panel className="lv-pr-mcp-auth" title="Autorisatie & Goedkeuringen">
                <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                  Beheer tool-toegang, permissies en goedkeuringsbeleid.
                </p>
                <div className="lv-pr-mcp-auth-summary">
                  {MCP_AUTH_SUMMARY.map((item) => (
                    <div
                      key={item.id}
                      className={`lv-pr-mcp-auth-box${"tone" in item && item.tone ? ` is-${item.tone}` : ""}`}
                    >
                      <span className={`lv-pr-mcp-auth-icon${"tone" in item && item.tone ? ` is-${item.tone}` : " is-gold"}`}>
                        {AUTH_ICONS[item.id]}
                      </span>
                      <div>
                        <div className="lv-pr-mcp-auth-label">{item.label}</div>
                        <div className="lv-pr-mcp-auth-value">{item.value}</div>
                        {item.id === "authorized" ? <div className="lv-pr-mcp-auth-meta is-ok">85%</div> : null}
                        {item.id === "queued" ? <div className="lv-pr-mcp-auth-meta is-err">Goedkeuring</div> : null}
                        {item.id === "blocked" ? <div className="lv-pr-mcp-auth-meta">Beleid</div> : null}
                        {item.id === "discovered" ? <div className="lv-pr-mcp-auth-meta is-ok">+12</div> : null}
                      </div>
                    </div>
                  ))}
                </div>

                <div className="lv-pr-mcp-policy-title">Toegangsbeleid</div>
                <div className="lv-pr-mcp-policies">
                  {MCP_AUTH_POLICIES.map((policy) => (
                    <label key={policy.id} className="lv-pr-mcp-policy-row">
                      <span>{policy.label}</span>
                      <select
                        className="lv-pr-mcp-select"
                        value={policies[policy.id] ?? policy.value}
                        onChange={(e) => {
                          setPolicies((prev) => ({ ...prev, [policy.id]: e.target.value }));
                          toast(`${policy.label}: ${e.target.value}`);
                        }}
                      >
                        <option value={policy.value}>{policy.value}</option>
                        <option value="Altijd toestaan">Altijd toestaan</option>
                        <option value="Altijd vragen">Altijd vragen</option>
                        <option value="Blokkeren">Blokkeren</option>
                      </select>
                    </label>
                  ))}
                </div>
              </Panel>

              <Panel
                className="lv-pr-mcp-calls"
                title="Recente Tool Calls"
                action={
                  <button
                    type="button"
                    className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                    onClick={() => toast("Alle logs")}
                  >
                    Alle logs
                  </button>
                }
              >
                <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                  Laatste MCP tool aanroepen in het systeem.
                </p>
                <div className="lv-pr-table-wrap">
                  <table className="lv-pr-table lv-pr-mcp-calls-table">
                    <thead>
                      <tr>
                        <th>Tijdstip</th>
                        <th>Tool Naam</th>
                        <th>Aangevraagd Door</th>
                        <th>Duur</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {MCP_RECENT_CALLS.map((call) => (
                        <tr key={call.id}>
                          <td className="lv-pr-mcp-mono">{call.time}</td>
                          <td className="is-name">{call.tool}</td>
                          <td>{call.requester}</td>
                          <td>{call.duration}</td>
                          <td>
                            <span className={`lv-pr-mcp-status is-${call.statusTone}`}>
                              <StatusDot tone={call.statusTone} />
                              {call.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>

          <aside className="lv-pr-mcp-col-side">
            <Panel className="lv-pr-mcp-bridge" title="Bridge Samenvatting">
              <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                Een universele MCP bridge voor alle servers en transports.
              </p>
              <div className="lv-pr-mcp-bridge-body">
                <div className="lv-pr-mcp-bridge-left">
                  <div className="lv-pr-mcp-bridge-title">{MCP_BRIDGE.title}</div>
                  <Pill tone={MCP_BRIDGE.statusTone}>{MCP_BRIDGE.status}</Pill>
                  <div className="lv-pr-mcp-bridge-uptime">Uptime: {MCP_BRIDGE.uptime}</div>
                  <div className="lv-pr-mcp-bridge-viz" aria-hidden="true">
                    <svg viewBox="0 0 120 90" width="110" height="82">
                      <defs>
                        <linearGradient id="mcpBridgeGlow" x1="0" y1="0" x2="1" y2="1">
                          <stop offset="0%" stopColor="#00E5FF" stopOpacity="0.95" />
                          <stop offset="100%" stopColor="#22C9D6" stopOpacity="0.35" />
                        </linearGradient>
                      </defs>
                      <path d="M60 8 104 30 60 52 16 30Z" fill="none" stroke="url(#mcpBridgeGlow)" strokeWidth="1.4" />
                      <path d="M16 30v28l44 22 44-22V30" fill="none" stroke="url(#mcpBridgeGlow)" strokeWidth="1.3" />
                      <path d="M60 52v28" fill="none" stroke="url(#mcpBridgeGlow)" strokeWidth="1.2" />
                      <path d="M28 36h64M28 44h64M28 52h64" stroke="#00E5FF" strokeOpacity="0.35" strokeWidth="1" />
                      <circle cx="60" cy="30" r="4" fill="#00E5FF" opacity="0.85" />
                    </svg>
                  </div>
                  <div className="lv-pr-mcp-bridge-actions">
                    <button type="button" className="lv-pr-mcp-btn lv-pr-mcp-btn--gold" onClick={() => toast("Bridge herstarten")}>
                      Bridge herstarten
                    </button>
                    <button type="button" className="lv-pr-mcp-btn" onClick={() => toast("Configuratie")}>
                      Configuratie
                    </button>
                  </div>
                </div>
                <div className="lv-pr-mcp-bridge-right">
                  <div className="lv-pr-mcp-bridge-stat">
                    <span>Totaal sessies</span>
                    <strong>{MCP_BRIDGE.sessions}</strong>
                  </div>
                  <div className="lv-pr-mcp-bridge-stat">
                    <span>Actieve servers</span>
                    <strong>{MCP_BRIDGE.activeServers}</strong>
                  </div>
                  <div className="lv-pr-mcp-mix-label">Transport Mix</div>
                  {MCP_BRIDGE.transportMix.map((mix) => (
                    <div key={mix.id} className="lv-pr-mcp-mix-row">
                      <span>{mix.label}</span>
                      <Bar pct={mix.pct} tone={mix.tone} />
                      <em>{mix.pct}%</em>
                    </div>
                  ))}
                  <div className="lv-pr-mcp-mix-label">Huidige Health</div>
                  <div className="lv-pr-mcp-mix-row">
                    <Bar pct={MCP_BRIDGE.healthPct} tone="cyan" className="lv-pr-mcp-health-bar" />
                    <em>{MCP_BRIDGE.healthPct}%</em>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel
              className="lv-pr-mcp-catalog"
              title="Tool Discovery / Catalogus"
              action={
                <button type="button" className="lv-pr-mcp-btn" onClick={() => toast("Catalogus vernieuwd")}>
                  Vernieuwen
                </button>
              }
            >
              <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                Ontdekte tools uit alle MCP servers.
              </p>
              <div className="lv-pr-table-wrap">
                <table className="lv-pr-table lv-pr-mcp-catalog-table">
                  <thead>
                    <tr>
                      <th>Tool Naam</th>
                      <th>Server</th>
                      <th>Beschrijving</th>
                    </tr>
                  </thead>
                  <tbody>
                    {MCP_TOOL_CATALOG.map((tool) => (
                      <tr key={tool.id}>
                        <td>
                          <span className="lv-pr-mcp-name">
                            <span className="lv-pr-mcp-name-icon is-gold">
                              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                                <path d="M8 2.5 13 5.5v5L8 13.5 3 10.5v-5z" fill="none" stroke="currentColor" strokeWidth="1.2" />
                              </svg>
                            </span>
                            <span className="is-name">{tool.name}</span>
                          </span>
                        </td>
                        <td>{tool.server}</td>
                        <td className="lv-pr-mcp-desc">{tool.description}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <div className="lv-pr-mcp-side-bottom">
              <div className="lv-pr-mcp-side-stack">
                <Panel
                  className="lv-pr-mcp-transports"
                  title="Transport & Health"
                  action={
                    <button type="button" className="lv-pr-mcp-btn" onClick={() => toast("Transport details")}>
                      Details
                    </button>
                  }
                >
                  <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                    Status van MCP transports en verbindingen.
                  </p>
                  <div className="lv-pr-mcp-transport-list">
                    {MCP_TRANSPORTS.map((t) => (
                      <article key={t.id} className="lv-pr-mcp-transport-card">
                        <div className="lv-pr-mcp-transport-head">
                          <strong>{t.label}</strong>
                          <Pill tone={t.statusTone}>{t.status}</Pill>
                        </div>
                        <div className="lv-pr-mcp-transport-body">
                          <div>
                            <div className="lv-pr-mcp-transport-servers">{t.servers} servers</div>
                            <div className="lv-pr-mcp-transport-lat">Gem. latentie {t.latency}</div>
                          </div>
                          <Spark
                            points={t.id === "stdio" ? [20, 28, 24, 36, 30, 42, 38, 44] : [30, 26, 34, 28, 40, 36, 48, 42]}
                            color="#00E5FF"
                            width={72}
                            height={22}
                          />
                        </div>
                      </article>
                    ))}
                  </div>
                </Panel>

                <Panel
                  className="lv-pr-mcp-alerts"
                  title="Recente Alerts"
                  action={
                    <button
                      type="button"
                      className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                      onClick={() => toast("Alle alerts")}
                    >
                      Alle alerts
                    </button>
                  }
                >
                  <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                    Systeem meldingen en belangrijke gebeurtenissen.
                  </p>
                  <ul className="lv-pr-alert-list lv-pr-mcp-alert-list">
                    {MCP_ALERTS.map((alert) => (
                      <li key={alert.id}>
                        <span className="time">{alert.time}</span>
                        <span className={`lv-pr-mcp-status is-${alert.tone}`}>
                          <StatusDot tone={alert.tone} />
                          {alert.label}
                        </span>
                        <span className={`lv-pr-mcp-alert-msg is-${alert.tone}`}>{alert.message}</span>
                      </li>
                    ))}
                  </ul>
                </Panel>
              </div>

              <Panel className="lv-pr-mcp-quick" title="Snelle Acties">
                <div className="lv-pr-mcp-quick-list">
                  {MCP_QUICK_ACTIONS.map((action) => (
                    <button
                      key={action.id}
                      type="button"
                      className="lv-pr-mcp-quick-btn"
                      onClick={() => toast(action.label)}
                    >
                      <span className="lv-pr-mcp-quick-icon">{QUICK_ICONS[action.id]}</span>
                      {action.label}
                    </button>
                  ))}
                </div>
              </Panel>
            </div>
          </aside>
        </section>
      </main>
    </AppShell>
  );
}
