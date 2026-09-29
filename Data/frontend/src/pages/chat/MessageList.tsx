import { useEffect, useRef, useState, type ReactNode } from "react";
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
  /** Optional measured reasoning elapsed (ms) — never invent. */
  reasoningElapsedMs?: number | null;
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

function ReasoningCard({ lastTurn }: { lastTurn: MessageListLastTurn }) {
  const steps = lastTurn.reasoning?.steps?.filter(Boolean) ?? [];
  const [open, setOpen] = useState(steps.length > 0);
  const summary =
    lastTurn.cognitionPhase ||
    (lastTurn.reasoning?.complexity === "deep"
      ? "Stap-voor-stap analyse"
      : lastTurn.reasoning?.complexity) ||
    null;
  const elapsed = formatElapsed(lastTurn.reasoningElapsedMs ?? null);
  const streaming = lastTurn.streaming === "streaming";

  const metaParts: string[] = [];
  if (steps.length > 0) {
    metaParts.push(`${steps.length} stap${steps.length === 1 ? "" : "pen"}`);
  }
  if (elapsed) metaParts.push(elapsed);

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
            <p style={{ margin: "6px 0 0", fontSize: 12, opacity: 0.7 }}>
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
                {showReasoning && lastTurn ? <ReasoningCard lastTurn={lastTurn} /> : null}
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
