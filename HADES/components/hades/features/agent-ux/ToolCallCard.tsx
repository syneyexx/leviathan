"use client";

import { AlertTriangle, CheckCircle2, Loader2, Wrench } from "lucide-react";
import { StatusBadge } from "@/components/hades/ui";
import type { ChatToolCall } from "@/components/hades/features/chat/types";

export function ToolCallCard({ call, compact = false }: { call: ChatToolCall; compact?: boolean }) {
  const status = String(call.status || "unknown");
  const failed = status === "failed" || status === "error" || Boolean(call.error);
  const running = status === "running" || status === "pending";
  const tone = failed ? "danger" : running ? "info" : status === "success" || status === "completed" ? "success" : "warning";
  const Icon = failed ? AlertTriangle : running ? Loader2 : status === "success" || status === "completed" ? CheckCircle2 : Wrench;

  return (
    <article className={`tool-card agent-tool-card${compact ? " agent-tool-card--compact" : ""}`}>
      <header>
        <Icon className={running ? "spin" : undefined} aria-hidden="true" />
        <strong>{String(call.tool_name || call.plugin_id || "tool")}</strong>
        <StatusBadge tone={tone}>{status}</StatusBadge>
      </header>
      {call.summary ? <p>{String(call.summary)}</p> : null}
      {call.error ? <p className="tool-card-error">{String(call.error)}</p> : null}
      {!compact && call.call_id ? <small>Aanroep: <code>{String(call.call_id)}</code></small> : null}
    </article>
  );
}
