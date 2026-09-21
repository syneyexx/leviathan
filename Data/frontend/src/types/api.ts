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
  detail?: string | { msg: string }[] | { code?: string; message?: string; retryable?: boolean };
};

export type CapabilityState = "supported" | "unsupported" | "unknown" | "unverified";

export type ModelCapabilities = {
  chat: CapabilityState;
  reasoning: CapabilityState;
  coding: CapabilityState;
  toolCalling: CapabilityState;
  structuredOutput: CapabilityState;
  vision: CapabilityState;
  embeddings: CapabilityState;
  streaming: CapabilityState;
};

export type ModelDescriptor = {
  id: string;
  displayName: string;
  providerId: string;
  runtimeId?: string | null;
  source: string;
  objectType?: string | null;
  architecture?: string | null;
  family?: string | null;
  parameterCount?: number | null;
  quantization?: string | null;
  format?: string | null;
  diskSizeBytes?: number | null;
  contextWindow?: number | null;
  maxOutputTokens?: number | null;
  capabilities: ModelCapabilities;
  lifecycleState: string;
  health: string;
  active: boolean;
  loaded: boolean | null;
  localPath?: string | null;
  endpoint?: string | null;
  lastDiscoveredAt?: string | null;
  lastUsedAt?: string | null;
  tags?: string[];
  metadata?: Record<string, unknown>;
};

export type ModelProfile = {
  modelId: string;
  temperature: number;
  topP: number;
  topK: number;
  maxTokens: number;
  repeatPenalty: number;
  seed: number;
  systemPrompt: string;
  active: boolean;
  updatedAt?: string | null;
};

export type RuntimeCapabilities = {
  discoverModels: boolean;
  importModel: boolean;
  downloadModel: boolean;
  loadModel: boolean;
  unloadModel: boolean;
  deleteModel: boolean;
  listLoadedModels: boolean;
  inference: boolean;
  streaming: boolean;
  embeddings: boolean;
  toolCalling: boolean;
  structuredOutput: boolean;
  vision: boolean;
  runtimeMetrics: boolean;
  loadOptions: string[];
};

export type ModelProvider = {
  id: string;
  name: string;
  type: string;
  endpoint: string;
  enabled: boolean;
  health: string;
  apiKeyConfigured: boolean;
  autoConnect: boolean;
  timeoutSeconds: number;
  refreshIntervalSeconds: number;
  lastSuccessfulAt?: string | null;
  lastError?: string | null;
  lastLatencyMs?: number | null;
  lastCheckAt?: string | null;
  capabilities: RuntimeCapabilities;
  metadata?: Record<string, unknown>;
};

export type ModelsStatus = {
  runtime: string;
  availableModels: number;
  activeModel: string | null;
  loadedModels: number;
  discoveryLatencyMs: number | null;
  gatewayHealth: string;
  lastRefreshAt?: string | null;
  lastRefreshError?: string | null;
  providerCount?: number;
  offlineProviders?: ModelProvider[];
};

export type GatewaySnapshot = {
  modelsInUse: string[];
  activeCalls: number;
  queueDepth: number;
  capacity: {
    globalLimit: number | null;
    globalInflight: number;
    providerLimits: Record<string, number | null>;
    modelLimits: Record<string, number | null>;
    queueDepth: number;
  };
  lastFallbackReason: string | null;
  callsFailed: number;
  capacityTimeouts: number;
  lastError: string | null;
  lastSelectedModel?: string | null;
  lastTraceId?: string | null;
};

export type RouterConfig = {
  fallbackOrder: string[];
  roleModelOverrides: Record<string, string>;
  cloudFallbackAllowed: boolean;
  streaming: boolean;
  streamProvisionalText: boolean;
  progressEventsEnabled: boolean;
};

export type DownloadJob = {
  id: string;
  state: string;
  source: string;
  repositoryId?: string | null;
  revision?: string | null;
  destination?: string | null;
  bytesDownloaded?: number | null;
  totalBytes?: number | null;
  speedBps?: number | null;
  etaSeconds?: number | null;
  error?: string | null;
  createdAt?: string | null;
  updatedAt?: string | null;
  modelId?: string | null;
};

export type VerifiedCapability = {
  capability: string;
  declared: CapabilityState;
  verified: CapabilityState;
  lastTestedAt?: string | null;
  detail?: string | null;
};

