import type { ChatMessage, ConversationRunLink } from "@/lib/hades-api";

export type ExecutionStage =
  | "understanding"
  | "retrieval"
  | "plan"
  | "tools"
  | "verification"
  | "completed"
  | "failed"
  | "cancelled";

export type HighLevelExecutionEvent = {
  type: string;
  sequence?: number;
  created_at?: string;
  payload?: Record<string, unknown>;
};

export type ChatToolCall = {
  call_id?: string;
  tool_name?: string;
  plugin_id?: string;
  status?: string;
  summary?: string;
  error?: string;
  [key: string]: unknown;
};

export type AcceptanceCheck = {
  criterion: string;
  met: boolean;
  note?: string;
};

export type ChatExecutionState = {
  status?: string;
  linked_task_id?: string | null;
  run_id?: string | null;
  /** Persisted conversation↔engine links for reconnect (Phase 3A). */
  linked_runs?: ConversationRunLink[];
  target?: string;
  verification?: boolean;
  verification_expected?: boolean;
  route?: Record<string, unknown>;
  executed_route?: Record<string, unknown>;
  verification_notes?: string[];
  acceptance?: string[];
  acceptance_checklist?: AcceptanceCheck[];
  route_profile?: string;
  difficulty_router?: Record<string, unknown>;
  tools?: ChatToolCall[];
  tool_cards?: Array<Record<string, unknown>>;
  reasoning_profile?: string;
  selected_mode?: string;
  effective_policy?: string;
  decision_reason?: string;
  policy_version?: string;
  retrieval?: Record<string, unknown>;
  live_events?: HighLevelExecutionEvent[];
  stream_text?: string;
  working_state?: Record<string, unknown>;
  budget?: Record<string, unknown>;
  /** Backend-owned truth — never derived from assistant prose. */
  grounding?: Record<string, unknown>;
  verification_display?: string;
  result_artifact_id?: string | null;
  persistence?: Array<Record<string, unknown>>;
};

export type PendingAttachment = {
  artifact_id: string;
  filename: string;
  status: string;
};

export type ChatMessageAction = (message: ChatMessage) => void | Promise<void>;
