"use client";

import { VerificationPanel } from "@/components/hades/features/agent-ux";
import type { ChatExecutionState } from "./types";

export function VerificationSummary({ execution }: { execution: ChatExecutionState | null }) {
  if (!execution) return null;
  const grounding = execution.grounding || {};
  const truthNotes = [
    ...(execution.verification_notes || []),
    execution.verification_display ? `weergave:${execution.verification_display}` : "",
    typeof grounding.executed === "boolean" ? `tools_uitgevoerd:${grounding.executed ? "ja" : "nee"}` : "",
    typeof grounding.tool_success === "boolean" ? `tool_succes:${grounding.tool_success ? "ja" : "nee"}` : "",
    typeof grounding.saved_knowledge_count === "number"
      ? `kennis_geverifieerd:${grounding.saved_knowledge_count}`
      : "",
    typeof grounding.persistence_verified === "boolean"
      ? `persistentie_geverifieerd:${grounding.persistence_verified ? "ja" : "nee"}`
      : "",
  ].filter(Boolean);
  return (
    <VerificationPanel
      called={execution.verification}
      expected={execution.verification_expected}
      notes={truthNotes}
      checks={execution.acceptance_checklist}
    />
  );
}
