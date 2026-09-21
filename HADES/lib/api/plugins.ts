/** Plugin Manager HTTP types + client methods (extracted from hades-api barrel). */

export type ApiRequest = <T>(path: string, init?: RequestInit) => Promise<T>;

export type PluginApiErrorCtor = new (message: string, status?: number, detail?: unknown) => Error;

export type PluginApiDeps = {
  request: ApiRequest;
  ApiError: PluginApiErrorCtor;
};

export type PluginTool = {
  id: string;
  plugin_id: string;
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  command: string | string[];
  metadata: Record<string, unknown>;
  enabled: boolean;
};
export type HadesPlugin = {
  id: string;
  name: string;
  version: string;
  description: string;
  source: string;
  source_ref: string;
  local_path: string;
  plugin_type: string;
  runtime_type: string;
  entrypoint: string;
  manifest: Record<string, unknown>;
  permissions: string[];
  status: string;
  enabled: boolean;
  health: string;
  trust: string;
  isolation?: string;
  failure_state?: string | null;
  capabilities?: Record<string, unknown>;
  last_error: string | null;
  created_at: string;
  updated_at: string;
  tools: PluginTool[];
  category: string;
  labels: string[];
  autonomous: boolean;
  dependency_call: PluginToolCall | null;
};
export type PluginEvent = { id: number; plugin_id: string; level: string; message: string; created_at: string };
export type PluginTimelineItem = {
  kind: string;
  id: string;
  status?: string | null;
  message?: string | null;
  created_at?: string | number | null;
  tool_name?: string;
  invocation_type?: string;
  duration_ms?: number | null;
  source?: string;
  detail?: Record<string, unknown>;
};
export type PluginToolCall = {
  id: string;
  plugin_id: string;
  tool_name: string;
  input: Record<string, unknown>;
  output: string | null;
  stdout: string;
  stderr: string;
  status: string;
  error: string | null;
  exit_code: number | null;
  duration_ms: number | null;
  invocation_type: string;
  approved_by_user: boolean;
  metadata: Record<string, unknown>;
  started_at: string;
  finished_at: string | null;
  timestamp: string;
};
export type PluginToolLogEntry = {
  call_id: string | null;
  plugin_id: string;
  tool_name: string;
  status: string;
  error: string | null;
  exit_code?: number | null;
  invocation_type?: string;
};

export function createPluginApi({ request, ApiError }: PluginApiDeps) {
  return {
  pluginMarketplace: () =>
    request<{ items: Array<Record<string, unknown>>; count: number; plugins_root?: string; note?: string }>("/plugins/marketplace"),
  installMarketplacePlugin: (pluginId: string, install_dependencies = true) =>
    request<Record<string, unknown>>(
      `/plugins/marketplace/${encodeURIComponent(pluginId)}/install?install_dependencies=${install_dependencies ? "true" : "false"}`,
      { method: "POST" },
    ),
  plugins: () => request<{ plugins: HadesPlugin[] }>("/plugins"),
  pickPluginFolder: () => request<{ path: string | null; cancelled: boolean }>("/plugins/pick-folder", { method: "POST" }),
  importPlugin: (values: { source_type: "folder" | "git"; path_or_url: string; ref?: string; install_dependencies: boolean; approved_network: boolean; approved_file_read: boolean; approved_file_write: boolean }) => request<{ plugin: HadesPlugin; tools: PluginTool[]; dependencies: Record<string, unknown>; package_path: string }>("/plugins/import", { method: "POST", body: JSON.stringify(values) }),
  importPluginFolder: (files: File[], installDependencies: boolean, approvedFileWrite: boolean, approvedNetwork: boolean) => {
    const skip = new Set([".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".turbo", ".next", "target", ".tox"]);
    const body = new FormData();
    let appended = 0;
    for (const file of files) {
      const relative = ((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name).replace(/\\/g, "/");
      if (!relative.trim() || relative.split("/").some((part) => skip.has(part))) continue;
      body.append("files", file, relative);
      appended += 1;
    }
    if (!appended) throw new ApiError("De geselecteerde map bevat geen bruikbare bestanden.");
    body.append("install_dependencies", String(installDependencies));
    body.append("approved_file_write", String(approvedFileWrite));
    body.append("approved_file_read", "true");
    body.append("approved_network", String(approvedNetwork));
    return request<{ plugin: HadesPlugin; tools: PluginTool[]; dependencies: Record<string, unknown>; package_path: string }>("/plugins/import-folder", { method: "POST", body });
  },
  importPluginZip: (file: File, installDependencies: boolean, approvedFileWrite: boolean, approvedNetwork: boolean) => {
    const body = new FormData();
    body.append("file", file);
    body.append("install_dependencies", String(installDependencies));
    body.append("approved_file_write", String(approvedFileWrite));
    body.append("approved_network", String(approvedNetwork));
    return request<{
      plugin: HadesPlugin;
      tools: PluginTool[];
      dependencies: Record<string, unknown>;
      package_path: string;
      warnings?: string[];
      dependencies_skipped?: boolean;
    }>("/plugins/import-zip", { method: "POST", body });
  },
  setPluginState: (id: string, enabled: boolean) => request<HadesPlugin>(`/plugins/${id}/state`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  setPluginTrust: (id: string, trust: "untrusted" | "manual" | "verified" | "trusted") =>
    request<HadesPlugin>(`/plugins/${id}/trust`, { method: "PUT", body: JSON.stringify({ trust }) }),
  expandPluginMcp: (id: string) => request<{ plugin: HadesPlugin; expansion: Record<string, unknown>; tools: PluginTool[] }>(`/plugins/${id}/expand-mcp`, { method: "POST" }),
  pluginTimeline: (id: string, limit = 200) =>
    request<{ plugin_id: string; trust: string; isolation?: string; failure_state?: string | null; capabilities?: Record<string, unknown>; items: PluginTimelineItem[]; count: number }>(
      `/plugins/${id}/timeline?limit=${limit}`,
    ),
  batchPluginApprovals: (request_ids: string[], approve = true, note = "") =>
    request<{ results: Array<Record<string, unknown>>; approved: boolean; count: number }>("/plugins/approvals/batch", {
      method: "POST",
      body: JSON.stringify({ request_ids, approve, note }),
    }),
  repairPlugin: (id: string) => request<{ plugin: HadesPlugin; dependencies: Record<string, unknown> }>(`/plugins/${id}/repair`, { method: "POST", body: JSON.stringify({ approved_network: true, approved_file_write: true }) }),
  updatePlugin: (id: string) => request<{ plugin: HadesPlugin; tools: PluginTool[]; dependencies: Record<string, unknown>; package_path: string }>(`/plugins/${id}/update`, { method: "POST", body: JSON.stringify({ approved_network: true, approved_file_write: true }) }),
  rollbackPlugin: (id: string) => request<{ plugin: HadesPlugin; tools: PluginTool[]; dependencies: Record<string, unknown>; package_path: string }>(`/plugins/${id}/rollback`, { method: "POST", body: JSON.stringify({ approved_file_write: true }) }),
  deletePlugin: (id: string) => request<void>(`/plugins/${id}`, { method: "DELETE", body: JSON.stringify({ approved_file_write: true }) }),
  pluginEvents: (id: string) => request<PluginEvent[]>(`/plugins/${id}/events`),
  pluginToolCalls: (id: string, limit = 100) => request<PluginToolCall[]>(`/plugins/${id}/tool-calls?limit=${limit}`),
  invokePlugin: (id: string, tool_name: string, input: Record<string, unknown>, timeout_seconds = 120, approvals?: { approved_network?: boolean; approved_file_read?: boolean; approved_file_write?: boolean; approved_subprocess?: boolean }) =>
    request<PluginToolCall>(`/plugins/${id}/invoke`, {
      method: "POST",
      body: JSON.stringify({
        tool_name,
        input,
        timeout_seconds,
        approved_by_user: true,
        approved_network: Boolean(approvals?.approved_network),
        approved_file_read: Boolean(approvals?.approved_file_read),
        approved_file_write: Boolean(approvals?.approved_file_write),
        approved_subprocess: Boolean(approvals?.approved_subprocess),
      }),
    }),
  capabilityIntelOverview: () => request<{ registry: Record<string, unknown>; native_provider: string }>("/capability-intel/overview"),
  capabilityIntelPluginGroups: (pluginId: string) =>
    request<{ plugin_id: string; groups: Record<string, Array<Record<string, unknown>>> }>(
      `/capability-intel/plugins/${encodeURIComponent(pluginId)}/groups`,
    ),
  capabilityIntelRoute: (query: string, limit = 8) =>
    request<{ plan: Record<string, unknown>; routing: Record<string, unknown> }>("/capability-intel/route", {
      method: "POST",
      body: JSON.stringify({ query, limit }),
    }),
  } as const;
}
