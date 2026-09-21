export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Message = {
  id: number;
  conversation_id: string;
  role: "system" | "user" | "assistant";
  content: string;
  created_at: string;
};

export type ReasoningSummary = {
  intent: string;
  complexity: string;
  use_knowledge: boolean;
  steps: string[];
};

export type KnowledgeSource = {
  id: string;
  title: string;
  source: string;
};

export type ChatResponse = {
  conversation_id: string;
  user_message: Message;
  assistant_message: Message;
  model: string;
  reasoning: ReasoningSummary;
  knowledge_sources: KnowledgeSource[];
  neuro?: unknown;
  cortex?: unknown;
};

export type HealthResponse = {
  ok: boolean;
  version: string;
  database: string;
  reasoning_enabled: boolean;
  llm: {
    available: boolean;
    model: string | null;
    base_url: string;
    error?: string;
  };
  agents?: { enabled: boolean };
  approvals?: { pending: number };
  jobs?: { queued: number };
  capabilities?: { registered: number };
  chaos?: { plan: { enabled: boolean } };
  backup?: { count: number };
  verification_reports?: { recent: number };
  neuro?: {
    enabled: boolean;
    associative_memory?: boolean;
    process_critic?: boolean;
    residual_injection?: boolean;
    cortex?: boolean;
    memory_tiers?: boolean;
    residual_supported?: boolean;
    residual_kind?: string;
    absorb?: Record<string, number>;
  };
  module_manager?: {
    enabled: boolean;
    subprocess_isolation?: boolean;
    modules?: number;
  };
  training_recipes?: { registered: number };
};

export type ReleaseGateReport = {
  ready: boolean;
  checks: Array<{
    gate_id: string;
    name: string;
    severity: string;
    passed: boolean;
    detail: string;
  }>;
  truth?: Record<string, boolean>;
};

export type SecurityAuditReport = {
  findings: Array<{
    finding_id: string;
    severity: string;
    title: string;
    detail: string;
    passed: boolean;
  }>;
  summary: { total: number; passed: number; failed: number };
  truth?: Record<string, boolean>;
};

export type MasterGateReport = {
  status: string;
  phase_span: string;
  checks: Array<{
    check_id: string;
    name: string;
    status: string;
    detail: string;
  }>;
  truth?: Record<string, boolean>;
};

export type MetricsSnapshot = {
  collected_at: number;
  counters: Record<string, number>;
  gauges: Record<string, number>;
  labels: Record<string, string>;
  truth?: Record<string, boolean>;
};

export type VerificationReport = {
  report_id: string;
  outcome: string;
  created_at: string;
  run_id?: string | null;
  job_id?: string | null;
};

export type BackupManifest = {
  backup_id: string;
  created_at: string;
  size_bytes: number;
  schema_version: number;
  artifacts_copied: number;
};

export type NeuroResidualStatus = {
  supports_residuals: boolean;
  hook_points: unknown[];
  runtime?: unknown;
  kind?: string;
  truth?: Record<string, boolean>;
};

export type NeuroAssessmentResponse = {
  assessment: unknown;
  reasoning?: ReasoningSummary;
};

export type TrainingRecipe = {
  recipe_id: string;
  name: string;
  objective: string;
  loss: string;
  formulation: string;
};

export type SoakReport = {
  iterations: number;
  passed: number;
  failed: number;
  duration_ms: number;
  steps: Array<{ name: string; ok: boolean; detail: string; duration_ms: number }>;
  notes?: string[];
  truth?: Record<string, boolean>;
};

export type ApiErrorBody = {
  detail?: string | { msg: string }[];
};
