"use client";

import { AlertTriangle, XCircle } from "lucide-react";
import type { CompletionAssessment } from "@/lib/execution-completion";

export function ExecutionCompletionBanner({ assessment }: { assessment: CompletionAssessment | null }) {
  if (!assessment || assessment.kind === "ok") return null;
  const isWarn = assessment.kind === "unverified";
  const title = assessment.criticBlocked
    ? "Critic blokkeerde voltooiing"
    : isWarn
      ? "Niet geverifieerd"
      : "Niet voltooid";
  return (
    <div className={isWarn ? "completion-banner warn" : "completion-banner incomplete"} role="status">
      {isWarn ? <AlertTriangle /> : <XCircle />}
      <span>
        <strong>{title}</strong>
        <small>{assessment.message}</small>
      </span>
    </div>
  );
}
