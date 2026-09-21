"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import { hadesApi, type HadesPlugin, type PluginEvent, type PluginToolCall } from "@/lib/hades-api";

const PLUGINS_KEY = "hades:plugins";
const MARKETPLACE_KEY = "hades:plugins:marketplace";

export type PluginUiStatus = "active" | "inactive" | "update" | "broken" | "blocked";

export type PluginCardView = {
  id: string;
  name: string;
  version: string;
  description: string;
  tags: string[];
  permissions: number;
  status: PluginUiStatus;
  statusLabel: string;
  enabled: boolean;
  trust: string;
  health: string;
  pluginStatus: string;
  autonomous: boolean;
  failureState: string | null;
  category: string;
  labels: string[];
  toolCount: number;
  lastError: string | null;
  raw: HadesPlugin;
};

function mapPluginCard(plugin: HadesPlugin): PluginCardView {
  const failure = plugin.failure_state ? String(plugin.failure_state) : null;
  const ready = String(plugin.status || "").toLowerCase() === "ready" || String(plugin.health || "").toLowerCase() === "ok";
  let status: PluginUiStatus = "inactive";
  let statusLabel = "Uitgeschakeld";
  if (failure || String(plugin.health || "").toLowerCase() === "error" || String(plugin.status || "").toLowerCase() === "error") {
    status = "broken";
    statusLabel = "Defect";
  } else if (!plugin.enabled && ready) {
    status = "inactive";
    statusLabel = "Ready · niet enabled";
  } else if (plugin.enabled && ready) {
    status = "active";
    statusLabel = "Enabled";
  } else if (!ready) {
    status = "blocked";
    statusLabel = plugin.status || "Niet ready";
  }
  return {
    id: plugin.id,
    name: plugin.name || plugin.id,
    version: plugin.version ? (plugin.version.startsWith("v") ? plugin.version : `v${plugin.version}`) : "—",
    description: plugin.description || "Geen beschrijving.",
    tags: (plugin.labels?.length ? plugin.labels : [plugin.category].filter(Boolean)).slice(0, 6),
    permissions: Array.isArray(plugin.permissions) ? plugin.permissions.length : 0,
    status,
    statusLabel,
    enabled: Boolean(plugin.enabled),
    trust: plugin.trust || "untrusted",
    health: plugin.health || "unknown",
    pluginStatus: plugin.status || "unknown",
    autonomous: Boolean(plugin.autonomous),
    failureState: failure,
    category: plugin.category || "general",
    labels: plugin.labels || [],
    toolCount: plugin.tools?.length ?? 0,
    lastError: plugin.last_error,
    raw: plugin,
  };
}

export function useHadesPlugins(options?: { includeMarketplace?: boolean }) {
  const pluginsQuery = useHadesQuery(
    PLUGINS_KEY,
    async () => {
      const res = await hadesApi.plugins();
      return res.plugins || [];
    },
    { staleTime: 5_000, refetchInterval: 15_000 },
  );

  const marketplaceQuery = useHadesQuery(
    MARKETPLACE_KEY,
    async () => {
      const res = await hadesApi.pluginMarketplace();
      return res;
    },
    { enabled: options?.includeMarketplace !== false, staleTime: 30_000 },
  );

  const plugins = pluginsQuery.data ?? [];
  const cards = useMemo(() => plugins.map(mapPluginCard), [plugins]);

  const stats = useMemo(() => {
    const installed = cards.length;
    const enabled = cards.filter((p) => p.enabled).length;
    const broken = cards.filter((p) => p.status === "broken").length;
    const readyDisabled = cards.filter((p) => !p.enabled && p.status === "inactive").length;
    const marketplaceCount = marketplaceQuery.data?.count ?? marketplaceQuery.data?.items?.length ?? null;
    const healthy = broken === 0 && installed > 0;
    return {
      installed,
      enabled,
      broken,
      readyDisabled,
      marketplaceCount,
      runtimeLabel: pluginsQuery.error ? "Onbekend" : healthy ? "Gezond" : installed === 0 ? "Leeg" : "Aandacht vereist",
      runtimeHint: pluginsQuery.error
        ? pluginsQuery.error.message
        : broken
          ? `${broken} defect`
          : readyDisabled
            ? `${readyDisabled} ready maar niet enabled`
            : enabled
              ? `${enabled} enabled`
              : "Geen enabled plugins",
    };
  }, [cards, marketplaceQuery.data, pluginsQuery.error]);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(PLUGINS_KEY);
    invalidateHadesQuery(MARKETPLACE_KEY);
    await Promise.all([pluginsQuery.refetch(), marketplaceQuery.refetch()]);
  }, [pluginsQuery, marketplaceQuery]);

  const setEnabled = useCallback(
    async (id: string, enabled: boolean) => {
      const updated = await hadesApi.setPluginState(id, enabled);
      invalidateHadesQuery(PLUGINS_KEY);
      await pluginsQuery.refetch();
      return updated;
    },
    [pluginsQuery],
  );

  const setTrust = useCallback(
    async (id: string, trust: "untrusted" | "manual" | "verified" | "trusted") => {
      const updated = await hadesApi.setPluginTrust(id, trust);
      invalidateHadesQuery(PLUGINS_KEY);
      await pluginsQuery.refetch();
      return updated;
    },
    [pluginsQuery],
  );

  const repair = useCallback(
    async (id: string) => {
      const result = await hadesApi.repairPlugin(id);
      invalidateHadesQuery(PLUGINS_KEY);
      await pluginsQuery.refetch();
      return result;
    },
    [pluginsQuery],
  );

  const update = useCallback(
    async (id: string) => {
      const result = await hadesApi.updatePlugin(id);
      invalidateHadesQuery(PLUGINS_KEY);
      await pluginsQuery.refetch();
      return result;
    },
    [pluginsQuery],
  );

  const remove = useCallback(
    async (id: string) => {
      await hadesApi.deletePlugin(id);
      invalidateHadesQuery(PLUGINS_KEY);
      await pluginsQuery.refetch();
    },
    [pluginsQuery],
  );

  const installMarketplace = useCallback(
    async (pluginId: string) => {
      const result = await hadesApi.installMarketplacePlugin(pluginId, true);
      invalidateHadesQuery(PLUGINS_KEY);
      invalidateHadesQuery(MARKETPLACE_KEY);
      await refresh();
      return result;
    },
    [refresh],
  );

  const loadEvents = useCallback(async (id: string): Promise<PluginEvent[]> => hadesApi.pluginEvents(id), []);
  const loadToolCalls = useCallback(async (id: string, limit = 50): Promise<PluginToolCall[]> => hadesApi.pluginToolCalls(id, limit), []);

  return {
    plugins,
    cards,
    stats,
    marketplace: marketplaceQuery.data,
    loading: pluginsQuery.status === "loading" && !pluginsQuery.data,
    error: pluginsQuery.error,
    marketplaceError: marketplaceQuery.error,
    refresh,
    setEnabled,
    setTrust,
    repair,
    update,
    remove,
    installMarketplace,
    loadEvents,
    loadToolCalls,
    importPluginZip: hadesApi.importPluginZip.bind(hadesApi),
    importPluginFolder: hadesApi.importPluginFolder.bind(hadesApi),
    pickPluginFolder: hadesApi.pickPluginFolder.bind(hadesApi),
    importPlugin: hadesApi.importPlugin.bind(hadesApi),
  };
}
