import type { AgentHealth, AgentStatus, HadesAgent } from "@/lib/hades-api";

export type AgentSortKey = "name" | "status" | "last_activity" | "tokens" | "cost" | "runs" | "failures";

export function formatMetric(value: number | null | undefined, opts?: { compact?: boolean; digits?: number }): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (opts?.compact) {
    if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
    if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}K`;
  }
  const digits = opts?.digits ?? 0;
  return value.toLocaleString("nl-NL", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatCost(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `€${value.toFixed(4).replace(".", ",")}`;
}

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}u`;
}

export function statusTone(status: AgentStatus | string | undefined): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (status) {
    case "running":
    case "busy":
      return "info";
    case "idle":
      return "success";
    case "error":
      return "danger";
    case "disabled":
    case "unavailable":
    default:
      return "neutral";
  }
}

export function healthTone(health: AgentHealth | string | undefined): "success" | "warning" | "danger" | "info" | "neutral" {
  switch (health) {
    case "healthy":
      return "success";
    case "degraded":
      return "warning";
    case "error":
      return "danger";
    case "offline":
    default:
      return "neutral";
  }
}

export function filterAgents(
  agents: HadesAgent[],
  opts: {
    query: string;
    status: string;
    role: string;
    provider: string;
    model: string;
    activeOnly: boolean;
    errorOnly: boolean;
  },
): HadesAgent[] {
  const needle = opts.query.trim().toLowerCase();
  return agents.filter((agent) => {
    if (opts.activeOnly && !agent.enabled) return false;
    if (opts.errorOnly && agent.status !== "error" && agent.health !== "error") return false;
    if (opts.status !== "all" && agent.status !== opts.status) return false;
    if (opts.role !== "all" && agent.role !== opts.role) return false;
    if (opts.provider !== "all" && (agent.provider || "") !== opts.provider) return false;
    if (opts.model !== "all" && (agent.model || "") !== opts.model) return false;
    if (!needle) return true;
    const haystack = [
      agent.name,
      agent.id,
      agent.role,
      agent.description,
      agent.status,
      agent.provider,
      agent.model,
      agent.current_task?.task_title,
      agent.current_task?.step_title,
      agent.last_error,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(needle);
  });
}

export function sortAgents(agents: HadesAgent[], key: AgentSortKey, direction: "asc" | "desc"): HadesAgent[] {
  const factor = direction === "asc" ? 1 : -1;
  const ranked = [...agents];
  ranked.sort((left, right) => {
    const cmp = (() => {
      switch (key) {
        case "status":
          return String(left.status || "").localeCompare(String(right.status || ""), "nl");
        case "last_activity":
          return String(left.last_activity_at || "").localeCompare(String(right.last_activity_at || ""));
        case "tokens":
          return (left.usage?.total_tokens ?? -1) - (right.usage?.total_tokens ?? -1);
        case "cost":
          return (left.usage?.cost ?? -1) - (right.usage?.cost ?? -1);
        case "runs":
          return (left.metrics?.runs ?? 0) - (right.metrics?.runs ?? 0);
        case "failures":
          return (left.metrics?.failed_runs ?? 0) - (right.metrics?.failed_runs ?? 0);
        case "name":
        default:
          return String(left.name || left.id).localeCompare(String(right.name || right.id), "nl");
      }
    })();
    return cmp * factor;
  });
  return ranked;
}
