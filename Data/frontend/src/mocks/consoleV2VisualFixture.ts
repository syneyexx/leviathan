/**
 * TEST-ONLY Screen 1 Console visual fixture.
 * Activated solely when window.__LV_V2_VISUAL_FIXTURE__ === 'console'.
 * Production Console pages must NEVER import these numbers as defaults.
 */

import type { ConsoleOverviewResponse, RuntimeEvent } from "../types/api";

export const CONSOLE_V2_VISUAL_FROZEN_ISO = "2025-05-25T14:37:26.000Z";

export function isConsoleVisualFixtureActive(): boolean {
  if (typeof window === "undefined") return false;
  const flag = (window as Window & { __LV_V2_VISUAL_FIXTURE__?: unknown }).__LV_V2_VISUAL_FIXTURE__;
  return flag === "console";
}

function spark(seed: number, n = 24): number[] {
  const out: number[] = [];
  let v = seed;
  for (let i = 0; i < n; i += 1) {
    v = (v * 17 + 23 + i * 3) % 97;
    out.push(20 + (v % 60));
  }
  return out;
}

export function consoleOverviewFixture(): ConsoleOverviewResponse {
  const until = new Date(CONSOLE_V2_VISUAL_FROZEN_ISO).getTime();
  const since = until - 24 * 3_600_000;
  const buckets = Array.from({ length: 24 }, (_, i) => {
    const info = 40 + ((i * 7) % 30);
    const success = 10 + ((i * 3) % 12);
    const warning = i % 5 === 0 ? 2 : 0;
    const error = i % 11 === 0 ? 1 : 0;
    return {
      bucket_index: i,
      bucket_start_ms: since + i * 3_600_000,
      bucket_end_ms: since + (i + 1) * 3_600_000,
      info,
      success,
      warning,
      error,
      other: 0,
      total: info + success + warning + error,
    };
  });
  const total = buckets.reduce((a, b) => a + b.total, 0);
  const warnings = buckets.reduce((a, b) => a + b.warning, 0);
  const errors = buckets.reduce((a, b) => a + b.error, 0);
  const success = buckets.reduce((a, b) => a + b.success, 0);
  const info = buckets.reduce((a, b) => a + b.info, 0);

  return {
    generated_at_ms: until,
    window_hours: 24,
    stats: {
      window: {
        since_ms: since,
        until_ms: until,
        bucket_count: 24,
        bucket_ms: 3_600_000,
        rate_window_ms: 300_000,
      },
      totals: {
        events: total,
        info,
        success,
        warning: warnings,
        error: errors,
        by_level: { INFO: info, SUCCESS: success, WARNING: warnings, ERROR: errors },
      },
      log_rate_per_min: 423,
      log_rate_sample_count: 2115,
      buckets,
      top_components: [
        { rank: 1, component: "api", event_count: Math.round(total * 0.34), share: 0.34, share_denominator: "total_events_in_selected_period" },
        { rank: 2, component: "agent", event_count: Math.round(total * 0.22), share: 0.22, share_denominator: "total_events_in_selected_period" },
        { rank: 3, component: "dataset", event_count: Math.round(total * 0.14), share: 0.14, share_denominator: "total_events_in_selected_period" },
        { rank: 4, component: "mcp", event_count: Math.round(total * 0.11), share: 0.11, share_denominator: "total_events_in_selected_period" },
        { rank: 5, component: "worker", event_count: Math.round(total * 0.09), share: 0.09, share_denominator: "total_events_in_selected_period" },
      ],
      recent_errors: [
        {
          sequence: 9001,
          event_id: "fx-e1",
          created_at_ms: until - 13_000,
          level: "ERROR",
          category: "mcp",
          subsystem: "BraveSearch",
          name: "rate_limit",
          message: "Rate limit exceeded (429)",
          source: "mcp",
        },
        {
          sequence: 9000,
          event_id: "fx-e2",
          created_at_ms: until - 52_000,
          level: "ERROR",
          category: "http",
          subsystem: "api",
          name: "timeout",
          message: "Upstream timeout after 30s",
          source: "api",
        },
      ],
      filter_options: {
        categories: ["http", "mcp", "agent", "workflow", "module_manager", "system"],
        subsystems: ["api", "agent", "mcp", "worker", "dataset"],
      },
      sparklines: {
        total: spark(11),
        warning: spark(3).map((v) => Math.round(v / 8)),
        error: spark(5).map((v) => Math.round(v / 20)),
        success: spark(7),
        rate: spark(13),
      },
      activity_rate_by_component: {
        api: 120,
        agent: 80,
        mcp: 40,
        worker: 55,
        dataset: 30,
      },
      truth: { measured: true, fixture: true },
    },
    metrics: {
      total_logs_24h: total,
      warnings_24h: warnings,
      errors_24h: errors,
      info_24h: info,
      success_24h: success,
      log_rate_per_min: 423,
      active_services: 12,
      total_services: 12,
      sparklines: {
        total: spark(11),
        warning: spark(3).map((v) => Math.round(v / 8)),
        error: spark(5).map((v) => Math.round(v / 20)),
        success: spark(7),
        rate: spark(13),
      },
    },
    services: [
      { id: "api", name: "API Server", type: "runtime", status: "operational", measured: true, events_per_min: 120 },
      { id: "agent", name: "Agent Runtime", type: "runtime", status: "operational", measured: true, events_per_min: 80 },
      { id: "mcp", name: "MCP Services", type: "runtime", status: "operational", measured: true, events_per_min: 40 },
      { id: "workers", name: "Worker Pool", type: "runtime", status: "operational", measured: true, events_per_min: 55 },
      { id: "tools", name: "Tool Registry", type: "runtime", status: "operational", measured: true, events_per_min: 22 },
      { id: "db", name: "Database", type: "storage", status: "operational", measured: true, events_per_min: 18 },
      { id: "trading", name: "Trading Engine", type: "runtime", status: "degraded", measured: true, events_per_min: 9 },
      { id: "research", name: "Research Pipeline", type: "runtime", status: "operational", measured: true, events_per_min: 14 },
      { id: "automation", name: "Automation", type: "runtime", status: "operational", measured: true, events_per_min: 11 },
      { id: "ws", name: "WebSocket", type: "runtime", status: "operational", measured: true, events_per_min: 33 },
      { id: "containers", name: "Container Manager", type: "runtime", status: "unmeasured", measured: false, events_per_min: null },
      { id: "monitor", name: "System Monitor", type: "runtime", status: "operational", measured: true, events_per_min: 7 },
    ],
    stream: { latest_sequence: 9001, buffered: 120, subscribers: 1, durable: true },
    truth: { fixture: true },
  };
}

export function liveEventsFixture(): RuntimeEvent[] {
  const until = new Date(CONSOLE_V2_VISUAL_FROZEN_ISO).getTime();
  const rows: Array<Partial<RuntimeEvent> & Pick<RuntimeEvent, "sequence" | "event_id" | "level" | "message">> = [
    { sequence: 1, event_id: "a", level: "INFO", message: "Request completed in 42ms", category: "http", subsystem: "api", name: "Request", created_at_ms: until - 40_000 },
    { sequence: 2, event_id: "b", level: "SUCCESS", message: "Agent step finished", category: "agent", subsystem: "agent", name: "Step", created_at_ms: until - 35_000 },
    { sequence: 3, event_id: "c", level: "WARNING", message: "Dataset validation slow", category: "dataset", subsystem: "dataset", name: "Validate", created_at_ms: until - 30_000 },
    { sequence: 4, event_id: "d", level: "INFO", message: "MCP tool listed", category: "mcp", subsystem: "mcp", name: "List", created_at_ms: until - 25_000 },
    { sequence: 5, event_id: "e", level: "ERROR", message: "Rate limit exceeded (429)", category: "mcp", subsystem: "BraveSearch", name: "Search", created_at_ms: until - 13_000 },
    { sequence: 6, event_id: "f", level: "INFO", message: "Worker heartbeat", category: "worker", subsystem: "worker", name: "Heartbeat", created_at_ms: until - 8_000 },
    { sequence: 7, event_id: "g", level: "SUCCESS", message: "Workflow step ok", category: "workflow", subsystem: "workflow", name: "Step", created_at_ms: until - 4_000 },
    { sequence: 8, event_id: "h", level: "INFO", message: "Console overview refreshed", category: "console", subsystem: "system", name: "Refresh", created_at_ms: until - 1_000 },
  ];
  return rows.map((r) => ({
    payload: {},
    source: "fixture",
    category: r.category || "system",
    subsystem: r.subsystem || "system",
    name: r.name || "event",
    created_at_ms: r.created_at_ms || until,
    ...r,
  }));
}
