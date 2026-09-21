"use client";

import { ChangeEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Download, FolderOpen, Loader2, Mic, PackageCheck, Play, PlugZap, Plus, Power, RefreshCcw, RotateCcw, Search, ShieldCheck, TerminalSquare, Trash2, TriangleAlert, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { PageHeader, Panel, StatCard, StatusBadge } from "@/components/hades/ui";
import { PluginCapabilityGroups } from "@/components/hades/features/plugins/PluginCapabilityGroups";
import { API_BASE, formatDate, hadesApi, HadesApiError, HadesPlugin, PluginEvent, PluginTimelineItem, PluginTool, PluginToolCall } from "@/lib/hades-api";

const pluginTone = (status: string) => status === "ready" ? "success" : status === "unsupported" ? "danger" : status === "preparing" ? "info" : "warning";
const callTone = (status: string) => status === "completed" ? "success" : status === "running" ? "info" : status === "failed" || status === "blocked" ? "danger" : "warning";

type SchemaProperty = { type?: string; title?: string; description?: string; default?: unknown; enum?: unknown[] };

function initialToolInput(tool: PluginTool | null): Record<string, unknown> {
  const properties = tool?.input_schema?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return {};
  return Object.fromEntries(Object.entries(properties).flatMap(([name, raw]) => {
    if (!raw || typeof raw !== "object" || Array.isArray(raw) || !("default" in raw)) return [];
    return [[name, (raw as SchemaProperty).default]];
  }));
}

export function PluginsPage() {
  const [plugins, setPlugins] = useState<HadesPlugin[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [events, setEvents] = useState<PluginEvent[]>([]);
  const [timeline, setTimeline] = useState<PluginTimelineItem[]>([]);
  const [timelineMeta, setTimelineMeta] = useState<{ trust?: string; isolation?: string; failure_state?: string | null; capabilities?: Record<string, unknown> }>({});
  const [query, setQuery] = useState("");
  const [dialogOpen, setDialogOpen] = useState(false);
  const [converterOpen, setConverterOpen] = useState(false);
  const [folderBuilderOpen, setFolderBuilderOpen] = useState(false);
  const [sourceType, setSourceType] = useState<"folder" | "git">("git");
  const [source, setSource] = useState("");
  const [ref, setRef] = useState("");
  const [installDependencies, setInstallDependencies] = useState(true);
  const [importing, setImporting] = useState(false);
  const [tool, setTool] = useState<PluginTool | null>(null);
  const [toolArgs, setToolArgs] = useState("{}");
  const [toolResult, setToolResult] = useState<PluginToolCall | null>(null);
  const [toolCalls, setToolCalls] = useState<PluginToolCall[]>([]);
  const [observabilityError, setObservabilityError] = useState<string | null>(null);
  const [runningTool, setRunningTool] = useState(false);
  const [activeTab, setActiveTab] = useState("installed");
  const [mcpItems, setMcpItems] = useState<Array<Record<string, unknown>>>([]);
  const [mcpNote, setMcpNote] = useState<string | null>(null);
  const [mcpLoading, setMcpLoading] = useState(false);
  const [mcpError, setMcpError] = useState<string | null>(null);
  const [marketItems, setMarketItems] = useState<Array<Record<string, unknown>>>([]);
  const [marketNote, setMarketNote] = useState<string | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [marketError, setMarketError] = useState<string | null>(null);
  const [marketInstalling, setMarketInstalling] = useState<string | null>(null);
  const zipRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);

  const selected = useMemo(() => plugins.find((item) => item.id === selectedId) ?? plugins[0], [plugins, selectedId]);
  const visible = useMemo(() => plugins.filter((item) => !query.trim() || `${item.name} ${item.description} ${item.runtime_type} ${item.category}`.toLowerCase().includes(query.toLowerCase())), [plugins, query]);
  const toolInput = useMemo(() => {
    try {
      const parsed = JSON.parse(toolArgs) as unknown;
      return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed as Record<string, unknown> : {};
    } catch { return {}; }
  }, [toolArgs]);
  const schemaProperties = useMemo(() => {
    const properties = tool?.input_schema?.properties;
    return properties && typeof properties === "object" && !Array.isArray(properties) ? Object.entries(properties) as Array<[string, SchemaProperty]> : [];
  }, [tool]);

  const refresh = useCallback(async () => {
    try {
      const result = await hadesApi.plugins();
      setPlugins(result.plugins);
      setSelectedId((current) => current || result.plugins[0]?.id || "");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Plugins laden is mislukt.");
    }
  }, []);

  useEffect(() => {
    void refresh();
    void hadesApi.settings().then((result) => setInstallDependencies(result.values.plugin_auto_install_dependencies)).catch(() => undefined);
  }, [refresh]);

  const loadMcpCatalog = useCallback(async () => {
    setMcpLoading(true);
    setMcpError(null);
    try {
      const result = await hadesApi.mcpCatalog(true);
      setMcpItems(result.items ?? []);
      setMcpNote(result.note ?? null);
    } catch (reason) {
      setMcpItems([]);
      setMcpNote(null);
      setMcpError(reason instanceof Error ? reason.message : "MCP-catalogus laden is mislukt.");
    } finally {
      setMcpLoading(false);
    }
  }, []);

  const loadMarketplace = useCallback(async () => {
    setMarketLoading(true);
    setMarketError(null);
    try {
      const result = await hadesApi.pluginMarketplace();
      setMarketItems(result.items ?? []);
      setMarketNote(result.note ?? null);
    } catch (reason) {
      setMarketItems([]);
      setMarketNote(null);
      setMarketError(reason instanceof Error ? reason.message : "Marketplace laden is mislukt.");
    } finally {
      setMarketLoading(false);
    }
  }, []);

  const installFromMarketplace = async (pluginId: string) => {
    setMarketInstalling(pluginId);
    try {
      const result = await hadesApi.installMarketplacePlugin(pluginId, installDependencies);
      const proof = (result.marketplace as Record<string, unknown> | undefined)?.health_proof;
      if (proof) {
        toast.success(`${pluginId} geïnstalleerd (Ready/health ok).`);
      } else {
        toast.message(`${pluginId} geïnstalleerd — Ready/health niet bewezen; controleer status.`);
      }
      await Promise.all([refresh(), loadMarketplace()]);
      const plugin = result.plugin as HadesPlugin | undefined;
      if (plugin?.id) {
        setSelectedId(plugin.id);
        setActiveTab("installed");
      }    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Marketplace-installatie mislukt.");
    } finally {
      setMarketInstalling(null);
    }
  };

  useEffect(() => {
    if (activeTab !== "mcp") return;
    void loadMcpCatalog();
  }, [activeTab, loadMcpCatalog]);

  useEffect(() => {
    if (activeTab !== "marketplace") return;
    void loadMarketplace();
  }, [activeTab, loadMarketplace]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const hash = window.location.hash;
    const query = hash.includes("?") ? hash.split("?")[1] : "";
    const params = new URLSearchParams(query);
    const tab = params.get("tab");
    if (tab === "mcp" || tab === "marketplace" || tab === "installed" || tab === "runtime" || tab === "permissions" || tab === "timeline") {
      setActiveTab(tab);
    }
  }, []);

  useEffect(() => {
    if (!selected?.id) {
      setEvents([]);
      setToolCalls([]);
      setTimeline([]);
      setTimelineMeta({});
      setObservabilityError(null);
      return;
    }
    setObservabilityError(null);
    void Promise.all([
      hadesApi.pluginEvents(selected.id),
      hadesApi.pluginToolCalls(selected.id),
      hadesApi.pluginTimeline(selected.id),
    ])
      .then(([nextEvents, nextCalls, nextTimeline]) => {
        setEvents(nextEvents);
        setToolCalls(nextCalls);
        setTimeline(nextTimeline.items ?? []);
        setTimelineMeta({
          trust: nextTimeline.trust,
          isolation: nextTimeline.isolation,
          failure_state: nextTimeline.failure_state,
          capabilities: nextTimeline.capabilities,
        });
        setObservabilityError(null);
      })
      .catch((reason: Error) => {
        // Preserve previous observability lists; empty UI must not look like a clean successful history.
        setObservabilityError(reason.message || "Plugin-observability laden mislukt.");
      });
    const firstTool = selected.tools[0] ?? null;
    setTool(firstTool);
    setToolArgs(JSON.stringify(initialToolInput(firstTool), null, 2));
    setToolResult(null);
  }, [selected?.id]);

  const setTrust = async (trust: "untrusted" | "manual" | "verified" | "trusted") => {
    if (!selected) return;
    try {
      await hadesApi.setPluginTrust(selected.id, trust);
      await refresh();
      toast.success(`Trust gezet op ${trust}.`);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Trust wijzigen is mislukt.");
    }
  };

  const expandMcp = async () => {
    if (!selected) return;
    try {
      const result = await hadesApi.expandPluginMcp(selected.id);
      await refresh();
      const expansion = (result.expansion || {}) as {
        expanded?: number;
        skipped?: boolean;
        ok?: boolean;
        error?: string;
        reason?: string;
      };
      const expanded = Number(expansion.expanded ?? 0);
      if (expansion.skipped) {
        toast.message(`MCP-expansie overgeslagen: ${expansion.reason || "geen actie"}.`);
      } else if (expansion.ok === false || expanded <= 0) {
        toast.error(expansion.error || "MCP-expansie leverde geen remote tools op.");
      } else {
        toast.success(`MCP-expansie: ${String(expanded)} tools.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "MCP-expansie is mislukt.");
    }
  };

  const chooseTool = (nextTool: PluginTool, openRuntime = false) => {
    setTool(nextTool);
    setToolArgs(JSON.stringify(initialToolInput(nextTool), null, 2));
    setToolResult(null);
    if (openRuntime) setActiveTab("runtime");
  };

  const setToolInputValue = (name: string, value: unknown) => {
    setToolArgs(JSON.stringify({ ...toolInput, [name]: value }, null, 2));
  };

  const doImport = async () => {
    if (!source.trim()) return;
    setImporting(true);
    try {
      const result = await hadesApi.importPlugin({
        source_type: sourceType,
        path_or_url: source.trim(),
        ref: ref.trim(),
        install_dependencies: installDependencies,
        approved_network: sourceType === "git" || installDependencies,
        approved_file_read: true,
        approved_file_write: true,
      });
      setDialogOpen(false);
      setSource("");
      setRef("");
      await refresh();
      setSelectedId(result.plugin.id);
      const status = String(result.plugin.status || "");
      if (["error", "failed", "broken", "blocked"].includes(status)) {
        toast.error(`Pluginconversie eindigde in status: ${status}.`);
      } else {
        toast.success(`Plugin geconverteerd: ${status}.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Pluginimport is mislukt.");
    } finally {
      setImporting(false);
    }
  };

  const importZip = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    const lower = file.name.toLowerCase();
    if (!lower.endsWith(".zip") && !lower.endsWith(".hadesplugin")) {
      toast.error("Kies een .zip of .HadesPlugin-bestand.");
      return;
    }
    if (file.size < 64) {
      toast.error("Bestand is te klein om een geldig pluginarchief te zijn (mogelijk een LFS-pointer).");
      return;
    }
    setImporting(true);
    try {
      // Prefer package import even when network is blocked: backend soft-skips deps.
      const result = await hadesApi.importPluginZip(file, installDependencies, true, installDependencies);
      await refresh();
      setSelectedId(result.plugin.id);
      const status = String(result.plugin.status || "");
      const skipped = Boolean((result as { dependencies_skipped?: boolean }).dependencies_skipped);
      const warnings = (result as { warnings?: string[] }).warnings || [];
      if (["error", "failed", "broken", "blocked"].includes(status)) {
        toast.error(`Pluginimport eindigde in status: ${status}.`);
      } else if (skipped || warnings.length) {
        toast.success(`Plugin geïmporteerd (${status}). Dependencies later via Repair.`);
        warnings.slice(0, 2).forEach((warning) => toast.message(warning));
      } else {
        toast.success(`.HadesPlugin-conversie afgerond: ${status}.`);
      }
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "ZIP-import is mislukt.");
    } finally {
      setImporting(false);
    }
  };

  const toggle = async (enabled: boolean) => {
    if (!selected) return;
    try { await hadesApi.setPluginState(selected.id, enabled); await refresh(); } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Pluginstatus wijzigen is mislukt."); }
  };

  const repair = async () => {
    if (!selected) return;
    try {
      const result = await hadesApi.repairPlugin(selected.id);
      await refresh();
      const status = String(result.plugin.status || "");
      if (status === "ready") {
        toast.success("Dependencies en runtime zijn gereed.");
      } else if (["error", "failed", "broken", "blocked"].includes(status)) {
        toast.error(`Repair mislukt (status: ${status}).`);
      } else {
        toast.message(`Repair afgerond; status is ${status || "onbekend"} — review blijft nodig.`);
      }
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Dependency-repair is mislukt."); }
  };

  const updatePlugin = async () => {
    if (!selected) return;
    try {
      const result = await hadesApi.updatePlugin(selected.id);
      await refresh();
      setSelectedId(result.plugin.id);
      const status = String(result.plugin.status || "");
      if (["error", "failed", "broken", "blocked"].includes(status)) {
        toast.error(`Pluginupdate eindigde in status: ${status}.`);
      } else {
        toast.success(`Plugin bijgewerkt: ${status}.`);
      }
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Pluginupdate is mislukt."); }
  };

  const rollbackPlugin = async () => {
    if (!selected) return;
    try {
      const result = await hadesApi.rollbackPlugin(selected.id);
      await refresh();
      setSelectedId(result.plugin.id);
      toast.success("Vorige plugin-snapshot is hersteld.");
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Rollback is mislukt."); }
  };

  const exportPlugin = async () => {
    if (!selected) return;
    try {
      await downloadPluginPackage(selected);
      toast.success(".HadesPlugin geëxporteerd.");
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Pluginexport is mislukt."); }
  };

  const downloadPluginPackage = async (plugin: Pick<HadesPlugin, "id" | "version">) => {
    const response = await fetch(`${API_BASE}/plugins/${plugin.id}/export`);
    if (!response.ok) throw new Error(`Export mislukt (HTTP ${response.status}).`);
    const blob = await response.blob();
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `${plugin.id}-${plugin.version}.HadesPlugin`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(href);
  };

  const finishBuiltPlugin = async (result: { plugin: HadesPlugin }) => {
    setFolderBuilderOpen(false);
    await refresh();
    setSelectedId(result.plugin.id);
    try {
      await downloadPluginPackage(result.plugin);
    } catch {
      // The plugin is already in the library; the package download is a convenience.
    }
    const status = String(result.plugin.status || "");
    const enabled = Boolean(result.plugin.enabled);
    if (status === "ready" && enabled) {
      toast.success(`.HadesPlugin gebouwd en klaar voor gebruik: ${result.plugin.name}.`);
    } else if (status === "ready") {
      toast.success(`.HadesPlugin gebouwd (Ready). Schakel '${result.plugin.name}' handmatig in na review.`);
    } else if (["error", "failed", "broken", "blocked"].includes(status)) {
      toast.error(`.HadesPlugin build eindigde in status: ${status}.`);
    } else {
      toast.message(`.HadesPlugin gebouwd (${status}). Review of Repair dependencies blijft nodig.`);
    }
  };

  const pickAndBuildFromComputer = async () => {
    setImporting(true);
    try {
      const picked = await hadesApi.pickPluginFolder();
      if (picked.cancelled || !picked.path) return;
      const result = await hadesApi.importPlugin({
        source_type: "folder",
        path_or_url: picked.path,
        install_dependencies: false,
        approved_network: false,
        approved_file_read: true,
        approved_file_write: true,
      });
      await finishBuiltPlugin(result);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Map bouwen is mislukt.");
    } finally {
      setImporting(false);
    }
  };

  const importFolderFromBrowser = async (event: ChangeEvent<HTMLInputElement>) => {
    const files = event.target.files ? Array.from(event.target.files) : [];
    event.target.value = "";
    if (!files.length) return;
    setImporting(true);
    try {
      const result = await hadesApi.importPluginFolder(files, false, true, false);
      await finishBuiltPlugin(result);
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Map bouwen is mislukt.");
    } finally {
      setImporting(false);
    }
  };

  const convertSource = async () => {
    if (!source.trim()) return;
    setImporting(true);
    try {
      // Conversion only copies/inspects source and writes a package: it never
      // installs dependencies or runs source code.
      const result = await hadesApi.importPlugin({
        source_type: sourceType,
        path_or_url: source.trim(),
        ref: ref.trim(),
        install_dependencies: false,
        approved_network: sourceType === "git",
        approved_file_read: true,
        approved_file_write: true,
      });
      await hadesApi.setPluginState(result.plugin.id, false);
      await downloadPluginPackage(result.plugin);
      setConverterOpen(false);
      setSource("");
      setRef("");
      await refresh();
      setSelectedId(result.plugin.id);
      toast.success(".HadesPlugin is gedownload. De bron blijft ter review uitgeschakeld in je pluginbibliotheek.");
    } catch (reason) {
      toast.error(reason instanceof Error ? reason.message : "Bronconversie is mislukt.");
    } finally {
      setImporting(false);
    }
  };

  const uninstallPlugin = async () => {
    if (!selected || !window.confirm(`Plugin '${selected.name}' volledig verwijderen?`)) return;
    try {
      await hadesApi.deletePlugin(selected.id);
      setSelectedId("");
      await refresh();
      toast.success("Plugin verwijderd.");
    } catch (reason) { toast.error(reason instanceof Error ? reason.message : "Plugin verwijderen is mislukt."); }
  };

  const runTool = async () => {
    if (!selected || !tool) return;
    setRunningTool(true);
    setToolResult(null);
    try {
      const input = JSON.parse(toolArgs || "{}") as unknown;
      if (!input || typeof input !== "object" || Array.isArray(input)) throw new Error("Toolinput moet een JSON-object zijn.");
      const result = await hadesApi.invokePlugin(selected.id, tool.name, input as Record<string, unknown>);
      setToolResult(result);
      const [nextEvents, nextCalls] = await Promise.all([hadesApi.pluginEvents(selected.id), hadesApi.pluginToolCalls(selected.id)]);
      setEvents(nextEvents);
      setToolCalls(nextCalls);
      await refresh();
      if (result.status === "completed") toast.success(`Tool '${tool.name}' voltooid.`);
      else toast.error(result.error || `Tool '${tool.name}' is mislukt.`);
    } catch (reason) {
      if (reason instanceof HadesApiError && reason.detail && typeof reason.detail === "object" && "tool_call" in reason.detail) {
        setToolResult((reason.detail as { tool_call: PluginToolCall }).tool_call);
        setToolCalls(await hadesApi.pluginToolCalls(selected.id).catch(() => toolCalls));
        setEvents(await hadesApi.pluginEvents(selected.id).catch(() => events));
      }
      toast.error(reason instanceof Error ? reason.message : "Tooluitvoering mislukt.");
    } finally { setRunningTool(false); }
  };

  const readyCount = plugins.filter((item) => item.status === "ready").length;
  const enabledCount = plugins.filter((item) => item.enabled).length;
  const attentionCount = plugins.filter((item) => item.status !== "ready").length;

  return (
    <div className="page page-plugins">
      <PageHeader title="Plugins" description="Converteer GitHub/source-projecten naar geïsoleerde HADES-tools met dependency-preparatie, inspecteerbare manifests en bewijsbare runtime-health." actions={<>
        <input ref={zipRef} className="visually-hidden" type="file" accept=".zip,.HadesPlugin" onChange={importZip} />
        <input ref={folderRef} className="visually-hidden" type="file" multiple aria-hidden="true" tabIndex={-1} aria-label="Pluginmap via browser kiezen" onChange={importFolderFromBrowser} {...({ webkitdirectory: "", directory: "" } as Record<string, string>)} />
        <Dialog open={folderBuilderOpen} onOpenChange={setFolderBuilderOpen}>
          <DialogTrigger asChild>
            <Button variant="outline" disabled={importing}><FolderOpen />Map → .HadesPlugin</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Map → .HadesPlugin</DialogTitle>
              <DialogDescription>Selecteer een lokale map. HADES inspecteert de bron, bouwt een .HadesPlugin-package en zet de plugin in je bibliotheek zodat je hem kunt gebruiken.</DialogDescription>
            </DialogHeader>
            <div className="form-stack">
              <div className="security-note compact"><ShieldCheck /><span><strong>Alleen inpakken</strong><small>HADES kopieert en inspecteert de map, bouwt het .HadesPlugin-package en zet de plugin in je bibliotheek. Dependencies worden niet geïnstalleerd; gebruik daarna Repair als de runtime dat nodig heeft. Grote mappen: kies “Deze computer” zodat bestanden niet via de browser worden geüpload.</small></span></div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setFolderBuilderOpen(false)}>Annuleren</Button>
              <Button variant="outline" onClick={() => folderRef.current?.click()} disabled={importing}>{importing ? <Loader2 className="spin" /> : <Upload />}Via browser</Button>
              <Button onClick={() => void pickAndBuildFromComputer()} disabled={importing}>{importing ? <Loader2 className="spin" /> : <FolderOpen />}Deze computer</Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
        <Button variant="outline" onClick={() => zipRef.current?.click()} disabled={importing}><Upload />ZIP / .HadesPlugin</Button>
        <Dialog open={converterOpen} onOpenChange={setConverterOpen}><DialogTrigger asChild><Button variant="outline"><PackageCheck />Bron converteren</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Source → .HadesPlugin converter</DialogTitle><DialogDescription>Maakt een downloadbaar package van een Git-repository of lokale map. HADES inspecteert en kopieert uitsluitend de bron: dependencies worden niet geïnstalleerd en de source wordt niet uitgevoerd. Controleer een package altijd vóór je het inschakelt.</DialogDescription></DialogHeader>
          <div className="form-stack">
            <label><span>Bronsoort</span><Select value={sourceType} onValueChange={(value) => setSourceType(value as "folder" | "git")}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="git">Git/GitHub URL</SelectItem><SelectItem value="folder">Lokale map</SelectItem></SelectContent></Select></label>
            <label><span>{sourceType === "git" ? "Repository URL" : "Lokaal mappad"}</span><Input value={source} onChange={(event) => setSource(event.target.value)} placeholder={sourceType === "git" ? "https://github.com/owner/project.git" : "D:\\Source\\project"} /></label>
            {sourceType === "git" ? <label><span>Branch/tag (optioneel)</span><Input value={ref} onChange={(event) => setRef(event.target.value)} placeholder="main / v1.2.0" /></label> : null}
            <div className="security-note compact"><ShieldCheck /><span><strong>Alleen converteren</strong><small>Geen dependency-installatie, geen toolrun en de geconverteerde plugin blijft uitgeschakeld.</small></span></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setConverterOpen(false)}>Annuleren</Button><Button onClick={convertSource} disabled={!source.trim() || importing}>{importing ? <Loader2 className="spin" /> : <Download />}Converteren & downloaden</Button></DialogFooter>
        </DialogContent></Dialog>
        <Dialog open={dialogOpen} onOpenChange={setDialogOpen}><DialogTrigger asChild><Button><Plus />Plugin toevoegen</Button></DialogTrigger><DialogContent><DialogHeader><DialogTitle>Plugin importeren</DialogTitle><DialogDescription>HADES inspecteert de bron, detecteert de runtime, bouwt een adaptervoorstel en installeert plugin-lokale dependencies. Unsupported blijft expliciet zichtbaar.</DialogDescription></DialogHeader>
          <div className="form-stack">
            <label><span>Bronsoort</span><Select value={sourceType} onValueChange={(value) => setSourceType(value as "folder" | "git")}><SelectTrigger><SelectValue /></SelectTrigger><SelectContent><SelectItem value="git">Git/GitHub URL</SelectItem><SelectItem value="folder">Lokale map</SelectItem></SelectContent></Select></label>
            <label><span>{sourceType === "git" ? "Repository URL" : "Lokaal mappad"}</span><Input value={source} onChange={(event) => setSource(event.target.value)} placeholder={sourceType === "git" ? "https://github.com/owner/project.git" : "D:\\Source\\project"} /></label>
            {sourceType === "git" ? <label><span>Branch/tag (optioneel)</span><Input value={ref} onChange={(event) => setRef(event.target.value)} placeholder="main / v1.2.0" /></label> : null}
            <label className="setting-row"><span><strong>Dependencies automatisch voorbereiden</strong><small>Plugin-lokaal; geen stille globale systeemwijzigingen.</small></span><Switch checked={installDependencies} onCheckedChange={setInstallDependencies} /></label>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setDialogOpen(false)}>Annuleren</Button><Button onClick={doImport} disabled={!source.trim() || importing}>{importing ? <Loader2 className="spin" /> : <PackageCheck />}Analyseren & converteren</Button></DialogFooter>
        </DialogContent></Dialog>
      </>} />

      <section className="stat-grid four"><StatCard label="Geïnstalleerd" value={String(plugins.length)} note={`${enabledCount} ingeschakeld`} icon={<PackageCheck />} /><StatCard label="Ready" value={String(readyCount)} note="Runtime structureel gereed" icon={<CheckCircle2 />} /><StatCard label="Aandacht" value={String(attentionCount)} note="Setup/health vraagt actie" icon={<TriangleAlert />} /><StatCard label="Tool Registry" value={String(plugins.reduce((sum, item) => sum + item.tools.length, 0))} note="Machine-readable acties" icon={<PlugZap />} /></section>

      <div className="security-note compact" style={{ marginBottom: 16 }}>
        <Mic />
        <span>
          <strong>Spraak → taak (plak / lokale STT)</strong>
          <small>
            Geen cloud-STT. Dit paste-pad doet zelf geen ASR — importeer <code>plugins/local-stt-paste</code> (<code>transcribe_paste</code>),
            plak in Taken → Spraak, of chat <code>/voice</code>. Ingebouwde microfoon-ASR zit in Chat → Spraak. VoiceStudio is optionele externe ASR/TTS.
          </small>
        </span>
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="plugin-tabs">
        <div className="tabs-toolbar"><TabsList><TabsTrigger value="installed">Geïnstalleerd</TabsTrigger><TabsTrigger value="runtime">Runtime & test</TabsTrigger><TabsTrigger value="timeline">Timeline</TabsTrigger><TabsTrigger value="permissions">Toestemmingen</TabsTrigger><TabsTrigger value="marketplace">Marketplace</TabsTrigger><TabsTrigger value="mcp">MCP-catalogus</TabsTrigger></TabsList><div className="inline-search"><Search /><Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Zoek plugins…" /></div></div>
        <TabsContent value="installed">
          <div className="plugin-layout">
            <Panel title="Pluginbibliotheek" actions={<Button variant="outline" size="sm" onClick={() => void refresh()}><RefreshCcw />Vernieuwen</Button>}>
              <div className="plugin-list">{visible.map((plugin) => <button className={plugin.id === selected?.id ? "plugin-row active" : "plugin-row"} type="button" key={plugin.id} onClick={() => setSelectedId(plugin.id)}><span className="plugin-icon"><PlugZap /></span><span className="plugin-copy"><strong>{plugin.name} <em className="plugin-category-label">{plugin.category}</em>{plugin.labels.filter((label) => label.toLowerCase() !== plugin.category.toLowerCase()).slice(0, 2).map((label) => <em className="plugin-category-label secondary" key={label}>{label}</em>)}</strong><small>{plugin.description || plugin.local_path}</small><span><StatusBadge tone={pluginTone(plugin.status)}>{plugin.status}</StatusBadge><em>{plugin.runtime_type}</em><em>v{plugin.version}</em></span></span><Switch checked={plugin.enabled} disabled aria-label={`${plugin.name} status`} /></button>)}{!visible.length ? <p className="empty-copy">Nog geen plugins geïnstalleerd.</p> : null}</div>
            </Panel>
            <div className="details-stack">
              <Panel title={selected?.name ?? "Plugin"} actions={selected ? <StatusBadge tone={pluginTone(selected.status)}>{selected.status}</StatusBadge> : undefined}>
                {selected ? <><div className="plugin-hero"><span className="plugin-icon large"><PlugZap /></span><div><strong>{selected.runtime_type} · {selected.category}</strong><p>{selected.description || "Geen beschrijving uit de bron gevonden."}</p></div></div><dl className="detail-list spaced"><div><dt>Versie</dt><dd>{selected.version}</dd></div><div><dt>Bron</dt><dd>{selected.source}</dd></div><div><dt>Source ref</dt><dd><code>{selected.source_ref || "—"}</code></dd></div><div><dt>Runtime health</dt><dd>{selected.health}</dd></div><div><dt>Dependencies</dt><dd>{selected.dependency_call ? selected.dependency_call.status : selected.status === "ready" ? "niet vereist / voorbereid" : "onbekend"}</dd></div><div><dt>Enabled</dt><dd>{selected.enabled ? "ja" : "nee"}</dd></div><div><dt>Autonoom toegestaan</dt><dd>{selected.autonomous ? "ja (onder policy)" : "nee"}</dd></div><div><dt>Trust ladder</dt><dd>{selected.trust}</dd></div><div><dt>Isolation</dt><dd>{selected.isolation || "plugin_cwd"} <small>(geen OS-sandbox)</small></dd></div><div><dt>Failure state</dt><dd>{selected.failure_state || "—"}</dd></div><div><dt>Capabilities</dt><dd><code>{JSON.stringify(selected.capabilities || selected.manifest?.capabilities || {})}</code></dd></div><div><dt>Laatste update</dt><dd>{formatDate(selected.updated_at)}</dd></div></dl>{selected.last_error ? <div className="inline-error">{selected.last_error}</div> : null}<div className="button-row"><Button variant="outline" onClick={() => void toggle(!selected.enabled)} disabled={selected.status !== "ready" && !selected.enabled}><Power />{selected.enabled ? "Uitschakelen" : "Inschakelen"}</Button><Button variant="outline" onClick={repair}><RefreshCcw />Repair dependencies</Button><Button variant="outline" onClick={() => void setTrust("verified")}><ShieldCheck />Trust: verified</Button><Button variant="outline" onClick={() => void setTrust("trusted")}><ShieldCheck />Trust: trusted</Button><Button variant="outline" onClick={() => void expandMcp()}><PlugZap />Expand MCP</Button><Button variant="outline" onClick={exportPlugin}><Download />Export</Button>{selected.source === "git" ? <Button variant="outline" onClick={updatePlugin}><RefreshCcw />Update Git</Button> : null}<Button variant="outline" onClick={rollbackPlugin}><RotateCcw />Rollback</Button><Button variant="outline" onClick={uninstallPlugin}><Trash2 />Uninstall</Button></div></> : <p className="empty-copy">Selecteer een plugin.</p>}
              </Panel>
              <Panel title="Geregistreerde tools"><div className="permission-cards">{selected?.tools.map((item) => <button type="button" key={item.id} onClick={() => chooseTool(item, true)}><TerminalSquare /><div><strong>{item.name}</strong><small>{item.description || (Array.isArray(item.command) ? item.command.join(" ") : item.command)}</small>{item.metadata?.mcp_remote ? <em> MCP</em> : null}</div><StatusBadge tone={item.enabled ? "success" : "neutral"}>{item.enabled ? "Uitvoerbaar" : "Uit"}</StatusBadge></button>)}{selected && !selected.tools.length ? <div className="security-note"><TriangleAlert /><span><strong>Geen toolcontract gedetecteerd</strong><small>Deze source blijft Needs review totdat een expliciete adapter/tool is gedefinieerd.</small></span></div> : null}</div></Panel>
              {selected ? <Panel title="Capability groepen"><PluginCapabilityGroups pluginId={selected.id} /></Panel> : null}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="timeline">
          <Panel title="Observability timeline" actions={<Button variant="outline" size="sm" onClick={() => selected?.id && void hadesApi.pluginTimeline(selected.id).then((result) => { setTimeline(result.items); setTimelineMeta(result); setObservabilityError(null); }).catch((reason: Error) => setObservabilityError(reason.message || "Plugin-timeline laden mislukt."))}><RefreshCcw />Vernieuwen</Button>}>
            {observabilityError ? <div className="inline-error">{observabilityError}</div> : null}
            <div className="security-note compact">
              <ShieldCheck />
              <span>
                <strong>Eén tijdlijn per plugin</strong>
                <small>
                  trust={timelineMeta.trust || selected?.trust || "—"} · isolation={timelineMeta.isolation || selected?.isolation || "plugin_cwd"} · failure={timelineMeta.failure_state || selected?.failure_state || "—"}
                </small>
              </span>
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Tijd</th><th>Soort</th><th>Status</th><th>Bericht</th></tr>
                </thead>
                <tbody>
                  {[...timeline].reverse().map((item) => (
                    <tr key={item.id}>
                      <td>{typeof item.created_at === "string" ? formatDate(item.created_at) : String(item.created_at ?? "—")}</td>
                      <td>{item.kind}{item.tool_name ? ` · ${item.tool_name}` : ""}</td>
                      <td><StatusBadge tone={callTone(String(item.status || "info"))}>{String(item.status || "—")}</StatusBadge></td>
                      <td><small>{item.message || "—"}</small></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!timeline.length ? <div className="table-empty">Nog geen timeline-items voor deze plugin.</div> : null}
            </div>
          </Panel>
        </TabsContent>

        <TabsContent value="marketplace">
          <Panel
            title="Lokale plugin-marketplace"
            actions={
              <Button variant="outline" size="sm" onClick={() => void loadMarketplace()} disabled={marketLoading}>
                {marketLoading ? <Loader2 className="spin" /> : <RefreshCcw />}
                Vernieuwen
              </Button>
            }
          >
            <div className="security-note compact">
              <PackageCheck />
              <span>
                <strong>.HadesPlugin-bronnen</strong>
                <small>Installeer gebundelde plugins uit <code>plugins/</code>. Installatie inspecteert + packed; Ready/health is apart bewijs — catalogus keurt niets stil goed.</small>
              </span>
            </div>
            {marketNote ? <p className="empty-copy">{marketNote}</p> : null}
            {marketError ? <div className="inline-error">{marketError}</div> : null}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Plugin</th><th>Runtime</th><th>Tools</th><th>Status</th><th>Health</th><th>Actie</th></tr>
                </thead>
                <tbody>
                  {marketItems
                    .filter((item) => !query.trim() || `${item.name} ${item.id} ${item.description} ${item.category}`.toLowerCase().includes(query.toLowerCase()))
                    .map((item) => {
                      const id = String(item.id);
                      const status = String(item.status ?? "available");
                      const health = item.health == null ? "—" : String(item.health);
                      return (
                        <tr key={id}>
                          <td>
                            <strong>{String(item.name ?? id)}</strong>
                            <small>{String(item.description || item.relative_path || "")}</small>
                          </td>
                          <td>{String(item.runtime_type ?? "—")}{item.mcp ? " · MCP" : ""}</td>
                          <td>{String(item.tool_count ?? 0)}</td>
                          <td><StatusBadge tone={status === "installed" ? "success" : status === "installed_needs_attention" ? "warning" : "neutral"}>{status}</StatusBadge></td>
                          <td><StatusBadge tone={pluginTone(health === "—" ? "unknown" : health)}>{health}</StatusBadge></td>
                          <td>
                            <Button
                              size="sm"
                              variant="outline"
                              disabled={marketInstalling === id || Boolean(item.installed)}
                              onClick={() => void installFromMarketplace(id)}
                            >
                              {marketInstalling === id ? <Loader2 className="spin" /> : <Download />}
                              {item.installed ? "Geïnstalleerd" : "Installeren"}
                            </Button>
                          </td>
                        </tr>
                      );
                    })}
                </tbody>
              </table>
              {marketLoading ? <div className="table-empty"><Loader2 className="spin" />Marketplace laden…</div> : null}
              {!marketItems.length && !marketLoading ? (
                <div className="table-empty">Geen lokale marketplace-items gevonden.</div>
              ) : null}
            </div>
            <div className="table-footer">
              <span>{marketItems.length} bronnen</span>
              <span>{marketItems.filter((item) => item.installed).length} geïnstalleerd · health proof na install/repair</span>
            </div>
          </Panel>
        </TabsContent>

        <TabsContent value="runtime">
          <div className="plugin-layout">
            <Panel title="Handmatige tooltest">
              {selected?.tools.length ? <div className="form-stack">
                <div className="runtime-tool-list">{selected.tools.map((item) => <button type="button" className={tool?.id === item.id ? "active" : ""} key={item.id} onClick={() => chooseTool(item)}><TerminalSquare /><span><strong>{item.name}</strong><small>{String(item.metadata.action || "run")}</small></span></button>)}</div>
                {schemaProperties.length ? <div className="tool-fields">{schemaProperties.map(([name, definition]) => {
                  const required = Array.isArray(tool?.input_schema.required) && tool.input_schema.required.includes(name);
                  const label = definition.title || name;
                  const value = toolInput[name];
                  if (definition.type === "boolean") return <label className="setting-row" key={name}><span><strong>{label}{required ? " *" : ""}</strong><small>{definition.description || "Boolean"}</small></span><Switch checked={Boolean(value)} onCheckedChange={(checked) => setToolInputValue(name, checked)} /></label>;
                  if (definition.type === "array") return <label key={name}><span>{label}{required ? " *" : ""}</span><Textarea value={Array.isArray(value) ? value.map(String).join("\n") : ""} onChange={(event) => setToolInputValue(name, event.target.value.split(/\r?\n/).filter(Boolean))} placeholder={definition.description || "Eén argument per regel"} /></label>;
                  if (definition.type === "object") return <label key={name}><span>{label}{required ? " *" : ""}</span><Textarea key={`${tool?.id}-${name}`} defaultValue={value && typeof value === "object" ? JSON.stringify(value, null, 2) : "{}"} onBlur={(event) => { try { setToolInputValue(name, JSON.parse(event.target.value)); } catch { toast.error(`Veld '${name}' bevat ongeldige JSON.`); } }} placeholder={definition.description || "JSON-object"} /></label>;
                  return <label key={name}><span>{label}{required ? " *" : ""}</span><Input type={definition.type === "integer" || definition.type === "number" ? "number" : "text"} value={typeof value === "string" || typeof value === "number" ? value : ""} onChange={(event) => setToolInputValue(name, definition.type === "integer" ? Number.parseInt(event.target.value, 10) : definition.type === "number" ? Number(event.target.value) : event.target.value)} placeholder={definition.description || String(definition.type || "string")} /></label>;
                })}</div> : <p className="empty-copy">Deze tool heeft geen afzonderlijke schemavelden; gebruik het JSON-object hieronder.</p>}
                <label><span>JSON-argumenten</span><Textarea value={toolArgs} onChange={(event) => setToolArgs(event.target.value)} className="tool-json-input" placeholder={'{"query":"..."}'} /></label>
                <div className="security-note compact"><ShieldCheck /><span><strong>Eenmalige gebruikersgoedkeuring</strong><small>Door Run te klikken keur je uitsluitend deze handmatige toolcall goed. Globale block-rechten blijven altijd blokkeren.</small></span></div>
                <Button onClick={runTool} disabled={!selected.enabled || !tool?.enabled || runningTool}>{runningTool ? <Loader2 className="spin" /> : <Play />}Run</Button>
                {toolResult ? <div className="tool-result-panel"><dl className="detail-list spaced"><div><dt>Status</dt><dd><StatusBadge tone={callTone(toolResult.status)}>{toolResult.status}</StatusBadge></dd></div><div><dt>Exit code</dt><dd>{toolResult.exit_code ?? "—"}</dd></div><div><dt>Duur</dt><dd>{toolResult.duration_ms === null ? "—" : `${toolResult.duration_ms} ms`}</dd></div><div><dt>Gestart</dt><dd>{formatDate(toolResult.started_at)}</dd></div><div><dt>Voltooid</dt><dd>{formatDate(toolResult.finished_at)}</dd></div><div><dt>Herkomst</dt><dd>{toolResult.invocation_type} · {toolResult.approved_by_user ? "approved" : "niet approved"}</dd></div></dl>{toolResult.error ? <div className="inline-error">{toolResult.error}</div> : null}<label><span>Resultaat</span><Textarea value={toolResult.output || "(leeg)"} readOnly className="memory-content" /></label><label><span>stdout</span><Textarea value={toolResult.stdout || "(leeg)"} readOnly className="memory-content" /></label><label><span>stderr</span><Textarea value={toolResult.stderr || "(leeg)"} readOnly className="memory-content" /></label></div> : null}
              </div> : <p className="empty-copy">Selecteer een Ready-plugin met minimaal één tool.</p>}
            </Panel>
            <div className="details-stack"><Panel title="Runtime log"><div className="task-log">{observabilityError ? <div className="inline-error">{observabilityError}</div> : null}{events.length ? events.slice().reverse().map((event) => <code key={event.id}>{formatDate(event.created_at)}  {event.level.toUpperCase()}  {event.message}</code>) : !observabilityError ? <span className="empty-copy">Nog geen runtime-events.</span> : null}</div></Panel><Panel title="Persistente toolcalls"><div className="tool-call-list">{toolCalls.length ? toolCalls.map((call) => <button type="button" key={call.id} onClick={() => setToolResult(call)}><span><strong>{call.tool_name}</strong><small>{formatDate(call.timestamp)} · {call.duration_ms ?? "—"} ms · {call.invocation_type}</small></span><StatusBadge tone={callTone(call.status)}>{call.status}</StatusBadge></button>) : <span className="empty-copy">Nog geen toolcalls opgeslagen.</span>}</div></Panel></div>
          </div>
        </TabsContent>

        <TabsContent value="permissions"><Panel title="Plugin permissions"><div className="permission-matrix">{selected ? <>{selected.permissions.map((permission) => <div key={permission}><span>{permission}</span><StatusBadge tone="warning">Manifest declaration</StatusBadge></div>)}<div className="security-note"><ShieldCheck /><span><strong>Least privilege + core policies</strong><small>Netwerk- en bestandstoegang worden ook door HADES Settings afgedwongen. Systeemafhankelijkheden worden niet stil globaal geïnstalleerd.</small></span></div></> : <p className="empty-copy">Selecteer een plugin.</p>}</div></Panel></TabsContent>

        <TabsContent value="mcp">
          <Panel
            title="MCP-catalogus"
            actions={
              <Button variant="outline" size="sm" onClick={() => void loadMcpCatalog()} disabled={mcpLoading}>
                {mcpLoading ? <Loader2 className="spin" /> : <RefreshCcw />}
                Vernieuwen
              </Button>
            }
          >
            <div className="security-note compact">
              <ShieldCheck />
              <span>
                <strong>Eerste-klas toolrijen</strong>
                <small>Catalogus toont MCP-capable plugins/tools met health/enabled. Permission Engine + Ready-status blijven van kracht — catalogus is geen goedkeuring.</small>
              </span>
            </div>
            {mcpNote ? <p className="empty-copy">{mcpNote}</p> : null}
            {mcpError ? <div className="inline-error">{mcpError}</div> : null}
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr><th>Plugin</th><th>Tool</th><th>Health</th><th>Ready</th><th>Ingeschakeld</th><th>Permissions</th><th>MCP</th></tr>
                </thead>
                <tbody>
                  {mcpItems.map((item, index) => {
                    const perms = (item.permissions && typeof item.permissions === "object")
                      ? item.permissions as Record<string, unknown>
                      : {};
                    const flags = [
                      perms.network ? "net" : null,
                      perms.file_read ? "read" : null,
                      perms.file_write ? "write" : null,
                      perms.subprocess ? "subproc" : null,
                    ].filter(Boolean);
                    return (
                      <tr
                        key={`${String(item.plugin_id)}-${String(item.tool_name)}-${index}`}
                        className="clickable-row"
                        onClick={() => {
                          if (item.plugin_id) {
                            setSelectedId(String(item.plugin_id));
                            setActiveTab("installed");
                          }
                        }}
                      >
                        <td><strong>{String(item.plugin_name ?? item.plugin_id ?? "—")}</strong><small>{String(item.plugin_id ?? "")}</small></td>
                        <td><strong>{String(item.tool_name ?? "—")}</strong><small>{String(item.description ?? "")}</small></td>
                        <td><StatusBadge tone={pluginTone(String(item.health ?? "unknown"))}>{String(item.health ?? "unknown")}</StatusBadge></td>
                        <td><StatusBadge tone={item.ready ? "success" : "warning"}>{item.ready ? "ready" : "niet ready"}</StatusBadge></td>
                        <td><StatusBadge tone={item.enabled ? "success" : "neutral"}>{item.enabled ? "ja" : "nee"}</StatusBadge></td>
                        <td><small>{flags.length ? flags.join(" · ") : "geen"}</small></td>
                        <td>{item.mcp ? "ja" : "nee"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {mcpLoading ? <div className="table-empty"><Loader2 className="spin" />Catalogus laden…</div> : null}
              {!mcpItems.length && !mcpLoading ? (
                <div className="table-empty">Geen MCP-tools gevonden. Installeer MCP-plugins of bridges met geregistreerde tools.</div>
              ) : null}
            </div>
            <div className="table-footer">
              <span>{mcpItems.length} toolrijen</span>
              <span>Permissions blijven via manifest + HADES Settings afgedwongen</span>
            </div>
          </Panel>
        </TabsContent>
      </Tabs>
    </div>
  );
}
