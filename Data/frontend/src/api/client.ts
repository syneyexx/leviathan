import type {
  AgentCreatePayload,
  AgentDefinition,
  AgentEvent,
  AgentFleetSummary,
  AgentMission,
  AgentMissionLaunchPayload,
  AgentRosterEntry,
  AnalyticsAgentsResponse,
  AnalyticsDatasetsResponse,
  AnalyticsOverview,
  AnalyticsToolsResponse,
  AnalyticsTrainingResponse,
  ApiErrorBody,
  BackupManifest,
  ChatResponse,
  CognitionHealth,
  CognitionRunStatus,
  Conversation,
  DatasetFile,
  DatasetIndex,
  DatasetJob,
  DatasetLearningStatus,
  DatasetPreviewRow,
  DatasetRecord,
  DatasetVersion,
  DownloadJob,
  GatewaySnapshot,
  HardwareSnapshot,
  HealthResponse,
  HfDatasetFile,
  MasterGateReport,
  Message,
  MetricsSnapshot,
  ModelDescriptor,
  ModelInferenceTestResult,
  ModelProfile,
  ModelProvider,
  ModelResidency,
  ModelRuntimeBinding,
  ModelsStatus,
  NeuroAssessmentResponse,
  NeuroResidualStatus,
  ResidencyPolicy,
  ResourceEstimate,
  PreflightResult,
  ReleaseGateReport,
  ResearchClaim,
  ResearchConflict,
  ResearchCoverage,
  ResearchEvent,
  ResearchEvidence,
  ResearchPlan,
  ResearchProject,
  ResearchProjectCreate,
  ResearchReport,
  ResearchSource,
  ResearchBudgetCatalog,
  ResearchWorker,
  RouterConfig,
  SecurityAuditReport,
  SoakReport,
  SystemArchitectureEntry,
  TrainingCapabilities,
  TrainingCheckpoint,
  TrainingJob,
  TrainingJobCreatePayload,
  TrainingLogs,
  TrainingMetric,
  TrainingPlan,
  TrainingPreflightPayload,
  TrainingRecipe,
  VerificationReport,
  VerifiedCapability,
  CodingStatusResponse,
  CodingSession,
  CodingSessionDetail,
  CodingTurnResponse,
  CodingMission,
  CodingWorkspaceTreeResponse,
  ChatOptions,
  CapabilityListItem,
  SystemTelemetryResponse,
  McpCallRecord,
  McpServerPublic,
  McpToolRecord,
  MarketSimStatusResponse,
  MarketDataSource,
  MarketStrategy,
  MarketStrategyVersion,
  MarketSimRun,
  MarketSimLiveState,
  SettingsSnapshot,
  SettingState,
  SettingMutationResult,
  RuntimeEvent,
  EventsListResponse,
  OperatorCommandResult,
  PerformanceSnapshot,
  InferenceEfficiencySnapshot,
  ModuleSnapshot,
  KnowledgeDocument,
  KnowledgeChunk,
  KnowledgeSearchHit,
  MemoryCreatePayload,
  MemoryRecord,
  EvidenceRecord,
  WorkflowRecord,
  WorkflowCreatePayload,
  ScheduleRecord,
  ScheduleCreatePayload,
  JobRecord,
  TaskRecord,
  TaskSummary,
  TaskEvent,
  TaskSubtask,
  TaskNote,
  TaskDependency,
  TaskTimelineItem,
  TaskWorkloadEntry,
  TaskAgentActivity,
  TaskWeekdayCompletions,
  TaskCreatePayload,
  TaskPatchPayload,
  TaskQuickCapturePayload,
  TaskAutoPlanProposal,
  TaskListFilters,
} from "../types/api";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

function detailMessage(data: ApiErrorBody | null, status: number): string {
  if (!data?.detail) {
    return `Request failed (${status})`;
  }
  if (typeof data.detail === "string") {
    return data.detail;
  }
  if (Array.isArray(data.detail) && data.detail.length > 0) {
    return data.detail.map((item) => item.msg).join("; ");
  }
  if (typeof data.detail === "object" && data.detail !== null && "message" in data.detail) {
    const body = data.detail as { code?: string; message?: string };
    return body.code ? `${body.code}: ${body.message ?? ""}` : String(body.message ?? `Request failed (${status})`);
  }
  if (typeof data.detail === "object" && data.detail !== null && "error" in data.detail) {
    const body = data.detail as { error?: unknown; detail?: unknown; message?: string };
    if (typeof body.error === "string") {
      const msg =
        typeof body.detail === "string"
          ? body.detail
          : typeof body.message === "string"
            ? body.message
            : "";
      return msg ? `${body.error}: ${msg}` : body.error;
    }
    const nested = body.error as { code?: string; message?: string };
    if (nested?.message) {
      return nested.code ? `${nested.code}: ${nested.message}` : nested.message;
    }
  }
  return `Request failed (${status})`;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const isFormData = typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = new Headers(options.headers ?? undefined);
  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (isFormData) {
    // Browser must set multipart boundary — never force application/json.
    headers.delete("Content-Type");
  }

  const response = await fetch(path, {
    ...options,
    headers,
  });

  let data: ApiErrorBody | null = null;
  try {
    data = (await response.json()) as ApiErrorBody;
  } catch {
    data = null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, detailMessage(data, response.status));
  }

  return data as T;
}

async function requestBlob(path: string, options: RequestInit = {}): Promise<Blob> {
  const response = await fetch(path, { ...options });
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const data = (await response.json()) as ApiErrorBody;
      message = detailMessage(data, response.status);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new ApiError(response.status, message);
  }
  return response.blob();
}

export const api = {
  health(): Promise<HealthResponse> {
    return request<HealthResponse>("/api/health");
  },

  productTruth(): Promise<{ product_truth: HealthResponse["product_truth"] }> {
    return request<{ product_truth: HealthResponse["product_truth"] }>("/api/product/truth");
  },

  listMemory(opts?: {
    status?: string;
    kind?: string;
    limit?: number;
    conversation_id?: string;
    project_id?: string;
    scope?: string;
  }): Promise<{ memory: MemoryRecord[] }> {
    const params = new URLSearchParams();
    if (opts?.status) params.set("status", opts.status);
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.conversation_id) params.set("conversation_id", opts.conversation_id);
    if (opts?.project_id) params.set("project_id", opts.project_id);
    if (opts?.scope) params.set("scope", opts.scope);
    const q = params.toString();
    return request<{ memory: MemoryRecord[] }>(`/api/memory${q ? `?${q}` : ""}`);
  },

  createMemory(payload: MemoryCreatePayload): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>("/api/memory", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  searchMemory(opts: {
    q: string;
    limit?: number;
    conversation_id?: string;
    project_id?: string;
  }): Promise<{ memory: MemoryRecord[]; truth?: Record<string, boolean> }> {
    const params = new URLSearchParams();
    params.set("q", opts.q);
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.conversation_id) params.set("conversation_id", opts.conversation_id);
    if (opts.project_id) params.set("project_id", opts.project_id);
    return request<{ memory: MemoryRecord[]; truth?: Record<string, boolean> }>(
      `/api/memory/search?${params.toString()}`,
    );
  },

  getMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(`/api/memory/${encodeURIComponent(memoryId)}`);
  },

  archiveMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/archive`,
      { method: "POST" },
    );
  },

  revokeMemory(memoryId: string): Promise<{ memory: MemoryRecord }> {
    return request<{ memory: MemoryRecord }>(
      `/api/memory/${encodeURIComponent(memoryId)}/revoke`,
      { method: "POST" },
    );
  },

  metrics(): Promise<{ metrics: MetricsSnapshot }> {
    return request<{ metrics: MetricsSnapshot }>("/api/metrics");
  },

  listConversations(opts?: {
    q?: string;
    limit?: number;
  }): Promise<{ conversations: Conversation[] }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request<{ conversations: Conversation[] }>(`/api/conversations${q ? `?${q}` : ""}`);
  },

  createConversation(title = "New conversation"): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },

  getConversation(
    conversationId: string,
  ): Promise<{ conversation: Conversation; messages: Message[] }> {
    return request<{ conversation: Conversation; messages: Message[] }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
    );
  },

  updateConversation(
    conversationId: string,
    patch: { title?: string; pinned?: boolean },
  ): Promise<{ conversation: Conversation }> {
    return request<{ conversation: Conversation }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(patch),
      },
    );
  },

  deleteConversation(conversationId: string): Promise<{ deleted: boolean; id: string }> {
    return request<{ deleted: boolean; id: string }>(
      `/api/conversations/${encodeURIComponent(conversationId)}`,
      { method: "DELETE" },
    );
  },

  chat(message: string, options: ChatOptions = {}): Promise<ChatResponse> {
    return request<ChatResponse>("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        message,
        conversation_id: options.conversationId ?? null,
        ...(options.modelId ? { model_id: options.modelId } : {}),
        ...(options.preferredRole ? { preferred_role: options.preferredRole } : {}),
        ...(options.stream != null ? { stream: options.stream } : {}),
      }),
    });
  },

  /**
   * Stream chat via SSE when backend CHAT_STREAMING is ON.
   * Falls back to non-stream chat() when the response is JSON (feature off / degrade).
   */
  async chatStream(
    message: string,
    options: ChatOptions,
    handlers: {
      onMeta?: (data: Record<string, unknown>) => void;
      onToken?: (text: string, model?: string) => void;
      onDone?: (data: ChatResponse) => void;
      onError?: (detail: string) => void;
    },
  ): Promise<ChatResponse> {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "text/event-stream",
      },
      body: JSON.stringify({
        message,
        conversation_id: options.conversationId ?? null,
        stream: true,
        ...(options.modelId ? { model_id: options.modelId } : {}),
        ...(options.preferredRole ? { preferred_role: options.preferredRole } : {}),
      }),
    });

    const contentType = (response.headers.get("content-type") || "").toLowerCase();
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try {
        const body = (await response.json()) as ApiErrorBody;
        detail = detailMessage(body, response.status);
      } catch {
        /* ignore */
      }
      throw new ApiError(response.status, detail);
    }

    // Feature flag OFF → normal JSON response.
    if (!contentType.includes("text/event-stream")) {
      const data = (await response.json()) as ChatResponse;
      handlers.onDone?.(data);
      return data;
    }

    const reader = response.body?.getReader();
    if (!reader) {
      throw new ApiError(503, "Streaming response body missing");
    }
    const decoder = new TextDecoder();
    let buffer = "";
    let donePayload: ChatResponse | null = null;
    let eventName = "message";

    const flushBlock = (block: string) => {
      const lines = block.split("\n");
      let dataLines: string[] = [];
      for (const line of lines) {
        if (line.startsWith("event:")) {
          eventName = line.slice(6).trim();
        } else if (line.startsWith("data:")) {
          dataLines.push(line.slice(5).trimStart());
        }
      }
      if (!dataLines.length) return;
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(dataLines.join("\n")) as Record<string, unknown>;
      } catch {
        return;
      }
      if (eventName === "meta") {
        handlers.onMeta?.(parsed);
      } else if (eventName === "token") {
        const text = typeof parsed.text === "string" ? parsed.text : "";
        const model = typeof parsed.model === "string" ? parsed.model : undefined;
        if (text) handlers.onToken?.(text, model);
      } else if (eventName === "done") {
        donePayload = parsed as unknown as ChatResponse;
        handlers.onDone?.(donePayload);
      } else if (eventName === "error") {
        const detail =
          typeof parsed.detail === "string" ? parsed.detail : "stream error";
        handlers.onError?.(detail);
        throw new ApiError(503, detail);
      }
      eventName = "message";
    };

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf("\n\n");
      while (sep >= 0) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        flushBlock(block);
        sep = buffer.indexOf("\n\n");
      }
    }
    if (buffer.trim()) {
      flushBlock(buffer);
    }
    if (!donePayload) {
      throw new ApiError(503, "Stream ended without done event");
    }
    return donePayload;
  },

  listApprovals(status?: string): Promise<{ approvals: unknown[] }> {
    const query = status ? `?status=${encodeURIComponent(status)}` : "";
    return request<{ approvals: unknown[] }>(`/api/approvals${query}`);
  },

  approveApproval(approvalId: string, reason?: string): Promise<{ approval: unknown }> {
    return request(`/api/approvals/${encodeURIComponent(approvalId)}/approve`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    });
  },

  denyApproval(approvalId: string, reason?: string): Promise<{ approval: unknown }> {
    return request(`/api/approvals/${encodeURIComponent(approvalId)}/deny`, {
      method: "POST",
      body: JSON.stringify({ reason: reason ?? null }),
    });
  },

  listJobs(): Promise<{ jobs: JobRecord[] }> {
    return request<{ jobs: JobRecord[] }>("/api/jobs");
  },

  releaseGates(): Promise<{ report: ReleaseGateReport }> {
    return request<{ report: ReleaseGateReport }>("/api/release/gates");
  },

  securityAudit(): Promise<{ report: SecurityAuditReport }> {
    return request<{ report: SecurityAuditReport }>("/api/security/audit");
  },

  masterGates(): Promise<{ report: MasterGateReport }> {
    return request<{ report: MasterGateReport }>("/api/master/gates");
  },

  listVerificationReports(limit = 20): Promise<{ reports: VerificationReport[] }> {
    return request<{ reports: VerificationReport[] }>(
      `/api/verification/reports?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listBackups(): Promise<{ backups: BackupManifest[] }> {
    return request<{ backups: BackupManifest[] }>("/api/backup");
  },

  createBackup(note?: string): Promise<{ backup: BackupManifest }> {
    return request<{ backup: BackupManifest }>("/api/backup", {
      method: "POST",
      body: JSON.stringify({ note: note ?? null }),
    });
  },

  telemetry(): Promise<{ events: RuntimeEvent[]; snapshot?: unknown; latest_sequence?: number }> {
    return request<{ events: RuntimeEvent[]; snapshot?: unknown; latest_sequence?: number }>("/api/telemetry");
  },

  listEvents(opts?: {
    limit?: number;
    before?: number;
    after?: number;
    level?: string;
    category?: string;
    subsystem?: string;
    source?: string;
    correlation_id?: string;
    q?: string;
    since_ms?: number;
    until_ms?: number;
  }): Promise<EventsListResponse> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.before != null) params.set("before", String(opts.before));
    if (opts?.after != null) params.set("after", String(opts.after));
    if (opts?.level) params.set("level", opts.level);
    if (opts?.category) params.set("category", opts.category);
    if (opts?.subsystem) params.set("subsystem", opts.subsystem);
    if (opts?.source) params.set("source", opts.source);
    if (opts?.correlation_id) params.set("correlation_id", opts.correlation_id);
    if (opts?.q) params.set("q", opts.q);
    if (opts?.since_ms != null) params.set("since_ms", String(opts.since_ms));
    if (opts?.until_ms != null) params.set("until_ms", String(opts.until_ms));
    const q = params.toString();
    return request<EventsListResponse>(`/api/events${q ? `?${q}` : ""}`);
  },

  listOperatorCommands(): Promise<{ commands: Array<{ name: string; help: string }> }> {
    return request("/api/console/commands");
  },

  runOperatorCommand(command: string): Promise<{ result: OperatorCommandResult }> {
    return request("/api/console/command", {
      method: "POST",
      body: JSON.stringify({ command }),
    });
  },

  performanceSnapshot(): Promise<PerformanceSnapshot> {
    return request<PerformanceSnapshot>("/api/performance/snapshot");
  },

  inferenceEfficiency(): Promise<InferenceEfficiencySnapshot> {
    return request<InferenceEfficiencySnapshot>("/api/inference/efficiency");
  },

  clearInferenceCaches(payload?: {
    cacheType?: string;
    projectScope?: string;
  }): Promise<{ cleared: Record<string, number>; truth?: Record<string, boolean> }> {
    return request("/api/inference/efficiency/cache/clear", {
      method: "POST",
      body: JSON.stringify({
        cacheType: payload?.cacheType ?? null,
        projectScope: payload?.projectScope ?? null,
      }),
    });
  },

  tokenizationStatus(modelId?: string): Promise<{
    mode: string;
    boundTokenizerId?: string | null;
    cache: Record<string, unknown>;
    modelId?: string | null;
    truth?: Record<string, boolean>;
  }> {
    const q = modelId ? `?model_id=${encodeURIComponent(modelId)}` : "";
    return request(`/api/inference/tokenization/status${q}`);
  },

  performanceSeries(
    name: string,
    opts?: { since_ms?: number; until_ms?: number; limit?: number },
  ): Promise<{ name: string; points: Array<{ ts_ms: number; value: number }> }> {
    const params = new URLSearchParams({ name });
    if (opts?.since_ms != null) params.set("since_ms", String(opts.since_ms));
    if (opts?.until_ms != null) params.set("until_ms", String(opts.until_ms));
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    return request(`/api/performance/series?${params.toString()}`);
  },

  brainAtlasConfidence(limit = 100): Promise<{ available: boolean; records: Array<{ atlas_id: string; confidence: number; last_revised_at?: string }> }> {
    return request(`/api/knowledge/atlas?limit=${Math.max(1, Math.min(100, limit))}`);
  },

  listModules(): Promise<ModuleSnapshot> {
    return request<ModuleSnapshot>("/api/modules");
  },

  discoverModules(): Promise<{ discovered: unknown[]; snapshot: ModuleSnapshot }> {
    return request("/api/modules/discover", { method: "POST" });
  },

  executeModule(
    moduleId: string,
    operation: string,
    arguments_: Record<string, unknown> = {},
  ): Promise<{ result: unknown }> {
    return request(`/api/modules/${encodeURIComponent(moduleId)}/execute`, {
      method: "POST",
      body: JSON.stringify({ operation, arguments: arguments_ }),
    });
  },

  listWorkflows(limit = 100): Promise<{ workflows: WorkflowRecord[] }> {
    return request(`/api/workflows?limit=${encodeURIComponent(String(limit))}`);
  },

  createWorkflow(payload: WorkflowCreatePayload): Promise<{ workflow: WorkflowRecord }> {
    return request("/api/workflows", { method: "POST", body: JSON.stringify(payload) });
  },

  getWorkflow(workflowId: string): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}`);
  },

  runWorkflow(workflowId: string): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/run`, { method: "POST" });
  },

  cancelWorkflow(workflowId: string): Promise<{ workflow: WorkflowRecord }> {
    return request(`/api/workflows/${encodeURIComponent(workflowId)}/cancel`, { method: "POST" });
  },

  listSchedules(opts?: {
    status?: string;
    limit?: number;
  }): Promise<{ schedules: ScheduleRecord[]; telemetry?: Record<string, unknown> }> {
    const params = new URLSearchParams();
    if (opts?.status) params.set("status", opts.status);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/schedules${q ? `?${q}` : ""}`);
  },

  createSchedule(payload: ScheduleCreatePayload): Promise<{ schedule: ScheduleRecord }> {
    return request("/api/schedules", { method: "POST", body: JSON.stringify(payload) });
  },

  getSchedule(scheduleId: string): Promise<{ schedule: ScheduleRecord }> {
    return request(`/api/schedules/${encodeURIComponent(scheduleId)}`);
  },

  pauseSchedule(scheduleId: string): Promise<{ schedule: ScheduleRecord }> {
    return request(`/api/schedules/${encodeURIComponent(scheduleId)}/pause`, { method: "POST" });
  },

  resumeSchedule(scheduleId: string): Promise<{ schedule: ScheduleRecord }> {
    return request(`/api/schedules/${encodeURIComponent(scheduleId)}/resume`, { method: "POST" });
  },

  listEvidence(opts?: {
    status?: string;
    run_id?: string;
    limit?: number;
  }): Promise<{ evidence: EvidenceRecord[] }> {
    const params = new URLSearchParams();
    if (opts?.status) params.set("status", opts.status);
    if (opts?.run_id) params.set("run_id", opts.run_id);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/evidence${q ? `?${q}` : ""}`);
  },

  getEvidence(evidenceId: string): Promise<{ evidence: EvidenceRecord }> {
    return request(`/api/evidence/${encodeURIComponent(evidenceId)}`);
  },

  verifyEvidence(evidenceId: string): Promise<{ evidence: EvidenceRecord }> {
    return request(`/api/evidence/${encodeURIComponent(evidenceId)}/verify`, { method: "POST" });
  },

  listKnowledgeDocuments(): Promise<{ documents: KnowledgeDocument[] }> {
    return request("/api/knowledge");
  },

  getKnowledgeDocument(documentId: string): Promise<{ document: KnowledgeDocument; chunks: KnowledgeChunk[] }> {
    return request(`/api/knowledge/${encodeURIComponent(documentId)}`);
  },

  createKnowledgeDocument(payload: {
    id?: string;
    title: string;
    content: string;
    source?: string;
  }): Promise<{ document: KnowledgeDocument }> {
    return request("/api/knowledge", { method: "POST", body: JSON.stringify(payload) });
  },

  deleteKnowledgeDocument(documentId: string): Promise<{ deleted: boolean; id: string }> {
    return request(`/api/knowledge/${encodeURIComponent(documentId)}`, { method: "DELETE" });
  },

  searchKnowledge(opts: {
    q: string;
    limit?: number;
    source?: string;
  }): Promise<{ hits: KnowledgeSearchHit[]; documents: KnowledgeDocument[] }> {
    const params = new URLSearchParams({ q: opts.q });
    if (opts.limit != null) params.set("limit", String(opts.limit));
    if (opts.source) params.set("source", opts.source);
    return request(`/api/knowledge/search?${params.toString()}`);
  },

  listFunctions(): Promise<{ functions: unknown[]; loaded?: unknown[]; telemetry?: unknown }> {
    return request("/api/functions");
  },

  neuroAssess(text: string): Promise<NeuroAssessmentResponse> {
    return request<NeuroAssessmentResponse>("/api/neuro/assess", {
      method: "POST",
      body: JSON.stringify({ text }),
    });
  },

  neuroResidual(): Promise<NeuroResidualStatus> {
    return request<NeuroResidualStatus>("/api/neuro/residual");
  },

  neuroStatus(): Promise<{
    enabled: boolean;
    residual: Record<string, unknown>;
    contrastive: Record<string, unknown>;
    streaming: Record<string, unknown>;
    truth?: Record<string, boolean>;
  }> {
    return request("/api/neuro/status");
  },

  neuroAbsorb(limit = 50): Promise<{ ingested: number; truth?: Record<string, boolean> }> {
    return request<{ ingested: number; truth?: Record<string, boolean> }>("/api/neuro/absorb", {
      method: "POST",
      body: JSON.stringify({ limit }),
    });
  },

  neuroSoak(iterations = 3, mode: "mini" | "long" = "mini"): Promise<{ report: SoakReport }> {
    return request<{ report: SoakReport }>("/api/neuro/soak", {
      method: "POST",
      body: JSON.stringify({ iterations, mode }),
    });
  },

  neuroResidualOrchestrate(payload: {
    text: string;
    complexity?: string;
    run_forward?: boolean;
    mode?: string;
  }): Promise<{ report: unknown }> {
    return request<{ report: unknown }>("/api/neuro/residual/orchestrate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  neuroEvaluation(): Promise<{ report: unknown }> {
    return request<{ report: unknown }>("/api/evaluation/neuro", { method: "POST" });
  },

  listTrainingRecipes(): Promise<{ recipes: TrainingRecipe[] }> {
    return request<{ recipes: TrainingRecipe[] }>("/api/training/recipes");
  },

  listModels(): Promise<{
    models: ModelDescriptor[];
    status: ModelsStatus;
    discoveryLatencyMs?: number | null;
  }> {
    return request("/api/models");
  },

  modelsStatus(): Promise<{
    status: ModelsStatus;
    telemetry: Record<string, unknown>;
  }> {
    return request("/api/models/status");
  },

  refreshModels(): Promise<{
    summary: unknown;
    models: ModelDescriptor[];
    status: ModelsStatus;
  }> {
    return request("/api/models/refresh", { method: "POST" });
  },

  getModel(modelId: string): Promise<{
    model: ModelDescriptor;
    profile: ModelProfile;
    capabilities: VerifiedCapability[];
    provider: ModelProvider | null;
    preflight: Record<string, unknown>;
    runtimeBinding?: ModelRuntimeBinding | null;
    residency?: ModelResidency | null;
    residencyPolicy?: ResidencyPolicy | null;
    resourceEstimate?: ResourceEstimate | null;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}`);
  },

  getModelResidency(modelId: string): Promise<{
    residency: ModelResidency;
    policy: ResidencyPolicy;
    runtimeBinding: ModelRuntimeBinding;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/residency`);
  },

  saveResidencyPolicy(
    modelId: string,
    policy: Partial<ResidencyPolicy>,
  ): Promise<{ policy: ResidencyPolicy }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/residency-policy`, {
      method: "PUT",
      body: JSON.stringify(policy),
    });
  },

  getModelProfile(modelId: string): Promise<{ profile: ModelProfile }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`);
  },

  saveModelProfile(
    modelId: string,
    profile: Partial<ModelProfile> & { activate?: boolean },
  ): Promise<{ profile: ModelProfile; activeModelId: string | null }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/profile`, {
      method: "PUT",
      body: JSON.stringify(profile),
    });
  },

  activateModel(modelId: string): Promise<{
    model: ModelDescriptor;
    activeModelId: string;
  }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/activate`, { method: "POST" });
  },

  loadModel(modelId: string, options: Record<string, unknown> = {}): Promise<unknown> {
    return request(`/api/models/${encodeURIComponent(modelId)}/load`, {
      method: "POST",
      body: JSON.stringify(options),
    });
  },

  unloadModel(modelId: string): Promise<unknown> {
    return request(`/api/models/${encodeURIComponent(modelId)}/unload`, { method: "POST" });
  },

  deleteModel(modelId: string): Promise<{ deleted: boolean }> {
    return request(`/api/models/${encodeURIComponent(modelId)}`, { method: "DELETE" });
  },

  probeModel(modelId: string, capabilities?: string[]): Promise<{ results: VerifiedCapability[] }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/probe`, {
      method: "POST",
      body: JSON.stringify({ capabilities }),
    });
  },

  benchmarkModel(modelId: string): Promise<{ benchmark: Record<string, unknown> }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/benchmark`, { method: "POST" });
  },

  testModel(
    modelId: string,
    payload: { prompt: string; maxTokens?: number; stream?: boolean },
  ): Promise<{ result: ModelInferenceTestResult }> {
    return request(`/api/models/${encodeURIComponent(modelId)}/test`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getGateway(): Promise<{ gateway: GatewaySnapshot }> {
    return request("/api/models/gateway");
  },

  getRouter(): Promise<{ router: RouterConfig }> {
    return request("/api/models/router");
  },

  saveRouter(config: Partial<RouterConfig>): Promise<{ router: RouterConfig }> {
    return request("/api/models/router", {
      method: "PUT",
      body: JSON.stringify(config),
    });
  },

  listModelProviders(): Promise<{ providers: ModelProvider[] }> {
    return request("/api/model-providers");
  },

  createModelProvider(payload: Record<string, unknown>): Promise<{
    provider: ModelProvider;
  }> {
    return request("/api/model-providers", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateModelProvider(
    providerId: string,
    payload: Record<string, unknown>,
  ): Promise<{ provider: ModelProvider }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  deleteModelProvider(providerId: string): Promise<{ deleted: boolean }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}`, { method: "DELETE" });
  },

  testModelProvider(providerId: string): Promise<{
    connected: boolean;
    providerId: string;
    provider: string;
    modelsFound: number;
    latencyMs: number | null;
    health: string;
    error: string | null;
  }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}/test`, {
      method: "POST",
    });
  },

  importModel(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
    return request("/api/models/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  downloadModel(payload: Record<string, unknown>): Promise<{
    download: DownloadJob;
  }> {
    return request("/api/models/download", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listModelDownloads(): Promise<{ downloads: DownloadJob[] }> {
    return request("/api/model-downloads");
  },

  cancelModelDownload(downloadId: string): Promise<{ download: DownloadJob }> {
    return request(`/api/model-downloads/${encodeURIComponent(downloadId)}/cancel`, {
      method: "POST",
    });
  },

  getModelDownload(downloadId: string): Promise<{ download: DownloadJob }> {
    return request(`/api/model-downloads/${encodeURIComponent(downloadId)}`);
  },

  getModelProvider(providerId: string): Promise<{ provider: ModelProvider }> {
    return request(`/api/model-providers/${encodeURIComponent(providerId)}`);
  },

  listServingWorkers(): Promise<{ workers: Record<string, unknown>[]; truth?: Record<string, boolean> }> {
    return request("/api/models/serving/workers");
  },

  reconcileServingWorkers(): Promise<{
    changed: Record<string, unknown>[];
    workers: Record<string, unknown>[];
    truth?: Record<string, boolean>;
  }> {
    return request("/api/models/serving/reconcile", { method: "POST" });
  },

  listModelAudit(limit = 50): Promise<{
    events: Array<{
      id: number | string;
      createdAt: string;
      actor: string;
      action: string;
      detail: unknown;
    }>;
  }> {
    return request(`/api/models/audit?limit=${encodeURIComponent(String(limit))}`);
  },

  listRouteDecisions(limit = 50): Promise<{
    decisions: Record<string, unknown>[];
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/models/router/decisions?limit=${encodeURIComponent(String(limit))}`);
  },

  /* ---------- Datasets ---------- */

  listDatasets(limit = 100): Promise<{ datasets: DatasetRecord[] }> {
    return request(`/api/datasets?limit=${encodeURIComponent(String(limit))}`);
  },

  createDataset(payload: {
    name: string;
    description?: string;
    license?: string | null;
    metadata?: Record<string, unknown>;
  }): Promise<{ dataset: DatasetRecord }> {
    return request("/api/datasets", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  uploadDataset(form: FormData): Promise<{ job: DatasetJob; bytes: number; filename: string }> {
    return request("/api/datasets/upload", {
      method: "POST",
      body: form,
    });
  },

  getDataset(datasetId: string): Promise<{
    dataset: DatasetRecord;
    versions: DatasetVersion[];
    files: DatasetFile[];
    indexes: DatasetIndex[];
  }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}`);
  },

  deleteDataset(datasetId: string): Promise<{ deleted: boolean; datasetId: string }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}`, { method: "DELETE" });
  },

  inspectDatasetPath(path: string): Promise<{ inspection: Record<string, unknown> }> {
    return request("/api/datasets/inspect", {
      method: "POST",
      body: JSON.stringify({ path }),
    });
  },

  importDatasetLocal(payload: {
    path: string;
    name?: string | null;
    description?: string;
    license?: string | null;
    materialize?: boolean;
    datasetId?: string | null;
  }): Promise<{ job: DatasetJob }> {
    return request("/api/datasets/import/local", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  importDatasetHuggingFace(payload: {
    repositoryId: string;
    filename?: string | null;
    revision?: string;
    name?: string | null;
    description?: string;
    license?: string | null;
    token?: string | null;
    materialize?: boolean;
    datasetId?: string | null;
  }): Promise<{ job: DatasetJob }> {
    return request("/api/datasets/import/huggingface", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listHuggingFaceDatasetFiles(payload: {
    repositoryId: string;
    revision?: string;
    token?: string | null;
  }): Promise<{ files: HfDatasetFile[] }> {
    return request("/api/datasets/huggingface/list", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listDatasetVersions(datasetId: string): Promise<{ versions: DatasetVersion[] }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/versions`);
  },

  getDatasetVersion(versionId: string): Promise<{ version: DatasetVersion }> {
    return request(`/api/datasets/versions/${encodeURIComponent(versionId)}`);
  },

  previewDatasetVersion(
    versionId: string,
    limit = 20,
  ): Promise<{ rows: DatasetPreviewRow[]; limit: number }> {
    return request(
      `/api/datasets/versions/${encodeURIComponent(versionId)}/preview?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  scanDatasetPii(versionId: string): Promise<{ pii: Record<string, unknown> }> {
    return request(`/api/datasets/versions/${encodeURIComponent(versionId)}/pii`);
  },

  materializeDataset(datasetId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/materialize`, {
      method: "POST",
    });
  },

  validateDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/validate`,
      { method: "POST" },
    );
  },

  dedupeDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/dedupe`,
      { method: "POST" },
    );
  },

  transformDatasetVersion(
    datasetId: string,
    versionId: string,
    transforms: Record<string, unknown>[] = [],
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/transform`,
      { method: "POST", body: JSON.stringify({ transforms }) },
    );
  },

  splitDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { seed?: number; trainRatio?: number; valRatio?: number; testRatio?: number } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/split`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  tokenizeStatsDatasetVersion(datasetId: string, versionId: string): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/tokenize-stats`,
      { method: "POST" },
    );
  },

  exportDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: { split?: string | null } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/export`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  indexDatasetVersion(
    datasetId: string,
    versionId: string,
    payload: {
      scope?: string;
      maxRecords?: number | null;
      offlineOnly?: boolean;
      sourceFingerprint?: string | null;
      rebuild?: boolean;
    } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/index`,
      { method: "POST", body: JSON.stringify(payload) },
    );
  },

  duplicateDataset(
    datasetId: string,
    payload: { versionId?: string | null; name?: string | null } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/duplicate`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  downloadDatasetExport(datasetId: string, exportVersionId: string): Promise<Blob> {
    return requestBlob(
      `/api/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(exportVersionId)}/download`,
    );
  },

  listDatasetJobs(datasetId?: string, limit = 100): Promise<{ jobs: DatasetJob[] }> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (datasetId) params.set("datasetId", datasetId);
    return request(`/api/datasets/jobs?${params.toString()}`);
  },

  getDatasetJob(jobId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/jobs/${encodeURIComponent(jobId)}`);
  },

  cancelDatasetJob(jobId: string): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },

  retryDatasetJob(jobId: string, resume = true): Promise<{ job: DatasetJob }> {
    const params = new URLSearchParams({ resume: resume ? "true" : "false" });
    return request(`/api/datasets/jobs/${encodeURIComponent(jobId)}/retry?${params.toString()}`, {
      method: "POST",
    });
  },

  datasetLearningActivity(limit = 40): Promise<{
    agentSystemKey?: string;
    agentName?: string;
    activeCount: number;
    active: DatasetJob[];
    recent: DatasetJob[];
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/datasets/learning/activity?limit=${encodeURIComponent(String(limit))}`);
  },

  reconcileDatasetSidecars(maxFiles = 2000): Promise<{
    scanned: number;
    created: number;
    updated: number;
    skippedTombstone: number;
    conflicts: Array<Record<string, unknown>>;
    restoredDatasetIds: string[];
    truth?: Record<string, boolean>;
  }> {
    return request(
      `/api/datasets/sidecars/reconcile?maxFiles=${encodeURIComponent(String(maxFiles))}`,
      { method: "POST" },
    );
  },

  processDatasetJobs(maxJobs = 10): Promise<{ processed: DatasetJob[] }> {
    return request(`/api/datasets/jobs/process?maxJobs=${encodeURIComponent(String(maxJobs))}`, {
      method: "POST",
    });
  },

  reconcileDatasetJobs(): Promise<{ updated: DatasetJob[] }> {
    return request("/api/datasets/jobs/reconcile", { method: "POST" });
  },

  discoverOfflineDatasets(maxFiles = 500): Promise<{
    roots: Array<{ id: string; path: string }>;
    sources: Array<Record<string, unknown>>;
    count: number;
    dataRoot?: string;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/datasets/offline/discover?maxFiles=${encodeURIComponent(String(maxFiles))}`);
  },

  refreshDatasetLibrary(maxFiles = 500): Promise<{
    created: number;
    updated: number;
    missingSources: number;
    discovered: number;
    registeredDatasetIds: string[];
    roots: Array<{ id: string; path: string }>;
    dataRoot?: string;
    datasets: DatasetRecord[];
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/datasets/library/refresh?maxFiles=${encodeURIComponent(String(maxFiles))}`, {
      method: "POST",
    });
  },

  listLearnedDatasets(limit = 100): Promise<{
    datasets: DatasetRecord[];
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/datasets/learned?limit=${encodeURIComponent(String(limit))}`);
  },

  listOfflineBrainIndexes(limit = 100): Promise<{ indexes: DatasetIndex[] }> {
    return request(`/api/datasets/offline/indexes?limit=${encodeURIComponent(String(limit))}`);
  },

  offlineBrainPreflight(payload: {
    datasetId: string;
    versionId: string;
    offlineOnly?: boolean;
  }): Promise<{ preflight: Record<string, unknown> }> {
    return request("/api/datasets/offline/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /** @deprecated Prefer learnDataset — offline index is Brain ingestion. */
  enqueueOfflineBrainIndex(payload: {
    datasetId: string;
    versionId?: string | null;
    scope?: string;
    maxRecords?: number | null;
    sourceFingerprint?: string | null;
    rebuild?: boolean;
  }): Promise<{ job: DatasetJob }> {
    return request("/api/datasets/offline/index", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  learnDataset(
    datasetId: string,
    payload: {
      versionId?: string | null;
      scope?: string;
      maxRecords?: number | null;
      sourceFingerprint?: string | null;
      rebuild?: boolean;
      offlineOnly?: boolean;
    } = {},
  ): Promise<{ job: DatasetJob }> {
    return request(`/api/datasets/${encodeURIComponent(datasetId)}/learn`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /* ---------- Training ---------- */

  trainingCapabilities(): Promise<{ capabilities: TrainingCapabilities }> {
    return request("/api/training/capabilities");
  },

  trainingHardware(): Promise<{ hardware: HardwareSnapshot }> {
    return request("/api/training/hardware");
  },

  trainingPreflight(payload: TrainingPreflightPayload): Promise<{ preflight: PreflightResult }> {
    return request("/api/training/preflight", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  trainingPlan(payload: TrainingPreflightPayload): Promise<{ plan: TrainingPlan }> {
    return request("/api/training/plan", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listTrainingJobs(status?: string, limit = 100): Promise<{ jobs: TrainingJob[] }> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (status) params.set("status", status);
    return request(`/api/training/jobs?${params.toString()}`);
  },

  createTrainingJob(payload: TrainingJobCreatePayload): Promise<{ job: TrainingJob }> {
    return request("/api/training/jobs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}`);
  },

  startTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/start`, { method: "POST" });
  },

  cancelTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  },

  resumeTrainingJob(jobId: string): Promise<{ job: TrainingJob }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/resume`, { method: "POST" });
  },

  listTrainingCheckpoints(jobId: string): Promise<{ checkpoints: TrainingCheckpoint[] }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/checkpoints`);
  },

  listTrainingMetrics(jobId: string, limit = 500): Promise<{ metrics: TrainingMetric[] }> {
    return request(
      `/api/training/jobs/${encodeURIComponent(jobId)}/metrics?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  getTrainingLogs(jobId: string): Promise<TrainingLogs> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/logs`);
  },

  evaluateTrainingJob(jobId: string): Promise<{ evaluation: Record<string, unknown> }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/evaluate`, { method: "POST" });
  },

  exportTrainingJob(jobId: string): Promise<{ export: Record<string, unknown> }> {
    return request(`/api/training/jobs/${encodeURIComponent(jobId)}/export`, { method: "POST" });
  },

  reconcileTrainingJobs(): Promise<{ reconciled: number }> {
    return request("/api/training/reconcile", { method: "POST" });
  },

  /* ---------- Research ---------- */

  researchBudgets(): Promise<ResearchBudgetCatalog> {
    return request("/api/research/budgets");
  },

  listResearchProjects(limit = 100): Promise<{ projects: ResearchProject[] }> {
    return request(`/api/research?limit=${encodeURIComponent(String(limit))}`);
  },

  createResearchProject(payload: ResearchProjectCreate): Promise<{ project: ResearchProject }> {
    return request("/api/research", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}`);
  },

  updateResearchProject(
    projectId: string,
    payload: Partial<ResearchProjectCreate>,
  ): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    });
  },

  planResearchProject(
    projectId: string,
    payload: Record<string, unknown> = {},
  ): Promise<{ project: ResearchProject; plan: ResearchPlan | null }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/plan`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  runResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/run`, { method: "POST" });
  },

  cancelResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/cancel`, { method: "POST" });
  },

  resumeResearchProject(projectId: string): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/resume`, { method: "POST" });
  },

  deepenResearchProject(
    projectId: string,
    extraRounds = 1,
  ): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/deepen`, {
      method: "POST",
      body: JSON.stringify({ extraRounds }),
    });
  },

  listResearchWorkers(projectId: string): Promise<{ workers: ResearchWorker[] }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/workers`);
  },

  listResearchEvents(projectId: string, limit = 200): Promise<{ events: ResearchEvent[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/events?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchSources(projectId: string, limit = 200): Promise<{ sources: ResearchSource[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  uploadResearchSource(
    projectId: string,
    file: File,
  ): Promise<{
    source: ResearchSource;
    source_id?: string;
    job_id?: string | null;
    status?: string;
    source_type?: string;
    filename?: string;
    extracted_chars: number;
    page_count?: number | null;
    progress?: import("../types/api").SourceIngestionProgress;
  }> {
    const body = new FormData();
    body.append("file", file);
    return request(`/api/research/${encodeURIComponent(projectId)}/sources/upload`, {
      method: "POST",
      body,
    });
  },

  getSourceIngestionStatus(
    projectId: string,
    sourceId: string,
  ): Promise<{ source: ResearchSource; progress?: import("../types/api").SourceIngestionProgress }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/ingestion`,
    );
  },

  listSourceIngestionChildren(
    projectId: string,
    sourceId: string,
    opts?: { offset?: number; limit?: number; outcome?: string },
  ): Promise<{
    source_id: string;
    offset: number;
    limit: number;
    total: number;
    members: import("../types/api").SourceIngestionMember[];
    counts?: Record<string, number>;
  }> {
    const q = new URLSearchParams();
    if (opts?.offset != null) q.set("offset", String(opts.offset));
    if (opts?.limit != null) q.set("limit", String(opts.limit));
    if (opts?.outcome) q.set("outcome", opts.outcome);
    const qs = q.toString();
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/children${qs ? `?${qs}` : ""}`,
    );
  },

  cancelSourceIngestion(projectId: string, sourceId: string): Promise<{ progress: import("../types/api").SourceIngestionProgress }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/ingestion/cancel`,
      { method: "POST" },
    );
  },

  retrySourceIngestion(
    projectId: string,
    sourceId: string,
    failedOnly = true,
  ): Promise<{ source_id: string; job_id?: string | null; status?: string; progress?: import("../types/api").SourceIngestionProgress }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/ingestion/retry?failed_only=${failedOnly ? "true" : "false"}`,
      { method: "POST" },
    );
  },

  retrySourceIngestionBrain(
    projectId: string,
    sourceId: string,
  ): Promise<Record<string, unknown>> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/ingestion/brain-retry`,
      { method: "POST" },
    );
  },

  addResearchUrlSource(projectId: string, url: string): Promise<{ source: ResearchSource }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/sources/url`, {
      method: "POST",
      body: JSON.stringify({ url }),
    });
  },

  connectResearchDataset(
    projectId: string,
    payload: {
      datasetId: string;
      versionId?: string | null;
      indexed?: boolean | null;
      label?: string | null;
    },
  ): Promise<{ project: ResearchProject }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/datasets/connect`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  retryResearchBrainSync(
    projectId: string,
    sourceId: string,
  ): Promise<{ source: ResearchSource }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/sources/${encodeURIComponent(sourceId)}/brain-retry`,
      { method: "POST" },
    );
  },

  listResearchEvidence(projectId: string, limit = 500): Promise<{ evidence: ResearchEvidence[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/evidence?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchClaims(projectId: string, limit = 500): Promise<{ claims: ResearchClaim[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/claims?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  listResearchConflicts(
    projectId: string,
    limit = 200,
  ): Promise<{ conflicts: ResearchConflict[] }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/conflicts?limit=${encodeURIComponent(String(limit))}`,
    );
  },

  getResearchCoverage(projectId: string): Promise<{ coverage: ResearchCoverage }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/coverage`);
  },

  getResearchGaps(projectId: string): Promise<{ gaps: Array<Record<string, unknown>> }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/gaps`);
  },

  getResearchSourceAssessments(
    projectId: string,
  ): Promise<{ assessments: Array<Record<string, unknown>> }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/source-assessments`);
  },

  getResearchCitationAudit(
    projectId: string,
  ): Promise<{ audit: Record<string, unknown> }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/citation-audit`);
  },

  getResearchQuality(
    projectId: string,
  ): Promise<{ quality: Record<string, unknown> }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/quality`);
  },

  getResearchPlanHistory(
    projectId: string,
  ): Promise<{ history: Array<Record<string, unknown>> }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/plan-history`);
  },

  getResearchReport(projectId: string): Promise<{ report: ResearchReport }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/report`);
  },

  regenerateResearchReport(projectId: string): Promise<{ report: ResearchReport }> {
    return request(`/api/research/${encodeURIComponent(projectId)}/report`, { method: "POST" });
  },

  exportResearchProject(
    projectId: string,
    format: "markdown" | "md" | "html" | "json" = "markdown",
  ): Promise<{ export: Record<string, unknown> }> {
    return request(
      `/api/research/${encodeURIComponent(projectId)}/export?format=${encodeURIComponent(format)}`,
    );
  },

  /* ---------- Coding Agent ---------- */

  codingStatus(): Promise<CodingStatusResponse> {
    return request("/api/coding/status");
  },

  listCodingSessions(limit = 50): Promise<{ sessions: CodingSession[] }> {
    return request(`/api/coding/sessions?limit=${encodeURIComponent(String(limit))}`);
  },

  createCodingSession(payload: {
    goal: string;
    mission?: CodingMission;
    workspaceRoot?: string;
    modelId?: string;
    conversationId?: string;
    title?: string;
  }): Promise<{ session: CodingSession }> {
    return request("/api/coding/sessions", {
      method: "POST",
      body: JSON.stringify({
        goal: payload.goal,
        ...(payload.mission ? { mission: payload.mission } : {}),
        ...(payload.workspaceRoot ? { workspaceRoot: payload.workspaceRoot } : {}),
        ...(payload.modelId ? { modelId: payload.modelId } : {}),
        ...(payload.conversationId ? { conversationId: payload.conversationId } : {}),
        ...(payload.title ? { title: payload.title } : {}),
      }),
    });
  },

  getCodingSession(sessionId: string): Promise<CodingSessionDetail> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}`);
  },

  codingTurn(
    sessionId: string,
    payload: { message?: string; approvalId?: string; capabilityId?: string } = {},
  ): Promise<CodingTurnResponse> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}/turn`, {
      method: "POST",
      body: JSON.stringify({
        ...(payload.message != null ? { message: payload.message } : {}),
        ...(payload.approvalId ? { approvalId: payload.approvalId } : {}),
        ...(payload.capabilityId ? { capabilityId: payload.capabilityId } : {}),
      }),
    });
  },

  cancelCodingSession(sessionId: string): Promise<{ session: CodingSession }> {
    return request(`/api/coding/sessions/${encodeURIComponent(sessionId)}/cancel`, {
      method: "POST",
    });
  },

  codingWorkspaceTree(opts?: {
    path?: string;
    recursive?: boolean;
    sessionId?: string;
  }): Promise<CodingWorkspaceTreeResponse> {
    const params = new URLSearchParams();
    if (opts?.path) params.set("path", opts.path);
    if (opts?.recursive != null) params.set("recursive", String(opts.recursive));
    if (opts?.sessionId) params.set("session_id", opts.sessionId);
    const q = params.toString();
    return request(`/api/coding/workspace/tree${q ? `?${q}` : ""}`);
  },

  systemTelemetry(): Promise<SystemTelemetryResponse> {
    return request<SystemTelemetryResponse>("/api/system/telemetry");
  },

  listCapabilities(opts?: {
    q?: string;
    limit?: number;
  }): Promise<{ capabilities: CapabilityListItem[] }> {
    const params = new URLSearchParams();
    if (opts?.q) params.set("q", opts.q);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request<{ capabilities: CapabilityListItem[] }>(`/api/capabilities${q ? `?${q}` : ""}`);
  },

  executeCapability(
    capabilityId: string,
    arguments_: Record<string, unknown> = {},
  ): Promise<{ result: unknown }> {
    return request(`/api/capabilities/${encodeURIComponent(capabilityId)}/execute`, {
      method: "POST",
      body: JSON.stringify({ arguments: arguments_, requested_by: "ui" }),
    });
  },

  mcpServers(): Promise<{ servers: McpServerPublic[]; feature_enabled: boolean }> {
    return request("/api/mcp/servers");
  },

  mcpCreateServer(payload: Record<string, unknown>): Promise<{ server: McpServerPublic }> {
    return request("/api/mcp/servers", { method: "POST", body: JSON.stringify(payload) });
  },

  mcpEnableServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/enable`, { method: "POST" });
  },

  mcpDisableServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/disable`, { method: "POST" });
  },

  mcpConnectServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/connect`, { method: "POST" });
  },

  mcpDisconnectServer(serverId: string): Promise<{ server: McpServerPublic }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/disconnect`, {
      method: "POST",
    });
  },

  mcpRefreshTools(serverId: string): Promise<{ tools: McpToolRecord[] }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}/refresh-tools`, {
      method: "POST",
    });
  },

  mcpDeleteServer(serverId: string): Promise<{ ok: boolean }> {
    return request(`/api/mcp/servers/${encodeURIComponent(serverId)}`, { method: "DELETE" });
  },

  mcpTools(serverId?: string): Promise<{ tools: McpToolRecord[] }> {
    const q = serverId ? `?server_id=${encodeURIComponent(serverId)}` : "";
    return request(`/api/mcp/tools${q}`);
  },

  mcpCalls(limit = 100): Promise<{ calls: McpCallRecord[] }> {
    return request(`/api/mcp/calls?limit=${encodeURIComponent(String(limit))}`);
  },

  mcpCall(payload: {
    capability_id: string;
    arguments?: Record<string, unknown>;
    approval_id?: string;
    approved_by_user?: boolean;
  }): Promise<{ result: unknown; truth: Record<string, boolean> }> {
    return request("/api/mcp/call", { method: "POST", body: JSON.stringify(payload) });
  },

  /* ---------- Market Simulation ---------- */

  marketSimStatus(): Promise<MarketSimStatusResponse> {
    return request("/api/market-sim/status");
  },

  listMarketData(limit = 200): Promise<{ sources: MarketDataSource[] }> {
    return request(`/api/market-sim/data?limit=${encodeURIComponent(String(limit))}`);
  },

  scanMarketData(): Promise<{ sources: MarketDataSource[] }> {
    return request("/api/market-sim/data/scan", { method: "POST" });
  },

  registerMarketData(payload: {
    path: string;
    symbol?: string;
    timeframe?: string;
  }): Promise<{ source: MarketDataSource }> {
    return request("/api/market-sim/data/register", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listMarketStrategies(limit = 100): Promise<{ strategies: MarketStrategy[] }> {
    return request(`/api/market-sim/strategies?limit=${encodeURIComponent(String(limit))}`);
  },

  createMarketStrategy(payload: {
    name: string;
    description?: string;
    tags?: string[];
    parameters?: Record<string, unknown>;
    entryRules?: Record<string, unknown>;
    exitRules?: Record<string, unknown>;
    riskRules?: Record<string, unknown>;
    requiredTimeframes?: string[];
    brainDependencies?: string[];
  }): Promise<{ strategy: MarketStrategy; version: MarketStrategyVersion }> {
    return request("/api/market-sim/strategies", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getMarketStrategy(
    strategyId: string,
  ): Promise<{ strategy: MarketStrategy; versions: MarketStrategyVersion[] }> {
    return request(`/api/market-sim/strategies/${encodeURIComponent(strategyId)}`);
  },

  listMarketSimRuns(limit = 50): Promise<{ runs: MarketSimRun[] }> {
    return request(`/api/market-sim/runs?limit=${encodeURIComponent(String(limit))}`);
  },

  createMarketSimRun(payload: {
    sourceId: string;
    strategyId?: string;
    strategyVersion?: number;
    startTs?: string;
    endTs?: string;
    seed?: number;
    speed?: number;
    initialCash?: number;
    deliberationEveryN?: number;
    agents?: Array<Record<string, unknown>>;
    gameMode?: string;
    metadata?: Record<string, unknown>;
  }): Promise<{ run: MarketSimRun }> {
    return request("/api/market-sim/runs", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  startMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/start`, { method: "POST" });
  },

  pauseMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/pause`, { method: "POST" });
  },

  stepMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/step`, { method: "POST" });
  },

  stopMarketSimRun(runId: string): Promise<{ run: MarketSimRun }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/stop`, { method: "POST" });
  },

  getMarketSimLive(runId: string): Promise<MarketSimLiveState> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/live`);
  },

  getMarketSimResults(runId: string): Promise<MarketSimLiveState & { metrics: Record<string, unknown> }> {
    return request(`/api/market-sim/runs/${encodeURIComponent(runId)}/results`);
  },

  marketSimProviders(): Promise<{ providers: Array<Record<string, unknown>> }> {
    return request("/api/market-sim/providers");
  },

  marketSimImportProvider(payload: {
    providerId: string;
    symbol: string;
    timeframe?: string;
    limit?: number;
  }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/providers/import", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  marketSimCapabilities(): Promise<Record<string, unknown>> {
    return request("/api/market-sim/capabilities");
  },

  listPaperSessions(): Promise<{ sessions: Array<Record<string, unknown>> }> {
    return request("/api/market-sim/paper/sessions");
  },

  createPaperSession(payload: {
    symbol: string;
    strategyId?: string;
    strategyVersion?: number;
    brokerId?: string;
    providerId?: string;
    initialCash?: number;
  }): Promise<{ session: Record<string, unknown> }> {
    return request("/api/market-sim/paper/sessions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  getPaperSession(sessionId: string): Promise<{ session: Record<string, unknown> }> {
    return request(`/api/market-sim/paper/sessions/${encodeURIComponent(sessionId)}`);
  },

  placePaperOrder(
    sessionId: string,
    payload: { side: string; qty: number; clientOrderId?: string },
  ): Promise<Record<string, unknown>> {
    return request(`/api/market-sim/paper/sessions/${encodeURIComponent(sessionId)}/orders`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  paperKillSwitch(sessionId: string, armed = true): Promise<{ session: Record<string, unknown> }> {
    return request(
      `/api/market-sim/paper/sessions/${encodeURIComponent(sessionId)}/kill-switch?armed=${armed ? "true" : "false"}`,
      { method: "POST" },
    );
  },

  marketSimLiveTradingStatus(): Promise<Record<string, unknown>> {
    return request("/api/market-sim/live-trading");
  },

  runMarketDemo(payload: { family: string; barsLimit?: number }): Promise<Record<string, unknown>> {
    return request("/api/market-sim/demos/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  cognitionHealth(): Promise<{ cognition: CognitionHealth }> {
    return request("/api/cognition/health");
  },

  intelligenceHealth(): Promise<Record<string, unknown>> {
    return request("/api/intelligence/health");
  },

  cognitionSubmit(payload: {
    message: string;
    conversation_id?: string | null;
    history?: Array<{ role: string; content: string }>;
    has_knowledge?: boolean;
    shadow?: boolean | null;
    constraints?: string[];
    run?: boolean;
  }): Promise<CognitionRunStatus> {
    return request("/api/cognition/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  cognitionStatus(runId: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}`);
  },

  cognitionEvents(runId: string): Promise<{ run_id: string; events: unknown[] }> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/events`);
  },

  cognitionTrace(runId: string): Promise<{
    run_id: string;
    trace: Record<string, unknown>;
    truth?: Record<string, boolean>;
  }> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/trace`);
  },

  cognitionCancel(runId: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/cancel`, { method: "POST" });
  },

  cognitionSteer(runId: string, instruction: string): Promise<CognitionRunStatus> {
    return request(`/api/cognition/runs/${encodeURIComponent(runId)}/steer`, {
      method: "POST",
      body: JSON.stringify({ instruction }),
    });
  },

  getSettings(): Promise<SettingsSnapshot> {
    return request("/api/settings");
  },

  getSettingsCatalog(): Promise<Record<string, unknown>> {
    return request("/api/settings/catalog");
  },

  getSettingsCategory(category: string): Promise<{ category: string; settings: SettingState[] }> {
    return request(`/api/settings/categories/${encodeURIComponent(category)}`);
  },

  patchSettings(
    values: Record<string, unknown>,
    confirmDangerous = false,
  ): Promise<{ results: SettingMutationResult[]; settings: SettingState[] }> {
    return request("/api/settings", {
      method: "PATCH",
      body: JSON.stringify({ values, confirm_dangerous: confirmDangerous }),
    });
  },

  patchSetting(
    key: string,
    value: unknown,
    opts?: { confirmDangerous?: boolean; clearSecret?: boolean },
  ): Promise<{ result: SettingMutationResult; setting: SettingState }> {
    return request(`/api/settings/keys/${key.split("/").map(encodeURIComponent).join("/")}`, {
      method: "PATCH",
      body: JSON.stringify({
        value,
        confirm_dangerous: opts?.confirmDangerous ?? false,
        clear_secret: opts?.clearSecret ?? false,
      }),
    });
  },

  resetSetting(key: string): Promise<{ result: SettingMutationResult; setting: SettingState }> {
    return request(`/api/settings/reset/${key.split("/").map(encodeURIComponent).join("/")}`, {
      method: "POST",
    });
  },

  resetSettingsCategory(
    category: string,
  ): Promise<{ results: SettingMutationResult[]; settings: SettingState[] }> {
    return request(`/api/settings/reset-category/${encodeURIComponent(category)}`, {
      method: "POST",
    });
  },

  getBehaviorProfile(): Promise<{
    profile: Record<string, unknown>;
    truth?: Record<string, unknown>;
  }> {
    return request("/api/settings/behavior-profile");
  },

  putBehaviorSystemPrompt(systemPrompt: string): Promise<{
    profile: Record<string, unknown>;
    effective: Record<string, unknown>;
  }> {
    return request("/api/settings/behavior-profile/system-prompt", {
      method: "PUT",
      body: JSON.stringify({ system_prompt: systemPrompt }),
    });
  },

  resetBehaviorProfile(): Promise<{
    profile: Record<string, unknown>;
    effective: Record<string, unknown>;
  }> {
    return request("/api/settings/behavior-profile/reset", {
      method: "POST",
    });
  },

  brainGraph(opts?: {
    limit?: number;
    q?: string;
    types?: string;
    root?: string;
  }): Promise<{
    nodes: Array<{
      id: string;
      type: string;
      label: string;
      created_at?: string | null;
      meta?: Record<string, unknown>;
    }>;
    edges: Array<{ id: string; source: string; target: string; relation: string }>;
    stats: {
      node_count: number;
      edge_count: number;
      by_type?: Record<string, number>;
      by_relation?: Record<string, number>;
    };
    truth?: Record<string, boolean>;
  }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.q) params.set("q", opts.q);
    if (opts?.types) params.set("types", opts.types);
    if (opts?.root) params.set("root", opts.root);
    const q = params.toString();
    return request(`/api/brain/graph${q ? `?${q}` : ""}`);
  },

  brainStats(): Promise<{ stats: Record<string, unknown>; truth?: Record<string, boolean> }> {
    return request("/api/brain/stats");
  },

  /* ---------- Agent fleet ---------- */

  listAgents(opts?: {
    includeArchived?: boolean;
    kind?: string;
    includeSystem?: boolean;
  }): Promise<{
    agents: AgentDefinition[];
    summary: AgentFleetSummary;
    system?: SystemArchitectureEntry[];
    truth?: Record<string, boolean>;
  }> {
    const params = new URLSearchParams();
    if (opts?.includeArchived) params.set("includeArchived", "true");
    if (opts?.kind) params.set("kind", opts.kind);
    if (opts?.includeSystem === false) params.set("includeSystem", "false");
    const q = params.toString();
    return request(`/api/agents${q ? `?${q}` : ""}`);
  },

  listAgentRoster(opts?: {
    includeArchived?: boolean;
    includeArchitecture?: boolean;
    origin?: string;
    entityType?: string;
  }): Promise<{
    entries: AgentRosterEntry[];
    agents: AgentDefinition[];
    system: SystemArchitectureEntry[];
    summary: AgentFleetSummary;
    truth?: Record<string, boolean>;
  }> {
    const params = new URLSearchParams();
    if (opts?.includeArchived) params.set("includeArchived", "true");
    if (opts?.includeArchitecture === false) params.set("includeArchitecture", "false");
    if (opts?.origin) params.set("origin", opts.origin);
    if (opts?.entityType) params.set("entityType", opts.entityType);
    const q = params.toString();
    return request(`/api/agents/roster${q ? `?${q}` : ""}`);
  },

  listSystemAgents(): Promise<{
    system: SystemArchitectureEntry[];
    summary: AgentFleetSummary;
    truth?: Record<string, boolean>;
  }> {
    return request("/api/agents/system");
  },

  getAgentFleetSummary(): Promise<{ summary: AgentFleetSummary }> {
    return request("/api/agents/summary");
  },

  getDatasetLearningStatus(): Promise<DatasetLearningStatus> {
    return request("/api/agents/dataset-learning");
  },

  getAgent(agentId: string): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}`);
  },

  createAgent(payload: AgentCreatePayload): Promise<{ agent: AgentDefinition }> {
    return request("/api/agents", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateAgent(
    agentId: string,
    payload: Partial<AgentCreatePayload> & { enabled?: boolean },
  ): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  cloneAgent(agentId: string): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}/clone`, { method: "POST" });
  },

  enableAgent(agentId: string): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}/enable`, { method: "POST" });
  },

  disableAgent(agentId: string): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}/disable`, { method: "POST" });
  },

  archiveAgent(agentId: string): Promise<{ agent: AgentDefinition }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}/archive`, { method: "POST" });
  },

  launchAgentMission(
    agentId: string,
    payload: AgentMissionLaunchPayload,
  ): Promise<{ mission: AgentMission }> {
    return request(`/api/agents/${encodeURIComponent(agentId)}/missions`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  listAgentMissions(opts?: {
    agentId?: string;
    status?: string;
    limit?: number;
  }): Promise<{ missions: AgentMission[] }> {
    const params = new URLSearchParams();
    if (opts?.agentId) params.set("agentId", opts.agentId);
    if (opts?.status) params.set("status", opts.status);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/missions${q ? `?${q}` : ""}`);
  },

  getAgentMission(missionId: string): Promise<{
    mission: AgentMission;
    children: AgentMission[];
    events: AgentEvent[];
  }> {
    return request(`/api/agents/missions/${encodeURIComponent(missionId)}`);
  },

  cancelAgentMission(missionId: string): Promise<{ mission: AgentMission }> {
    return request(`/api/agents/missions/${encodeURIComponent(missionId)}/cancel`, {
      method: "POST",
    });
  },

  listAgentEvents(opts?: {
    agentId?: string;
    missionId?: string;
    category?: string;
    limit?: number;
  }): Promise<{ events: AgentEvent[] }> {
    const params = new URLSearchParams();
    if (opts?.agentId) params.set("agentId", opts.agentId);
    if (opts?.missionId) params.set("missionId", opts.missionId);
    if (opts?.category) params.set("category", opts.category);
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    const q = params.toString();
    return request(`/api/agents/events${q ? `?${q}` : ""}`);
  },

  reconcileAgents(): Promise<{ updated: string[]; count: number }> {
    return request("/api/agents/reconcile", { method: "POST" });
  },

  /* ---------- Analytics ---------- */

  analyticsOverview(rangeKey = "7d"): Promise<{ overview: AnalyticsOverview }> {
    return request(`/api/analytics/overview?rangeKey=${encodeURIComponent(rangeKey)}`);
  },

  analyticsAgents(rangeKey = "7d"): Promise<{ agents: AnalyticsAgentsResponse }> {
    return request(`/api/analytics/agents?rangeKey=${encodeURIComponent(rangeKey)}`);
  },

  analyticsTraining(rangeKey = "7d"): Promise<{ training: AnalyticsTrainingResponse }> {
    return request(`/api/analytics/training?rangeKey=${encodeURIComponent(rangeKey)}`);
  },

  analyticsDatasets(rangeKey = "7d"): Promise<{ datasets: AnalyticsDatasetsResponse }> {
    return request(`/api/analytics/datasets?rangeKey=${encodeURIComponent(rangeKey)}`);
  },

  analyticsTools(rangeKey = "7d"): Promise<{ tools: AnalyticsToolsResponse }> {
    return request(`/api/analytics/tools?rangeKey=${encodeURIComponent(rangeKey)}`);
  },

  /* ---------- Tasks / Taken ---------- */

  listTasks(filters?: TaskListFilters): Promise<{ tasks: TaskRecord[] }> {
    const params = new URLSearchParams();
    if (filters?.search) params.set("search", filters.search);
    if (filters?.boardColumn) params.set("boardColumn", filters.boardColumn);
    if (filters?.executionState) params.set("executionState", filters.executionState);
    if (filters?.priority) params.set("priority", filters.priority);
    if (filters?.assignee) params.set("assignee", filters.assignee);
    if (filters?.blocked != null) params.set("blocked", String(filters.blocked));
    if (filters?.overdue != null) params.set("overdue", String(filters.overdue));
    if (filters?.dueFrom) params.set("dueFrom", filters.dueFrom);
    if (filters?.dueTo) params.set("dueTo", filters.dueTo);
    if (filters?.project) params.set("project", filters.project);
    if (filters?.archived != null) params.set("archived", String(filters.archived));
    if (filters?.datePreset) params.set("datePreset", filters.datePreset);
    if (filters?.timezone) params.set("timezone", filters.timezone);
    if (filters?.limit != null) params.set("limit", String(filters.limit));
    if (filters?.offset != null) params.set("offset", String(filters.offset));
    const q = params.toString();
    return request<{ tasks: TaskRecord[] }>(`/api/tasks${q ? `?${q}` : ""}`);
  },

  getTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}`);
  },

  createTask(payload: TaskCreatePayload): Promise<{ task: TaskRecord }> {
    return request("/api/tasks", { method: "POST", body: JSON.stringify(payload) });
  },

  updateTask(taskId: string, payload: TaskPatchPayload): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
  },

  archiveTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/archive`, { method: "POST" });
  },

  duplicateTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/duplicate`, { method: "POST" });
  },

  startTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/start`, { method: "POST" });
  },

  cancelTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/cancel`, { method: "POST" });
  },

  retryTask(taskId: string): Promise<{ task: TaskRecord }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/retry`, { method: "POST" });
  },

  listTaskEvents(
    taskId: string,
    opts?: { limit?: number; offset?: number },
  ): Promise<{ events: TaskEvent[] }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    const q = params.toString();
    return request(`/api/tasks/${encodeURIComponent(taskId)}/events${q ? `?${q}` : ""}`);
  },

  listTaskSubtasks(taskId: string): Promise<{ subtasks: TaskSubtask[] }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/subtasks`);
  },

  createSubtask(taskId: string, title: string): Promise<{ subtask: TaskSubtask }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/subtasks`, {
      method: "POST",
      body: JSON.stringify({ title }),
    });
  },

  updateSubtask(
    taskId: string,
    subtaskId: string,
    payload: { title?: string; completed?: boolean; sortOrder?: number },
  ): Promise<{ subtask: TaskSubtask }> {
    return request(
      `/api/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}`,
      { method: "PATCH", body: JSON.stringify(payload) },
    );
  },

  deleteSubtask(taskId: string, subtaskId: string): Promise<{ ok: boolean }> {
    return request(
      `/api/tasks/${encodeURIComponent(taskId)}/subtasks/${encodeURIComponent(subtaskId)}`,
      { method: "DELETE" },
    );
  },

  listTaskNotes(taskId: string): Promise<{ notes: TaskNote[] }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/notes`);
  },

  createTaskNote(
    taskId: string,
    payload: { body: string; authorName?: string | null },
  ): Promise<{ note: TaskNote }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/notes`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  updateTaskNote(taskId: string, noteId: string, body: string): Promise<{ note: TaskNote }> {
    return request(
      `/api/tasks/${encodeURIComponent(taskId)}/notes/${encodeURIComponent(noteId)}`,
      { method: "PATCH", body: JSON.stringify({ body }) },
    );
  },

  deleteTaskNote(taskId: string, noteId: string): Promise<{ ok: boolean }> {
    return request(
      `/api/tasks/${encodeURIComponent(taskId)}/notes/${encodeURIComponent(noteId)}`,
      { method: "DELETE" },
    );
  },

  listTaskDependencies(taskId: string): Promise<{ dependencies: TaskDependency[] }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/dependencies`);
  },

  addTaskDependency(
    taskId: string,
    payload: { dependsOnTaskId: string; soft?: boolean },
  ): Promise<{ dependency: TaskDependency }> {
    return request(`/api/tasks/${encodeURIComponent(taskId)}/dependencies`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  removeTaskDependency(taskId: string, dependencyId: string): Promise<{ ok: boolean }> {
    return request(
      `/api/tasks/${encodeURIComponent(taskId)}/dependencies/${encodeURIComponent(dependencyId)}`,
      { method: "DELETE" },
    );
  },

  taskSummary(timezone?: string): Promise<{ summary: TaskSummary }> {
    const params = new URLSearchParams();
    if (timezone) params.set("timezone", timezone);
    const q = params.toString();
    return request(`/api/tasks/summary${q ? `?${q}` : ""}`);
  },

  taskActivity(opts?: { limit?: number; offset?: number }): Promise<{ activity: TaskEvent[] }> {
    const params = new URLSearchParams();
    if (opts?.limit != null) params.set("limit", String(opts.limit));
    if (opts?.offset != null) params.set("offset", String(opts.offset));
    const q = params.toString();
    return request(`/api/tasks/activity${q ? `?${q}` : ""}`);
  },

  taskTimeline(opts?: {
    view?: string;
    timezone?: string;
  }): Promise<{ timeline: TaskTimelineItem[]; view: string }> {
    const params = new URLSearchParams();
    if (opts?.view) params.set("view", opts.view);
    if (opts?.timezone) params.set("timezone", opts.timezone);
    const q = params.toString();
    return request(`/api/tasks/timeline${q ? `?${q}` : ""}`);
  },

  taskWorkload(): Promise<{ workload: TaskWorkloadEntry[] }> {
    return request("/api/tasks/workload");
  },

  taskWeekdayCompletions(timezone?: string): Promise<TaskWeekdayCompletions> {
    const params = new URLSearchParams();
    if (timezone) params.set("timezone", timezone);
    const q = params.toString();
    return request(`/api/tasks/weekday-completions${q ? `?${q}` : ""}`);
  },

  taskAgentActivity(limit = 20): Promise<{ agents: TaskAgentActivity[] }> {
    return request(`/api/tasks/agent-activity?limit=${encodeURIComponent(String(limit))}`);
  },

  quickCaptureTask(payload: TaskQuickCapturePayload): Promise<{ task: TaskRecord }> {
    return request("/api/tasks/quick-capture", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  previewTaskAutoPlan(payload: {
    brief: string;
    targetDate?: string | null;
    project?: string | null;
    priority?: string | null;
    allowedAgentIds?: string[];
  }): Promise<{ proposals: TaskAutoPlanProposal[] }> {
    return request("/api/tasks/auto-plan/preview", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  commitTaskAutoPlan(payload: {
    proposals: TaskAutoPlanProposal[];
    project?: string | null;
  }): Promise<{ tasks: TaskRecord[] }> {
    return request("/api/tasks/auto-plan/commit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
