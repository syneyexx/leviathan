/**
 * useChatTurn — send / stream / cancel with turn state machine,
 * idempotency keys, and rAF-coalesced token updates.
 */
import { useCallback, useRef, useState, type Dispatch, type SetStateAction } from "react";
import { api } from "../../../api/client";
import { displayMessageContent, normalizeMessage } from "../../../api/chatContract";
import { ActivityClientProjector } from "../../../lib/activityProjector";
import {
  chatErrorUserMessage,
  classifyChatError,
} from "../../../lib/chat/errorTaxonomy";
import { reasoningModeForApi, type ReasoningModeId } from "../../../lib/chat/reasoningModes";
import {
  chatTurnToStreamingBadge,
  isBusyChatTurn,
  tryTransitionChatTurn,
  type ChatTurnUiState,
} from "../../../lib/chat/turnStateMachine";
import { formatJobStateLabel, normalizeJobStatus } from "../../../lib/jobStatus";
import { deriveAssistantTelemetry } from "../../chatTelemetry";
import type {
  ActivityDisplayMode,
  ActivityProjection,
  DecisionReceipt,
} from "../../../types/activity";
import { parseActivityProjection } from "../../../types/activity";
import type {
  AssistantTurnTelemetry,
  ChatResponse,
  KnowledgeSource,
  ReasoningSummary,
} from "../../../types/api";
import type { ThreadMessage } from "./useConversationThread";

export type LastTurnMeta = {
  turnId: string | null;
  chatRunId: string | null;
  model: string | null;
  intent: string | null;
  complexity: string | null;
  knowledgeCount: number | null;
  streaming: "idle" | "streaming" | "degraded" | "complete" | "failed";
  turnState: ChatTurnUiState;
  reasoning: ReasoningSummary | null;
  knowledgeSources: KnowledgeSource[];
  cognitionMode: string | null;
  cognitionStatus: string | null;
  cognitionPhase: string | null;
  language: string | null;
  languageSource: string | null;
  reasoningMode: string | null;
  memoryCount: number | null;
  verification: string | null;
  telemetry: AssistantTurnTelemetry | null;
  activity: ActivityProjection | null;
  activityMode: ActivityDisplayMode;
  decisionReceipts: DecisionReceipt[];
};

export const EMPTY_TURN: LastTurnMeta = {
  turnId: null,
  chatRunId: null,
  model: null,
  intent: null,
  complexity: null,
  knowledgeCount: null,
  streaming: "idle",
  turnState: "IDLE",
  reasoning: null,
  knowledgeSources: [],
  cognitionMode: null,
  cognitionStatus: null,
  cognitionPhase: null,
  language: null,
  languageSource: null,
  reasoningMode: null,
  memoryCount: null,
  verification: null,
  telemetry: null,
  activity: null,
  activityMode: "detailed",
  decisionReceipts: [],
};

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
    return crypto.randomUUID();
  }
  return `idem-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export type UseChatTurnArgs = {
  getConversationId: () => string | null;
  ensureConversationId: () => Promise<string | null>;
  setMessages: Dispatch<SetStateAction<ThreadMessage[]>>;
  reasoningMode: ReasoningModeId;
  selectedModelId: string | null;
  collaborationStrategy: "direct" | "team";
  toolPolicy?: Record<string, unknown> | null;
  onToast: (message: string) => void;
  onConversationId: (id: string) => void;
  onAfterTurn: (conversationId: string) => Promise<void>;
  onTeamPanel: (panel: Record<string, unknown> | null) => void;
};

export type SendTurnOptions = {
  artifactIds?: string[];
};

/** Map durable chat-run / turn status → coarse UI outcome. */
export function mapRunStatusToOutcome(status: {
  turn?: { run_state?: string | null } | null;
  run?: { state?: string | null } | null;
}): "completed" | "failed" | "cancelled" | "running" | "unknown" {
  const turnState = String(status.turn?.run_state || "").toUpperCase();
  const runState = String(status.run?.state || "").toUpperCase();
  if (turnState === "COMPLETED" || runState === "COMPLETED") return "completed";
  if (turnState === "CANCELLED" || runState === "CANCELLED") return "cancelled";
  if (
    turnState === "FAILED" ||
    turnState === "INTERRUPTED" ||
    runState === "FAILED"
  ) {
    return "failed";
  }
  if (
    turnState === "ACCEPTED" ||
    turnState === "RUNNING" ||
    turnState === "STREAMING" ||
    runState === "PLANNING" ||
    runState === "EXECUTING" ||
    runState === "RUNNING"
  ) {
    return "running";
  }
  return "unknown";
}

export function useChatTurn(args: UseChatTurnArgs) {
  const [lastTurn, setLastTurn] = useState<LastTurnMeta>(EMPTY_TURN);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const abortRef = useRef<AbortController | null>(null);
  const turnIdRef = useRef<string | null>(null);
  const chatRunIdRef = useRef<string | null>(null);
  const tokenBufferRef = useRef("");
  const rafRef = useRef<number | null>(null);
  const turnStateRef = useRef<ChatTurnUiState>("IDLE");

  const setTurnState = useCallback((next: ChatTurnUiState) => {
    const applied = tryTransitionChatTurn(turnStateRef.current, next);
    turnStateRef.current = applied;
    setLastTurn((prev) => ({
      ...prev,
      turnState: applied,
      streaming: chatTurnToStreamingBadge(applied),
    }));
    return applied;
  }, []);

  const flushTokenBuffer = useCallback(() => {
    rafRef.current = null;
    const chunk = tokenBufferRef.current;
    if (!chunk) return;
    tokenBufferRef.current = "";
    args.setMessages((current) => {
      const copy = [...current];
      const last = copy[copy.length - 1];
      if (last?.pending && last.role === "assistant") {
        const base = last.content === "Thinking…" ? "" : last.content;
        copy[copy.length - 1] = { ...last, content: `${base}${chunk}` };
      }
      return copy;
    });
  }, [args]);

  const enqueueToken = useCallback(
    (token: string) => {
      tokenBufferRef.current += token;
      if (rafRef.current == null) {
        rafRef.current = requestAnimationFrame(flushTokenBuffer);
      }
    },
    [flushTokenBuffer],
  );

  const resetTurn = useCallback(() => {
    turnStateRef.current = "IDLE";
    turnIdRef.current = null;
    chatRunIdRef.current = null;
    tokenBufferRef.current = "";
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    setLastTurn(EMPTY_TURN);
  }, []);

  const reconcile = useCallback(async (): Promise<
    "completed" | "failed" | "cancelled" | "running" | "unknown"
  > => {
    const runId = chatRunIdRef.current;
    if (!runId) return "unknown";
    try {
      const status = await api.getChatRunStatus(runId);
      const outcome = mapRunStatusToOutcome(status);
      if (status.turn?.turn_id) {
        turnIdRef.current = status.turn.turn_id;
      }
      setLastTurn((prev) => ({
        ...prev,
        turnId: status.turn?.turn_id ?? prev.turnId,
        chatRunId: status.chat_run_id ?? prev.chatRunId,
        model: status.turn?.effective_model ?? prev.model,
        reasoningMode:
          status.turn?.effective_reasoning_mode ?? prev.reasoningMode,
      }));
      if (outcome === "completed") setTurnState("COMPLETED");
      else if (outcome === "cancelled") setTurnState("CANCELLED");
      else if (outcome === "failed") setTurnState("FAILED");
      else if (outcome === "running") setTurnState("STREAMING");
      return outcome;
    } catch {
      return "unknown";
    }
  }, [setTurnState]);

  const cancel = useCallback(async () => {
    const turnId = turnIdRef.current;
    const chatRunId = chatRunIdRef.current;
    setTurnState("CANCELLING");
    abortRef.current?.abort();
    abortRef.current = null;
    if (turnId || chatRunId) {
      try {
        await api.cancelChat({
          turn_id: turnId,
          chat_run_id: chatRunId,
          reason: "user_cancel",
        });
      } catch {
        /* best-effort cancel */
      }
    }
    // Authoritative outcome from control plane when available.
    const outcome = await reconcile();
    if (outcome === "unknown" || outcome === "running") {
      setTurnState("CANCELLED");
    }
    busyRef.current = false;
    setBusy(false);
    args.onToast("Antwoord gestopt.");
  }, [args, reconcile, setTurnState]);

  const send = useCallback(
    async (textRaw: string, options?: SendTurnOptions) => {
      const text = textRaw.trim();
      if (!text || busyRef.current) return;
      busyRef.current = true;
      setBusy(true);
      setTurnState("PREPARING");

      let activeId = args.getConversationId();
      if (!activeId) {
        activeId = await args.ensureConversationId();
        if (!activeId) {
          busyRef.current = false;
          setBusy(false);
          setTurnState("FAILED");
          setTurnState("IDLE");
          return;
        }
      }

      const idempotencyKey = newIdempotencyKey();
      const artifactIds = options?.artifactIds?.filter(Boolean) ?? [];
      args.setMessages((current) => [
        ...current,
        {
          id: -Date.now(),
          role: "user",
          content: text,
          created_at: new Date().toISOString(),
        },
        {
          id: -Date.now() - 1,
          role: "assistant",
          content: "Thinking…",
          created_at: null,
          pending: true,
        },
      ]);

      const activityProjector = new ActivityClientProjector();
      setTurnState("RUNNING");
      setLastTurn((prev) => ({
        ...prev,
        streaming: "streaming",
        activity: activityProjector.project(),
        decisionReceipts: [],
      }));

      const abort = new AbortController();
      abortRef.current = abort;
      tokenBufferRef.current = "";

      try {
        let doneOnce = false;
        const data = await api.chatStream(
          text,
          {
            conversationId: activeId,
            modelId: args.selectedModelId,
            reasoningMode: reasoningModeForApi(args.reasoningMode),
            collaborationStrategy:
              args.collaborationStrategy === "team" ? "team" : null,
            idempotencyKey,
            toolPolicy: args.toolPolicy ?? null,
            ...(artifactIds.length ? { artifactIds } : {}),
          },
          {
            onMeta: (meta) => {
              const turnId =
                typeof meta.turn_id === "string"
                  ? meta.turn_id
                  : typeof meta.chat_turn === "object" &&
                      meta.chat_turn &&
                      typeof (meta.chat_turn as { turn_id?: unknown }).turn_id === "string"
                    ? String((meta.chat_turn as { turn_id: string }).turn_id)
                    : null;
              if (turnId) turnIdRef.current = turnId;
              if (typeof meta.chat_run_id === "string") {
                chatRunIdRef.current = meta.chat_run_id;
              }
              setTurnState("STREAMING");
              setLastTurn((prev) => ({
                ...prev,
                turnId: turnId ?? prev.turnId,
                chatRunId:
                  typeof meta.chat_run_id === "string"
                    ? meta.chat_run_id
                    : prev.chatRunId,
              }));
              const projection = parseActivityProjection(meta.activity);
              if (projection) {
                activityProjector.ingestProjection(projection);
                setLastTurn((prev) => ({
                  ...prev,
                  activity: activityProjector.project(),
                }));
              }
              if (meta.reasoning && typeof meta.reasoning === "object") {
                setLastTurn((prev) => ({
                  ...prev,
                  reasoning: meta.reasoning as ReasoningSummary,
                }));
              }
            },
            onActivity: (payload) => {
              if (
                payload &&
                typeof payload === "object" &&
                Array.isArray((payload as { tree?: unknown }).tree)
              ) {
                activityProjector.ingestProjection(parseActivityProjection(payload));
              } else {
                activityProjector.ingest(payload);
              }
              setLastTurn((prev) => ({
                ...prev,
                activity: activityProjector.project(),
              }));
            },
            onToken: (token) => {
              setTurnState("STREAMING");
              enqueueToken(token);
            },
            onSnapshot: (snapshotText) => {
              if (rafRef.current != null) {
                cancelAnimationFrame(rafRef.current);
                rafRef.current = null;
              }
              tokenBufferRef.current = "";
              args.setMessages((current) => {
                const copy = [...current];
                const last = copy[copy.length - 1];
                if (last?.pending && last.role === "assistant") {
                  copy[copy.length - 1] = { ...last, content: snapshotText };
                }
                return copy;
              });
            },
            onDone: () => {
              doneOnce = true;
            },
            onCancelled: () => {
              setTurnState("CANCELLED");
            },
            onCapabilityEvent: (event, payload) => {
              const cap = String(
                payload.capability_id || payload.module_id || payload.job_id || event,
              );
              let statusLabel = "";
              if (event.startsWith("job.")) {
                const raw =
                  payload.state ||
                  payload.status ||
                  payload.phase ||
                  event.replace(/^job\./, "");
                statusLabel = formatJobStateLabel(normalizeJobStatus(String(raw)));
                const pct = payload.progress ?? payload.percent;
                if (typeof pct === "number" && Number.isFinite(pct)) {
                  statusLabel = `${statusLabel} · ${Math.round(pct * (pct <= 1 ? 100 : 1))}%`;
                }
              } else {
                const status = String(payload.status || payload.phase || "");
                statusLabel = status && status !== event ? status : "";
              }
              args.setMessages((current) => {
                const copy = [...current];
                const last = copy[copy.length - 1];
                if (last?.pending && last.role === "assistant") {
                  const prev = last.content === "Thinking…" ? "" : last.content;
                  const line = `[${event}] ${cap}${statusLabel ? ` · ${statusLabel}` : ""}`;
                  const withoutStatus = prev.replace(/\n?\[[^\]]+\].*$/s, "").trimEnd();
                  copy[copy.length - 1] = {
                    ...last,
                    content: withoutStatus ? `${withoutStatus}\n${line}` : line,
                  };
                }
                return copy;
              });
            },
          },
          { signal: abort.signal },
        );

        if (rafRef.current != null) {
          cancelAnimationFrame(rafRef.current);
          rafRef.current = null;
          flushTokenBuffer();
        }

        if (data.turn_id) turnIdRef.current = data.turn_id;
        if (data.chat_run_id) chatRunIdRef.current = data.chat_run_id;
        args.onConversationId(data.conversation_id);
        await finalizeTurn({
          data,
          doneOnce,
          activityProjector,
          reasoningMode: args.reasoningMode,
          setLastTurn,
          setTurnState,
          setMessages: args.setMessages,
          onTeamPanel: args.onTeamPanel,
          onToast: args.onToast,
        });
        await args.onAfterTurn(data.conversation_id || activeId);
      } catch (error) {
        const classified = classifyChatError(error);
        activityProjector.markDisconnected();
        // Ambiguous network: reconcile via getChatRunStatus before declaring failure.
        let reconciled: "completed" | "failed" | "cancelled" | "running" | "unknown" =
          "unknown";
        if (!classified.userCancel && chatRunIdRef.current) {
          reconciled = await reconcile();
        }
        if (classified.userCancel || classified.code === "CANCELLED" || reconciled === "cancelled") {
          setTurnState("CANCELLED");
        } else if (reconciled === "completed") {
          setTurnState("COMPLETED");
          setLastTurn((prev) => ({
            ...prev,
            streaming: "complete",
            activity: activityProjector.project(),
          }));
          if (activeId) await args.onAfterTurn(activeId);
          return;
        } else if (reconciled === "running") {
          setTurnState("DEGRADED");
          args.onToast("Stream interrupted — run still active on server; reconciling…");
        } else {
          setTurnState("FAILED");
        }
        setLastTurn((prev) => ({
          ...prev,
          activity: activityProjector.project(),
        }));
        args.onTeamPanel(null);
        args.setMessages((current) => {
          const withoutPending = current.filter((item) => !item.pending);
          const streamed = current.find((item) => item.pending && item.role === "assistant");
          const provisional =
            streamed && streamed.content && streamed.content !== "Thinking…"
              ? streamed.content
              : null;
          return [
            ...withoutPending,
            {
              id: -Date.now(),
              role: "assistant",
              content: provisional
                ? `${provisional}\n\n[Provisional — ${classified.message}]`
                : chatErrorUserMessage(classified),
              created_at: new Date().toISOString(),
              error: true,
              provisional: true,
            },
          ];
        });
        if (!classified.userCancel && reconciled !== "completed") {
          args.onToast(chatErrorUserMessage(classified));
        }
        if (activeId) {
          await args.onAfterTurn(activeId);
        }
      } finally {
        busyRef.current = false;
        setBusy(false);
        abortRef.current = null;
      }
    },
    [args, enqueueToken, flushTokenBuffer, reconcile, setTurnState],
  );

  return {
    lastTurn,
    setLastTurn,
    busy: busy || isBusyChatTurn(lastTurn.turnState),
    busyRef,
    send,
    cancel,
    reconcile,
    resetTurn,
    turnIdRef,
    chatRunIdRef,
  };
}

async function finalizeTurn(opts: {
  data: ChatResponse;
  doneOnce: boolean;
  activityProjector: ActivityClientProjector;
  reasoningMode: ReasoningModeId;
  setLastTurn: Dispatch<SetStateAction<LastTurnMeta>>;
  setTurnState: (s: ChatTurnUiState) => ChatTurnUiState;
  setMessages: Dispatch<SetStateAction<ThreadMessage[]>>;
  onTeamPanel: (panel: Record<string, unknown> | null) => void;
  onToast: (message: string) => void;
}) {
  const { data, doneOnce, activityProjector } = opts;
  const protocolFailure =
    typeof data.protocol_failure === "string" ? data.protocol_failure : null;
  const isProvisional = Boolean(data.provisional) || Boolean(protocolFailure);
  const assistantNormalized = normalizeMessage(data.assistant_message);
  const assistantContent = assistantNormalized
    ? displayMessageContent(assistantNormalized.content)
    : "";

  opts.setMessages((current) => {
    const withoutPending = current.filter((item) => !item.pending);
    if (doneOnce || assistantNormalized) {
      const streamedProvisional = current.find(
        (item) => item.pending && item.role === "assistant",
      );
      const streamedText =
        streamedProvisional && streamedProvisional.content !== "Thinking…"
          ? streamedProvisional.content
          : "";
      const content =
        assistantContent ||
        streamedText ||
        (protocolFailure
          ? `Stream protocol failure (${protocolFailure}). Partial reply may be incomplete.`
          : "");
      return [
        ...withoutPending,
        {
          id: assistantNormalized?.id ?? -Date.now(),
          role: "assistant" as const,
          content,
          created_at: assistantNormalized?.created_at ?? new Date().toISOString(),
          error: Boolean(protocolFailure),
          provisional: isProvisional,
        },
      ];
    }
    return withoutPending;
  });

  if (protocolFailure) {
    opts.setTurnState("FAILED");
    opts.onToast(`Chat protocol failure: ${protocolFailure}`);
    opts.onTeamPanel(null);
    return;
  }

  const degraded = Boolean(data.truth?.streaming_degraded);
  opts.setTurnState(degraded ? "DEGRADED" : "COMPLETED");
  const cog = data.cognition && typeof data.cognition === "object" ? data.cognition : null;
  const cogDecision =
    cog && "decision" in cog && cog.decision && typeof cog.decision === "object"
      ? (cog.decision as Record<string, unknown>)
      : null;
  const cogStatus =
    cog && "status" in cog && typeof cog.status === "string" ? cog.status : null;
  const telemetry = deriveAssistantTelemetry(data);
  const verificationLabel =
    telemetry.verification_mode && telemetry.verification_mode !== "NONE"
      ? telemetry.verification_passed === true
        ? `${telemetry.verification_mode} · passed`
        : telemetry.verification_passed === false
          ? `${telemetry.verification_mode} · failed`
          : `${telemetry.verification_mode}`
      : data.quality?.pass === false
        ? "issues found"
        : data.quality
          ? "ok"
          : "not required";

  opts.setLastTurn((prev) => ({
    ...prev,
    turnId: data.turn_id ?? data.chat_turn?.turn_id ?? prev.turnId,
    chatRunId: data.chat_run_id ?? prev.chatRunId,
    model: telemetry.model || data.model || null,
    intent: data.reasoning?.intent ?? null,
    complexity: data.reasoning?.complexity ?? null,
    knowledgeCount: telemetry.knowledge_hits ?? data.knowledge_sources?.length ?? null,
    streaming: degraded ? "degraded" : "complete",
    reasoning: data.reasoning ?? null,
    knowledgeSources: data.knowledge_sources ?? [],
    cognitionMode:
      telemetry.cognition_mode ||
      (cogDecision && typeof cogDecision.mode === "string"
        ? String(cogDecision.mode)
        : null),
    cognitionStatus: telemetry.cognition_status || cogStatus,
    cognitionPhase:
      cogStatus &&
      ["REASONING", "PERCEIVING", "VERIFYING", "EXECUTING"].includes(cogStatus)
        ? cogStatus.charAt(0) + cogStatus.slice(1).toLowerCase()
        : null,
    language: data.language?.response_language ?? null,
    languageSource: data.language?.source ?? null,
    reasoningMode: data.reasoning?.mode?.effective ?? opts.reasoningMode,
    memoryCount: telemetry.memory_hits ?? data.memory_sources?.length ?? null,
    verification: verificationLabel,
    telemetry,
    activity: (() => {
      if (data.activity) {
        activityProjector.ingestProjection(parseActivityProjection(data.activity));
      }
      if (Array.isArray(data.activity_events)) {
        activityProjector.ingestMany(data.activity_events);
      }
      return activityProjector.project();
    })(),
    activityMode: "detailed",
    decisionReceipts: Array.isArray(data.decision_receipts)
      ? (data.decision_receipts as DecisionReceipt[])
      : [],
  }));

  const teamPayload = data.team;
  if (teamPayload && typeof teamPayload === "object") {
    opts.onTeamPanel(teamPayload);
  } else {
    opts.onTeamPanel(null);
  }
}
