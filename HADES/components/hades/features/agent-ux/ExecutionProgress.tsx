"use client";

import { AlertTriangle, Ban, Check, Circle, Loader2 } from "lucide-react";
import type { ExecutionStage, HighLevelExecutionEvent } from "@/components/hades/features/chat/types";

const STEPS: Array<{ id: ExecutionStage; label: string }> = [
  { id: "understanding", label: "Begrijpen" },
  { id: "retrieval", label: "Context ophalen" },
  { id: "plan", label: "Plan" },
  { id: "tools", label: "Tools" },
  { id: "verification", label: "Verificatie" },
  { id: "completed", label: "Afgerond" },
];

function inferStage(events: HighLevelExecutionEvent[], status?: string): ExecutionStage {
  if (status === "failed") return "failed";
  if (status === "cancelled") return "cancelled";
  if (status === "completed" || status === "success") return "completed";
  const types = new Set(events.map((event) => event.type));
  if (types.has("verification") || types.has("verification_completed")) return "verification";
  if (types.has("tool_status") || types.has("tool_call")) return "tools";
  if (types.has("plan_created") || types.has("route_chosen")) return "plan";
  if (types.has("retrieval") || types.has("retrieval_completed")) return "retrieval";
  return "understanding";
}

export function ExecutionProgress({
  events = [],
  status,
  activeStage,
}: {
  events?: HighLevelExecutionEvent[];
  status?: string;
  activeStage?: ExecutionStage;
}) {
  const current = activeStage ?? inferStage(events, status);
  const terminal = current === "failed" || current === "cancelled";
  const currentIndex = terminal ? -1 : STEPS.findIndex((step) => step.id === current);

  return (
    <ol
      className="agent-execution-progress"
      aria-label="Uitvoeringsvoortgang"
      aria-live="polite"
      aria-busy={!terminal && current !== "completed"}
    >
      {STEPS.map((step, index) => {
        const done = current === "completed" || index < currentIndex;
        const active = index === currentIndex;
        const Icon = done ? Check : active ? Loader2 : Circle;
        return (
          <li key={step.id} className={done ? "done" : active ? "active" : ""} aria-current={active ? "step" : undefined}>
            <Icon className={active ? "spin" : undefined} aria-hidden="true" />
            <span>{step.label}</span>
          </li>
        );
      })}
      {terminal ? (
        <li className="terminal">
          {current === "failed" ? <AlertTriangle aria-hidden="true" /> : <Ban aria-hidden="true" />}
          <span>{current === "failed" ? "Mislukt" : "Geannuleerd"}</span>
        </li>
      ) : null}
    </ol>
  );
}
