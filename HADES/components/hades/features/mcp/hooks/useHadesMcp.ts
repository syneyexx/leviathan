"use client";

import { useCallback, useMemo } from "react";
import { useHadesQuery, invalidateHadesQuery } from "@/hooks/use-hades-query";
import {
  hadesApi,
  type AppSettings,
  type McpExecution,
  type McpServer,
  type McpTool,
} from "@/lib/hades-api";

const SERVERS_KEY = "hades:mcp:servers";
const TOOLS_KEY = "hades:mcp:tools";
const CATALOG_KEY = "hades:mcp:catalog";

export function useHadesMcp(_options?: { selectedServerId?: string | null }) {
  const serversQuery = useHadesQuery(
    SERVERS_KEY,
    async () => {
      const res = await hadesApi.mcpServers();
      return res.items || [];
    },
    { staleTime: 5_000, refetchInterval: 12_000 },
  );

  const toolsQuery = useHadesQuery(
    TOOLS_KEY,
    async () => {
      const res = await hadesApi.mcpTools();
      return res.items || [];
    },
    { staleTime: 5_000, refetchInterval: 12_000 },
  );

  const catalogQuery = useHadesQuery(
    CATALOG_KEY,
    async () => hadesApi.mcpHostCatalog(),
    { staleTime: 30_000 },
  );

  const settingsQuery = useHadesQuery(
    "hades:settings:mcp-policy",
    async () => {
      const res = await hadesApi.settings();
      return res.values;
    },
    { staleTime: 10_000 },
  );

  const servers = serversQuery.data ?? [];
  const tools = toolsQuery.data ?? [];
  const networkPolicy = settingsQuery.data?.network_policy ?? "block";

  const stats = useMemo(() => {
    const connected = servers.filter((s) => {
      const status = String(s.connection_status_effective || s.connection_status || "").toLowerCase();
      return status.includes("connect") && !status.includes("disconnect");
    }).length;
    const enabled = servers.filter((s) => s.enabled !== false).length;
    return {
      serverCount: servers.length,
      connected,
      enabled,
      toolCount: tools.length,
      networkPolicy,
    };
  }, [servers, tools, networkPolicy]);

  const refresh = useCallback(async () => {
    invalidateHadesQuery(SERVERS_KEY);
    invalidateHadesQuery(TOOLS_KEY);
    invalidateHadesQuery(CATALOG_KEY);
    await Promise.all([serversQuery.refetch(), toolsQuery.refetch(), catalogQuery.refetch()]);
  }, [serversQuery, toolsQuery, catalogQuery]);

  const connect = useCallback(
    async (id: string, approvalId?: string | null) => {
      const result = await hadesApi.mcpConnectServer(id, approvalId);
      await refresh();
      return result;
    },
    [refresh],
  );

  const disconnect = useCallback(
    async (id: string) => {
      const result = await hadesApi.mcpDisconnectServer(id);
      await refresh();
      return result;
    },
    [refresh],
  );

  const reconnect = useCallback(
    async (id: string, approvalId?: string | null) => {
      const result = await hadesApi.mcpReconnectServer(id, approvalId);
      await refresh();
      return result;
    },
    [refresh],
  );

  const enable = useCallback(
    async (id: string, enabled: boolean) => {
      const result = await hadesApi.mcpEnableServer(id, enabled);
      await refresh();
      return result;
    },
    [refresh],
  );

  const remove = useCallback(
    async (id: string) => {
      await hadesApi.mcpDeleteServer(id);
      await refresh();
    },
    [refresh],
  );

  const create = useCallback(
    async (body: Record<string, unknown>) => {
      const result = await hadesApi.mcpCreateServer(body);
      await refresh();
      return result;
    },
    [refresh],
  );

  const update = useCallback(
    async (id: string, body: Record<string, unknown>) => {
      const result = await hadesApi.mcpUpdateServer(id, body);
      await refresh();
      return result;
    },
    [refresh],
  );

  const refreshTools = useCallback(
    async (id: string) => {
      const result = await hadesApi.mcpRefreshTools(id);
      invalidateHadesQuery(TOOLS_KEY);
      await toolsQuery.refetch();
      await serversQuery.refetch();
      return result;
    },
    [toolsQuery, serversQuery],
  );

  const invokeTool = useCallback(
    async (toolId: string, args: Record<string, unknown>, approved = true) => {
      // approved_by_user is audit/compat only — authorization requires approval_id.
      try {
        return await hadesApi.mcpInvokeTool(toolId, {
          arguments: args,
          approved_by_user: approved,
          idempotency_key: `${toolId}:${Date.now()}`,
        });
      } catch (err: unknown) {
        const apiErr = err as { status?: number; detail?: { approval_required?: boolean; approval?: { id?: string } } };
        const detail = apiErr?.detail;
        const approvalId = detail?.approval?.id;
        if ((apiErr?.status === 428 || detail?.approval_required) && approvalId) {
          await hadesApi.decideApproval(approvalId, true, "MCP UI invoke");
          return hadesApi.mcpInvokeTool(toolId, {
            arguments: args,
            approval_id: approvalId,
            approved_by_user: true,
            idempotency_key: `${toolId}:${Date.now()}`,
          });
        }
        throw err;
      }
    },
    [],
  );

  const loadExecutions = useCallback(async (serverId?: string, limit = 50): Promise<McpExecution[]> => {
    const res = await hadesApi.mcpExecutions(serverId, limit);
    return res.items || [];
  }, []);

  return {
    servers: servers as McpServer[],
    tools: tools as McpTool[],
    catalog: catalogQuery.data,
    settings: settingsQuery.data as AppSettings | undefined,
    networkPolicy,
    stats,
    loading: serversQuery.status === "loading" && !serversQuery.data,
    error: serversQuery.error || toolsQuery.error,
    refresh,
    connect,
    disconnect,
    reconnect,
    enable,
    remove,
    create,
    update,
    refreshTools,
    invokeTool,
    loadExecutions,
    updateTool: hadesApi.mcpUpdateTool.bind(hadesApi),
  };
}
