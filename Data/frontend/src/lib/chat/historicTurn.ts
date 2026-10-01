/**
 * Historic turn hydration helpers — tool receipts + activity from durable ChatTurn.
 * Never invents telemetry; only surfaces backend-persisted fields.
 */
import type { AssistantToolCallTelemetry, ChatTurn } from "../../types/api";
import type { ActivityProjection } from "../../types/activity";
import { parseActivityProjection } from "../../types/activity";

export function resolveTurnForMessage(
  message: { id?: number | null; turn?: ChatTurn | null },
  turnsByMessageId: Record<string, ChatTurn> = {},
): ChatTurn | null {
  return (
    message.turn ||
    (message.id != null ? turnsByMessageId[String(message.id)] ?? null : null) ||
    null
  );
}

function asToolCall(raw: unknown): AssistantToolCallTelemetry | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const row = raw as Record<string, unknown>;
  const capabilityId = row.capability_id ?? row.module_id;
  if (capabilityId == null || String(capabilityId).trim() === "") return null;
  return {
    capability_id: String(capabilityId),
    status: String(row.status || "UNKNOWN"),
    success: typeof row.success === "boolean" ? row.success : row.success == null ? null : Boolean(row.success),
    duration_ms: typeof row.duration_ms === "number" ? row.duration_ms : null,
    receipt_id: row.receipt_id != null ? String(row.receipt_id) : null,
    error: row.error != null ? String(row.error) : null,
    summary: row.summary != null ? String(row.summary) : null,
    provider: row.provider != null ? String(row.provider) : null,
    module_id: row.module_id != null ? String(row.module_id) : null,
    result_count: typeof row.result_count === "number" ? row.result_count : null,
    source_count: typeof row.source_count === "number" ? row.source_count : null,
    artifact_refs: Array.isArray(row.artifact_refs)
      ? row.artifact_refs.map(String).filter(Boolean)
      : [],
    parts: Array.isArray(row.parts)
      ? (row.parts.filter((p) => p && typeof p === "object") as Array<Record<string, unknown>>)
      : [],
  };
}

/**
 * Prefer live last-turn telemetry for the active message; otherwise use
 * durable turn.tool_calls / metadata.tool_calls when present.
 */
export function resolveHistoricToolCalls(
  turn: ChatTurn | null | undefined,
  options?: {
    isLast?: boolean;
    liveToolCalls?: AssistantToolCallTelemetry[] | null;
  },
): AssistantToolCallTelemetry[] {
  const live = options?.liveToolCalls;
  if (options?.isLast && live && live.length > 0) {
    return live.filter((c) => c?.capability_id);
  }

  const fromTurn = turn?.tool_calls;
  if (Array.isArray(fromTurn) && fromTurn.length > 0) {
    return fromTurn.map(asToolCall).filter((c): c is AssistantToolCallTelemetry => !!c);
  }

  const meta = turn?.metadata;
  if (meta && typeof meta === "object" && !Array.isArray(meta)) {
    const nested = (meta as { tool_calls?: unknown }).tool_calls;
    if (Array.isArray(nested) && nested.length > 0) {
      return nested.map(asToolCall).filter((c): c is AssistantToolCallTelemetry => !!c);
    }
  }

  // Receipt IDs alone are not enough for CapabilityResultCards (needs capability_id).
  // Fall through to live only when last and available.
  if (options?.isLast && live?.length) {
    return live.filter((c) => c?.capability_id);
  }
  return [];
}

/**
 * Historic activity only when the turn carries a real activity projection.
 * activity_ref alone is a pointer — do not invent a timeline from it.
 */
export function resolveHistoricActivity(
  turn: ChatTurn | null | undefined,
): ActivityProjection | null {
  if (!turn) return null;
  if (turn.activity && typeof turn.activity === "object") {
    return parseActivityProjection(turn.activity);
  }
  const meta = turn.metadata;
  if (meta && typeof meta === "object" && !Array.isArray(meta)) {
    const nested = (meta as { activity?: unknown }).activity;
    if (nested && typeof nested === "object") {
      return parseActivityProjection(nested);
    }
  }
  return null;
}

/** ArtifactStore IDs persisted on the turn — references only, never invent paths. */
export function resolveHistoricArtifactIds(turn: ChatTurn | null | undefined): string[] {
  if (!turn) return [];
  const ids = turn.artifact_ids;
  if (!Array.isArray(ids)) return [];
  return ids.map(String).map((s) => s.trim()).filter(Boolean);
}

