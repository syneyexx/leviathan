import type { RuntimeEvent, RuntimeEventLevel } from "../../types/api";

export type ConsoleSeverityChip = "all" | "info" | "success" | "warning" | "error";

export type ConsoleQuickFilter =
  | "errors"
  | "warnings"
  | "agenten"
  | "trading"
  | "datasets"
  | "mcp"
  | "tools"
  | "system"
  | "http"
  | "modules"
  | "workflows"
  | null;

export type ConsoleTimeRange = "1h" | "6h" | "24h" | "7d";

export const CONSOLE_TIME_RANGES: Array<{ id: ConsoleTimeRange; label: string; hours: number }> = [
  { id: "1h", label: "Laatste 1 uur", hours: 1 },
  { id: "6h", label: "Laatste 6 uur", hours: 6 },
  { id: "24h", label: "Laatste 24 uur", hours: 24 },
  { id: "7d", label: "Laatste 7 dagen", hours: 168 },
];

export function hoursForRange(range: ConsoleTimeRange): number {
  return CONSOLE_TIME_RANGES.find((r) => r.id === range)?.hours ?? 24;
}

export function formatConsoleTime(ms: number, withDate = false): string {
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "—";
  const pad = (n: number) => String(n).padStart(2, "0");
  const t = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  if (!withDate) return t;
  return `${pad(d.getDate())}-${pad(d.getMonth() + 1)} ${t}`;
}

export function normalizeSeverity(level: string): ConsoleSeverityChip | "debug" | "other" {
  const u = level.toUpperCase();
  if (u === "SUCCESS") return "success";
  if (u === "WARNING" || u === "WARN") return "warning";
  if (u === "ERROR" || u === "CRITICAL") return "error";
  if (u === "DEBUG") return "debug";
  if (u === "INFO") return "info";
  return "other";
}

export function severityTone(
  level: string,
): "info" | "success" | "warning" | "danger" | "muted" {
  const s = normalizeSeverity(level);
  if (s === "success") return "success";
  if (s === "warning") return "warning";
  if (s === "error") return "danger";
  if (s === "info") return "info";
  return "muted";
}

export function formatCompactCount(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${Math.round(n / 1000)}k`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(Math.round(n));
}

export function formatRate(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n >= 100) return String(Math.round(n));
  if (n >= 10) return n.toFixed(1);
  return n.toFixed(2);
}

/** Safe RegExp compile — returns null + reason on invalid/pathological patterns. */
export function compileSafeRegex(raw: string): { re: RegExp | null; error: string | null } {
  const text = raw.trim();
  if (!text) return { re: null, error: null };
  if (text.length > 120) return { re: null, error: "Regex te lang (max 120)" };
  // Reject nested quantifiers that commonly trigger catastrophic backtracking.
  if (
    /(\+|\*|\}|\*)\s*(\+|\*|\{)/.test(text) ||
    /\([^)]*[+*][^)]*\)[+*]/.test(text) ||
    /(\.\*){3,}/.test(text)
  ) {
    return { re: null, error: "Potentieel pathologische regex geweigerd" };
  }
  try {
    return { re: new RegExp(text, "i"), error: null };
  } catch (err) {
    return { re: null, error: err instanceof Error ? err.message : "Ongeldige regex" };
  }
}

export function eventMatchesQuickFilter(event: RuntimeEvent, filter: ConsoleQuickFilter): boolean {
  if (!filter) return true;
  const cat = (event.category || "").toLowerCase();
  const sub = (event.subsystem || "").toLowerCase();
  const src = (event.source || "").toLowerCase();
  const sev = normalizeSeverity(event.level);
  if (filter === "errors") return sev === "error";
  if (filter === "warnings") return sev === "warning";
  if (filter === "agenten") {
    return cat.includes("agent") || sub.includes("agent") || Boolean(event.actor);
  }
  if (filter === "trading") {
    return cat.includes("trad") || sub.includes("trad") || cat.includes("market");
  }
  if (filter === "datasets") {
    return cat.includes("dataset") || sub.includes("dataset") || Boolean(event.dataset_id);
  }
  if (filter === "mcp") {
    return cat === "mcp" || sub.includes("mcp") || Boolean(event.mcp_server_id);
  }
  if (filter === "tools") {
    return (
      cat.includes("tool") ||
      cat.includes("capability") ||
      Boolean(event.tool_id) ||
      Boolean(event.capability_id)
    );
  }
  if (filter === "system") {
    return cat === "system" || sub === "system" || src === "system" || cat === "console";
  }
  if (filter === "http") return cat === "http" || sub === "http";
  if (filter === "modules") {
    return cat === "module_manager" || cat.includes("module") || Boolean(event.module_id);
  }
  if (filter === "workflows") {
    return cat.includes("workflow") || Boolean(event.workflow_id);
  }
  return true;
}

export function eventSearchHaystack(event: RuntimeEvent): string {
  return [
    event.message,
    event.level,
    event.category,
    event.subsystem,
    event.name,
    event.source,
    event.correlation_id ?? "",
    event.module_id ?? "",
    event.mcp_server_id ?? "",
  ]
    .join(" ")
    .toLowerCase();
}

export function displayLevel(level: RuntimeEventLevel | string): string {
  const u = String(level || "INFO").toUpperCase();
  if (u === "WARN") return "WARNING";
  if (u === "CRITICAL") return "ERROR";
  return u;
}

export function serviceStatusTone(
  status: string,
  measured: boolean,
): "success" | "warning" | "danger" | "muted" {
  const s = status.toLowerCase();
  if (!measured || s === "unmeasured" || s === "unknown") return "muted";
  if (s === "operational") return "success";
  if (s === "degraded" || s === "experimental") return "warning";
  if (s === "unavailable" || s === "fixture") return "danger";
  if (s === "unconfigured") return "muted";
  return "muted";
}
