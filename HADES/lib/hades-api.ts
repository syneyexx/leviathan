import { createPluginApi, type PluginToolLogEntry } from "./api/plugins";

export type {
  HadesPlugin,
  PluginEvent,
  PluginTimelineItem,
  PluginTool,
  PluginToolCall,
  PluginToolLogEntry,
} from "./api/plugins";

export const API_BASE = (import.meta.env.VITE_HADES_API_URL as string | undefined) ?? "http://127.0.0.1:8000/api";

/** Generated OpenAPI-focused contracts (regenerate: `npm run contracts:openapi`). */
export type {
  ApiErrorBody,
  BrainGraphResponse,
  CodingJobsListResponse,
  ModelsGatewayResponse,
  ModelsListResponse,
  PageMeta,
} from "./generated/api-contracts";

export class HadesApiError extends Error {
  status: number;
  detail: unknown;

  constructor(message: string, status = 0, detail: unknown = null) {
    super(message);
    this.name = "HadesApiError";
    this.status = status;
    this.detail = detail;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  const isFormData = typeof FormData !== "undefined" && init?.body instanceof FormData;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: isFormData ? init?.headers : { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
  }
  if (!response.ok) {
    let message = `API-fout ${response.status}`;
    let detail: unknown = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      detail = body.detail;
      if (typeof body.detail === "string") message = body.detail;
      else if (body.detail && typeof body.detail === "object" && "message" in body.detail) message = String((body.detail as { message: unknown }).message);
    } catch {
      // Keep the status fallback for non-JSON errors.
    }
    throw new HadesApiError(message, response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export type SystemHealth = {
  backend: "ok";
  lm_studio: "connected" | "disconnected";
  models: number;
  latency_ms?: number;
  active_model?: string | null;
  detail?: string;
  version: string;
  storage: { path: string; size_bytes: number };
  knowledge?: KnowledgeStats;
  agents?: number;
  plugins?: number;
  overall?: "ok" | "warn" | "error";
  checks?: Array<{ id: string; label: string; status: "ok" | "warn" | "error"; detail?: string }>;
  disk_free_bytes?: number | null;
};

export type ModelProfile = {
  model_id: string;
  temperature: number;
  top_p: number;
  top_k: number;
  max_tokens: number;
  repeat_penalty: number;
  seed: number;
  system_prompt: string;
  is_active: boolean;
};

export type LmModel = { id: string; object?: string; owned_by?: string; created?: number };
export type ModelGatewayOverview = {
  models_in_use: string[];
  active_calls: Array<Record<string, unknown>>;
  active_count: number;
  queue_depth: number;
  capacity: Record<string, unknown>;
  fallback_reason?: string | null;
  errors?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
};
export type ModelsResponse = {
  connected: boolean;
  models: LmModel[];
  active_profile: ModelProfile;
  latency_ms?: number;
  error?: string;
  gateway?: ModelGatewayOverview;
  router_capacity?: Record<string, unknown>;
};

export type Conversation = {
  id: string;
  title: string;
  model_id: string | null;
  system_prompt_override: string | null;
  message_count: number;
  active_branch_id?: string | null;
  created_at: string;
  updated_at: string;
};

/** Persisted Chat timeline engine binding (HADES-10 Phase 3A). */
export type ConversationRunType =
  | "tool"
  | "coding"
  | "research"
  | "work"
  | "approval"
  | "artifact"
  | "verification"
  | "chat";

export type ConversationRunLink = {
  id: string;
  conversation_id: string;
  run_id: string;
  run_type: ConversationRunType | string;
  status: string;
  title?: string;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ConversationBranch = {
  id: string;
  conversation_id: string;
  parent_branch_id: string | null;
  fork_message_id: string;
  title: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};
export type ChatMessage = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  client_request_id?: string | null;
  parent_message_id?: string | null;
  branch_id?: string | null;
  revised_from_id?: string | null;
  is_active?: boolean;
  metadata?: Record<string, unknown>;
};

export type HadesArtifact = {
  id: string;
  name: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  checksum_sha256: string;
  version: number;
  parent_artifact_id?: string | null;
  status: string;
  storage_path: string;
  conversation_id?: string | null;
  task_id?: string | null;
  project_id?: string | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  updated_at: string;
};

export type ApprovalRequest = {
  id: string;
  kind: string;
  status: string;
  tool_name?: string | null;
  plugin_id?: string | null;
  expected_effect: string;
  arguments_preview?: Record<string, unknown>;
  destination_paths?: string[];
  task_id?: string | null;
  conversation_id?: string | null;
  expires_at?: string | null;
  created_at: string;
  resume_ok?: boolean;
  resume_error?: string | null;
};

export type InboxItem = {
  id: string;
  kind: string;
  title: string;
  body: string;
  ref_type?: string | null;
  ref_id?: string | null;
  status: string;
  task_id?: string | null;
  conversation_id?: string | null;
  created_at: string;
};

export type GlobalSearchResult = {
  query: string;
  groups: Record<string, Array<{ type: string; id: string; title: string; snippet: string; href?: string; updated_at?: string }>>;
  commands: Array<{ id: string; title: string; href: string; action: string }>;
};

export type TaskStatus = "queued" | "running" | "completed" | "failed" | "cancelled" | "blocked";
export type HadesTask = {
  id: string;
  title: string;
  prompt: string;
  agent: string;
  priority: "low" | "normal" | "high";
  status: TaskStatus;
  model_id: string | null;
  progress: number;
  result: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};
export type TaskEvent = { id: number; task_id: string; level: string; message: string; created_at: string };

export type WorkStep = {
  id: string;
  task_id: string;
  step_index: number;
  agent_id: string;
  kind: string;
  title: string;
  instruction: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  output: string;
  error: string | null;
  created_at: string;
  updated_at: string;
  step_key?: string;
  depends_on?: string[];
};
export type WorkCheckpoint = { id: string; task_id: string; state: Record<string, unknown>; created_at: string };
export type SpecialistContract = {
  agent_id: string;
  name: string;
  responsibility: string;
  required_inputs: string[];
  expected_outputs: string[];
  capabilities: string[];
  allowed_tools: string[];
  model_profile: string;
  context_kinds: string[];
  budget: Record<string, number>;
  acceptance_criteria: string[];
  error_recovery: string;
  deterministic?: boolean;
  planned_only?: boolean;
  enabled?: boolean;
};
export type WorkSummary = {
  steps: WorkStep[];
  checkpoint: WorkCheckpoint | null;
  counts: Record<string, number>;
  waves?: string[][];
};

export type MemoryItem = {
  id: string;
  title: string;
  content: string;
  summary: string;
  collection: string;
  tags: string[];
  source: string;
  scope?: "session" | "project" | "global";
  status?: string;
  supersedes?: string | null;
  superseded_by?: string | null;
  forgotten_marker?: boolean;
  created_at: string;
  updated_at: string;
};
export type MemoriesResponse = {
  items: MemoryItem[];
  stats: { items: number; collections: number; indexed: number; database_bytes: number; historical?: number };
  collections: string[];
  scope_filter?: string | null;
};

export type BrainNode = {
  id: string;
  label: string;
  kind: string;
  description: string;
  tags: string[];
  source: string;
  created_at: string;
  updated_at: string;
  open_href?: string;
  persistent?: boolean;
  pos_x?: number | null;
  pos_y?: number | null;
  pinned?: boolean;
  content_editable?: boolean;
  layout_movable?: boolean;
  status?: string;
  version?: string;
};
export type BrainLink = { source_id: string; target_id: string; relation: string; relation_kind?: string; external?: boolean; provenance?: string };
export type BrainLayoutPosition = { entity_id: string; pos_x: number; pos_y: number; pinned?: boolean; updated_at?: string };
export type BrainLayout = {
  view_id: string;
  viewport: { x: number; y: number; zoom: number; updated_at?: string | null };
  positions: BrainLayoutPosition[];
};
export type BrainResponse = {
  nodes: BrainNode[];
  links: BrainLink[];
  layout?: BrainLayout;
  view_id?: string;
  counts: {
    nodes: number;
    links: number;
    available?: Record<string, number>;
    included?: Record<string, number>;
    truncated?: boolean;
    visible_hint?: number;
  };
  relation_kinds?: string[];
};

export type ClaimRecord = {
  id: string;
  text: string;
  provenance: string;
  verification_status: string;
  source_kind?: string;
  observed_at?: string;
  valid_from?: string | null;
  valid_until?: string | null;
  supports?: string[];
  contradicts?: string[];
  evidence_links?: Array<Record<string, unknown>>;
  task_id?: string | null;
  superseded_by?: string | null;
  confidence?: number | null;
  confidence_basis?: string;
  confidence_note?: string;
  [key: string]: unknown;
};

export type KnowledgeHarvestResult = {
  seed_url: string;
  pages_crawled: number;
  documents_discovered: number;
  documents_ingested: number;
  page_sources: KnowledgeSource[];
  documents: KnowledgeSource[];
  failures: Array<{ url: string; error: string }>;
  authorized_downloads: boolean;
};

export type AppSettings = {
  lm_studio_base_url: string;
  lm_studio_api_key: string;
  request_timeout_seconds: number | null;
  model_refresh_seconds: number | null;
  streaming: boolean;
  auto_connect: boolean;
  language: "nl" | "en";
  theme: "light" | "dark" | "system";
  ui_style: "lux" | "finalbeta" | "classic" | "obsidian" | "beta" | "beta2";
  motion_level: "reduced" | "standard" | "cinematic";
  native_runtime_mode: "auto" | "enabled" | "disabled";
  max_concurrent_tasks: number | null;
  file_read_policy: "allow" | "ask" | "block";
  file_write_policy: "allow" | "ask" | "block";
  network_policy: "allow" | "ask" | "block";
  subprocess_policy: "allow" | "ask" | "block";
  reasoning_profile: "normal" | "medium" | "high" | "adaptive" | "fast" | "standard" | "maximum";
  conversation_learning: boolean;
  auto_memory_mode: "off" | "project" | "all";
  max_retrieval_items: number | null;
  max_retrieval_chars: number | null;
  max_retrieval_chars_per_hit: number | null;
  research_default_depth: "quick" | "standard" | "deep" | "expert";
  system_prompt: string;
  plugin_autonomous_tools: boolean;
  auto_web_research: boolean;
  plugin_auto_install_dependencies: boolean;
  max_tool_rounds: number | null;
  expert_mastery_target: number;
  expert_max_cycles: number | null;
  max_model_calls_per_task: number | null;
  max_specialist_steps: number | null;
  max_subtasks: number | null;
  max_dependency_depth: number | null;
  max_parallel_steps: number | null;
  max_model_concurrency: number | null;
  model_fallback_order: string[];
  role_model_overrides: Record<string, string>;
  allow_cloud_model_fallback: boolean;
  retrieval_lexical_weight: number;
  retrieval_semantic_weight: number;
  retrieval_multilingual_expand: boolean;
  enable_semantic_retrieval: boolean;
  enable_context_compiler_chat: boolean;
  embedding_model_id: string;
  embedding_timeout_seconds: number | null;
  embedding_batch_size: number | null;
  retrieval_diversity_window: number | null;
  memory_auto_promote: boolean;
  memory_write_enabled: boolean;
  memory_default_scope: "session" | "project" | "global";
  research_max_questions: number | null;
  research_prefer_local: boolean;
  progress_events_enabled: boolean;
  stream_provisional_text: boolean;
  terminal_allowlist: string[];
  onboarding_completed_at: string;
  /** Optimistic concurrency token for Settings / Control Center editors. */
  config_revision: number;
  voice_enabled: boolean;
  voice_asr_provider: string;
  voice_asr_model: string;
  voice_asr_device: "auto" | "cpu" | "cuda";
  voice_asr_compute_type: string;
  voice_tts_provider: "piper" | "browser";
  voice_tts_voice: string;
  voice_tts_speed: number;
  voice_tts_volume: number;
  voice_language: "nl" | "en" | "auto";
  voice_spoken_answers_default: boolean;
  voice_speak_style: "compact" | "full";
  voice_turn_mode: "manual" | "auto";
  voice_vad_sensitivity: number;
  voice_vad_end_silence_ms: number;
  voice_barge_in: boolean;
  voice_wake_word_enabled: boolean;
  voice_session_idle_seconds: number;
  voice_keep_recordings: boolean;
  voice_input_device_id: string;
  voice_output_device_id: string;
  voice_setup_completed_at: string;
  spoken_answers_enabled: boolean;
  tts_provider: "none" | "voicestudio";
  tts_base_url: string;
  tts_api_key: string;
  tts_voice_id: string;
  tts_model: string;
  tts_speed: number;
  tts_language: string;
  tts_response_format: "mp3" | "opus" | "aac" | "flac" | "wav" | "pcm";
  tts_sentence_chunking: boolean;
  tts_min_free_ram_mb: number;
  tts_min_free_vram_mb: number;
  tts_instruct: string;
  tts_description: string;
  stt_provider: "none" | "voicestudio" | "paste";
  stt_base_url: string;
  stt_api_key: string;
  stt_model: string;
  stt_language: string;
  stt_echo_guard_ms: number;
};

export type NeuralProductSettings = {
  neural_allow: boolean;
  neural_mode: "off" | "shadow" | "read" | "learn";
  neural_requirement: "off" | "preferred" | "required";
  neural_shadow_sample_rate: number;
  neural_dual_memory_enabled: boolean;
  neural_domain_coding_enabled: boolean;
  neural_domain_research_enabled: boolean;
  neural_domain_trading_enabled: boolean;
  neural_max_concurrent_infer: number;
  learn_default?: string;
  notes?: string[];
};

export type NeuralProductStatus = {
  ready: boolean;
  product_state?: string;
  dependency_available?: boolean;
  started?: boolean;
  allow?: boolean;
  mode?: string;
  settings?: Partial<NeuralProductSettings>;
  health?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  capacity?: Record<string, unknown>;
  persistence?: Record<string, unknown>;
  domains?: Record<string, unknown>;
  artifacts?: {
    base_model?: string;
    hades_adapter?: string | null;
    fast_memory?: string;
    slow_memory?: string | null;
    exact_brain?: string;
  };
  error?: string;
};

export type SpeechEchoGuard = {
  blocked: boolean;
  playback_active: boolean;
  remaining_ms: number;
  reason?: string | null;
  note?: string;
};

export type NativeRuntimeStatus = {
  mode: "auto" | "enabled" | "disabled" | string;
  available: boolean;
  connected: boolean;
  version: string | null;
  protocol_version: number | null;
  compiler: string | null;
  uptime_ms: number | null;
  capabilities: string[];
  fallback_active: boolean;
  executable: string | null;
  last_error: string | null;
  process_count?: number | null;
  service_count?: number | null;
  health?: Record<string, unknown>;
};

export type SpeechStatus = {
  spoken_answers_enabled: boolean;
  tts: {
    provider: string;
    configured: boolean;
    available: boolean;
    base_url: string;
    voice_id: string;
    model: string;
    streaming_speech: boolean;
    sentence_chunking?: boolean;
    supported_settings: Record<string, boolean>;
    engines: Array<Record<string, unknown>>;
    voices: Array<Record<string, unknown>>;
    version?: string | null;
    error?: string | null;
    recovery?: Array<Record<string, string>>;
    selected_engine?: Record<string, unknown> | null;
    streaming_note?: string;
  };
  stt: {
    provider: string;
    configured: boolean;
    available: boolean;
    base_url: string;
    model: string;
    error?: string | null;
    recovery?: Array<Record<string, string>>;
    note?: string;
  };
  echo_guard: SpeechEchoGuard;
  active_generation_id?: string | null;
  inflight?: number;
  last_error?: string | null;
  lm_studio_independence?: boolean;
  note?: string;
};

export type SpeechVoicesResponse = {
  voices: Array<Record<string, unknown>>;
  engines: Array<Record<string, unknown>>;
  supported_settings: Record<string, boolean>;
  selected_engine?: Record<string, unknown> | null;
  streaming_speech: boolean;
  version?: string | null;
  base_url?: string;
};

export type SpeechSpeakPlan = {
  generation_id: string;
  provider: string;
  streaming_speech: boolean;
  sentence_chunking: boolean;
  chunk_count: number;
  chunks: Array<{ index: number; text: string }>;
  speakable_chars: number;
};

export type SpeechChunkAudio = {
  generation_id: string;
  chunk_index: number;
  text: string;
  mime_type: string;
  response_format: string;
  bytes: number;
  audio_base64: string;
  voice: string;
  model: string;
  provider: string;
  streaming_speech?: boolean;
  skipped?: boolean;
};

export type ControlDefinition = {
  id: string;
  storage_key: string;
  category: string;
  label: string;
  description: string;
  type: string;
  default_value: unknown;
  allow_unlimited?: boolean;
  min?: number | null;
  max?: number | null;
  enum_values?: string[];
  scopes: string[];
  source: string;
  restart_required: boolean;
  apply_mode: string;
  risk_level: string;
  overrideable: boolean;
  unit?: string;
  /** null/undefined = unaudited; true = enforced; false = stored only */
  implemented?: boolean | null;
};

export type ControlEffectiveValue = {
  setting_id: string;
  configured: unknown;
  effective: unknown;
  source: string;
  scope: string;
  overrideable: boolean;
  clamped: boolean;
  clamp_reason?: string | null;
  capability_max?: unknown;
  unlimited_requested?: boolean;
  inheritance?: Array<Record<string, unknown>>;
};

export type ControlPreset = {
  id: string;
  label: string;
  description: string;
  values: Record<string, unknown>;
  warnings?: string[];
};

export type KnowledgeStats = { sources: number; chunks: number; token_estimate: number; types: Record<string, number> };
export type KnowledgeSource = {
  id: string;
  title: string;
  source_type: string;
  uri: string;
  local_path: string | null;
  content_hash: string | null;
  metadata: Record<string, unknown>;
  status: string;
  created_at: string;
  updated_at: string;
};
export type KnowledgeMatch = {
  chunk_id: string;
  source_id: string;
  title: string;
  heading: string;
  content: string;
  rank: number;
  source_type: string;
  uri: string;
  local_path: string | null;
  updated_at: string;
};

export type Workspace = { id: string; name: string; root_path: string; created_at: string; updated_at: string };
export type IndexedFile = {
  id: string;
  workspace_id: string | null;
  path: string;
  name: string;
  extension: string;
  size_bytes: number;
  mtime: number;
  content_hash: string | null;
  source_id: string | null;
  status: "ready" | "error" | "unsupported" | string;
  error: string | null;
  indexed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type ResearchProject = {
  id: string;
  title: string;
  topic: string;
  depth: "quick" | "standard" | "deep" | "expert";
  status: "queued" | "running" | "completed" | "failed" | "cancelled" | string;
  progress: number;
  allow_web: boolean;
  authorized_downloads: boolean;
  source_inputs: string[];
  findings: string;
  report: string;
  max_rounds?: number | null;
  agent_count?: number;
  metrics: {
    mastery?: number;
    coverage_score?: number;
    metric_kind?: string;
    metric_note?: string;
    mastery_target?: number;
    source_count?: number;
    evidence_chunks?: number;
    domain_diversity?: number;
    local_source_diversity?: number;
    research_rounds?: number;
    configured_rounds?: number;
    agent_count?: number;
    queries?: string[];
    authorized_downloads?: boolean;
    status?: string;
    contradictions?: string[];
  };
  error: string | null;
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
};
export type ResearchEvent = { id: number; project_id: string; level: string; message: string; created_at: string };

export type ResearchCoverageSummary = {
  ok: boolean;
  project_id?: string;
  depth: string;
  complete: boolean;
  incomplete: boolean;
  needs_more_evidence: boolean;
  coverage_score: number;
  mastery_target: number;
  source_count: number;
  source_target: number;
  evidence_chunks: number;
  domain_diversity: number;
  metric_kind: string;
  metric_note: string;
  gaps: string[];
  contradictions: string[];
  status: string;
  metric_status: string | null;
  label: string;
};

export type AgentStatus =
  | "idle"
  | "running"
  | "busy"
  | "error"
  | "disabled"
  | "unavailable";

export type AgentHealth = "healthy" | "degraded" | "error" | "offline";

export type AgentUsage = {
  input_tokens: number | null;
  output_tokens: number | null;
  total_tokens: number | null;
  cached_tokens: number | null;
  reasoning_tokens: number | null;
  requests: number;
  cost: number | null;
  known: boolean;
};

export type AgentMetrics = {
  requests: number;
  runs: number;
  successful_runs: number;
  failed_runs: number;
  success_rate: number | null;
  avg_execution_seconds: number | null;
};

export type AgentTaskRef = {
  task_id?: string | null;
  task_title?: string | null;
  step_id?: string | null;
  step_title?: string | null;
  step_index?: number | null;
  started_at?: string | null;
  finished_at?: string | null;
  progress?: number | null;
  parent_agent?: string | null;
  agent_id?: string | null;
  status?: string | null;
  error?: string | null;
};

export type AgentRun = {
  id: string;
  kind: "task" | "work_step" | string;
  title?: string | null;
  status?: string | null;
  model_id?: string | null;
  task_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  updated_at?: string | null;
  error?: string | null;
  progress?: number | null;
};

export type HadesAgent = {
  id: string;
  name: string;
  name_raw?: string;
  role: string;
  type?: string;
  description: string;
  reasoning_profile: string | null;
  enabled: boolean;
  planned?: boolean;
  implemented?: boolean;
  available?: boolean;
  status?: AgentStatus;
  status_label?: string;
  health?: AgentHealth;
  health_label?: string;
  provider?: string | null;
  model?: string | null;
  model_settings?: {
    temperature?: number | null;
    top_p?: number | null;
    max_tokens?: number | null;
    context_window?: number | null;
  };
  capabilities?: string[];
  tools?: string[];
  allowed_tools: string[];
  max_subtasks: number;
  permissions?: { tools_policy?: string; deterministic?: boolean };
  current_task?: AgentTaskRef | null;
  last_task?: AgentTaskRef | null;
  last_activity_at?: string | null;
  last_error?: string | null;
  queue?: { tasks: number; steps: number; pending: number };
  metrics?: AgentMetrics;
  usage?: AgentUsage;
  hierarchy?: { parent_id: string | null; child_ids: string[] };
  contract?: Record<string, unknown> | null;
  controls?: {
    can_enable: boolean;
    can_disable: boolean;
    can_cancel_current: boolean;
    can_refresh: boolean;
    can_view_runs: boolean;
    can_view_logs: boolean;
  };
  created_at: string;
  updated_at: string;
  heartbeat_at?: string | null;
  recent_runs?: AgentRun[];
  recent_errors?: Array<{ at?: string | null; source?: string; id?: string; message?: string }>;
  recent_logs?: Array<{ id?: number; task_id?: string; level?: string; message?: string; created_at?: string; agent?: string; task_title?: string }>;
  usage_events?: Array<Record<string, unknown>>;
  configuration?: Record<string, unknown>;
};

export type AgentsConsoleResponse = {
  items: HadesAgent[];
  summary: {
    total: number;
    enabled: number;
    running: number;
    planned: number;
    errors: number;
    open_queue: number;
    total_tokens: number | null;
    total_cost: number | null;
    avg_success_rate: number | null;
    provider_connected: boolean;
    active_model: string | null;
    provider: string;
  };
  activity: Array<{
    at?: string | null;
    agent_id?: string | null;
    task_id?: string | null;
    level?: string;
    message?: string;
    source?: string;
  }>;
  router: string;
};


export type McpServer = {
  id: string;
  name: string;
  description?: string;
  transport: "stdio" | "streamable_http" | string;
  enabled: boolean;
  auto_connect?: boolean;
  owner_kind?: "managed" | "plugin" | string;
  owner_plugin_id?: string | null;
  catalog_id?: string | null;
  command?: { executable?: string; args?: string[]; cwd?: string | null } | null;
  env?: { plain?: Record<string, string>; secret_keys?: string[]; secret_refs?: Record<string, string> };
  endpoint_url?: string | null;
  auth_method?: "none" | "bearer" | "oauth" | string;
  headers?: Record<string, string>;
  has_auth_secret?: boolean;
  timeout_seconds?: number;
  connection_status?: string;
  connection_status_effective?: string;
  auth_status?: string;
  last_check_at?: string | null;
  last_error?: string | null;
  last_error_kind?: string | null;
  protocol_version?: string | null;
  discovery_complete?: boolean;
  tool_count?: number;
  allowed_tool_count?: number;
  chatbot_tool_count?: number;
  session_live?: boolean;
  metadata?: Record<string, unknown>;
};

export type McpTool = {
  id: string;
  server_id: string;
  remote_name: string;
  model_name: string;
  description?: string;
  input_schema?: Record<string, unknown>;
  output_schema?: Record<string, unknown> | null;
  annotations?: Record<string, unknown>;
  allowed: boolean;
  chatbot_enabled: boolean;
  require_approval: boolean;
  schema_issue?: string | null;
  last_executed_at?: string | null;
  last_result_status?: string | null;
  server_name?: string;
  connection_status?: string;
};

export type McpCatalogItem = {
  id: string;
  name: string;
  description?: string;
  transport?: string;
  status?: "available" | "configured" | "connected" | "blocked_or_incomplete" | string;
  auth_methods?: string[];
  auth_hint?: string;
  docs_url?: string | null;
  oauth_supported?: boolean;
  oauth_note?: string;
  plugin_id?: string | null;
  owned_by_plugin?: boolean;
  configured_servers?: Array<Record<string, unknown>>;
  endpoint_url?: string;
  command_template?: { executable: string; args?: string[] };
};

export type McpMarketCandidate = {
  name?: string;
  slug?: string;
  description?: string;
  why?: string;
  needs_setup?: boolean;
  requires_auth?: boolean;
  side_effect_class?: string;
};

export type McpMarketSearchResult = {
  status?: string;
  query?: string;
  candidates?: McpMarketCandidate[];
  model_called?: boolean;
  cache?: string;
  note?: string;
  proposal?: Record<string, unknown>;
  result?: Record<string, unknown>;
};

export type McpExecution = {
  id: string;
  server_id: string;
  tool_id: string;
  status: string;
  error_kind?: string | null;
  started_at?: string;
  ended_at?: string | null;
  duration_ms?: number | null;
  input?: Record<string, unknown>;
  result?: Record<string, unknown> | null;
  cancel_requested?: boolean;
};

export type PaperTradingState = {
  settings: { enabled: boolean; kill_switch: boolean; updated_at: string };
  wallets: Array<{ asset: string; balance: number; reserved: number; updated_at: string }>;
  positions: Array<{ id: string; symbol: string; side: string; quantity: number; entry_price: number; cost_basis: number; status: "open" | "closed"; realized_pnl: number; opened_at: string; closed_at: string | null }>;
  orders: Array<{ id: string; symbol: string; side: string; quantity: number; price: number; notional: number; status: string; position_id: string | null; created_at: string }>;
  events: Array<{ id: number; level: string; message: string; created_at: string }>;
};

export type MarketBar = {
  symbol: string;
  timeframe: string;
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  source: string;
};

export type TradingStrategy = {
  id: string;
  name: string;
  kind: string;
  params: Record<string, number>;
  status: string;
  score: number;
  metrics: Record<string, number | string | Record<string, number>>;
  notes: string;
  knowledge_source_id: string | null;
  created_at: string;
  updated_at: string;
};

export type TradingRun = {
  id: string;
  kind: "discover" | "backtest" | "paper_bot" | string;
  status: string;
  progress: number;
  symbol: string;
  timeframe: string;
  strategy_id: string | null;
  config: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string | null;
  knowledge_source_id: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  updated_at: string;
};

export type TradingBotSettings = {
  id: number;
  enabled: boolean;
  strategy_id: string | null;
  symbol: string;
  timeframe: string;
  position_fraction: number;
  last_bar_ts: string | null;
  updated_at: string;
};

export type TradingDashboard = {
  paper: PaperTradingState;
  bot: TradingBotSettings;
  symbols: Array<{ symbol: string; timeframe: string; bars: number; first_ts: string; last_ts: string; last_close: number }>;
  bars: MarketBar[];
  strategies: TradingStrategy[];
  runs: TradingRun[];
  learnings: KnowledgeMatch[];
  strategy_kinds: string[];
};

// --- Trading Lab (simulation / paper research environment) ---------------------------

export type LabInstrument = {
  instrument_id: string;
  family: string;
  venue: string;
  symbol: string;
  description?: string;
  base_currency: string;
  quote_currency: string;
  settlement_currency?: string | null;
  multiplier: string | number;
  tick_size: string | number;
  lot_size: string | number;
  min_notional?: string | number;
  price_can_be_negative?: boolean;
  shorting_allowed?: boolean;
  calendar: string;
  timezone?: string;
  listed_from?: string | null;
  delisted_at?: string | null;
  initial_margin_rate?: string | number;
  maintenance_margin_rate?: string | number;
  funding_interval_hours?: number | null;
  metadata?: Record<string, unknown>;
};

export type LabDataset = {
  dataset_id: string;
  name: string;
  instrument_id: string;
  timeframe: string;
  data_level: string;
  provider: string;
  provider_kind: string;
  licence: string;
  is_synthetic: boolean;
  revision: number;
  row_count: number;
  first_event_time: string | null;
  last_event_time: string | null;
  calendar: string;
  availability_delay_seconds: number;
  content_checksum: string;
  frozen: boolean;
  quality?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
  created_at?: string;
};

export type LabStrategy = {
  strategy_id: string;
  name: string;
  family: string;
  status: string;
  current_version: number;
  hypothesis: Record<string, unknown>;
  owner?: string;
  created_by?: string;
  scope_note?: string;
  updated_at?: string;
};

export type LabRun = {
  run_id: string;
  mode: string;
  label: string;
  status: string;
  progress: number;
  split: string;
  strategy_id?: string | null;
  strategy_version?: number | null;
  strategy_hash?: string;
  dataset_ids: string[];
  dataset_hash?: string;
  simulation_time?: string | null;
  first_event_time?: string | null;
  last_event_time?: string | null;
  events_processed?: number;
  config: Record<string, unknown>;
  cost_model: Record<string, unknown>;
  risk_limits: Record<string, unknown>;
  seeds: Record<string, unknown>;
  result: Record<string, unknown>;
  base_commit?: string;
  engine_version?: string;
  branch_of_run_id?: string | null;
  branch_from_event_time?: string | null;
  error?: string | null;
  created_at?: string;
};

export type LabExperiment = {
  experiment_id: string;
  title: string;
  strategy_family: string;
  status: string;
  progress: number;
  split: string;
  search_method: string;
  search_budget: number;
  trials_completed: number;
  trials_failed: number;
  seed: number;
  spec: Record<string, unknown>;
  preregistration: Record<string, unknown>;
  result: Record<string, unknown>;
  job_id?: string | null;
  created_at?: string;
};

export type LabEvaluation = {
  report_id: string;
  strategy_id: string;
  strategy_version: number;
  verdict: "pass" | "fail" | "insufficient_evidence";
  evidence_class: string;
  evaluated_by: string;
  protocol: string;
  deflated_sharpe?: number | null;
  search_trials_considered?: number;
  report?: Record<string, unknown>;
  created_at?: string;
};

export type LabOverview = {
  mode: string;
  counts: Record<string, number>;
  lifecycle: { counts: Record<string, number>; total: number; states: string[] };
  recent_runs: LabRun[];
  recent_experiments: LabExperiment[];
  recent_evaluations: LabEvaluation[];
  paper_accounts: Array<Record<string, unknown>>;
  queue: Record<string, unknown>;
  coverage: { first_event_time: string | null; last_event_time: string | null; instruments: number; rows: number };
  known_data_gaps: Array<{ area: string; missing: string; consequence: string }>;
  simulator_limitations: string[];
  providers: Array<Record<string, unknown>>;
  warnings: string[];
  learning?: Record<string, unknown>;
};

export type LabJobsSnapshot = {
  queue: Record<string, unknown>;
  jobs: Array<Record<string, unknown>>;
};

export type MediaCapabilityItem = {
  id: string;
  label: string;
  status: string;
  detail?: string;
  remediation?: string;
  evidence?: Record<string, unknown>;
};

export type MediaChannel = {
  id: string;
  name: string;
  description?: string;
  niche?: string;
  platforms: string[];
  autonomy_level: string;
  language?: string;
  target_audience?: string;
  posting_frequency?: string;
  voice_persona?: Record<string, unknown>;
  visual_persona?: Record<string, unknown>;
  preferred_topics?: string[];
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type MediaProject = {
  id: string;
  channel_id: string;
  title: string;
  topic: string;
  stage: string;
  platforms: string[];
  autonomy_level: string;
  progress: number;
  artifacts?: Record<string, unknown>;
  content_dna?: Record<string, unknown>;
  error?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type MediaOverview = {
  engine_status: string;
  channels: number;
  trend_signals: number;
  opportunities: number;
  projects_producing: number;
  ready_to_publish: number;
  published_today: number;
  failures: number;
  platforms: Record<string, MediaCapabilityItem>;
  campaigns: MediaChannel[];
  active_generation: MediaProject[];
  publish_queue: Array<Record<string, unknown>>;
  trending_opportunities: Array<Record<string, unknown>>;
  experiments: Array<Record<string, unknown>>;
  learning_findings: Array<Record<string, unknown>>;
  blockers: MediaCapabilityItem[];
  budget: Record<string, unknown>;
  recent_failures: MediaProject[];
  capabilities?: Record<string, unknown>;
};

/** Mission lifecycle — mirrors backend ``MISSION_TRANSITIONS`` keys. */
export type Gen2MissionStatus =
  | "draft"
  | "compiled"
  | "awaiting_approval"
  | "ready"
  | "queued"
  | "dispatched"
  | "running"
  | "paused"
  | "blocked"
  | "completed"
  | "failed"
  | "cancelled";

export type Gen2GateStatus = "pending" | "approved" | "rejected";

export type Gen2EvalStatus = "completed" | "unmeasured";

export type Gen2CommitteeStatus = "completed" | "completed_heuristic_fallback";

/** Coding background job lifecycle — mirrors backend ``JobStatus``. */
export type CodingJobStatus =
  | "queued"
  | "running"
  | "pause_requested"
  | "paused"
  | "cancel_requested"
  | "cancelled"
  | "interrupted"
  | "verified"
  | "failed"
  | "completed"
  | "tests_failed"
  | "no_change"
  | "implementation_missing"
  | "model_output_invalid"
  | "model_unavailable";

export type CodingTestSuiteApi =
  | "auto"
  | "unittest"
  | "pytest"
  | "npm_test"
  | "go_test"
  | "cargo_test"
  | "ctest";

export type Gen2CapabilityStatus = {
  implemented: boolean;
  available_on_host: boolean;
  operationally_tested: boolean;
  quality_evaluated: boolean;
  note: string;
  simulated?: boolean;
  degraded?: boolean;
  blocked?: boolean;
  unverified_on_host?: boolean;
  os_isolation_enforced?: boolean;
  available_tiers?: unknown;
  job_objects?: unknown;
  job_object_enforcement_implemented?: unknown;
  verification_status?: string;
  docker?: unknown;
  wsl?: unknown;
};

export type Gen2MissionGate = {
  id: string;
  required?: boolean;
  status: Gen2GateStatus | string;
  before_wave?: number;
  label?: string;
  note?: string;
  kind?: string;
};

export type Gen2MissionVerification = {
  required?: boolean;
  status?: string;
  source?: string;
  evidence_refs?: string[];
  criteria_checklist?: Array<Record<string, unknown>>;
  criteria_results?: Array<Record<string, unknown>>;
  acceptance?: Record<string, unknown>;
  acceptance_checks_eval?: Record<string, unknown>;
};

export type Gen2AcceptanceCheckType =
  | "status_equals"
  | "artifact_exists"
  | "verification_passed"
  | "step_completed";

export type Gen2AcceptanceCheck = {
  id?: string;
  type: Gen2AcceptanceCheckType | string;
  expected?: string;
  name?: string;
  step_id?: string;
  require_all?: boolean;
  source?: string;
  domain?: string;
  [key: string]: unknown;
};

export type Gen2ResourcePlan = {
  source?: string;
  domain?: string;
  host_measured?: boolean;
  model_slots?: Record<string, number>;
  estimated_ram_mb?: number;
  tool_contention_groups?: Array<Record<string, unknown>>;
  step_count?: number;
  note?: string;
  [key: string]: unknown;
};

export type Gen2Mission = {
  id: string;
  title?: string;
  goal?: string;
  status: Gen2MissionStatus;
  task_id: string | null;
  execution_id: string | null;
  executions?: Array<Record<string, unknown>>;
  acceptance_criteria?: Array<string | Gen2AcceptanceCheck>;
  budgets?: Record<string, unknown>;
  gates?: Gen2MissionGate[];
  verification?: Gen2MissionVerification;
  ir?: {
    execution_waves?: Array<{
      wave?: number;
      steps?: Array<{ id?: string; title?: string; agent?: string; depends_on?: string[] }>;
    }>;
    acceptance_checks?: Gen2AcceptanceCheck[];
    resource_plan?: Gen2ResourcePlan;
    replan_count?: number;
    replan_history?: Array<Record<string, unknown>>;
    [key: string]: unknown;
  };
  error: string | null;
  updated_at?: string;
  created_at?: string;
  blocked_gates?: Gen2MissionGate[];
  idempotent?: boolean;
  replan?: Record<string, unknown>;
  replan_count?: number;
  max_replans?: number;
  links?: Gen2MissionIdentityLinks;
  revision?: number;
  confirmed_outcome?: {
    status?: string;
    confirmed?: boolean;
    source?: string;
    mission_id?: string | null;
    task_id?: string | null;
    run_id?: string | null;
  };
};

export type Gen2MissionIdentityLinks = {
  mission_id?: string | null;
  task_id?: string | null;
  run_id?: string | null;
  execution_id?: string | null;
  step_ids?: string[];
  steps?: Array<Record<string, unknown>>;
  artifacts?: Array<Record<string, unknown>>;
  gates?: Array<Record<string, unknown>>;
  domain?: string;
  status?: string;
};

export type Gen2MissionPortfolio = {
  missions: Array<{
    id: string;
    title?: string;
    goal?: string;
    status: string;
    domain?: string;
    task_id?: string | null;
    execution_id?: string | null;
    budgets?: Record<string, unknown>;
    gates_summary?: Record<string, unknown>;
    blocked_or_waiting?: boolean;
    updated_at?: string;
    created_at?: string;
    links?: Gen2MissionIdentityLinks;
  }>;
  count: number;
  filter?: { status?: string | null; limit?: number };
  by_status?: Record<string, number>;
  by_domain?: Record<string, number>;
};

export type Gen2MissionRevision = {
  id: string;
  mission_id: string;
  version: number;
  cause?: string;
  snapshot?: Record<string, unknown>;
  created_at?: string;
  note?: string;
};

export type Gen2MissionBudgetLedger = {
  mission_id: string;
  budgets: Record<string, unknown>;
  ledger: {
    reserved: Record<string, number>;
    consumed: Record<string, number>;
    reservations: Record<string, Record<string, unknown>>;
    entries: Array<Record<string, unknown>>;
    idempotency: Record<string, Record<string, unknown>>;
  };
  shared?: boolean;
  note?: string;
  reservation_id?: string;
};

export type Gen2EvalRun = {
  id: string;
  suite: string;
  status: Gen2EvalStatus | string;
  mode?: string;
  model_id: string | null;
  created_at?: string;
  summary?: {
    total?: number;
    passed?: number;
    failed?: number;
    pass_rate?: number;
    model_invoked?: boolean;
    not_model_quality?: boolean;
    not_coding_or_research_benchmark?: boolean;
    quality_layer?: string;
    reason?: string;
    mode?: string;
    model_id?: string;
    note?: string;
  };
  scores?: Array<Record<string, unknown>>;
};

/** Committee consensus payload — mode is here (not top-level on the session). */
export type Gen2CommitteeConsensus = {
  mode?: string;
  basis?: string;
  live_requested?: boolean;
  model_id?: string | null;
  agreements?: string[];
  disagreements?: string[];
  minority_positions?: string[];
  unsupported_claims?: string[];
  supported_count?: number;
  position_count?: number;
  support_ratio?: number;
  confidence?: number;
  missing_evidence?: string[];
  evidence_checks?: Array<Record<string, unknown>>;
  note?: string;
  role_selection?: Record<string, unknown>;
  agent_rationale_summaries?: Array<Record<string, unknown>>;
  [key: string]: unknown;
};

export type Gen2CommitteeSession = {
  id: string;
  topic: string;
  domain: string;
  status: Gen2CommitteeStatus | string;
  positions: Array<Record<string, unknown>>;
  consensus: Gen2CommitteeConsensus;
  run_id: string | null;
  created_at?: string;
};

export type Gen2Dashboard = {
  missions: Gen2Mission[];
  eval_runs: Gen2EvalRun[];
  matrix_rows: number;
  skills: Array<Record<string, unknown>>;
  committees: Gen2CommitteeSession[];
  market_events: Array<Record<string, unknown>>;
  nodes: Array<Record<string, unknown>>;
  envelopes: number;
  graph_edges: number;
  phase: Record<string, boolean>;
  capability_status?: Record<string, Gen2CapabilityStatus>;
  live_model_smoke_seen?: boolean;
  live_model_quality_seen?: boolean;
  readiness_note?: string;
  workflows?: Gen2Workflow[];
};

/** Workflow lifecycle — mirrors backend ``WORKFLOW_STATUSES``. */
export type Gen2WorkflowStatus = "draft" | "tested" | "promoted" | "archived";

export type Gen2WorkflowStepType =
  | "action"
  | "skill"
  | "handler"
  | "tool"
  | "check"
  | "approve"
  | "choose"
  | "provide_secret"
  | string;

export type Gen2WorkflowStep = {
  id: string;
  type?: Gen2WorkflowStepType;
  action?: string;
  inputs?: Record<string, unknown>;
  depends_on?: string[];
  description?: string;
  prompt?: string;
  choices?: string[];
  success_criteria?: string[];
  tools?: string[];
  [key: string]: unknown;
};

export type Gen2WorkflowDefinition = {
  id?: string;
  name: string;
  description?: string;
  version?: number;
  status?: Gen2WorkflowStatus | string;
  steps: Gen2WorkflowStep[];
  inputs_schema?: Record<string, unknown>;
  success_checks?: string[];
  permissions?: Record<string, string>;
  offline_safe?: boolean;
  metrics?: Record<string, unknown>;
  draft_source?: string;
  human_approved?: boolean;
  pattern_tags?: string[];
  test_evidence?: Record<string, unknown>;
  skill_candidate_id?: string | null;
  awaiting_human?: { step_id?: string; prompt?: string; type?: string; choices?: string[] } | string | null;
  active_run_id?: string | null;
  [key: string]: unknown;
};

export type Gen2Workflow = {
  id: string;
  name: string;
  status: Gen2WorkflowStatus | string;
  definition: Gen2WorkflowDefinition;
  metrics?: Record<string, unknown>;
  version?: number;
  created_at?: string;
  updated_at?: string;
};

export type Gen2WorkflowTemplate = {
  id: string;
  name: string;
  description?: string;
  pattern_tags?: string[];
  offline_safe?: boolean;
  definition?: Gen2WorkflowDefinition;
};

export type Gen2WorkflowValidateResult = {
  workflow_id: string;
  valid: boolean;
  errors: string[];
};

export type Gen2WorkflowRunResult = {
  workflow_id?: string;
  run_id?: string;
  status?: string;
  passed?: boolean;
  mode?: string;
  steps?: Array<Record<string, unknown>>;
  awaiting_human?: {
    step_id?: string;
    prompt?: string;
    type?: string;
    choices?: string[];
  } | null;
  note?: string;
  [key: string]: unknown;
};

export type Gen2WorkflowRevision = {
  id: string;
  workflow_id: string;
  version: number;
  definition?: Gen2WorkflowDefinition;
  created_at?: string;
  note?: string;
};

export type Gen2WorkflowMetrics = {
  workflow_id: string;
  metrics: Record<string, unknown>;
  runs?: Array<Record<string, unknown>>;
};

export type Gen2WorkflowExportPackage = {
  format?: string;
  format_version?: number;
  definition?: Gen2WorkflowDefinition;
  metadata?: Record<string, unknown>;
  encoding?: string;
  data?: string;
  [key: string]: unknown;
};

const pluginApi = createPluginApi({ request, ApiError: HadesApiError });

export const hadesApi = {
  health: (signal?: AbortSignal) => request<SystemHealth>("/health", { signal }),
  models: () => request<ModelsResponse>("/models"),
  modelProfile: (id: string) => request<ModelProfile>(`/models/${encodeURIComponent(id)}/profile`),
  saveModelProfile: (id: string, values: Omit<ModelProfile, "model_id" | "is_active"> & { make_active: boolean }) =>
    request<ModelProfile>(`/models/${encodeURIComponent(id)}/profile`, { method: "PUT", body: JSON.stringify(values) }),
  testConnection: (values: Partial<AppSettings> = {}) =>
    request<{ connected: boolean; models: number; latency_ms: number }>("/connection/test", { method: "POST", body: JSON.stringify(values) }),

  conversations: () => request<Conversation[]>("/conversations"),
  createConversation: (title = "Nieuw gesprek", model_id?: string, system_prompt_override?: string) => request<Conversation>("/conversations", { method: "POST", body: JSON.stringify({ title, model_id, system_prompt_override }) }),
  updateConversation: (id: string, values: { title?: string; model_id?: string; system_prompt_override?: string | null; update_system_prompt?: boolean }) => request<Conversation>(`/conversations/${id}`, { method: "PATCH", body: JSON.stringify(values) }),
  deleteConversation: (id: string) => request<void>(`/conversations/${id}`, { method: "DELETE" }),
  conversationRuns: (id: string, options?: { active_only?: boolean; limit?: number }) => {
    const q = new URLSearchParams();
    if (options?.active_only) q.set("active_only", "true");
    if (options?.limit) q.set("limit", String(options.limit));
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return request<{ conversation_id: string; runs: ConversationRunLink[]; count: number }>(`/conversations/${id}/runs${suffix}`);
  },
  bindConversationRun: (
    id: string,
    values: { run_id: string; run_type: ConversationRunType; status?: string; title?: string; metadata?: Record<string, unknown> },
  ) =>
    request<{ conversation_id: string; run: ConversationRunLink }>(`/conversations/${id}/runs`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  patchConversationRun: (
    id: string,
    runId: string,
    values: { status: string; metadata?: Record<string, unknown> },
  ) =>
    request<{ conversation_id: string; run: ConversationRunLink }>(`/conversations/${id}/runs/${encodeURIComponent(runId)}`, {
      method: "PATCH",
      body: JSON.stringify(values),
    }),
  previewConversationPins: (id: string, values: { paths: string[]; force?: boolean }) =>
    request<{
      conversation_id: string;
      accepted: Array<Record<string, unknown>>;
      skipped: Array<Record<string, unknown>>;
      summary: { indexed: number; stale: number; skipped: number; total: number; label: string };
    }>(`/conversations/${encodeURIComponent(id)}/pins/preview`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  getConversationPins: (id: string) =>
    request<{
      conversation_id: string;
      accepted: Array<Record<string, unknown>>;
      skipped: Array<Record<string, unknown>>;
      summary: { indexed: number; stale: number; skipped: number; total: number; label: string };
    }>(`/conversations/${encodeURIComponent(id)}/pins`),
  putConversationPins: (id: string, values: { paths: string[]; force?: boolean }) =>
    request<{
      conversation_id: string;
      accepted: Array<Record<string, unknown>>;
      skipped: Array<Record<string, unknown>>;
      summary: { indexed: number; stale: number; skipped: number; total: number; label: string };
      working_state?: Record<string, unknown>;
    }>(`/conversations/${encodeURIComponent(id)}/pins`, {
      method: "PUT",
      body: JSON.stringify(values),
    }),
  pickConversationPinFolder: (id: string, values?: { approved_subprocess?: boolean }) =>
    request<{ path: string | null; cancelled: boolean }>(
      `/conversations/${encodeURIComponent(id)}/pins/pick-folder`,
      { method: "POST", body: JSON.stringify(values || {}) },
    ),
  exportConversation: (id: string) =>
    request<{ conversation_id: string; format: string; markdown: string; bytes: number }>(
      `/conversations/${encodeURIComponent(id)}/export?format=markdown`,
    ),
  messages: (id: string, options?: { branch_id?: string; active_only?: boolean }) => {
    const q = new URLSearchParams();
    if (options?.branch_id) q.set("branch_id", options.branch_id);
    if (options?.active_only === false) q.set("active_only", "false");
    const suffix = q.toString() ? `?${q.toString()}` : "";
    return request<ChatMessage[]>(`/conversations/${id}/messages${suffix}`);
  },
  sendMessage: (id: string, content: string, model_id?: string, extra?: {
    client_request_id?: string;
    attachment_ids?: string[];
    branch_id?: string;
    revise_message_id?: string;
    regenerate_of?: string;
    metadata?: Record<string, unknown>;
    reasoning_profile?: string;
  }) =>
    request<{
      user_message: ChatMessage;
      assistant_message: ChatMessage;
      model_id: string;
      reasoning_profile: string;
      selected_mode?: string;
      effective_policy?: string;
      decision_reason?: string;
      policy_version?: string;
      retrieval: {
        memories: number;
        knowledge_chunks: number;
        mentions?: Array<{ kind: string; ref?: string; raw?: string }>;
        sources?: Array<{ kind: string; label: string }>;
        request_kind?: string;
        web_refresh?: { attempted: boolean; indexed: number };
        context_budget?: Record<string, unknown>;
        working_state?: Record<string, unknown>;
      };
      tools: PluginToolLogEntry[];
      tool_cards?: Array<Record<string, unknown>>;
      run_id?: string;
      request_spec?: Record<string, unknown>;
      route?: Record<string, unknown>;
      executed_route?: Record<string, unknown>;
      execution?: Record<string, unknown>;
      execution_status?: string;
      linked_task_id?: string | null;
      acceptance_criteria?: string[];
      acceptance_checklist?: Array<{ criterion: string; met: boolean; note?: string }>;
      reasoning_meta?: Record<string, unknown>;
      difficulty_router?: Record<string, unknown>;
      budget?: Record<string, unknown>;
      working_state?: Record<string, unknown>;
      attachments?: Array<Record<string, unknown>>;
      command?: Record<string, unknown>;
      execution_truth?: Record<string, unknown>;
      grounding?: Record<string, unknown>;
      verification_display?: string;
      answer_presentation?: Record<string, unknown>;
      result_artifact_id?: string | null;
      persistence?: Array<Record<string, unknown>>;
      usage?: {
        input_tokens?: number | null;
        output_tokens?: number | null;
        total_tokens?: number | null;
        cached_tokens?: number | null;
        reasoning_tokens?: number | null;
        cost?: number | null;
        model_id?: string | null;
        provider?: string | null;
      } | null;
    }>(`/conversations/${id}/messages`, {
      method: "POST",
      body: JSON.stringify({ content, model_id, ...(extra || {}) }),
    }),
  uploadChatAttachment: (conversationId: string, file: File) => {
    const body = new FormData();
    body.append("file", file);
    return request<{ artifact: HadesArtifact; filename: string; size_bytes: number; extract_status: string }>(
      `/conversations/${conversationId}/attachments`,
      { method: "POST", body },
    );
  },
  branchConversation: (id: string, fork_message_id: string, title = "Vertakking") =>
    request<ConversationBranch>(`/conversations/${id}/branch`, { method: "POST", body: JSON.stringify({ fork_message_id, title }) }),
  listConversationBranches: (id: string) => request<ConversationBranch[]>(`/conversations/${id}/branches`),
  activateConversationBranch: (conversationId: string, branchId: string) =>
    request<ConversationBranch>(`/conversations/${conversationId}/branches/${encodeURIComponent(branchId)}/activate`, { method: "POST" }),
  saveDraft: (id: string, content: string, attachment_ids: string[] = []) =>
    request<Record<string, unknown>>(`/conversations/${id}/draft`, { method: "PUT", body: JSON.stringify({ content, attachment_ids }) }),
  getDraft: (id: string) => request<{ conversation_id: string; content: string; attachment_ids: string[] }>(`/conversations/${id}/draft`),

  artifacts: (params: { conversation_id?: string; task_id?: string; kind?: string } = {}) => {
    const q = new URLSearchParams();
    if (params.conversation_id) q.set("conversation_id", params.conversation_id);
    if (params.task_id) q.set("task_id", params.task_id);
    if (params.kind) q.set("kind", params.kind);
    const suffix = q.toString() ? `?${q}` : "";
    return request<HadesArtifact[]>(`/artifacts${suffix}`);
  },
  generateArtifact: (values: { name: string; content: string; mime_type?: string; kind?: string; conversation_id?: string; task_id?: string }) =>
    request<HadesArtifact>("/artifacts/generate", { method: "POST", body: JSON.stringify(values) }),
  artifactPreview: (id: string) => request<{ artifact: HadesArtifact; previewable: boolean; text: string | null; reason?: string | null; truncated?: boolean }>(`/artifacts/${id}/preview`),
  artifactDownloadUrl: (id: string) => `${API_BASE}/artifacts/${encodeURIComponent(id)}/download`,
  artifactResultSummary: (id: string) =>
    request<Record<string, unknown>>(`/artifacts/${encodeURIComponent(id)}/result-summary`),
  deleteArtifact: (id: string) => request<void>(`/artifacts/${id}`, { method: "DELETE" }),

  projects: (status = "active") =>
    request<{ projects: Array<Record<string, unknown>>; count: number }>(`/projects?status=${encodeURIComponent(status)}`),
  createProject: (values: { name: string; description?: string }) =>
    request<{ project: Record<string, unknown> }>("/projects", { method: "POST", body: JSON.stringify(values) }),
  projectContext: (id: string, includeProposals = false) =>
    request<Record<string, unknown>>(
      `/projects/${encodeURIComponent(id)}/context?include_proposals=${includeProposals ? "true" : "false"}`,
    ),
  addProjectItem: (
    projectId: string,
    values: {
      kind: string;
      title: string;
      body?: string;
      provenance?: string;
      status?: string;
      replace_overlapping?: boolean;
    },
  ) =>
    request<{ item: Record<string, unknown> }>(`/projects/${encodeURIComponent(projectId)}/items`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  researchConflictsFixture: () => request<Record<string, unknown>>("/research/conflicts/fixture"),
  presentResearchConflicts: (claims: Array<Record<string, unknown>>) =>
    request<Record<string, unknown>>("/research/conflicts/present", {
      method: "POST",
      body: JSON.stringify({ claims }),
    }),
  proactiveTriggers: () =>
    request<{ triggers: Array<Record<string, unknown>>; count: number }>("/proactive/triggers"),
  createProactiveTrigger: (values: Record<string, unknown>) =>
    request<{ trigger: Record<string, unknown> }>("/proactive/triggers", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  disableProactiveTrigger: (id: string) =>
    request<{ trigger: Record<string, unknown> }>(`/proactive/triggers/${encodeURIComponent(id)}/disable`, {
      method: "POST",
    }),
  proactiveSuggestions: (status = "open") =>
    request<{ suggestions: Array<Record<string, unknown>>; count: number }>(
      `/proactive/suggestions?status=${encodeURIComponent(status)}`,
    ),
  effectRestartClass: (effectId: string) =>
    request<Record<string, unknown>>(`/effects/${encodeURIComponent(effectId)}/restart-class`),
  invalidateWorkByInput: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/work/invalidate-by-input", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  classifyTaskResources: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/resources/classify-task", {
      method: "POST",
      body: JSON.stringify(values),
    }),

  approvals: () => request<ApprovalRequest[]>("/approvals"),
  decideApproval: (id: string, approve: boolean, note = "") =>
    request<ApprovalRequest>(`/approvals/${id}/decide`, { method: "POST", body: JSON.stringify({ approve, note }) }),
  inbox: (status?: string) => request<InboxItem[]>(`/inbox${status ? `?status=${encodeURIComponent(status)}` : ""}`),
  readInbox: (id: string) => request<InboxItem>(`/inbox/${id}/read`, { method: "POST" }),
  globalSearch: (query: string, project_id?: string) =>
    request<GlobalSearchResult>("/search", { method: "POST", body: JSON.stringify({ query, project_id }) }),
  memoryProposals: () => request<Array<Record<string, unknown>>>("/memory/proposals"),
  scanMemoryProposals: () => request<{ created: number; proposals: Array<Record<string, unknown>>; auto_written: boolean }>("/memory/proposals/scan", { method: "POST", body: "{}" }),
  decideMemoryProposal: (id: string, action: "accept" | "edit" | "reject" | "merge", edited: Record<string, unknown> = {}) =>
    request<Record<string, unknown>>(`/memory/proposals/${id}/decide`, { method: "POST", body: JSON.stringify({ action, edited }) }),
  forgetMemoryScope: (values: { conversation_id?: string; memory_id?: string; include_derived?: boolean; preview_only?: boolean }) =>
    request<Record<string, unknown>>("/memory/forget", { method: "POST", body: JSON.stringify(values) }),
  scheduleTask: (taskId: string, values: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/tasks/${taskId}/schedule`, { method: "POST", body: JSON.stringify(values) }),
  buildPlan: (values: { edits: Array<Record<string, unknown>>; goal?: string }) =>
    request<{
      goal?: string | null;
      status: string;
      file_count: number;
      edit_count: number;
      files: Array<Record<string, unknown>>;
      unique_paths: string[];
      risks: string[];
      approval_required: boolean;
      note?: string;
    }>("/build/plan", { method: "POST", body: JSON.stringify(values) }),
  buildRun: (values: {
    source_repo: string;
    edits?: Array<Record<string, unknown>>;
    repair_waves?: Array<Array<Record<string, unknown>>>;
    test_suite?: CodingTestSuiteApi;
    test_args?: string[];
    max_attempts?: number;
    goal?: string;
    auto_repair?: boolean;
  }) => request<Record<string, unknown>>("/build/run", { method: "POST", body: JSON.stringify(values) }),
  buildFromGoal: (values: {
    source_repo: string;
    goal: string;
    test_suite?: CodingTestSuiteApi;
    test_args?: string[];
    max_attempts?: number;
    model_id?: string | null;
    auto_repair?: boolean;
    strategy?: "fast" | "investigate" | "auto";
    autonomy_profile?: "analyze_only" | "managed_workspace_modify" | "reviewable_result";
    task_type?: "bugfix" | "feature" | "regression" | "review" | null;
    use_omniroute?: boolean;
    edits?: Array<Record<string, unknown>>;
    repair_waves?: Array<Array<Record<string, unknown>>>;
  }) => request<Record<string, unknown>>("/build/goal", { method: "POST", body: JSON.stringify(values) }),
  buildFromGoalAsync: (values: {
    source_repo: string;
    goal: string;
    test_suite?: CodingTestSuiteApi;
    test_args?: string[];
    max_attempts?: number;
    model_id?: string | null;
    auto_repair?: boolean;
    strategy?: "fast" | "investigate" | "auto";
    selector_mode?: "deterministic" | "model";
    autonomy_profile?: "analyze_only" | "managed_workspace_modify" | "reviewable_result";
    task_type?: "bugfix" | "feature" | "regression" | "review" | null;
    use_omniroute?: boolean;
    edits?: Array<Record<string, unknown>>;
    repair_waves?: Array<Array<Record<string, unknown>>>;
  }) =>
    request<{ job_id: string; status: CodingJobStatus; created_at?: number; poll: string; model_id?: string | null }>(
      "/build/goal/async",
      {
        method: "POST",
        body: JSON.stringify(values),
      },
    ),
  startConversationCodingJob: (
    conversationId: string,
    values: {
      source_repo: string;
      goal: string;
      test_suite?: CodingTestSuiteApi;
      test_args?: string[];
      max_attempts?: number;
      model_id?: string | null;
      auto_repair?: boolean;
      strategy?: "fast" | "investigate" | "auto";
      selector_mode?: "deterministic" | "model";
      autonomy_profile?: "analyze_only" | "managed_workspace_modify" | "reviewable_result";
      task_type?: "bugfix" | "feature" | "regression" | "review" | null;
      use_omniroute?: boolean;
      approved_subprocess?: boolean;
    },
  ) =>
    request<{
      job_id: string;
      status: CodingJobStatus;
      created_at?: number;
      poll: string;
      conversation_id?: string;
      conversation_run?: ConversationRunLink;
    }>(`/conversations/${encodeURIComponent(conversationId)}/coding-jobs`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  buildJobsList: (limit = 40, includeTerminal = true) =>
    request<{ jobs: Array<{ id?: string; status?: CodingJobStatus; [key: string]: unknown }> }>(
      `/build/jobs?limit=${limit}&include_terminal=${includeTerminal ? "true" : "false"}`,
    ),
  buildOmnirouteStatus: () =>
    request<{
      installed: boolean;
      enabled: boolean;
      ready: boolean;
      usable: boolean;
      toggle_enabled: boolean;
      enabled_by_default?: boolean;
      status_code: string;
      status_label: string;
      reason: string;
      explanation?: string;
      [key: string]: unknown;
    }>("/build/omniroute/status"),
  buildJobGet: (jobId: string) =>
    request<{ id?: string; status: CodingJobStatus; [key: string]: unknown }>(`/build/jobs/${encodeURIComponent(jobId)}`),
  buildJobEvents: (jobId: string, limit = 100, afterSeq?: number | null) =>
    request<{ job_id: string; events: Array<Record<string, unknown>>; after_seq?: number | null; next_cursor?: number | null }>(
      `/build/jobs/${encodeURIComponent(jobId)}/events?limit=${limit}${afterSeq != null ? `&after_seq=${afterSeq}` : ""}`,
    ),
  buildJobCancel: (jobId: string) =>
    request<Record<string, unknown>>(`/build/jobs/${encodeURIComponent(jobId)}/cancel`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  buildJobPause: (jobId: string) =>
    request<Record<string, unknown>>(`/build/jobs/${encodeURIComponent(jobId)}/pause`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  buildJobResume: (jobId: string) =>
    request<Record<string, unknown>>(`/build/jobs/${encodeURIComponent(jobId)}/resume`, {
      method: "POST",
      body: JSON.stringify({}),
    }),
  buildJobRedirect: (jobId: string, note: string) =>
    request<Record<string, unknown>>(`/build/jobs/${encodeURIComponent(jobId)}/redirect`, {
      method: "POST",
      body: JSON.stringify({ note }),
    }),
  buildJobsControlContract: () => request<Record<string, unknown>>("/build/jobs/control-contract"),
  buildJobsRecover: (auto_resume = false) =>
    request<Record<string, unknown>>("/build/jobs/recover", {
      method: "POST",
      body: JSON.stringify({ auto_resume }),
    }),
  buildGet: (runId: string) => request<Record<string, unknown>>(`/build/${encodeURIComponent(runId)}`),
  buildApply: (runId: string, approved: boolean) =>
    request<Record<string, unknown>>(`/build/${runId}/apply`, { method: "POST", body: JSON.stringify({ approved }) }),
  buildConflicts: (runId: string) => request<Record<string, unknown>>(`/build/${runId}/conflicts`),
  buildPreview: (runId: string) =>
    request<{
      run_id: string;
      source?: string;
      files: Array<Record<string, unknown>>;
      file_count: number;
      conflicts: Array<Record<string, unknown>>;
      can_apply: boolean;
      note?: string;
    }>(`/build/${encodeURIComponent(runId)}/preview`),
  buildRestore: (runId: string) => request<Record<string, unknown>>(`/build/${runId}/restore`, { method: "POST", body: JSON.stringify({}) }),
  terminalRun: (values: { argv: string[]; cwd?: string; timeout_seconds?: number; conversation_id?: string; task_id?: string; approved?: boolean }) =>
    request<{
      status: string;
      argv: string[];
      cwd: string;
      exit_code: number;
      duration_ms: number;
      stdout: string;
      stderr: string;
      artifact_id?: string;
    }>("/terminal/run", { method: "POST", body: JSON.stringify(values) }),
  practiceScenarios: () => request<{ scenarios: Array<{ id: string; title: string; description: string; kind: string }> }>("/practice/scenarios"),
  practiceRun: (id: string) => request<{ scenario_id: string; passed: boolean; trace: Record<string, unknown>; notes: string[] }>(`/practice/scenarios/${encodeURIComponent(id)}/run`, { method: "POST" }),
  practiceRunAll: () => request<{ passed: boolean; results: Array<Record<string, unknown>>; summary: Record<string, number> }>("/practice/run-all", { method: "POST" }),
  onboarding: () => request<{ completed: boolean; completed_at: string | null; steps: Array<{ id: string; title: string; done: boolean }>; active_model: string | null; suggested_first_prompt: string }>("/onboarding"),
  completeOnboarding: (step = "done") => request<{ completed: boolean; completed_at: string; step: string }>("/onboarding/complete", { method: "POST", body: JSON.stringify({ step }) }),
  searchSymbols: (values: { workspace_id?: string; path?: string; query?: string; limit?: number; refresh?: boolean; use_cache?: boolean }) =>
    request<{
      root: string;
      files_scanned: number;
      symbols: Array<{ name: string; kind: string; path: string; line: number }>;
      truncated: boolean;
      from_cache?: boolean;
      cache_path?: string;
      embeddings?: boolean;
      embeddings_note?: string;
      tree?: { root: string; entries: Array<{ name: string; kind: string; code_files: number }>; truncated?: boolean };
    }>("/files/symbols", { method: "POST", body: JSON.stringify(values) }),
  refreshSymbols: (values: { workspace_id?: string; path?: string; force?: boolean; max_files?: number } = {}) =>
    request<{
      root: string;
      cache_path?: string;
      files_scanned: number;
      files_reused?: number;
      files_rescanned?: number;
      symbol_count: number;
      truncated: boolean;
      refreshed?: boolean;
      force?: boolean;
      embeddings?: boolean;
      embeddings_note?: string;
      tree?: { root: string; entries: Array<{ name: string; kind: string; code_files: number }>; truncated?: boolean };
      updated_at?: string;
    }>("/files/symbols/refresh", { method: "POST", body: JSON.stringify(values) }),
  workspaceTree: (values: { workspace_id?: string; path?: string; relative?: string; query?: string; max_entries?: number }) =>
    request<{
      root: string;
      relative: string;
      entries: Array<{ name: string; path: string; kind: string; size?: number | null; dirty?: boolean }>;
      truncated: boolean;
      query?: string;
    }>("/files/tree", { method: "POST", body: JSON.stringify(values) }),
  workspacePreview: (values: { workspace_id?: string; path?: string; relative: string; max_chars?: number }) =>
    request<{
      root: string;
      path: string;
      content: string;
      truncated: boolean;
      chars: number;
      total_chars: number;
    }>("/files/preview", { method: "POST", body: JSON.stringify(values) }),
  workspaceOpenExternal: (values: { workspace_id?: string; path?: string; relative: string }) =>
    request<{
      opened: boolean;
      path: string;
      root: string;
      editor?: string;
      argv?: string[];
      error?: string;
      message?: string;
    }>("/files/open-external", { method: "POST", body: JSON.stringify(values) }),
  workspaceGitStatus: (values: { workspace_id?: string; path?: string }) =>
    request<{
      is_git: boolean;
      root: string;
      branch?: string | null;
      dirty?: Array<{ code: string; path: string }>;
      dirty_count?: number;
      diff?: string;
      status_text?: string;
      ok?: boolean;
      error?: string;
      message?: string;
    }>("/workspace/git/status", { method: "POST", body: JSON.stringify(values) }),
  workspaceGitCommit: (values: { workspace_id?: string; path?: string; message: string; approved: boolean }) =>
    request<{
      is_git: boolean;
      committed: boolean;
      root?: string;
      branch?: string | null;
      message?: string;
      error?: string;
      stdout?: string;
    }>("/workspace/git/commit", { method: "POST", body: JSON.stringify(values) }),
  codeDefinition: (values: { workspace_id?: string; path?: string; symbol: string; limit?: number }) =>
    request<{ definitions: Array<{ name: string; kind: string; path: string; line: number }>; count: number; note?: string; from_cache?: boolean }>("/code/definition", { method: "POST", body: JSON.stringify(values) }),
  codeReferences: (values: { workspace_id?: string; path?: string; symbol: string; limit?: number }) =>
    request<{ references: Array<{ name: string; kind: string; path: string; line: number; snippet?: string }>; count: number; note?: string; from_cache?: boolean }>("/code/references", { method: "POST", body: JSON.stringify(values) }),
  codeOutline: (values: { workspace_id?: string; path?: string; limit?: number }) =>
    request<{
      path?: string;
      outline?: Array<Record<string, unknown>>;
      symbols?: Array<Record<string, unknown>>;
      note?: string;
      [key: string]: unknown;
    }>("/code/outline", { method: "POST", body: JSON.stringify(values) }),
  voiceToTask: (values: { transcript: string; create?: boolean; auto_start?: boolean; agent?: string }) =>
    request<{ created: boolean; started?: boolean; proposal: Record<string, unknown>; task?: HadesTask }>("/voice/to-task", { method: "POST", body: JSON.stringify(values) }),
  voiceStatus: () => request<Record<string, unknown>>("/voice/status"),
  voiceDoctor: () => request<Record<string, unknown>>("/voice/doctor", { method: "POST", body: "{}" }),
  voiceInstall: (values?: { steps?: string[]; voice_asr_model?: string; voice_tts_voice?: string }) =>
    request<Record<string, unknown>>("/voice/install", { method: "POST", body: JSON.stringify(values ?? { steps: ["deps", "whisper", "piper_voice"] }) }),
  voiceTranscribe: (values: {
    audio_base64: string;
    mime_type: string;
    language?: string;
    session_id?: string;
    turn_id?: string;
    is_final?: boolean;
  }) => request<Record<string, unknown>>("/voice/transcribe", { method: "POST", body: JSON.stringify(values) }),
  voiceSpeakable: (values: { text: string; style?: "compact" | "full"; language?: string }) =>
    request<{ speakable_text: string; segments: string[]; style: string; language: string }>("/voice/speakable", { method: "POST", body: JSON.stringify(values) }),
  voiceSpeak: async (values: {
    text: string;
    voice_id?: string;
    language?: string;
    speed?: number;
    style?: "compact" | "full";
    already_speakable?: boolean;
    message_id?: string;
    session_id?: string;
  }): Promise<Blob> => {
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/voice/speak`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(values),
      });
    } catch {
      throw new HadesApiError("De lokale FastAPI-backend is niet bereikbaar. Start eerst START_HADES.bat.");
    }
    if (!response.ok) {
      let message = `API-fout ${response.status}`;
      try {
        const body = (await response.json()) as { detail?: unknown };
        if (typeof body.detail === "string") message = body.detail;
        else if (body.detail && typeof body.detail === "object" && "message" in body.detail) {
          message = String((body.detail as { message: unknown }).message);
        }
      } catch {
        // keep status
      }
      throw new HadesApiError(message, response.status);
    }
    return response.blob();
  },
  voiceVoices: (language?: string) => {
    const suffix = language ? `?language=${encodeURIComponent(language)}` : "";
    return request<{ voices: Array<Record<string, unknown>>; provider?: string; availability?: unknown }>(`/voice/voices${suffix}`);
  },
  voiceSessionStart: (values: { conversation_id?: string | null; client_tab_id: string; keep_audio?: boolean; force?: boolean; idle_timeout_seconds?: number }) =>
    request<{ session_id: string; conversation_id?: string | null; client_tab_id: string; status: string; generation: number; mic_must_reenable?: boolean; idle_timeout_seconds?: number }>(
      "/voice/session/start",
      { method: "POST", body: JSON.stringify(values) },
    ),
  voiceSessionStop: (sessionId: string, reason = "user") =>
    request<Record<string, unknown>>(`/voice/session/${encodeURIComponent(sessionId)}/stop`, { method: "POST", body: JSON.stringify({ reason }) }),
  voiceSessionInterrupt: (sessionId: string, reason = "user") =>
    request<Record<string, unknown>>(`/voice/session/${encodeURIComponent(sessionId)}/interrupt`, { method: "POST", body: JSON.stringify({ reason }) }),
  voiceSessionSpeakResponse: (values: { session_id: string; response_id: string; text: string; force_replay?: boolean }) =>
    request<{ ok: boolean; segments: number; events: Array<Record<string, unknown>> }>("/voice/session/speak-response", { method: "POST", body: JSON.stringify(values) }),
  voiceWakeProbe: (values: { audio_base64: string; mime_type: string; language?: string }) =>
    request<Record<string, unknown>>("/voice/wake/probe", { method: "POST", body: JSON.stringify(values) }),
  voiceMetricsReference: () => request<Record<string, unknown>>("/voice/metrics/reference"),
  voiceRecordingsList: () =>
    request<{ sessions: Array<{ session_id: string; files: Array<{ name: string; bytes: number; path: string }>; file_count: number }>; root: string }>("/voice/recordings"),
  voiceRecordingsDelete: (sessionId: string) =>
    request<{ ok: boolean; deleted: string }>(`/voice/recordings/${encodeURIComponent(sessionId)}`, { method: "DELETE" }),
  speechStatus: () => request<SpeechStatus>("/speech/status"),
  speechVoices: () => request<SpeechVoicesResponse>("/speech/voices"),
  speechBegin: () => request<{ generation_id: string; provider: string; sentence_chunking: boolean }>("/speech/begin", { method: "POST", body: "{}" }),
  speechStop: (values: { generation_id?: string | null } = {}) =>
    request<{ stopped: boolean; generation_id?: string | null }>("/speech/stop", { method: "POST", body: JSON.stringify(values) }),
  speechPlayback: (values: { active: boolean; echo_guard_ms?: number }) =>
    request<SpeechEchoGuard>("/speech/playback", { method: "POST", body: JSON.stringify(values) }),
  speechEchoGuard: () => request<SpeechEchoGuard>("/speech/echo-guard"),
  speechPreview: () => request<SpeechChunkAudio>("/speech/preview", { method: "POST", body: "{}" }),
  speechSpeak: (values: { text: string; message_id?: string; conversation_id?: string }) =>
    request<SpeechSpeakPlan>("/speech/speak", { method: "POST", body: JSON.stringify(values) }),
  speechChunk: (values: { text: string; generation_id: string; chunk_index?: number }) =>
    request<SpeechChunkAudio>("/speech/chunk", { method: "POST", body: JSON.stringify(values) }),
  speechTranscribe: async (file: Blob, filename = "audio.wav") => {
    const body = new FormData();
    body.append("file", file, filename);
    return request<{ ok: boolean; text?: string; provider?: string; [key: string]: unknown }>("/speech/transcribe", { method: "POST", body });
  },
  debugDiagnose: (values: { logs: string; failing_test?: string; context_files?: Array<{ path: string; content?: string }> }) =>
    request<{
      status: string;
      failing_test?: string | null;
      failing_tests?: string[];
      findings?: Array<Record<string, unknown>>;
      assertions?: string[];
      suggestions?: string[];
      proposed_edits?: Array<Record<string, unknown>>;
      what_broke?: string[];
      verification_required?: boolean;
      note?: string;
      [key: string]: unknown;
    }>("/debug/diagnose", { method: "POST", body: JSON.stringify(values) }),
  releaseConfidence: () =>
    request<{
      overall: string;
      gates: Array<{ id: string; label: string; status: string; detail?: string }>;
      note?: string;
      smoke?: Record<string, unknown>;
      platform?: string;
      what_broke?: Array<{ kind: string; label: string }>;
      verify_stages?: Array<{ id: string; label: string }>;
    }>("/release/confidence"),
  releaseConfidenceSmoke: (run_smoke = true, module = "tests.test_world_class_capabilities") =>
    request<{
      overall: string;
      gates: Array<{ id: string; label: string; status: string; detail?: string }>;
      note?: string;
      smoke?: Record<string, unknown>;
      platform?: string;
      what_broke?: Array<{ kind: string; label: string }>;
      verify_stages?: Array<{ id: string; label: string }>;
    }>("/release/confidence/smoke", { method: "POST", body: JSON.stringify({ run_smoke, module }) }),
  toolCards: (observations: Array<Record<string, unknown>>) =>
    request<{ cards: Array<Record<string, unknown>>; count: number }>("/tools/cards", { method: "POST", body: JSON.stringify({ observations }) }),
  mcpCatalog: (mcp_only = true) =>
    request<{ items: Array<Record<string, unknown>>; count: number; plugins: number; note?: string; mcp_only?: boolean }>(
      `/mcp/catalog?mcp_only=${mcp_only ? "true" : "false"}`,
    ),
  mcpHostCatalog: () =>
    request<{ items: McpCatalogItem[]; count: number; secret_storage?: Record<string, unknown> }>("/mcp/host/catalog"),
  mcpmarketStatus: () =>
    request<{ state?: string; required_for_startup?: boolean; executes_tools?: boolean; official?: Record<string, unknown> }>(
      "/mcpmarket/status",
    ),
  mcpmarketSearch: (query: string, kind: "mcp_server" | "skill" = "mcp_server") =>
    request<McpMarketSearchResult>("/mcpmarket/search", {
      method: "POST",
      body: JSON.stringify({ query, kind, mission_id: "ui" }),
    }),
  mcpmarketPrepareConnection: (listing: Record<string, unknown>, operatorApproved: boolean) =>
    request<{ allowed?: boolean; reason?: string; draft?: Record<string, unknown>; executes?: boolean; installs?: boolean }>(
      "/mcpmarket/prepare-connection",
      { method: "POST", body: JSON.stringify({ listing, operator_approved: operatorApproved }) },
    ),
  mcpServers: () => request<{ items: McpServer[]; count: number }>("/mcp/servers"),
  mcpServer: (id: string) => request<{ server: McpServer }>(`/mcp/servers/${encodeURIComponent(id)}`),
  mcpCreateServer: (body: Record<string, unknown>) =>
    request<{ server: McpServer }>("/mcp/servers", { method: "POST", body: JSON.stringify(body) }),
  mcpUpdateServer: (id: string, body: Record<string, unknown>) =>
    request<{ server: McpServer }>(`/mcp/servers/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  mcpDeleteServer: (id: string) =>
    request<{ ok: boolean; deleted: string }>(`/mcp/servers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  mcpDuplicateServer: (id: string) =>
    request<{ server: McpServer }>(`/mcp/servers/${encodeURIComponent(id)}/duplicate`, { method: "POST" }),
  mcpEnableServer: (id: string, enabled: boolean) =>
    request<{ server: McpServer }>(`/mcp/servers/${encodeURIComponent(id)}/enable?enabled=${enabled ? "true" : "false"}`, { method: "POST" }),
  mcpConnectServer: (id: string, approval_id?: string | null) =>
    request<Record<string, unknown>>(`/mcp/servers/${encodeURIComponent(id)}/connect`, {
      method: "POST",
      body: JSON.stringify(approval_id ? { approval_id } : {}),
    }),
  mcpDisconnectServer: (id: string) =>
    request<Record<string, unknown>>(`/mcp/servers/${encodeURIComponent(id)}/disconnect`, { method: "POST" }),
  mcpReconnectServer: (id: string, approval_id?: string | null) =>
    request<Record<string, unknown>>(`/mcp/servers/${encodeURIComponent(id)}/reconnect`, {
      method: "POST",
      body: JSON.stringify(approval_id ? { approval_id } : {}),
    }),
  mcpRefreshTools: (id: string) =>
    request<{ discovery: Record<string, unknown>; tools: McpTool[] }>(`/mcp/servers/${encodeURIComponent(id)}/refresh-tools`, { method: "POST" }),
  mcpTools: (params?: { server_id?: string; q?: string; allowed?: boolean; chatbot_enabled?: boolean }) => {
    const qs = new URLSearchParams();
    if (params?.server_id) qs.set("server_id", params.server_id);
    if (params?.q) qs.set("q", params.q);
    if (params?.allowed != null) qs.set("allowed", String(params.allowed));
    if (params?.chatbot_enabled != null) qs.set("chatbot_enabled", String(params.chatbot_enabled));
    const suffix = qs.toString() ? `?${qs.toString()}` : "";
    return request<{ items: McpTool[]; count: number }>(`/mcp/tools${suffix}`);
  },
  mcpUpdateTool: (toolId: string, body: { allowed?: boolean; chatbot_enabled?: boolean; require_approval?: boolean }) =>
    request<{ tool: McpTool }>(`/mcp/tools/${encodeURIComponent(toolId)}`, { method: "PATCH", body: JSON.stringify(body) }),
  mcpInvokeTool: (toolId: string, body: { arguments: Record<string, unknown>; approved_by_user?: boolean; approval_id?: string | null; idempotency_key?: string }) =>
    request<Record<string, unknown>>(`/mcp/tools/${encodeURIComponent(toolId)}/invoke`, { method: "POST", body: JSON.stringify(body) }),
  mcpCancelExecution: (executionId: string) =>
    request<{ execution: McpExecution }>(`/mcp/executions/${encodeURIComponent(executionId)}/cancel`, { method: "POST" }),
  mcpExecutions: (server_id?: string, limit = 50) => {
    const qs = new URLSearchParams({ limit: String(limit) });
    if (server_id) qs.set("server_id", server_id);
    return request<{ items: McpExecution[]; count: number }>(`/mcp/executions?${qs.toString()}`);
  },
  mcpAuthStatus: (id: string, discover = false) =>
    request<Record<string, unknown>>(`/mcp/servers/${encodeURIComponent(id)}/auth?discover=${discover ? "true" : "false"}`),
  mcpAuthDiscover: (id: string, approval_id?: string | null) =>
    request<Record<string, unknown>>(
      `/mcp/servers/${encodeURIComponent(id)}/auth/discover${approval_id ? `?approval_id=${encodeURIComponent(approval_id)}` : ""}`,
      { method: "POST" },
    ),
  mcpOAuthCallbackUrl: () => {
    const base = API_BASE.replace(/\/$/, "");
    return `${base}/mcp/oauth/callback`;
  },
  mcpOAuthStart: (id: string, opts?: { redirect_uri?: string; ui_return_url?: string; approval_id?: string | null }) =>
    request<Record<string, unknown>>(`/mcp/servers/${encodeURIComponent(id)}/oauth/start`, {
      method: "POST",
      body: JSON.stringify({
        redirect_uri: opts?.redirect_uri ?? `${API_BASE.replace(/\/$/, "")}/mcp/oauth/callback`,
        ui_return_url: opts?.ui_return_url,
        ...(opts?.approval_id ? { approval_id: opts.approval_id } : {}),
      }),
    }),
  mcpOAuthComplete: (state: string, code: string, iss?: string | null) =>
    request<Record<string, unknown>>("/mcp/oauth/complete", {
      method: "POST",
      body: JSON.stringify({ state, code, ...(iss ? { iss } : {}) }),
    }),
  mcpExport: () => request<{ servers: Array<Record<string, unknown>>; secret_storage?: Record<string, unknown> }>("/mcp/export"),
  mcpImport: (servers: Array<Record<string, unknown>>, connect = false) =>
    request<{ ok: boolean; imported: string[] }>("/mcp/import", { method: "POST", body: JSON.stringify({ servers, connect }) }),
  runEventsStreamUrl: (runId: string, after = 0) => `${API_BASE}/runs/${encodeURIComponent(runId)}/events/stream?after=${after}`,
  /**
   * Subscribe to SSE `/api/runs/{id}/events/stream`. Resolves when the stream ends
   * (final_outcome/error/cancelled), the abort signal fires, or the connection fails.
   * Callers should fall back to `runEvents` polling when this rejects before any event.
   */
  openRunEventStream: async (
    runId: string,
    options: {
      after?: number;
      signal?: AbortSignal;
      onEvent: (event: Record<string, unknown>) => void;
    },
  ): Promise<{ eventsSeen: number }> => {
    const after = options.after ?? 0;
    const response = await fetch(hadesApi.runEventsStreamUrl(runId, after), {
      method: "GET",
      headers: { Accept: "text/event-stream" },
      signal: options.signal,
    });
    if (!response.ok) {
      throw new HadesApiError(`SSE-fout ${response.status}`, response.status);
    }
    if (!response.body) {
      throw new HadesApiError("SSE-stream zonder body.");
    }
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let eventsSeen = 0;
    const flushBlock = (block: string) => {
      const dataLines = block
        .split("\n")
        .map((line) => line.trimEnd())
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (!dataLines.length) return;
      try {
        const parsed = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
        eventsSeen += 1;
        options.onEvent(parsed);
      } catch {
        // Ignore malformed keepalive/partial frames.
      }
    };
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let splitAt = buffer.indexOf("\n\n");
      while (splitAt >= 0) {
        const block = buffer.slice(0, splitAt);
        buffer = buffer.slice(splitAt + 2);
        flushBlock(block);
        splitAt = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) flushBlock(buffer);
    return { eventsSeen };
  },

  tasks: () => request<HadesTask[]>("/tasks"),
  createTask: (values: { title: string; prompt: string; agent: string; priority: HadesTask["priority"]; model_id?: string; auto_start: boolean; schedule?: Record<string, unknown> }) => request<HadesTask>("/tasks", { method: "POST", body: JSON.stringify(values) }),
  taskEvents: (id: string) => request<TaskEvent[]>(`/tasks/${id}/events`),
  taskWork: (id: string) => request<WorkSummary>(`/tasks/${id}/work`),
  runTask: (id: string) => request<HadesTask>(`/tasks/${id}/run`, { method: "POST" }),
  cancelTask: (id: string) => request<HadesTask>(`/tasks/${id}/cancel`, { method: "POST" }),
  retryTask: (id: string) => request<HadesTask>(`/tasks/${id}/retry`, { method: "POST" }),
  resumeTaskCheckpoint: (id: string) =>
    request<{ task: HadesTask; checkpoint: WorkCheckpoint | null; work: WorkSummary; resumed: boolean }>(
      `/tasks/${id}/resume-checkpoint`,
      { method: "POST" },
    ),
  controlTask: (id: string, body: { action: "pause" | "resume" | "redirect" | "retry_step" | "status"; plan_version?: number; instruction?: string; step_id?: string }) =>
    request<Record<string, unknown>>(`/tasks/${id}/control`, { method: "POST", body: JSON.stringify(body) }),
  runEvents: (runId: string, after = 0) => request<{ run_id: string; events: Array<Record<string, unknown>>; latest_sequence: number }>(`/runs/${runId}/events?after=${after}`),
  chatUsageTelemetry: (conversationId?: string) =>
    request<{
      status: string;
      model_id?: string | null;
      current: { total_tokens: number | null; input_tokens: number | null; output_tokens: number | null; kind: string };
      peak: { total_tokens: number | null };
      totals: { session_tokens: number; conversation_tokens: number };
      model_calls: number;
      history: Array<{ at: number; total_tokens: number | null; input_tokens?: number | null; output_tokens?: number | null; kind?: string; status?: string }>;
      last_error?: string | null;
    }>(`/chat/usage-telemetry${conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : ""}`),
  runInspection: (runId: string) => request<Record<string, unknown>>(`/runs/${runId}/inspection`),
  specialists: () => request<{ items: SpecialistContract[]; router?: string }>("/specialists"),

  memories: (query = "", collection = "", scope = "") =>
    request<MemoriesResponse>(
      `/memories?q=${encodeURIComponent(query)}&collection=${encodeURIComponent(collection)}&scope=${encodeURIComponent(scope)}`,
    ),
  createMemory: (values: Omit<MemoryItem, "id" | "created_at" | "updated_at">) => request<MemoryItem>("/memories", { method: "POST", body: JSON.stringify(values) }),
  updateMemory: (id: string, values: Omit<MemoryItem, "id" | "created_at" | "updated_at">) => request<MemoryItem>(`/memories/${id}`, { method: "PUT", body: JSON.stringify(values) }),
  supersedeMemory: (id: string, values: Omit<MemoryItem, "id" | "created_at" | "updated_at">) => request<MemoryItem>(`/memories/${id}/supersede`, { method: "POST", body: JSON.stringify(values) }),
  memoryHistory: (id: string) => request<{ items: MemoryItem[] }>(`/memories/${id}/history`),
  deleteMemory: (id: string) => request<void>(`/memories/${id}`, { method: "DELETE" }),
  retrieveMemory: (query: string) => request<{ matches: Array<MemoryItem & { score: number }> }>("/memories/retrieve", { method: "POST", body: JSON.stringify({ query }) }),
  exportMemories: () => request<{ version: number; exported_at: string; items: MemoryItem[] }>("/memories/export"),
  importMemories: (items: Array<Omit<MemoryItem, "id" | "created_at" | "updated_at">>) => request<{ imported: number }>("/memories/import", { method: "POST", body: JSON.stringify({ items }) }),

  knowledge: () => request<{ stats: KnowledgeStats; sources: KnowledgeSource[] }>("/knowledge"),
  searchKnowledge: (query: string, limit = 8) => request<{ matches: KnowledgeMatch[] }>("/knowledge/search", { method: "POST", body: JSON.stringify({ query, limit }) }),
  harvestKnowledgeSite: (values: {
    url: string;
    max_pages?: number;
    max_depth?: number;
    max_documents?: number;
    authorized_downloads: boolean;
    include_html_pages?: boolean;
    approved_network: boolean;
  }) => request<KnowledgeHarvestResult>("/knowledge/harvest", { method: "POST", body: JSON.stringify(values) }),
  exportKnowledgePack: (limit = 200) => request<{
    format: string;
    exported_at: string;
    memory_count: number;
    knowledge_count: number;
    agent_count?: number;
    decision_count?: number;
    evidence_count?: number;
    memories: MemoryItem[];
    knowledge_sources: KnowledgeSource[];
    evidence?: Array<Record<string, unknown>>;
    agents?: Array<Record<string, unknown>>;
    decisions?: Array<Record<string, unknown>>;
    notes?: string[];
    stats: KnowledgeStats;
  }>(`/knowledge/pack?limit=${limit}`),
  importKnowledgePack: (pack: Record<string, unknown>) =>
    request<{
      imported_memories: number;
      imported_knowledge_stubs: number;
      updated_agents: number;
      notes: string[];
    }>("/knowledge/pack/import", { method: "POST", body: JSON.stringify(pack) }),

  claims: (taskId = "") =>
    request<{ claims: ClaimRecord[]; count: number }>(
      `/claims${taskId ? `?task_id=${encodeURIComponent(taskId)}` : ""}`,
    ),
  addClaim: (values: {
    text: string;
    provenance?: string;
    verification_status?: string;
    source_kind?: string;
    task_id?: string;
    supports?: string[];
    contradicts?: string[];
  }) => request<{ id: string; claim: ClaimRecord }>("/claims", { method: "POST", body: JSON.stringify(values) }),
  attachClaimEvidence: (
    claimId: string,
    values: { evidence_id: string; relation?: string; independent?: boolean; note?: string },
  ) =>
    request<{ claim: ClaimRecord }>(`/claims/${encodeURIComponent(claimId)}/evidence`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  reassessClaim: (claimId: string) =>
    request<{ claim: ClaimRecord }>(`/claims/${encodeURIComponent(claimId)}/reassess`, { method: "POST" }),

  brain: (viewId = "default") => request<BrainResponse>(`/brain?view_id=${encodeURIComponent(viewId)}`),
  /** One Brain observability overview (`/api/hades-brain/overview`). */
  hadesBrainOverview: (signal?: AbortSignal) =>
    request<{
      brain?: string;
      monolith?: boolean;
      substrate?: Record<string, unknown>;
      capability_intel?: Record<string, unknown>;
      cognitive?: { status?: string; error?: string; [key: string]: unknown } | null;
      [key: string]: unknown;
    }>("/hades-brain/overview", { signal }),
  brainLayout: (viewId = "default") => request<BrainLayout>(`/brain/layout?view_id=${encodeURIComponent(viewId)}`),
  saveBrainLayoutPosition: (values: { entity_id: string; pos_x: number; pos_y: number; pinned?: boolean; view_id?: string }) =>
    request<BrainLayoutPosition>("/brain/layout/position", { method: "PUT", body: JSON.stringify(values) }),
  saveBrainViewport: (values: { x: number; y: number; zoom: number; view_id?: string }) =>
    request<{ view_id: string; x: number; y: number; zoom: number }>("/brain/layout/viewport", { method: "PUT", body: JSON.stringify(values) }),
  createBrainNode: (values: { label: string; kind: string; description: string; tags: string[]; connect_to?: string; pos_x?: number; pos_y?: number }) =>
    request<BrainNode>("/brain/nodes", { method: "POST", body: JSON.stringify(values) }),
  updateBrainNode: (id: string, values: { label?: string; kind?: string; description?: string; tags?: string[]; pos_x?: number; pos_y?: number }) =>
    request<BrainNode>(`/brain/nodes/${encodeURIComponent(id)}`, { method: "PUT", body: JSON.stringify(values) }),
  deleteBrainNode: (id: string) => request<void>(`/brain/nodes/${encodeURIComponent(id)}`, { method: "DELETE" }),
  createBrainLink: (values: { source_id: string; target_id: string; relation?: string }) =>
    request<BrainLink>("/brain/links", { method: "POST", body: JSON.stringify(values) }),
  updateBrainLink: (values: { source_id: string; target_id: string; relation: string }) =>
    request<BrainLink>("/brain/links", { method: "PUT", body: JSON.stringify(values) }),
  deleteBrainLink: (sourceId: string, targetId: string) =>
    request<void>(`/brain/links?source_id=${encodeURIComponent(sourceId)}&target_id=${encodeURIComponent(targetId)}`, { method: "DELETE" }),
  modelGateway: () => request<{ gateway: ModelGatewayOverview; router_capacity: Record<string, unknown>; budget_pool: Record<string, unknown> }>("/models/gateway"),
  agents: () => request<AgentsConsoleResponse>("/agents"),
  agent: (id: string) => request<HadesAgent>(`/agents/${encodeURIComponent(id)}`),
  setAgentState: (id: string, enabled: boolean) => request<HadesAgent>(`/agents/${encodeURIComponent(id)}/state`, { method: "PUT", body: JSON.stringify({ enabled }) }),
  cancelAgentCurrent: (id: string) => request<{ cancelled_task_ids: string[]; agent: HadesAgent | null }>(`/agents/${encodeURIComponent(id)}/cancel-current`, { method: "POST" }),

  files: (workspaceId = "") => request<{ workspaces: Workspace[]; files: IndexedFile[]; knowledge: KnowledgeStats; uploads_count: number; filter: string }>(`/files?workspace_id=${encodeURIComponent(workspaceId)}`),
  addWorkspace: (values: { path: string; name?: string; recursive: boolean; max_files?: number; approved: boolean }) => request<{ workspace: Workspace; processed: number; ready: number; failed: number; unsupported: number; unchanged: number; limited: boolean }>("/files/workspaces", { method: "POST", body: JSON.stringify(values) }),
  rescanWorkspace: (workspaceId: string, values?: { recursive?: boolean; max_files?: number; approved?: boolean }) =>
    request<{ workspace: Workspace; processed: number; ready: number; failed: number; unsupported: number; unchanged: number; limited: boolean }>(
      `/files/workspaces/${encodeURIComponent(workspaceId)}/rescan`,
      { method: "POST", body: JSON.stringify({ recursive: true, max_files: 10000, approved: true, ...values }) },
    ),
  deleteWorkspace: (workspaceId: string) => request<{ removed: boolean; workspace: Workspace & { removed_files?: number } }>(`/files/workspaces/${encodeURIComponent(workspaceId)}`, { method: "DELETE" }),
  uploadFile: (file: File, approved: boolean) => {
    const body = new FormData();
    body.append("file", file);
    body.append("approved", String(approved));
    return request<{ path: string; file: IndexedFile; source: KnowledgeSource | null; chunks: number }>("/files/upload", { method: "POST", body });
  },
  fileDetail: (fileId: string, chunkLimit = 40) =>
    request<{ file: IndexedFile; source: KnowledgeSource | null; chunks: Array<{ id: string; source_id: string; sequence: number; heading: string; content: string; token_estimate: number }> }>(
      `/files/${encodeURIComponent(fileId)}?chunk_limit=${chunkLimit}`,
    ),
  reindexFile: (fileId: string) => request<{ file: IndexedFile; source: KnowledgeSource | null; chunks: number; unchanged?: boolean }>(`/files/${encodeURIComponent(fileId)}/reindex?approved=true`, { method: "POST" }),
  deleteIndexedFile: (fileId: string) => request<{ removed: boolean; file: IndexedFile }>(`/files/${encodeURIComponent(fileId)}`, { method: "DELETE" }),

  research: () => request<{ projects: ResearchProject[]; knowledge: KnowledgeStats }>("/research"),
  createResearch: (values: {
    title?: string;
    topic: string;
    depth: ResearchProject["depth"];
    allow_web: boolean;
    sources: string[];
    auto_start: boolean;
    approved_network: boolean;
    approved_file_read: boolean;
    authorized_downloads: boolean;
    max_rounds?: number | null;
    agent_count?: number;
  }) => request<ResearchProject>("/research", { method: "POST", body: JSON.stringify(values) }),
  startConversationResearch: (
    conversationId: string,
    values: {
      title?: string;
      topic: string;
      depth?: ResearchProject["depth"];
      allow_web?: boolean;
      sources?: string[];
      auto_start?: boolean;
      approved_network?: boolean;
      approved_file_read?: boolean;
      authorized_downloads?: boolean;
      max_rounds?: number | null;
      agent_count?: number;
    },
  ) =>
    request<{ conversation_id: string; project: ResearchProject; conversation_run?: ConversationRunLink | null }>(
      `/conversations/${encodeURIComponent(conversationId)}/research`,
      { method: "POST", body: JSON.stringify(values) },
    ),
  researchProject: (id: string) => request<{ project: ResearchProject; events: ResearchEvent[]; sources: KnowledgeSource[] }>(`/research/${id}`),
  researchCoverage: (id: string) => request<ResearchCoverageSummary>(`/research/${id}/coverage`),
  runResearch: (id: string) => request<ResearchProject>(`/research/${id}/run`, { method: "POST" }),
  cancelResearch: (id: string) => request<ResearchProject>(`/research/${id}/cancel`, { method: "POST" }),

  ...pluginApi,

  trading: () => request<PaperTradingState>("/trading"),
  tradingDashboard: () => request<TradingDashboard>("/trading/dashboard"),
  setPaperTrading: (enabled: boolean) => request<PaperTradingState>("/trading/enabled", { method: "PUT", body: JSON.stringify({ enabled }) }),
  setTradingKillSwitch: (armed: boolean) => request<PaperTradingState>("/trading/kill-switch", { method: "PUT", body: JSON.stringify({ armed }) }),
  paperBuy: (symbol: string, quantity: number, price: number) => request<{ order_id: string; position_id: string; state: PaperTradingState }>("/trading/buy", { method: "POST", body: JSON.stringify({ symbol, quantity, price }) }),
  closePaperPosition: (id: string, price: number) => request<{ order_id: string; realized_pnl: number; state: PaperTradingState }>(`/trading/positions/${encodeURIComponent(id)}/close`, { method: "POST", body: JSON.stringify({ price }) }),
  resetPaperTrading: (balance = 10000) => request<PaperTradingState>("/trading/reset", { method: "POST", body: JSON.stringify({ balance }) }),
  seedTradingMarket: (values?: { symbol?: string; timeframe?: string; bars?: number; start_price?: number; seed?: number; replace?: boolean }) =>
    request<{ summary: Record<string, unknown>; dashboard: TradingDashboard }>("/trading/market/seed", { method: "POST", body: JSON.stringify(values ?? {}) }),
  importTradingCsv: (values: { symbol: string; timeframe?: string; csv_text: string; replace?: boolean }) =>
    request<{ summary: Record<string, unknown>; dashboard: TradingDashboard }>("/trading/market/import-csv", { method: "POST", body: JSON.stringify(values) }),
  updateTradingBot: (values: { enabled?: boolean; strategy_id?: string | null; symbol?: string; timeframe?: string; position_fraction?: number; clear_strategy?: boolean }) =>
    request<{ bot: TradingBotSettings; dashboard: TradingDashboard }>("/trading/bot", { method: "PUT", body: JSON.stringify(values) }),
  createTradingRun: (values: { kind: "discover" | "backtest" | "paper_bot"; symbol?: string; timeframe?: string; strategy_id?: string; top_n?: number; window?: number; auto_start?: boolean }) =>
    request<{ run: TradingRun; dashboard: TradingDashboard }>("/trading/runs", { method: "POST", body: JSON.stringify(values) }),
  cancelTradingRun: (runId: string) => request<{ run: TradingRun; dashboard: TradingDashboard }>(`/trading/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" }),

  // --- Trading Lab ---------------------------------------------------------------
  labOverview: () => request<LabOverview>("/trading/lab/overview"),
  labCapabilities: () => request<Record<string, unknown>>("/trading/lab/capabilities"),
  labDataGaps: () => request<Record<string, unknown>>("/trading/lab/data-gaps"),
  labJobs: () => request<LabJobsSnapshot>("/trading/lab/jobs"),
  labInstruments: (params?: { family?: string; venue?: string }) => {
    const query = new URLSearchParams();
    if (params?.family) query.set("family", params.family);
    if (params?.venue) query.set("venue", params.venue);
    const suffix = query.toString();
    return request<{ instruments: LabInstrument[] }>(`/trading/lab/instruments${suffix ? `?${suffix}` : ""}`);
  },
  createLabInstrument: (values: Record<string, unknown>) =>
    request<LabInstrument>("/trading/lab/instruments", { method: "POST", body: JSON.stringify(values) }),
  deleteLabInstrument: (instrumentId: string) =>
    request<{ deleted: boolean; reason?: string }>(`/trading/lab/instruments/${encodeURIComponent(instrumentId)}`, { method: "DELETE" }),
  labDatasets: (params?: { instrument_id?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.instrument_id) query.set("instrument_id", params.instrument_id);
    query.set("limit", String(params?.limit ?? 200));
    return request<{ datasets: LabDataset[] }>(`/trading/lab/datasets?${query.toString()}`);
  },
  labDataset: (datasetId: string) => request<Record<string, unknown>>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}`),
  labDatasetPreview: (datasetId: string, limit = 300) =>
    request<Record<string, unknown>>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}/preview?limit=${limit}`),
  labDatasetGaps: (datasetId: string) => request<Record<string, unknown>>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}/gaps`),
  labImportDataset: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/datasets/import", { method: "POST", body: JSON.stringify(values) }),
  labDownloadDataset: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/datasets/download", { method: "POST", body: JSON.stringify(values) }),
  labSyntheticDataset: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/datasets/synthetic", { method: "POST", body: JSON.stringify(values) }),
  labFreezeDataset: (datasetId: string) =>
    request<{ dataset: LabDataset }>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}/freeze`, { method: "POST" }),
  labSetDatasetSplits: (datasetId: string, values: Record<string, unknown>) =>
    request<{ dataset: LabDataset }>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}/splits`, { method: "PUT", body: JSON.stringify(values) }),
  labImportCorporateActions: (datasetId: string, actions: Array<Record<string, unknown>>) =>
    request<Record<string, unknown>>(`/trading/lab/datasets/${encodeURIComponent(datasetId)}/corporate-actions`, {
      method: "POST",
      body: JSON.stringify({ actions }),
    }),
  labProviders: () => request<Record<string, unknown>>("/trading/lab/providers"),
  labStrategies: (params?: { status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    query.set("limit", String(params?.limit ?? 200));
    return request<{ strategies: LabStrategy[] }>(`/trading/lab/strategies?${query.toString()}`);
  },
  labStrategyFamilies: () => request<{ families: Array<Record<string, unknown>> }>("/trading/lab/strategy-families"),
  labStrategy: (strategyId: string) => request<Record<string, unknown>>(`/trading/lab/strategies/${encodeURIComponent(strategyId)}`),
  createLabStrategy: (values: Record<string, unknown>) =>
    request<{ created: boolean; reason?: string; strategy?: LabStrategy }>("/trading/lab/strategies", { method: "POST", body: JSON.stringify(values) }),
  addLabStrategyVersion: (strategyId: string, values: Record<string, unknown>) =>
    request<{ created?: boolean; reason?: string; version?: number; strategy?: LabStrategy }>(
      `/trading/lab/strategies/${encodeURIComponent(strategyId)}/versions`,
      { method: "POST", body: JSON.stringify(values) },
    ),
  promoteLabStrategy: (values: Record<string, unknown>) =>
    request<{ promoted: boolean; reason?: string; strategy?: LabStrategy }>("/trading/lab/strategies/promote", { method: "POST", body: JSON.stringify(values) }),
  labExperiments: (params?: { status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    query.set("limit", String(params?.limit ?? 100));
    return request<{ experiments: LabExperiment[] }>(`/trading/lab/experiments?${query.toString()}`);
  },
  createLabExperiment: (values: Record<string, unknown>) =>
    request<{ created?: boolean; reason?: string; experiment_id?: string; experiment?: LabExperiment }>("/trading/lab/experiments", { method: "POST", body: JSON.stringify(values) }),
  labExperiment: (experimentId: string) => request<Record<string, unknown>>(`/trading/lab/experiments/${encodeURIComponent(experimentId)}`),
  startLabExperiment: (experimentId: string, strategyId?: string) =>
    request<Record<string, unknown>>(
      `/trading/lab/experiments/${encodeURIComponent(experimentId)}/start${strategyId ? `?strategy_id=${encodeURIComponent(strategyId)}` : ""}`,
      { method: "POST" },
    ),
  labRuns: (params?: { status?: string; mode?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.mode) query.set("mode", params.mode);
    query.set("limit", String(params?.limit ?? 100));
    return request<{ runs: LabRun[] }>(`/trading/lab/runs?${query.toString()}`);
  },
  startLabRun: (values: Record<string, unknown>) =>
    request<{ started: boolean; reason?: string; run_id?: string; job?: Record<string, unknown> }>("/trading/lab/runs", { method: "POST", body: JSON.stringify(values) }),
  labRun: (runId: string) => request<Record<string, unknown>>(`/trading/lab/runs/${encodeURIComponent(runId)}`),
  labRunOrders: (runId: string, limit = 200) =>
    request<{ orders: Array<Record<string, unknown>> }>(`/trading/lab/runs/${encodeURIComponent(runId)}/orders?limit=${limit}`),
  labRunFills: (runId: string, limit = 500) =>
    request<{ fills: Array<Record<string, unknown>> }>(`/trading/lab/runs/${encodeURIComponent(runId)}/fills?limit=${limit}`),
  labRunLedger: (runId: string, limit = 1000) =>
    request<Record<string, unknown>>(`/trading/lab/runs/${encodeURIComponent(runId)}/ledger?limit=${limit}`),
  labRunDecisions: (runId: string, limit = 200) =>
    request<{ decisions: Array<Record<string, unknown>> }>(`/trading/lab/runs/${encodeURIComponent(runId)}/decisions?limit=${limit}`),
  labRunSnapshots: (runId: string, limit = 500) =>
    request<{ snapshots: Array<Record<string, unknown>> }>(`/trading/lab/runs/${encodeURIComponent(runId)}/snapshots?limit=${limit}`),
  controlLabRun: (runId: string, action: string, value?: number) =>
    request<Record<string, unknown>>(`/trading/lab/runs/${encodeURIComponent(runId)}/control`, { method: "POST", body: JSON.stringify({ action, value }) }),
  rewindLabRun: (runId: string, eventTime: string) =>
    request<Record<string, unknown>>(`/trading/lab/runs/${encodeURIComponent(runId)}/rewind`, { method: "POST", body: JSON.stringify({ event_time: eventTime }) }),
  labRunReproducibility: (runId: string) => request<Record<string, unknown>>(`/trading/lab/runs/${encodeURIComponent(runId)}/reproducibility`),
  labCompareRuns: (left: string, right: string) =>
    request<Record<string, unknown>>(`/trading/lab/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`),
  labEvaluations: (params?: { strategy_id?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.strategy_id) query.set("strategy_id", params.strategy_id);
    query.set("limit", String(params?.limit ?? 100));
    return request<{ evaluations: LabEvaluation[] }>(`/trading/lab/evaluations?${query.toString()}`);
  },
  startLabEvaluation: (values: Record<string, unknown>) =>
    request<{ started: boolean; reason?: string; job?: Record<string, unknown> }>("/trading/lab/evaluations", { method: "POST", body: JSON.stringify(values) }),
  labEvaluation: (reportId: string) => request<Record<string, unknown>>(`/trading/lab/evaluations/${encodeURIComponent(reportId)}`),
  labPortfolio: (runId?: string) =>
    request<Record<string, unknown>>(`/trading/lab/portfolio${runId ? `?run_id=${encodeURIComponent(runId)}` : ""}`),
  labRiskPreview: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/risk/preview", { method: "POST", body: JSON.stringify(values) }),
  labOrderPreview: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/orders/preview", { method: "POST", body: JSON.stringify(values) }),
  labModels: () => request<{ models: Array<Record<string, unknown>> }>("/trading/lab/models"),
  trainLabModel: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/models/train", { method: "POST", body: JSON.stringify(values) }),
  labAgentRoles: () => request<Record<string, unknown>>("/trading/lab/agents/roles"),
  labAgentSessions: (limit = 50) => request<{ sessions: Array<Record<string, unknown>> }>(`/trading/lab/agents/sessions?limit=${limit}`),
  runLabAgents: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/agents/run", { method: "POST", body: JSON.stringify(values) }),
  labSettings: () => request<Record<string, unknown>>("/trading/lab/settings"),
  saveLabSettings: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/settings", { method: "PUT", body: JSON.stringify(values) }),
  labLearningOverview: () => request<Record<string, unknown>>("/trading/lab/learning/overview"),
  ingestLabExperiences: (values: Record<string, unknown> = {}) =>
    request<Record<string, unknown>>("/trading/lab/learning/experiences/ingest", { method: "POST", body: JSON.stringify(values) }),
  labExperiences: (params?: { strategy_id?: string; strategy_family?: string; instrument_id?: string; timeframe?: string; regime_key?: string; split?: string; limit?: number; offset?: number }) => {
    const query = new URLSearchParams();
    if (params?.strategy_id) query.set("strategy_id", params.strategy_id);
    if (params?.strategy_family) query.set("strategy_family", params.strategy_family);
    if (params?.instrument_id) query.set("instrument_id", params.instrument_id);
    if (params?.timeframe) query.set("timeframe", params.timeframe);
    if (params?.regime_key) query.set("regime_key", params.regime_key);
    if (params?.split) query.set("split", params.split);
    query.set("limit", String(params?.limit ?? 50));
    query.set("offset", String(params?.offset ?? 0));
    return request<{ experiences: Array<Record<string, unknown>>; count: number; limit: number; offset: number }>(`/trading/lab/learning/experiences?${query.toString()}`);
  },
  labBeliefs: (params?: { status?: string; strategy_family?: string; instrument_id?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.strategy_family) query.set("strategy_family", params.strategy_family);
    if (params?.instrument_id) query.set("instrument_id", params.instrument_id);
    query.set("limit", String(params?.limit ?? 100));
    return request<{ beliefs: Array<Record<string, unknown>> }>(`/trading/lab/learning/beliefs?${query.toString()}`);
  },
  labLearningFindings: (cycleId?: string) => {
    const query = new URLSearchParams();
    if (cycleId) query.set("cycle_id", cycleId);
    return request<{ findings: Array<Record<string, unknown>> }>(`/trading/lab/learning/findings?${query.toString()}`);
  },
  labStrategyLineage: (strategyId?: string) => {
    const query = new URLSearchParams();
    if (strategyId) query.set("strategy_id", strategyId);
    return request<{ lineage: Array<Record<string, unknown>> }>(`/trading/lab/learning/lineage?${query.toString()}`);
  },
  labStrategyCandidates: (params?: { cycle_id?: string; strategy_id?: string }) => {
    const query = new URLSearchParams();
    if (params?.cycle_id) query.set("cycle_id", params.cycle_id);
    if (params?.strategy_id) query.set("strategy_id", params.strategy_id);
    return request<{ candidates: Array<Record<string, unknown>> }>(`/trading/lab/learning/candidates?${query.toString()}`);
  },
  labChampions: () => request<{ champions: Array<Record<string, unknown>> }>("/trading/lab/learning/champions"),
  compareLabChampion: (values: { strategy_id: string; version?: number }) =>
    request<Record<string, unknown>>("/trading/lab/learning/champions/compare", { method: "POST", body: JSON.stringify(values) }),
  labLearningCycles: (limit = 50) => request<{ cycles: Array<Record<string, unknown>> }>(`/trading/lab/learning/cycles?limit=${limit}`),
  labLearningCycle: (cycleId: string) => request<Record<string, unknown>>(`/trading/lab/learning/cycles/${encodeURIComponent(cycleId)}`),
  startLabLearningCycle: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/trading/lab/learning/cycles", { method: "POST", body: JSON.stringify(values) }),

  mediaOverview: () => request<MediaOverview>("/media/overview"),
  mediaCapabilities: () => request<Record<string, unknown>>("/media/capabilities"),
  mediaSetup: () => request<Record<string, unknown>>("/media/setup"),
  mediaChannels: (limit = 50, offset = 0) =>
    request<{ items: MediaChannel[]; limit: number; offset: number }>(`/media/channels?limit=${limit}&offset=${offset}`),
  createMediaChannel: (values: Record<string, unknown>) =>
    request<{ channel: MediaChannel }>("/media/channels", { method: "POST", body: JSON.stringify(values) }),
  updateMediaChannel: (id: string, values: Record<string, unknown>) =>
    request<{ channel: MediaChannel }>(`/media/channels/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(values) }),
  mediaProjects: (params?: { channel_id?: string; stage?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.channel_id) query.set("channel_id", params.channel_id);
    if (params?.stage) query.set("stage", params.stage);
    query.set("limit", String(params?.limit ?? 50));
    return request<{ items: MediaProject[] }>(`/media/projects?${query.toString()}`);
  },
  createMediaProject: (values: Record<string, unknown>) =>
    request<{ project: MediaProject }>("/media/projects", { method: "POST", body: JSON.stringify(values) }),
  mediaProject: (id: string) => request<Record<string, unknown>>(`/media/projects/${encodeURIComponent(id)}`),
  runMediaProject: (id: string, max_stages = 30) =>
    request<{ ok: boolean; project?: MediaProject }>(`/media/projects/${encodeURIComponent(id)}/run`, {
      method: "POST",
      body: JSON.stringify({ max_stages }),
    }),
  cancelMediaProject: (id: string) =>
    request<{ project: MediaProject }>(`/media/projects/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  mediaTrends: (limit = 50) => request<{ items: Array<Record<string, unknown>> }>(`/media/trends?limit=${limit}`),
  discoverMediaTrends: (values?: { query?: string; channel_id?: string }) =>
    request<Record<string, unknown>>("/media/trends/discover", { method: "POST", body: JSON.stringify(values ?? {}) }),
  mediaOpportunities: (channel_id?: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      channel_id ? `/media/opportunities?channel_id=${encodeURIComponent(channel_id)}` : "/media/opportunities",
    ),
  mediaIdeas: (channel_id?: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      channel_id ? `/media/ideas?channel_id=${encodeURIComponent(channel_id)}` : "/media/ideas",
    ),
  mediaAssets: (project_id?: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      project_id ? `/media/assets?project_id=${encodeURIComponent(project_id)}` : "/media/assets",
    ),
  mediaPublishJobs: (params?: { status?: string; project_id?: string }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status", params.status);
    if (params?.project_id) query.set("project_id", params.project_id);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ items: Array<Record<string, unknown>> }>(`/media/publish${suffix}`);
  },
  approveMediaPublish: (values: { job_ids: string[]; platform_consent?: Record<string, unknown> }) =>
    request<{ items: Array<Record<string, unknown>> }>("/media/publish/approve", { method: "POST", body: JSON.stringify(values) }),
  executeMediaPublish: (jobId: string) =>
    request<Record<string, unknown>>(`/media/publish/${encodeURIComponent(jobId)}/execute`, { method: "POST" }),
  mediaAnalytics: (params?: { platform?: string; external_post_id?: string; project_id?: string }) => {
    const query = new URLSearchParams();
    if (params?.platform) query.set("platform", params.platform);
    if (params?.external_post_id) query.set("external_post_id", params.external_post_id);
    if (params?.project_id) query.set("project_id", params.project_id);
    const suffix = query.toString() ? `?${query.toString()}` : "";
    return request<{ items: Array<Record<string, unknown>> }>(`/media/analytics${suffix}`);
  },
  mediaExperiments: (channel_id?: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      channel_id ? `/media/experiments?channel_id=${encodeURIComponent(channel_id)}` : "/media/experiments",
    ),
  mediaLearning: (channel_id?: string) =>
    request<{ items: Array<Record<string, unknown>> }>(
      channel_id ? `/media/learning?channel_id=${encodeURIComponent(channel_id)}` : "/media/learning",
    ),
  mediaSchedulerTick: () => request<Record<string, unknown>>("/media/scheduler/tick", { method: "POST" }),

  settings: () => request<{ values: AppSettings; storage: { path: string; size_bytes: number }; version: string; knowledge?: KnowledgeStats; config_revision?: number }>("/settings"),
  saveSettings: (values: AppSettings, options?: { expected_revision?: number }) =>
    request<{ values: AppSettings; config_revision?: number }>("/settings", {
      method: "PUT",
      body: JSON.stringify(
        options?.expected_revision != null
          ? { values, expected_revision: options.expected_revision }
          : values,
      ),
    }),
  patchSettings: (values: Partial<AppSettings>, expected_revision?: number) =>
    request<{ values: AppSettings; config_revision?: number }>("/settings", {
      method: "PATCH",
      body: JSON.stringify({
        values,
        ...(expected_revision != null ? { expected_revision } : {}),
      }),
    }),
  resetSettings: () => request<{ values: AppSettings }>("/settings/reset", { method: "POST" }),

  neuralStatus: (signal?: AbortSignal) => request<NeuralProductStatus>("/neural/status", { signal }),
  neuralSettings: (signal?: AbortSignal) => request<NeuralProductSettings>("/neural/settings", { signal }),
  patchNeuralSettings: (values: Partial<NeuralProductSettings>) =>
    request<{ updated: boolean; values: Partial<NeuralProductSettings>; config_revision?: number }>("/neural/settings", {
      method: "PATCH",
      body: JSON.stringify(values),
    }),
  neuralDomains: (signal?: AbortSignal) => request<Record<string, unknown>>("/neural/domains", { signal }),
  neuralRuntimeStart: () => request<NeuralProductStatus>("/neural/runtime/start", { method: "POST" }),
  neuralRuntimeStop: () => request<NeuralProductStatus>("/neural/runtime/stop", { method: "POST" }),

  nativeStatus: () => request<NativeRuntimeStatus>("/native/status"),
  nativeRestart: () => request<NativeRuntimeStatus>("/native/restart", { method: "POST" }),
  nativeMetrics: () => request<{ available: boolean; fallback_active: boolean; metrics: Record<string, unknown> | null }>("/native/metrics"),
  nativeBenchmark: () =>
    request<{ available: boolean; fallback_active: boolean; result: Record<string, unknown> | null; note?: string }>("/native/benchmark", {
      method: "POST",
    }),
  backupDatabase: () =>
    request<{ created: boolean; path: string; size_bytes: number; kind?: string; full_workspace?: boolean; note?: string }>(
      "/settings/backup",
      { method: "POST" },
    ),
  workspaceBackupInventory: (params?: { include_secrets?: boolean; include?: string; exclude?: string }) => {
    const q = new URLSearchParams();
    if (params?.include_secrets) q.set("include_secrets", "true");
    if (params?.include) q.set("include", params.include);
    if (params?.exclude) q.set("exclude", params.exclude);
    const suffix = q.toString() ? `?${q}` : "";
    return request<Record<string, unknown>>(`/workspace/backup/inventory${suffix}`);
  },
  workspaceBackup: (values: { include?: string[]; exclude?: string[]; include_secrets?: boolean } = {}) =>
    request<Record<string, unknown>>("/workspace/backup", { method: "POST", body: JSON.stringify(values) }),
  workspaceBackupJob: (jobId: string) => request<Record<string, unknown>>(`/workspace/backup/jobs/${encodeURIComponent(jobId)}`),
  workspaceBackupCancel: (jobId: string) =>
    request<Record<string, unknown>>(`/workspace/backup/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" }),
  workspaceRestore: (values: { archive_path: string; target_dir?: string }) =>
    request<Record<string, unknown>>("/workspace/restore", { method: "POST", body: JSON.stringify(values) }),
  workspaceRestoreActivate: (values: { isolated_workspace_root: string; confirm: boolean; backup_current?: boolean }) =>
    request<Record<string, unknown>>("/workspace/restore/activate", { method: "POST", body: JSON.stringify(values) }),
  gen2ComparativeReplay: (
    runId: string,
    values: {
      alternate_model?: string;
      implementation_id?: string;
      reuse_recorded_tools?: boolean;
      reexecute_side_effects?: boolean;
      from_sequence?: number;
      stub_model_output?: string;
      stub_tokens?: number;
      source_versions?: Record<string, unknown>;
    } = {},
  ) =>
    request<Record<string, unknown>>(`/gen2/flight/runs/${encodeURIComponent(runId)}/comparative-replay`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2RecordFlightEvent: (values: {
    run_id: string;
    event_type: string;
    payload?: Record<string, unknown>;
    model_id?: string | null;
    component?: string | null;
    input_text?: string | null;
    output_text?: string | null;
    config_fingerprint?: string | null;
  }) =>
    request<Record<string, unknown>>("/gen2/flight/events", { method: "POST", body: JSON.stringify(values) }),
  gen2EmitLifecycle: (values: {
    run_id: string;
    phase: string;
    payload?: Record<string, unknown>;
    model_id?: string | null;
    component?: string | null;
    input_text?: string | null;
    output_text?: string | null;
    config_fingerprint?: string | null;
    severity?: string | null;
    duration_ms?: number | null;
    correlation_id?: string | null;
  }) =>
    request<Record<string, unknown>>("/gen2/flight/lifecycle", { method: "POST", body: JSON.stringify(values) }),
  gen2FlightEvents: (runId: string, afterSequence = 0) =>
    request<Array<Record<string, unknown>>>(
      `/gen2/flight/runs/${encodeURIComponent(runId)}/events?after_sequence=${afterSequence}`,
    ),
  gen2FlightAuditBundle: (runId: string) =>
    request<Record<string, unknown>>(`/gen2/flight/runs/${encodeURIComponent(runId)}/audit-bundle`),
  gen2FlightCompare: (runA: string, runB: string) =>
    request<Record<string, unknown>>(
      `/gen2/flight/compare?run_a=${encodeURIComponent(runA)}&run_b=${encodeURIComponent(runB)}`,
    ),
  gen2FlightReplay: (
    runId: string,
    values: {
      from_sequence?: number;
      alternate_model?: string | null;
      alternate_plugin_version?: string | null;
      permit_side_effects?: boolean;
    } = {},
  ) =>
    request<Record<string, unknown>>(`/gen2/flight/runs/${encodeURIComponent(runId)}/replay`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2ComputeStatus: () => request<Record<string, unknown>>("/gen2/compute/status"),
  gen2PairWorker: (values: {
    node_id?: string;
    name?: string;
    base_url?: string;
    shared_secret?: string;
    capabilities?: Record<string, unknown>;
  }) => request<Record<string, unknown>>("/gen2/compute/workers/pair", { method: "POST", body: JSON.stringify(values) }),


  controlDashboard: () => request<{
    config_schema_version: number;
    cache_version: number;
    categories: string[];
    definition_count: number;
    presets: ControlPreset[];
    immutable_constraints: Array<Record<string, unknown>>;
    capabilities: Array<Record<string, unknown>>;
    values: Record<string, unknown>;
    recent_limit_events: Array<Record<string, unknown>>;
  }>("/control/dashboard"),
  controlDefinitions: (params?: { category?: string; q?: string }) => {
    const query = new URLSearchParams();
    if (params?.category) query.set("category", params.category);
    if (params?.q) query.set("q", params.q);
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ definitions: ControlDefinition[]; categories: string[] }>(`/control/definitions${suffix}`);
  },
  controlValues: () => request<{ values: Record<string, unknown>; cache_version: number }>("/control/values"),
  controlEffective: (params?: { setting_id?: string; agent_id?: string; project_id?: string }) => {
    const query = new URLSearchParams();
    if (params?.setting_id) query.set("setting_id", params.setting_id);
    if (params?.agent_id) query.set("agent_id", params.agent_id);
    if (params?.project_id) query.set("project_id", params.project_id);
    const suffix = query.toString() ? `?${query}` : "";
    return request<{ effective: Record<string, ControlEffectiveValue> }>(`/control/effective${suffix}`);
  },
  controlPatchSettings: (values: Record<string, unknown>, expected_revision?: number) =>
    request<{ values: Record<string, unknown>; cache_version: number; config_revision?: number }>("/control/settings", {
      method: "PATCH",
      body: JSON.stringify({
        values,
        ...(expected_revision != null ? { expected_revision } : {}),
      }),
    }),
  controlDeleteOverride: (setting_id: string, scope = "global", scope_id?: string) =>
    request<Record<string, unknown>>("/control/override/delete", {
      method: "POST",
      body: JSON.stringify({ setting_id, scope, scope_id }),
    }),
  controlApplyPreset: (preset_id: string) =>
    request<{ values: Record<string, unknown>; preset: string; applied_keys: string[] }>("/control/presets/apply", {
      method: "POST",
      body: JSON.stringify({ preset_id }),
    }),
  controlExport: (include_secrets = false) =>
    request<Record<string, unknown>>(`/control/export?include_secrets=${include_secrets ? "true" : "false"}`, { method: "POST" }),
  controlImport: (payload: { config_schema_version?: number; values?: Record<string, unknown>; overrides?: unknown[] }) =>
    request<Record<string, unknown>>("/control/import", { method: "POST", body: JSON.stringify(payload) }),
  controlLimits: (limit = 50) => request<{ events: Array<Record<string, unknown>> }>(`/control/limits?limit=${limit}`),
  controlHistory: (key?: string, limit = 100) =>
    request<{ history: Array<Record<string, unknown>> }>(`/control/history?limit=${limit}${key ? `&key=${encodeURIComponent(key)}` : ""}`),

  // Gen2 strategic systems
  gen2Dashboard: () => request<Gen2Dashboard>("/gen2/dashboard"),
  gen2RunEvals: (values?: {
    model_id?: string;
    suite?: string;
    mode?: string;
    holdout_limit?: number | null;
    seed?: number | null;
    holdout_split?: string | null;
  }) =>
    request<Gen2EvalRun>("/gen2/evals/run", { method: "POST", body: JSON.stringify(values || {}) }),
  gen2EvalCatalog: () => request<Record<string, unknown>>("/gen2/evals/catalog"),
  gen2EvalMetricsCatalog: () => request<Record<string, unknown>>("/gen2/evals/metrics-catalog"),
  gen2EvalReports: (limit = 50) => request<Gen2EvalRun[]>(`/gen2/evals/reports?limit=${limit}`),
  gen2EvalMatrix: () => request<{ rows: Array<Record<string, unknown>>; by_model: Array<Record<string, unknown>> }>("/gen2/evals/matrix"),
  gen2EvalFlaky: (params: { suite: string; mode?: string; last_n?: number }) => {
    const q = new URLSearchParams({ suite: params.suite });
    if (params.mode) q.set("mode", params.mode);
    if (params.last_n != null) q.set("last_n", String(params.last_n));
    return request<Record<string, unknown>>(`/gen2/evals/flaky?${q}`);
  },
  gen2EvalAb: (values: {
    strategy_a: string;
    strategy_b: string;
    suite?: string;
    n?: number;
    model_id?: string | null;
  }) => request<Gen2EvalRun>("/gen2/evals/ab", { method: "POST", body: JSON.stringify(values) }),
  gen2EvalPrHelp: (values: { run_a: string; run_b: string }) =>
    request<Record<string, unknown>>("/gen2/evals/pr-help", { method: "POST", body: JSON.stringify(values) }),
  gen2EvalIngestFlight: (values: { run_id: string }) =>
    request<Gen2EvalRun>("/gen2/evals/ingest-flight", { method: "POST", body: JSON.stringify(values) }),
  gen2EvalHumanRating: (values: {
    rating:
      | "directly_usable"
      | "usable_after_small_correction"
      | "needs_major_correction"
      | "unusable";
    eval_run_id?: string | null;
    task_id?: string | null;
    coding_job_id?: string | null;
    artifact_version?: string;
    model_config?: Record<string, unknown>;
    correction_notes?: string;
    correction_seconds?: number | null;
    primary_error?: string;
    original_result?: Record<string, unknown>;
    timer_opt_in?: boolean;
  }) =>
    request<Record<string, unknown>>("/gen2/evals/human-rating", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2EvalHumanRatings: (params?: { eval_run_id?: string; task_id?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.eval_run_id) q.set("eval_run_id", params.eval_run_id);
    if (params?.task_id) q.set("task_id", params.task_id);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q}` : "";
    return request<{
      ratings: Array<Record<string, unknown>>;
      trends: Record<string, unknown>;
    }>(`/gen2/evals/human-ratings${suffix}`);
  },
  gen2CompileMission: (values: { goal: string; title?: string; domain?: string }) =>
    request<Gen2Mission>("/gen2/missions/compile", { method: "POST", body: JSON.stringify(values) }),
  gen2ListMissions: (params?: { limit?: number; status?: string }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.status) query.set("status", params.status);
    const suffix = query.toString() ? `?${query}` : "";
    return request<Gen2Mission[]>(`/gen2/missions${suffix}`);
  },
  gen2MissionPortfolio: (params?: { limit?: number; status?: string }) => {
    const query = new URLSearchParams();
    if (params?.limit != null) query.set("limit", String(params.limit));
    if (params?.status) query.set("status", params.status);
    const suffix = query.toString() ? `?${query}` : "";
    return request<Gen2MissionPortfolio>(`/gen2/missions/portfolio${suffix}`);
  },
  gen2GetMission: (id: string) => request<Gen2Mission>(`/gen2/missions/${encodeURIComponent(id)}`),
  gen2MissionLinks: (id: string) =>
    request<Gen2MissionIdentityLinks>(`/gen2/missions/${encodeURIComponent(id)}/links`),
  gen2ListMissionRevisions: (id: string, limit = 50) =>
    request<Gen2MissionRevision[]>(
      `/gen2/missions/${encodeURIComponent(id)}/revisions?limit=${limit}`,
    ),
  gen2DiffMissionRevisions: (id: string, fromVersion: number, toVersion: number) =>
    request<Record<string, unknown>>(
      `/gen2/missions/${encodeURIComponent(id)}/revisions/diff?from_version=${fromVersion}&to_version=${toVersion}`,
    ),
  gen2StartMission: (id: string, options?: { force_retry?: boolean }) =>
    request<Gen2Mission>(
      `/gen2/missions/${encodeURIComponent(id)}/start${options?.force_retry ? "?force_retry=true" : ""}`,
      { method: "POST" },
    ),
  gen2PauseMission: (id: string) =>
    request<Gen2Mission>(`/gen2/missions/${encodeURIComponent(id)}/pause`, { method: "POST" }),
  gen2ResumeMission: (id: string) =>
    request<Gen2Mission>(`/gen2/missions/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  gen2MissionBudgets: (id: string) =>
    request<Gen2MissionBudgetLedger>(`/gen2/missions/${encodeURIComponent(id)}/budgets`),
  gen2DecideGate: (missionId: string, gateId: string, approve: boolean, note = "") =>
    request<Gen2Mission>(`/gen2/missions/${encodeURIComponent(missionId)}/gates/${encodeURIComponent(gateId)}`, {
      method: "POST",
      body: JSON.stringify({ approve, note }),
    }),
  gen2EvaluateMissionAcceptance: (
    id: string,
    values?: {
      status?: string | null;
      verification?: Record<string, unknown>;
      step_summary?: Record<string, unknown>;
    },
  ) =>
    request<Record<string, unknown>>(`/gen2/missions/${encodeURIComponent(id)}/acceptance/evaluate`, {
      method: "POST",
      body: JSON.stringify(values || {}),
    }),
  gen2ReplanMission: (id: string, values: { cause: string; note?: string }) =>
    request<Gen2Mission>(`/gen2/missions/${encodeURIComponent(id)}/replan`, {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2RunCommittee: (values: {
    topic: string;
    domain?: string;
    evidence?: string[];
    mode?: "heuristic" | "live" | "live_specialist" | "model";
    model_id?: string | null;
    model_slots?: Record<string, string>;
  }) => request<Gen2CommitteeSession>("/gen2/committees", { method: "POST", body: JSON.stringify(values) }),
  gen2CompileContext: (values: {
    goal: string;
    items?: Array<Record<string, unknown>>;
    max_tokens?: number;
    model_context_size?: number | null;
    run_id?: string | null;
    persist?: boolean;
    response_reserve_tokens?: number | null;
    system_reserve_tokens?: number | null;
    request_budget_tokens?: number | null;
    tokenizer_mode?: string;
    max_age_hours?: number | null;
    hierarchical_summarization?: boolean;
    pin_overflow?: string;
  }) => request<Record<string, unknown>>("/gen2/context/compile", { method: "POST", body: JSON.stringify(values) }),
  gen2CompileContextForChat: (values: {
    goal: string;
    items?: Array<Record<string, unknown>>;
    max_tokens?: number;
    opt_in?: boolean;
    persist?: boolean;
    tokenizer_mode?: string;
  }) =>
    request<Record<string, unknown>>("/gen2/context/compile-for-chat", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2FuseFinance: (values: { articles: Array<Record<string, unknown>>; symbol?: string }) =>
    request<Record<string, unknown>>("/gen2/finance/fuse", { method: "POST", body: JSON.stringify(values) }),
  gen2FinanceEventStudy: (values: {
    event?: Record<string, unknown>;
    event_id?: string;
    bars?: Array<Record<string, unknown>>;
    window_days?: number;
  }) =>
    request<Record<string, unknown>>("/gen2/finance/event-study", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2ComputeNodes: () => request<Array<Record<string, unknown>>>("/gen2/compute/nodes"),
  gen2ComputeJobs: (limit = 50) =>
    request<Array<Record<string, unknown>>>(`/gen2/compute/jobs?limit=${limit}`),
  gen2DispatchJob: (values: {
    payload?: Record<string, unknown>;
    mission_id?: string | null;
    node_id?: string | null;
    network_allowed?: boolean | null;
    prefer_local_fallback?: boolean;
  }) =>
    request<Record<string, unknown>>("/gen2/compute/jobs", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2ComputeDrainQueue: (limit = 20) =>
    request<Record<string, unknown>>(`/gen2/compute/queue/drain?limit=${limit}`, { method: "POST" }),
  gen2ComputeSingleNodeGate: () =>
    request<Record<string, unknown>>("/gen2/compute/gates/single-node"),
  gen2ComputeHeartbeat: (nodeId = "node_local") =>
    request<Record<string, unknown>>(
      `/gen2/compute/nodes/heartbeat?node_id=${encodeURIComponent(nodeId)}`,
      { method: "POST" },
    ),
  gen2SandboxProfiles: () => request<Array<Record<string, unknown>>>("/gen2/sandbox/profiles"),
  gen2SandboxHostCapabilities: () =>
    request<Record<string, unknown>>("/gen2/sandbox/host-capabilities"),
  gen2SandboxTier2Selftest: () =>
    request<Record<string, unknown>>("/gen2/sandbox/tier2-selftest", { method: "POST" }),
  gen2ApplySandboxProfile: (profileId: string, pluginId: string) =>
    request<Record<string, unknown>>(
      `/gen2/sandbox/profiles/${encodeURIComponent(profileId)}/apply`,
      { method: "POST", body: JSON.stringify({ plugin_id: pluginId }) },
    ),
  gen2SandboxJitUx: (profileId?: string) => {
    const q = profileId ? `?profile_id=${encodeURIComponent(profileId)}` : "";
    return request<Record<string, unknown>>(`/gen2/sandbox/jit/ux${q}`);
  },
  gen2SandboxJitGrants: (params?: { plugin_id?: string; status?: string; limit?: number }) => {
    const q = new URLSearchParams();
    if (params?.plugin_id) q.set("plugin_id", params.plugin_id);
    if (params?.status) q.set("status", params.status);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q}` : "";
    return request<Array<Record<string, unknown>>>(`/gen2/sandbox/jit/grants${suffix}`);
  },
  gen2RequestJitGrant: (values: {
    plugin_id: string;
    profile_id: string;
    capability: string;
    reason?: string;
    expires_at?: string | null;
  }) =>
    request<Record<string, unknown>>("/gen2/sandbox/jit/grants", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2RevokeJitGrant: (grantId: string, reason = "") =>
    request<Record<string, unknown>>(
      `/gen2/sandbox/jit/grants/${encodeURIComponent(grantId)}/revoke`,
      { method: "POST", body: JSON.stringify({ reason }) },
    ),
  gen2PluginSecurityScan: (values: { path?: string; manifest?: Record<string, unknown> }) =>
    request<Record<string, unknown>>("/gen2/plugins/security/scan", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2PluginSecurityVerify: (values: { plugin_id?: string; path?: string; expected_hash: string }) =>
    request<Record<string, unknown>>("/gen2/plugins/security/verify", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2ValidateMcpAllowlist: (config: Record<string, unknown>) =>
    request<Record<string, unknown>>("/gen2/mcp/allowlist/validate", {
      method: "POST",
      body: JSON.stringify({ config }),
    }),
  gen2EnforceToolBoundary: (values: { args?: unknown; mode?: string }) =>
    request<Record<string, unknown>>("/gen2/tools/boundary/enforce", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2SkillCatalogHygiene: (staleDays = 30) =>
    request<Record<string, unknown>>(`/gen2/skills/catalog/hygiene?stale_days=${staleDays}`),
  gen2GraphAddEdge: (values: {
    source_id: string;
    target_id: string;
    relation?: string;
    relation_kind?: string;
    valid_from?: string | null;
    valid_until?: string | null;
    observed_at?: string | null;
    source_ref?: string;
    confidence?: number;
    provenance?: string;
    supersedes?: string | null;
    contradicts?: string | null;
    metadata?: Record<string, unknown>;
    require_provenance?: boolean;
  }) =>
    request<Record<string, unknown>>("/gen2/graph/edges", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2GraphEdges: (params?: {
    as_of?: string;
    source_id?: string;
    target_id?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.as_of) q.set("as_of", params.as_of);
    if (params?.source_id) q.set("source_id", params.source_id);
    if (params?.target_id) q.set("target_id", params.target_id);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q}` : "";
    return request<Array<Record<string, unknown>>>(`/gen2/graph/edges${suffix}`);
  },
  gen2GraphAsOf: (entityId: string, asOf: string, knownAsOf?: string) => {
    const q = new URLSearchParams({
      entity_id: entityId,
      as_of: asOf,
    });
    if (knownAsOf) q.set("known_as_of", knownAsOf);
    return request<Record<string, unknown>>(`/gen2/graph/as-of?${q.toString()}`);
  },
  gen2GraphContradictions: (entityId?: string) => {
    const q = entityId ? `?entity_id=${encodeURIComponent(entityId)}` : "";
    return request<Array<Record<string, unknown>>>(`/gen2/graph/contradictions${q}`);
  },
  gen2GraphAnalogues: (params?: {
    entity_id?: string;
    relation_kind?: string;
    text?: string;
    limit?: number;
  }) => {
    const q = new URLSearchParams();
    if (params?.entity_id) q.set("entity_id", params.entity_id);
    if (params?.relation_kind) q.set("relation_kind", params.relation_kind);
    if (params?.text) q.set("text", params.text);
    if (params?.limit != null) q.set("limit", String(params.limit));
    const suffix = q.toString() ? `?${q}` : "";
    return request<Record<string, unknown>>(`/gen2/graph/analogues${suffix}`);
  },
  gen2ExtractSkill: (values: {
    name: string;
    workflow: Array<string | { action: string; inputs?: Record<string, unknown>; success_criteria?: string[] }>;
    pattern_source?: string;
    tools?: string[];
  }) => request<Record<string, unknown>>("/gen2/skills/candidates", { method: "POST", body: JSON.stringify(values) }),
  gen2ExtractSkillFromRun: (values: {
    run_id: string;
    name?: string | null;
    tools?: string[];
    create?: boolean;
  }) =>
    request<Record<string, unknown>>("/gen2/skills/extract-from-run", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2BenchmarkSkill: (id: string) => request<Record<string, unknown>>(`/gen2/skills/${encodeURIComponent(id)}/benchmark`, { method: "POST" }),
  gen2PromoteSkill: (id: string, human_approved: boolean) =>
    request<Record<string, unknown>>(`/gen2/skills/${encodeURIComponent(id)}/promote`, { method: "POST", body: JSON.stringify({ human_approved }) }),
  gen2ExecuteSkill: (id: string, inputs?: Record<string, unknown>) =>
    request<Record<string, unknown>>(`/gen2/skills/${encodeURIComponent(id)}/execute`, {
      method: "POST",
      body: JSON.stringify({ inputs: inputs || {} }),
    }),
  gen2DeactivateSkill: (id: string, reason = "deactivated") =>
    request<Record<string, unknown>>(`/gen2/skills/${encodeURIComponent(id)}/deactivate`, {
      method: "POST",
      body: JSON.stringify({ reason }),
    }),
  gen2RollbackSkill: (id: string, to_status = "benchmarked") =>
    request<Record<string, unknown>>(`/gen2/skills/${encodeURIComponent(id)}/rollback`, {
      method: "POST",
      body: JSON.stringify({ to_status }),
    }),

  // Gen2 Workflows
  gen2ListWorkflows: (params?: { status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status_filter", params.status);
    if (params?.limit != null) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<Gen2Workflow[]>(`/gen2/workflows${suffix}`);
  },
  /** Alias used by FINALBETA hooks (F-10). */
  gen2Workflows: (params?: { status?: string; limit?: number }) => {
    const query = new URLSearchParams();
    if (params?.status) query.set("status_filter", params.status);
    if (params?.limit != null) query.set("limit", String(params.limit));
    const suffix = query.toString() ? `?${query}` : "";
    return request<Gen2Workflow[]>(`/gen2/workflows${suffix}`);
  },
  gen2GetWorkflow: (id: string) =>
    request<Gen2Workflow>(`/gen2/workflows/${encodeURIComponent(id)}`),
  gen2CreateWorkflow: (values: {
    definition?: Record<string, unknown>;
    name?: string;
    note?: string;
  }) =>
    request<Gen2Workflow>("/gen2/workflows", { method: "POST", body: JSON.stringify(values) }),
  gen2UpdateWorkflow: (
    id: string,
    values: {
      definition?: Record<string, unknown>;
      name?: string;
      bump_version?: boolean;
      note?: string;
    },
  ) =>
    request<Gen2Workflow>(`/gen2/workflows/${encodeURIComponent(id)}`, {
      method: "PUT",
      body: JSON.stringify(values),
    }),
  gen2DraftWorkflow: (goal: string) =>
    request<Gen2WorkflowDefinition>("/gen2/workflows/draft", {
      method: "POST",
      body: JSON.stringify({ goal }),
    }),
  gen2ListWorkflowTemplates: () =>
    request<Gen2WorkflowTemplate[]>("/gen2/workflows/templates"),
  /** Alias used by FINALBETA hooks (F-10). */
  gen2WorkflowTemplates: () => request<Gen2WorkflowTemplate[]>("/gen2/workflows/templates"),
  gen2CreateWorkflowFromTemplate: (template_id: string, name?: string) =>
    request<Gen2Workflow>("/gen2/workflows/templates", {
      method: "POST",
      body: JSON.stringify({ template_id, name }),
    }),
  gen2ImportWorkflow: (values: { package?: Record<string, unknown>; raw?: string }) =>
    request<Gen2Workflow>("/gen2/workflows/import", {
      method: "POST",
      body: JSON.stringify(values),
    }),
  gen2ValidateWorkflow: (id: string) =>
    request<Gen2WorkflowValidateResult>(`/gen2/workflows/${encodeURIComponent(id)}/validate`, {
      method: "POST",
    }),
  gen2DryRunWorkflow: (id: string) =>
    request<Gen2WorkflowRunResult>(`/gen2/workflows/${encodeURIComponent(id)}/dry-run`, {
      method: "POST",
    }),
  gen2SandboxRunWorkflow: (id: string, values?: { inputs?: Record<string, unknown> }) =>
    request<Gen2WorkflowRunResult>(`/gen2/workflows/${encodeURIComponent(id)}/sandbox-run`, {
      method: "POST",
      body: JSON.stringify({ inputs: values?.inputs || {} }),
    }),
  gen2ExecuteWorkflow: (
    id: string,
    values?: {
      inputs?: Record<string, unknown>;
      timeout_seconds?: number;
      async_mode?: boolean;
      blocking?: boolean;
    },
  ) =>
    request<Gen2WorkflowRunResult>(`/gen2/workflows/${encodeURIComponent(id)}/execute`, {
      method: "POST",
      body: JSON.stringify({
        inputs: values?.inputs || {},
        timeout_seconds: values?.timeout_seconds,
        async_mode: values?.async_mode ?? true,
        blocking: values?.blocking ?? false,
      }),
    }),
  gen2ListWorkflowRuns: (id: string, limit = 50) =>
    request<Array<Record<string, unknown>>>(
      `/gen2/workflows/${encodeURIComponent(id)}/runs?limit=${limit}`,
    ),
  gen2GetWorkflowRun: (workflowId: string, runId: string) =>
    request<Record<string, unknown>>(
      `/gen2/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}`,
    ),
  gen2CancelWorkflowRun: (workflowId: string, runId: string) =>
    request<Record<string, unknown>>(
      `/gen2/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST" },
    ),
  gen2PauseWorkflowRun: (workflowId: string, runId: string) =>
    request<Record<string, unknown>>(
      `/gen2/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/pause`,
      { method: "POST" },
    ),
  gen2ResumeWorkflowRun: (workflowId: string, runId: string) =>
    request<Record<string, unknown>>(
      `/gen2/workflows/${encodeURIComponent(workflowId)}/runs/${encodeURIComponent(runId)}/resume`,
      { method: "POST" },
    ),
  gen2PromoteWorkflow: (id: string, values?: { human_approved?: boolean; target?: string }) =>
    request<Gen2Workflow>(`/gen2/workflows/${encodeURIComponent(id)}/promote`, {
      method: "POST",
      body: JSON.stringify(values || {}),
    }),
  gen2RollbackWorkflow: (id: string, values?: { to_status?: string; to_version?: number }) =>
    request<Gen2Workflow>(`/gen2/workflows/${encodeURIComponent(id)}/rollback`, {
      method: "POST",
      body: JSON.stringify(values || {}),
    }),
  gen2ArchiveWorkflow: (id: string) =>
    request<Gen2Workflow>(`/gen2/workflows/${encodeURIComponent(id)}/archive`, { method: "POST" }),
  gen2ListWorkflowRevisions: (id: string, limit = 50) =>
    request<Gen2WorkflowRevision[]>(
      `/gen2/workflows/${encodeURIComponent(id)}/revisions?limit=${limit}`,
    ),
  gen2DiffWorkflowRevisions: (id: string, fromVersion: number, toVersion: number) =>
    request<Record<string, unknown>>(
      `/gen2/workflows/${encodeURIComponent(id)}/diff?from=${fromVersion}&to=${toVersion}`,
    ),
  gen2ExportWorkflow: (id: string, asZip = false) =>
    request<Gen2WorkflowExportPackage>(
      `/gen2/workflows/${encodeURIComponent(id)}/export?as_zip=${asZip ? "true" : "false"}`,
    ),
  gen2WorkflowToSkill: (id: string) =>
    request<Record<string, unknown>>(`/gen2/workflows/${encodeURIComponent(id)}/to-skill`, {
      method: "POST",
    }),
  gen2DecideWorkflowHuman: (
    workflowId: string,
    stepId: string,
    values: { decision: string; value?: unknown; resume?: boolean },
  ) =>
    request<Gen2WorkflowRunResult>(
      `/gen2/workflows/${encodeURIComponent(workflowId)}/human/${encodeURIComponent(stepId)}/decide`,
      { method: "POST", body: JSON.stringify(values) },
    ),
  gen2WorkflowMetrics: (id: string) =>
    request<Gen2WorkflowMetrics>(`/gen2/workflows/${encodeURIComponent(id)}/metrics`),

  hostCapabilities: () => request<Record<string, unknown>>("/host/capabilities"),
  hostVerify: () => request<Record<string, unknown>>("/host/verify", { method: "POST", body: "{}" }),
  projectMap: (values: { path: string; refresh_symbols?: boolean }) =>
    request<Record<string, unknown>>("/project/map", { method: "POST", body: JSON.stringify(values) }),
  projectImpact: (values: { path: string; symbol?: string; file?: string; limit?: number }) =>
    request<Record<string, unknown>>("/project/impact", { method: "POST", body: JSON.stringify(values) }),
  projectRetrievalCompare: (values: { path: string; query: string; symbol?: string; limit?: number }) =>
    request<Record<string, unknown>>("/project/retrieval-compare", { method: "POST", body: JSON.stringify(values) }),
  previewPlan: (values: { path: string; kind?: string }) =>
    request<Record<string, unknown>>("/preview/plan", { method: "POST", body: JSON.stringify(values) }),
  previewStart: (values: { path: string; run_id: string; kind?: string }) =>
    request<Record<string, unknown>>("/preview/start", { method: "POST", body: JSON.stringify(values) }),
  previewStop: (values: { run_id: string }) =>
    request<Record<string, unknown>>("/preview/stop", { method: "POST", body: JSON.stringify(values) }),
  browserCapabilities: () => request<Record<string, unknown>>("/browser/capabilities"),
  computeLocalCapabilities: () => request<Record<string, unknown>>("/compute/local/capabilities"),
  computeLocalSubmit: (values: Record<string, unknown>) =>
    request<Record<string, unknown>>("/compute/local/submit", { method: "POST", body: JSON.stringify(values) }),
};

export function formatBytes(value: number): string {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} MB`;
  return `${(value / 1024 ** 3).toFixed(1)} GB`;
}

export function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("nl-NL", { dateStyle: "short", timeStyle: "short" }).format(new Date(value));
}

