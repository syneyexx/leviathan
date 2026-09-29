import { useEffect, useRef, useState } from "react";
import { media } from "../../assets/media";
import type {
  AssistantTurnTelemetry,
  ReasoningSummary,
} from "../../types/api";
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
};

export type MessageListProps = {
  messages: ChatDisplayMessage[];
  lastTurn?: MessageListLastTurn | null;
  emptyTitle?: string;
  emptyDetail?: string;
};

function formatElapsed(ms: number | null | undefined): string | null {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return null;
  if (ms >= 1000) {
    const s = ms / 1000;
    return `${s >= 10 ? Math.round(s) : s.toFixed(1).replace(/\.0$/, "")} seconden`;
  }
  return `${Math.round(ms)} ms`;
}

function ReasoningCard({ lastTurn }: { lastTurn: MessageListLastTurn }) {
  const steps = lastTurn.reasoning?.steps?.filter(Boolean) ?? [];
  const [open, setOpen] = useState(steps.length > 0);
  const summary =
    lastTurn.reasoning?.intent ||
    lastTurn.reasoning?.complexity ||
    lastTurn.cognitionPhase ||
    null;
  const elapsed = formatElapsed(lastTurn.telemetry?.latency_ms ?? null);
  const streaming = lastTurn.streaming === "streaming";

  const metaParts: string[] = [];
  if (steps.length > 0) {
    metaParts.push(`${steps.length} stap${steps.length === 1 ? "" : "pen"}`);
  }
  if (elapsed) metaParts.push(elapsed);
  if (lastTurn.cognitionPhase) metaParts.push(lastTurn.cognitionPhase);

  const hasBody = Boolean(summary || steps.length > 0);
  if (!hasBody && !streaming) return null;

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
        {streaming ? "Redeneert…" : "Redenering"}
        {metaParts.length > 0 ? (
          <span className="lv-v2-reason-card__meta">{metaParts.join(" • ")}</span>
        ) : null}
      </button>
      {open ? (
        <div className="lv-v2-reason-card__body">
          {summary ? <p style={{ margin: 0 }}>{summary}</p> : null}
          {steps.length > 0 ? (
            <ul>
              {steps.map((step, index) => (
                <li key={`reason-step-${index}`}>{step}</li>
              ))}
            </ul>
          ) : (
            <p className="lv-v2-muted" style={{ margin: "6px 0 0", fontSize: 12 }}>
              Geen redeneerstappen geleverd door de backend.
            </p>
          )}
        </div>
      ) : null}
    </div>
  );
}

export function MessageList({
  messages,
  lastTurn = null,
  emptyTitle = "Hades AI is gereed.",
  emptyDetail = "Start een gesprek. Persistente chat, reasoning en knowledge retrieval zijn gekoppeld aan de backend.",
}: MessageListProps) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [nearBottom, setNearBottom] = useState(true);

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
    if (!el || !nearBottom) return;
    el.scrollTo({ top: el.scrollHeight, behavior: "auto" });
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
        <div className="lv-v2-empty" role="status">
          <strong>{emptyTitle}</strong>
          <p>{emptyDetail}</p>
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
              <div>
                {message.role === "assistant" ? (
                  <div className="lv-v2-msg__identity">Hades AI</div>
                ) : null}
                {showReasoning && lastTurn ? <ReasoningCard lastTurn={lastTurn} /> : null}
                <div
                  className={`lv-v2-msg__bubble${message.pending ? " is-pending" : ""}${
                    message.error ? " is-error" : ""
                  }`}
                >
                  {message.content}
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
