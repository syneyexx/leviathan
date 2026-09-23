import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { pluginRuntimeHeroes } from "../assets/pluginRuntimeAssets";
import { api, ApiError } from "../api/client";
import { AppShell } from "../layouts/AppShell";
import { useAppToast } from "../state/useAppToast";
import type { McpCallRecord, McpServerPublic, McpToolRecord } from "../types/api";
import { Bar, Panel, Pill, PrHero, Spark, Toggle } from "./plugin-runtime/shared";
import type { PrTone } from "./plugin-runtime/mocks";

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

function errorMessage(err: unknown, fallback = "Request failed"): string {
  if (err instanceof ApiError) return err.message || fallback;
  if (err instanceof Error) return err.message || fallback;
  return fallback;
}

function StatusDot({ tone }: { tone: PrTone }) {
  return <span className={`lv-pr-mcp-dot is-${tone}`} aria-hidden="true" />;
}

function IconBtn({
  label,
  onClick,
  children,
  disabled,
}: {
  label: string;
  onClick: () => void;
  children: ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="lv-pr-mcp-icon-btn"
      aria-label={label}
      title={label}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function serverIconKey(server: McpServerPublic): string {
  const hay = `${server.source_key} ${server.display_name} ${server.server_id}`.toLowerCase();
  for (const key of Object.keys(SERVER_ICONS)) {
    if (hay.includes(key)) return key;
  }
  return "docs";
}

function runtimeState(server: McpServerPublic): string {
  return (server.runtime?.state ?? (server.enabled ? "DISCONNECTED" : "DISABLED")).toUpperCase();
}

function statusTone(state: string): PrTone {
  if (state === "READY" || state === "BUSY") return "ok";
  if (state === "ERROR" || state === "CIRCUIT_OPEN" || state === "UNRESPONSIVE") return "err";
  if (state === "DEGRADED" || state === "CONNECTING" || state === "RESTARTING") return "warn";
  if (state === "DISABLED") return "muted";
  return "cyan";
}

function statusLabel(state: string): string {
  if (state === "READY" || state === "BUSY") return "Verbonden";
  if (state === "ERROR" || state === "CIRCUIT_OPEN" || state === "UNRESPONSIVE") return "Fout";
  if (state === "DEGRADED") return "Belast";
  if (state === "CONNECTING" || state === "RESTARTING") return "Bezig";
  if (state === "DISABLED") return "Uit";
  if (state === "DISCONNECTED") return "Losgekoppeld";
  return state;
}

function callTone(status: string): PrTone {
  const s = status.toUpperCase();
  if (s === "COMPLETED") return "ok";
  if (s === "FAILED" || s === "TIMEOUT" || s === "REJECTED" || s === "CANCELLED") return "err";
  return "warn";
}

function formatTs(value: string | null | undefined): string {
  if (!value) return "—";
  try {
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString();
  } catch {
    return value;
  }
}

function formatDuration(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function relativeTime(value: string | null | undefined): string {
  if (!value) return "—";
  const t = Date.parse(value);
  if (!Number.isFinite(t)) return value;
  const delta = Math.max(0, Date.now() - t);
  if (delta < 60_000) return `${Math.round(delta / 1000)}s geleden`;
  if (delta < 3_600_000) return `${Math.round(delta / 60_000)}m geleden`;
  if (delta < 86_400_000) return `${Math.round(delta / 3_600_000)}u geleden`;
  return formatTs(value);
}

/** Secret refs are reference names — never treat redacted payloads as displayable values. */
function formatSecretRef(value: string | null | undefined): string {
  if (value == null || value === "") return "—";
  if (/\*{2,}|redacted|••••|\[secret\]/i.test(value)) return "••••";
  return value;
}

function tryParseArgs(raw: string): { ok: true; value: Record<string, unknown> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Arguments must be a JSON object" };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { ok: false, error: "Invalid JSON arguments" };
  }
}

function tryParseStringMap(raw: string): { ok: true; value: Record<string, string> } | { ok: false; error: string } {
  const trimmed = raw.trim();
  if (!trimmed) return { ok: true, value: {} };
  try {
    const parsed = JSON.parse(trimmed) as unknown;
    if (parsed == null || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { ok: false, error: "Must be a JSON object of string → string refs" };
    }
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof v !== "string") {
        return { ok: false, error: "Secret refs must be string reference names, not secret values" };
      }
      out[k] = v;
    }
    return { ok: true, value: out };
  } catch {
    return { ok: false, error: "Invalid JSON for secret refs" };
  }
}

const EMPTY_CREATE = {
  display_name: "",
  transport: "stdio",
  command: "",
  args: "",
  url: "",
  trust: "untrusted",
  requested_isolation: "subprocess",
  enabled: false,
  eager_connect: false,
  secret_refs: "",
};

export function McpPage() {
  const toast = useAppToast();
  const [servers, setServers] = useState<McpServerPublic[]>([]);
  const [tools, setTools] = useState<McpToolRecord[]>([]);
  const [calls, setCalls] = useState<McpCallRecord[]>([]);
  const [featureEnabled, setFeatureEnabled] = useState(true);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [transportFilter, setTransportFilter] = useState("all");

  const [showCreate, setShowCreate] = useState(false);
  const [createForm, setCreateForm] = useState(EMPTY_CREATE);
  const [creating, setCreating] = useState(false);

  const [invokeCapabilityId, setInvokeCapabilityId] = useState("");
  const [invokeArgs, setInvokeArgs] = useState("{}");
  const [invoking, setInvoking] = useState(false);
  const [invokeResult, setInvokeResult] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const [serversRes, toolsRes, callsRes] = await Promise.all([
        api.mcpServers(),
        api.mcpTools().catch(() => ({ tools: [] as McpToolRecord[] })),
        api.mcpCalls(100).catch(() => ({ calls: [] as McpCallRecord[] })),
      ]);
      setServers(serversRes.servers ?? []);
      setFeatureEnabled(serversRes.feature_enabled !== false);
      setTools(toolsRes.tools ?? []);
      setCalls(callsRes.calls ?? []);
      setSelectedId((prev) => {
        const ids = (serversRes.servers ?? []).map((s) => s.server_id);
        if (prev && ids.includes(prev)) return prev;
        return ids[0] ?? null;
      });
      setInvokeCapabilityId((prev) => {
        const ids = (toolsRes.tools ?? []).map((t) => t.capability_id);
        if (prev && ids.includes(prev)) return prev;
        return ids[0] ?? "";
      });
    } catch (err) {
      setLoadError(errorMessage(err, "Failed to load MCP data"));
      setServers([]);
      setTools([]);
      setCalls([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = useMemo(
    () => servers.find((s) => s.server_id === selectedId) ?? null,
    [servers, selectedId],
  );

  const filteredServers = useMemo(() => {
    const q = query.trim().toLowerCase();
    return servers.filter((s) => {
      const state = runtimeState(s);
      const label = statusLabel(state);
      if (statusFilter === "connected" && !(state === "READY" || state === "BUSY")) return false;
      if (statusFilter === "error" && !(state === "ERROR" || state === "CIRCUIT_OPEN" || state === "UNRESPONSIVE")) {
        return false;
      }
      if (statusFilter === "disconnected" && state !== "DISCONNECTED" && state !== "DISABLED") return false;
      if (transportFilter !== "all" && s.transport !== transportFilter) return false;
      if (!q) return true;
      const err = s.runtime?.last_error_message ?? "";
      return `${s.display_name} ${s.server_id} ${s.transport} ${s.requested_isolation} ${label} ${err}`
        .toLowerCase()
        .includes(q);
    });
  }, [servers, query, statusFilter, transportFilter]);

  const kpis = useMemo(() => {
    const total = servers.length;
    const connected = servers.filter((s) => {
      const st = runtimeState(s);
      return st === "READY" || st === "BUSY";
    }).length;
    const enabled = servers.filter((s) => s.enabled).length;
    const availableTools = tools.filter((t) => t.availability === "available").length;
    const unavailable = tools.filter((t) => t.availability !== "available").length;
    const failedCalls = calls.filter((c) => {
      const st = (c.status ?? "").toUpperCase();
      return st === "FAILED" || st === "TIMEOUT" || st === "REJECTED";
    }).length;
    const completed = calls.filter((c) => (c.status ?? "").toUpperCase() === "COMPLETED").length;
    const withDuration = calls.filter((c) => c.duration_ms != null && Number.isFinite(c.duration_ms));
    const avgLatency =
      withDuration.length > 0
        ? Math.round(withDuration.reduce((sum, c) => sum + Number(c.duration_ms), 0) / withDuration.length)
        : null;
    const errPct = calls.length ? ((failedCalls / calls.length) * 100).toFixed(1) : "0.0";
    const connectPct = total ? Math.round((connected / total) * 100) : 0;

    return [
      { id: "servers", label: "Totaal servers", value: String(total), spark: undefined as number[] | undefined },
      {
        id: "connected",
        label: "Verbonden servers",
        value: String(connected),
        sub: total ? `${connectPct}%` : undefined,
        pct: total ? connectPct : undefined,
        barTone: "ok" as const,
      },
      { id: "tools", label: "Ontdekte tools", value: String(tools.length) },
      { id: "sessions", label: "Ingeschakeld", value: String(enabled) },
      { id: "throughput", label: "Recente calls", value: String(calls.length), sub: "laatste 100" },
      {
        id: "approval",
        label: "Unavailable tools",
        value: String(unavailable),
        warn: unavailable > 0,
      },
      {
        id: "error",
        label: "Foutpercentage",
        value: `${errPct}%`,
        warn: failedCalls > 0,
      },
      {
        id: "latency",
        label: "Gem. latentie",
        value: avgLatency == null ? "—" : `${avgLatency} ms`,
      },
      {
        id: "tools",
        label: "Available tools",
        value: String(availableTools),
        hide: true,
      },
      {
        id: "throughput",
        label: "Completed",
        value: String(completed),
        hide: true,
      },
    ].filter((k) => !("hide" in k && k.hide));
  }, [servers, tools, calls]);

  const authSummary = useMemo(() => {
    const available = tools.filter((t) => t.availability === "available").length;
    const disabled = tools.filter((t) => t.availability === "disabled").length;
    const unavailable = tools.filter((t) => t.availability === "unavailable").length;
    return [
      { id: "discovered", label: "Ontdekte tools", value: String(tools.length) },
      { id: "authorized", label: "Available", value: String(available), tone: "ok" as PrTone },
      { id: "queued", label: "Disabled", value: String(disabled), tone: disabled ? ("warn" as PrTone) : undefined },
      { id: "blocked", label: "Unavailable", value: String(unavailable), tone: unavailable ? ("err" as PrTone) : undefined },
    ];
  }, [tools]);

  const transportStats = useMemo(() => {
    const by = new Map<string, { total: number; ready: number; latencies: number[] }>();
    for (const s of servers) {
      const key = s.transport || "unknown";
      const cur = by.get(key) ?? { total: 0, ready: 0, latencies: [] };
      cur.total += 1;
      const st = runtimeState(s);
      if (st === "READY" || st === "BUSY") cur.ready += 1;
      by.set(key, cur);
    }
    for (const c of calls) {
      const server = servers.find((s) => s.server_id === c.server_id);
      if (!server || c.duration_ms == null) continue;
      const cur = by.get(server.transport);
      if (cur) cur.latencies.push(Number(c.duration_ms));
    }
    return [...by.entries()].map(([id, v]) => {
      const avg =
        v.latencies.length > 0
          ? Math.round(v.latencies.reduce((a, b) => a + b, 0) / v.latencies.length)
          : null;
      const healthy = v.ready === v.total && v.total > 0;
      return {
        id,
        label: id,
        servers: v.total,
        latency: avg == null ? "—" : `${avg} ms`,
        status: healthy ? "Gezond" : v.ready > 0 ? "Gedeeltelijk" : "Idle",
        statusTone: (healthy ? "ok" : v.ready > 0 ? "warn" : "muted") as PrTone,
      };
    });
  }, [servers, calls]);

  const alerts = useMemo(() => {
    const items: Array<{ id: string; time: string; tone: PrTone; label: string; message: string }> = [];
    for (const s of servers) {
      const err = s.runtime?.last_error_message;
      if (err) {
        items.push({
          id: `srv-${s.server_id}`,
          time: relativeTime(s.runtime?.last_seen_at),
          tone: "err",
          label: "Fout",
          message: `${s.display_name}: ${err}`,
        });
      }
    }
    for (const c of calls.slice(0, 20)) {
      const st = (c.status ?? "").toUpperCase();
      if (st === "FAILED" || st === "TIMEOUT" || st === "REJECTED") {
        items.push({
          id: `call-${c.call_id}`,
          time: relativeTime(c.started_at),
          tone: "err",
          label: st === "TIMEOUT" ? "Timeout" : "Fout",
          message: `${c.external_tool_name}: ${c.error_message ?? st}`,
        });
      }
    }
    if (!featureEnabled) {
      items.unshift({
        id: "feature-off",
        time: "nu",
        tone: "warn",
        label: "Info",
        message: "MCP feature flag is disabled",
      });
    }
    return items.slice(0, 8);
  }, [servers, calls, featureEnabled]);

  const bridge = useMemo(() => {
    const connected = servers.filter((s) => {
      const st = runtimeState(s);
      return st === "READY" || st === "BUSY";
    }).length;
    const enabled = servers.filter((s) => s.enabled).length;
    const mix = transportStats.map((t) => ({
      id: t.id,
      label: t.label,
      pct: servers.length ? Math.round((t.servers / servers.length) * 100) : 0,
      tone: (t.id === "stdio" ? "cyan" : "ok") as "cyan" | "ok",
    }));
    const healthPct = servers.length ? Math.round((connected / servers.length) * 100) : 0;
    return {
      title: "LEVIATHAN MCP BRIDGE",
      status: !featureEnabled ? "Disabled" : connected > 0 ? "Operationeel" : servers.length ? "Idle" : "Leeg",
      statusTone: (!featureEnabled ? "muted" : connected > 0 ? "ok" : "warn") as PrTone,
      sessions: calls.length,
      activeServers: `${connected}/${servers.length || enabled}`,
      transportMix: mix,
      healthPct,
    };
  }, [servers, calls.length, transportStats, featureEnabled]);

  const serverNameById = useMemo(() => {
    const map = new Map<string, string>();
    for (const s of servers) map.set(s.server_id, s.display_name || s.server_id);
    return map;
  }, [servers]);

  async function withBusy(id: string, action: () => Promise<void>, successMsg: string) {
    setBusyId(id);
    try {
      await action();
      toast(successMsg);
      await load();
    } catch (err) {
      toast(errorMessage(err));
    } finally {
      setBusyId(null);
    }
  }

  async function onToggleEnabled(server: McpServerPublic) {
    const id = server.server_id;
    await withBusy(
      id,
      async () => {
        if (server.enabled) await api.mcpDisableServer(id);
        else await api.mcpEnableServer(id);
      },
      server.enabled ? `${server.display_name} uitgeschakeld` : `${server.display_name} ingeschakeld`,
    );
  }

  async function onConnect(server: McpServerPublic) {
    await withBusy(server.server_id, () => api.mcpConnectServer(server.server_id).then(() => undefined), `${server.display_name} verbonden`);
  }

  async function onDisconnect(server: McpServerPublic) {
    await withBusy(
      server.server_id,
      () => api.mcpDisconnectServer(server.server_id).then(() => undefined),
      `${server.display_name} losgekoppeld`,
    );
  }

  async function onRefreshTools(server: McpServerPublic) {
    await withBusy(
      server.server_id,
      async () => {
        const res = await api.mcpRefreshTools(server.server_id);
        setTools((prev) => {
          const others = prev.filter((t) => t.server_id !== server.server_id);
          return [...others, ...(res.tools ?? [])];
        });
      },
      `Tools vernieuwd (${server.display_name})`,
    );
  }

  async function onDelete(server: McpServerPublic) {
    if (!window.confirm(`Delete MCP server “${server.display_name}”?`)) return;
    await withBusy(server.server_id, () => api.mcpDeleteServer(server.server_id).then(() => undefined), `${server.display_name} verwijderd`);
  }

  async function onCreateServer() {
    const name = createForm.display_name.trim();
    if (!name) {
      toast("Display name is required");
      return;
    }
    const refs = tryParseStringMap(createForm.secret_refs);
    if (!refs.ok) {
      toast(refs.error);
      return;
    }
    const args = createForm.args
      .split(/\s+/)
      .map((a) => a.trim())
      .filter(Boolean);
    const payload: Record<string, unknown> = {
      display_name: name,
      transport: createForm.transport,
      trust: createForm.trust,
      requested_isolation: createForm.requested_isolation,
      enabled: createForm.enabled,
      eager_connect: createForm.eager_connect,
      secret_refs: refs.value,
    };
    if (createForm.transport === "stdio") {
      if (!createForm.command.trim()) {
        toast("Command is required for stdio transport");
        return;
      }
      payload.command = createForm.command.trim();
      payload.args = args;
    } else {
      if (!createForm.url.trim()) {
        toast("URL is required for http/sse transport");
        return;
      }
      payload.url = createForm.url.trim();
    }
    setCreating(true);
    try {
      const res = await api.mcpCreateServer(payload);
      toast(`Server “${res.server.display_name}” aangemaakt`);
      setShowCreate(false);
      setCreateForm(EMPTY_CREATE);
      setSelectedId(res.server.server_id);
      await load();
    } catch (err) {
      toast(errorMessage(err, "Create server failed"));
    } finally {
      setCreating(false);
    }
  }

  async function onRediscoverAll() {
    const targets = servers.filter((s) => {
      const st = runtimeState(s);
      return s.enabled && (st === "READY" || st === "BUSY" || st === "DEGRADED");
    });
    if (!targets.length) {
      toast("No connected servers to refresh");
      return;
    }
    setBusyId("rediscover");
    try {
      let ok = 0;
      const errors: string[] = [];
      for (const s of targets) {
        try {
          await api.mcpRefreshTools(s.server_id);
          ok += 1;
        } catch (err) {
          errors.push(`${s.display_name}: ${errorMessage(err)}`);
        }
      }
      await load();
      if (errors.length) {
        toast(`Refreshed ${ok}/${targets.length}. ${errors[0]}`);
      } else {
        toast(`Tools vernieuwd voor ${ok} server(s)`);
      }
    } finally {
      setBusyId(null);
    }
  }

  async function onReconnectEnabled() {
    const targets = servers.filter((s) => s.enabled);
    if (!targets.length) {
      toast("No enabled servers");
      return;
    }
    setBusyId("restart");
    try {
      let ok = 0;
      const errors: string[] = [];
      for (const s of targets) {
        try {
          await api.mcpDisconnectServer(s.server_id).catch(() => undefined);
          await api.mcpConnectServer(s.server_id);
          ok += 1;
        } catch (err) {
          errors.push(`${s.display_name}: ${errorMessage(err)}`);
        }
      }
      await load();
      if (errors.length) toast(`Reconnected ${ok}/${targets.length}. ${errors[0]}`);
      else toast(`Reconnected ${ok} server(s)`);
    } finally {
      setBusyId(null);
    }
  }

  async function onInvoke() {
    if (!invokeCapabilityId) {
      toast("Select a tool capability");
      return;
    }
    const parsed = tryParseArgs(invokeArgs);
    if (!parsed.ok) {
      toast(parsed.error);
      return;
    }
    setInvoking(true);
    setInvokeResult(null);
    try {
      const res = await api.mcpCall({
        capability_id: invokeCapabilityId,
        arguments: parsed.value,
      });
      setInvokeResult(JSON.stringify(res.result ?? res, null, 2));
      toast("Tool call completed");
      const callsRes = await api.mcpCalls(100).catch(() => null);
      if (callsRes) setCalls(callsRes.calls ?? []);
    } catch (err) {
      const msg = errorMessage(err, "Tool call failed");
      setInvokeResult(msg);
      toast(msg);
    } finally {
      setInvoking(false);
    }
  }

  const secretRefEntries = Object.entries(selected?.secret_refs ?? {});

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
          {kpis.map((kpi) => (
            <article key={kpi.id + kpi.label} className={`lv-pr-kpi${"warn" in kpi && kpi.warn ? " is-warn" : ""}`}>
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
                    {"pct" in kpi && kpi.pct != null ? (
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

        {loadError ? (
          <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block" role="alert">
            {loadError}{" "}
            <button type="button" className="lv-pr-mcp-btn" onClick={() => void load()}>
              Opnieuw
            </button>
          </p>
        ) : null}

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
                    <option value="connected">Verbonden</option>
                    <option value="error">Fout</option>
                    <option value="disconnected">Losgekoppeld</option>
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
                    <option value="sse">sse</option>
                  </select>
                  <button
                    type="button"
                    className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                    onClick={() => setShowCreate((v) => !v)}
                  >
                    + Server toevoegen
                  </button>
                  <button type="button" className="lv-pr-mcp-btn" onClick={() => void load()} disabled={loading}>
                    {loading ? "Laden…" : "Vernieuwen"}
                  </button>
                </div>
              }
            >
              {showCreate ? (
                <div className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block" style={{ marginBottom: 12 }}>
                  <div className="lv-pr-mcp-toolbar" style={{ flexWrap: "wrap", gap: 8 }}>
                    <input
                      className="lv-pr-mcp-input"
                      placeholder="Display name"
                      value={createForm.display_name}
                      onChange={(e) => setCreateForm((f) => ({ ...f, display_name: e.target.value }))}
                      aria-label="Display name"
                    />
                    <select
                      className="lv-pr-mcp-select"
                      value={createForm.transport}
                      onChange={(e) => setCreateForm((f) => ({ ...f, transport: e.target.value }))}
                      aria-label="Transport"
                    >
                      <option value="stdio">stdio</option>
                      <option value="http">http</option>
                      <option value="sse">sse</option>
                    </select>
                    {createForm.transport === "stdio" ? (
                      <>
                        <input
                          className="lv-pr-mcp-input"
                          placeholder="Command"
                          value={createForm.command}
                          onChange={(e) => setCreateForm((f) => ({ ...f, command: e.target.value }))}
                          aria-label="Command"
                        />
                        <input
                          className="lv-pr-mcp-input"
                          placeholder="Args (space-separated)"
                          value={createForm.args}
                          onChange={(e) => setCreateForm((f) => ({ ...f, args: e.target.value }))}
                          aria-label="Args"
                        />
                      </>
                    ) : (
                      <input
                        className="lv-pr-mcp-input"
                        placeholder="URL"
                        value={createForm.url}
                        onChange={(e) => setCreateForm((f) => ({ ...f, url: e.target.value }))}
                        aria-label="URL"
                      />
                    )}
                    <select
                      className="lv-pr-mcp-select"
                      value={createForm.trust}
                      onChange={(e) => setCreateForm((f) => ({ ...f, trust: e.target.value }))}
                      aria-label="Trust"
                    >
                      <option value="untrusted">untrusted</option>
                      <option value="manual">manual</option>
                      <option value="trusted">trusted</option>
                    </select>
                    <select
                      className="lv-pr-mcp-select"
                      value={createForm.requested_isolation}
                      onChange={(e) => setCreateForm((f) => ({ ...f, requested_isolation: e.target.value }))}
                      aria-label="Isolation"
                    >
                      <option value="subprocess">subprocess</option>
                      <option value="process">process</option>
                      <option value="container">container</option>
                      <option value="sandbox">sandbox</option>
                      <option value="none">none</option>
                    </select>
                    <input
                      className="lv-pr-mcp-input"
                      placeholder='Secret refs JSON e.g. {"TOKEN":"vault://…"}'
                      value={createForm.secret_refs}
                      onChange={(e) => setCreateForm((f) => ({ ...f, secret_refs: e.target.value }))}
                      aria-label="Secret refs"
                    />
                    <label className="lv-pr-mcp-status">
                      <input
                        type="checkbox"
                        checked={createForm.enabled}
                        onChange={(e) => setCreateForm((f) => ({ ...f, enabled: e.target.checked }))}
                      />{" "}
                      Enabled
                    </label>
                    <label className="lv-pr-mcp-status">
                      <input
                        type="checkbox"
                        checked={createForm.eager_connect}
                        onChange={(e) => setCreateForm((f) => ({ ...f, eager_connect: e.target.checked }))}
                      />{" "}
                      Eager connect
                    </label>
                    <button
                      type="button"
                      className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                      disabled={creating}
                      onClick={() => void onCreateServer()}
                    >
                      {creating ? "Aanmaken…" : "Aanmaken"}
                    </button>
                    <button type="button" className="lv-pr-mcp-btn" onClick={() => setShowCreate(false)}>
                      Annuleren
                    </button>
                  </div>
                </div>
              ) : null}

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
                    {!loading && filteredServers.length === 0 ? (
                      <tr>
                        <td colSpan={9} className="lv-pr-empty">
                          {servers.length === 0
                            ? featureEnabled
                              ? "Geen MCP servers geregistreerd. Voeg een server toe om te beginnen."
                              : "MCP feature is disabled."
                            : "Geen servers matchen de huidige filters."}
                        </td>
                      </tr>
                    ) : null}
                    {filteredServers.map((server) => {
                      const state = runtimeState(server);
                      const tone = statusTone(state);
                      const busy = busyId === server.server_id;
                      const connected = state === "READY" || state === "BUSY";
                      const lastSeen = server.runtime?.last_seen_at ?? server.runtime?.last_connected_at;
                      return (
                        <tr
                          key={server.server_id}
                          className={selectedId === server.server_id ? "is-selected" : undefined}
                          onClick={() => setSelectedId(server.server_id)}
                        >
                          <td>
                            <span className="lv-pr-mcp-name">
                              <span className="lv-pr-mcp-name-icon">
                                {SERVER_ICONS[serverIconKey(server)] ?? SERVER_ICONS.docs}
                              </span>
                              <span className="is-name">{server.display_name}</span>
                            </span>
                          </td>
                          <td>{server.transport}</td>
                          <td>
                            <span className={`lv-pr-mcp-status is-${tone}`}>
                              <StatusDot tone={tone} />
                              {statusLabel(state)}
                            </span>
                          </td>
                          <td>
                            <button
                              type="button"
                              className="lv-pr-mcp-toggle-btn"
                              disabled={busy}
                              onClick={(e) => {
                                e.stopPropagation();
                                void onToggleEnabled(server);
                              }}
                              aria-label={`${server.display_name} ${server.enabled ? "uitschakelen" : "inschakelen"}`}
                            >
                              <Toggle on={server.enabled} label={server.display_name} />
                            </button>
                          </td>
                          <td>{server.runtime?.tool_count ?? tools.filter((t) => t.server_id === server.server_id).length}</td>
                          <td className="lv-pr-mcp-health">{relativeTime(lastSeen)}</td>
                          <td className="lv-pr-mcp-iso">
                            {server.runtime?.effective_isolation || server.requested_isolation}
                          </td>
                          <td className={server.runtime?.last_error_message ? "is-err" : ""}>
                            {server.runtime?.last_error_message || "—"}
                          </td>
                          <td>
                            <div className="lv-pr-mcp-row-actions">
                              <IconBtn
                                label={connected ? "Disconnect" : "Connect"}
                                disabled={busy || (!server.enabled && !connected)}
                                onClick={() => void (connected ? onDisconnect(server) : onConnect(server))}
                              >
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <path
                                    d="M6 3.5H3.5v9h9V10M8.5 3.5H12.5V7.5M12.5 3.5 7 9"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.2"
                                  />
                                </svg>
                              </IconBtn>
                              <IconBtn
                                label="Refresh tools"
                                disabled={busy}
                                onClick={() => void onRefreshTools(server)}
                              >
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <path
                                    d="M3.5 8a4.5 4.5 0 0 1 7.5-3.3L13 3v4H9"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.2"
                                  />
                                </svg>
                              </IconBtn>
                              <IconBtn label="Delete" disabled={busy} onClick={() => void onDelete(server)}>
                                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                                  <path
                                    d="M4 5h8M6.5 5V3.8h3V5M5.5 5l.5 7.2h4l.5-7.2"
                                    fill="none"
                                    stroke="currentColor"
                                    strokeWidth="1.2"
                                  />
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
                  Tool availability from the MCP catalog (discoverable ≠ authorized).
                </p>
                <div className="lv-pr-mcp-auth-summary">
                  {authSummary.map((item) => (
                    <div
                      key={item.id}
                      className={`lv-pr-mcp-auth-box${"tone" in item && item.tone ? ` is-${item.tone}` : ""}`}
                    >
                      <span
                        className={`lv-pr-mcp-auth-icon${"tone" in item && item.tone ? ` is-${item.tone}` : " is-gold"}`}
                      >
                        {AUTH_ICONS[item.id]}
                      </span>
                      <div>
                        <div className="lv-pr-mcp-auth-label">{item.label}</div>
                        <div className="lv-pr-mcp-auth-value">{item.value}</div>
                      </div>
                    </div>
                  ))}
                </div>

                <div className="lv-pr-mcp-policy-title">Handmatige Invoke</div>
                <div className="lv-pr-mcp-policies">
                  <label className="lv-pr-mcp-policy-row">
                    <span>Capability</span>
                    <select
                      className="lv-pr-mcp-select"
                      value={invokeCapabilityId}
                      onChange={(e) => setInvokeCapabilityId(e.target.value)}
                      aria-label="Capability"
                    >
                      <option value="">— select tool —</option>
                      {tools.map((t) => (
                        <option key={t.capability_id} value={t.capability_id}>
                          {t.external_name} ({serverNameById.get(t.server_id) ?? t.server_id})
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="lv-pr-mcp-policy-row" style={{ alignItems: "flex-start" }}>
                    <span>Arguments</span>
                    <textarea
                      className="lv-pr-mcp-input"
                      style={{ minHeight: 72, fontFamily: "ui-monospace, monospace", width: "100%" }}
                      value={invokeArgs}
                      onChange={(e) => setInvokeArgs(e.target.value)}
                      aria-label="Invoke arguments JSON"
                    />
                  </label>
                  <div className="lv-pr-mcp-toolbar">
                    <button
                      type="button"
                      className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                      disabled={invoking || !invokeCapabilityId}
                      onClick={() => void onInvoke()}
                    >
                      {invoking ? "Calling…" : "Invoke via Gateway"}
                    </button>
                  </div>
                  {invokeResult ? (
                    <pre className="lv-pr-mcp-mono" style={{ whiteSpace: "pre-wrap", maxHeight: 180, overflow: "auto" }}>
                      {invokeResult}
                    </pre>
                  ) : null}
                </div>

                {selected ? (
                  <>
                    <div className="lv-pr-mcp-policy-title">Selected server secrets</div>
                    <div className="lv-pr-mcp-policies">
                      {secretRefEntries.length === 0 ? (
                        <div className="lv-pr-mcp-panel-sub">Geen secret refs</div>
                      ) : (
                        secretRefEntries.map(([key, ref]) => (
                          <div key={key} className="lv-pr-mcp-policy-row">
                            <span>{key}</span>
                            <span className="lv-pr-mcp-mono">{formatSecretRef(ref)}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </>
                ) : null}
              </Panel>

              <Panel
                className="lv-pr-mcp-calls"
                title="Recente Tool Calls"
                action={
                  <button type="button" className="lv-pr-mcp-btn lv-pr-mcp-btn--gold" onClick={() => void load()}>
                    Vernieuwen
                  </button>
                }
              >
                <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                  Laatste MCP tool aanroepen via ExecutionGateway.
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
                      {calls.length === 0 ? (
                        <tr>
                          <td colSpan={5} className="lv-pr-empty">
                            Geen recente calls
                          </td>
                        </tr>
                      ) : null}
                      {calls.map((call) => {
                        const tone = callTone(call.status);
                        return (
                          <tr key={call.call_id}>
                            <td className="lv-pr-mcp-mono">{formatTs(call.started_at)}</td>
                            <td className="is-name">{call.external_tool_name || call.capability_id}</td>
                            <td>{call.requester || "—"}</td>
                            <td>{formatDuration(call.duration_ms)}</td>
                            <td>
                              <span className={`lv-pr-mcp-status is-${tone}`}>
                                <StatusDot tone={tone} />
                                {call.status}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Panel>
            </div>
          </div>

          <aside className="lv-pr-mcp-col-side">
            <Panel className="lv-pr-mcp-bridge" title="Bridge Samenvatting">
              <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                Universele MCP bridge — live server & transport overzicht.
              </p>
              <div className="lv-pr-mcp-bridge-body">
                <div className="lv-pr-mcp-bridge-left">
                  <div className="lv-pr-mcp-bridge-title">{bridge.title}</div>
                  <Pill tone={bridge.statusTone}>{bridge.status}</Pill>
                  <div className="lv-pr-mcp-bridge-uptime">
                    Feature: {featureEnabled ? "enabled" : "disabled"}
                  </div>
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
                    <button
                      type="button"
                      className="lv-pr-mcp-btn lv-pr-mcp-btn--gold"
                      disabled={busyId === "restart"}
                      onClick={() => void onReconnectEnabled()}
                    >
                      Bridge herstarten
                    </button>
                    <button type="button" className="lv-pr-mcp-btn" onClick={() => setShowCreate(true)}>
                      Configuratie
                    </button>
                  </div>
                </div>
                <div className="lv-pr-mcp-bridge-right">
                  <div className="lv-pr-mcp-bridge-stat">
                    <span>Recente calls</span>
                    <strong>{bridge.sessions}</strong>
                  </div>
                  <div className="lv-pr-mcp-bridge-stat">
                    <span>Actieve servers</span>
                    <strong>{bridge.activeServers}</strong>
                  </div>
                  <div className="lv-pr-mcp-mix-label">Transport Mix</div>
                  {bridge.transportMix.length === 0 ? (
                    <div className="lv-pr-mcp-panel-sub">Geen transports</div>
                  ) : (
                    bridge.transportMix.map((mix) => (
                      <div key={mix.id} className="lv-pr-mcp-mix-row">
                        <span>{mix.label}</span>
                        <Bar pct={mix.pct} tone={mix.tone} />
                        <em>{mix.pct}%</em>
                      </div>
                    ))
                  )}
                  <div className="lv-pr-mcp-mix-label">Huidige Health</div>
                  <div className="lv-pr-mcp-mix-row">
                    <Bar pct={bridge.healthPct} tone="cyan" className="lv-pr-mcp-health-bar" />
                    <em>{bridge.healthPct}%</em>
                  </div>
                </div>
              </div>
            </Panel>

            <Panel
              className="lv-pr-mcp-catalog"
              title="Tool Discovery / Catalogus"
              action={
                <button
                  type="button"
                  className="lv-pr-mcp-btn"
                  disabled={busyId === "rediscover"}
                  onClick={() => void onRediscoverAll()}
                >
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
                    {tools.length === 0 ? (
                      <tr>
                        <td colSpan={3} className="lv-pr-empty">
                          Geen tools ontdekt
                        </td>
                      </tr>
                    ) : null}
                    {tools.map((tool) => (
                      <tr
                        key={tool.capability_id}
                        onClick={() => setInvokeCapabilityId(tool.capability_id)}
                        style={{ cursor: "pointer" }}
                      >
                        <td>
                          <span className="lv-pr-mcp-name">
                            <span className="lv-pr-mcp-name-icon is-gold">
                              <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                                <path
                                  d="M8 2.5 13 5.5v5L8 13.5 3 10.5v-5z"
                                  fill="none"
                                  stroke="currentColor"
                                  strokeWidth="1.2"
                                />
                              </svg>
                            </span>
                            <span className="is-name">{tool.external_name}</span>
                          </span>
                        </td>
                        <td>{serverNameById.get(tool.server_id) ?? tool.server_id}</td>
                        <td className="lv-pr-mcp-desc">{tool.description || tool.availability}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>

            <div className="lv-pr-mcp-side-bottom">
              <div className="lv-pr-mcp-side-stack">
                <Panel className="lv-pr-mcp-transports" title="Transport & Health">
                  <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                    Status van MCP transports en verbindingen.
                  </p>
                  <div className="lv-pr-mcp-transport-list">
                    {transportStats.length === 0 ? (
                      <div className="lv-pr-empty">Geen transports</div>
                    ) : null}
                    {transportStats.map((t) => (
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
                        </div>
                      </article>
                    ))}
                  </div>
                </Panel>

                <Panel className="lv-pr-mcp-alerts" title="Recente Alerts">
                  <p className="lv-pr-mcp-panel-sub lv-pr-mcp-panel-sub--block">
                    Fouten en events uit servers / call history.
                  </p>
                  <ul className="lv-pr-alert-list lv-pr-mcp-alert-list">
                    {alerts.length === 0 ? <li className="lv-pr-empty">Geen alerts</li> : null}
                    {alerts.map((alert) => (
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
                  <button type="button" className="lv-pr-mcp-quick-btn" onClick={() => setShowCreate(true)}>
                    <span className="lv-pr-mcp-quick-icon">{QUICK_ICONS.add}</span>
                    Server toevoegen
                  </button>
                  <button
                    type="button"
                    className="lv-pr-mcp-quick-btn"
                    disabled={busyId === "rediscover"}
                    onClick={() => void onRediscoverAll()}
                  >
                    <span className="lv-pr-mcp-quick-icon">{QUICK_ICONS.rediscover}</span>
                    Tools herontdekken
                  </button>
                  <button
                    type="button"
                    className="lv-pr-mcp-quick-btn"
                    disabled={busyId === "restart"}
                    onClick={() => void onReconnectEnabled()}
                  >
                    <span className="lv-pr-mcp-quick-icon">{QUICK_ICONS.restart}</span>
                    Bridge herstarten
                  </button>
                  <button type="button" className="lv-pr-mcp-quick-btn" onClick={() => void load()}>
                    <span className="lv-pr-mcp-quick-icon">{QUICK_ICONS.config}</span>
                    Status vernieuwen
                  </button>
                </div>
              </Panel>
            </div>
          </aside>
        </section>
      </main>
    </AppShell>
  );
}
