"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Cable, Plus, RefreshCw, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { EmptyLine, PageHeader, Panel, StatCard, StatusBadge, type StatusTone } from "@/components/hades/ui";
import {
  AppSettings,
  HadesApiError,
  McpCatalogItem,
  McpExecution,
  McpMarketCandidate,
  McpServer,
  McpTool,
  hadesApi,
} from "@/lib/hades-api";

type Lang = "nl" | "en";

const copy = {
  nl: {
    title: "MCP",
    subtitle: "Beheer lokale stdio- en externe Streamable HTTP MCP-servers. Groen = geverifieerd (legacy handshake of 2026 discover/ready).",
    connections: "Verbindingen",
    catalog: "Catalogus",
    marketplace: "MCPMarket",
    marketplaceHint: "Externe ontdekking. Untrusted. Geen auto-install. HADES blijft autoriteit.",
    marketplaceSearch: "Zoek externe capability",
    marketplaceEmpty: "Geen MCPMarket-kandidaten (of marketplace onbeschikbaar).",
    marketplaceTrust: "untrusted",
    prepareDraft: "Voorbereiden (geen connect)",
    tools: "Tools",
    add: "Server toevoegen",
    refresh: "Vernieuwen",
    connect: "Verbinden",
    disconnect: "Verbreken",
    reconnect: "Opnieuw verbinden",
    refreshTools: "Tools vernieuwen",
    edit: "Bewerken",
    duplicate: "Dupliceren",
    remove: "Verwijderen",
    enable: "Ingeschakeld",
    pluginOwned: "Beheerd door plugin",
    noServers: "Nog geen MCP-servers geconfigureerd.",
    confirmDelete: "Deze MCP-server verwijderen? Geheimen worden gewist; plugin-eigenaren moeten via Plugins.",
    invoke: "Uitvoeren",
    cancel: "Annuleren",
    allowed: "Toegestaan",
    chatbot: "Chatbot",
    approval: "Goedkeuring vereist",
    rawJson: "Ruwe JSON",
    result: "Resultaat",
    schemaIssue: "Schema-beperking",
  },
  en: {
    title: "MCP",
    subtitle: "Manage local stdio and remote Streamable HTTP MCP servers. Green means verified (legacy handshake or 2026 discover/ready).",
    connections: "Connections",
    catalog: "Catalog",
    marketplace: "MCPMarket",
    marketplaceHint: "External discovery. Untrusted. No auto-install. HADES stays authoritative.",
    marketplaceSearch: "Search external capability",
    marketplaceEmpty: "No MCPMarket candidates (or marketplace unavailable).",
    marketplaceTrust: "untrusted",
    prepareDraft: "Prepare draft (no connect)",
    tools: "Tools",
    add: "Add server",
    refresh: "Refresh",
    connect: "Connect",
    disconnect: "Disconnect",
    reconnect: "Reconnect",
    refreshTools: "Refresh tools",
    edit: "Edit",
    duplicate: "Duplicate",
    remove: "Delete",
    enable: "Enabled",
    pluginOwned: "Owned by plugin",
    noServers: "No MCP servers configured yet.",
    confirmDelete: "Delete this MCP server? Secrets are cleared; plugin-owned servers must be removed via Plugins.",
    invoke: "Run",
    cancel: "Cancel",
    allowed: "Allowed",
    chatbot: "Chatbot",
    approval: "Approval required",
    rawJson: "Raw JSON",
    result: "Result",
    schemaIssue: "Schema limitation",
  },
} as const;

function statusTone(status: string | undefined): StatusTone {
  switch (status) {
    case "connected":
    case "ready":
      return "success";
    case "connecting":
      return "info";
    case "auth_required":
    case "policy_blocked":
    case "disabled":
      return "warning";
    case "error":
      return "danger";
    default:
      return "neutral";
  }
}

function statusLabel(status: string | undefined, lang: Lang): string {
  const map: Record<string, { nl: string; en: string }> = {
    configured: { nl: "Geconfigureerd", en: "Configured" },
    disconnected: { nl: "Niet verbonden", en: "Disconnected" },
    connecting: { nl: "Bezig met verbinden", en: "Connecting" },
    connected: { nl: "Verbonden (sessie)", en: "Connected (session)" },
    ready: { nl: "Gereed (stateless)", en: "Ready (stateless)" },
    auth_required: { nl: "Authenticatie nodig", en: "Authentication required" },
    policy_blocked: { nl: "Geblokkeerd door beleid", en: "Blocked by policy" },
    error: { nl: "Fout", en: "Error" },
    disabled: { nl: "Uitgeschakeld", en: "Disabled" },
  };
  const hit = map[status || ""] || { nl: status || "onbekend", en: status || "unknown" };
  return hit[lang];
}

const emptyForm = {
  name: "",
  description: "",
  transport: "stdio" as "stdio" | "streamable_http",
  catalog_id: "custom",
  executable: "",
  argsText: "",
  cwd: "",
  envPlainText: "",
  envSecretsText: "",
  endpoint_url: "",
  auth_method: "none",
  bearer_token: "",
  headersText: "",
  timeout_seconds: "60",
  auto_connect: false,
};

export function McpPage() {
  const [lang, setLang] = useState<Lang>("nl");
  const t = copy[lang];
  const [servers, setServers] = useState<McpServer[]>([]);
  const [catalog, setCatalog] = useState<McpCatalogItem[]>([]);
  const [tools, setTools] = useState<McpTool[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedToolId, setSelectedToolId] = useState<string | null>(null);
  const [toolQuery, setToolQuery] = useState("");
  const [filterAllowed, setFilterAllowed] = useState<"all" | "yes" | "no">("all");
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [invokeArgs, setInvokeArgs] = useState("{}");
  const [invokeResult, setInvokeResult] = useState<Record<string, unknown> | null>(null);
  const [executions, setExecutions] = useState<McpExecution[]>([]);
  const [secretStorage, setSecretStorage] = useState<Record<string, unknown> | null>(null);
  const [marketQuery, setMarketQuery] = useState("");
  const [marketKind, setMarketKind] = useState<"mcp_server" | "skill">("mcp_server");
  const [marketStatus, setMarketStatus] = useState<string>("unknown");
  const [marketCandidates, setMarketCandidates] = useState<McpMarketCandidate[]>([]);
  const [marketNote, setMarketNote] = useState("");

  const selected = useMemo(() => servers.find((s) => s.id === selectedId) || null, [servers, selectedId]);
  const selectedTool = useMemo(() => tools.find((t) => t.id === selectedToolId) || null, [tools, selectedToolId]);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const [settings, serverRes, catalogRes, toolRes] = await Promise.all([
        hadesApi.settings().catch(() => ({ values: { language: "nl" } as AppSettings })),
        hadesApi.mcpServers(),
        hadesApi.mcpHostCatalog(),
        hadesApi.mcpTools(),
      ]);
      const language = (settings.values?.language === "en" ? "en" : "nl") as Lang;
      setLang(language);
      setServers(serverRes.items || []);
      setCatalog(catalogRes.items || []);
      setSecretStorage(catalogRes.secret_storage || null);
      setTools(toolRes.items || []);
      if (!selectedId && serverRes.items?.[0]) setSelectedId(serverRes.items[0].id);
      void hadesApi.mcpmarketStatus().then((row) => setMarketStatus(String(row.state || "unknown"))).catch(() => setMarketStatus("unavailable"));
    } catch (error) {
      toast.error(error instanceof HadesApiError ? error.message : String(error));
    } finally {
      setLoading(false);
    }
  }, [selectedId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    // OAuth browser callback lands on the FastAPI loopback endpoint, which then
    // redirects to /#/mcp?oauth=done|error — never put code/state in a fragment redirect_uri.
    if (typeof window === "undefined") return;
    const hash = window.location.hash || "";
    const qIndex = hash.indexOf("?");
    if (qIndex < 0) return;
    const params = new URLSearchParams(hash.slice(qIndex + 1));
    const oauthStatus = params.get("oauth");
    if (!oauthStatus) return;
    if (oauthStatus === "done") {
      toast.success(lang === "nl" ? "OAuth voltooid — verbind de server" : "OAuth complete — connect the server");
      void refresh();
    } else if (oauthStatus === "error") {
      toast.error(params.get("message") || (lang === "nl" ? "OAuth mislukt" : "OAuth failed"));
    }
    const clean = `${window.location.origin}${window.location.pathname}#/mcp`;
    window.history.replaceState({}, "", clean);
  }, [lang, refresh]);

  useEffect(() => {
    if (!selectedId) return;
    void hadesApi.mcpExecutions(selectedId, 20).then((res) => setExecutions(res.items || [])).catch(() => undefined);
  }, [selectedId, invokeResult]);

  const openCreate = (catalogItem?: McpCatalogItem) => {
    setEditingId(null);
    const next = { ...emptyForm };
    if (catalogItem) {
      next.catalog_id = catalogItem.id;
      next.name = catalogItem.name;
      next.description = catalogItem.description || "";
      if (catalogItem.transport === "streamable_http" || catalogItem.endpoint_url) {
        next.transport = "streamable_http";
        next.endpoint_url = catalogItem.endpoint_url || "";
        next.auth_method = catalogItem.auth_methods?.[0] === "none" ? "none" : "bearer";
      } else if (catalogItem.command_template) {
        next.transport = "stdio";
        next.executable = catalogItem.command_template.executable;
        next.argsText = (catalogItem.command_template.args || []).join("\n");
      }
      if (catalogItem.owned_by_plugin) {
        toast.message(lang === "nl" ? "Deze server hoort bij een plugin — open Plugins of verbind via de catalogusregel." : "This server is plugin-owned — use Plugins or connect from the catalog row.");
      }
    }
    setForm(next);
    setEditorOpen(true);
  };

  const openEdit = (server: McpServer) => {
    setEditingId(server.id);
    setForm({
      name: server.name,
      description: server.description || "",
      transport: (server.transport === "streamable_http" ? "streamable_http" : "stdio"),
      catalog_id: server.catalog_id || "custom",
      executable: server.command?.executable || "",
      argsText: (server.command?.args || []).join("\n"),
      cwd: server.command?.cwd || "",
      envPlainText: Object.entries(server.env?.plain || {}).map(([k, v]) => `${k}=${v}`).join("\n"),
      envSecretsText: (server.env?.secret_keys || []).map((k) => `${k}=`).join("\n"),
      endpoint_url: server.endpoint_url || "",
      auth_method: server.auth_method || "none",
      bearer_token: "",
      headersText: Object.entries(server.headers || {}).map(([k, v]) => `${k}: ${v}`).join("\n"),
      timeout_seconds: String(server.timeout_seconds || 60),
      auto_connect: Boolean(server.auto_connect),
    });
    setEditorOpen(true);
  };

  const parseEnvLines = (text: string) => {
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const idx = trimmed.indexOf("=");
      if (idx <= 0) continue;
      out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1);
    }
    return out;
  };

  const parseHeaders = (text: string) => {
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const idx = trimmed.indexOf(":");
      if (idx <= 0) continue;
      out[trimmed.slice(0, idx).trim()] = trimmed.slice(idx + 1).trim();
    }
    return out;
  };

  const saveServer = async () => {
    setBusy("save");
    try {
      const body: Record<string, unknown> = {
        name: form.name,
        description: form.description,
        transport: form.transport,
        catalog_id: form.catalog_id,
        timeout_seconds: Number(form.timeout_seconds) || 60,
        auto_connect: form.auto_connect,
        auth_method: form.auth_method,
      };
      if (form.transport === "stdio") {
        body.command = {
          executable: form.executable,
          args: form.argsText.split("\n").map((x) => x.trim()).filter(Boolean),
          cwd: form.cwd || null,
        };
        body.env = {
          plain: parseEnvLines(form.envPlainText),
          secrets: parseEnvLines(form.envSecretsText),
          keep_secrets: Object.keys(parseEnvLines(form.envSecretsText)),
        };
      } else {
        body.endpoint_url = form.endpoint_url;
        body.headers = parseHeaders(form.headersText);
        if (form.bearer_token) body.bearer_token = form.bearer_token;
      }
      const result = editingId
        ? await hadesApi.mcpUpdateServer(editingId, body)
        : await hadesApi.mcpCreateServer(body);
      toast.success(editingId ? (lang === "nl" ? "Server bijgewerkt" : "Server updated") : (lang === "nl" ? "Server toegevoegd" : "Server added"));
      setEditorOpen(false);
      setSelectedId(result.server.id);
      await refresh();
    } catch (error) {
      toast.error(error instanceof HadesApiError ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const runAction = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await fn();
      await refresh();
    } catch (error) {
      toast.error(error instanceof HadesApiError ? error.message : String(error));
    } finally {
      setBusy(null);
    }
  };

  const filteredTools = useMemo(() => {
    return tools.filter((tool) => {
      if (selectedId && tool.server_id !== selectedId && filterAllowed === "all" && !toolQuery) {
        // When a server is selected, default tools tab to that server unless searching globally
      }
      if (selectedId && !toolQuery && tool.server_id !== selectedId) return false;
      if (filterAllowed === "yes" && !tool.allowed) return false;
      if (filterAllowed === "no" && tool.allowed) return false;
      if (toolQuery) {
        const hay = `${tool.remote_name} ${tool.description || ""} ${tool.server_name || ""}`.toLowerCase();
        if (!hay.includes(toolQuery.toLowerCase())) return false;
      }
      return true;
    });
  }, [tools, selectedId, filterAllowed, toolQuery]);

  const connectedCount = servers.filter((s) => {
    const status = s.connection_status_effective || s.connection_status;
    return (status === "connected" || status === "ready") && s.session_live !== false;
  }).length;

  return (
    <div className="page-stack">
      <PageHeader
        title={t.title}
        description={t.subtitle}
        actions={
          <>
            <Button variant="outline" onClick={() => void refresh()} disabled={loading}>
              <RefreshCw className="size-4" /> {t.refresh}
            </Button>
            <Button onClick={() => openCreate()}>
              <Plus className="size-4" /> {t.add}
            </Button>
          </>
        }
      />

      <div className="stat-grid four">
        <StatCard label={lang === "nl" ? "Servers" : "Servers"} value={String(servers.length)} note="" />
        <StatCard label={lang === "nl" ? "Verbonden" : "Connected"} value={String(connectedCount)} note="" />
        <StatCard label={lang === "nl" ? "Tools" : "Tools"} value={String(tools.length)} note="" />
        <StatCard
          label={lang === "nl" ? "Secret-opslag" : "Secret storage"}
          value={secretStorage?.ok ? "OK" : (lang === "nl" ? "Ontbreekt" : "Missing")}
          note=""
        />
      </div>

      <Tabs defaultValue="connections">
        <TabsList>
          <TabsTrigger value="connections">{t.connections}</TabsTrigger>
          <TabsTrigger value="catalog">{t.catalog}</TabsTrigger>
          <TabsTrigger value="tools">{t.tools}</TabsTrigger>
        </TabsList>

        <TabsContent value="connections" className="plugin-layout">
          <Panel title={t.connections}>
            {servers.length === 0 ? <EmptyLine>{t.noServers}</EmptyLine> : null}
            <div className="list-stack">
              {servers.map((server) => {
                const status = server.connection_status_effective || server.connection_status;
                const greenOk = status === "connected" && (server.owner_kind === "plugin" || server.session_live);
                return (
                  <button
                    key={server.id}
                    type="button"
                    className={`list-row ${selectedId === server.id ? "active" : ""}`}
                    onClick={() => setSelectedId(server.id)}
                  >
                    <div>
                      <strong>{server.name}</strong>
                      <p>{server.description || server.transport}</p>
                    </div>
                    <StatusBadge tone={greenOk ? "success" : statusTone(status)}>
                      {statusLabel(status, lang)}
                    </StatusBadge>
                  </button>
                );
              })}
            </div>
          </Panel>

          <div className="details-stack">
            {selected ? (
              <Panel
                title={selected.name}
                actions={
                  <div className="inline-actions">
                    <label className="inline-switch">
                      <span>{t.enable}</span>
                      <Switch
                        checked={selected.enabled}
                        onCheckedChange={(value) => void runAction("enable", () => hadesApi.mcpEnableServer(selected.id, value))}
                      />
                    </label>
                  </div>
                }
              >
                <div className="form-grid two">
                  <div><span className="muted">{lang === "nl" ? "Transport" : "Transport"}</span><div>{selected.transport === "stdio" ? (lang === "nl" ? "Lokaal (stdio)" : "Local (stdio)") : "Streamable HTTP"}</div></div>
                  <div><span className="muted">{lang === "nl" ? "Auth" : "Auth"}</span><div>{selected.auth_method} / {selected.auth_status}</div></div>
                  <div><span className="muted">{lang === "nl" ? "Tools" : "Tools"}</span><div>{selected.allowed_tool_count ?? 0}/{selected.tool_count ?? 0} {lang === "nl" ? "toegestaan" : "allowed"}</div></div>
                  <div><span className="muted">{lang === "nl" ? "Laatste controle" : "Last check"}</span><div>{selected.last_check_at || "—"}</div></div>
                </div>
                {selected.owner_kind === "plugin" ? (
                  <p className="muted" style={{ marginTop: 8 }}>{t.pluginOwned}: {selected.owner_plugin_id}</p>
                ) : null}
                {selected.last_error ? (
                  <p className="error-text" style={{ marginTop: 8 }}>
                    [{selected.last_error_kind || "error"}] {selected.last_error}
                  </p>
                ) : null}
                <div className="inline-actions" style={{ marginTop: 12, flexWrap: "wrap", gap: 8 }}>
                  <Button size="sm" disabled={!!busy} onClick={() => void runAction("connect", () => hadesApi.mcpConnectServer(selected.id))}>
                    <Cable className="size-4" /> {t.connect}
                  </Button>
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void runAction("disconnect", () => hadesApi.mcpDisconnectServer(selected.id))}>{t.disconnect}</Button>
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void runAction("reconnect", () => hadesApi.mcpReconnectServer(selected.id))}>{t.reconnect}</Button>
                  <Button size="sm" variant="outline" disabled={!!busy} onClick={() => void runAction("refresh", () => hadesApi.mcpRefreshTools(selected.id))}>{t.refreshTools}</Button>
                  <Button size="sm" variant="outline" disabled={selected.owner_kind === "plugin"} onClick={() => openEdit(selected)}>{t.edit}</Button>
                  <Button size="sm" variant="outline" disabled={selected.owner_kind === "plugin"} onClick={() => void runAction("dup", async () => { const r = await hadesApi.mcpDuplicateServer(selected.id); setSelectedId(r.server.id); })}>{t.duplicate}</Button>
                  <Button size="sm" variant="destructive" disabled={selected.owner_kind === "plugin"} onClick={() => setDeleteId(selected.id)}><Trash2 className="size-4" /> {t.remove}</Button>
                </div>
                {selected.auth_method === "oauth" ? (
                  <div style={{ marginTop: 12 }}>
                    <Button
                      size="sm"
                      variant="secondary"
                      onClick={() => void runAction("oauth", async () => {
                        const redirect = hadesApi.mcpOAuthCallbackUrl();
                        const uiReturn = `${window.location.origin}${window.location.pathname}#/mcp`;
                        const start = await hadesApi.mcpOAuthStart(selected.id, {
                          redirect_uri: redirect,
                          ui_return_url: uiReturn,
                        });
                        if (start.authorization_url) {
                          window.open(String(start.authorization_url), "_blank", "noopener,noreferrer");
                          toast.message(lang === "nl" ? "Voltooi OAuth in de browser — callback is automatisch." : "Complete OAuth in the browser — callback is automatic.");
                        } else {
                          toast.error(String(start.error || "OAuth niet beschikbaar"));
                        }
                      })}
                    >
                      OAuth
                    </Button>
                  </div>
                ) : null}
              </Panel>
            ) : (
              <Panel title={lang === "nl" ? "Details" : "Details"}><EmptyLine>{lang === "nl" ? "Selecteer een server" : "Select a server"}</EmptyLine></Panel>
            )}
          </div>
        </TabsContent>

        <TabsContent value="catalog">
          <Panel title={t.catalog}>
            <div className="list-stack">
              {catalog.map((item) => (
                <div key={item.id} className="list-row static">
                  <div>
                    <strong>{item.name}</strong>
                    <p>{item.description}</p>
                    <p className="muted">{item.auth_hint}</p>
                    {item.oauth_note ? <p className="muted">{item.oauth_note}</p> : null}
                  </div>
                  <div className="inline-actions">
                    <StatusBadge tone={item.status === "connected" ? "success" : item.status === "blocked_or_incomplete" ? "warning" : "neutral"}>
                      {item.status || "available"}
                    </StatusBadge>
                    {item.owned_by_plugin ? (
                      <Button size="sm" variant="outline" onClick={() => {
                        const match = servers.find((s) => s.owner_plugin_id === item.plugin_id);
                        if (match) {
                          setSelectedId(match.id);
                          void runAction("connect", () => hadesApi.mcpConnectServer(match.id));
                        } else {
                          toast.message(lang === "nl" ? "Installeer/activeer eerst de plugin." : "Install/enable the plugin first.");
                        }
                      }}>{t.connect}</Button>
                    ) : (
                      <Button size="sm" onClick={() => openCreate(item)}>{t.add}</Button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </Panel>
          <Panel title={t.marketplace} className="mcpmarket-discovery">
            <p className="muted">{t.marketplaceHint}</p>
            <p className="muted">trust={t.marketplaceTrust} · status={marketStatus}</p>
            <div className="form-grid two" style={{ marginTop: 8, marginBottom: 12 }}>
              <Input
                placeholder={t.marketplaceSearch}
                value={marketQuery}
                onChange={(e) => setMarketQuery(e.target.value)}
                data-testid="mcpmarket-search"
              />
              <div className="inline-actions">
                <Select value={marketKind} onValueChange={(v: "mcp_server" | "skill") => setMarketKind(v)}>
                  <SelectTrigger><SelectValue /></SelectTrigger>
                  <SelectContent>
                    <SelectItem value="mcp_server">MCP</SelectItem>
                    <SelectItem value="skill">Skill</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  disabled={!!busy || !marketQuery.trim()}
                  onClick={() => void runAction("mcpmarket-search", async () => {
                    const res = await hadesApi.mcpmarketSearch(marketQuery.trim(), marketKind);
                    setMarketStatus(String(res.status || "unknown"));
                    setMarketCandidates(res.candidates || []);
                    setMarketNote(String(res.note || ""));
                  })}
                >{t.refresh}</Button>
              </div>
            </div>
            {marketNote ? <p className="muted">{marketNote}</p> : null}
            {marketCandidates.length === 0 ? <EmptyLine>{t.marketplaceEmpty}</EmptyLine> : (
              <div className="list-stack">
                {marketCandidates.map((item) => (
                  <div key={item.slug || item.name} className="list-row static">
                    <div>
                      <strong>{item.name || item.slug}</strong>
                      <p>{item.description}</p>
                      <p className="muted">{item.why} · {t.marketplaceTrust} · {item.side_effect_class || "network"}</p>
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => void runAction("mcpmarket-prepare", async () => {
                        const prepared = await hadesApi.mcpmarketPrepareConnection({
                          name: item.name,
                          slug: item.slug,
                          description: item.description,
                          kind_hint: marketKind === "skill" ? "skill" : "mcp_server",
                        }, true);
                        if (!prepared.allowed || !prepared.draft) {
                          toast.message(String(prepared.reason || t.marketplaceEmpty));
                          return;
                        }
                        if (prepared.executes || prepared.installs) {
                          toast.error("MCPMarket must not execute or install.");
                          return;
                        }
                        const created = await hadesApi.mcpCreateServer(prepared.draft);
                        setSelectedId(created.server.id);
                        toast.message(lang === "nl" ? "Draft-server aangemaakt. Verbind handmatig." : "Draft server created. Connect manually.");
                      })}
                    >{t.prepareDraft}</Button>
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </TabsContent>

        <TabsContent value="tools" className="plugin-layout">
          <Panel title={t.tools}>
            <div className="form-grid two" style={{ marginBottom: 12 }}>
              <Input placeholder={lang === "nl" ? "Zoeken…" : "Search…"} value={toolQuery} onChange={(e) => setToolQuery(e.target.value)} />
              <Select value={filterAllowed} onValueChange={(v: "all" | "yes" | "no") => setFilterAllowed(v)}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">{lang === "nl" ? "Alle rechten" : "All permissions"}</SelectItem>
                  <SelectItem value="yes">{t.allowed}</SelectItem>
                  <SelectItem value="no">{lang === "nl" ? "Geblokkeerd" : "Blocked"}</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="list-stack">
              {filteredTools.map((tool) => (
                <button key={tool.id} type="button" className={`list-row ${selectedToolId === tool.id ? "active" : ""}`} onClick={() => {
                  setSelectedToolId(tool.id);
                  setInvokeArgs(JSON.stringify({}, null, 2));
                  setInvokeResult(null);
                }}>
                  <div>
                    <strong>{tool.remote_name}</strong>
                    <p>{tool.server_name} · {tool.model_name}</p>
                  </div>
                  <StatusBadge tone={tool.allowed ? "success" : "danger"}>{tool.allowed ? t.allowed : (lang === "nl" ? "Geblokkeerd" : "Blocked")}</StatusBadge>
                </button>
              ))}
              {filteredTools.length === 0 ? <EmptyLine>{lang === "nl" ? "Geen tools" : "No tools"}</EmptyLine> : null}
            </div>
          </Panel>

          <div className="details-stack">
            {selectedTool ? (
              <Panel title={selectedTool.remote_name}>
                <p>{selectedTool.description}</p>
                {selectedTool.schema_issue ? <p className="error-text">{t.schemaIssue}: {selectedTool.schema_issue}</p> : null}
                <div className="form-grid two" style={{ marginTop: 12 }}>
                  <label className="inline-switch"><span>{t.allowed}</span><Switch checked={selectedTool.allowed} onCheckedChange={(v) => void runAction("pref", async () => { await hadesApi.mcpUpdateTool(selectedTool.id, { allowed: v }); })} /></label>
                  <label className="inline-switch"><span>{t.chatbot}</span><Switch checked={selectedTool.chatbot_enabled} onCheckedChange={(v) => void runAction("pref", async () => { await hadesApi.mcpUpdateTool(selectedTool.id, { chatbot_enabled: v }); })} /></label>
                  <label className="inline-switch"><span>{t.approval}</span><Switch checked={selectedTool.require_approval} onCheckedChange={(v) => void runAction("pref", async () => { await hadesApi.mcpUpdateTool(selectedTool.id, { require_approval: v }); })} /></label>
                </div>
                <h4 style={{ marginTop: 16 }}>{lang === "nl" ? "Invoerschema" : "Input schema"}</h4>
                <pre className="code-block">{JSON.stringify(selectedTool.input_schema || {}, null, 2)}</pre>
                {selectedTool.annotations && Object.keys(selectedTool.annotations).length ? (
                  <>
                    <h4>Annotations</h4>
                    <pre className="code-block">{JSON.stringify(selectedTool.annotations, null, 2)}</pre>
                    <p className="muted">{lang === "nl" ? "Annotaties zijn aanwijzingen, geen autorisatiebewijs." : "Annotations are hints, not authorization."}</p>
                  </>
                ) : null}
                <h4 style={{ marginTop: 16 }}>{t.invoke}</h4>
                <Textarea value={invokeArgs} onChange={(e) => setInvokeArgs(e.target.value)} rows={8} />
                <div className="inline-actions" style={{ marginTop: 8 }}>
                  <Button
                    disabled={!!busy}
                    onClick={() => void runAction("invoke", async () => {
                      let args: Record<string, unknown> = {};
                      try {
                        args = JSON.parse(invokeArgs || "{}");
                      } catch {
                        throw new Error(lang === "nl" ? "Ongeldige JSON-argumenten" : "Invalid JSON arguments");
                      }
                      const result = await hadesApi.mcpInvokeTool(selectedTool.id, {
                        arguments: args,
                        // approved_by_user is audit only; approval_id is authority.
                        approved_by_user: true,
                        idempotency_key: `${selectedTool.id}:${Date.now()}`,
                      }).catch(async (err: unknown) => {
                        const apiErr = err as { status?: number; detail?: { approval_required?: boolean; approval?: { id?: string } } };
                        const approvalId = apiErr?.detail?.approval?.id;
                        if ((apiErr?.status === 428 || apiErr?.detail?.approval_required) && approvalId) {
                          await hadesApi.decideApproval(approvalId, true, "MCP page invoke");
                          return hadesApi.mcpInvokeTool(selectedTool.id, {
                            arguments: args,
                            approval_id: approvalId,
                            approved_by_user: true,
                            idempotency_key: `${selectedTool.id}:${Date.now()}`,
                          });
                        }
                        throw err;
                      });
                      setInvokeResult(result);
                      const payload = (result as { result?: { isError?: boolean }; error_kind?: string; execution?: { status?: string } }) || {};
                      const failed =
                        Boolean(payload.result?.isError) ||
                        Boolean(payload.error_kind) ||
                        (payload.execution?.status && !["completed", "running"].includes(String(payload.execution.status)));
                      if (failed) {
                        toast.error(lang === "nl" ? "MCP-uitvoering mislukt of onzeker" : "MCP execution failed or uncertain");
                      } else {
                        toast.success(lang === "nl" ? "Uitvoering afgerond" : "Execution finished");
                      }
                    })}
                  >
                    {t.invoke}
                  </Button>
                  {invokeResult && typeof invokeResult.execution === "object" && invokeResult.execution && "id" in (invokeResult.execution as object) ? (
                    <Button variant="outline" onClick={() => void runAction("cancel", () => hadesApi.mcpCancelExecution(String((invokeResult.execution as { id: string }).id)))}>{t.cancel}</Button>
                  ) : null}
                </div>
                {invokeResult ? (
                  <>
                    <h4 style={{ marginTop: 12 }}>{t.result}</h4>
                    <pre className="code-block">{JSON.stringify(invokeResult, null, 2)}</pre>
                  </>
                ) : null}
                <h4 style={{ marginTop: 12 }}>{lang === "nl" ? "Recente uitvoeringen" : "Recent executions"}</h4>
                <div className="list-stack">
                  {executions.filter((e) => e.tool_id === selectedTool.id || !selectedTool).slice(0, 8).map((exec) => (
                    <div key={exec.id} className="list-row static">
                      <div>
                        <strong>{exec.status}</strong>
                        <p>{exec.error_kind || "—"} · {exec.duration_ms != null ? `${Math.round(exec.duration_ms)}ms` : "—"}</p>
                      </div>
                      <span className="muted">{exec.started_at}</span>
                    </div>
                  ))}
                </div>
              </Panel>
            ) : (
              <Panel title={lang === "nl" ? "Tool details" : "Tool details"}><EmptyLine>{lang === "nl" ? "Selecteer een tool" : "Select a tool"}</EmptyLine></Panel>
            )}
          </div>
        </TabsContent>
      </Tabs>

      <Dialog open={editorOpen} onOpenChange={setEditorOpen}>
        <DialogContent className="max-w-xl">
          <DialogHeader>
            <DialogTitle>{editingId ? t.edit : t.add}</DialogTitle>
            <DialogDescription>{lang === "nl" ? "Geen shell-interpolatie: executable + aparte argumenten." : "No shell interpolation: executable + separate args."}</DialogDescription>
          </DialogHeader>
          <div className="form-grid">
            <label><span>{lang === "nl" ? "Naam" : "Name"}</span><Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
            <label><span>{lang === "nl" ? "Beschrijving" : "Description"}</span><Input value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label>
            <label><span>Transport</span>
              <Select value={form.transport} onValueChange={(v: "stdio" | "streamable_http") => setForm({ ...form, transport: v })}>
                <SelectTrigger><SelectValue /></SelectTrigger>
                <SelectContent>
                  <SelectItem value="stdio">stdio</SelectItem>
                  <SelectItem value="streamable_http">streamable_http</SelectItem>
                </SelectContent>
              </Select>
            </label>
            {form.transport === "stdio" ? (
              <>
                <label><span>Executable</span><Input value={form.executable} onChange={(e) => setForm({ ...form, executable: e.target.value })} /></label>
                <label><span>{lang === "nl" ? "Argumenten (één per regel)" : "Arguments (one per line)"}</span><Textarea value={form.argsText} onChange={(e) => setForm({ ...form, argsText: e.target.value })} rows={4} /></label>
                <label><span>{lang === "nl" ? "Werkdirectory" : "Working directory"}</span><Input value={form.cwd} onChange={(e) => setForm({ ...form, cwd: e.target.value })} /></label>
                <label><span>{lang === "nl" ? "Omgeving (KEY=value)" : "Environment (KEY=value)"}</span><Textarea value={form.envPlainText} onChange={(e) => setForm({ ...form, envPlainText: e.target.value })} rows={3} /></label>
                <label><span>{lang === "nl" ? "Geheimen (KEY=value, veilig opgeslagen)" : "Secrets (KEY=value, secure store)"}</span><Textarea value={form.envSecretsText} onChange={(e) => setForm({ ...form, envSecretsText: e.target.value })} rows={3} /></label>
              </>
            ) : (
              <>
                <label><span>Endpoint URL</span><Input value={form.endpoint_url} onChange={(e) => setForm({ ...form, endpoint_url: e.target.value })} /></label>
                <label><span>{lang === "nl" ? "Authenticatie" : "Authentication"}</span>
                  <Select value={form.auth_method} onValueChange={(v) => setForm({ ...form, auth_method: v })}>
                    <SelectTrigger><SelectValue /></SelectTrigger>
                    <SelectContent>
                      <SelectItem value="none">{lang === "nl" ? "Geen" : "None"}</SelectItem>
                      <SelectItem value="bearer">Bearer</SelectItem>
                      <SelectItem value="oauth">OAuth</SelectItem>
                    </SelectContent>
                  </Select>
                </label>
                {form.auth_method === "bearer" ? (
                  <label><span>Bearer token</span><Input type="password" value={form.bearer_token} onChange={(e) => setForm({ ...form, bearer_token: e.target.value })} placeholder={editingId ? "•••• (unchanged if empty)" : ""} /></label>
                ) : null}
                <label><span>{lang === "nl" ? "Headers (Name: value)" : "Headers (Name: value)"}</span><Textarea value={form.headersText} onChange={(e) => setForm({ ...form, headersText: e.target.value })} rows={3} /></label>
              </>
            )}
            <label><span>Timeout (s)</span><Input value={form.timeout_seconds} onChange={(e) => setForm({ ...form, timeout_seconds: e.target.value })} /></label>
            <label className="inline-switch"><span>{lang === "nl" ? "Automatisch verbinden" : "Auto-connect"}</span><Switch checked={form.auto_connect} onCheckedChange={(v) => setForm({ ...form, auto_connect: v })} /></label>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setEditorOpen(false)}>{t.cancel}</Button>
            <Button disabled={!!busy} onClick={() => void saveServer()}>{lang === "nl" ? "Opslaan" : "Save"}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteId} onOpenChange={(open) => !open && setDeleteId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.remove}</DialogTitle>
            <DialogDescription>{t.confirmDelete}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteId(null)}>{t.cancel}</Button>
            <Button variant="destructive" onClick={() => {
              if (!deleteId) return;
              void runAction("delete", async () => {
                await hadesApi.mcpDeleteServer(deleteId);
                if (selectedId === deleteId) setSelectedId(null);
                setDeleteId(null);
              });
            }}>{t.remove}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
