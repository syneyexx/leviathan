/**
 * Tools V2 workspace — CapabilityCatalog / ExecutionGateway / receipts / MCP / plugins.
 * Visual fixture is TEST-ONLY behind window.__LV_V2_VISUAL_FIXTURE__ === 'tools'.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError } from "../../../api/client";
import {
  TOOLS_V2_VISUAL_FIXTURE,
  isToolsVisualFixtureActive,
} from "../../../mocks/toolsV2VisualFixture";
import { useAppToast } from "../../../state/useAppToast";
import type {
  ToolsCapabilityDetail,
  ToolsLibraryItem,
  ToolsOverview,
  ToolsRecentCall,
} from "../../../types/api";

export type ToolsDetailTab =
  | "overview"
  | "parameters"
  | "schema"
  | "example"
  | "logs"
  | "dependencies";

export type ToolsSortKey =
  | "name"
  | "category"
  | "source"
  | "status"
  | "version"
  | "last_used"
  | "-name"
  | "-category"
  | "-source"
  | "-status"
  | "-version"
  | "-last_used";

function errorMessage(err: unknown): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error) return err.message;
  return "Request failed";
}

function newIdempotencyKey(): string {
  return `tools-ui-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export function useToolsWorkspace() {
  const toast = useAppToast();
  const visual = isToolsVisualFixtureActive();

  const [overview, setOverview] = useState<ToolsOverview | null>(
    visual ? TOOLS_V2_VISUAL_FIXTURE.overview : null,
  );
  const [tools, setTools] = useState<ToolsLibraryItem[]>(
    visual ? TOOLS_V2_VISUAL_FIXTURE.tools : [],
  );
  const [toolsTotal, setToolsTotal] = useState(visual ? TOOLS_V2_VISUAL_FIXTURE.tools.length : 0);
  const [selectedId, setSelectedId] = useState<string | null>(
    visual ? TOOLS_V2_VISUAL_FIXTURE.tools[0]?.id ?? null : null,
  );
  const [detail, setDetail] = useState<ToolsCapabilityDetail | null>(
    visual ? TOOLS_V2_VISUAL_FIXTURE.detail : null,
  );
  const [recentCalls, setRecentCalls] = useState<ToolsRecentCall[]>(
    visual ? TOOLS_V2_VISUAL_FIXTURE.overview.recent_calls : [],
  );

  const [query, setQuery] = useState("");
  const [topbarQuery, setTopbarQuery] = useState("");
  const [category, setCategory] = useState("all");
  const [source, setSource] = useState("all");
  const [sort, setSort] = useState<ToolsSortKey>("name");
  const [detailTab, setDetailTab] = useState<ToolsDetailTab>("overview");

  const [loading, setLoading] = useState(!visual);
  const [detailLoading, setDetailLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [overviewStale, setOverviewStale] = useState(false);
  const [mcpStale, setMcpStale] = useState(false);
  const [pluginsStale, setPluginsStale] = useState(false);

  const [newToolOpen, setNewToolOpen] = useState(false);
  const [testOpen, setTestOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [mcpAddOpen, setMcpAddOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);
  const [testArgs, setTestArgs] = useState<Record<string, unknown>>({});
  const [creating, setCreating] = useState(false);

  const refreshLock = useRef(false);
  const selectGen = useRef(0);
  const pollRef = useRef<number | null>(null);
  const mounted = useRef(true);

  const effectiveQuery = topbarQuery.trim() || query.trim();

  const loadLibrary = useCallback(async () => {
    if (visual) return;
    const res = await api.capabilitiesLibrary({
      q: effectiveQuery || undefined,
      category: category === "all" ? undefined : category,
      source: source === "all" ? undefined : source,
      sort,
      limit: 200,
      offset: 0,
    });
    if (!mounted.current) return;
    setTools(res.tools ?? []);
    setToolsTotal(res.total ?? 0);
    setSelectedId((prev) => {
      const ids = (res.tools ?? []).map((t) => t.id);
      if (prev && ids.includes(prev)) return prev;
      return ids[0] ?? null;
    });
  }, [visual, effectiveQuery, category, source, sort]);

  const loadOverview = useCallback(async () => {
    if (visual) return;
    const res = await api.capabilitiesOverview(7);
    if (!mounted.current) return;
    setOverview(res.overview);
    setRecentCalls(res.overview.recent_calls ?? []);
    setOverviewStale(Boolean(res.overview.coverage?.receipts_stale));
    setMcpStale(Boolean(res.overview.coverage?.mcp_stale));
    setPluginsStale(Boolean(res.overview.coverage?.plugins_stale));
  }, [visual]);

  const loadDetail = useCallback(
    async (id: string) => {
      if (visual) {
        setDetail(TOOLS_V2_VISUAL_FIXTURE.detail);
        return;
      }
      const gen = ++selectGen.current;
      setDetailLoading(true);
      try {
        const res = await api.capabilityDetail(id, { receiptLimit: 40 });
        if (!mounted.current || gen !== selectGen.current) return;
        setDetail(res);
        const schema = res.capability.input_schema;
        const defaults: Record<string, unknown> = {};
        const props = (schema?.properties ?? {}) as Record<string, { default?: unknown }>;
        for (const [key, spec] of Object.entries(props)) {
          if (spec && "default" in spec) defaults[key] = spec.default;
        }
        setTestArgs(defaults);
        setTestResult(null);
      } catch (err) {
        if (!mounted.current || gen !== selectGen.current) return;
        toast(errorMessage(err));
      } finally {
        if (mounted.current && gen === selectGen.current) setDetailLoading(false);
      }
    },
    [visual, toast],
  );

  const load = useCallback(async () => {
    if (visual) {
      setOverview(TOOLS_V2_VISUAL_FIXTURE.overview);
      setTools(TOOLS_V2_VISUAL_FIXTURE.tools);
      setToolsTotal(TOOLS_V2_VISUAL_FIXTURE.tools.length);
      setRecentCalls(TOOLS_V2_VISUAL_FIXTURE.overview.recent_calls);
      setDetail(TOOLS_V2_VISUAL_FIXTURE.detail);
      setLoading(false);
      return;
    }
    if (refreshLock.current) return;
    refreshLock.current = true;
    setRefreshing(true);
    setLoadError(null);
    try {
      await Promise.all([loadOverview(), loadLibrary()]);
      setStale(false);
    } catch (err) {
      if (overview || tools.length) {
        setStale(true);
        toast(errorMessage(err));
      } else {
        setLoadError(errorMessage(err));
      }
    } finally {
      refreshLock.current = false;
      if (mounted.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, [visual, loadOverview, loadLibrary, overview, tools.length, toast]);

  useEffect(() => {
    mounted.current = true;
    void load();
    return () => {
      mounted.current = false;
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (visual) return;
    void loadLibrary().catch((err) => toast(errorMessage(err)));
  }, [effectiveQuery, category, source, sort, visual, loadLibrary, toast]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (visual) return;
    const tick = () => {
      if (document.hidden || refreshLock.current) return;
      void api
        .capabilitiesOverview(7)
        .then((res) => {
          if (!mounted.current) return;
          setRecentCalls(res.overview.recent_calls ?? []);
          setOverview((prev) =>
            prev
              ? {
                  ...prev,
                  ...res.overview,
                  // preserve last-known MCP/plugin panels if subsystem stale
                  mcp_servers:
                    res.overview.coverage?.mcp_stale && prev.mcp_servers?.length
                      ? prev.mcp_servers
                      : res.overview.mcp_servers,
                  plugins:
                    res.overview.coverage?.plugins_stale && prev.plugins?.length
                      ? prev.plugins
                      : res.overview.plugins,
                }
              : res.overview,
          );
          setOverviewStale(Boolean(res.overview.coverage?.receipts_stale));
          setMcpStale(Boolean(res.overview.coverage?.mcp_stale));
          setPluginsStale(Boolean(res.overview.coverage?.plugins_stale));
        })
        .catch(() => {
          /* keep last-known */
        });
    };
    pollRef.current = window.setInterval(tick, 12_000);
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current);
    };
  }, [visual]);

  const categories = useMemo(() => overview?.categories ?? [], [overview]);
  const selected = useMemo(
    () => tools.find((t) => t.id === selectedId) ?? null,
    [tools, selectedId],
  );

  const selectTool = useCallback((id: string) => {
    setSelectedId(id);
    setDetailTab("overview");
    setTestResult(null);
  }, []);

  const runTest = useCallback(async () => {
    if (!selectedId || !detail) return;
    if (detail.testability?.allowed === false) {
      toast(detail.testability.reason ?? "Test niet beschikbaar");
      return;
    }
    if (testing) return;
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.executeCapability(selectedId, testArgs, {
        requested_by: "tools-ui:operator",
        idempotency_key: newIdempotencyKey(),
      });
      setTestResult(JSON.stringify(res.result ?? res, null, 2));
      toast("Test voltooid");
      void loadOverview();
      void loadDetail(selectedId);
    } catch (err) {
      const msg = errorMessage(err);
      setTestResult(msg);
      if (err instanceof ApiError && err.status === 403) {
        toast("Goedkeuring vereist of test geblokkeerd");
      } else {
        toast(msg);
      }
    } finally {
      setTesting(false);
    }
  }, [selectedId, detail, testing, testArgs, toast, loadOverview, loadDetail]);

  const createCustomTool = useCallback(
    async (payload: {
      name: string;
      description?: string;
      wraps_capability_id: string;
      capability_id?: string;
    }) => {
      if (creating) return;
      setCreating(true);
      try {
        const res = await api.createCustomCapability(payload);
        toast("Custom tool aangemaakt");
        setNewToolOpen(false);
        await load();
        if (res.capability?.id) setSelectedId(res.capability.id);
      } catch (err) {
        toast(errorMessage(err));
      } finally {
        setCreating(false);
      }
    },
    [creating, toast, load],
  );

  const updateCustomTool = useCallback(
    async (payload: { name?: string; description?: string; enabled?: boolean; version?: string }) => {
      if (!selectedId) return;
      try {
        await api.updateCustomCapability(selectedId, payload);
        toast("Custom tool bijgewerkt");
        setEditOpen(false);
        await load();
        void loadDetail(selectedId);
      } catch (err) {
        toast(errorMessage(err));
      }
    },
    [selectedId, toast, load, loadDetail],
  );

  const deleteCustomTool = useCallback(async () => {
    if (!selectedId) return;
    if (!window.confirm(`Verwijder custom tool ${selectedId}?`)) return;
    try {
      await api.deleteCustomCapability(selectedId);
      toast("Custom tool verwijderd");
      await load();
    } catch (err) {
      toast(errorMessage(err));
    }
  }, [selectedId, toast, load]);

  const togglePlugin = useCallback(
    async (pluginId: string, enable: boolean) => {
      try {
        if (enable) await api.enablePlugin(pluginId);
        else await api.disablePlugin(pluginId);
        toast(enable ? "Plugin ingeschakeld" : "Plugin uitgeschakeld");
        await loadOverview();
      } catch (err) {
        toast(errorMessage(err));
      }
    },
    [toast, loadOverview],
  );

  const reconnectMcp = useCallback(
    async (serverId: string) => {
      try {
        await api.mcpConnectServer(serverId);
        await api.mcpRefreshTools(serverId);
        toast("MCP herverbonden");
        await load();
      } catch (err) {
        toast(errorMessage(err));
      }
    },
    [toast, load],
  );

  const createMcpServer = useCallback(
    async (payload: Record<string, unknown>) => {
      try {
        await api.mcpCreateServer(payload);
        toast("MCP server toegevoegd");
        setMcpAddOpen(false);
        await load();
      } catch (err) {
        toast(errorMessage(err));
      }
    },
    [toast, load],
  );

  const copyId = useCallback(
    async (id: string) => {
      try {
        await navigator.clipboard.writeText(id);
        toast("ID gekopieerd");
      } catch {
        toast(id);
      }
    },
    [toast],
  );

  return {
    visual,
    overview,
    tools,
    toolsTotal,
    selectedId,
    selected,
    detail,
    recentCalls,
    query,
    setQuery,
    topbarQuery,
    setTopbarQuery,
    category,
    setCategory,
    source,
    setSource,
    sort,
    setSort,
    detailTab,
    setDetailTab,
    loading,
    detailLoading,
    refreshing,
    loadError,
    stale,
    overviewStale,
    mcpStale,
    pluginsStale,
    categories,
    newToolOpen,
    setNewToolOpen,
    testOpen,
    setTestOpen,
    editOpen,
    setEditOpen,
    mcpAddOpen,
    setMcpAddOpen,
    historyOpen,
    setHistoryOpen,
    testing,
    testResult,
    testArgs,
    setTestArgs,
    creating,
    selectTool,
    load,
    runTest,
    createCustomTool,
    updateCustomTool,
    deleteCustomTool,
    togglePlugin,
    reconnectMcp,
    createMcpServer,
    copyId,
  };
}
