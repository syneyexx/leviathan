/** FINALBETA MCP — live mcp_host wiring (visual shell preserved). */
"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { useHadesMcp } from "@/components/hades/features/mcp/hooks/useHadesMcp";
import type { McpExecution, McpServer, McpTool } from "@/lib/hades-api";
import { FbIcon } from "../icons";
import { MediaWelcome, McFooter } from "../media/media-chrome";
import { MCP_TABS, type McpTab } from "../mocks/pr-mcp";
import { FinalBetaShell } from "../shell/finalbeta-shell";
import type { FinalBetaNavigate } from "../types";

type Props = { onNavigate: FinalBetaNavigate };

type UiServer = {
  id: string;
  name: string;
  summary: string;
  online: boolean;
  statusLabel: string;
  transport: string;
  transportDetail: string;
  tools: number;
  auth: string;
  authTone: "ok" | "warn" | "none";
  lastActive: string;
  lastActiveFull: string;
  endpoint: string;
  scopes: string[];
  enabled: boolean;
  icon: string;
  lastError: string | null;
  raw: McpServer;
};

function errMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function isConnected(server: McpServer): boolean {
  const status = String(server.connection_status_effective || server.connection_status || "").toLowerCase();
  if (!status) return false;
  if (status.includes("disconnect") || status.includes("error") || status.includes("fail")) return false;
  return status.includes("connect") || status === "ready" || status === "online";
}

function formatWhen(value?: string | null): string {
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

function authLabel(server: McpServer): { auth: string; tone: "ok" | "warn" | "none" } {
  const method = String(server.auth_method || "none").toLowerCase();
  if (method === "none" || !method) return { auth: "Geen", tone: "none" };
  if (method === "bearer" || method === "api_key" || method.includes("key")) {
    return { auth: server.has_auth_secret ? "API key" : "API key", tone: server.has_auth_secret ? "ok" : "warn" };
  }
  if (method === "oauth") {
    const st = String(server.auth_status || "").toLowerCase();
    return { auth: "OAuth 2.0", tone: st.includes("ok") || st.includes("ready") || st.includes("authed") ? "ok" : "warn" };
  }
  return { auth: method, tone: server.has_auth_secret ? "ok" : "warn" };
}

function iconForServer(server: McpServer): string {
  const hay = `${server.name} ${server.catalog_id || ""} ${server.transport}`.toLowerCase();
  if (hay.includes("file") || hay.includes("fs")) return "folder";
  if (hay.includes("search") || hay.includes("brave") || hay.includes("web")) return "search";
  if (hay.includes("git") || hay.includes("code")) return "code";
  if (hay.includes("sql") || hay.includes("db") || hay.includes("postgres")) return "database";
  return server.transport === "stdio" ? "terminal" : "link";
}

function toUiServer(server: McpServer): UiServer {
  const online = isConnected(server) && server.session_live !== false;
  const { auth, tone } = authLabel(server);
  const transport = server.transport === "streamable_http" ? "HTTP" : server.transport || "—";
  const transportDetail =
    server.transport === "streamable_http"
      ? "HTTP (SSE / streamable)"
      : server.transport === "stdio"
        ? "stdio (lokaal)"
        : String(server.transport || "—");
  return {
    id: server.id,
    name: server.name,
    summary: server.description || (server.owner_plugin_id ? `Plugin: ${server.owner_plugin_id}` : transportDetail),
    online,
    statusLabel: online ? "Online" : server.enabled === false ? "Disabled" : "Offline",
    transport,
    transportDetail,
    tools: server.tool_count ?? 0,
    auth,
    authTone: tone,
    lastActive: formatWhen(server.last_check_at),
    lastActiveFull: formatWhen(server.last_check_at),
    endpoint: server.endpoint_url || server.command?.executable || "—",
    scopes: [],
    enabled: server.enabled !== false,
    icon: iconForServer(server),
    lastError: server.last_error || null,
    raw: server,
  };
}

function categoryTone(name: string): "green" | "blue" | "teal" | "gold" {
  const n = name.toLowerCase();
  if (n.includes("zoek") || n.includes("search") || n.includes("web")) return "green";
  if (n.includes("file") || n.includes("best") || n.includes("fs")) return "teal";
  if (n.includes("code") || n.includes("git")) return "blue";
  return "gold";
}

function toolCategory(tool: McpTool): string {
  const hay = `${tool.remote_name} ${tool.description || ""}`.toLowerCase();
  if (hay.includes("search") || hay.includes("zoek")) return "Zoeken";
  if (hay.includes("file") || hay.includes("dir") || hay.includes("path")) return "Bestanden";
  if (hay.includes("web") || hay.includes("http") || hay.includes("url")) return "Web";
  if (hay.includes("repo") || hay.includes("git") || hay.includes("code")) return "Code";
  return "Algemeen";
}

function iconForTool(tool: McpTool): string {
  const cat = toolCategory(tool).toLowerCase();
  if (cat.includes("zoek")) return "search";
  if (cat.includes("web")) return "globe";
  if (cat.includes("best")) return "folder";
  if (cat.includes("code")) return "code";
  return "wrench";
}

function defaultParamsFor(tool: McpTool | null): string {
  if (!tool?.input_schema || typeof tool.input_schema !== "object") return "{\n  \n}";
  const props = (tool.input_schema as { properties?: Record<string, unknown> }).properties;
  if (!props || typeof props !== "object") return "{\n  \n}";
  const sample: Record<string, unknown> = {};
  for (const [key, schema] of Object.entries(props).slice(0, 6)) {
    const t = String((schema as { type?: string })?.type || "string");
    if (t === "number" || t === "integer") sample[key] = 0;
    else if (t === "boolean") sample[key] = false;
    else if (t === "array") sample[key] = [];
    else if (t === "object") sample[key] = {};
    else sample[key] = "";
  }
  return JSON.stringify(sample, null, 2);
}

function AuthCell({ auth, tone }: { auth: string; tone: "ok" | "warn" | "none" }) {
  if (tone === "none") return <span className="mcp-auth none">{auth}</span>;
  if (tone === "ok") {
    return (
      <span className="mcp-auth ok">
        {auth}
        <FbIcon name="checkcircle" size={12} />
      </span>
    );
  }
  return (
    <span className="mcp-auth warn">
      {auth}
      <span className="mcp-auth-warn" aria-hidden="true">
        !
      </span>
    </span>
  );
}

export function McpPage({ onNavigate }: Props) {
  const [tab, setTab] = useState<McpTab>("Overzicht");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [toolQuery, setToolQuery] = useState("");
  const [serverFilter, setServerFilter] = useState("all");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [testServerId, setTestServerId] = useState<string | null>(null);
  const [testToolId, setTestToolId] = useState<string | null>(null);
  const [testParams, setTestParams] = useState("{\n  \n}");
  const [testResult, setTestResult] = useState<string>("Nog geen resultaat — voer een tool uit.");
  const [testOk, setTestOk] = useState<boolean | null>(null);
  const [testMs, setTestMs] = useState<number | null>(null);
  const [actionBusy, setActionBusy] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [createName, setCreateName] = useState("");
  const [createTransport, setCreateTransport] = useState<"stdio" | "streamable_http">("stdio");
  const [createEndpoint, setCreateEndpoint] = useState("");
  const [createCommand, setCreateCommand] = useState("");
  const [recentCalls, setRecentCalls] = useState<McpExecution[]>([]);

  const {
    servers: apiServers,
    tools: apiTools,
    networkPolicy,
    stats,
    loading,
    error,
    refresh,
    connect,
    disconnect,
    reconnect,
    enable,
    remove,
    create,
    refreshTools,
    invokeTool,
    loadExecutions,
  } = useHadesMcp({ selectedServerId: selectedId });

  const servers = useMemo(() => apiServers.map(toUiServer), [apiServers]);
  const serverById = useMemo(() => new Map(servers.map((s) => [s.id, s])), [servers]);

  const tools = useMemo(
    () =>
      apiTools.map((tool) => {
        const category = toolCategory(tool);
        return {
          id: tool.id,
          name: tool.remote_name || tool.model_name || tool.id,
          description: tool.description || "—",
          serverId: tool.server_id,
          server: tool.server_name || serverById.get(tool.server_id)?.name || tool.server_id,
          category,
          categoryTone: categoryTone(category),
          icon: iconForTool(tool),
          raw: tool,
        };
      }),
    [apiTools, serverById],
  );

  useEffect(() => {
    if (!selectedId && servers[0]) setSelectedId(servers[0].id);
    if (selectedId && servers.length && !servers.some((s) => s.id === selectedId)) {
      setSelectedId(servers[0]?.id ?? null);
    }
  }, [servers, selectedId]);

  useEffect(() => {
    if (!testServerId && servers[0]) setTestServerId(servers[0].id);
  }, [servers, testServerId]);

  useEffect(() => {
    const forServer = tools.filter((t) => t.serverId === testServerId);
    if (!testToolId && forServer[0]) {
      setTestToolId(forServer[0].id);
      setTestParams(defaultParamsFor(forServer[0].raw));
    } else if (testToolId && forServer.length && !forServer.some((t) => t.id === testToolId)) {
      setTestToolId(forServer[0]?.id ?? null);
      setTestParams(defaultParamsFor(forServer[0]?.raw ?? null));
    }
  }, [tools, testServerId, testToolId]);

  const reloadExecutions = useCallback(async () => {
    try {
      const items = await loadExecutions(undefined, 8);
      setRecentCalls(items);
    } catch {
      /* keep previous */
    }
  }, [loadExecutions]);

  useEffect(() => {
    void reloadExecutions();
  }, [reloadExecutions, apiServers.length, apiTools.length]);

  const selected = servers.find((s) => s.id === selectedId) ?? null;
  const testTool = tools.find((t) => t.id === testToolId) ?? null;
  const testServer = servers.find((s) => s.id === testServerId) ?? null;
  const testToolsForServer = tools.filter((tool) => tool.serverId === testServerId);

  const filteredTools = useMemo(() => {
    const q = toolQuery.trim().toLowerCase();
    return tools.filter((tool) => {
      if (serverFilter !== "all" && tool.serverId !== serverFilter) return false;
      if (categoryFilter !== "all" && tool.category !== categoryFilter) return false;
      if (!q) return true;
      return (
        tool.name.toLowerCase().includes(q) ||
        tool.description.toLowerCase().includes(q) ||
        tool.server.toLowerCase().includes(q)
      );
    });
  }, [tools, toolQuery, serverFilter, categoryFilter]);

  const categories = useMemo(() => Array.from(new Set(tools.map((t) => t.category))), [tools]);

  const liveKpis = useMemo(() => {
    const offline = Math.max(0, stats.serverCount - stats.connected);
    const pct = stats.serverCount ? Math.round((stats.connected / stats.serverCount) * 100) : 0;
    return [
      {
        id: "servers",
        label: "MCP servers",
        value: loading && !servers.length ? "…" : `${stats.connected} verbonden`,
        hint: stats.serverCount ? `${offline} offline · ${stats.enabled} enabled` : "geen servers",
        icon: "link",
        tone: "cyan" as const,
        valueTone: "cyan" as const,
      },
      {
        id: "tools",
        label: "Beschikbare tools",
        value: loading && !tools.length ? "…" : `${stats.toolCount} tools`,
        hint: stats.serverCount ? `uit ${stats.serverCount} servers` : "geen servers",
        icon: "wrench",
        tone: "green" as const,
        valueTone: "white" as const,
      },
      {
        id: "perms",
        label: "Netwerkbeleid",
        value: String(networkPolicy || "block"),
        hint: "settings.network_policy",
        icon: "shield",
        tone: "teal" as const,
        valueTone: "teal" as const,
      },
      {
        id: "health",
        label: "Systeemhealth",
        value: stats.serverCount ? `${stats.connected} / ${stats.serverCount} online` : "0 / 0 online",
        hint: stats.serverCount ? `${pct}% operationeel` : "nog geen MCP servers",
        icon: "line",
        tone: "green" as const,
        valueTone: "white" as const,
        trend: stats.connected < stats.serverCount ? ("down" as const) : undefined,
        hintTone: "green" as const,
      },
    ];
  }, [stats, networkPolicy, loading, servers.length, tools.length]);

  const statusRows = useMemo(
    () => [
      { id: "total", label: "Servers totaal", value: String(stats.serverCount), icon: "database", tone: "" },
      { id: "online", label: "Online", value: String(stats.connected), icon: "checkcircle", tone: "green" },
      {
        id: "offline",
        label: "Offline",
        value: String(Math.max(0, stats.serverCount - stats.connected)),
        icon: "stop",
        tone: "red",
      },
      { id: "tools", label: "Tools totaal", value: String(stats.toolCount), icon: "wrench", tone: "" },
      { id: "enabled", label: "Enabled", value: String(stats.enabled), icon: "checkcircle", tone: "" },
      {
        id: "policy",
        label: "network_policy",
        value: String(networkPolicy || "block"),
        icon: "shield",
        tone: networkPolicy === "allow" ? "green" : networkPolicy === "ask" ? "" : "red",
      },
    ],
    [stats, networkPolicy],
  );

  async function runAction(key: string, fn: () => Promise<unknown>, okMsg: string) {
    setActionBusy(key);
    try {
      await fn();
      toast.success(okMsg);
      await reloadExecutions();
    } catch (err) {
      toast.error(errMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  async function onCreateServer() {
    const name = createName.trim();
    if (!name) {
      toast.error("Geef een servernaam op.");
      return;
    }
    const body: Record<string, unknown> = {
      name,
      transport: createTransport,
      auth_method: "none",
      auto_connect: false,
      enabled: true,
    };
    if (createTransport === "stdio") {
      const exe = createCommand.trim();
      if (!exe) {
        toast.error("Geef een stdio executable op.");
        return;
      }
      body.command = { executable: exe, args: [], cwd: null };
    } else {
      const url = createEndpoint.trim();
      if (!url) {
        toast.error("Geef een endpoint URL op.");
        return;
      }
      body.endpoint_url = url;
    }
    await runAction(
      "create",
      async () => {
        const result = await create(body);
        setSelectedId(result.server.id);
        setShowCreate(false);
        setCreateName("");
        setCreateEndpoint("");
        setCreateCommand("");
      },
      `MCP server toegevoegd: ${name}`,
    );
  }

  async function onRunTool() {
    if (!testTool) {
      toast.error("Selecteer eerst een tool.");
      return;
    }
    let args: Record<string, unknown> = {};
    try {
      args = testParams.trim() ? (JSON.parse(testParams) as Record<string, unknown>) : {};
    } catch (err) {
      toast.error(`Parameters JSON ongeldig: ${errMessage(err)}`);
      return;
    }
    setActionBusy("invoke");
    const started = Date.now();
    try {
      const result = await invokeTool(testTool.id, args, true);
      const ms = Date.now() - started;
      setTestMs(ms);
      setTestOk(true);
      setTestResult(JSON.stringify(result, null, 2));
      toast.success(`Tool uitgevoerd: ${testTool.name}`);
      await reloadExecutions();
    } catch (err) {
      const ms = Date.now() - started;
      setTestMs(ms);
      setTestOk(false);
      setTestResult(JSON.stringify({ error: errMessage(err) }, null, 2));
      toast.error(errMessage(err));
    } finally {
      setActionBusy(null);
    }
  }

  const body = (
    <div className="mc-page pr-page mcp-page" data-page="mcp" data-live="mcp">
      <MediaWelcome
        title="MCP"
        subtitle="Verbind Model Context Protocol servers en breid HADES uit met externe tools en data."
        quote="More tools. Greater possibilities."
        right={
          <div className="pr-welcome-actions mcp-welcome-actions">
            <button
              className="btn btn-outline"
              type="button"
              disabled={!!actionBusy}
              onClick={() => setShowCreate((v) => !v)}
            >
              <FbIcon name="plus" size={13} />
              MCP server toevoegen
            </button>
            <button
              className="btn btn-gold"
              type="button"
              onClick={() => toast.message("MCP marktplaats discovery: gebruik catalogus of MCPMarket via Advanced MCP.")}
            >
              <FbIcon name="plus" size={13} />
              Verbinden met marktplaats
            </button>
          </div>
        }
      />

      {error ? (
        <div className="mc-panel" role="alert" style={{ marginBottom: 12, padding: 12 }}>
          <strong>MCP laden mislukt.</strong> {error.message}
        </div>
      ) : null}

      {showCreate ? (
        <section className="mc-panel" style={{ marginBottom: 12, padding: 16 }}>
          <h2 style={{ marginTop: 0 }}>Nieuwe MCP server</h2>
          <div className="mcp-test-fields">
            <label>
              <span>Naam</span>
              <input
                className="mcp-select"
                value={createName}
                onChange={(e) => setCreateName(e.target.value)}
                placeholder="bijv. filesystem"
              />
            </label>
            <label>
              <span>Transport</span>
              <select
                className="mcp-select"
                value={createTransport}
                onChange={(e) => setCreateTransport(e.target.value as "stdio" | "streamable_http")}
              >
                <option value="stdio">stdio</option>
                <option value="streamable_http">streamable_http</option>
              </select>
            </label>
            {createTransport === "stdio" ? (
              <label>
                <span>Executable</span>
                <input
                  className="mcp-select"
                  value={createCommand}
                  onChange={(e) => setCreateCommand(e.target.value)}
                  placeholder="pad of command"
                />
              </label>
            ) : (
              <label>
                <span>Endpoint URL</span>
                <input
                  className="mcp-select"
                  value={createEndpoint}
                  onChange={(e) => setCreateEndpoint(e.target.value)}
                  placeholder="https://…"
                />
              </label>
            )}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
            <button
              className="btn btn-gold"
              type="button"
              disabled={actionBusy === "create"}
              onClick={() => void onCreateServer()}
            >
              Aanmaken
            </button>
            <button className="btn btn-outline" type="button" onClick={() => setShowCreate(false)}>
              Annuleren
            </button>
          </div>
        </section>
      ) : null}

      <div className="tabs mcp-tabs" role="tablist" aria-label="MCP secties">
        {MCP_TABS.map((item) => (
          <button
            key={item}
            type="button"
            role="tab"
            className={`tab${tab === item ? " active" : ""}`}
            aria-selected={tab === item}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>

      <div className="mcp-kpi-row">
        {liveKpis.map((kpi) => (
          <article key={kpi.id} className={`mcp-kpi mcp-kpi-${kpi.id}`}>
            <span className={`mcp-kpi-ico ${kpi.tone}`}>
              <FbIcon name={kpi.icon} size={15} />
            </span>
            <div className="mcp-kpi-body">
              <div className="mcp-kpi-label">{kpi.label}</div>
              <div className={`mcp-kpi-value ${kpi.valueTone}`}>
                {"trend" in kpi && kpi.trend === "down" ? (
                  <span className="mcp-kpi-down" aria-hidden="true">
                    ▼
                  </span>
                ) : null}
                {kpi.value}
              </div>
              <div className={`mcp-kpi-hint${"hintTone" in kpi && kpi.hintTone ? ` ${kpi.hintTone}` : ""}`}>
                {kpi.hint}
              </div>
            </div>
            {kpi.id === "servers" ? <span className="mcp-kpi-deco" aria-hidden="true" /> : null}
          </article>
        ))}
      </div>

      <div className="mcp-mid">
        <section className="mc-panel mcp-servers-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="database" size={13} className="mcp-panel-ico" />
                MCP servers
              </h2>
              <p>Beheer je MCP server verbindingen, authenticatie en status.</p>
            </div>
            <button
              className="btn btn-sm btn-outline"
              type="button"
              disabled={!!actionBusy}
              onClick={() => void refresh().then(() => toast.success("MCP vernieuwd"))}
            >
              <FbIcon name="refresh" size={12} />
              Vernieuwen
            </button>
          </div>
          {loading && !servers.length ? (
            <p className="muted" style={{ padding: 16 }}>
              MCP servers laden…
            </p>
          ) : null}
          {!loading && servers.length === 0 ? (
            <p className="muted" style={{ padding: 16 }} data-empty="mcp-servers">
              Geen MCP servers geconfigureerd. Voeg een server toe of verbind via de marktplaats/catalogus.
            </p>
          ) : (
            <div className="mcp-table-wrap">
              <table className="mc-table mcp-servers-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Status</th>
                    <th>Transport</th>
                    <th>Tools</th>
                    <th>Authenticatie</th>
                    <th>Laatst actief</th>
                    <th>Acties</th>
                  </tr>
                </thead>
                <tbody>
                  {servers.map((server) => (
                    <tr
                      key={server.id}
                      className={server.id === selected?.id ? "active" : undefined}
                      onClick={() => setSelectedId(server.id)}
                    >
                      <td>
                        <span className="mcp-name-cell">
                          <span className="mcp-row-ico">
                            <FbIcon name={server.icon} size={13} />
                          </span>
                          <span>
                            <strong>{server.name}</strong>
                            <small>{server.summary}</small>
                          </span>
                        </span>
                      </td>
                      <td>
                        <span className={`mc-pill ${server.online ? "green" : "red"}`}>
                          <span className={`mc-dot ${server.online ? "green" : "red"}`} />
                          {server.statusLabel}
                        </span>
                      </td>
                      <td>{server.transport}</td>
                      <td>{server.tools}</td>
                      <td>
                        <AuthCell auth={server.auth} tone={server.authTone} />
                      </td>
                      <td>{server.lastActive}</td>
                      <td>
                        <div style={{ display: "flex", gap: 4 }} onClick={(e) => e.stopPropagation()}>
                          {server.online ? (
                            <button
                              type="button"
                              className="btn btn-sm btn-outline"
                              disabled={!!actionBusy}
                              onClick={() =>
                                void runAction(
                                  `disconnect:${server.id}`,
                                  () => disconnect(server.id),
                                  `${server.name} ontkoppeld`,
                                )
                              }
                            >
                              Disconnect
                            </button>
                          ) : (
                            <button
                              type="button"
                              className="btn btn-sm btn-outline"
                              disabled={!!actionBusy || !server.enabled}
                              onClick={() =>
                                void runAction(
                                  `connect:${server.id}`,
                                  () => connect(server.id),
                                  `${server.name} verbonden`,
                                )
                              }
                            >
                              Connect
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="mc-panel mcp-details-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="sliders" size={13} className="mcp-panel-ico" />
                Server details
              </h2>
            </div>
            {selected ? (
              <button
                className="btn btn-sm btn-outline"
                type="button"
                disabled={!!actionBusy}
                onClick={() =>
                  void runAction(
                    `enable:${selected.id}`,
                    () => enable(selected.id, !selected.enabled),
                    selected.enabled ? `${selected.name} uitgeschakeld` : `${selected.name} ingeschakeld`,
                  )
                }
              >
                {selected.enabled ? "Disable" : "Enable"}
              </button>
            ) : null}
          </div>

          {!selected ? (
            <p className="muted" style={{ padding: 16 }}>
              Selecteer een server of voeg er een toe.
            </p>
          ) : (
            <>
              <div className="mcp-detail-hero">
                <span className="mcp-detail-mark">
                  <FbIcon name={selected.icon} size={16} />
                </span>
                <div className="mcp-detail-hero-copy">
                  <div className="mcp-detail-hero-top">
                    <strong>{selected.name}</strong>
                    <span className={`mc-pill ${selected.online ? "green" : "red"}`}>
                      <FbIcon name={selected.online ? "checkcircle" : "stop"} size={11} />
                      {selected.statusLabel}
                    </span>
                  </div>
                  <small>{selected.summary}</small>
                </div>
              </div>

              <div className="mcp-detail-rows">
                <div className="mcp-detail-row">
                  <span className="k">Transport</span>
                  <span className="v">{selected.transportDetail}</span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Endpoint</span>
                  <span className="v mono">{selected.endpoint}</span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Authenticatie</span>
                  <span className="v mcp-detail-auth">
                    <AuthCell auth={selected.auth} tone={selected.authTone} />
                  </span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Tools</span>
                  <span className="v mcp-detail-auth">
                    <span>{selected.tools} tools beschikbaar</span>
                    <button
                      className="btn btn-sm btn-outline"
                      type="button"
                      disabled={!!actionBusy}
                      onClick={() =>
                        void runAction(
                          `refresh-tools:${selected.id}`,
                          () => refreshTools(selected.id),
                          `Tools vernieuwd: ${selected.name}`,
                        )
                      }
                    >
                      Tools vernieuwen
                    </button>
                  </span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Laatst actief</span>
                  <span className="v">{selected.lastActiveFull}</span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Status</span>
                  <span className="v mcp-detail-auth">
                    <span className={`mcp-auth ${selected.online ? "ok" : "warn"}`}>
                      <FbIcon name={selected.online ? "checkcircle" : "stop"} size={12} />
                      <em>{selected.online ? "Operationeel" : selected.lastError || "Niet verbonden"}</em>
                    </span>
                  </span>
                </div>
                <div className="mcp-detail-row">
                  <span className="k">Acties</span>
                  <span className="v mcp-detail-auth" style={{ flexWrap: "wrap", gap: 6 }}>
                    <button
                      className="btn btn-sm btn-outline"
                      type="button"
                      disabled={!!actionBusy || !selected.enabled}
                      onClick={() =>
                        void runAction(`connect:${selected.id}`, () => connect(selected.id), `${selected.name} verbonden`)
                      }
                    >
                      Connect
                    </button>
                    <button
                      className="btn btn-sm btn-outline"
                      type="button"
                      disabled={!!actionBusy}
                      onClick={() =>
                        void runAction(
                          `disconnect:${selected.id}`,
                          () => disconnect(selected.id),
                          `${selected.name} ontkoppeld`,
                        )
                      }
                    >
                      Disconnect
                    </button>
                    <button
                      className="btn btn-sm btn-outline"
                      type="button"
                      disabled={!!actionBusy || !selected.enabled}
                      onClick={() =>
                        void runAction(
                          `reconnect:${selected.id}`,
                          () => reconnect(selected.id),
                          `${selected.name} herverbonden`,
                        )
                      }
                    >
                      Reconnect
                    </button>
                    <button
                      className="btn btn-sm btn-outline"
                      type="button"
                      disabled={!!actionBusy || selected.raw.owner_kind === "plugin"}
                      onClick={() =>
                        void runAction(
                          `delete:${selected.id}`,
                          async () => {
                            await remove(selected.id);
                            setSelectedId(null);
                          },
                          `${selected.name} verwijderd`,
                        )
                      }
                    >
                      Verwijderen
                    </button>
                  </span>
                </div>
              </div>
            </>
          )}
        </section>
      </div>

      <div className="mcp-bottom">
        <section className="mc-panel mcp-tools-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="wrench" size={13} className="mcp-panel-ico" />
                Beschikbare tools
              </h2>
            </div>
          </div>
          <div className="mcp-tools-toolbar">
            <label className="mcp-search">
              <FbIcon name="search" size={13} />
              <input
                type="search"
                placeholder="Zoek tools..."
                value={toolQuery}
                onChange={(event) => setToolQuery(event.target.value)}
              />
            </label>
            <select
              className="mcp-select"
              value={serverFilter}
              onChange={(event) => setServerFilter(event.target.value)}
              aria-label="Filter servers"
            >
              <option value="all">Alle servers</option>
              {servers.map((server) => (
                <option key={server.id} value={server.id}>
                  {server.name}
                </option>
              ))}
            </select>
            <select
              className="mcp-select"
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              aria-label="Filter categorieën"
            >
              <option value="all">Alle categorieën</option>
              {categories.map((category) => (
                <option key={category} value={category}>
                  {category}
                </option>
              ))}
            </select>
            <button
              className="btn btn-sm btn-outline mcp-refresh"
              type="button"
              disabled={!!actionBusy || !selected}
              onClick={() => {
                if (!selected) return;
                void runAction(
                  `refresh-tools:${selected.id}`,
                  () => refreshTools(selected.id),
                  `Tools vernieuwd: ${selected.name}`,
                );
              }}
            >
              <FbIcon name="refresh" size={12} />
              Vernieuwen
            </button>
          </div>
          {!tools.length ? (
            <p className="muted" style={{ padding: 16 }}>
              Geen tools ontdekt. Verbind een server en vernieuw tools.
            </p>
          ) : (
            <div className="mcp-table-wrap">
              <table className="mc-table mcp-tools-table">
                <thead>
                  <tr>
                    <th>Naam</th>
                    <th>Beschrijving</th>
                    <th>Server</th>
                    <th>Categorie</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {filteredTools.map((tool) => (
                    <tr key={tool.id}>
                      <td>
                        <span className="mcp-name-cell compact">
                          <span className="mcp-row-ico sm">
                            <FbIcon name={tool.icon} size={12} />
                          </span>
                          <strong>{tool.name}</strong>
                        </span>
                      </td>
                      <td>{tool.description}</td>
                      <td>{tool.server}</td>
                      <td>
                        <span className={`mc-pill ${tool.categoryTone}`}>{tool.category}</span>
                      </td>
                      <td>
                        <button
                          className="btn btn-sm btn-outline"
                          type="button"
                          onClick={() => {
                            setTestServerId(tool.serverId);
                            setTestToolId(tool.id);
                            setTestParams(defaultParamsFor(tool.raw));
                            setTab("Testen");
                          }}
                        >
                          Testen
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>

        <section className="mc-panel mcp-test-panel">
          <div className="mc-panel-head">
            <div>
              <h2>
                <FbIcon name="code" size={13} className="mcp-panel-ico" />
                Tool testen
              </h2>
              <p>Voer een tool direct uit en bekijk de response.</p>
            </div>
          </div>

          <div className="mcp-test-fields">
            <label>
              <span>Server</span>
              <select
                className="mcp-select"
                value={testServerId ?? ""}
                onChange={(event) => {
                  const next = event.target.value;
                  setTestServerId(next || null);
                  const first = tools.find((tool) => tool.serverId === next);
                  if (first) {
                    setTestToolId(first.id);
                    setTestParams(defaultParamsFor(first.raw));
                  } else {
                    setTestToolId(null);
                  }
                }}
                disabled={!servers.length}
              >
                {!servers.length ? <option value="">Geen servers</option> : null}
                {servers.map((server) => (
                  <option key={server.id} value={server.id}>
                    {server.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span>Tool</span>
              <select
                className="mcp-select"
                value={testToolId ?? ""}
                onChange={(event) => {
                  const id = event.target.value;
                  setTestToolId(id || null);
                  const tool = tools.find((t) => t.id === id);
                  setTestParams(defaultParamsFor(tool?.raw ?? null));
                }}
                disabled={!testToolsForServer.length}
              >
                {!testToolsForServer.length ? <option value="">Geen tools</option> : null}
                {testToolsForServer.map((tool) => (
                  <option key={tool.id} value={tool.id}>
                    {tool.name}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="mcp-test-desc">
            {testTool && testServer && testTool.serverId === testServer.id
              ? testTool.description
              : "Selecteer een tool"}
          </p>

          <div className="mcp-json-block">
            <div className="mcp-json-head">
              <span>Parameters (JSON)</span>
              <button
                className="mcp-voorbeeld"
                type="button"
                onClick={() => setTestParams(defaultParamsFor(testTool?.raw ?? null))}
              >
                Voorbeeld
                <FbIcon name="chevron" size={11} />
              </button>
            </div>
            <textarea
              className="mcp-json"
              style={{ width: "100%", minHeight: 120, fontFamily: "inherit" }}
              value={testParams}
              onChange={(e) => setTestParams(e.target.value)}
              spellCheck={false}
            />
          </div>

          <button
            className="btn btn-gold mcp-run-btn"
            type="button"
            disabled={!!actionBusy || !testTool}
            onClick={() => void onRunTool()}
          >
            <FbIcon name="play" size={14} />
            Tool uitvoeren
          </button>

          <div className="mcp-result-head">
            <span className={testOk === false ? "mcp-result-ok" : "mcp-result-ok"} style={testOk === false ? { color: "#e85b5b" } : undefined}>
              <FbIcon name={testOk === false ? "stop" : "checkcircle"} size={13} />
              {testOk == null
                ? "Nog niet uitgevoerd"
                : testOk
                  ? `Succes${testMs != null ? ` (${(testMs / 1000).toFixed(1)}s)` : ""}`
                  : `Mislukt${testMs != null ? ` (${(testMs / 1000).toFixed(1)}s)` : ""}`}
            </span>
            <button
              className="btn btn-sm btn-outline"
              type="button"
              onClick={() => {
                void navigator.clipboard?.writeText(testResult).then(
                  () => toast.success("Resultaat gekopieerd"),
                  () => toast.error("Kopiëren mislukt"),
                );
              }}
            >
              <FbIcon name="copy" size={12} />
              Kopieer
            </button>
          </div>
          <div className="mcp-json-block result">
            <div className="mcp-json-head">
              <span>Resultaat</span>
            </div>
            <pre className="mcp-json">{testResult}</pre>
          </div>
        </section>
      </div>
    </div>
  );

  const inspector = (
    <>
      <p className="mc-insp-quote">
        “More tools.
        <br />
        Greater possibilities.”
      </p>

      <section className="mc-insp-section">
        <div className="mcp-insp-card">
          <div className="mcp-insp-card-head">
            <h3 className="mc-insp-title">MCP STATUS</h3>
            <span className="mcp-live-pill">
              <span className={`mc-dot ${stats.connected > 0 ? "green" : "red"}`} />
              {loading ? "…" : "LIVE"}
            </span>
          </div>
          <div className="mcp-status-list">
            {statusRows.map((row) => (
              <div className="mcp-status-row" key={row.id}>
                <span className={`mcp-status-ico ${row.tone}`}>
                  <FbIcon name={row.icon} size={12} />
                </span>
                <span className="k">{row.label}</span>
                <span className={`v${row.tone ? ` ${row.tone}` : ""}`}>{row.value}</span>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <div className="mcp-insp-card">
          <div className="mcp-insp-card-head">
            <h3 className="mc-insp-title">RECENTE CALLS</h3>
            <button className="btn btn-sm btn-outline" type="button" onClick={() => void reloadExecutions()}>
              Vernieuwen
            </button>
          </div>
          <div className="mcp-calls-list">
            {!recentCalls.length ? (
              <p className="muted" style={{ padding: 8 }}>
                Nog geen uitvoeringen.
              </p>
            ) : (
              recentCalls.map((call) => {
                const ok = String(call.status || "").toLowerCase().includes("success") || call.status === "ok";
                const toolName = tools.find((t) => t.id === call.tool_id)?.name || call.tool_id;
                const serverName = serverById.get(call.server_id)?.name || call.server_id;
                const dur =
                  call.duration_ms != null ? `${(call.duration_ms / 1000).toFixed(1)}s` : "—";
                return (
                  <div className="mcp-call-row" key={call.id}>
                    <span className={`mcp-call-ico ${ok ? "ok" : "err"}`}>
                      <FbIcon name={ok ? "checkcircle" : "stop"} size={12} />
                    </span>
                    <div className="mcp-call-copy">
                      <strong>{toolName}</strong>
                      <small>{serverName}</small>
                    </div>
                    <span className={`mcp-call-dur${ok ? "" : " err"}`}>{dur}</span>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </section>

      <section className="mc-insp-section">
        <h3 className="mc-insp-title">SNELLE ACTIES</h3>
        <div className="mcp-action-list">
          <button
            type="button"
            className="mcp-action-btn"
            disabled={!!actionBusy || !selected}
            onClick={() => {
              if (!selected) return;
              void runAction(`reconnect:${selected.id}`, () => reconnect(selected.id), "Verbinding getest/hernomen");
            }}
          >
            <FbIcon name="line" size={13} />
            <span>Test verbindingen</span>
          </button>
          <button type="button" className="mcp-action-btn" onClick={() => setShowCreate(true)}>
            <FbIcon name="plus" size={13} />
            <span>Nieuwe MCP server</span>
          </button>
          <button
            type="button"
            className="mcp-action-btn"
            disabled={!!actionBusy || !selected}
            onClick={() => {
              if (!selected) return;
              void runAction(
                `refresh-tools:${selected.id}`,
                () => refreshTools(selected.id),
                `Tools vernieuwd: ${selected.name}`,
              );
            }}
          >
            <FbIcon name="refresh" size={13} />
            <span>Tools vernieuwen</span>
          </button>
          <button
            type="button"
            className="mcp-action-btn"
            onClick={() => void refresh().then(() => toast.success("MCP status vernieuwd"))}
          >
            <FbIcon name="list" size={13} />
            <span>Status vernieuwen</span>
          </button>
        </div>
      </section>

      <section className="mc-insp-section">
        <div className="mcp-insp-card">
          <div className="mcp-insp-card-head">
            <h3 className="mc-insp-title">PERMISSIES</h3>
          </div>
          <div className="mcp-perm-list">
            <div className="mcp-perm-row">
              <span className="k">network_policy</span>
              <span className={`v${networkPolicy === "block" ? " red" : networkPolicy === "allow" ? " green" : ""}`}>
                {networkPolicy === "allow" ? <FbIcon name="checkcircle" size={11} /> : null}
                {String(networkPolicy || "block")}
              </span>
            </div>
            <div className="mcp-perm-row">
              <span className="k">Servers enabled</span>
              <span className="v">{stats.enabled}</span>
            </div>
            <div className="mcp-perm-row">
              <span className="k">Verbonden</span>
              <span className="v green">{stats.connected}</span>
            </div>
          </div>
        </div>
      </section>
    </>
  );

  return (
    <FinalBetaShell
      page="mcp"
      appClassName="mc-app pr-app"
      mainClassName="mc-main"
      body={body}
      inspector={inspector}
      footer={<McFooter />}
      onNavigate={onNavigate}
    />
  );
}
