import type { AgentSignal } from "../../types/api";

export type SignalFilterId =
  | "ALL"
  | "TASKS"
  | "HANDOFFS"
  | "VERIFY"
  | "KNOWLEDGE"
  | "BLOCKS"
  | "WARNINGS"
  | "ERRORS";

export const SIGNAL_FILTERS: Array<{ id: SignalFilterId; label: string }> = [
  { id: "ALL", label: "ALL" },
  { id: "TASKS", label: "TASKS" },
  { id: "HANDOFFS", label: "HANDOFFS" },
  { id: "VERIFY", label: "VERIFY" },
  { id: "KNOWLEDGE", label: "KNOWLEDGE" },
  { id: "BLOCKS", label: "BLOCKS" },
  { id: "WARNINGS", label: "WARNINGS" },
  { id: "ERRORS", label: "ERRORS" },
];

const FILTER_TYPES: Record<SignalFilterId, string[] | null> = {
  ALL: null,
  TASKS: ["TASK_REQUEST", "TASK_HANDOFF"],
  HANDOFFS: ["TASK_HANDOFF"],
  VERIFY: ["VERIFY_REQUEST", "VERIFIED", "REJECTED", "CHALLENGE"],
  KNOWLEDGE: ["KNOWLEDGE_CANDIDATE", "MEMORY_CANDIDATE", "FINDING", "EVIDENCE", "HYPOTHESIS"],
  BLOCKS: ["BLOCK", "UNBLOCK", "CANCEL"],
  WARNINGS: ["WARNING"],
  ERRORS: ["ERROR"],
};

export function matchesSignalFilter(signal: AgentSignal, filter: SignalFilterId): boolean {
  const types = FILTER_TYPES[filter];
  if (!types) return true;
  return types.includes(String(signal.signalType || "").toUpperCase());
}

export function formatSignalConfidence(confidence: number | null | undefined): string | null {
  if (confidence == null || Number.isNaN(confidence)) return null;
  return `${Math.round(Math.max(0, Math.min(1, confidence)) * 100)}%`;
}
