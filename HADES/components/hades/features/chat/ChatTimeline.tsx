"use client";

import type { ReactNode } from "react";
import { Check, Copy, FileText, GitBranch, Loader2, MessageSquareText, RefreshCcw, Square, Volume2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ChatProvenanceList } from "@/components/hades/chat-provenance";
import { StatusBadge } from "@/components/hades/ui";
import type { ChatExecutionState } from "./types";
import { type ChatMessage, formatDate } from "@/lib/hades-api";

export function ChatTimeline({
  messages,
  loading,
  sending,
  execution,
  streamText,
  copiedId,
  speakingMessageId,
  onCopy,
  onEdit,
  onResend,
  onBranch,
  onRegenerate,
  onSpeak,
  onStopSpeaking,
  onOpenInCanvas,
  renderVoiceActions,
}: {
  messages: ChatMessage[];
  loading: boolean;
  sending: boolean;
  execution: ChatExecutionState | null;
  streamText?: string;
  copiedId: string;
  speakingMessageId?: string | null;
  onCopy: (message: ChatMessage) => void;
  onEdit: (message: ChatMessage) => void;
  onResend: (message: ChatMessage) => void;
  onBranch: (message: ChatMessage) => void;
  onRegenerate: (message: ChatMessage) => void;
  onSpeak: (message: ChatMessage) => void;
  onStopSpeaking: () => void;
  onOpenInCanvas: (content: string) => void;
  renderVoiceActions?: (message: ChatMessage) => ReactNode;
}) {
  return (
    <div className="message-flow live-messages" aria-label="Gespreksberichten">
      {loading ? <div className="page-state" role="status"><Loader2 className="spin" />Lokale gegevens laden…</div> : null}
      {!loading && !messages.length ? (
        <div className="chat-empty">
          <span><MessageSquareText /></span>
          <h2>Waar wil je aan werken?</h2>
          <p>Je bericht en het antwoord worden alleen lokaal opgeslagen. Probeer bijvoorbeeld:</p>
          <ul className="chat-starter-hints">
            <li><code>/help</code> — beschikbare commando&apos;s</li>
            <li><code>/harvest https://…</code> — ebooks/PDF&apos;s downloaden naar Knowledge</li>
            <li><code>/remember …</code> — geheugenvoorstel</li>
            <li><code>@memory:</code> / <code>@knowledge:</code> — gerichte context</li>
          </ul>
        </div>
      ) : null}
      {messages.filter((item) => item.role !== "system").map((message) => {
        const command = typeof message.metadata?.command === "string" ? message.metadata.command : null;
        const commandOk = message.metadata?.command_ok;
        return (
          <article className={`message ${message.role === "user" ? "user-message" : "assistant-message"}`} key={message.id}>
            <span className={`message-avatar ${message.role === "user" ? "user" : "ai"}`} aria-hidden="true">{message.role === "user" ? "U" : "H"}</span>
            <div className="message-body">
              <div className="message-meta">
                <strong>{message.role === "user" ? "Jij" : "HADES"}</strong>
                <time dateTime={message.created_at}>{formatDate(message.created_at)}</time>
                {command ? <StatusBadge tone={commandOk === false ? "warning" : "success"}>cmd:{command}</StatusBadge> : null}
                {(() => {
                  const executionStatus = String(message.metadata?.execution_status || "").toLowerCase();
                  const toolRows = Array.isArray(message.metadata?.tools)
                    ? (message.metadata?.tools as Array<Record<string, unknown>>)
                    : [];
                  const failedTools = toolRows.filter((row) =>
                    ["blocked", "failed", "unavailable"].includes(String(row.status || "").toLowerCase()),
                  );
                  if (executionStatus === "failed" || executionStatus === "cancelled" || executionStatus === "blocked" || executionStatus === "degraded") {
                    return (
                      <StatusBadge tone={executionStatus === "cancelled" ? "warning" : "danger"}>
                        {executionStatus}
                      </StatusBadge>
                    );
                  }
                  if (failedTools.length) {
                    return (
                      <StatusBadge tone="danger">
                        {failedTools.length === 1
                          ? `${String(failedTools[0].status)}: ${String(failedTools[0].tool_name || failedTools[0].plugin_id || "tool")}`
                          : `${failedTools.length} tools geblokkeerd/mislukt`}
                      </StatusBadge>
                    );
                  }
                  return null;
                })()}
              </div>
              <p className="message-content">{message.content}</p>
              {message.role === "assistant" ? (
                <ChatProvenanceList
                  className="message-provenance"
                  retrievalSummary={message.metadata?.retrieval_summary as Record<string, unknown> | undefined}
                  compact
                />
              ) : null}
              <div className="message-actions mt-2 flex flex-wrap items-center gap-1.5">
                <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={() => onCopy(message)} aria-label="Bericht kopiëren">
                  {copiedId === message.id ? <Check /> : <Copy />}
                </Button>
                {message.role === "user" ? (
                  <>
                    <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={() => onEdit(message)}>Bewerken</Button>
                    <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={() => onResend(message)}>Opnieuw versturen</Button>
                    <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={() => onBranch(message)}><GitBranch />Branch here</Button>
                  </>
                ) : (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-1.5 border-[#d8d1c3] bg-[#fbfaf7] px-3 text-[0.68rem] font-semibold text-[#4a4439] shadow-sm hover:bg-[#f2ede4]"
                      onClick={() => onRegenerate(message)}
                    >
                      <RefreshCcw className="h-3.5 w-3.5" />
                      Opnieuw antwoorden
                    </Button>
                    {speakingMessageId === message.id ? (
                      <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={onStopSpeaking} aria-label="Voorlezen stoppen">
                        <Square />Stop
                      </Button>
                    ) : (
                      <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={() => onSpeak(message)} aria-label="Bericht voorlezen">
                        <Volume2 />Voorlezen
                      </Button>
                    )}
                    {message.content.length >= 400 ? (
                      <Button variant="ghost" size="sm" className="h-8 px-2.5 text-[0.68rem]" onClick={() => onOpenInCanvas(message.content)}>
                        <FileText />Open in canvas
                      </Button>
                    ) : null}
                    {renderVoiceActions?.(message)}
                  </>
                )}
              </div>
            </div>
          </article>
        );
      })}
      {sending ? (
        <article className="message assistant-message" role="status" aria-live="polite" aria-busy="true">
          <span className="message-avatar ai" aria-hidden="true">H</span>
          <div className="typing-state">
            <Loader2 className="spin" aria-hidden="true" />
            {streamText || execution?.stream_text ? (
              <span className="stream-provisional">{streamText || execution?.stream_text}</span>
            ) : (
              <span>HADES voert de gekozen route uit…{execution?.tools?.length ? ` · ${execution.tools.length} toolstap(pen)` : ""}</span>
            )}
          </div>
        </article>
      ) : null}
    </div>
  );
}
