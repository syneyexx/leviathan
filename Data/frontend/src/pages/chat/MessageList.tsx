import { useEffect, useRef, useState, type ReactNode } from "react";
import { media } from "../../assets/media";
import type {
  AssistantTurnTelemetry,
  ReasoningSummary,
} from "../../types/api";
import type {
  ActivityDisplayMode,
  ActivityProjection,
  DecisionReceipt,
} from "../../types/activity";
import { ActivityTimeline } from "../../components/activity/ActivityTimeline";
import { formatMessageTime } from "./chatHelpers";
import { CapabilityResultCards } from "./CapabilityResultCards";

export type ChatDisplayMessage = {
  role: "user" | "assistant";
  content: string;
  created_at: string | null;
  pending?: boolean;
  error?: boolean;
};

export type MessageListLastTurn = {
  reasoning?: ReasoningSummary | null;
  cognitionPhase?: string | null;
  streaming?: "idle" | "streaming" | "degraded" | "complete" | "failed";
  telemetry?: AssistantTurnTelemetry | null;
  /** Optional measured reasoning elapsed (ms) — never invent. */
  reasoningElapsedMs?: number | null;
  /** Backend-backed activity projection — preferred over legacy steps. */
  activity?: ActivityProjection | null;
  activityMode?: ActivityDisplayMode;
  decisionReceipts?: DecisionReceipt[];
};

export type MessageListProps = {
  messages: ChatDisplayMessage[];
  lastTurn?: MessageListLastTurn | null;
  emptyTitle?: string;
  emptyDetail?: string;
  onActivityModeChange?: (mode: ActivityDisplayMode) => void;
};

/** Minimal safe inline formatting: **bold** + newlines. No HTML injection. */
function renderPlainContent(content: string): ReactNode {
  const lines = content.split("\n");
  return lines.map((line, lineIdx) => {
    const parts: ReactNode[] = [];
    const re = /\*\*(.+?)\*\*/g;
    let last = 0;
    let match: RegExpExecArray | null;
    let key = 0;
    while ((match = re.exec(line)) != null) {
      if (match.index > last) parts.push(line.slice(last, match.index));
      parts.push(<strong key={`b-${lineIdx}-${key++}`}>{match[1]}</strong>);
      last = match.index + match[0].length;
    }
    if (last < line.length) parts.push(line.slice(last));
    return (
      <span key={`l-${lineIdx}`}>
        {lineIdx > 0 ? "\n" : null}
        {parts.length ? parts : line}
      </span>
    );
  });
}

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

export function MessageList({
  messages,
  lastTurn = null,
  emptyTitle = "Hades AI is gereed.",
  emptyDetail = "Start een gesprek. Persistente chat, reasoning en knowledge retrieval zijn gekoppeld aan de backend.",
  onActivityModeChange,
}: MessageListProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [nearBottom, setNearBottom] = useState(true);
  const hydratedRef = useRef(false);
  const prevLenRef = useRef(0);

  function measureNearBottom(el: HTMLDivElement): boolean {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  }

  function scrollToBottom(behavior: ScrollBehavior = "smooth") {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTo({ top: el.scrollHeight, behavior });
    setNearBottom(true);
  }

  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;

    // First paint of a loaded conversation: keep top so user+assistant share the viewport.
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
      {messages.length === 0 ? (
        <div className="lv-v2-chat-empty" role="status">
          <strong>{emptyTitle}</strong>
          <span>{emptyDetail}</span>
        </div>
      ) : (
        messages.map((message, index) => {
          const isLast = index === messages.length - 1;
          const showReasoning =
            message.role === "assistant" &&
            isLast &&
            lastTurn != null &&
            !message.error;
          const showTools =
            message.role === "assistant" &&
            isLast &&
            !message.pending &&
            (lastTurn?.telemetry?.tool_calls?.length ?? 0) > 0;

          return (
            <article
              key={`${message.role}-${index}-${message.created_at ?? "pending"}`}
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
                {showReasoning && lastTurn ? (
                  <ActivityOrLegacy
                    lastTurn={lastTurn}
                    onActivityModeChange={onActivityModeChange}
                  />
                ) : null}
                <div
                  className={`lv-v2-msg__bubble${message.pending ? " is-pending" : ""}${
                    message.error ? " is-error" : ""
                  }`}
                >
                  {renderPlainContent(message.content)}
                </div>
                {showTools ? (
                  <CapabilityResultCards toolCalls={lastTurn?.telemetry?.tool_calls} />
                ) : null}
                <div className="lv-v2-msg__meta">
                  {formatMessageTime(message.created_at) ||
                    (message.pending ? "bezig…" : "")}
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
          Naar beneden
        </button>
      ) : null}
    </div>
  );
}
