/**
 * Shared HADES chat runtime helpers — pure logic used by Lux and FINALBETA.
 * Keep UI out of this module so behaviour can be regression-tested without React.
 */

import type { ConversationRunLink } from "@/lib/hades-api";
import type { ChatExecutionState, PendingAttachment } from "./types";

export const CHAT_MAX_ATTACHMENTS = 10;
export const CHAT_MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024;

export const TERMINAL_RUN_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "rejected",
  "expired",
]);

export type UnifiedStopTarget =
  | { engine: "coding"; run_id: string }
  | { engine: "research"; run_id: string }
  | { engine: "work"; run_id: string };

/** conversation.model_id → active/default → empty. Never inherit a previous conversation's model. */
export function resolveConversationModelId(
  conversationModelId: string | null | undefined,
  activeDefaultModelId: string | null | undefined,
): string {
  if (conversationModelId) return conversationModelId;
  if (activeDefaultModelId) return activeDefaultModelId;
  return "";
}

export function draftAttachmentsFromIds(attachmentIds: string[] | null | undefined): PendingAttachment[] {
  return (attachmentIds || []).map((id) => ({
    artifact_id: id,
    filename: id,
    status: "ready" as const,
  }));
}

export function attachmentIdsFromPending(attachments: PendingAttachment[]): string[] {
  return attachments.map((item) => item.artifact_id).filter(Boolean);
}

export function validateAttachmentBatch(
  currentCount: number,
  files: Array<{ name: string; size: number }>,
): { ok: true } | { ok: false; error: string } {
  if (currentCount + files.length > CHAT_MAX_ATTACHMENTS) {
    return { ok: false, error: `Maximaal ${CHAT_MAX_ATTACHMENTS} bijlagen per bericht.` };
  }
  for (const file of files) {
    if (file.size > CHAT_MAX_ATTACHMENT_BYTES) {
      return { ok: false, error: `${file.name} is groter dan 20 MB.` };
    }
  }
  return { ok: true };
}

export function isTerminalRunStatus(status: string | null | undefined): boolean {
  return TERMINAL_RUN_STATUSES.has(String(status || "").toLowerCase());
}

/** Collect cancellable linked engines for Unified Stop. */
export function collectUnifiedStopTargets(input: {
  linkedRuns?: ConversationRunLink[] | null;
  codingJobIds?: string[];
  researchProjectIds?: string[];
  codingStatuses?: Record<string, string>;
  researchStatuses?: Record<string, string>;
}): UnifiedStopTarget[] {
  const targets: UnifiedStopTarget[] = [];
  const seen = new Set<string>();

  const push = (target: UnifiedStopTarget) => {
    const key = `${target.engine}:${target.run_id}`;
    if (seen.has(key) || !target.run_id) return;
    seen.add(key);
    targets.push(target);
  };

  for (const link of input.linkedRuns || []) {
    if (isTerminalRunStatus(link.status)) continue;
    if (link.run_type === "coding") push({ engine: "coding", run_id: link.run_id });
    else if (link.run_type === "research") push({ engine: "research", run_id: link.run_id });
    else if (link.run_type === "work") push({ engine: "work", run_id: link.run_id });
  }

  for (const jobId of input.codingJobIds || []) {
    const status = input.codingStatuses?.[jobId];
    if (status && ["completed", "failed", "cancelled"].includes(status.toLowerCase())) continue;
    push({ engine: "coding", run_id: jobId });
  }

  for (const projectId of input.researchProjectIds || []) {
    const status = input.researchStatuses?.[projectId];
    if (status && ["completed", "failed", "cancelled"].includes(status.toLowerCase())) continue;
    push({ engine: "research", run_id: projectId });
  }

  return targets;
}

export function shouldIgnoreCancelledCompletion(
  requestId: string,
  cancelledRequestIds: Set<string>,
  executionStatus: string | null | undefined,
): boolean {
  if (!cancelledRequestIds.has(requestId)) return false;
  const status = String(executionStatus || "").toLowerCase();
  return status !== "cancelled" && status !== "failed" && status !== "blocked";
}

/** Ignore stream/progress updates that belong to another conversation than the one on screen. */
export function shouldApplyStreamToSelection(input: {
  selectedConversationId: string | null;
  runConversationId: string | null;
  requestId: string | null;
  activeRequestId: string | null;
}): boolean {
  if (!input.requestId || !input.activeRequestId) return false;
  if (input.requestId !== input.activeRequestId) return false;
  if (!input.selectedConversationId || !input.runConversationId) return false;
  return input.selectedConversationId === input.runConversationId;
}

export function mapSendResultToExecution(
  result: Record<string, unknown>,
  requestId: string,
): ChatExecutionState {
  const executedRoute = (result.executed_route as Record<string, unknown> | undefined) || undefined;
  const route = (result.route as Record<string, unknown> | undefined) || undefined;
  const requestSpec = (result.request_spec as Record<string, unknown> | undefined) || undefined;
  return {
    status: typeof result.execution_status === "string" ? result.execution_status : undefined,
    linked_task_id: (result.linked_task_id as string | null | undefined) ?? null,
    run_id: (typeof result.run_id === "string" && result.run_id) || requestId || null,
    target: String(executedRoute?.actual_target || route?.target || ""),
    verification: Boolean(executedRoute?.verification_called),
    verification_expected: Boolean(route?.require_verification),
    route,
    executed_route: executedRoute,
    verification_notes: Array.isArray(executedRoute?.notes) ? (executedRoute?.notes as string[]) : [],
    acceptance: Array.isArray(result.acceptance_criteria) && result.acceptance_criteria.length
      ? (result.acceptance_criteria as string[])
      : Array.isArray(requestSpec?.acceptance_hints)
        ? (requestSpec?.acceptance_hints as string[])
        : Array.isArray(requestSpec?.acceptance_criteria)
          ? (requestSpec?.acceptance_criteria as string[])
          : [],
    acceptance_checklist: Array.isArray(result.acceptance_checklist)
      ? (result.acceptance_checklist as ChatExecutionState["acceptance_checklist"])
      : [],
    route_profile: String(route?.profile || result.reasoning_profile || ""),
    difficulty_router: (result.difficulty_router as Record<string, unknown> | undefined)
      || (result.reasoning_meta as Record<string, unknown> | undefined)
      || undefined,
    tools: (result.tools as ChatExecutionState["tools"]) || [],
    tool_cards: (result.tool_cards as Array<Record<string, unknown>> | undefined) || [],
    reasoning_profile: typeof result.reasoning_profile === "string" ? result.reasoning_profile : undefined,
    selected_mode: typeof result.selected_mode === "string" ? result.selected_mode : undefined,
    effective_policy: typeof result.effective_policy === "string" ? result.effective_policy : undefined,
    decision_reason: typeof result.decision_reason === "string" ? result.decision_reason : undefined,
    retrieval: (result.retrieval as Record<string, unknown> | undefined) || undefined,
    working_state: (result.working_state as Record<string, unknown> | undefined) || undefined,
    budget: (result.budget as Record<string, unknown> | undefined) || undefined,
    live_events: [],
    stream_text: "",
    grounding: (result.grounding as Record<string, unknown> | undefined) || undefined,
    verification_display: typeof result.verification_display === "string" ? result.verification_display : undefined,
    result_artifact_id: (result.result_artifact_id as string | null | undefined) || null,
    persistence: Array.isArray(result.persistence) ? (result.persistence as Array<Record<string, unknown>>) : [],
    linked_runs: Array.isArray(result.linked_runs) ? (result.linked_runs as ConversationRunLink[]) : undefined,
  };
}

export function markCardsCancelled<T extends { status: string }>(cards: T[]): T[] {
  return cards.map((item) => (
    ["completed", "failed", "cancelled"].includes(item.status.toLowerCase())
      ? item
      : { ...item, status: "cancelled" }
  ));
}

export function newChatRequestId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function conversationListTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = Date.parse(iso);
  if (!Number.isFinite(then)) return "—";
  const date = new Date(then);
  const now = new Date();
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate();
  if (sameDay) {
    return new Intl.DateTimeFormat("nl-NL", { hour: "2-digit", minute: "2-digit" }).format(date);
  }
  return new Intl.DateTimeFormat("nl-NL", { day: "numeric", month: "short" }).format(date);
}

export function estimateTokensFromText(text: string): number {
  const length = text.trim().length;
  return length ? Math.max(1, Math.ceil(length / 4)) : 0;
}

export function contextBudgetTokens(retrieval: Record<string, unknown> | undefined): {
  used: number | null;
  max: number | null;
} {
  const budget = (retrieval?.context_budget as Record<string, unknown> | undefined) || undefined;
  if (!budget) return { used: null, max: null };
  const usedChars = typeof budget.used_chars === "number" ? budget.used_chars : null;
  const maxChars = typeof budget.max_chars === "number" ? budget.max_chars : null;
  return {
    used: usedChars == null ? null : Math.max(0, Math.ceil(usedChars / 4)),
    max: maxChars == null ? null : Math.max(0, Math.ceil(maxChars / 4)),
  };
}

export function budgetToolRounds(budget: Record<string, unknown> | undefined): {
  used: number | null;
  max: number | null;
} {
  if (!budget) return { used: null, max: null };
  return {
    used: typeof budget.tool_rounds === "number" ? budget.tool_rounds : null,
    max: typeof budget.max_tool_rounds === "number" ? budget.max_tool_rounds : null,
  };
}

export function pickCanvasArtifact<T extends { status: string; mime_type: string; name: string; updated_at: string }>(
  items: T[],
  canvasNames = ["canvas.md", "scratchpad.md"],
): T | null {
  const readyText = items.filter((item) => item.status === "ready" && (
    item.mime_type.startsWith("text/") || item.name.endsWith(".md") || item.name.endsWith(".txt")
  ));
  const preferred = readyText.find((item) => canvasNames.includes(item.name.toLowerCase()));
  if (preferred) return preferred;
  return readyText.sort((left, right) => right.updated_at.localeCompare(left.updated_at))[0] ?? null;
}

export function scopePendingApprovals(
  items: Array<Record<string, unknown>>,
  selectedConversationId: string | null,
): Array<Record<string, unknown>> {
  return items.filter((item) => {
    if (String(item.status || "") !== "pending") return false;
    if (!selectedConversationId) return true;
    const cid = item.conversation_id ? String(item.conversation_id) : "";
    return !cid || cid === selectedConversationId;
  });
}
