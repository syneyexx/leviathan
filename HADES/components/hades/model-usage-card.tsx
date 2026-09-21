"use client";

import { useMemo } from "react";
import { Activity, ServerOff } from "lucide-react";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Panel, StatusBadge } from "@/components/hades/ui";
import type { LmModel } from "@/lib/hades-api";

export type UsageKind = "exact" | "estimate" | "unavailable";
export type UsageStatus =
  | "idle"
  | "queued"
  | "generating"
  | "tool_continuation"
  | "running"
  | "degraded"
  | "failed"
  | "error"
  | "cancelled";

export type ModelUsageState = {
  status: UsageStatus;
  modelId: string;
  currentTotal: number | null;
  currentInput: number | null;
  currentOutput: number | null;
  kind: UsageKind;
  peakTotal: number | null;
  sessionTotal: number | null;
  conversationTotal: number | null;
  modelCalls: number | null;
  history: Array<{ at: number; total: number | null }>;
};

/** Optional execution-derived fields for the operator telemetry strip. */
export type ChatTelemetryExtras = {
  executionStatus?: string | null;
  contextUsed?: number | null;
  contextMax?: number | null;
  toolRounds?: number | null;
  maxToolRounds?: number | null;
  wallMs?: number | null;
  dropReasons?: string[] | null;
};

const statusCopy: Record<UsageStatus, string> = {
  idle: "Idle",
  queued: "In wachtrij",
  generating: "Genereren",
  tool_continuation: "Toolvervolg",
  running: "Running",
  degraded: "Degraded",
  failed: "Failed",
  error: "Fout",
  cancelled: "Geannuleerd",
};

const statusTone = (status: UsageStatus): "success" | "info" | "warning" | "danger" => {
  if (status === "generating" || status === "tool_continuation" || status === "running") return "info";
  if (status === "queued" || status === "degraded" || status === "cancelled") return "warning";
  if (status === "error" || status === "failed") return "danger";
  return "success";
};

/** Missing / unknown → em dash. Never paint a fake zero for absent usage. */
export function formatUsageValue(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("nl-NL").format(value);
}

function formatWallMs(wallMs: number | null | undefined): string {
  if (wallMs == null || Number.isNaN(wallMs) || wallMs < 0) return "—";
  if (wallMs < 1000) return `${Math.round(wallMs)} ms`;
  const seconds = wallMs / 1000;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
  const minutes = Math.floor(seconds / 60);
  const rem = Math.round(seconds - minutes * 60);
  return `${minutes}m ${rem}s`;
}

function formatTokPerSec(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value) || value < 0) return "—";
  if (value < 10) return value.toFixed(1);
  return String(Math.round(value));
}

/** Derive tok/s from consecutive history samples with known totals. */
export function estimateTokensPerSecond(history: Array<{ at: number; total: number | null }>): number | null {
  const points = history.filter((item): item is { at: number; total: number } => typeof item.total === "number" && item.total >= 0);
  if (points.length < 2) return null;
  const a = points[points.length - 2];
  const b = points[points.length - 1];
  const dtSec = (b.at - a.at) / 1000;
  const delta = b.total - a.total;
  if (!(dtSec > 0) || delta < 0) return null;
  return delta / dtSec;
}

/** Operator-facing run status: running / degraded / failed (plus idle/cancelled when known). */
export function resolveOperatorRunStatus(
  usageStatus: UsageStatus,
  executionStatus?: string | null,
): UsageStatus {
  const exec = String(executionStatus || "").toLowerCase();
  if (exec === "degraded") return "degraded";
  if (exec === "failed" || exec === "blocked") return "failed";
  if (exec === "cancelled" || usageStatus === "cancelled") return "cancelled";
  if (exec === "running" || usageStatus === "running") return "running";
  if (usageStatus === "degraded") return "degraded";
  if (usageStatus === "failed" || usageStatus === "error") return "failed";
  if (usageStatus === "generating" || usageStatus === "tool_continuation" || usageStatus === "queued") return "running";
  if (exec === "completed" || exec === "partial" || usageStatus === "idle") return "idle";
  if (!exec && usageStatus === "idle") return "idle";
  return usageStatus;
}

function UsageSparkline({ history, peak }: { history: Array<{ at: number; total: number | null }>; peak: number | null }) {
  const points = useMemo(() => {
    const values = history.map((item) => item.total).filter((value): value is number => typeof value === "number" && value >= 0);
    if (!values.length) return "";
    const width = 220;
    const height = 48;
    const max = Math.max(peak || 0, ...values, 1);
    return values
      .map((value, index) => {
        const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
        const y = height - (value / max) * (height - 4) - 2;
        return `${x.toFixed(1)},${y.toFixed(1)}`;
      })
      .join(" ");
  }, [history, peak]);

  const peakY = useMemo(() => {
    const values = history.map((item) => item.total).filter((value): value is number => typeof value === "number");
    if (!values.length || peak == null) return null;
    const max = Math.max(peak, ...values, 1);
    return 48 - (peak / max) * 44 - 2;
  }, [history, peak]);

  return (
    <svg className="usage-sparkline" viewBox="0 0 220 48" role="img" aria-label="Live tokenverbruik">
      <rect x="0" y="0" width="220" height="48" className="usage-sparkline-bg" />
      {peakY != null ? <line x1="0" x2="220" y1={peakY} y2={peakY} className="usage-sparkline-peak" /> : null}
      {points ? <polyline fill="none" points={points} className="usage-sparkline-line" /> : (
        <text x="110" y="28" textAnchor="middle" className="usage-sparkline-empty">Nog geen gebruik</text>
      )}
    </svg>
  );
}

export function ModelUsageCard({
  models,
  modelId,
  onModelChange,
  usage,
  telemetry,
}: {
  models: LmModel[];
  modelId: string;
  onModelChange: (value: string) => void;
  usage: ModelUsageState;
  telemetry?: ChatTelemetryExtras;
}) {
  const operatorStatus = resolveOperatorRunStatus(usage.status, telemetry?.executionStatus);
  const tokPerSec = useMemo(() => {
    const fromHistory = estimateTokensPerSecond(usage.history);
    if (fromHistory != null) return fromHistory;
    const wallMs = telemetry?.wallMs;
    const out = usage.currentOutput;
    if (wallMs != null && wallMs > 0 && typeof out === "number" && out >= 0) {
      return out / (wallMs / 1000);
    }
    return null;
  }, [usage.history, usage.currentOutput, telemetry?.wallMs]);

  const displayModel = usage.modelId || modelId || "";
  const ctxUsed = telemetry?.contextUsed ?? null;
  const ctxMax = telemetry?.contextMax ?? null;
  const toolRounds = telemetry?.toolRounds ?? null;
  const maxToolRounds = telemetry?.maxToolRounds ?? null;

  return (
    <Panel
      title="Modelgebruik"
      className="flat-panel model-usage-panel"
      actions={<StatusBadge tone={statusTone(operatorStatus)}>{statusCopy[operatorStatus]}</StatusBadge>}
    >
      {models.length ? (
        <Select value={modelId} onValueChange={onModelChange}>
          <SelectTrigger aria-label="Actief model">
            <SelectValue placeholder="Kies een model" />
          </SelectTrigger>
          <SelectContent>
            {models.map((model) => (
              <SelectItem value={model.id} key={model.id}>{model.id}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <div className="offline-box">
          <ServerOff />
          <span>
            <strong>Geen model gevonden</strong>
            <small>Start de lokale server en laad een model.</small>
          </span>
        </div>
      )}

      <div className="usage-detail-row" role="status" aria-label="Chat telemetry">
        <Activity />
        <small>
          model {displayModel || "—"}
          {" · "}ctx {formatUsageValue(ctxUsed)}/{formatUsageValue(ctxMax)}
          {" · "}{formatTokPerSec(tokPerSec)} tok/s
          {" · "}tools {formatUsageValue(toolRounds)}/{formatUsageValue(maxToolRounds)}
          {" · "}{formatWallMs(telemetry?.wallMs)}
        {telemetry?.dropReasons?.length ? <>{" · "}drops:{telemetry.dropReasons.slice(0, 4).join(",")}</> : null}
          {" · "}{statusCopy[operatorStatus]}
        </small>
      </div>

      <UsageSparkline history={usage.history} peak={usage.peakTotal} />

      <div className="usage-metrics">
        <div className={usage.status === "generating" || usage.status === "tool_continuation" || usage.status === "running" ? "usage-metric-live" : undefined}>
          <span>CURRENT</span>
          <strong>{formatUsageValue(usage.currentTotal)}</strong>
          <small>{usage.kind === "exact" ? "provider" : usage.kind === "estimate" ? "schatting" : "n.v.t."}</small>
        </div>
        <div>
          <span>PEAK</span>
          <strong>{formatUsageValue(usage.peakTotal)}</strong>
          <small>sessie</small>
        </div>
        <div>
          <span>TOTAL</span>
          <strong>{formatUsageValue(usage.sessionTotal)}</strong>
          <small>sessie</small>
        </div>
      </div>

      <div className="usage-detail-row">
        <Activity />
        <small>
          in {formatUsageValue(usage.currentInput)} · out {formatUsageValue(usage.currentOutput)} · calls {formatUsageValue(usage.modelCalls)}
          {displayModel ? ` · ${displayModel}` : ""}
        </small>
      </div>
    </Panel>
  );
}

export const EMPTY_MODEL_USAGE: ModelUsageState = {
  status: "idle",
  modelId: "",
  currentTotal: null,
  currentInput: null,
  currentOutput: null,
  kind: "unavailable",
  peakTotal: null,
  sessionTotal: null,
  conversationTotal: null,
  modelCalls: null,
  history: [],
};
