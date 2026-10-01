import { useEffect, useRef, useState } from "react";
import { media } from "../../assets/media";
import type {
  AssistantTurnTelemetry,
  ChatTurn,
  ReasoningSummary,
} from "../../types/api";
import type {
  ActivityDisplayMode,
  ActivityProjection,
  DecisionReceipt,
} from "../../types/activity";
import { ActivityTimeline } from "../../components/activity/ActivityTimeline";
import {
  resolveHistoricActivity,
  resolveHistoricArtifactIds,
  resolveHistoricToolCalls,
  resolveTurnForMessage,
} from "../../lib/chat/historicTurn";
import { SafeMarkdown } from "../../lib/chat/safeMarkdown";
import { formatMessageTime } from "./chatHelpers";
import { CapabilityResultCards } from "./CapabilityResultCards";
import type { ThreadMessage } from "./hooks/useConversationThread";

export type ChatDisplayMessage = {
  id?: number;
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
  pending?: boolean;
  error?: boolean;
  turn?: ChatTurn | null;
};

export type MessageListStreamingBadge =
  | "idle"
  | "streaming"
  | "degraded"
  | "complete"
  | "failed"
  | "cancelled";

export type MessageListLastTurn = {
  reasoning?: ReasoningSummary | null;
  cognitionPhase?: string | null;
  streaming?: MessageListStreamingBadge;
  telemetry?: AssistantTurnTelemetry | null;
  /** Optional measured reasoning elapsed (ms) — never invent. */
  reasoningElapsedMs?: number | null;
  /** Backend-backed activity projection — preferred over legacy steps. */
  activity?: ActivityProjection | null;
  activityMode?: ActivityDisplayMode;
  decisionReceipts?: DecisionReceipt[];
};

export type MessageListProps = {
  messages: Array<ChatDisplayMessage | ThreadMessage>;
  lastTurn?: MessageListLastTurn | null;
  /** Per-assistant-message turn metadata (message id → turn). */
  turnsByMessageId?: Record<string, ChatTurn>;
  emptyTitle?: string;
  emptyDetail?: string;
  hasMoreOlder?: boolean;
  loadingOlder?: boolean;
  onLoadOlder?: () => void;
  onActivityModeChange?: (mode: ActivityDisplayMode) => void;
  onOpenInspector?: () => void;
};

/**
 * Legacy fallback when the backend has not yet emitted ActivityEvents.
 * Renders planned step titles only — never invents live lifecycle.
 */
function LegacyReasoningFallback({ lastTurn }: { lastTurn: MessageListLastTurn }) {
  const steps = lastTurn.reasoning?.steps?.filter(Boolean) ?? [];
  const [open, setOpen] = useState(steps.length > 0);
  const streaming = lastTurn.streaming === "streaming";
  if (!steps.length && !streaming) return null;

  const titleMap: Record<string, string> = {
    understand_request: "Request interpreted",
    retrieve_atlas_context: "Atlas context retrieval",
    deep_recall_hydrate: "Deep recall hydration",
    retrieve_relevant_knowledge: "Knowledge retrieval",
    structure_response: "Response structure planned",
    generate_answer: "Answer synthesis",
  };

  return (
    <div className="lv-v2-reason-card">
      <button
        type="button"
        className="lv-v2-reason-card__toggle"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true">
          <path d="M12 3a6 6 0 0 1 4.5 9.8V16a.5.5 0 0 1-.5.5h-8a.5.5 0 0 1-.5-.5v-3.2A6 6 0 0 1 12 3z" />
          <path d="M9 19h6" />
        </svg>
        {streaming ? "Activity…" : "Planned steps"}
        <span className="lv-v2-reason-card__meta">compatibility</span>
      </button>
      {open ? (
        <div className="lv-v2-reason-card__body">
          <p style={{ margin: 0 }}>
            Planned execution path from the reasoning engine. Live lifecycle was not
            provided for this turn.
          </p>
          <ul>
            {steps.map((step, index) => (
              <li key={`reason-step-${index}`}>{titleMap[step] || step}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}

function ActivityOrLegacy({
  lastTurn,
  onActivityModeChange,
}: {
  lastTurn: MessageListLastTurn;
  onActivityModeChange?: (mode: ActivityDisplayMode) => void;
}) {
  const hasActivity =
    (lastTurn.activity?.events?.length ?? 0) > 0 ||
    (lastTurn.activity?.tree?.length ?? 0) > 0 ||
    lastTurn.streaming === "streaming";

  if (hasActivity && lastTurn.activity) {
    return (
      <ActivityTimeline
        projection={lastTurn.activity}
        mode={lastTurn.activityMode ?? "detailed"}
        streaming={lastTurn.streaming === "streaming"}
        onModeChange={onActivityModeChange}
        decisionReceipts={lastTurn.decisionReceipts}
      />
    );
  }
  if (hasActivity && lastTurn.streaming === "streaming") {
    return (
      <ActivityTimeline
        projection={
          lastTurn.activity ?? {
            operationId: "",
            highestSequence: 0,
            tree: [],
            events: [],
          }
        }
        mode={lastTurn.activityMode ?? "detailed"}
        streaming
        onModeChange={onActivityModeChange}
      />
    );
  }
  return <LegacyReasoningFallback lastTurn={lastTurn} />;
}

function HistoricActivity({
  activity,
  activityMode,
  onActivityModeChange,
}: {
  activity: ActivityProjection;
  activityMode?: ActivityDisplayMode;
  onActivityModeChange?: (mode: ActivityDisplayMode) => void;
}) {
  const hasRows =
    (activity.events?.length ?? 0) > 0 || (activity.tree?.length ?? 0) > 0;
  if (!hasRows) return null;
  return (
    <ActivityTimeline
      projection={activity}
      mode={activityMode ?? "detailed"}
      streaming={false}
      onModeChange={onActivityModeChange}
    />
  );
}

function TurnMetaChip({ turn }: { turn: ChatTurn }) {
  const model = turn.effective_model || turn.requested_model;
  const mode = turn.effective_reasoning_mode || turn.requested_reasoning_mode;
  const state = turn.run_state;
  const owner = turn.response_owner;
  const collab = turn.collaboration_strategy;
  const bits = [model, mode, owner, collab, state].filter(Boolean);
  const measured: string[] = [];
  if (turn.knowledge_hit_count != null) measured.push(`knowledge=${turn.knowledge_hit_count}`);
  if (turn.memory_hit_count != null) measured.push(`memory=${turn.memory_hit_count}`);
  if (turn.evidence_hit_count != null) measured.push(`evidence=${turn.evidence_hit_count}`);
  if (turn.verification_state) measured.push(`verify=${turn.verification_state}`);
  if (!bits.length && !measured.length) return null;
  return (
    <div className="lv-v2-msg__meta" style={{ opacity: 0.75 }}>
      {[...bits, ...measured].join(" · ")}
    </div>
  );
}

export function MessageList({
  messages,
  lastTurn = null,
  turnsByMessageId = {},
  emptyTitle = "Hades AI is gereed.",
  emptyDetail = "Start een gesprek. Persistente chat, reasoning en knowledge retrieval zijn gekoppeld aan de backend.",
  hasMoreOlder = false,
  loadingOlder = false,
  onLoadOlder,
  onActivityModeChange,
  onOpenInspector,
}: MessageListProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [nearBottom, setNearBottom] = useState(true);
  const hydratedRef = useRef(false);
  const prevLenRef = useRef(0);
  const conversationKeyRef = useRef<string>("");

  function measureNearBottom(el: HTMLDivElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scrollToBottom(behavior: ScrollBehavior = "smooth") {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    setNearBottom(true);
  }

  // Reset hydration when message identity changes (new conversation).
  useEffect(() => {
    const key = messages[0] ? `${messages[0].id ?? 0}:${messages[0].created_at ?? ""}` : "empty";
    if (key !== conversationKeyRef.current) {
      conversationKeyRef.current = key;
      hydratedRef.current = false;
      prevLenRef.current = 0;
    }
  }, [messages]);

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;

    if (!hydratedRef.current && messages.length > 0) {
      hydratedRef.current = true;
      prevLenRef.current = messages.length;
      if (lastTurn?.streaming !== "streaming") {
        el.scrollTo({ top: 0, behavior: "auto" });
        setNearBottom(measureNearBottom(el));
        return;
      }
    }

    const grew = messages.length > prevLenRef.current;
    prevLenRef.current = messages.length;
    if ((grew || lastTurn?.streaming === "streaming") && nearBottom) {
      el.scrollTo({ top: el.scrollHeight, behavior: "auto" });
    }
  }, [messages, lastTurn?.streaming, nearBottom]);

  return (
    <div
      className="lv-v2-chat-messages"
      ref={scrollerRef}
      onScroll={(e) => {
        setNearBottom(measureNearBottom(e.currentTarget));
      }}
    >
      {hasMoreOlder ? (
        <div className="lv-v2-chat-load-older">
          <button
            type="button"
            disabled={loadingOlder}
            onClick={() => onLoadOlder?.()}
          >
            {loadingOlder ? "Oudere berichten laden…" : "Oudere berichten laden"}
          </button>
        </div>
      ) : null}

      {messages.length === 0 ? (
        <div className="lv-v2-chat-empty" role="status">
          <strong>{emptyTitle}</strong>
          <span>{emptyDetail}</span>
        </div>
      ) : (
        messages.map((message, index) => {
          const isLast = index === messages.length - 1;
          const messageTurn = resolveTurnForMessage(message, turnsByMessageId);
          const showLiveReasoning =
            message.role === "assistant" &&
            isLast &&
            lastTurn != null &&
            !message.error;
          const historicActivity =
            message.role === "assistant" && !showLiveReasoning && !message.error
              ? resolveHistoricActivity(messageTurn)
              : null;
          const toolCalls = resolveHistoricToolCalls(messageTurn, {
            isLast,
            liveToolCalls: lastTurn?.telemetry?.tool_calls,
          });
          const showTools =
            message.role === "assistant" &&
            !message.pending &&
            toolCalls.length > 0;

          return (
            <article
              key={`${message.role}-${message.id ?? index}-${message.created_at ?? "pending"}`}
              className={`lv-v2-msg lv-v2-msg--${message.role}`}
              data-pending={message.pending ? "true" : undefined}
              data-error={message.error ? "true" : undefined}
            >
              {message.role === "user" ? (
                <img className="lv-v2-msg__avatar" src={media.avatar} alt="" />
              ) : (
                <span className="lv-v2-msg__avatar-fallback" aria-hidden="true">
                  HA
                </span>
              )}
              <div className="lv-v2-msg__stack">
                {message.role === "assistant" ? (
                  <div className="lv-v2-msg__identity">Hades AI</div>
                ) : null}
                {showLiveReasoning && lastTurn ? (
                  <ActivityOrLegacy
                    lastTurn={lastTurn}
                    onActivityModeChange={onActivityModeChange}
                  />
                ) : null}
                {historicActivity ? (
                  <HistoricActivity
                    activity={historicActivity}
                    activityMode={lastTurn?.activityMode}
                    onActivityModeChange={onActivityModeChange}
                  />
                ) : null}
                <div
                  className={`lv-v2-msg__bubble${message.pending ? " is-pending" : ""}${
                    message.error ? " is-error" : ""
                  }`}
                >
                  {message.pending && message.content === "Thinking…" ? (
                    message.content
                  ) : (
                    <SafeMarkdown content={message.content} />
                  )}
                </div>
                {showTools ? <CapabilityResultCards toolCalls={toolCalls} /> : null}
                {messageTurn ? <TurnMetaChip turn={messageTurn} /> : null}
                {(() => {
                  const artifactIds = resolveHistoricArtifactIds(messageTurn);
                  if (!artifactIds.length) return null;
                  return (
                    <ul className="lv-v2-msg__artifacts" aria-label="Turn artifacts">
                      {artifactIds.map((id) => (
                        <li key={id}>
                          <a
                            href={`/api/artifacts/${encodeURIComponent(id)}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            title={id}
                          >
                            artifact {id.slice(0, 8)}
                          </a>
                        </li>
                      ))}
                    </ul>
                  );
                })()}
                <div className="lv-v2-msg__meta">
                  {formatMessageTime(message.created_at) ||
                    (message.pending ? "bezig…" : "")}
                  {message.role === "assistant" && onOpenInspector ? (
                    <>
                      {" · "}
                      <button
                        type="button"
                        className="lv-v2-msg__inspector-link"
                        onClick={onOpenInspector}
                      >
                        Inspector
                      </button>
                    </>
                  ) : null}
                </div>
              </div>
            </article>
          );
        })
      )}

      {!nearBottom && messages.length > 0 ? (
        <button
          type="button"
          className="lv-v2-chat-jump"
          onClick={() => scrollToBottom("smooth")}
        >
          Jump to latest
        </button>
      ) : null}
    </div>
  );
}
