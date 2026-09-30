/**
 * Project public runtime events → knowledge activation for Brain ↔ Chat sync.
 * Only activates retrieval-backed node ids — never keyword-match guesses.
 */

import type { RuntimeEvent } from "../../types/api";

export const KNOWLEDGE_ACTIVATION_CATEGORY = "brain";
export const KNOWLEDGE_ACTIVATION_NAME = "knowledge_activation";

export type KnowledgeActivationPhase =
  | "standby"
  | "retrieving"
  | "activating"
  | "complete"
  | "cancelled"
  | "unavailable"
  | "partial";

export type KnowledgeActivationRequest = {
  requestId: string;
  conversationId: string | null;
  runId: string | null;
  sequence: number;
  startedSequence?: number;
  eventId: string;
  phase: KnowledgeActivationPhase;
  hitCount: number | null;
  nodeIds: string[];
  identifiersAvailable: boolean;
  createdAtMs: number;
  message: string | null;
};

export type KnowledgeActivationState = {
  /** Request currently driving the helix highlight. */
  followedRequestId: string | null;
  requests: KnowledgeActivationRequest[];
  activeNodeIds: string[];
  phase: KnowledgeActivationPhase;
  hitCount: number | null;
  identifiersAvailable: boolean;
  detail: string;
  connectionNote: string | null;
};

export type KnowledgeActivationEventPayload = {
  conversation_id?: unknown;
  request_id?: unknown;
  run_id?: unknown;
  phase?: unknown;
  hit_count?: unknown;
  node_ids?: unknown;
  identifiers_available?: unknown;
  truth?: unknown;
};

function asString(v: unknown): string | null {
  return typeof v === "string" && v.trim() ? v.trim() : null;
}

function asNumber(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() && Number.isFinite(Number(v))) return Number(v);
  return null;
}

function asStringList(v: unknown): string[] {
  if (!Array.isArray(v)) return [];
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of v) {
    const s = asString(item);
    if (!s || seen.has(s)) continue;
    seen.add(s);
    out.push(s);
  }
  return out;
}

export function isKnowledgeActivationEvent(event: RuntimeEvent): boolean {
  return (
    event.category === KNOWLEDGE_ACTIVATION_CATEGORY &&
    event.name === KNOWLEDGE_ACTIVATION_NAME
  );
}

export function parseKnowledgeActivationEvent(
  event: RuntimeEvent,
): KnowledgeActivationRequest | null {
  if (!isKnowledgeActivationEvent(event)) return null;
  const payload = (event.payload || {}) as KnowledgeActivationEventPayload;
  const requestId =
    asString(payload.request_id) ||
    asString(event.request_id) ||
    asString(payload.run_id) ||
    asString(event.run_id) ||
    event.event_id;
  const nodeIds = asStringList(payload.node_ids);
  const identifiersAvailable =
    typeof payload.identifiers_available === "boolean"
      ? payload.identifiers_available
      : nodeIds.length > 0;
  const phaseRaw = asString(payload.phase)?.toLowerCase() ?? "complete";
  const phase: KnowledgeActivationPhase =
    phaseRaw === "retrieving" ||
    phaseRaw === "activating" ||
    phaseRaw === "cancelled" ||
    phaseRaw === "unavailable" ||
    phaseRaw === "partial" ||
    phaseRaw === "standby" ||
    phaseRaw === "complete"
      ? phaseRaw
      : "complete";

  return {
    requestId,
    conversationId: asString(payload.conversation_id) || asString(event.correlation_id),
    runId: asString(payload.run_id) || asString(event.run_id),
    sequence: event.sequence,
    eventId: event.event_id,
    phase,
    hitCount: asNumber(payload.hit_count),
    nodeIds: identifiersAvailable ? nodeIds : [],
    identifiersAvailable,
    createdAtMs: event.created_at_ms,
    message: asString(event.message),
  };
}

/**
 * Merge activation events with sequence/event-id dedupe.
 * Late events for a non-followed request never overwrite the followed request's nodes.
 */
export function reduceKnowledgeActivation(
  prev: KnowledgeActivationState,
  events: readonly RuntimeEvent[],
  opts?: {
    followedRequestId?: string | null;
    /** Prefer selecting this conversation when auto-following. */
    preferredConversationId?: string | null;
  },
): KnowledgeActivationState {
  const byRequest = new Map<string, KnowledgeActivationRequest>();
  for (const r of prev.requests) byRequest.set(r.requestId, r);

  const seenEventIds = new Set(prev.requests.map((r) => r.eventId));
  let maxSeq = Math.max(0, ...prev.requests.map((r) => r.sequence));

  for (const event of [...events].sort((a, b) => a.sequence - b.sequence)) {
    if (seenEventIds.has(event.event_id)) continue;
    if (event.sequence < maxSeq - 500) continue; // ignore far-stale reconnect noise lightly
    const parsed = parseKnowledgeActivationEvent(event);
    if (!parsed) continue;
    seenEventIds.add(event.event_id);
    maxSeq = Math.max(maxSeq, parsed.sequence);
    const existing = byRequest.get(parsed.requestId);
    if (existing && existing.sequence > parsed.sequence) continue;
    byRequest.set(parsed.requestId, { ...parsed, startedSequence: existing?.startedSequence ?? existing?.sequence ?? parsed.sequence });
  }

  const requests = [...byRequest.values()].sort((a, b) => a.sequence - b.sequence);
  const trimmed = requests.length > 40 ? requests.slice(requests.length - 40) : requests;

  let followed =
    opts?.followedRequestId !== undefined ? opts.followedRequestId : prev.followedRequestId;

  if (followed && !trimmed.some((r) => r.requestId === followed)) {
    followed = null;
  }

  if (!followed && trimmed.length) {
    const newest = [...trimmed].sort((a, b) => (a.startedSequence ?? a.sequence) - (b.startedSequence ?? b.sequence));
    const preferred = opts?.preferredConversationId;
    const preferMatch = preferred
      ? [...newest].reverse().find((r) => r.conversationId === preferred)
      : null;
    followed = (preferred ? preferMatch : newest[newest.length - 1])?.requestId ?? null;
  }

  const active = followed ? trimmed.find((r) => r.requestId === followed) : null;
  if (!active) {
    return {
      followedRequestId: followed,
      requests: trimmed,
      activeNodeIds: [],
      phase: "standby",
      hitCount: null,
      identifiersAvailable: false,
      detail: "Het geheugen wacht op een vraag.",
      connectionNote: null,
    };
  }

  let detail: string;
  if (active.phase === "cancelled" || active.phase === "unavailable") {
    detail = active.phase === "cancelled" ? "Retrieval geannuleerd." : "Retrieval niet beschikbaar.";
  } else if (active.phase === "retrieving") {
    detail = "Retrieval loopt — bronnen worden opgehaald.";
  } else if (!active.identifiersAvailable) {
    detail =
      active.hitCount != null
        ? `Fase ${active.phase} · ${active.hitCount} hits · Geen node-identificatie beschikbaar`
        : `Fase ${active.phase} · Geen node-identificatie beschikbaar`;
  } else if (active.nodeIds.length === 0) {
    detail = "Retrieval voltooid zonder herkenbare kennisnodes.";
  } else {
    detail = `${active.nodeIds.length} kennisnode(s) geactiveerd voor request ${active.requestId.slice(0, 8)}…`;
  }

  return {
    followedRequestId: followed,
    requests: trimmed,
    activeNodeIds: active.identifiersAvailable && active.phase !== "cancelled" && active.phase !== "unavailable" ? active.nodeIds : [],
    phase: active.phase,
    hitCount: active.hitCount,
    identifiersAvailable: active.identifiersAvailable,
    detail,
    connectionNote: null,
  };
}

export const EMPTY_KNOWLEDGE_ACTIVATION: KnowledgeActivationState = {
  followedRequestId: null,
  requests: [],
  activeNodeIds: [],
  phase: "standby",
  hitCount: null,
  identifiersAvailable: false,
  detail: "Het geheugen wacht op een vraag.",
  connectionNote: null,
};
