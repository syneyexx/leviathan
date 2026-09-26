export type Conversation = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  pinned?: boolean;
};

export type Message = {
  id: number;
  conversation_id: string;
  role: "system" | "user" | "assistant";
  content: string;
  created_at: string;
};

export type ChatOptions = {
  conversationId?: string | null;
  modelId?: string | null;
  preferredRole?: string | null;
  reasoningMode?: string | null;
  /** Orthogonal to reasoning depth: direct | team */
  collaborationStrategy?: string | null;
  stream?: boolean;
};

export type ReasoningSummary = {
  intent: string;
  complexity: string;
  use_knowledge: boolean;
  steps: string[];
  mode?: {
    requested?: string;
    effective?: string;
    source?: string;
    prefer_reasoning_model?: boolean;
  };
};

export type LanguageDecisionMeta = {
  mode?: string;
  response_language?: string;
  source?: string;
  reason?: string;
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
  memory_sources?: Array<{ memory_id?: string }>;
  language?: LanguageDecisionMeta;
  behavior?: Record<string, unknown>;
  quality?: {
    pass?: boolean;
    issues?: Array<{ type: string; severity: string; detail?: string }>;
  };
  neuro?: unknown;
  cortex?: unknown;
  cognition?: CognitionRunStatus | { error?: string; truth?: Record<string, boolean> };
  assistant_telemetry?: AssistantTurnTelemetry;
  streamed?: boolean;
  truth?: {
    neural_signal_is_not_authority?: boolean;
    residual_implemented?: boolean;
    residual_applied?: boolean;
    streaming_degraded?: boolean;
    model_output_is_not_evidence?: boolean;
    [key: string]: boolean | undefined;
  };
};

/** Public tool-call row for Chat Tools tab — status/duration/receipt only. */
export type AssistantToolCallTelemetry = {
  capability_id: string;
  status: string;
  success?: boolean | null;
  duration_ms?: number | null;
  receipt_id?: string | null;
  error?: string | null;
  summary?: string | null;
};

/** Specialist delegation row for Chat Agents tab. */
export type AssistantAgentDelegationTelemetry = {
  agent_kind: string;
  status: string;
  success?: boolean | null;
  summary?: string | null;
  artifact_refs?: string[];
  evidence_refs?: string[];
  idempotent_reuse?: boolean;
};

export type AssistantWebSourceTelemetry = {
  title?: string | null;
  url?: string | null;
  source?: string | null;
  snippet?: string | null;
  error?: string | null;
  error_code?: string | null;
  honest_failure?: boolean;
};

/** Real turn telemetry for Chat Context/Tools/Agents panels — never mocked. */
export type AssistantTurnTelemetry = {
  model?: string | null;
  behavior_hash?: string | null;
  behavior_profile_id?: string | null;
  behavior_version?: string | null;
  context_budget?: number | null;
  context_used?: number | null;
  context_tokens?: number | null;
  brain_hits?: number;
  knowledge_hits?: number;
  memory_hits?: number;
  evidence_hits?: number;
  tools_invoked?: string[];
  tool_calls?: AssistantToolCallTelemetry[];
  agents?: string[];
  agent_delegations?: AssistantAgentDelegationTelemetry[];
  gi_specialists?: string[];
  web_sources?: AssistantWebSourceTelemetry[];
  verification_mode?: string | null;
  verification_passed?: boolean | null;
  factuality?: Record<string, unknown> | null;
  execution_class?: string | null;
  cognition_mode?: string | null;
  cognition_status?: string | null;
  latency_ms?: number | null;
  usage?: Record<string, number> | null;
  budgets?: Record<string, number> | null;
  web_used?: boolean;
  truth?: Record<string, boolean>;
};

export type CognitionHealth = {
  enabled: boolean;
  shadow_default: boolean;
  iterative: boolean;
  belief_enabled: boolean;
  neuro_enabled: boolean;
  delegation_enabled: boolean;
  experience_learning: boolean;
  active_runs: number;
  tracked_runs: number;
  delegation_handlers: string[];
  truth?: Record<string, boolean>;
};

export type CognitionRunStatus = {
  run_id: string;
  task_id?: string;
  status: string;
  stage?: string;
  mode?: string | null;
  strategy?: string | null;
  goal?: string;
  domain?: string;
  uncertainty?: number;
  belief_counts?: Record<string, number>;
  working_memory_count?: number;
  budgets?: Record<string, number>;
  usage?: Record<string, number>;
  plan?: {
    strategy?: string;
    steps?: Array<{ step_id: string; objective: string; status: string }>;
  } | null;
  observations?: Array<{ kind: string; summary: string; success?: boolean | null }>;
  actions?: Array<{ kind: string; rationale?: string | null; capability_id?: string | null }>;
  cancel_requested?: boolean;
  cancel_acknowledged?: boolean;
  shadow?: boolean;
  error?: string | null;
  verification_passed?: boolean | null;
  completion?: Record<string, unknown> | null;
  factuality?: Record<string, unknown> | null;
  response_preview?: string;
  response?: string | null;
  execution_class?: string | null;
  verification_mode?: string | null;
  gi_specialists?: string[];
  behavior_hash?: string | null;
  behavior_profile_id?: string | null;
  behavior_profile_version?: string | null;
  context_budget?: number | null;
  context_used?: number | null;
  retrieval_hits?: {
    brain?: number;
    knowledge?: number;
    memory?: number;
    evidence?: number;
  };
  tools_invoked?: string[];
  tool_calls?: AssistantToolCallTelemetry[];
  active_agents?: Array<string | null | undefined>;
  agent_delegations?: AssistantAgentDelegationTelemetry[];
  web_sources?: AssistantWebSourceTelemetry[];
  latency_ms?: number | null;
  truth?: Record<string, boolean>;
};

export type HealthResponse = {
  ok: boolean;
  liveness?: string;
  posture?: string;
  version: string;
  database: string;
  reasoning_enabled: boolean;
  product_truth?: {
    overall?: string;
    components?: Array<{
      id: string;
      name: string;
      type: string;
      status: string;
      detail?: string;
      measured?: boolean;
    }>;
    vocabulary?: string[];
    truth?: Record<string, boolean>;
  };
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
    residual_orchestrator?: boolean;
    cortex_blocks?: boolean;
    contrastive_training?: boolean;
    soak_long?: boolean;
    training_real_worker?: boolean;
    residual_supported?: boolean;
    residual_kind?: string;
    residual_production?: boolean;
    residual_load_weights?: boolean;
    residual_hook_layers?: number[];
    cortex_max_k?: number;
    working_memory_load?: number;
    working_memory_slots?: number;
    memory_tier0_max_slots?: number;
    absorb?: Record<string, number>;
    contrastive_ready?: boolean;
    contrastive_method_default?: string;
    chat_streaming?: boolean;
    chat_sse?: boolean;
    streaming_posture?: string;
    residual_applied_count?: number;
    residual_degraded_count?: number;
    truth?: Record<string, boolean>;
  };
  knowledge?: {
    data_root?: string;
    documents?: number;
    embedding_provider?: string;
    embedding_available?: boolean;
    embedding_status?: Record<string, unknown>;
    rag_v3?: boolean;
    deep_recall?: boolean;
    why_library?: boolean;
    reranker_available?: boolean;
    deep_recall_budget?: number;
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
  residual_production?: boolean;
  residual_orchestrator?: boolean;
  load_weights?: boolean;
  hook_layers?: number[];
  cortex_max_k?: number;
  orchestrator_telemetry?: Record<string, number>;
  recent_receipts?: unknown[];
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
  mode?: string;
  long_soak_enabled?: boolean;
  truth?: Record<string, boolean>;
};

export type ApiErrorBody = {
  detail?: string | { msg: string }[] | { code?: string; message?: string; retryable?: boolean };
};

export type CapabilityState = "supported" | "unsupported" | "unknown" | "unverified" | "unmeasured";

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

export type ModelRuntimeBinding = {
  modelId: string;
  runtimeKind: string;
  runtimeProviderId?: string | null;
  backendModelId?: string | null;
  localPath?: string | null;
  managed: boolean;
  servabilityState: string;
  servabilityReason?: string | null;
  runtimeCapabilities?: RuntimeCapabilities | null;
  metadata?: Record<string, unknown>;
};

export type ResidencyPolicy = {
  modelId: string;
  policy: "KEEP_HOT" | "IDLE_UNLOAD" | "WARM_THEN_UNLOAD" | string;
  idleUnloadSeconds: number;
  fullUnloadSeconds?: number | null;
  pinned: boolean;
  loadOptions?: {
    contextLength?: number | null;
    gpuOffloadLayers?: number | null;
    gpuMemoryLimitBytes?: number | null;
    cpuThreads?: number | null;
    batchSize?: number | null;
    flashAttention?: boolean | null;
  } | null;
  updatedAt?: string | null;
};

export type ResourceEstimate = {
  ramNeededBytes?: number | null;
  ramNeededProvenance: string;
  vramNeededBytes?: number | null;
  vramNeededProvenance: string;
  ramAvailableBytes?: number | null;
  ramAvailableProvenance: string;
  vramAvailableBytes?: number | null;
  vramAvailableProvenance: string;
  headroomRamBytes?: number | null;
  headroomVramBytes?: number | null;
  verdict: string;
  reasons: string[];
  details?: Record<string, unknown>;
  truth?: Record<string, boolean>;
};

export type ComputeDeviceInfo = {
  stableDeviceId: string;
  ordinal?: number | null;
  vendor?: string | null;
  name?: string | null;
  uuid?: string | null;
  pciBusId?: string | null;
  backend?: string | null;
  driverVersion?: string | null;
  totalVramBytes?: number | null;
  usedVramBytes?: number | null;
  freeVramBytes?: number | null;
  utilizationPct?: number | null;
  temperatureC?: number | null;
  powerWatts?: number | null;
  computeCapability?: string | null;
  health: string;
  enabledForNewWork: boolean;
  measuredAt?: string | null;
  provenance: string;
};

export type HostMemoryInfo = {
  totalBytes?: number | null;
  usedBytes?: number | null;
  availableBytes?: number | null;
  safetyReserveBytes?: number | null;
  pressure: string;
  provenance: string;
  measuredAt?: string | null;
};

export type ModelHardwareInventory = {
  hostMemory: HostMemoryInfo;
  devices: ComputeDeviceInfo[];
  aggregatePhysicalVramBytes?: number | null;
  largestSingleDeviceTotalBytes?: number | null;
  largestSingleDeviceFreeBytes?: number | null;
  sampleAgeMs?: number | null;
  measuredAt?: string | null;
  provenance: string;
  telemetryHealth: string;
  notes: string[];
  truth?: Record<string, boolean>;
};

export type DeviceAssignmentInfo = {
  stableDeviceId: string;
  ordinal?: number | null;
  reservedVramBytes?: number | null;
  processVisibleOrdinal?: number | null;
  role: string;
};

export type PlacementReceiptInfo = {
  receiptId: string;
  planId?: string | null;
  modelId?: string | null;
  workerId?: string | null;
  pid?: number | null;
  runtimeGeneration?: number | null;
  devices: DeviceAssignmentInfo[];
  requestedPlacement: string;
  actualPlacement: string;
  reservationIds: string[];
  measuredVramBytes?: number | null;
  measuredRamBytes?: number | null;
  state: string;
  verifiedAt?: string | null;
  provenance: string;
  mismatch: boolean;
};

export type ModelResidency = {
  modelId: string;
  state: string;
  placement: string;
  managed: boolean;
  workerId?: string | null;
  pid?: number | null;
  endpoint?: string | null;
  activeLeaseCount: number;
  consumers: string[];
  policy?: ResidencyPolicy | null;
  lastUsedAt?: number | null;
  idleSince?: number | null;
  nextActionAt?: number | null;
  runtimeKind?: string | null;
  loadStartedAt?: number | null;
  readyAt?: number | null;
  lastError?: string | null;
  resourceEstimate?: ResourceEstimate | null;
  assignedDevices?: DeviceAssignmentInfo[];
  deploymentPlanId?: string | null;
  placementReceipt?: PlacementReceiptInfo | null;
  reservationIds?: string[];
  runtimeGeneration?: number | null;
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

export type ModelInferenceTestResult = {
  ok: boolean;
  modelId: string;
  providerId: string;
  callId?: string;
  traceId?: string;
  totalLatencyMs?: number;
  ttftMs?: number | null;
  finishReason?: string | null;
  preview?: string;
  raw?: Record<string, unknown>;
  streamRequested?: boolean;
  streamImplemented?: boolean;
  note?: string | null;
};

/* ---------- Datasets ---------- */

export type DatasetBrainStatus = {
  brainStatus: string;
  label?: string;
  indexId?: string | null;
  chunkCount?: number | null;
  documentCount?: number | null;
  jobId?: string | null;
  progress?: number | null;
  phase?: string | null;
  updatedAt?: string | null;
  sourceMissing?: boolean;
  learned?: boolean;
  versionId?: string;
  error?: unknown;
};

export type DatasetRecord = {
  datasetId: string;
  name: string;
  sourceType: string;
  status: string;
  description: string;
  originalFilename?: string | null;
  originalUri?: string | null;
  license?: string | null;
  schemaVersion: number;
  contentHash?: string | null;
  byteSize?: number | null;
  rowCount?: number | null;
  detectedFormat?: string | null;
  formatConfidence?: number | null;
  provenance?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  rawPath?: string | null;
  createdAt: string;
  updatedAt: string;
  brain?: DatasetBrainStatus;
  brainStatus?: string;
  learned?: boolean;
  sourceMissing?: boolean;
  indexes?: DatasetIndex[];
};

export type DatasetVersion = {
  versionId: string;
  datasetId: string;
  versionLabel: string;
  parentVersionId?: string | null;
  status: string;
  kind: string;
  schema?: Record<string, unknown>;
  rowCount?: number | null;
  byteSize?: number | null;
  contentHash?: string | null;
  storagePath?: string | null;
  split?: Record<string, unknown>;
  transformLineage?: Record<string, unknown>[];
  tokenStats?: Record<string, unknown>;
  validation?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type DatasetFile = {
  fileId: string;
  datasetId: string;
  versionId?: string | null;
  role: string;
  path: string;
  contentHash: string;
  byteSize: number;
  metadata?: Record<string, unknown>;
  createdAt: string;
};

export type DatasetJobCheckpoint = {
  repositoryId?: string;
  revision?: string;
  filename?: string;
  relativePath?: string;
  bytesDownloaded?: number;
  bytesTotal?: number | null;
  totalBytes?: number | null;
  filesTotal?: number | null;
  filesCompleted?: number | null;
  filesFailed?: number | null;
  bytesPerSecond?: number | null;
  etaSeconds?: number | null;
  etag?: string | null;
  attempts?: number;
  lastStatus?: number | null;
  lastHttpStatus?: number | null;
  rateLimitEvents?: number;
  file?: DatasetJobCheckpoint;
  manifestSummary?: Record<string, unknown>;
  [key: string]: unknown;
};

export type DatasetJobDownloadSummary = {
  repositoryId?: string | null;
  revision?: string | null;
  filename?: string | null;
  bytesDownloaded?: number | null;
  bytesTotal?: number | null;
  filesTotal?: number | null;
  filesCompleted?: number | null;
  attempts?: number | null;
  lastHttpStatus?: number | null;
  rateLimitEvents?: number | null;
  etag?: string | null;
  bytesPerSecond?: number | null;
  etaSeconds?: number | null;
};

export type DatasetActivityLevel = "info" | "progress" | "warning" | "error" | "success";

export type DatasetActivityEntry = {
  id: string;
  timestamp: string;
  datasetId?: string;
  jobId?: string;
  level: DatasetActivityLevel;
  stage?: string;
  message: string;
  bytesCompleted?: number;
  bytesTotal?: number;
  filesCompleted?: number;
  filesTotal?: number;
  retryCount?: number;
};

export type DatasetJob = {
  jobId: string;
  datasetId?: string | null;
  versionId?: string | null;
  jobType: string;
  status: string;
  phase?: string | null;
  progress?: number | null;
  cancelRequested?: boolean;
  workerPid?: number | null;
  checkpoint?: DatasetJobCheckpoint;
  config?: Record<string, unknown>;
  result?: Record<string, unknown>;
  error?: string | null;
  logPath?: string | null;
  traceId?: string | null;
  createdAt: string;
  startedAt?: string | null;
  updatedAt: string;
  finishedAt?: string | null;
  /** Derived download summary from backend public_job (HF imports). */
  download?: DatasetJobDownloadSummary | null;
  datasetName?: string | null;
  learning?: DatasetLearningLadder | null;
  activity?: DatasetLearningJobActivity | null;
};

export type DatasetLearningLadder = {
  filesDiscovered?: boolean;
  inCatalog?: boolean;
  sidecarPresent?: boolean;
  indexed?: boolean;
  embeddingsAvailable?: boolean;
  embeddingsSemantic?: boolean;
  relationsVerified?: boolean;
  relationCount?: number;
  brainSearchable?: boolean;
  sourceMissing?: boolean;
  versionCount?: number;
  truth?: Record<string, boolean>;
};

export type DatasetLearningJobActivity = {
  datasetId?: string | null;
  datasetName?: string | null;
  jobId: string;
  phase?: string | null;
  progress?: number | null;
  status: string;
  processed?: number | null;
  indexed?: number | null;
  chunkCount?: number | null;
  relationsAccepted?: number | null;
  relationsRejected?: number | null;
  embeddingMode?: string | null;
  embeddingsSemantic?: boolean | null;
  lastRecordId?: string | null;
  updatedAt?: string | null;
  startedAt?: string | null;
  finishedAt?: string | null;
  error?: string | null;
  blocked?: boolean;
  elapsedSeconds?: number | null;
};

export type DatasetLearningStatus = {
  agent: AgentDefinition | null;
  activity: {
    agentSystemKey?: string;
    agentName?: string;
    activeCount: number;
    active: DatasetJob[];
    recent: DatasetJob[];
    truth?: Record<string, boolean>;
    error?: string;
  };
  truth?: Record<string, boolean>;
};

export type DatasetIndex = {
  indexId: string;
  datasetId: string;
  versionId: string;
  status: string;
  chunkCount?: number | null;
  embeddingModel?: string | null;
  indexVersion?: number;
  knowledgeScope?: string | null;
  storagePath?: string | null;
  provenance?: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
};

export type DatasetPreviewRow = Record<string, unknown>;

export type HfDatasetFile = {
  path?: string;
  filename?: string;
  size?: number | null;
  [key: string]: unknown;
};

/* ---------- Training ---------- */

export type PackageAvailability = {
  name: string;
  available: boolean;
  version?: string | null;
  importError?: string | null;
};

export type TrainingCapabilities = {
  packages: PackageAvailability[];
  canRunFixture: boolean;
  canRunLora: boolean;
  canRunQlora: boolean;
  canRunDpo: boolean;
  ready: boolean;
  missingForLora: string[];
  notes: string[];
  truth?: Record<string, boolean>;
};

export type GpuDeviceInfo = {
  index: number;
  name: string;
  totalVramBytes?: number | null;
  freeVramBytes?: number | null;
  usedVramBytes?: number | null;
  computeCapability?: string | null;
};

export type HardwareSnapshot = {
  cpuModel?: string | null;
  logicalCores?: number | null;
  physicalCores?: number | null;
  ramTotalBytes?: number | null;
  ramAvailableBytes?: number | null;
  diskFreeBytes?: number | null;
  gpus: GpuDeviceInfo[];
  cudaAvailable: boolean;
  cudaRuntimeVersion?: string | null;
  torchCudaVersion?: string | null;
  driverVersion?: string | null;
  supportsFp16?: boolean | null;
  supportsBf16?: boolean | null;
  supports4bit?: boolean | null;
  notes: string[];
  measuredAt?: string;
  truth?: Record<string, boolean>;
};

export type PreflightIssue = {
  severity: string;
  code: string;
  message: string;
};

export type PreflightResult = {
  verdict: string;
  issues: PreflightIssue[];
  details?: Record<string, unknown>;
};

export type TrainingPlan = {
  strategy: string;
  reason: string;
  effectiveBatchSize: number;
  trainBatchSize: number;
  gradientAccumulation: number;
  maxSeqLength: number;
  precision: string;
  gradientCheckpointing: boolean;
  loadIn4bit: boolean;
  warnings: string[];
  estimated: boolean;
  details?: Record<string, unknown>;
};

export type TrainingJob = {
  jobId: string;
  name: string;
  status: string;
  phase?: string | null;
  method: string;
  baseModelRef: string;
  datasetVersionId?: string | null;
  outputDir?: string | null;
  config?: Record<string, unknown>;
  planner?: Record<string, unknown>;
  preflight?: Record<string, unknown>;
  progress?: number | null;
  cancelRequested?: boolean;
  workerPid?: number | null;
  checkpoint?: Record<string, unknown>;
  metricsSummary?: Record<string, unknown>;
  evaluation?: Record<string, unknown>;
  artifactId?: string | null;
  error?: string | null;
  logPath?: string | null;
  traceId?: string | null;
  seed?: number | null;
  configHash?: string | null;
  environment?: Record<string, unknown>;
  createdAt: string;
  startedAt?: string | null;
  updatedAt: string;
  finishedAt?: string | null;
  truth?: Record<string, boolean>;
};

export type TrainingMetric = {
  id?: number | null;
  jobId: string;
  step?: number | null;
  epoch?: number | null;
  metricName: string;
  metricValue: number;
  recordedAt: string;
  metadata?: Record<string, unknown>;
};

export type TrainingCheckpoint = {
  checkpointId: string;
  jobId: string;
  step?: number | null;
  epoch?: number | null;
  path: string;
  contentHash?: string | null;
  metrics?: Record<string, unknown>;
  createdAt: string;
  metadata?: Record<string, unknown>;
};

export type TrainingLogs = {
  jobId: string;
  logPath?: string | null;
  text: string;
  events: Record<string, unknown>[];
};

export type TrainingJobCreatePayload = {
  name?: string;
  method?: string;
  base_model_ref?: string;
  dataset_version_id?: string | null;
  dataset_path?: string | null;
  output_dir?: string | null;
  seed?: number;
  epochs?: number | null;
  max_steps?: number | null;
  train_batch_size?: number;
  eval_batch_size?: number;
  gradient_accumulation?: number;
  learning_rate?: number;
  warmup_steps?: number;
  weight_decay?: number;
  max_seq_length?: number;
  logging_steps?: number;
  save_steps?: number;
  precision?: string;
  lora_r?: number;
  lora_alpha?: number;
  lora_dropout?: number;
  lora_target_modules?: string[];
  gradient_checkpointing?: boolean;
  load_in_4bit?: boolean;
  fixture_steps?: number;
  fixture_sleep_ms?: number;
  auto_start?: boolean;
};

export type TrainingPreflightPayload = {
  name?: string;
  method?: string;
  base_model_ref?: string;
  dataset_version_id?: string | null;
  dataset_path?: string | null;
  output_dir?: string | null;
  seed?: number;
  epochs?: number | null;
  max_steps?: number | null;
  train_batch_size?: number;
  gradient_accumulation?: number;
  learning_rate?: number;
  max_seq_length?: number;
  precision?: string;
  load_in_4bit?: boolean;
  fixture_steps?: number;
  fixture_sleep_ms?: number;
};

/* ---------- Research ---------- */

export type ResearchBudget = {
  search_queries: number;
  urls_per_query: number;
  max_sources: number;
  /** Null under TEAM quality_contract — open-ended cumulative work. */
  rounds: number | null;
  research_workers: number;
  max_local_hits: number;
  max_evidence_per_source: number;
  completion_policy?: string;
  max_iterations?: number | null;
  max_total_sources?: number | null;
};

export type ResearchBudgetCatalog = {
  presets: Record<string, ResearchBudget>;
  ceilings: ResearchBudget;
  limits: {
    research_workers: { min: number; max: number };
    rounds: { min: number; max: number };
    [key: string]: { min: number; max: number };
  };
  execution_modes: {
    normal: {
      research_workers: number;
      rounds: number;
      locked: boolean;
      description: string;
      completion_policy?: string;
    };
    custom: {
      limits: {
        research_workers: { min: number; max: number };
        rounds: { min: number; max: number };
      };
      locked: boolean;
      description: string;
      completion_policy?: string;
    };
    team?: {
      research_workers?: { min: number; max: number; default?: number };
      rounds: null;
      locked: boolean;
      completion_policy: string;
      description: string;
      optional_caps?: Record<string, { null_means_unbounded?: boolean }>;
    };
  };
};

export type ResearchWorker = {
  worker_id: string;
  project_id: string;
  run_id: string;
  worker_index: number;
  status: string;
  phase: string;
  current_round: number;
  total_rounds: number;
  completed_rounds: number;
  current_query?: string | null;
  current_task?: string | null;
  sources_added: number;
  evidence_added: number;
  started_at?: string | null;
  heartbeat_at?: string | null;
  finished_at?: string | null;
  last_error?: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchPlan = {
  interpreted_question: string;
  scope: string;
  assumptions: string[];
  subquestions: string[];
  retrieval_queries: string[];
  preferred_source_types: string[];
  local_scopes: string[];
  exclusion_criteria: string[];
  rounds: number;
  budget: ResearchBudget;
  notes: string;
};

export type ResearchCoverage = {
  planned_questions: string[];
  answered_questions: string[];
  unresolved_questions: string[];
  source_count: number;
  unique_domains: string[];
  claims_supported: number;
  claims_with_conflicts: number;
  claims_unsupported: number;
  rounds_completed: number;
  web_status: string;
  notes: string[];
};

export type ResearchProject = {
  project_id: string;
  title: string;
  topic: string;
  objective: string;
  status: string;
  depth: string;
  allow_web: boolean;
  respect_robots_txt: boolean;
  model_profile?: Record<string, unknown>;
  budget: ResearchBudget;
  plan?: ResearchPlan | null;
  coverage?: ResearchCoverage | null;
  local_scopes: string[];
  seed_sources: string[];
  connected_datasets?: Array<Record<string, unknown>>;
  current_round: number;
  total_rounds: number;
  error?: string | null;
  cancel_requested?: boolean;
  worker_pid?: number | null;
  trace_id?: string | null;
  report_version: number;
  created_at: string;
  updated_at: string;
  started_at?: string | null;
  finished_at?: string | null;
  execution_mode?: string;
  phase?: string;
  progress_pct?: number;
  analysis_mode?: string;
  active_run_id?: string | null;
  completed_worker_rounds?: number;
  total_worker_rounds?: number;
  source_count: number;
  claim_count: number;
  evidence_count: number;
  conflict_count: number;
  web_unavailable_reason?: string | null;
  workers?: ResearchWorker[];
};

export type ResearchEvent = {
  event_id: string;
  project_id: string;
  event_type: string;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

export type ResearchSource = {
  source_id: string;
  project_id: string;
  source_type: string;
  original_uri?: string | null;
  canonical_uri?: string | null;
  title?: string | null;
  author?: string | null;
  published_at?: string | null;
  fetched_at?: string | null;
  content_hash?: string | null;
  mime_type?: string | null;
  snapshot_path?: string | null;
  parse_status: string;
  parser?: string | null;
  brain_status?: string;
  brain_document_id?: string | null;
  brain_error?: string | null;
  provenance?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  created_at: string;
};

export type SourceIngestionProgress = {
  source_id: string;
  job_id?: string | null;
  status: string;
  phase: string;
  progress_pct?: number | null;
  files_discovered: number;
  files_ingested: number;
  files_skipped: number;
  files_failed: number;
  files_pending: number;
  files_quarantined: number;
  files_duplicate: number;
  files_routed: number;
  brain_synced: number;
  brain_failed: number;
  bytes_processed: number;
  compressed_bytes?: number | null;
  uncompressed_bytes?: number | null;
  archive_type?: string | null;
  filename?: string | null;
  error?: string | null;
  cancel_requested?: boolean;
};

export type SourceIngestionMember = {
  member_id: string;
  container_source_id: string;
  relative_path: string;
  original_filename: string;
  size_bytes: number;
  outcome: string;
  skip_reason?: string | null;
  error_code?: string | null;
  parse_status: string;
  brain_status: string;
  child_source_id?: string | null;
  brain_document_id?: string | null;
  parser?: string | null;
  detected_kind?: string | null;
  is_encrypted?: boolean;
  is_symlink?: boolean;
  is_directory?: boolean;
};

export type ResearchEvidence = {
  evidence_id: string;
  project_id: string;
  source_id: string;
  chunk_id?: string | null;
  span_text: string;
  location?: Record<string, unknown>;
  retrieval_method?: string | null;
  associated_claim_ids: string[];
  citation_key: string;
  created_at: string;
  metadata?: Record<string, unknown>;
};

export type ResearchClaim = {
  claim_id: string;
  project_id: string;
  proposition: string;
  raw_wording?: string | null;
  status: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  source_diversity: number;
  created_at: string;
  updated_at: string;
  metadata?: Record<string, unknown>;
};

export type ResearchConflict = {
  conflict_id: string;
  project_id: string;
  claim_id?: string | null;
  summary: string;
  supporting_evidence_ids: string[];
  contradicting_evidence_ids: string[];
  analysis?: Record<string, unknown>;
  unresolved_questions: string[];
  created_at: string;
};

export type ResearchReport = {
  report_id: string;
  project_id: string;
  version: number;
  title: string;
  body_markdown: string;
  body_html?: string | null;
  evidence_ids: string[];
  source_ids: string[];
  model_profile?: Record<string, unknown>;
  generation_trace?: Record<string, unknown>;
  created_at: string;
};

export type ResearchProjectCreate = {
  title?: string | null;
  topic: string;
  objective?: string;
  depth?: string;
  allowWeb?: boolean;
  respectRobotsTxt?: boolean;
  modelProfile?: Record<string, unknown> | null;
  budget?: Partial<ResearchBudget> | null;
  localScopes?: string[];
  seedSources?: string[];
  connectedDatasets?: Array<Record<string, unknown>>;
  executionMode?: string;
};

/* ---------- Knowledge Library ---------- */

export type KnowledgeDocument = {
  id: string;
  title: string;
  content: string;
  source: string;
  status?: string;
  content_hash?: string;
  original_path?: string | null;
  source_mtime?: string | null;
  size_bytes?: number | null;
  parser?: string;
  parser_version?: string;
  ingest_version?: number;
  trust_metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  error?: string | null;
};

export type KnowledgeChunk = {
  chunk_id: string;
  document_id: string;
  chunk_index: number;
  content: string;
  content_hash?: string;
  token_estimate?: number;
  start_offset?: number;
  end_offset?: number;
  confidence?: number;
  uncertainty_notes?: string;
  source_type?: string;
  provenance?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type KnowledgeSearchHit = {
  document_id: string;
  chunk_id?: string;
  chunk_index?: number;
  title: string;
  source: string;
  content: string;
  score?: number;
  modality?: string;
  confidence?: number;
  original_path?: string | null;
  document_hash?: string;
  chunk_hash?: string;
  start_offset?: number;
  end_offset?: number;
  source_type?: string;
  layer?: string;
  provenance?: Record<string, unknown>;
};

/* ---------- Memory (Geheugen) ---------- */

export type MemoryKind =
  | "NOTE"
  | "PREFERENCE"
  | "FACT"
  | "PROCEDURE"
  | "EPISODIC"
  | "DECISION"
  | "RELATION"
  | "SUMMARY"
  | "RESIDUE"
  | "COMMITMENT"
  | "CORRECTION"
  | "PROJECT"
  | string;

export type MemoryStatus = "ACTIVE" | "ARCHIVED" | "REVOKED" | "SUPERSEDED" | string;

export type MemoryScope =
  | "GLOBAL"
  | "USER"
  | "WORKSPACE"
  | "PROJECT"
  | "CONVERSATION"
  | "AGENT_PRIVATE"
  | string;

export type MemoryRecord = {
  memory_id: string;
  kind: MemoryKind;
  status: MemoryStatus;
  content: string;
  created_at: string;
  updated_at: string;
  source: string;
  trust: string;
  run_id?: string | null;
  conversation_id?: string | null;
  tags: string[];
  metadata?: Record<string, unknown>;
  priority?: number;
  scope: MemoryScope;
  workspace_id?: string | null;
  project_id?: string | null;
  user_id?: string | null;
  confidence?: number;
  valid_from?: string | null;
  valid_until?: string | null;
  supersedes_id?: string | null;
  source_refs?: string[];
  truth?: Record<string, boolean>;
};

export type MemoryCreatePayload = {
  content: string;
  kind?: MemoryKind;
  source?: string;
  trust?: string;
  tags?: string[];
  conversation_id?: string | null;
  run_id?: string | null;
  scope?: MemoryScope | null;
  project_id?: string | null;
  workspace_id?: string | null;
  user_id?: string | null;
};

/* ---------- Evidence Vault ---------- */

export type EvidenceKind = "ARTIFACT_HASH" | "OBSERVATION_REF" | "FILE_EXISTS" | "COMPOSITE" | string;

export type EvidenceStatus = "UNVERIFIED" | "VERIFIED" | "FAILED" | string;

export type EvidenceRecord = {
  evidence_id: string;
  kind: EvidenceKind;
  status: EvidenceStatus;
  claim: string;
  created_at: string;
  verified_at?: string | null;
  observation_id?: string | null;
  artifact_id?: string | null;
  run_id?: string | null;
  job_id?: string | null;
  content_hash?: string | null;
  path?: string | null;
  error?: string | null;
  metadata?: Record<string, unknown>;
  /** Present only when backend provides an assessment — never invent a score. */
  confidence?: number | null;
  truth?: Record<string, boolean>;
};

/* ---------- Coding Agent ---------- */

export type CodingMission = "SCAFFOLD" | "REVIEW" | "TEST" | "FIX" | "GENERIC";

export type CodingSessionStatus =
  | "CREATED"
  | "RUNNING"
  | "WAITING_APPROVAL"
  | "COMPLETED"
  | "FAILED"
  | "UNVERIFIED"
  | "PARTIAL"
  | "RESOURCE_EXHAUSTED"
  | "CANCELLED"
  | "DISABLED";

export type CodingStatusResponse = {
  enabled: boolean;
  agents_enabled: boolean;
  workspace_configured: boolean;
  residual_supported: boolean;
  catalog_ids: string[];
  truth: {
    gateway_only: boolean;
    hades_excluded: boolean;
  };
  error?: string | null;
};

export type CodingSession = {
  session_id: string;
  mission: CodingMission;
  status: CodingSessionStatus;
  workspace_root: string;
  title: string;
  user_goal: string;
  model_id: string | null;
  error: string | null;
  verification_id: string | null;
  created_at: string;
  updated_at: string;
  run_id?: string | null;
  pending_capability?: {
    capability_id?: string;
    approval_id?: string;
    arguments?: Record<string, unknown>;
    [key: string]: unknown;
  } | null;
  feature_truth?: Record<string, unknown> | null;
  round_count?: number;
  phase?: string | null;
  task_type?: string | null;
  coding_role?: string | null;
  plan?: Record<string, unknown> | null;
  brain_context?: Record<string, unknown> | null;
  acceptance?: Record<string, unknown> | null;
  hypotheses?: Array<Record<string, unknown>> | null;
  truth?: Record<string, unknown> | null;
};

export type CodingStep = {
  step_id: string;
  session_id: string;
  kind: string;
  capability_id: string | null;
  status: string;
  /** Canonical backend field from CodingStep.public_dict(). */
  output?: Record<string, unknown> | null;
  /** @deprecated Prefer `output` — kept for transitional reads. */
  output_json?: Record<string, unknown> | null;
  error?: string | null;
  created_at?: string;
  observation_id?: string | null;
  artifact_id?: string | null;
  approval_id?: string | null;
};

export type CodingPatch = {
  patch_id: string;
  session_id: string;
  path: string;
  diff_unified: string;
  applied: boolean;
  artifact_id?: string | null;
  approval_id?: string | null;
};

export type CodingVerification = {
  verification_id?: string | null;
  report_id?: string;
  outcome?: "PASSED" | "FAILED" | "UNMEASURED";
  requirements?: Array<{ requirement_id: string; outcome: string; detail?: string | null }>;
};

export type CodingNeuroSnapshot = {
  enabled: boolean;
  consistency?: number | null;
  progress?: number | null;
  grounding?: number | null;
  residual_supported?: boolean;
  notes?: string[];
};

export type CodingSessionDetail = {
  session: CodingSession;
  turns: Array<{ turn_id: string; role: string; content: string; created_at: string }>;
  steps: CodingStep[];
  patches: CodingPatch[];
  verification: CodingVerification | null;
  neuro: CodingNeuroSnapshot | null;
};

export type CodingTurnResponse = {
  session: CodingSession;
};

export type CodingWorkspaceTreeResponse = {
  entries: Array<{ path: string; type: "file" | "dir"; size?: number; mark?: "M" | "A" | null }>;
  root?: string;
};

export type SystemTelemetryResponse = {
  collectedAt: string | null;
  ageMs: number | null;
  cpu: { available: boolean; utilizationPct: number | null };
  memory: {
    available: boolean;
    totalBytes: number | null;
    usedBytes: number | null;
    availableBytes: number | null;
    utilizationPct: number | null;
  };
  gpu: {
    available: boolean;
    devices: Array<{
      index: number;
      name: string;
      utilizationPct: number | null;
      vramTotalBytes: number | null;
      vramUsedBytes: number | null;
      vramFreeBytes: number | null;
      vramUtilizationPct: number | null;
      driverVersion?: string | null;
    }>;
  };
  notes?: string[];
  truth: {
    measured: boolean;
    synthetic: boolean;
    unavailableIsNotZero?: boolean;
  };
  dashboard: {
    cpuPct: number | null;
    ramPct: number | null;
    gpuPct: number | null;
    vramPct: number | null;
  };
};

export type CapabilityListItem = {
  id: string;
  name?: string;
  description?: string;
  side_effects?: string[];
  enabled?: boolean;
  available?: boolean;
  availability_reason?: string | null;
  /** Alias some gateways surface instead of availability_reason. */
  unavailable_reason?: string | null;
  provider_kind?: string;
  provider_ref?: string;
  input_schema?: Record<string, unknown>;
  [key: string]: unknown;
};


export type McpServerRuntime = {
  server_id: string;
  state: string;
  effective_isolation: string;
  protocol_version?: string | null;
  server_version?: string | null;
  tool_count: number;
  last_connected_at?: string | null;
  last_seen_at?: string | null;
  last_error_code?: string | null;
  last_error_message?: string | null;
  pid?: number | null;
  circuit_open?: boolean;
};

export type McpServerPublic = {
  server_id: string;
  display_name: string;
  source_kind: string;
  source_key: string;
  transport: string;
  command?: string | null;
  args: string[];
  url?: string | null;
  enabled: boolean;
  trust: string;
  requested_isolation: string;
  secret_refs: Record<string, string>;
  runtime?: McpServerRuntime;
};

export type McpToolRecord = {
  server_id: string;
  external_name: string;
  capability_id: string;
  description: string;
  input_schema: Record<string, unknown>;
  schema_hash: string;
  semantic_effects: string[];
  availability: string;
  provider_kind?: string;
};

export type McpCallRecord = {
  call_id: string;
  server_id: string;
  capability_id: string;
  external_tool_name: string;
  requester?: string;
  status: string;
  duration_ms?: number | null;
  error_message?: string | null;
  started_at: string;
  finished_at?: string | null;
};

export type McpHealthSummary = {
  registered_servers: number;
  enabled_servers: number;
  connected_servers: number;
  ready_servers: number;
  tool_count: number;
  unavailable_tools: number;
  last_error?: string | null;
  feature_enabled: boolean;
};

/* ---------- Market Simulation ---------- */

export type MarketSimStatusResponse = {
  enabled: boolean;
  feature_flag: string;
  health: {
    markets_root: string;
    configured: boolean;
    exists: boolean;
    sources_indexed: number;
    sources_ready: number;
  };
  active_runs: number;
  worker: {
    slices?: number;
    completed?: number;
    failed?: number;
    cancelled?: number;
    worker_mode?: string;
    worker_pid?: number;
    isolated_subprocess?: boolean;
    lease_model?: string;
    [key: string]: unknown;
  };
  providers?: Array<{
    provider_id: string;
    reachable?: boolean | null;
    detail?: string;
    license_note?: string;
    [key: string]: unknown;
  }>;
  capabilities?: Record<string, unknown>;
  live_trading?: Record<string, unknown>;
  truth: Record<string, boolean | string>;
};

export type MarketDataSource = {
  source_id: string;
  symbol: string;
  timeframe: string;
  kind: string;
  path: string;
  content_hash: string;
  status: string;
  bar_count: number;
  start_ts: string | null;
  end_ts: string | null;
  byte_size: number;
  validation_error: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type MarketStrategy = {
  strategy_id: string;
  name: string;
  description: string;
  status: string;
  tags: string[];
  current_version: number;
  content_hash: string;
  created_at: string;
  updated_at: string;
};

export type MarketStrategyVersion = {
  version_id: string;
  strategy_id: string;
  version: number;
  content_hash: string;
  parameters: Record<string, unknown>;
  entry_rules: Record<string, unknown>;
  exit_rules: Record<string, unknown>;
  risk_rules: Record<string, unknown>;
  required_timeframes: string[];
  brain_dependencies: string[];
  created_at: string;
  changelog: string;
};

export type MarketSimAgent = {
  agent_id: string;
  role: string;
  label?: string;
  parameters?: Record<string, unknown>;
  entry_rules?: Record<string, unknown>;
  exit_rules?: Record<string, unknown>;
  initial_cash?: number;
  authority?: Record<string, unknown>;
  [key: string]: unknown;
};

export type MarketSimWallet = {
  wallet_id?: string;
  owner_id?: string;
  owner_kind?: string;
  cash?: number;
  position_qty?: number;
  equity?: number;
  [key: string]: unknown;
};

export type MarketSimRun = {
  run_id: string;
  status: string;
  source_id: string;
  strategy_id: string | null;
  strategy_version: number | null;
  symbol: string;
  timeframe: string;
  start_ts: string;
  end_ts: string;
  data_hash: string;
  seed: number;
  speed: number;
  initial_cash: number;
  clock_ts: string | null;
  bar_index: number;
  bar_count: number;
  cash: number;
  equity: number;
  position_qty: number;
  realized_pnl: number;
  unrealized_pnl: number;
  causality_violations: number;
  brain_hits: number;
  brain_misses: number;
  metrics: Record<string, unknown>;
  error: string | null;
  agents: MarketSimAgent[];
  metadata?: {
    wallets?: { wallets?: MarketSimWallet[] };
    fill_assumptions?: string[];
    multi_agent?: boolean;
    commit_reveal?: boolean;
    game_mode?: string;
    [key: string]: unknown;
  };
  created_at: string;
  updated_at: string;
  truth?: Record<string, boolean>;
};

export type MarketSimFill = {
  fill_id: string;
  run_id: string;
  bar_index: number;
  ts: string;
  side: string;
  qty: number;
  price: number;
  fee: number;
  slippage: number;
  agent_id: string | null;
  rationale: string;
  status: string;
};

export type MarketSimMessage = {
  message_id: string;
  run_id: string;
  bar_index: number;
  ts: string;
  agent_id: string;
  role: string;
  kind: string;
  content: string;
  proposal: Record<string, unknown>;
  confidence: number;
  brain_refs: Array<Record<string, unknown>>;
};

export type MarketSimLiveState = {
  run: MarketSimRun;
  fills: MarketSimFill[];
  messages: MarketSimMessage[];
  equity: Array<{ bar_index: number; ts: string; equity: number; cash: number; position_qty: number }>;
  truth: Record<string, unknown>;
};

export type PaperPortfolio = {
  portfolio_id: string;
  name: string;
  status: string;
  mode: string;
  base_currency: string;
  broker_mode: string;
  provider_id: string;
  benchmark_symbol: string;
  orchestra_id: string | null;
  initial_equity: string;
  cash: string;
  reserved_cash: string;
  available_buying_power?: string;
  realized_pnl: string;
  unrealized_pnl: string;
  fees_paid: string;
  equity: string;
  peak_equity: string;
  margin_used: string;
  gross_exposure: string;
  net_exposure: string;
  kill_switch: boolean;
  shorting_enabled: boolean;
  last_mark_at: string | null;
  created_at: string;
  updated_at: string;
  settings?: Record<string, unknown>;
  truth?: Record<string, unknown>;
};

export type PaperPortfolioKpis = {
  total_equity: string;
  daily_pnl: string;
  daily_pnl_pct: number;
  unrealized_pnl: string;
  unrealized_pnl_pct: number;
  realized_pnl: string;
  realized_pnl_pct: number;
  cash_balance: string;
  reserved_cash: string;
  available_buying_power: string;
  margin_usage_pct: number;
  margin_disabled?: boolean;
  win_rate: number | null;
  last_sync: string | null;
  stale?: boolean;
};

export type PortfolioPosition = {
  position_id: string;
  portfolio_id: string;
  symbol: string;
  display_name?: string;
  asset_class: string;
  side: string;
  qty: string;
  avg_entry_price: string;
  mark_price: string;
  market_value: string;
  cost_basis: string;
  realized_pnl: string;
  unrealized_pnl: string;
  pnl_pct: string;
  fees: string;
  allocation_pct: number;
  risk: string;
  agent_id: string | null;
  orchestra_id: string | null;
  strategy_id: string | null;
  strategy_version: number | null;
  status: string;
  opened_at?: string;
  updated_at?: string;
};

export type PortfolioTransaction = {
  transaction_id: string;
  portfolio_id: string;
  symbol: string;
  side: string;
  qty: string;
  price: string;
  fees: string;
  gross_notional?: string;
  net_cash_effect?: string;
  result: string;
  agent_id?: string | null;
  strategy_id?: string | null;
  timestamp: string;
};

export type PortfolioRiskSummary = {
  sharpe: number | null;
  sortino: number | null;
  max_drawdown: number | null;
  var_1d_95: number | null;
  beta: number | null;
  volatility: number | null;
  correlation: number | null;
  stress_level: string;
  liquidity_score: number | null;
  exposure_pct?: number;
  health: {
    score: number;
    label: string;
    components: Record<string, number>;
  };
  insufficient?: Record<string, boolean>;
};

export type PortfolioAllocationRow = {
  symbol: string;
  display_name?: string;
  asset_class: string;
  value: string;
  allocation_pct: number;
  pnl_24h?: string;
};

export type PortfolioAllocation = {
  total_equity: string;
  assets: PortfolioAllocationRow[];
  by_asset_class: Array<{ asset_class: string; value: string; allocation_pct: number }>;
  by_sector: Array<{ name: string; value: string; allocation_pct: number }>;
  by_geography: Array<{ name: string; value: string; allocation_pct: number }>;
};

export type PortfolioPerformancePoint = {
  timestamp?: string;
  equity?: string;
  drawdown?: string;
};

export type PortfolioStrategyAllocation = {
  strategy_id: string;
  strategy_version?: number | null;
  allocation_pct: number;
  equity: string;
  daily_pnl: string;
  total_pnl: string;
  status: string;
  agent_id?: string | null;
};

export type PortfolioRecommendation = {
  recommendation_id: string;
  portfolio_id: string;
  type: string;
  target: string;
  reason: string;
  current_value: string;
  target_value: string;
  impact: string;
  estimated_orders: Array<{ symbol: string; side: string; qty: number }>;
  status: string;
  created_at: string;
};

export type PortfolioDashboard = {
  portfolio: PaperPortfolio;
  kpis: PaperPortfolioKpis;
  positions: PortfolioPosition[];
  allocation: PortfolioAllocation;
  exposure: {
    net_exposure_pct: number;
    gross_exposure_pct: number;
    leverage: number;
    largest_position_pct: number;
    top3_concentration: Array<{ symbol: string; allocation_pct: number }>;
    crypto_allocation_pct: number;
    equities_allocation_pct: number;
    stablecoin_cash_allocation_pct: number;
    other_allocation_pct: number;
    margin_used: string;
  };
  risk: PortfolioRiskSummary;
  insights: Array<{ id: string; severity: string; text: string }>;
  recent_transactions: PortfolioTransaction[];
  strategy_allocation: PortfolioStrategyAllocation[];
  recommendations: PortfolioRecommendation[];
  performance_summary: {
    total_return: number | null;
    sharpe: number | null;
    max_drawdown: number | null;
    volatility: number | null;
    range: string;
    series: PortfolioPerformancePoint[];
  };
  market_status: {
    provider_id?: string;
    stale?: boolean;
    errors?: string[];
    marks?: Record<string, number>;
  };
  generated_at: string;
  truth?: Record<string, unknown>;
};

export type SettingsCategory = {
  id: string;
  label: string;
  description: string;
  order: number;
  setting_count: number;
};

export type SettingState = {
  key: string;
  category: string;
  label: string;
  description: string;
  type: string;
  default_value: unknown;
  desired_value: unknown;
  effective_value: unknown;
  source: string;
  editable: boolean;
  secret: boolean;
  configured?: boolean | null;
  restart_required: boolean;
  apply_mode: string;
  status: string;
  dangerous: boolean;
  experimental: boolean;
  requires: string[];
  enum_values: string[];
  min_value?: number | null;
  max_value?: number | null;
  consumer: string;
  effective_now: boolean;
};

export type SettingsSnapshot = {
  categories: SettingsCategory[];
  settings: SettingState[];
  effective_summary?: Record<string, unknown>;
};

export type SettingMutationResult = {
  key: string;
  status: string;
  message: string;
  desired_value?: unknown;
  effective_value?: unknown;
  restart_required?: boolean;
  saved?: boolean;
  applied?: boolean;
};

/** Canonical runtime event from ObservabilityHub (durable + live). */
export type RuntimeEventLevel =
  | "DEBUG"
  | "INFO"
  | "SUCCESS"
  | "WARNING"
  | "ERROR"
  | "CRITICAL"
  | string;

export type RuntimeEvent = {
  sequence: number;
  event_id: string;
  created_at_ms: number;
  level: RuntimeEventLevel;
  category: string;
  subsystem: string;
  name: string;
  message: string;
  payload: Record<string, unknown>;
  source: string;
  request_id?: string | null;
  correlation_id?: string | null;
  parent_correlation_id?: string | null;
  actor?: string | null;
  run_id?: string | null;
  job_id?: string | null;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  workflow_step_id?: string | null;
  module_id?: string | null;
  mcp_server_id?: string | null;
  tool_id?: string | null;
  capability_id?: string | null;
  research_project_id?: string | null;
  dataset_id?: string | null;
  evidence_id?: string | null;
  duration_ms?: number | null;
  success?: boolean | null;
  redacted?: boolean;
};

export type EventsListResponse = {
  events: RuntimeEvent[];
  latest_sequence: number;
  snapshot?: Record<string, unknown>;
  truth?: Record<string, boolean>;
};

export type OperatorCommandResult = {
  ok: boolean;
  command: string;
  output: unknown;
  error?: string | null;
  events_emitted?: number;
};

export type PerformanceSnapshot = {
  system: SystemTelemetryResponse;
  metrics: MetricsSnapshot;
  latency: Record<
    string,
    { p50: number | null; p95: number | null; p99: number | null; count: number; avg: number | null }
  >;
  hot_paths: Array<{
    name: string;
    count: number;
    avg_ms: number;
    p50_ms: number;
    p95_ms: number;
    p99_ms: number;
  }>;
  timeseries: Record<string, unknown>;
  components: Array<{
    id: string;
    name: string;
    type: string;
    status: string;
    detail?: string;
  }>;
  observability: Record<string, unknown>;
  inferenceEfficiency?: InferenceEfficiencySnapshot | null;
  truth?: Record<string, boolean>;
};

/** Provenance-aware inference efficiency snapshot (never mock zeros as measured). */
export type EfficiencyCapabilityState = "supported" | "unsupported" | "unknown" | "unverified" | "unmeasured";

export type InferenceEfficiencySnapshot = {
  metrics?: {
    tokenization?: { lookups: number; hits: number };
    contextCompile?: { hits: number; misses: number };
    retrieval?: { hits: number; misses: number };
    embedding?: { hits: number; misses: number };
    rerank?: { hits: number; misses: number };
    exactResult?: { hits: number; misses: number; bypasses: number };
    semantic?: { hits: number; misses: number; bypasses: number };
    prefixReuse?: number;
    cachedInputTokensProviderReported?: number;
    contextFitFailures?: number;
    compactionCount?: number;
    evictions?: number;
    invalidations?: number;
    ttftAvgMs?: number | null;
    tokenPrecisionShare?: { exact: number; heuristic: number };
    truth?: Record<string, boolean>;
  } | null;
  policy?: {
    cachesEnabled?: boolean;
    semanticEnabled?: boolean;
    exactResultEnabled?: boolean;
    semanticThreshold?: number;
  };
  caches?: Record<
    string,
    {
      name?: string;
      enabled?: boolean;
      entries?: number;
      maxEntries?: number;
      bytesEstimate?: number;
      stats?: {
        lookups?: number;
        hits?: number;
        misses?: number;
        hitRate?: number | null;
      };
    }
  >;
  runtimeAffinity?: Record<
    string,
    {
      modelId: string;
      workerId?: string | null;
      runtimeGeneration: number;
      prefixCacheState: string;
      kvCacheState: string;
      provenance: string;
    }
  >;
  truth?: Record<string, boolean>;
};

export type ModuleSnapshot = {
  enabled?: boolean;
  modules?: Array<{
    manifest?: {
      module_id?: string;
      name?: string;
      version?: string;
      capabilities?: unknown[];
      isolation?: string;
      source_path?: string;
    };
    status?: string;
    error?: string | null;
    health?: Record<string, unknown> | null;
    last_result?: Record<string, unknown> | null;
  }>;
  telemetry?: Record<string, number>;
  discovery_roots?: string[];
  truth?: Record<string, boolean>;
};

/* ---------- Workflows ---------- */

export type WorkflowState = "CREATED" | "RUNNING" | "COMPLETED" | "FAILED" | "CANCELLED";

export type WorkflowStepDef = {
  step_id: string;
  capability_id: string;
  arguments?: Record<string, unknown>;
  approval_id?: string | null;
};

export type WorkflowStepResult = {
  step_id: string;
  capability_id: string;
  status: string;
  result?: Record<string, unknown>;
};

export type WorkflowRecord = {
  workflow_id: string;
  name: string;
  state: WorkflowState | string;
  steps: WorkflowStepDef[];
  created_at: string;
  updated_at: string;
  current_step?: number;
  run_id?: string | null;
  step_results?: WorkflowStepResult[];
  error?: string | null;
  metadata?: Record<string, unknown>;
};

export type WorkflowCreatePayload = {
  name: string;
  run_id?: string | null;
  steps: Array<{
    step_id?: string;
    capability_id: string;
    arguments?: Record<string, unknown>;
    approval_id?: string | null;
  }>;
};

/* ---------- Schedules ---------- */

export type ScheduleStatus = "ACTIVE" | "PAUSED" | "DISABLED";

export type ScheduleTargetKind = "WORKFLOW" | "JOB";

export type ScheduleRecord = {
  schedule_id: string;
  name: string;
  status: ScheduleStatus | string;
  target_kind: ScheduleTargetKind | string;
  target_ref: string;
  interval_seconds: number;
  created_at: string;
  updated_at: string;
  next_run_at: string;
  last_run_at?: string | null;
  target_payload?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
};

export type ScheduleCreatePayload = {
  name: string;
  target_kind?: string;
  target_ref: string;
  interval_seconds?: number;
  target_payload?: Record<string, unknown>;
  start_after_seconds?: number;
};

/* ---------- Agent fleet ---------- */

export type OperationalJobStatus =
  | "queued"
  | "starting"
  | "running"
  | "pausing"
  | "paused"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed"
  | "interrupted"
  | "disabled"
  | "unknown";

export type AgentDefinitionKind =
  | "generic"
  | "coding"
  | "research"
  | "orchestrator"
  | "specialist"
  | "trading";

// --- Trade orchestras / trading agents (Frontier Program) ---

export type TradingAutonomyLevel = "A0" | "A1" | "A2" | "A3" | "A4";

export type TradingMandate = {
  universe: string[];
  paperCapital: number;
  maxGrossExposurePct: number;
  maxSymbolExposurePct: number;
  perTradeRiskPct: number;
  maxOrdersPerDay: number;
  maxDrawdownPct: number;
  allowedOrderTypes: string[];
  allowedFamilies: string[];
  autonomyLevel: TradingAutonomyLevel | string;
  readinessCeiling: TradingAutonomyLevel | string;
  decisionCadence: string;
  maxModelCallsPerMission: number;
  maxTokensPerMission: number;
  cannotEnableLive: true;
};

export type TradeOrchestraMember = {
  agentId: string;
  name: string;
  kind: AgentDefinitionKind | string;
  role: string;
  canonicalRole: string;
  enabled: boolean;
  health: AgentHealth | string;
};

export type TradeOrchestraDecisionStats = {
  byStage: Record<string, number>;
  total: number;
  riskRejections: number;
  lastDecisionAt: string | null;
};

export type TradeOrchestra = {
  orchestraId: string;
  name: string;
  description: string;
  enabled: boolean;
  archived: boolean;
  health: AgentHealth | string;
  role: string;
  mandate: TradingMandate;
  mandateFingerprint: string;
  readiness: { state: "UNMEASURED" | "MEASURED" | string; reason?: string };
  autonomyLevel: TradingAutonomyLevel | string;
  decisionStats: TradeOrchestraDecisionStats;
  lastMissionId: string | null;
  lastRunAt: string | null;
  createdAt: string;
  updatedAt: string;
  memberAgentIds: string[];
  members?: TradeOrchestraMember[];
  truth: Record<string, unknown>;
};

export type TradeOrchestraSummary = {
  enabled: boolean;
  fleetBound: boolean;
  model: string;
  modelAvailable: boolean;
  orchestras: number;
  feeds: number;
  feedsEnabled: number;
  newsItems: number;
  externalized: boolean;
  jobRuntimeBound: boolean;
  truth: Record<string, unknown>;
};

export type TradingMissionKind = "deliberation_round" | "news_digest" | "post_mortem";

export type TradingDecision = {
  decisionId: string;
  orchestraId: string;
  missionId: string | null;
  agentId: string;
  role: string;
  stage: string;
  asOf: string;
  payload: Record<string, unknown>;
  parentDecisionId: string | null;
  modelId: string | null;
  promptArtifactId: string | null;
  outputArtifactId: string | null;
  mandateFingerprint: string;
  createdAt: string;
};

export type TradingNewsFeed = {
  feedId: string;
  name: string;
  url: string;
  kind: string;
  enabled: boolean;
  declaredLatencySeconds: number;
  licenseState: string;
  symbolsHint: string[];
  lastPolledAt: string | null;
  lastStatus: string | null;
  lastError: string | null;
  createdAt: string;
  updatedAt: string;
};

export type TradingNewsItem = {
  itemId: string;
  feedId: string;
  source: string;
  url: string;
  title: string;
  summary: string;
  contentHash: string;
  publishedAt: string | null;
  fetchedAt: string;
  availableAt: string;
  licenseState: string;
  symbolsHint: string[];
  knowledgeDocumentId: string | null;
  truth: Record<string, unknown>;
};

export type TradingNewsSignal = {
  signalId: string;
  itemId: string;
  agentId: string;
  missionId: string | null;
  instruments: string[];
  eventType: string;
  direction: string;
  magnitude: number;
  confidence: number;
  horizon: string;
  rationale: string;
  asOf: string;
  modelId: string | null;
  createdAt: string;
  truth: Record<string, unknown>;
};

export type AgentHealth = "unknown" | "idle" | "busy" | "disabled" | "error" | "archived";

export type OrchestratorConfig = {
  memberAgentIds: string[];
  strategy: string;
  routingRules: Record<string, unknown>[];
  maxDelegationDepth: number;
  parallelismLimit: number;
  fanOutPolicy: string;
  retryPolicy: Record<string, unknown>;
  perNodeTimeoutS?: number | null;
  overallTimeoutS?: number | null;
  approvalEscalation: string;
  failureStrategy: string;
  verificationRequired: boolean;
  aggregationAgentId?: string | null;
  defaultModelFallback?: string | null;
};

export type AgentDefinition = {
  agentId: string;
  id?: string;
  name: string;
  kind: AgentDefinitionKind | string;
  description: string;
  role: string;
  enabled: boolean;
  archived: boolean;
  modelRef?: string | null;
  systemPolicy?: string | null;
  capabilities: string[];
  knowledgeSources: string[];
  memoryPolicy: string;
  datasetAccess: string;
  approvalMode: string;
  autonomy: number;
  maxConcurrency: number;
  timeoutS?: number | null;
  maxRetries: number;
  tokenBudget?: number | null;
  tags: string[];
  version: number;
  orchestrator?: OrchestratorConfig | null;
  health: AgentHealth | string;
  healthReason?: string | null;
  status?: string;
  lastRunAt?: string | null;
  lastMissionId?: string | null;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
  origin?: AgentOrigin;
  entityType?: AgentEntityType;
  systemKey?: string | null;
  mutable?: boolean;
  executable?: boolean;
  truth?: Record<string, boolean>;
};

export type AgentOrigin = "system" | "user";
export type AgentEntityType = "agent" | "orchestrator" | "architecture";

export type SystemArchitectureEntry = {
  id: string;
  name: string;
  origin: "system";
  entityType: "orchestrator" | "architecture";
  systemKey: string;
  runtimeKind?: string;
  description?: string;
  status: string;
  enabled?: boolean | null;
  mutable: false;
  sourceModule?: string;
  capabilities?: string[];
  relationships?: Array<{
    relation: string;
    targetId: string;
    targetSystemKey?: string;
  }>;
  metadata?: Record<string, unknown>;
  executable?: boolean;
  truth?: Record<string, boolean>;
};

export type AgentRosterEntry = AgentDefinition | SystemArchitectureEntry;

export type AgentMissionStatus =
  | "queued"
  | "starting"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed"
  | "interrupted"
  | "disabled"
  | string;

export type AgentMission = {
  missionId: string;
  agentId: string;
  title: string;
  request: string;
  status: AgentMissionStatus;
  priority: string;
  progress: number;
  parentMissionId?: string | null;
  runId?: string | null;
  jobIds: string[];
  result?: Record<string, unknown>;
  error?: string | null;
  cancelRequested?: boolean;
  traceId?: string | null;
  createdAt: string;
  startedAt?: string | null;
  updatedAt: string;
  finishedAt?: string | null;
  metadata?: Record<string, unknown>;
};

export type AgentEvent = {
  eventId: string;
  agentId?: string | null;
  missionId?: string | null;
  category: string;
  message: string;
  level: string;
  payload?: Record<string, unknown>;
  createdAt: string;
};

export type AgentFleetSummary = {
  agentsEnabled: boolean;
  agentCount: number;
  orchestratorCount: number;
  total?: number;
  system?: number;
  user?: number;
  agents?: number;
  orchestrators?: number;
  architecture?: number;
  health: Record<string, number>;
  idle?: number;
  busy?: number;
  disabled?: number;
  error?: number;
  active?: number;
  activeMissions: number;
  recentMissions: number;
  truth?: Record<string, boolean>;
};

export type AgentCreatePayload = {
  name: string;
  kind?: string;
  description?: string;
  role?: string;
  enabled?: boolean;
  modelRef?: string | null;
  systemPolicy?: string | null;
  capabilities?: string[];
  knowledgeSources?: string[];
  memoryPolicy?: string;
  datasetAccess?: string;
  approvalMode?: string;
  autonomy?: number;
  maxConcurrency?: number;
  timeoutS?: number | null;
  maxRetries?: number;
  tokenBudget?: number | null;
  tags?: string[];
  orchestrator?: Partial<OrchestratorConfig> | null;
  metadata?: Record<string, unknown>;
};

export type AgentMissionLaunchPayload = {
  request: string;
  title?: string;
  priority?: string;
  useJobs?: boolean;
  dryRun?: boolean;
};

/* ---------- Agents dashboard read-model (GET /api/agents/dashboard) ---------- */

export type AgentsDashboardPool = {
  poolId: string;
  description: string;
  desired: number;
  maxCount: number;
  instances: number;
  ready: number;
  busy: number;
  draining: number;
  degraded: number;
  queue: number | null;
  utilization: number | null;
  resourceClasses: string[];
  jobKinds: string[];
  entrypoint?: string | null;
};

export type AgentsDashboardWorkers = {
  available: boolean;
  active: number | null;
  instances: number | null;
  supervisorHealth: string | null;
  degradedReason?: string | null;
  pools: AgentsDashboardPool[];
  truth?: Record<string, boolean>;
};

/* ---------- Worker Fabric dashboard (GET /api/workers/dashboard) ---------- */

export type WorkerFabricJobSummary = {
  job_id: string;
  capability_id: string;
  state?: string | null;
  human_title?: string | null;
  phase?: string | null;
  message?: string | null;
  domain?: string | null;
  domain_entity_type?: string | null;
  domain_entity_id?: string | null;
  parent_job_id?: string | null;
  root_job_id?: string | null;
  trace_id?: string | null;
  progress?: number | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_percent?: number | null;
  started_at?: string | null;
  elapsed_seconds?: number | null;
  elapsed_display?: string | null;
  worker_pool?: string | null;
  attempt_number?: number | null;
  error_code?: string | null;
  finished_at?: string | null;
};

export type WorkerFabricWorker = {
  worker_id: string;
  pool_id: string;
  slot: number;
  pid: number;
  state: string;
  current_job_id: string | null;
  restart_count: number;
  degraded_reason?: string | null;
  display_name?: string;
  current_work?: string;
  current_job?: WorkerFabricJobSummary | null;
  current_capability?: string | null;
  progress_current?: number | null;
  progress_total?: number | null;
  progress_percent?: number | null;
  elapsed_seconds?: number | null;
  elapsed_display?: string | null;
  heartbeat_age_seconds?: number | null;
  cpu_percent?: number | null;
  rss_mb?: number | null;
  gpu_percent?: number | null;
  vram_mb?: number | null;
  last_heartbeat_at?: string | null;
  started_at?: string | null;
  process_start_identity?: string;
  supported_job_kinds?: string[];
  resource_class?: string[];
};

export type WorkerFabricPool = {
  pool_id: string;
  entrypoint: string;
  default_count: number;
  job_kinds: string[];
  resource_classes: string[];
  description: string;
  max_count: number;
  desired: number;
  env_desired?: number;
  override?: boolean;
  instances: number;
  running?: number;
  ready: number;
  idle?: number;
  busy: number;
  draining: number;
  degraded: number;
  failed?: number;
  starting?: number;
  queued?: number;
  restarts?: number;
  status: string;
  status_reason?: string | null;
  optional?: boolean;
  workers?: WorkerFabricWorker[];
};

export type WorkerFabricDashboard = {
  generated_at: string;
  summary: {
    pools_total: number;
    pools_enabled: number;
    desired_workers: number;
    running_workers: number;
    busy_workers: number;
    idle_workers: number;
    failed_workers: number;
    queue_depth: number;
    degraded_pools: number;
    fabric_status: string;
  };
  control_plane?: { role: string; status: string };
  supervisor: Record<string, unknown>;
  pools: WorkerFabricPool[];
  workers: WorkerFabricWorker[];
  queues: Array<{ pool_id: string; queued: number }>;
  queued_jobs: WorkerFabricJobSummary[];
  failures: WorkerFabricJobSummary[];
  settings?: Record<string, unknown>;
  truth?: Record<string, boolean>;
};

export type AgentsDashboardBucket = {
  start: string;
  end: string;
  completed: number;
  failed: number;
  successRate: number | null;
};

export type AgentsDashboard = {
  generatedAt: string;
  windowHours: number;
  agentsEnabled: boolean;
  fleet: {
    totalAgents: number;
    orchestrators: number;
    orchestratorsFleet: number;
    orchestratorsSystem: number;
    architecture: number;
    memoryLinked: number;
    truth?: Record<string, boolean>;
  };
  workers: AgentsDashboardWorkers;
  missions: {
    queued: number;
    starting: number;
    running: number;
    cancelling: number;
    active: number;
    completedInWindow: number;
    failedInWindow: number;
    cancelledInWindow: number;
  };
  performance: {
    successRate: number | null;
    avgDurationMs: number | null;
    p50DurationMs: number | null;
    p95DurationMs: number | null;
    sampleSize: number;
    eligibleTerminal: number;
    buckets: AgentsDashboardBucket[];
    truth?: Record<string, boolean>;
  };
  failureRetry: {
    windowHours: number;
    success: number;
    failed: number;
    retry: number;
    successRate: number | null;
    retryRate: number | null;
    failedRate: number | null;
    truth?: Record<string, boolean>;
  };
  flow: {
    incoming: number;
    routing: number;
    orchestrators: number;
    executing: number;
    verifying: number | null;
    memoryWriteback: number | null;
    completed: number;
    truth?: Record<string, boolean>;
  };
  teamDistribution: Array<{ team: string; count: number }>;
  lastSync: string;
  truth?: Record<string, boolean>;
};

/* ---------- Worker registry (GET /api/workers, /api/workers/pools) ---------- */

export type WorkerRegistration = {
  worker_id: string;
  pool_id: string;
  slot?: number;
  pid?: number | null;
  host?: string | null;
  started_at?: string | null;
  last_heartbeat_at?: string | null;
  state: string;
  current_job_id?: string | null;
  restart_count?: number;
  degraded_reason?: string | null;
  supported_job_kinds?: string[];
  metadata?: Record<string, unknown>;
  truth?: Record<string, boolean>;
};

export type WorkerPoolDefinition = {
  pool_id: string;
  entrypoint: string;
  default_count: number;
  job_kinds: string[];
  resource_classes: string[];
  description: string;
  max_count: number;
  desired: number;
  instances?: number;
  ready?: number;
  busy?: number;
};

export type WorkersListResponse = {
  workers: WorkerRegistration[];
  pools: WorkerPoolDefinition[];
  settings?: Record<string, unknown>;
  supervisor?: {
    health: string;
    degraded_reason?: string | null;
    last_tick_at?: string | null;
    last_successful_tick_at?: string | null;
    consecutive_tick_failures?: number;
    restart_count?: number;
    [key: string]: unknown;
  };
  truth?: Record<string, boolean>;
};

export type WorkerPoolScaleResponse = {
  pool: WorkerPoolDefinition & { envDesired?: number };
  override: { poolId: string; desiredCount: number; updatedAt: string; updatedBy?: string | null };
  truth?: Record<string, boolean>;
};

export type FleetBulkResult = {
  changed: string[];
  skipped: Array<{ agentId: string; reason: string }>;
  truth?: Record<string, boolean>;
};

/* ---------- Agent Signal Fabric ---------- */

export type AgentSignalType =
  | "TASK_REQUEST"
  | "TASK_HANDOFF"
  | "FINDING"
  | "EVIDENCE"
  | "HYPOTHESIS"
  | "QUESTION"
  | "ANSWER"
  | "ARTIFACT_READY"
  | "VERIFY_REQUEST"
  | "VERIFIED"
  | "REJECTED"
  | "CHALLENGE"
  | "DECISION"
  | "BLOCK"
  | "UNBLOCK"
  | "RESOURCE_REQUEST"
  | "WORKER_SPAWN_REQUEST"
  | "PROGRESS"
  | "WARNING"
  | "ERROR"
  | "CANCEL"
  | "MEMORY_CANDIDATE"
  | "KNOWLEDGE_CANDIDATE"
  | "HEARTBEAT"
  | "COMPLETED"
  | string;

export type AgentSignalPriority = "CRITICAL" | "HIGH" | "NORMAL" | "LOW" | "TELEMETRY" | string;

export type AgentSignal = {
  signalId: string;
  signalType: AgentSignalType;
  senderType: string;
  senderId: string;
  recipientType: string;
  recipientId: string;
  missionId?: string | null;
  runId?: string | null;
  traceId?: string | null;
  parentSignalId?: string | null;
  correlationId?: string | null;
  priority: AgentSignalPriority;
  subject: string;
  payload: Record<string, unknown>;
  artifactRefs: string[];
  evidenceRefs: string[];
  confidence?: number | null;
  requiresAck: boolean;
  expiresAt?: string | null;
  idempotencyKey?: string | null;
  hopCount: number;
  maxHops: number;
  status: string;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
  truth?: Record<string, boolean>;
};

export type AgentSignalDelivery = {
  deliveryId: string;
  signalId: string;
  recipientType: string;
  recipientId: string;
  resolvedAgentId?: string | null;
  state: string;
  attemptCount: number;
  maxAttempts: number;
  nextAttemptAt?: string | null;
  claimedBy?: string | null;
  claimedAt?: string | null;
  leaseExpiresAt?: string | null;
  deliveredAt?: string | null;
  acknowledgedAt?: string | null;
  consumedAt?: string | null;
  ackConsumer?: string | null;
  lastError?: string | null;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
};

export type AgentSignalDeadLetter = {
  deadLetterId: string;
  signalId: string;
  deliveryId?: string | null;
  recipientType?: string | null;
  recipientId?: string | null;
  attemptCount: number;
  lastError?: string | null;
  firstFailureAt?: string | null;
  lastFailureAt?: string | null;
  reason: string;
  retryable: boolean;
  signalSnapshot?: Record<string, unknown>;
  createdAt: string;
  retriedAt?: string | null;
  metadata?: Record<string, unknown>;
};

export type AgentSignalMetrics = {
  windowMinutes?: number;
  since?: string;
  signalsTotal: number;
  signalsPerMinute?: number;
  byType?: Record<string, number>;
  delivered: number;
  acknowledged: number;
  failed: number;
  deadLetter: number;
  expired: number;
  handoffs?: number;
  verificationRequests?: number;
  rejections?: number;
  blocks?: number;
  knowledgeCandidates?: number;
  avgDeliveryLatencyS?: number | null;
  p95DeliveryLatencyS?: number | null;
  avgAckLatencyS?: number | null;
  retryRate?: number;
  dedupeKeys?: number;
  truth?: Record<string, boolean>;
};

export type AgentCommunicationGraph = {
  since?: string;
  missionId?: string | null;
  nodes: Array<{ id: string; kind?: string }>;
  edges: Array<{
    from: string;
    to: string;
    signalCount: number;
    handoffs?: number;
    verificationRequests?: number;
    blocks?: number;
    errors?: number;
    avgDeliveryLatencyS?: number | null;
    byType?: Record<string, number>;
  }>;
  truth?: Record<string, boolean>;
};

export type SignalCausalChain = {
  signal: AgentSignal;
  parent?: AgentSignal | null;
  ancestors?: AgentSignal[];
  children?: AgentSignal[];
  related?: AgentSignal[];
  deliveries?: AgentSignalDelivery[];
  mission?: AgentMission | null;
  events?: AgentEvent[];
  truth?: Record<string, boolean>;
};

export type AgentSignalStats = {
  agentId: string;
  signalsSent: number;
  signalsReceived: number;
  handoffs: number;
  verificationRequests: number;
  blocksRejections: number;
  windowHours?: number;
  truth?: Record<string, boolean>;
};

/* ---------- Analytics ---------- */

export type AnalyticsOverview = {
  range: string;
  from: string;
  to: string;
  collectedAt: string;
  totals: Record<string, { total?: number; completed?: number; failed?: number; running?: number; cancelled?: number; other?: number } | number>;
  statusBreakdown?: Record<string, Record<string, number>>;
  truth?: Record<string, boolean>;
};

export type AnalyticsAgentsResponse = {
  range: string;
  from: string;
  to: string;
  collectedAt: string;
  agents: Array<{
    agentId: string;
    name?: string | null;
    total: number;
    completed: number;
    failed: number;
    cancelled: number;
    active: number;
  }>;
  truth?: Record<string, boolean>;
};

export type AnalyticsTrainingResponse = {
  range: string;
  from: string;
  to: string;
  collectedAt: string;
  byStatus: Record<string, number>;
  byMethod: Array<{ method: string; count: number }>;
  checkpoints: number;
  truth?: Record<string, boolean>;
};

export type AnalyticsDatasetsResponse = {
  range: string;
  from: string;
  to: string;
  collectedAt: string;
  inventory: { datasets: number; versions: number; indexes: number };
  jobsByStatus: Record<string, number>;
  jobsByType: Array<{ jobType: string; count: number }>;
  truth?: Record<string, boolean>;
};

export type AnalyticsToolsResponse = {
  range: string;
  from: string;
  to: string;
  collectedAt: string;
  capabilities: Array<{
    capabilityId: string;
    total: number;
    completed: number;
    failed: number;
  }>;
  approvals: { total: number };
  truth?: Record<string, boolean>;
};

/* ---------- Tasks / Taken ---------- */

export type TaskBoardColumn = "backlog" | "in_progress" | "review" | "done";
export type TaskPriorityValue = "low" | "medium" | "high";
export type TaskExecutionBinding = "manual" | "agent_mission" | "capability_job" | "workflow";
export type TaskAssigneeType = "none" | "human" | "agent" | "system";

export type TaskBlockingDependency = {
  taskId: string;
  title: string;
  boardColumn: TaskBoardColumn | string;
  executionState?: string | null;
};

export type TaskRecord = {
  taskId: string;
  title: string;
  description: string;
  boardColumn: TaskBoardColumn | string;
  blocked: boolean;
  blockedReason?: string | null;
  blockedReasonCode?: string | null;
  priority: TaskPriorityValue | string;
  tags: string[];
  project?: string | null;
  assigneeType: TaskAssigneeType | string;
  assigneeId?: string | null;
  assigneeName?: string | null;
  dueAt?: string | null;
  plannedStartAt?: string | null;
  completedAt?: string | null;
  progress?: number | null;
  displayProgress?: number | null;
  createdAt: string;
  updatedAt: string;
  archivedAt?: string | null;
  sourceType?: string;
  sourceRef?: string | null;
  executionBinding: TaskExecutionBinding | string;
  jobId?: string | null;
  workflowId?: string | null;
  missionId?: string | null;
  runId?: string | null;
  approvalId?: string | null;
  scheduleId?: string | null;
  capabilityId?: string | null;
  capabilityArguments?: Record<string, unknown>;
  missionRequest?: string | null;
  executionState?: string | null;
  executionError?: string | null;
  executionPhase?: string | null;
  executionAttempt?: number | null;
  executionProgress?: number | null;
  executionStartedAt?: string | null;
  executionFinishedAt?: string | null;
  boardOrder?: number;
  createdBy?: string;
  metadata?: Record<string, unknown>;
  subtaskCount?: number;
  subtaskCompleted?: number;
  blockingDependencies?: TaskBlockingDependency[];
};

export type TaskSummary = {
  active: number;
  inProgress: number;
  blocked: number;
  completedToday: number;
  overdue: number;
  agentsAssigned: number;
  completedPreviousPeriod?: number | null;
  completedTodayDelta?: string | null;
  columnCounts: Record<string, number>;
  timezone: string;
};

export type TaskEvent = {
  eventId: string;
  taskId: string;
  eventType: string;
  actorType?: string;
  actorId?: string | null;
  sourceType?: string | null;
  sourceRef?: string | null;
  payload?: Record<string, unknown>;
  createdAt: string;
  taskTitle?: string | null;
};

export type TaskSubtask = {
  subtaskId: string;
  taskId: string;
  title: string;
  completed: boolean;
  completedAt?: string | null;
  sortOrder: number;
  createdAt: string;
  updatedAt: string;
};

export type TaskNote = {
  noteId: string;
  taskId: string;
  body: string;
  authorType?: string;
  authorId?: string | null;
  authorName?: string | null;
  createdAt: string;
  updatedAt: string;
};

export type TaskDependencyTarget = {
  taskId: string;
  title: string;
  boardColumn: TaskBoardColumn | string;
  executionState?: string | null;
  blocked?: boolean;
  completed?: boolean;
};

export type TaskDependency = {
  dependencyId: string;
  taskId: string;
  dependsOnTaskId: string;
  soft: boolean;
  createdAt: string;
  dependsOn?: TaskDependencyTarget;
};

export type TaskTimelineItem = {
  taskId: string;
  title: string;
  boardColumn: TaskBoardColumn | string;
  startAt?: string | null;
  endAt?: string | null;
  kind: string;
  executionState?: string | null;
  blocked?: boolean;
};

export type TaskWorkloadEntry = {
  assigneeId?: string | null;
  assigneeName: string;
  assigneeType: string;
  activeCount: number;
  inProgressCount: number;
  blockedCount: number;
  overdueCount: number;
  maxConcurrency?: number | null;
  capacityPct?: number | null;
};

export type TaskAgentActivity = {
  agentId: string;
  name: string;
  status: string;
  detail?: string | null;
  phase?: string | null;
  progress?: number | null;
  activeTaskCount: number;
  activeTaskId?: string | null;
  lastRunAt?: string | null;
  missionId?: string | null;
};

export type TaskWeekdayCompletions = {
  timezone: string;
  weekStart: string;
  bars: number[];
  weekdays: string[];
};

export type TaskCreatePayload = {
  title: string;
  description?: string;
  priority?: string;
  boardColumn?: string;
  tags?: string[];
  project?: string | null;
  assigneeType?: string;
  assigneeId?: string | null;
  assigneeName?: string | null;
  dueAt?: string | null;
  plannedStartAt?: string | null;
  progress?: number | null;
  executionBinding?: string;
  capabilityId?: string | null;
  capabilityArguments?: Record<string, unknown>;
  missionRequest?: string | null;
  workflowId?: string | null;
  scheduleId?: string | null;
  metadata?: Record<string, unknown>;
};

export type TaskPatchPayload = {
  title?: string;
  description?: string;
  priority?: string;
  boardColumn?: string;
  tags?: string[];
  project?: string | null;
  assigneeType?: string;
  assigneeId?: string | null;
  assigneeName?: string | null;
  dueAt?: string | null;
  plannedStartAt?: string | null;
  progress?: number | null;
  manualBlock?: boolean | null;
  blockedReason?: string | null;
};

export type TaskQuickCapturePayload = {
  title: string;
  description?: string;
  priority?: string;
  dueAt?: string | null;
  assigneeType?: string;
  assigneeId?: string | null;
  assigneeName?: string | null;
};

export type TaskAutoPlanProposal = {
  title: string;
  description?: string;
  priority?: string;
  suggestedAssigneeId?: string | null;
  tags?: string[];
  dueAt?: string | null;
  dependencies?: number[];
};

export type TaskListFilters = {
  search?: string;
  boardColumn?: string;
  executionState?: string;
  priority?: string;
  assignee?: string;
  blocked?: boolean;
  overdue?: boolean;
  dueFrom?: string;
  dueTo?: string;
  project?: string;
  archived?: boolean;
  datePreset?: string;
  timezone?: string;
  limit?: number;
  offset?: number;
};

/** Minimal job shape for listJobs hardening. */
export type JobRecord = {
  jobId?: string;
  id?: string;
  state?: string;
  status?: string;
  capabilityId?: string | null;
  error?: string | null;
  createdAt?: string;
  updatedAt?: string;
  [key: string]: unknown;
};
