import type { ChatToolCall, HighLevelExecutionEvent } from "./types";

/** Presentation cap: distinct tool invocations (not status-update rows). */
export const LIVE_TOOL_CALL_LIMIT = 30;

/** Presentation cap: distinct live events after sequence reconciliation. */
export const LIVE_EVENT_LIMIT = 40;

function normalizedCallId(tool: ChatToolCall): string {
  const raw = tool.call_id;
  if (typeof raw !== "string") return "";
  return raw.trim();
}

function validEventSequence(event: HighLevelExecutionEvent): number | null {
  const sequence = Number(event.sequence);
  if (!Number.isFinite(sequence) || sequence <= 0) return null;
  return sequence;
}

/**
 * Reconcile live tool_status updates into distinct invocations.
 *
 * - Same non-empty call_id → upsert/merge (status transitions stay one row)
 * - New call_id → append
 * - Missing/blank call_id → append conservatively (never collapse by tool_name)
 * - Cap applies after reconciliation (last N unique invocations)
 */
export function mergeChatToolCalls(
  existing: ChatToolCall[] | undefined,
  incoming: ChatToolCall[],
  limit: number = LIVE_TOOL_CALL_LIMIT,
): ChatToolCall[] {
  if (!incoming.length) return existing ? [...existing] : [];
  const merged = [...(existing || [])];
  for (const tool of incoming) {
    const callId = normalizedCallId(tool);
    if (callId) {
      const index = merged.findIndex((row) => normalizedCallId(row) === callId);
      if (index >= 0) {
        merged[index] = { ...merged[index], ...tool, call_id: callId };
        continue;
      }
    }
    merged.push(callId ? { ...tool, call_id: callId } : { ...tool });
  }
  const capped = Math.max(0, Math.floor(limit));
  return capped > 0 ? merged.slice(-capped) : merged;
}

/**
 * Merge live execution events without duplicating the same backend sequence.
 *
 * - Same valid sequence → one event (newer copy replaces in place)
 * - No reliable sequence → append (do not guess identity from type/text)
 * - Cap applies after deduplication
 * - Chronological append order is preserved; in-place replace keeps first-seen position
 */
export function mergeLiveExecutionEvents(
  existing: HighLevelExecutionEvent[] | undefined,
  incoming: HighLevelExecutionEvent[],
  limit: number = LIVE_EVENT_LIMIT,
): HighLevelExecutionEvent[] {
  if (!incoming.length) return existing ? [...existing] : [];
  const merged = [...(existing || [])];
  for (const event of incoming) {
    const sequence = validEventSequence(event);
    if (sequence != null) {
      const index = merged.findIndex((row) => validEventSequence(row) === sequence);
      if (index >= 0) {
        merged[index] = event;
        continue;
      }
    }
    merged.push(event);
  }
  const capped = Math.max(0, Math.floor(limit));
  return capped > 0 ? merged.slice(-capped) : merged;
}
